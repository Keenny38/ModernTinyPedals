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
Bug report: collect logs, settings & system info into one zip file

Personal data is removed: user home folder in paths, access codes, repository names.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import zipfile
from time import localtime, strftime

from . import version_check
from .const_app import APP_NAME
from .const_file import LogFile
from .log_handler import ERROR_LOG_FILE
from .setting import cfg

logger = logging.getLogger(__name__)

SECRET_KEYS = ("access_code", "update_repository")
MAX_LOG_SIZE = 5 * 1024 * 1024


def redact_text(text: str) -> str:
    """Remove user home folder from text"""
    home = os.path.expanduser("~")
    if len(home) > 3:
        for variant in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
            text = text.replace(variant, "~")
    return text


def redact_setting(data):
    """Copy of setting with secret values removed"""
    if isinstance(data, dict):
        return {
            key: ("<removed>" if key in SECRET_KEYS and value else redact_setting(value))
            for key, value in data.items()
        }
    if isinstance(data, str):
        return redact_text(data)
    return data


def system_info() -> str:
    """Versions & platform info"""
    lines = [
        f"{APP_NAME}: {version_check.tinypedal()}",
        f"Python: {version_check.python()}",
        f"Qt: {version_check.qt()}",
        f"PySide: {version_check.pyside()}",
        f"psutil: {version_check.psutil()}",
        f"OS: {platform.platform()}",
        f"Machine: {platform.machine()}",
        f"Frozen: {getattr(sys, 'frozen', False)}",
        f"Loaded preset: {cfg.filename.setting}",
        f"API: {cfg.api_name if cfg.user.setting else '-'}",
    ]
    try:
        from PySide6.QtWidgets import QApplication

        for screen in QApplication.screens():
            geometry = screen.geometry()
            lines.append(
                f"Screen: {screen.name()} {geometry.width()}x{geometry.height()} "
                f"scale {screen.devicePixelRatio():g}"
            )
    except Exception:  # no GUI, report must still be generated
        logger.debug("BUG REPORT: screen info unavailable", exc_info=True)
    try:
        from .module_control import mctrl, wctrl

        lines.append(f"Active widgets: {', '.join(sorted(wctrl.active_modules)) or '-'}")
        lines.append(f"Active modules: {', '.join(sorted(mctrl.active_modules)) or '-'}")
    except Exception:  # module control not loaded, report must still be generated
        logger.debug("BUG REPORT: module info unavailable", exc_info=True)
    return redact_text("\n".join(lines)) + "\n"


def read_log(path: str) -> str:
    """Read log file tail (limited size)"""
    with open(path, "rb") as file:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(max(size - MAX_LOG_SIZE, 0))
        return redact_text(file.read().decode("utf-8", errors="replace"))


def create_bug_report(zip_filename: str, session_log: str = "", description: str = "") -> list[str]:
    """Create bug report zip, returns added file names"""
    added: list[str] = []
    config_path = cfg.path.config
    with zipfile.ZipFile(zip_filename, "w", compression=zipfile.ZIP_DEFLATED) as package:

        def add_text(name: str, text: str):
            package.writestr(name, text)
            added.append(name)

        add_text("system-info.txt", system_info())
        if description.strip():
            add_text("description.txt", description.strip() + "\n")
        if session_log:
            add_text("logs/session.log", redact_text(session_log))
        for log_name in os.listdir(config_path) if os.path.isdir(config_path) else ():
            if log_name.startswith((LogFile.APP_LOG, ERROR_LOG_FILE)):
                try:
                    add_text(f"logs/{log_name}", read_log(os.path.join(config_path, log_name)))
                except OSError as error:
                    logger.warning("BUG REPORT: unable to read %s: %s", log_name, error)
        settings = {
            "config.json": cfg.user.config,
            "shortcuts.json": cfg.user.shortcuts,
            f"preset/{cfg.filename.setting}": cfg.user.setting,
        }
        for name, data in settings.items():
            try:
                add_text(f"settings/{name}", json.dumps(redact_setting(dict(data)), indent=4, default=str))
            except (AttributeError, TypeError, ValueError) as error:
                logger.warning("BUG REPORT: unable to add %s: %s", name, error)
    logger.info("BUG REPORT: created %s (%s files)", zip_filename, len(added))
    return added


def default_report_filename() -> str:
    return f"tinypedal-bug-report-{strftime('%Y-%m-%d-%H%M%S', localtime())}.zip"
