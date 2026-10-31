#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
RestAPI module
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from collections.abc import Callable, Coroutine, Iterator
from contextlib import suppress
from functools import partial
from time import monotonic
from typing import Any, NamedTuple

from .. import realtime_state
from ..async_request import HttpConnection, forget_hostname, resolve_hostname_async, set_header_get
from ..const_common import TYPE_JSON
from ..game_rest_cache import rest_cache
from ..thread_guard import run_supervised, wait_all_stopped
from ..validator import check_json_nesting

logger = logging.getLogger(__name__)


class _CheckedDecoder(json.JSONDecoder):
    """JSON decoder refusing arrays & objects nested too deeply: RecursionError, as CPython up to 3.13 raised itself"""

    def decode(self, s: str, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        check_json_nesting(s)
        return super().decode(s, *args, **kwargs)


json_decoder = _CheckedDecoder()

MAX_UPDATE_INTERVAL = 5.0  # default maximum update interval while repeated resource data is unchanged
MISSING_RETRY_MAX = 10.0  # maximum delay between requests of resource without data (game answers null)
STOP_TIMEOUT = 3.0  # seconds to wait for update thread to stop
FAILURES_BEFORE_RESET = 3  # failed requests in a row of repeated resource before its values are reset to default
IDLE_WAIT = 5.0  # longest wait while not on track, woken earlier on activity change (realtime_state)
DEMAND_WAIT = 0.5  # seconds between checks of resource read only by overlays, while none of them runs
CACHE_PRUNE_INTERVAL = 30.0  # seconds between drops of stale shared game answers (game_rest_cache), also when idle


def prune_rest_cache(last: float) -> float:
    """Stale shared game answers dropped if CACHE_PRUNE_INTERVAL passed since last, returns time of last prune"""
    now = monotonic()
    if now - last < CACHE_PRUNE_INTERVAL:
        return last
    rest_cache.prune()
    return now


class HttpSetup(NamedTuple):
    """Http connection setup

    Attributes:
        host: url host.
        port: url port.
        timeout: timeout seconds.
        retry: number of retries.
        retry_delay: delay retry in seconds.
    """

    host: str
    port: int
    timeout: float
    retry: int
    retry_delay: float


class RestAPITask(NamedTuple):
    """RestAPI task

    Attributes:
        path: resource url path.
        outputs: resource data output set.
        condition: enable condition check.
        repeated: is repeated or one time task.
        interval: minimum update interval.
        max_interval: maximum update interval while data unchanged (repeated task).
        overlays: overlay names reading resource, requested only while one of them runs (realtime_state.overlays),
            any time if empty.
        pit_interval: minimum update interval while player in pit lane or garage (pit menu edited), if set.
        decoder: JSON decoder of answer text, json decode if None (see AppendedListDecoder).
    """

    path: str
    outputs: tuple[ResOutput, ...]
    condition: str
    repeated: bool
    interval: float
    max_interval: float = MAX_UPDATE_INTERVAL
    overlays: tuple[str, ...] = ()
    pit_interval: float = 0.0
    decoder: Callable[[str], Any] | None = None


class ResOutput(NamedTuple):
    """Resource data output

    Attributes:
        name: output data name.
        default: default value.
        parser: data parser function.
        keys: key sequence for fetch data from resource.
    """

    name: str
    default: Any
    parser: Callable[[Any, Any], Any]
    keys: tuple[str, ...] = ()

    def reset(self, output: object) -> None:
        """Reset data"""
        setattr(output, self.name, self.default)

    def update(self, output: object, data: Any) -> bool:
        """Update data"""
        for key in self.keys:  # get data from dict
            if not isinstance(data, dict):  # not exist, set to default
                setattr(output, self.name, self.default)
                return False
            data = data.get(key)
        # Not exist, set to default
        if data is None:
            setattr(output, self.name, self.default)
            return False
        # Parse and output
        setattr(output, self.name, self.parser(data, self.default))
        return True


class EndpointStatus(NamedTuple):
    """Rest API resource status, for performance monitor

    Attributes:
        path: resource url path.
        state: "idle" (not on track), "disabled" (option off), "waiting" (first request),
            "active" (data received), "missing" (no data yet, requested again), "dead" (stopped after error).
        error: last error ("timeout", "connection failed", "no answer", "invalid JSON", "no data",
            "parser error", "unexpected error"), empty if none.
        updated: monotonic time of last answer, 0 if never.
    """

    path: str
    state: str
    error: str = ""
    updated: float = 0.0


class AppendedListDecoder:
    """JSON array answer decoded incrementally: an answer made of the previous one with entries appended
    only decodes these entries (previous list kept, new list returned), other answers fully decoded

    Answers of a growing list (incidents) are long: full decode on every new entry is avoided.
    """

    __slots__ = ("_last",)

    def __init__(self) -> None:
        self._last: tuple[str, list] = ("", [])  # (answer text without closing bracket, decoded list), replaced at once

    def __call__(self, text: str) -> Any:
        prefix, items = self._last
        if prefix and len(text) > len(prefix) and text.startswith(prefix):
            tail = text[len(prefix):].lstrip()
            if tail.startswith(","):
                with suppress(ValueError, RecursionError):  # RecursionError: nested too deeply
                    added = json_decoder.decode(f"[{tail[1:]}")
                    if isinstance(added, list):
                        items = items + added
                        self._last = (text.rstrip()[:-1], items)
                        return items
        data = json_decoder.decode(text)
        if isinstance(data, list) and data:
            self._last = (text.rstrip()[:-1], data)
        else:
            self._last = ("", [])
        return data


def overlays_running(overlays: tuple[str, ...]) -> bool:
    """Whether resource read only by overlays is needed: one of them runs (any time if none given)"""
    return not overlays or not realtime_state.overlays.isdisjoint(overlays)


class RestError(Exception):
    """Resource unavailable, message is short reason (see EndpointStatus.error)"""


def valid_json_value(value: Any, default: Any) -> Any:
    """Validate JSON value against default value type, return default if invalid

    JSON has a single number type: int is accepted for float default (35 for 35.0),
    integral float for int default. Bool is never accepted as number.
    """
    if isinstance(default, bool) or not isinstance(default, (int, float)):
        return value if isinstance(value, type(default)) else default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if isinstance(default, float):
        try:
            value = float(value)
        except OverflowError:
            return default
        return value if math.isfinite(value) else default
    if isinstance(value, float):
        return int(value) if value.is_integer() else default
    return value


def retry_delay(attempt: int, retry: int, delay: float) -> float:
    """Delay before requesting again resource without data

    Configured number of retries at configured delay, then growing delay up to MISSING_RETRY_MAX,
    as game answers null for a while around session changes.
    """
    if attempt <= retry:
        return delay
    return min(max(delay, 1.0) * 2 ** min(attempt - retry, 8), MISSING_RETRY_MAX)


class TaskState:
    """Task cancel state, active tasks & wake (activity change or stop) of one update thread
    (a previous thread still stopping keeps its own)"""

    __slots__ = ("cancel", "active_tasks", "wake")

    def __init__(self) -> None:
        self.cancel = False
        self.active_tasks: dict[str, tuple[ResOutput, ...]] = {}
        self.wake = threading.Event()


class RestAPIConnector:
    """Rest API connector"""

    __slots__ = (
        "_taskset",
        "_dataset",
        "_cfg",
        "_updating",
        "_update_thread",
        "_active_interval",
        "_event",
        "_state",
        "_on_start",
        "_status",
        "_status_lock",
        "_warned",
        "_data_received",
        "_failures",
    )

    def __init__(self, taskset: tuple, dataset: object, on_start: Callable[[], None] | None = None):
        """
        Args:
            taskset: Rest API tasks.
            dataset: output data set.
            on_start: called before tasks start (player on track), to clear state kept between requests.
        """
        self._taskset = taskset
        self._dataset = dataset
        self._on_start = on_start

        self._cfg: dict = {}
        self._updating = False
        self._update_thread: threading.Thread | None = None
        self._active_interval = 0.2
        self._event = threading.Event()
        self._state = TaskState()
        self._status = {task.path: EndpointStatus(task.path, "idle") for task in taskset}
        self._status_lock = threading.Lock()
        self._warned: set[tuple[str, str]] = set()
        self._data_received = False
        self._failures: dict[str, int] = {}  # failed requests in a row of repeated resource

    def __del__(self) -> None:
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("RestAPI: GC: RestAPIConnector")

    def setConnection(self, config: dict) -> None:
        """Update connection config"""
        self._cfg = config
        self._active_interval = max(self._cfg["restapi_update_interval"], 100) / 1000

    def start(self) -> None:
        """Start update thread

        A previous thread still stopping (stop timed out) is not waited: it has its own stop event & task
        state (never resumes, never resets the new thread's data, see _reset_if_current).
        """
        if not self._updating and self._cfg["enable_restapi_access"]:
            self._updating = True
            # Own stop event & task state for each thread, so a previous thread still stopping never resumes
            self._event = threading.Event()
            self._state = TaskState()
            self._update_thread = threading.Thread(
                target=self.__update, args=(self._event, self._state), daemon=True, name="RestAPI")
            self._update_thread.start()
            logger.info("RestAPI: UPDATING: thread started")

    def stop(self) -> None:
        """Stop update thread, wait a bounded time (requests are cancelled within 0.1s)"""
        if self._updating:
            self.request_stop()
            self.wait_stopped()

    def request_stop(self) -> None:
        """Signal update thread to stop, returns at once: wait_stopped joins it

        Split so every API thread is signalled before any is waited (threads stop in parallel).
        """
        if self._updating:
            self._event.set()
            self._state.wake.set()

    def wait_stopped(self, timeout: float = STOP_TIMEOUT, deadline: float | None = None) -> bool:
        """Wait (bounded) for signalled update thread, returns True if it stopped

        Args:
            timeout: maximum wait (seconds), see thread_guard.wait_all_stopped.
            deadline: monotonic time to give up at instead (shared with other threads stopping).
        """
        if not self._updating:
            return True
        stopped = True
        self.request_stop()
        thread = self._update_thread
        if thread is not None:
            stopped = wait_all_stopped((("RestAPI", lambda: not thread.is_alive(), thread.join),), timeout, deadline)
            if not stopped:
                logger.warning("RestAPI: UPDATING: thread still stopping in background")
        self._updating = False
        logger.info("RestAPI: UPDATING: thread stopped")
        return stopped

    def status(self) -> tuple[EndpointStatus, ...]:
        """Status of every resource (any thread)"""
        with self._status_lock:
            return tuple(self._status.values())

    def _address(self) -> tuple[str, int] | None:
        """Configured host & port, key of answers shared with pages (game_rest_cache)"""
        try:
            return str(self._cfg["url_host"]), int(self._cfg["url_port"])
        except (KeyError, TypeError, ValueError):
            return None

    def _share(self, uri_path: str, raw_bytes: bytes) -> None:
        """Answer handed to other readers of resource (pages, tools)"""
        address = self._address()
        if raw_bytes and address is not None:
            rest_cache.store(uri_path, 200, raw_bytes, address)

    def _set_status(self, path: str, state: str, error: str | None = None, updated: bool = False) -> None:
        """Set resource status, keep last error & update time unless given"""
        with self._status_lock:
            old = self._status.get(path, EndpointStatus(path, state))
            self._status[path] = EndpointStatus(
                path,
                state,
                old.error if error is None else error,
                monotonic() if updated else old.updated,
            )

    def _reset_status(self, state: str) -> None:
        """Set every resource status"""
        with self._status_lock:
            for path, old in self._status.items():
                self._status[path] = old._replace(state=state)

    def _warn_once(self, key: tuple[str, str], message: str, *args: object, exc_info: bool = False) -> None:
        """Log warning once per connector (key: resource path, cause)"""
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message, *args, exc_info=exc_info)

    def __update(self, event: threading.Event, state: TaskState) -> None:
        """Run update loop, restart after unexpected error"""
        realtime_state.subscribe(state.wake)
        try:
            if (
                not run_supervised(lambda: self.__update_loop(event, state), "RestAPI update", event)
                and not event.is_set()
            ):
                # Stopped after repeated errors: no stale value left behind
                reset_to_default(self._dataset, state.active_tasks)
                self._reset_status("dead")
        finally:
            realtime_state.unsubscribe(state.wake)

    def __update_loop(self, event: threading.Event, state: TaskState) -> None:
        """Update Rest API data

        Not on track: waits for activity change (woken by realtime_state, or stop), at most IDLE_WAIT,
        instead of checking active state every 0.5s.
        """
        _event_wait = event.wait
        _wait_change = realtime_state.wait_change
        reset = False
        pruned = monotonic()

        while not event.is_set():
            pruned = prune_rest_cache(pruned)
            if realtime_state.active:

                # Also check task cancel state in case delay
                if not reset or state.cancel:
                    reset = True
                    state.cancel = False
                    self.run_tasks(event, state)
                _event_wait(self._active_interval)

            else:
                reset = False
                _wait_change(IDLE_WAIT, state.wake)

        # Reset to default on close
        self._reset_if_current(event, state)

    def run_tasks(self, event: threading.Event, state: TaskState) -> None:
        """Run tasks, blocks until leaving track or stopped"""
        logger.info("RestAPI: CONNECTING")
        if self._on_start is not None:
            self._on_start()
        self._data_received = False
        self._failures.clear()
        asyncio.run(self.task_init(event, state))
        logger.info("RestAPI: all tasks stopped")
        if not self._data_received:  # nothing answered: resolve host again next time
            forget_hostname(self._cfg["url_host"], self._cfg["url_port"])
        # Reset when finished
        self._reset_if_current(event, state)

    def _reset_if_current(self, event: threading.Event, state: TaskState) -> None:
        """Reset data & status to idle, unless a newer thread took over (stop timed out, then start)

        Data set & status are shared: a thread finishing late must not wipe what the new one fetched.
        """
        if event is not self._event:
            state.active_tasks.clear()
            return
        reset_to_default(self._dataset, state.active_tasks)
        self._reset_status("idle")

    def sort_taskset(
        self, http: HttpSetup, state: TaskState, taskset: tuple[RestAPITask, ...],
    ) -> Iterator[asyncio.Task]:
        """Sort task set into dictionary, key - uri_path, value - output_set"""
        for task in taskset:
            if self._cfg.get(task.condition, True):
                state.active_tasks[task.path] = task.outputs
                self._set_status(task.path, "waiting", "")
                update_interval = max(task.interval, self._active_interval)
                yield asyncio.create_task(self.fetch(http, task, state, update_interval))
            else:
                self._set_status(task.path, "disabled", "")

    async def task_init(self, event: threading.Event, state: TaskState) -> None:
        """Resolve host, then run tasks until leaving track or stopped"""
        cfg = self._cfg
        # Resolving probes connections for up to 3s: cancelled at once on stop
        host = await self.until_stopped(event, resolve_hostname_async(cfg["url_host"], cfg["url_port"]))
        if host is None:  # cancelled (stopped or brief leave of track): run again while on track
            state.cancel = True
            return
        sim_http = HttpSetup(
            host=host,
            port=cfg["url_port"],
            timeout=min(max(cfg["connection_timeout"], 0.5), 10),
            retry=min(max(int(cfg["connection_retry"]), 0), 10),
            retry_delay=min(max(cfg["connection_retry_delay"], 0), 60),
        )
        task_group = tuple(self.sort_taskset(sim_http, state, self._taskset))
        logger.info("RestAPI: all tasks started")
        # Task control
        await asyncio.create_task(self.task_control(event, state, task_group))
        # Collect tasks (unexpected errors are logged by each task)
        for task in task_group:
            with suppress(asyncio.CancelledError):
                await task

    async def until_stopped(self, event: threading.Event, coroutine: Coroutine) -> Any:
        """Result of coroutine, None if cancelled because stopped or leaving track"""
        task = asyncio.ensure_future(coroutine)
        while not task.done():
            if event.is_set() or not realtime_state.active:
                task.cancel()
                break
            await asyncio.wait((task,), timeout=0.1)
        try:
            return await task
        except asyncio.CancelledError:
            return None

    async def task_control(self, event: threading.Event, state: TaskState, task_group: tuple[asyncio.Task, ...]) -> None:
        """Control task running state"""
        _event_is_set = event.is_set
        pruned = monotonic()
        while not _event_is_set() and realtime_state.active:
            await asyncio.sleep(0.1)  # check every 100ms
            pruned = prune_rest_cache(pruned)
        # Set cancel state to exit loop in case failed to cancel
        state.cancel = True
        # Cancel all running tasks
        for task in task_group:
            task.cancel()

    async def fetch(self, http: HttpSetup, task: RestAPITask, state: TaskState, min_interval: float = 0.01) -> None:
        """Fetch data until available, then keep updating if repeated task"""
        uri_path = task.path
        connection = HttpConnection(http.host, http.port, http.timeout)
        request = set_header_get(uri_path, http.host)
        try:
            if not await self.until_overlays_running(uri_path, task.overlays, state):
                return
            if not await self.update_until_available(connection, request, http, uri_path, task.outputs, state):
                return
            if not task.repeated:
                logger.info("RestAPI: ACTIVE: %s (one time)", uri_path)
                return
            logger.info("RestAPI: ACTIVE: %s (%sms)", uri_path, int(min_interval * 1000))
            await self.update_repeat(
                connection, request, uri_path, task.outputs, state,
                min_interval, max(task.max_interval, min_interval), overlays=task.overlays,
                pit_interval=max(task.pit_interval, self._active_interval) if task.pit_interval > 0 else 0.0,
                decoder=task.decoder)
        except asyncio.CancelledError:
            raise
        except Exception:  # never hide unexpected error, other tasks keep running
            self._set_status(uri_path, "dead", "unexpected error")
            self._warn_once((uri_path, "task"), "RestAPI: task stopped after error: %s", uri_path, exc_info=True)
        finally:
            connection.close()

    async def until_overlays_running(self, uri_path: str, overlays: tuple[str, ...], state: TaskState) -> bool:
        """Wait until an overlay reading resource runs (see RestAPITask.overlays), False if cancelled"""
        if overlays_running(overlays):
            return True
        self._set_status(uri_path, "idle", "")
        while not state.cancel:
            await asyncio.sleep(DEMAND_WAIT)
            if overlays_running(overlays):
                self._set_status(uri_path, "waiting", "")
                return True
        return False

    async def update_until_available(
        self, connection: HttpConnection, request: bytes, http: HttpSetup, uri_path: str,
        output_set: tuple[ResOutput, ...], state: TaskState) -> bool:
        """Request resource until data available (game answers null around session changes)"""
        attempt = 0
        while not state.cancel:
            if await self.update_once(connection, request, uri_path, output_set):
                return True
            if attempt == 0:
                logger.info("RestAPI: MISSING: %s, requesting again", uri_path)
            attempt += 1
            await asyncio.sleep(retry_delay(attempt, http.retry, http.retry_delay))
        return False

    async def update_once(
        self, connection: HttpConnection, request: bytes, uri_path: str, output_set: tuple[ResOutput, ...]) -> bool:
        """Update once, returns True if data available"""
        try:
            resource_output = await get_resource(request, connection, partial(self._share, uri_path))
        except RestError as error:
            self._set_status(uri_path, "missing", str(error))
            return False
        self._data_received = True
        if self.apply_outputs(uri_path, output_set, resource_output):
            self._set_status(uri_path, "active", updated=True)
            return True
        self._set_status(uri_path, "missing", "no data", updated=True)
        return False

    async def update_repeat(
        self, connection: HttpConnection, request: bytes, uri_path: str, output_set: tuple[ResOutput, ...],
        state: TaskState, min_interval: float, max_interval: float = MAX_UPDATE_INTERVAL, *,
        overlays: tuple[str, ...] = (), pit_interval: float = 0.0,
        decoder: Callable[[str], Any] | None = None) -> None:
        """Update repeat

        Args:
            overlays: resource requested only while one of these overlays runs, values reset to default
                once none runs (see RestAPITask).
            pit_interval: minimum interval while player in pit lane or garage, if set.
            decoder: answer decoder (see RestAPITask).
        """
        interval = min_interval
        last_hash = new_hash = -1
        while not state.cancel:  # use task control to cancel & exit loop
            if overlays and not overlays_running(overlays):
                if last_hash != -1:  # no stale value shown once an overlay runs again
                    last_hash = -1
                    for res in output_set:
                        res.reset(self._dataset)
                    self._set_status(uri_path, "idle", "")
                await asyncio.sleep(DEMAND_WAIT)
                continue
            fastest = pit_interval if 0 < pit_interval < min_interval and realtime_state.in_pits else min_interval
            new_hash = await self.output_resource(
                connection, request, uri_path, output_set, last_hash, fastest / 2, decoder)
            if last_hash != new_hash:
                last_hash = new_hash
                interval = fastest
            elif interval < max_interval:  # increase update interval while no new data
                interval += interval / 2
                if interval > max_interval:
                    interval = max_interval
            await asyncio.sleep(interval)

    async def output_resource(
        self, connection: HttpConnection, request: bytes, uri_path: str, output_set: tuple[ResOutput, ...],
        last_hash: int, shared_age: float = 0.0, decoder: Callable[[str], Any] | None = None) -> int:
        """Get resource from REST API and output data, skip unnecessary checking

        Answer read by a page or tool less than shared_age seconds ago used instead of asking again.
        Answer decoded by decoder (json decode if None) only if changed.
        """
        address = self._address()
        shared = rest_cache.fresh(uri_path, shared_age, address) if shared_age > 0 and address else None
        if shared is not None and shared.ok:
            raw_bytes = shared.body
        else:
            try:
                raw_bytes = await connection.get(request)
            except (TimeoutError, OSError, EOFError, ValueError) as error:
                return self.request_failed(uri_path, output_set, last_hash, request_error(error))
            self._share(uri_path, raw_bytes)
        new_hash = hash(raw_bytes)
        if last_hash != new_hash:
            try:
                resource_output = (json_decoder.decode if decoder is None else decoder)(raw_bytes.decode())
            except (ValueError, RecursionError):  # RecursionError: nested too deeply
                return self.request_failed(
                    uri_path, output_set, last_hash, "invalid JSON" if raw_bytes else "no answer")
            self.apply_outputs(uri_path, output_set, resource_output)
        self._failures.pop(uri_path, None)
        self._set_status(uri_path, "active", updated=True)
        return new_hash

    def request_failed(self, uri_path: str, output_set: tuple[ResOutput, ...], last_hash: int, reason: str) -> int:
        """Failed request of repeated resource: values kept on a transient error, reset to default after
        a few failures in a row (no stale repair or pit estimate), returns hash of applied answer"""
        self._set_status(uri_path, "active", reason)
        failures = self._failures.get(uri_path, 0) + 1
        self._failures[uri_path] = failures
        if failures < FAILURES_BEFORE_RESET:
            return last_hash
        if failures == FAILURES_BEFORE_RESET:
            for res in output_set:
                res.reset(self._dataset)
            logger.info("RestAPI: RESET: %s (%s requests failed)", uri_path, failures)
        return -1  # next answer applied again, also if same as before

    def apply_outputs(self, uri_path: str, output_set: tuple[ResOutput, ...], resource_output: Any) -> bool:
        """Parse resource into data set, returns True if any data available

        An entry the parser cannot read is set to default, other entries & next updates go on.
        """
        data_available = False
        for res in output_set:
            try:
                if res.update(self._dataset, resource_output):
                    data_available = True
            except Exception:  # unexpected game data must not stop updates
                res.reset(self._dataset)
                self._set_status(uri_path, "active", "parser error")
                self._warn_once(
                    (uri_path, res.name), "RestAPI: unable to parse %s from %s", res.name, uri_path, exc_info=True)
        return data_available


def reset_to_default(dataset: object, active_task: dict[str, tuple[ResOutput, ...]]) -> None:
    """Reset active task data to default"""
    if active_task:
        for uri_path, output_set in active_task.items():
            for res in output_set:
                res.reset(dataset)
            logger.info("RestAPI: RESET: %s", uri_path)
        active_task.clear()


def request_error(error: BaseException) -> str:
    """Short reason of failed request"""
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(error, ValueError):
        return "invalid answer"
    return "connection failed"


async def get_resource(request: bytes, connection: HttpConnection,
                       received: Callable[[bytes], Any] | None = None) -> Any:
    """Get JSON resource (dict or list) from REST API, received called with answer body

    Raises:
        RestError: unavailable (connection, error status, invalid JSON, null).
    """
    try:
        raw_bytes = await connection.get(request)
    except (TimeoutError, OSError, EOFError, ValueError) as error:
        raise RestError(request_error(error)) from error
    if not raw_bytes:
        raise RestError("no answer")  # error status or empty body
    if received is not None:
        received(raw_bytes)
    try:
        resource_output = json_decoder.decode(raw_bytes.decode())
    except (ValueError, RecursionError) as error:  # RecursionError: nested too deeply
        raise RestError("invalid JSON") from error
    if not isinstance(resource_output, TYPE_JSON):
        raise RestError("no data")  # null outside session
    return resource_output
