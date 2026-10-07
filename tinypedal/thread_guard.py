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
Thread supervisor
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from time import monotonic, sleep

from . import app_signal

logger = logging.getLogger(__name__)

STOP_TIMEOUT = 5.0  # seconds, wait for a thread to stop before giving up
HEALTHY_RUN = 60.0  # seconds, a crash after running this long starts a fresh restart budget


def wait_stopped(is_stopped: Callable[[], bool], name: str, timeout: float | None = None) -> bool:
    """Wait (bounded) until a thread reports stopped, so a stuck thread never hangs reload or quit

    Args:
        is_stopped: returns True once thread stopped.
        name: display name for log.
        timeout: maximum wait (seconds), default STOP_TIMEOUT.

    Returns:
        True if stopped within timeout, False if gave up (error logged).
    """
    return wait_all_stopped(((name, is_stopped, None),), timeout)


def wait_all_stopped(
    targets: Iterable[tuple[str, Callable[[], bool], Callable[[float], object] | None]],
    timeout: float | None = None,
) -> bool:
    """Wait (bounded) until every thread reports stopped, against one shared deadline

    Signal stop to every thread first, then wait them all here, so threads stop in parallel.

    Args:
        targets: (display name, is_stopped, wait) per thread. wait(seconds) blocks until
            thread stopped or seconds elapsed (Event.wait, Thread.join), None to poll is_stopped.
        timeout: maximum wait (seconds) for all threads, default STOP_TIMEOUT.

    Returns:
        True if all stopped within timeout, False if gave up on any (error logged for each).
    """
    if timeout is None:
        timeout = STOP_TIMEOUT
    deadline = monotonic() + timeout
    all_stopped = True
    for name, is_stopped, wait in targets:
        while not is_stopped():
            remaining = deadline - monotonic()
            if remaining <= 0:
                logger.error("ERROR: %s not stopped after %ss, continue anyway", name, timeout)
                all_stopped = False
                break
            if wait is None:
                sleep(min(remaining, 0.01))
            elif wait(remaining) and not is_stopped():
                sleep(min(remaining, 0.01))  # waited object done but state not yet set, never spin
    return all_stopped


def run_supervised(
    target: Callable[[], object],
    name: str,
    stop_event: threading.Event,
    max_restarts: int = 3,
    restart_delay: float = 1.0,
) -> bool:
    """Run target in current thread, restart it after unexpected error

    Args:
        target: loop function to run, returns when stop event is set.
        name: display name for log & notification.
        stop_event: stop event, restart is canceled once set.
        max_restarts: maximum restart attempts after error, budget reset after a healthy run.
        restart_delay: delay (seconds) before restart.

    Returns:
        True if target exited normally, False if stopped after errors.
    """
    attempt = 0
    while True:
        started = monotonic()
        try:
            target()
            return True
        except Exception:
            if monotonic() - started >= HEALTHY_RUN:
                attempt = 0  # sporadic error after a healthy run, not a crash loop
            logger.exception("ERROR: %s crashed (%s/%s)", name, attempt + 1, max_restarts + 1)
        if attempt >= max_restarts or stop_event.wait(restart_delay):
            break
        attempt += 1
        logger.warning("ERROR: restarting %s", name)
        app_signal.error.emit(f"{name} crashed and was restarted, see log for details.")
    if not stop_event.is_set():
        logger.error("ERROR: %s stopped after repeated errors", name)
        app_signal.error.emit(f"{name} stopped after repeated errors, see log for details.")
    return False
