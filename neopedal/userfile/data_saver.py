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
Background saving of data module files

Data modules (delta, fuel, sectors, stint) save their files (delta best, reference consumption, best
sectors, consumption history) once a lap is validated, at checkpoints and on reset: while driving. A write
flushes to disk and may wait for a file locked for a moment (antivirus, cloud sync), so it runs here on a
single saver thread and the module thread keeps producing data (delta bar, pace notes, fuel estimates).
Saves run one at a time in submission order: a later save of the same file always wins. A module stopping
saves synchronously (waits its turn, module control waits for the module), and quit or restart waits for
pending saves with wait_data_saver.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

logger = logging.getLogger(__name__)

DATA_SAVER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Data saver")
SYNC_SAVE_TIMEOUT = 5.0  # seconds a synchronous save (module stop) waits for its turn & its write

_lock = threading.Lock()
_pending = 0  # saves queued or running


def queue_save(saver: Callable[..., Any], *args: Any, sync: bool = False, **kwargs: Any) -> None:
    """Run saver(*args, **kwargs) on the data saver thread, after every save queued before

    Arguments must be immutable (tuples, numbers, strings): the module keeps updating its own data meanwhile.
    Errors of saver are logged (its own logging for OSError, see userfile.atomic_write).

    Args:
        sync: wait until saved (module stop: data read back when module restarts), bounded by
            SYNC_SAVE_TIMEOUT; a save still finishes in background if the wait times out.
    """
    global _pending
    with _lock:
        _pending += 1
    try:
        future = DATA_SAVER.submit(_run, saver, args, kwargs)
    except RuntimeError:  # interpreter shutting down: saved on this thread
        _run(saver, args, kwargs)
        return
    if sync:
        try:
            future.result(SYNC_SAVE_TIMEOUT)
        except FuturesTimeout:
            logger.warning("USERDATA: %s still saving in background", getattr(saver, "__name__", saver))


def _run(saver: Callable[..., Any], args: tuple, kwargs: dict) -> None:
    """Run one save, error logged (never left in a discarded future)"""
    global _pending
    try:
        saver(*args, **kwargs)
    except Exception:
        logger.exception("USERDATA: saving failed (%s)", getattr(saver, "__name__", saver))
    finally:
        with _lock:
            _pending -= 1


def pending_saves() -> int:
    """Number of saves queued or running"""
    return _pending


def wait_data_saver(timeout: float | None = None) -> bool:
    """Wait (up to timeout seconds) until every save queued so far is written, True if done in time

    Called before quit or restart (process exits without waiting threads), and by a stopping data module
    (module restarted by a reload reads its files back).
    """
    if not _pending:
        return True
    try:
        DATA_SAVER.submit(lambda: None).result(timeout)  # single worker: runs after every save queued before
    except FuturesTimeout:
        return False
    except RuntimeError:  # interpreter shutting down: saves run on their callers' threads
        return not _pending
    return True
