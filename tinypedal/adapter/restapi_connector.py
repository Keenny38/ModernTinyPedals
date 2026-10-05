#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
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
from collections.abc import Callable, Coroutine
from contextlib import suppress
from time import monotonic
from typing import Any, NamedTuple

from .. import realtime_state
from ..async_request import HttpConnection, forget_hostname, resolve_hostname_async, set_header_get
from ..const_common import TYPE_JSON
from ..thread_guard import run_supervised

logger = logging.getLogger(__name__)
json_decoder = json.JSONDecoder()

MAX_UPDATE_INTERVAL = 5.0  # default maximum update interval while repeated resource data is unchanged
MISSING_RETRY_MAX = 10.0  # maximum delay between requests of resource without data (game answers null)
STOP_TIMEOUT = 3.0  # seconds to wait for update thread to stop


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
    """

    path: str
    outputs: tuple[ResOutput, ...]
    condition: str
    repeated: bool
    interval: float
    max_interval: float = MAX_UPDATE_INTERVAL


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

    def reset(self, output: object):
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


class RestAPIConnector:
    """Rest API connector"""

    __slots__ = (
        "_taskset",
        "_dataset",
        "_cfg",
        "_task_cancel",
        "_updating",
        "_update_thread",
        "_active_interval",
        "_event",
        "_on_start",
        "_active_tasks",
        "_status",
        "_status_lock",
        "_warned",
        "_data_received",
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
        self._task_cancel = False
        self._updating = False
        self._update_thread: threading.Thread | None = None
        self._active_interval = 0.2
        self._event = threading.Event()
        self._active_tasks: dict[str, tuple[ResOutput, ...]] = {}
        self._status = {task.path: EndpointStatus(task.path, "idle") for task in taskset}
        self._status_lock = threading.Lock()
        self._warned: set[tuple[str, str]] = set()
        self._data_received = False

    def __del__(self):
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("RestAPI: GC: RestAPIConnector")

    def setConnection(self, config: dict):
        """Update connection config"""
        self._cfg = config
        self._active_interval = max(self._cfg["restapi_update_interval"], 100) / 1000

    def start(self):
        """Start update thread"""
        if not self._updating and self._cfg["enable_restapi_access"]:
            previous = self._update_thread
            if previous is not None and previous.is_alive():  # still stopping, see stop()
                previous.join(STOP_TIMEOUT)
            self._updating = True
            # Own stop event for each thread, so a previous thread still stopping never resumes
            self._event = threading.Event()
            self._update_thread = threading.Thread(
                target=self.__update, args=(self._event,), daemon=True, name="RestAPI")
            self._update_thread.start()
            logger.info("RestAPI: UPDATING: thread started")

    def stop(self):
        """Stop update thread, wait a bounded time (requests are cancelled within 0.1s)"""
        if self._updating:
            self._event.set()
            if self._update_thread is not None:
                self._update_thread.join(STOP_TIMEOUT)
                if self._update_thread.is_alive():
                    logger.warning("RestAPI: UPDATING: thread still stopping in background")
            self._updating = False
            logger.info("RestAPI: UPDATING: thread stopped")

    def status(self) -> tuple[EndpointStatus, ...]:
        """Status of every resource (any thread)"""
        with self._status_lock:
            return tuple(self._status.values())

    def _set_status(self, path: str, state: str, error: str | None = None, updated: bool = False):
        """Set resource status, keep last error & update time unless given"""
        with self._status_lock:
            old = self._status.get(path, EndpointStatus(path, state))
            self._status[path] = EndpointStatus(
                path,
                state,
                old.error if error is None else error,
                monotonic() if updated else old.updated,
            )

    def _reset_status(self, state: str):
        """Set every resource status"""
        with self._status_lock:
            for path, old in self._status.items():
                self._status[path] = old._replace(state=state)

    def _warn_once(self, key: tuple[str, str], message: str, *args, exc_info: bool = False):
        """Log warning once per connector (key: resource path, cause)"""
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message, *args, exc_info=exc_info)

    def __update(self, event: threading.Event) -> None:
        """Run update loop, restart after unexpected error"""
        if not run_supervised(lambda: self.__update_loop(event), "RestAPI update", event) and not event.is_set():
            # Stopped after repeated errors: no stale value left behind
            reset_to_default(self._dataset, self._active_tasks)
            self._reset_status("dead")

    def __update_loop(self, event: threading.Event) -> None:
        """Update Rest API data"""
        _event_wait = event.wait
        reset = False
        update_interval = 0.5

        while not _event_wait(update_interval):
            if realtime_state.active:

                # Also check task cancel state in case delay
                if not reset or self._task_cancel:
                    reset = True
                    update_interval = self._active_interval
                    self._task_cancel = False
                    self.run_tasks(event)

            else:
                if reset:
                    reset = False
                    update_interval = 0.5

        # Reset to default on close
        reset_to_default(self._dataset, self._active_tasks)
        self._reset_status("idle")

    def run_tasks(self, event: threading.Event):
        """Run tasks, blocks until leaving track or stopped"""
        logger.info("RestAPI: CONNECTING")
        if self._on_start is not None:
            self._on_start()
        self._data_received = False
        asyncio.run(self.task_init(event))
        logger.info("RestAPI: all tasks stopped")
        if not self._data_received:  # nothing answered: resolve host again next time
            forget_hostname(self._cfg["url_host"], self._cfg["url_port"])
        # Reset when finished
        reset_to_default(self._dataset, self._active_tasks)
        self._reset_status("idle")

    def sort_taskset(self, http: HttpSetup, active_task: dict, taskset: tuple[RestAPITask, ...]):
        """Sort task set into dictionary, key - uri_path, value - output_set"""
        for task in taskset:
            if self._cfg.get(task.condition, True):
                active_task[task.path] = task.outputs
                self._set_status(task.path, "waiting", "")
                update_interval = max(task.interval, self._active_interval)
                yield asyncio.create_task(self.fetch(http, task, update_interval))
            else:
                self._set_status(task.path, "disabled", "")

    async def task_init(self, event: threading.Event):
        """Resolve host, then run tasks until leaving track or stopped"""
        cfg = self._cfg
        # Resolving probes connections for up to 3s: cancelled at once on stop
        host = await self.until_stopped(event, resolve_hostname_async(cfg["url_host"], cfg["url_port"]))
        if host is None:
            return
        sim_http = HttpSetup(
            host=host,
            port=cfg["url_port"],
            timeout=min(max(cfg["connection_timeout"], 0.5), 10),
            retry=min(max(int(cfg["connection_retry"]), 0), 10),
            retry_delay=min(max(cfg["connection_retry_delay"], 0), 60),
        )
        task_group = tuple(self.sort_taskset(sim_http, self._active_tasks, self._taskset))
        logger.info("RestAPI: all tasks started")
        # Task control
        await asyncio.create_task(self.task_control(event, task_group))
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

    async def task_control(self, event: threading.Event, task_group: tuple[asyncio.Task, ...]):
        """Control task running state"""
        _event_is_set = event.is_set
        while not _event_is_set() and realtime_state.active:
            await asyncio.sleep(0.1)  # check every 100ms
        # Set cancel state to exit loop in case failed to cancel
        self._task_cancel = True
        # Cancel all running tasks
        for task in task_group:
            task.cancel()

    async def fetch(self, http: HttpSetup, task: RestAPITask, min_interval: float = 0.01):
        """Fetch data until available, then keep updating if repeated task"""
        uri_path = task.path
        connection = HttpConnection(http.host, http.port, http.timeout)
        request = set_header_get(uri_path, http.host)
        try:
            if not await self.update_until_available(connection, request, http, uri_path, task.outputs):
                return
            if not task.repeated:
                logger.info("RestAPI: ACTIVE: %s (one time)", uri_path)
                return
            logger.info("RestAPI: ACTIVE: %s (%sms)", uri_path, int(min_interval * 1000))
            await self.update_repeat(
                connection, request, uri_path, task.outputs, min_interval, max(task.max_interval, min_interval))
        except asyncio.CancelledError:
            raise
        except Exception:  # never hide unexpected error, other tasks keep running
            self._set_status(uri_path, "dead", "unexpected error")
            self._warn_once((uri_path, "task"), "RestAPI: task stopped after error: %s", uri_path, exc_info=True)
        finally:
            connection.close()

    async def update_until_available(
        self, connection: HttpConnection, request: bytes, http: HttpSetup, uri_path: str,
        output_set: tuple[ResOutput, ...]) -> bool:
        """Request resource until data available (game answers null around session changes)"""
        attempt = 0
        while not self._task_cancel:
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
            resource_output = await get_resource(request, connection)
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
        min_interval: float, max_interval: float = MAX_UPDATE_INTERVAL):
        """Update repeat"""
        interval = min_interval
        last_hash = new_hash = -1
        while not self._task_cancel:  # use task control to cancel & exit loop
            new_hash = await self.output_resource(connection, request, uri_path, output_set, last_hash)
            if last_hash != new_hash:
                last_hash = new_hash
                interval = min_interval
            elif interval < max_interval:  # increase update interval while no new data
                interval += interval / 2
                if interval > max_interval:
                    interval = max_interval
            await asyncio.sleep(interval)

    async def output_resource(
        self, connection: HttpConnection, request: bytes, uri_path: str, output_set: tuple[ResOutput, ...],
        last_hash: int) -> int:
        """Get resource from REST API and output data, skip unnecessary checking"""
        try:
            raw_bytes = await connection.get(request)
        except (TimeoutError, OSError, EOFError, ValueError) as error:
            self._set_status(uri_path, "active", request_error(error))
            return last_hash
        new_hash = hash(raw_bytes)
        if last_hash != new_hash:
            try:
                resource_output = json_decoder.decode(raw_bytes.decode())
            except ValueError:
                self._set_status(uri_path, "active", "invalid JSON" if raw_bytes else "no answer")
                return last_hash
            self.apply_outputs(uri_path, output_set, resource_output)
        self._set_status(uri_path, "active", updated=True)
        return new_hash

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


def reset_to_default(dataset: object, active_task: dict[str, tuple[ResOutput, ...]]):
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


async def get_resource(request: bytes, connection: HttpConnection) -> Any:
    """Get JSON resource (dict or list) from REST API

    Raises:
        RestError: unavailable (connection, error status, invalid JSON, null).
    """
    try:
        raw_bytes = await connection.get(request)
    except (TimeoutError, OSError, EOFError, ValueError) as error:
        raise RestError(request_error(error)) from error
    if not raw_bytes:
        raise RestError("no answer")  # error status or empty body
    try:
        resource_output = json_decoder.decode(raw_bytes.decode())
    except ValueError as error:
        raise RestError("invalid JSON") from error
    if not isinstance(resource_output, TYPE_JSON):
        raise RestError("no data")  # null outside session
    return resource_output
