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
Safe mode: start after a crash at startup

A marker file is written in the config folder when starting, removed once the main window and
overlays are up (a few seconds after the event loop started) or when quitting. Marker found at
next start while the process that wrote it is gone: that start never finished (crash, killed),
so the user is asked whether to start in safe mode. A normal start finds no marker, nothing asked.

Safe mode (asked, or "--safe-mode" command line flag): plugin code not loaded, overlays (widgets
& VR overlay) not started, so settings can be fixed in the main window, then the app restarted
normally (restart never keeps safe mode).
"""

from __future__ import annotations

import logging
import os

import psutil

logger = logging.getLogger(__name__)

MARKER_FILE = "startup.marker"
SETTLE_MS = 5000  # main window & overlays up for this long: start finished
CLI_FLAG = "--safe-mode"


class SafeModeState:
    """Safe mode state

    Attributes:
        enabled: plugins not loaded, overlays not started.
        reason: "flag" (command line), "crash" (previous start did not finish), "" (normal start).
    """

    __slots__ = (
        "enabled",
        "reason",
    )

    def __init__(self):
        self.enabled = False
        self.reason = ""

    def enable(self, reason: str):
        self.enabled = True
        self.reason = reason
        logger.warning(
            "SAFE MODE: ON (%s), plugins not loaded, overlays not started; restart to start normally",
            "previous start did not finish" if reason == "crash" else "command line",
        )


state = SafeModeState()


def marker_path(config_path: str) -> str:
    return f"{config_path}{MARKER_FILE}"


def process_stamp(pid: int) -> str:
    """Process id & creation time, as written in marker"""
    return f"{pid},{psutil.Process(pid).create_time()}"


def write_marker(config_path: str):
    """Marker of a start under way (this process)"""
    try:
        with open(marker_path(config_path), "w", encoding="utf-8") as file:
            file.write(process_stamp(os.getpid()))
    except (OSError, psutil.Error) as error:
        logger.warning("SAFE MODE: unable to write startup marker: %s", error)


def clear_marker(config_path: str):
    """Start finished (or app quitting): marker removed"""
    try:
        os.remove(marker_path(config_path))
    except FileNotFoundError:
        pass
    except OSError as error:
        logger.warning("SAFE MODE: unable to remove startup marker: %s", error)


def unfinished_start(config_path: str) -> bool:
    """Previous start did not finish: marker left by a process no longer running

    Marker of a process still running (another instance starting) is not a crash.
    """
    try:
        with open(marker_path(config_path), encoding="utf-8") as file:
            stamp = file.readline().strip()
    except FileNotFoundError:
        return False
    except OSError:
        return True  # unreadable marker: left by a start that never finished
    try:
        pid = int(stamp.split(",")[0])
        if pid != os.getpid() and psutil.pid_exists(pid) and process_stamp(pid) == stamp:
            return False
    except (ValueError, psutil.Error):
        pass
    return True


def restart_arguments(arguments: list[str]) -> list[str]:
    """Command line arguments of a restart: safe mode flag left out (restart starts normally)"""
    return [argument for argument in arguments if argument != CLI_FLAG]
