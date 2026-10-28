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
Game controller buttons (wheel, button box, joystick, gamepad) as hotkey keys

Each button has a key code above keyboard key codes (0-255):
JOY_CODE_BASE + device index * JOY_CODE_STRIDE + button index,
button index 0-31 for buttons, 32-35 for the directions of the first POV hat (d-pad).
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import time
from contextlib import suppress

from ..const_app import PLATFORM

logger = logging.getLogger(__name__)

JOY_MAX_DEVICES = 16  # winmm joystick ids
JOY_MAX_BUTTONS = 32  # winmm buttons per device
JOY_POV_DIRECTIONS = ("up", "right", "down", "left")
JOY_CODE_BASE = 1000
JOY_CODE_STRIDE = 64
JOY_REFRESH_INTERVAL = 0.05  # one device read for all its buttons checked in a same pass
JOY_RETRY_INTERVAL = 2.0  # absent device checked again (slow to check on Windows)


def joystick_code(device: int, button: int) -> int:
    """Key code of a device (0-based) button (0-based, 32+ POV directions)"""
    return JOY_CODE_BASE + device * JOY_CODE_STRIDE + button


def split_joystick_code(code: int) -> tuple[int, int]:
    """Device & button index of a key code (-1, -1 if no controller button)"""
    if code < JOY_CODE_BASE:
        return -1, -1
    device, button = divmod(code - JOY_CODE_BASE, JOY_CODE_STRIDE)
    if device >= JOY_MAX_DEVICES or button >= JOY_MAX_BUTTONS + len(JOY_POV_DIRECTIONS):
        return -1, -1
    return device, button


def joystick_keymap() -> dict[str, int]:
    """Key name & code of every controller button, ex. 'joy1_button_5', 'joy2_pov_up'"""
    keymap = {}
    for device in range(JOY_MAX_DEVICES):
        for button in range(JOY_MAX_BUTTONS):
            keymap[f"joy{device + 1}_button_{button + 1}"] = joystick_code(device, button)
        for index, direction in enumerate(JOY_POV_DIRECTIONS):
            keymap[f"joy{device + 1}_pov_{direction}"] = joystick_code(device, JOY_MAX_BUTTONS + index)
    return keymap


def pov_buttons(angle: int) -> int:
    """POV direction bits (as buttons 32-35) from angle in hundredths of degree, diagonal sets two"""
    if not 0 <= angle < 36000:  # centered (65535 on Windows)
        return 0
    bits = 0
    if angle <= 4500 or angle >= 31500:
        bits |= 1  # up
    if 4500 <= angle <= 13500:
        bits |= 2  # right
    if 13500 <= angle <= 22500:
        bits |= 4  # down
    if 22500 <= angle <= 31500:
        bits |= 8  # left
    return bits << JOY_MAX_BUTTONS


class JoystickReader:
    """Pressed buttons of game controllers, each device read at most once per refresh interval"""

    __slots__ = (
        "_states",
        "_next_read",
    )

    def __init__(self):
        self._states: dict[int, int] = {}  # device: button bits
        self._next_read: dict[int, float] = {}

    def pressed(self, code: int) -> int:
        """Button state from key code - 1 if pressed, 0 otherwise"""
        device, button = split_joystick_code(code)
        if device < 0:
            return 0
        now = time.monotonic()
        if now >= self._next_read.get(device, 0.0):
            state = self._read(device)
            if state is None:  # absent
                self._states[device] = 0
                self._next_read[device] = now + JOY_RETRY_INTERVAL
            else:
                self._states[device] = state
                self._next_read[device] = now + JOY_REFRESH_INTERVAL
        return (self._states[device] >> button) & 1

    def close(self):
        """Release devices"""

    def _read(self, device: int) -> int | None:
        """Button bits of device, None if absent"""
        return None


class _WinJoystickReader(JoystickReader):
    """Windows multimedia joystick API (winmm), any DirectInput or XInput controller"""

    __slots__ = (
        "_get_pos",
        "_has_pov",
        "_info",
        "_pov_devices",
    )

    def __init__(self):
        super().__init__()
        if sys.platform != "win32":  # platform check also read by type checker
            raise OSError("winmm not available")
        import ctypes
        from ctypes import wintypes

        class JOYINFOEX(ctypes.Structure):
            _fields_ = [(_name, wintypes.DWORD) for _name in (
                "dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos", "dwVpos",
                "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1", "dwReserved2")]

        class JOYCAPSW(ctypes.Structure):
            _fields_ = [
                ("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("szPname", wintypes.WCHAR * 32),
                *((_name, wintypes.UINT) for _name in (
                    "wXmin", "wXmax", "wYmin", "wYmax", "wZmin", "wZmax", "wNumButtons", "wPeriodMin",
                    "wPeriodMax", "wRmin", "wRmax", "wUmin", "wUmax", "wVmin", "wVmax", "wCaps",
                    "wMaxAxes", "wNumAxes", "wMaxButtons")),
                ("szRegKey", wintypes.WCHAR * 32), ("szOEMVxD", wintypes.WCHAR * 260)]

        winmm = ctypes.WinDLL("winmm")
        self._info = JOYINFOEX()
        self._info.dwSize = ctypes.sizeof(JOYINFOEX)
        self._info.dwFlags = 0x80 | 0x40  # JOY_RETURNBUTTONS | JOY_RETURNPOV
        joy_get_pos = winmm.joyGetPosEx
        joy_get_pos.argtypes = (wintypes.UINT, ctypes.POINTER(JOYINFOEX))
        joy_get_pos.restype = wintypes.UINT
        info_ref = ctypes.byref(self._info)
        self._get_pos = lambda device: joy_get_pos(device, info_ref)

        joy_get_caps = winmm.joyGetDevCapsW
        joy_get_caps.argtypes = (ctypes.c_size_t, ctypes.POINTER(JOYCAPSW), wintypes.UINT)
        joy_get_caps.restype = wintypes.UINT

        def has_pov(device: int) -> bool:
            caps = JOYCAPSW()
            if joy_get_caps(device, ctypes.byref(caps), ctypes.sizeof(JOYCAPSW)) != 0:
                return False
            return bool(caps.wCaps & 0x10)  # JOYCAPS_HASPOV

        self._has_pov = has_pov
        self._pov_devices: dict[int, bool] = {}

    def _read(self, device: int) -> int | None:
        if sys.platform != "win32" or self._get_pos(device) != 0:  # JOYERR_NOERROR
            self._pov_devices.pop(device, None)  # other device may take its id
            return None
        info = self._info
        buttons = info.dwButtons & 0xFFFFFFFF
        pov = self._pov_devices.get(device)
        if pov is None:
            pov = self._pov_devices[device] = self._has_pov(device)
        if pov:  # POV angle of a device without POV is no direction
            buttons |= pov_buttons(info.dwPOV)
        return buttons


# Linux joystick API (linux/joystick.h)
_JS_EVENT = struct.Struct("IhBB")  # time, value, type, number
_JS_EVENT_BUTTON = 0x01
_JS_EVENT_AXIS = 0x02
_JS_EVENT_INIT = 0x80
_JSIOCGAXMAP = 0x80406A32  # _IOR('j', 0x32, __u8[ABS_CNT])
_ABS_HAT0X = 0x10
_ABS_HAT0Y = 0x11


class _LinuxJoystickReader(JoystickReader):
    """Linux joystick devices (/dev/input/jsN), read without blocking"""

    __slots__ = (
        "_files",
        "_buttons",
        "_hat_axes",
        "_hats",
    )

    def __init__(self):
        super().__init__()
        self._files: dict[int, int] = {}  # device: file descriptor
        self._buttons: dict[int, int] = {}  # device: button bits
        self._hat_axes: dict[int, tuple[int, int]] = {}  # device: axis number of hat x, y
        self._hats: dict[int, list[int]] = {}  # device: hat x, y value

    def close(self):
        for device in tuple(self._files):
            self._close_device(device)

    def __del__(self):
        self.close()

    def _open_device(self, device: int) -> int | None:
        if sys.platform == "win32":  # platform check also read by type checker
            return None
        try:
            fd = os.open(f"/dev/input/js{device}", os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return None
        self._files[device] = fd
        self._buttons[device] = 0
        self._hats[device] = [0, 0]
        self._hat_axes[device] = (-1, -1)
        try:
            import fcntl

            axis_map = bytearray(64)
            fcntl.ioctl(fd, _JSIOCGAXMAP, axis_map)
            self._hat_axes[device] = (axis_map.find(_ABS_HAT0X), axis_map.find(_ABS_HAT0Y))
        except (OSError, ImportError):  # no axis map: no hat
            pass
        return fd

    def _close_device(self, device: int):
        fd = self._files.pop(device, None)
        if fd is not None:
            with suppress(OSError):
                os.close(fd)

    def _read(self, device: int) -> int | None:
        fd = self._files.get(device)
        if fd is None:
            fd = self._open_device(device)
            if fd is None:
                return None
        buttons = self._buttons[device]
        hats = self._hats[device]
        hat_x, hat_y = self._hat_axes[device]
        size = _JS_EVENT.size
        while True:
            try:
                data = os.read(fd, size * 64)
            except BlockingIOError:
                break
            except OSError:  # unplugged
                self._close_device(device)
                return None
            if not data:
                break
            for offset in range(0, len(data) - size + 1, size):
                _, value, event_type, number = _JS_EVENT.unpack_from(data, offset)
                event_type &= ~_JS_EVENT_INIT
                if event_type == _JS_EVENT_BUTTON and number < JOY_MAX_BUTTONS:
                    if value:
                        buttons |= 1 << number
                    else:
                        buttons &= ~(1 << number)
                elif event_type == _JS_EVENT_AXIS:
                    if number == hat_x:
                        hats[0] = value
                    elif number == hat_y:
                        hats[1] = value
        self._buttons[device] = buttons
        return buttons | _hat_bits(*hats)


def _hat_bits(x: int, y: int) -> int:
    """POV direction bits (as buttons 32-35) from hat axes (negative: up or left)"""
    bits = 0
    if y < 0:
        bits |= 1
    if x > 0:
        bits |= 2
    if y > 0:
        bits |= 4
    if x < 0:
        bits |= 8
    return bits << JOY_MAX_BUTTONS


def joystick_reader() -> JoystickReader:
    """Platform specific game controller reader (never reads anything if unavailable)"""
    try:
        if PLATFORM.WINDOWS and sys.platform == "win32":
            return _WinJoystickReader()
        if sys.platform.startswith("linux"):
            return _LinuxJoystickReader()
    except (OSError, AttributeError) as error:
        logger.warning("HOTKEY: game controllers not readable (%s)", error)
    return JoystickReader()
