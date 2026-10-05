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
Hotkey Control
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from itertools import chain

from . import app_signal
from .hotkey.command import (
    COMMANDS_GENERAL,
    COMMANDS_MODULE,
    COMMANDS_PRESET,
    COMMANDS_WIDGET,
)
from .hotkey.common import (
    get_key_state_function,
    load_hotkey,
    refresh_keystate,
    sort_key_codes,
)
from .setting import cfg
from .thread_guard import run_supervised, wait_stopped

logger = logging.getLogger(__name__)


def gather_command(commands: Iterable[tuple[str, Callable]]) -> dict[tuple[int, ...], list[tuple[str, Callable]]]:
    """Gather & validate hotkey commands"""
    key_group: dict[tuple[int, ...], list[tuple[str, Callable]]] = {}
    for hotkey_name, hotkey_func in commands:
        key_string = cfg.user.shortcuts[hotkey_name]["bind"]
        key_codes = load_hotkey(key_string)
        if key_codes:
            if key_codes not in key_group:
                key_group[key_codes] = []  # create hotkey group list
            key_group[key_codes].append((hotkey_name, hotkey_func))
    return key_group


class HotkeyControl:
    """Hotkey control"""

    __slots__ = (
        "_stopped",
        "_event",
    )

    def __init__(self):
        self._stopped = True
        self._event = threading.Event()

    def enable(self):
        """Enable hotkey control"""
        if self._stopped and cfg.application["enable_global_hotkey"]:
            self._stopped = False
            self._event.clear()
            threading.Thread(target=self.__updating, daemon=True, name="Hotkey control").start()
            logger.info("ENABLED: hotkey control")

    def disable(self):
        """Disable hotkey control, wait (bounded) until stopped"""
        self._event.set()
        wait_stopped(lambda: self._stopped, "hotkey control")

    def reload(self):
        """Reload"""
        self.disable()
        self.enable()

    def __updating(self):
        """Run update loop, always mark stopped (disable() waits for it)"""
        try:
            run_supervised(self.__update_loop, "hotkey control", self._event)
        finally:
            self._stopped = True

    def __update_loop(self):
        """Update hotkey state"""
        _event_wait = self._event.wait
        available_commands = gather_command(chain(COMMANDS_GENERAL, COMMANDS_PRESET, COMMANDS_MODULE, COMMANDS_WIDGET))
        available_key_codes = sort_key_codes(available_commands.keys())

        get_key_state = get_key_state_function()
        refresh_keystate(get_key_state)
        last_key_codes: tuple[int, ...] = ()

        while not _event_wait(0.2):
            # Close & disable if no commands
            if not available_commands:
                break
            # Run command once per key press: a key of combo not held at last check (key held down
            # or other key of a longer combo released does not repeat command)
            detected_key_codes = tuple(_key for _key in available_key_codes if get_key_state(_key))
            pressed = not set(detected_key_codes).issubset(last_key_codes)
            last_key_codes = detected_key_codes
            if pressed and detected_key_codes in available_commands:
                hotkey_group = available_commands[detected_key_codes]
                # Run command in main thread
                for hotkey_name, hotkey_func in hotkey_group:
                    app_signal.hotkey.emit(hotkey_func)
                    logger.info(
                        "HOTKEY: %s (command: %s)",
                        cfg.user.shortcuts[hotkey_name]["bind"],
                        hotkey_name,
                    )

        self._stopped = True
        logger.info("DISABLED: hotkey control")


kctrl = HotkeyControl()
