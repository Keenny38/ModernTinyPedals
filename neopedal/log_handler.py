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
Log handler setup
"""

import logging
import sys
import threading
from collections import deque
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from time import monotonic

ERROR_LOG_FILE = "neopedal-errors.log"
LOG_STREAM_MAX_CHARS = 2 * 1024 * 1024  # log kept in memory (log dialog, bug report)


class BoundedLogStream:
    """In-memory log text (StringIO-like), only the latest text kept (max_chars at most)

    Oldest lines are dropped once size limit reached, so log never grows for whole app lifetime.
    Use getvalue() to read log text, tell() changes whenever text is written.
    """

    def __init__(self, max_chars: int = LOG_STREAM_MAX_CHARS):
        self.max_chars = max(int(max_chars), 1)
        self._chunks: deque[str] = deque()
        self._size = 0  # characters kept
        self._written = 0  # characters ever written
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        """Add text, drop oldest text over size limit"""
        if not text:
            return 0
        with self._lock:
            self._chunks.append(text)
            self._size += len(text)
            self._written += len(text)
            while self._size > self.max_chars and len(self._chunks) > 1:
                self._size -= len(self._chunks.popleft())
            if self._size > self.max_chars:  # single text over limit: keep its end
                last = self._chunks[0][-self.max_chars:]
                self._chunks[0] = last
                self._size = len(last)
        return len(text)

    def flush(self) -> None:
        """Nothing to flush (stream handler API)"""

    def getvalue(self) -> str:
        """Log text kept"""
        with self._lock:
            return "".join(self._chunks)

    def tell(self) -> int:
        """Characters ever written (changes on new log text)"""
        return self._written

    def clear(self) -> None:
        """Remove all log text"""
        with self._lock:
            self._chunks.clear()
            self._size = 0

    def truncate(self, size: int | None = 0) -> int:
        """Remove all log text (StringIO compatible for size 0)"""
        self.clear()
        return 0

    def seek(self, offset: int, whence: int = 0) -> int:
        """No position to set (StringIO compatible), returns tell()"""
        return self._written

    def __iter__(self) -> Iterator[str]:
        """Lines of log text kept"""
        return iter(self.getvalue().splitlines(keepends=True))


class ErrorThrottle:
    """Error of a repeated path (each request, each frame) logged as warning with traceback once per
    interval, as debug in between: visible at default log level, never floods the log"""

    __slots__ = ("interval", "_last", "_lock")

    def __init__(self, interval: float = 60.0):
        self.interval = interval
        self._last: float | None = None
        self._lock = threading.Lock()

    def log(self, _logger: logging.Logger, msg: str, *args, exc_info=True) -> bool:
        """Log msg (call from except block for traceback)

        Returns:
            True if logged as warning.
        """
        now = monotonic()
        with self._lock:
            warn = self._last is None or now - self._last >= self.interval
            if warn:
                self._last = now
        _logger.log(logging.WARNING if warn else logging.DEBUG, msg, *args, exc_info=exc_info)
        return warn


def new_stream_handler(
    _logger: logging.Logger, stream, level: int = logging.INFO
) -> logging.StreamHandler:
    """Create new stream handler

    Args:
        _logger: logger instance.
        stream: stream object.
        level: minimum logging level.
    Returns:
        Stream handler.
    """
    format_console = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s: %(message)s", datefmt="%H:%M:%S"
    )
    _handler = logging.StreamHandler(stream)
    _handler.setFormatter(format_console)
    _handler.setLevel(level)
    _logger.addHandler(_handler)
    return _handler


def new_file_handler(
    _logger: logging.Logger,
    filepath: str,
    filename: str,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Handler:
    """Create new rotating file handler

    Args:
        _logger: logger instance.
        filepath: log file path.
        filename: log file name.
        level: minimum logging level.
        max_bytes: rotate file after reaching size (bytes).
        backup_count: number of rotated files to keep (filename.1, filename.2, ...).
    Returns:
        File handler.
    """
    format_file = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    _handler = RotatingFileHandler(
        f"{filepath}{filename}", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    _handler.setFormatter(format_file)
    _handler.setLevel(level)
    _logger.addHandler(_handler)
    return _handler


class ExceptionRepeats:
    """Count repeats of same uncaught exception (type, raising file & line): an overlay timer failing
    20-50 times per second would flood the rotating error log, and stutter overlays while writing it"""

    __slots__ = ("_counts",)
    MAX_KEYS = 1000

    def __init__(self):
        self._counts: dict[tuple, int] = {}

    def count(self, exc_type, exc_traceback) -> int:
        """Return repeat count if exception should be logged (1st, 10th, 100th, then every 1000th), else 0"""
        tb = exc_traceback
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        if tb is None:
            key: tuple = (exc_type, "", 0)
        else:
            key = (exc_type, tb.tb_frame.f_code.co_filename, tb.tb_lineno)
        counts = self._counts
        if key not in counts and len(counts) >= self.MAX_KEYS:
            counts.clear()
        count = counts.get(key, 0) + 1
        counts[key] = count
        if count in (1, 10, 100) or count % 1000 == 0:
            return count
        return 0


def repeat_suffix(count: int) -> str:
    """Repeat count text of log message, none for first time"""
    return f" (x{count})" if count > 1 else ""


def install_exception_hooks(_logger: logging.Logger) -> None:
    """Uncaught exceptions logged (error log file): windowed executable has no stderr, the default
    hooks (Qt slots & timers, threads) would lose them"""
    default_hook = sys.excepthook
    repeats = ExceptionRepeats()

    def log_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            default_hook(exc_type, exc_value, exc_traceback)
            return
        count = repeats.count(exc_type, exc_traceback)
        if count:
            _logger.critical(
                "Uncaught exception%s", repeat_suffix(count), exc_info=(exc_type, exc_value, exc_traceback)
            )

    def log_thread_exception(args):
        if args.exc_type is SystemExit:
            return
        count = repeats.count(args.exc_type, args.exc_traceback)
        if not count:
            return
        name = args.thread.name if args.thread is not None else "unknown"
        _logger.critical(
            "Uncaught exception in thread %s%s", name, repeat_suffix(count),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_exception
    threading.excepthook = log_thread_exception


def set_log_stream(_logger: logging.Logger, log_stream, level: int = logging.INFO) -> logging.Handler:
    """In-memory log (log dialog, bug report) attached first thing at start: messages of the instance lock &
    settings import are kept, while log files can only be opened once the config folder is final"""
    _logger.setLevel(level)
    return new_stream_handler(_logger, log_stream, level)


def set_logging_level(_logger: logging.Logger, filepath: str, filename: str, log_stream=None, log_level=1) -> None:
    """Set logging level

    Args:
        _logger: logger instance.
        filepath: log file path.
        log_stream: log stream object (None if attached already, see set_log_stream).
        log_level:
            0 = output only warning or error to console.
            1 = output all log to console.
            2 = output all log to both console & file.
    """
    _logger.setLevel(logging.INFO)
    if log_stream is not None:
        new_stream_handler(_logger, log_stream)
    # No console in windowed executable (stdout None): no console handler, it would fail on every record
    if sys.stdout is not None:
        if log_level >= 1:
            new_stream_handler(_logger, sys.stdout)
            _logger.info("LOGGING: output to console")
        else:
            new_stream_handler(_logger, sys.stdout, level=logging.WARNING)
    if log_level == 2:
        try:
            new_file_handler(_logger, filepath, filename)
            _logger.info("LOGGING: output to %s", filename)
        except OSError:
            _logger.warning("LOGGING: unable to create %s", filename)
    # Always keep warning & error (including thread crash traceback) in small rotating file
    try:
        new_file_handler(
            _logger, filepath, ERROR_LOG_FILE, level=logging.WARNING, max_bytes=1024 * 1024
        )
    except OSError:
        _logger.warning("LOGGING: unable to create %s", ERROR_LOG_FILE)
