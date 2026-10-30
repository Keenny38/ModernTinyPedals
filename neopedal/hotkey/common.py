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
Hotkey function
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Mapping
from itertools import chain

from ..const_app import PLATFORM
from .joystick import JOY_CODE_BASE, JoystickReader, joystick_reader
from .keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

KEY_DOWN = 0x8000  # GetAsyncKeyState most significant bit: key held down


def sort_key_codes(
    available_commands: Iterable[tuple[int, ...]],
    key_modifier: Mapping[str, int] = KEYMAP_MODIFIER,
) -> tuple[int, ...]:
    """Sort available key codes in order - modifiers > keys

    Every modifier is checked (also if no hotkey uses it), so modifiers must match exactly:
    'c' does not run with Ctrl+C, 'ctrl+a' does not run with Ctrl+Shift+A.
    """
    all_keys = set(chain(*(_keys for _keys in available_commands)))
    if not all_keys:
        return ()
    all_modifiers = set(key_modifier.values())
    keys_only = tuple(all_keys - all_modifiers)
    return tuple(key_modifier.values()) + keys_only


def format_hotkey_name(name: str, notset: str = "", delimiter: str = "+") -> str:
    """Format hotkey name for display"""
    return name.replace("_", " ").replace("+", delimiter).title() if name else notset


def modifier_priority(key: str) -> int:
    """Get modifier key priority - 0=ctrl, 1=shift, 2=alt"""
    if "ctrl" in key:
        return 0
    if "shift" in key:
        return 1
    if "alt" in key:
        return 2
    return 0


class KeyState:
    """'Get key state' function (called with a key code, 0 if not pressed): keyboard & mouse keys, game
    controller buttons

    Keyboard keys report held or pressed since the last call (short key tap seen). Controller buttons report
    the state sampled at the call; with latch_controller_buttons, a button tapped and released between two
    calls is reported once as well (hotkey thread, key capture). Controller devices are released with the object.
    """

    __slots__ = (
        "latch_controller_buttons",
        "_keyboard",
        "_joystick",
        "_modifiers",
    )

    def __init__(self, get_keyboard_state: Callable[[int], int], joystick: JoystickReader):
        self.latch_controller_buttons = False
        self._keyboard = get_keyboard_state
        self._joystick = joystick
        self._modifiers = frozenset(KEYMAP_MODIFIER.values())

    def __call__(self, key_code: int) -> int:
        if key_code >= JOY_CODE_BASE:
            return self._joystick.pressed(key_code, self.latch_controller_buttons)
        if key_code in self._modifiers:  # held only: a modifier released just before a key is not in combo
            return self._keyboard(key_code) & KEY_DOWN
        return self._keyboard(key_code)  # held or pressed since last check (short key tap)


def get_key_state_function() -> KeyState:
    """Platform specific 'get key state' function, keyboard & mouse keys, game controller buttons"""
    get_keyboard_state: Callable[[int], int]
    if PLATFORM.WINDOWS and sys.platform == "win32":  # platform check also read by type checker
        from ctypes import windll

        get_keyboard_state = windll.user32.GetAsyncKeyState
    else:
        get_keyboard_state = _get_key_state_linux
    return KeyState(get_keyboard_state, joystick_reader())


def refresh_keystate(get_key_state: Callable[[int], int]) -> None:
    """Refresh and clean up key state - Windows"""
    if PLATFORM.WINDOWS:
        _refresh_keystate_win(get_key_state)
    else:
        _refresh_keystate_linux(get_key_state)


def validate_hotkey(
    key_string: str,
    key_general: Mapping[str, int] = KEYMAP_GENERAL,
    key_modifier: Mapping[str, int] = KEYMAP_MODIFIER,
    delimiter: str = "+",
) -> str:
    """Validate hotkey from string - ex. 'ctrl+alt+space' is valid

    Modifiers sorted in key_modifier order (same as detected key combo), duplicates removed.
    """
    if not key_string:
        return key_string
    *modifiers, key = key_string.split(delimiter)
    if key not in key_general:  # get general key (invalid if not found)
        return ""
    return "+".join((*sort_modifiers(modifiers, key_modifier), key))


def load_hotkey(
    key_string: str,
    key_general: Mapping[str, int] = KEYMAP_GENERAL,
    key_modifier: Mapping[str, int] = KEYMAP_MODIFIER,
    delimiter: str = "+",
) -> tuple[int, ...]:
    """Load hotkey string and export as key code sequence

    Modifiers sorted in key_modifier order (same as detected key combo), duplicates removed.
    """
    if not key_string:
        return ()
    *modifiers, key = key_string.split(delimiter)
    code = key_general.get(key)
    if code is None:  # invalid combo
        return ()
    return (*(key_modifier[_mod] for _mod in sort_modifiers(modifiers, key_modifier)), code)


def sort_modifiers(modifiers: Iterable[str], key_modifier: Mapping[str, int] = KEYMAP_MODIFIER) -> list[str]:
    """Valid modifier names in key_modifier order, without duplicates (invalid names dropped)"""
    names = set(modifiers)
    return [_mod for _mod in key_modifier if _mod in names]


def set_hotkey(
    get_key_state: Callable[[int], int],
    key_general: Mapping[str, int] = KEYMAP_GENERAL,
    key_modifier: Mapping[str, int] = KEYMAP_MODIFIER,
) -> tuple[str, ...]:
    """Set hotkey string from pressed keys (modifiers & one key, mouse or game controller button)"""
    key_combo = [""] * 4  # Ctrl, Alt, Shift, Key
    # Key state: 0=off, 1=pressed, <1=down
    # Assign mod key
    for key, code in key_modifier.items():
        priority = modifier_priority(key)
        if get_key_state(code) != 0:
            key_combo[priority] = key
        else:  # remove if not pressed
            key_combo[priority] = ""
    # Assign common key
    for key, code in key_general.items():
        if get_key_state(code) != 0:
            key_combo[-1] = key
            return tuple(key_combo)
    return ()


def held_modifiers(
    get_key_state: Callable[[int], int],
    key_modifier: Mapping[str, int] = KEYMAP_MODIFIER,
) -> list[str]:
    """Names of modifiers held down, in key_modifier order"""
    return [_mod for _mod, _code in key_modifier.items() if get_key_state(_code)]


def held_controller_buttons(
    get_key_state: Callable[[int], int],
    key_general: Mapping[str, int] = KEYMAP_GENERAL,
) -> set[int]:
    """Key codes of game controller buttons held down (button box switch or rotary held in a position)"""
    return {_code for _code in key_general.values() if _code >= JOY_CODE_BASE and get_key_state(_code)}


# Private
def _get_key_state_linux(key_code: int) -> int:
    """Get key state - Linux (placeholder)"""
    return 0


def _refresh_keystate_win(get_key_state: Callable[[int], int]) -> None:
    """Refresh and clean up key state - Windows"""
    for idx in range(255):
        get_key_state(idx)


def _refresh_keystate_linux(get_key_state: Callable[[int], int]) -> None:
    """Refresh and clean up key state - Linux (placeholder)"""
