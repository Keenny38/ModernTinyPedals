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
Log handler setup
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

ERROR_LOG_FILE = "tinypedal-errors.log"


def new_stream_handler(_logger: logging.Logger, stream) -> logging.StreamHandler:
    """Create new stream handler

    Args:
        _logger: logger instance.
        stream: stream object.
    Returns:
        Stream handler.
    """
    format_console = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s: %(message)s", datefmt="%H:%M:%S"
    )
    _handler = logging.StreamHandler(stream)
    _handler.setFormatter(format_console)
    _handler.setLevel(logging.INFO)
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


def set_logging_level(_logger: logging.Logger, filepath: str, filename: str, log_stream=None, log_level=1) -> None:
    """Set logging level

    Args:
        _logger: logger instance.
        filepath: log file path.
        log_stream: log stream object.
        log_level:
            0 = output only warning or error to console.
            1 = output all log to console.
            2 = output all log to both console & file.
    """
    _logger.setLevel(logging.INFO)
    if log_stream is not None:
        new_stream_handler(_logger, log_stream)
    if log_level >= 1:
        new_stream_handler(_logger, sys.stdout)
        _logger.info("LOGGING: output to console")
    if log_level == 2:
        new_file_handler(_logger, filepath, filename)
        _logger.info("LOGGING: output to %s", filename)
    # Always keep warning & error (including thread crash traceback) in small rotating file
    try:
        new_file_handler(
            _logger, filepath, ERROR_LOG_FILE, level=logging.WARNING, max_bytes=1024 * 1024
        )
    except OSError:
        _logger.warning("LOGGING: unable to create %s", ERROR_LOG_FILE)
