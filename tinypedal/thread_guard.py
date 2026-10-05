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
from collections.abc import Callable
from time import monotonic, sleep

from . import app_signal

logger = logging.getLogger(__name__)

STOP_TIMEOUT = 5.0  # seconds, wait for a thread to stop before giving up


def wait_stopped(is_stopped: Callable[[], bool], name: str, timeout: float | None = None) -> bool:
    """Wait (bounded) until a thread reports stopped, so a stuck thread never hangs reload or quit

    Args:
        is_stopped: returns True once thread stopped.
        name: display name for log.
        timeout: maximum wait (seconds), default STOP_TIMEOUT.

    Returns:
        True if stopped within timeout, False if gave up (error logged).
    """
    if timeout is None:
        timeout = STOP_TIMEOUT
    deadline = monotonic() + timeout
    while not is_stopped():
        if monotonic() >= deadline:
            logger.error("ERROR: %s not stopped after %ss, continue anyway", name, timeout)
            return False
        sleep(0.01)
    return True


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
        max_restarts: maximum restart attempts after error.
        restart_delay: delay (seconds) before restart.

    Returns:
        True if target exited normally, False if stopped after errors.
    """
    for attempt in range(max_restarts + 1):
        try:
            target()
            return True
        except Exception:
            logger.exception("ERROR: %s crashed (%s/%s)", name, attempt + 1, max_restarts + 1)
        if attempt >= max_restarts or stop_event.wait(restart_delay):
            break
        logger.warning("ERROR: restarting %s", name)
        app_signal.error.emit(f"{name} crashed and was restarted, see log for details.")
    if not stop_event.is_set():
        logger.error("ERROR: %s stopped after repeated errors", name)
        app_signal.error.emit(f"{name} stopped after repeated errors, see log for details.")
    return False
