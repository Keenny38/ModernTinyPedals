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
button index 0-127 for buttons, 128-131 for the directions of the first POV hat (d-pad).

128 buttons: virtual controllers (vJoy, as SimHub Control Mapper outputs) have up to 128 buttons,
read with DirectInput on Windows (winmm, the fallback, reads 32 buttons only).
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from ..const_app import PLATFORM

logger = logging.getLogger(__name__)

JOY_MAX_DEVICES = 16  # winmm joystick ids
JOY_MAX_BUTTONS = 128  # DirectInput buttons per device (vJoy maximum)
JOY_POV_DIRECTIONS = ("up", "right", "down", "left")
JOY_CODE_BASE = 1000
JOY_CODE_STRIDE = 256
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
    """Pressed buttons of game controllers, each device read at most once per refresh interval

    Button presses are latched between reads (rising edge of the sampled state, or press events on
    Linux): a button tapped and released between two checks is still reported once to a caller
    consuming the latch, like GetAsyncKeyState reports a key pressed since its last call.
    """

    __slots__ = (
        "_states",
        "_latched",
        "_next_read",
    )

    def __init__(self):
        self._states: dict[int, int] = {}  # device: button bits
        self._latched: dict[int, int] = {}  # device: buttons pressed since last consumed
        self._next_read: dict[int, float] = {}

    def pressed(self, code: int, consume: bool = False) -> int:
        """Button state from key code - 1 if pressed, 0 otherwise

        Args:
            code: key code of the button.
            consume: also report a press latched since the last consuming call, once (hotkey thread & key
                capture, which check buttons less often than they are tapped); False: sampled state only.
        """
        device, button = split_joystick_code(code)
        if device < 0:
            return 0
        now = time.monotonic()
        if now >= self._next_read.get(device, 0.0):
            state = self._read(device)
            if state is None:  # absent: a press latched before unplugging never runs once plugged back
                self._states[device] = 0
                self._latched[device] = 0
                self._next_read[device] = now + JOY_RETRY_INTERVAL
            else:
                self._latched[device] = self._latched.get(device, 0) | (state & ~self._states.get(device, 0))
                self._states[device] = state
                self._next_read[device] = now + JOY_REFRESH_INTERVAL
        state = self._states[device]
        if consume:
            bit = 1 << button
            latched = self._latched[device]
            if latched & bit:
                self._latched[device] = latched & ~bit
                state |= bit
        return (state >> button) & 1

    def _latch(self, device: int, bits: int):
        """Latch button bits pressed between two reads (event based readers)"""
        self._latched[device] = self._latched.get(device, 0) | bits

    def close(self):
        """Release devices"""

    def _read(self, device: int) -> int | None:
        """Button bits of device, None if absent"""
        return None


# DirectInput 8 (dinput.h): vtable index of the COM methods used
_COM_RELEASE = 2
_DI_CREATE_DEVICE = 3
_DI_ENUM_DEVICES = 4
_DID_GET_CAPABILITIES = 3
_DID_SET_PROPERTY = 6
_DID_ACQUIRE = 7
_DID_UNACQUIRE = 8
_DID_GET_DEVICE_STATE = 9
_DID_GET_DEVICE_DATA = 10
_DID_SET_DATA_FORMAT = 11
_DID_SET_COOPERATIVE_LEVEL = 13
_DID_POLL = 25
_DI_POVS = 4  # POV hats in read state (first one as hotkey directions)
_DI_BUFFER_SIZE = 64  # button & POV events kept between two reads


class _DirectInputReader(JoystickReader):
    """Windows DirectInput 8, 128 buttons per game controller (vJoy virtual controllers included)

    Every button & POV change between two reads is buffered by DirectInput: a press shorter than the read
    interval (virtual controller pulse, rotary encoder step) is latched as well.

    Devices numbered in DirectInput order (game controllers listed by Windows), same as winmm ids. Listing
    is slow (tens of ms): done again only once the Windows input device count changed (device plugged after
    start, unplugged & plugged back), checked in microseconds at each read.
    """

    __slots__ = (
        "_ctypes",
        "_api",
        "_methods",
        "_guids",
        "_names",
        "_devices",
        "_povs",
        "_listed_count",
        "_input_count",
        "_state",
        "_events",
        "_event_count",
        "_format",
        "_list_devices",
    )
    # Declared here: on other platforms the type checker skips __init__ after its platform check
    _ctypes: tuple[Any, ...]
    _methods: tuple[Any, ...]
    _format: tuple[Any, ...]
    _list_devices: tuple[Callable[[], list[tuple[bytes, str]]], Callable[[bytes], int | None]]
    _input_count: Callable[[], int]
    _listed_count: int
    _state: Any
    _events: Any
    _event_count: Any

    def __init__(self):
        super().__init__()
        if sys.platform != "win32":  # platform check also read by type checker
            raise OSError("DirectInput not available")
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8)]

        def guid(text: str) -> GUID:
            parts = text.split("-")
            tail = bytes.fromhex(parts[3] + parts[4])
            return GUID(int(parts[0], 16), int(parts[1], 16), int(parts[2], 16), (wintypes.BYTE * 8)(
                *(_byte - 256 if _byte > 127 else _byte for _byte in tail)))

        class DIDEVICEINSTANCEW(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("guidInstance", GUID), ("guidProduct", GUID),
                ("dwDevType", wintypes.DWORD), ("tszInstanceName", wintypes.WCHAR * 260),
                ("tszProductName", wintypes.WCHAR * 260), ("guidFFDriver", GUID),
                ("wUsagePage", wintypes.WORD), ("wUsage", wintypes.WORD)]

        class DIOBJECTDATAFORMAT(ctypes.Structure):
            _fields_ = [
                ("pguid", ctypes.POINTER(GUID)), ("dwOfs", wintypes.DWORD), ("dwType", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD)]

        class DIDATAFORMAT(ctypes.Structure):
            _fields_ = [
                *((_name, wintypes.DWORD) for _name in ("dwSize", "dwObjSize", "dwFlags", "dwDataSize", "dwNumObjs")),
                ("rgodf", ctypes.POINTER(DIOBJECTDATAFORMAT))]

        class DIDEVCAPS(ctypes.Structure):
            _fields_ = [(_name, wintypes.DWORD) for _name in (
                "dwSize", "dwFlags", "dwDevType", "dwAxes", "dwButtons", "dwPOVs", "dwFFSamplePeriod",
                "dwFFMinTimeResolution", "dwFirmwareRevision", "dwHardwareRevision", "dwFFDriverVersion")]

        class DIPROPDWORD(ctypes.Structure):  # DIPROPHEADER & value
            _fields_ = [(_name, wintypes.DWORD) for _name in ("dwSize", "dwHeaderSize", "dwObj", "dwHow", "dwData")]

        class DIDEVICEOBJECTDATA(ctypes.Structure):
            _fields_ = [
                *((_name, wintypes.DWORD) for _name in ("dwOfs", "dwData", "dwTimeStamp", "dwSequence")),
                ("uAppData", ctypes.c_size_t)]

        class STATE(ctypes.Structure):  # POV angles then button bytes (high bit: pressed)
            _fields_ = [("pov", wintypes.DWORD * _DI_POVS), ("buttons", ctypes.c_ubyte * JOY_MAX_BUTTONS)]

        # Data format of STATE: any POV & button of device, in device order (c_dfDIJoystick2 is not exported)
        optional_any = 0x80000000 | 0x00FFFF00  # DIDFT_OPTIONAL | DIDFT_ANYINSTANCE
        self._povs: dict[bytes, bool] = {}
        guid_pov = guid("A36D02F2-C9F3-11CF-BFC7-444553540000")
        objects = (DIOBJECTDATAFORMAT * (_DI_POVS + JOY_MAX_BUTTONS))(
            *(DIOBJECTDATAFORMAT(ctypes.pointer(guid_pov), _index * 4, 0x10 | optional_any, 0)  # DIDFT_POV
              for _index in range(_DI_POVS)),
            *(DIOBJECTDATAFORMAT(None, _DI_POVS * 4 + _index, 0x0C | optional_any, 0)  # DIDFT_BUTTON
              for _index in range(JOY_MAX_BUTTONS)))
        self._format = (guid_pov, objects, DIDATAFORMAT(
            ctypes.sizeof(DIDATAFORMAT), ctypes.sizeof(DIOBJECTDATAFORMAT), 0x01,  # DIDF_ABSAXIS
            ctypes.sizeof(STATE), len(objects), objects))
        self._state = STATE()
        self._events = (DIDEVICEOBJECTDATA * _DI_BUFFER_SIZE)()
        self._event_count = wintypes.DWORD()
        self._ctypes = (ctypes, DIDEVCAPS, DIPROPDWORD, DIDEVICEOBJECTDATA)

        hresult = ctypes.c_long
        void_p = ctypes.c_void_p
        prototypes = {
            _COM_RELEASE: (wintypes.ULONG,),
            _DI_CREATE_DEVICE: (hresult, ctypes.POINTER(GUID), ctypes.POINTER(void_p), void_p),
            _DI_ENUM_DEVICES: (hresult, wintypes.DWORD, void_p, void_p, wintypes.DWORD),
        }
        device_prototypes = {
            _COM_RELEASE: (wintypes.ULONG,),
            _DID_GET_CAPABILITIES: (hresult, ctypes.POINTER(DIDEVCAPS)),
            _DID_SET_PROPERTY: (hresult, void_p, ctypes.POINTER(DIPROPDWORD)),
            _DID_ACQUIRE: (hresult,),
            _DID_UNACQUIRE: (hresult,),
            _DID_GET_DEVICE_STATE: (hresult, wintypes.DWORD, void_p),
            _DID_GET_DEVICE_DATA: (hresult, wintypes.DWORD, void_p, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD),
            _DID_SET_DATA_FORMAT: (hresult, ctypes.POINTER(DIDATAFORMAT)),
            _DID_SET_COOPERATIVE_LEVEL: (hresult, wintypes.HWND, wintypes.DWORD),
            _DID_POLL: (hresult,),
        }
        # Method prototypes, called with (object pointer, vtable index, *args)
        self._methods = (
            {_index: ctypes.WINFUNCTYPE(_types[0], void_p, *_types[1:]) for _index, _types in prototypes.items()},
            {_index: ctypes.WINFUNCTYPE(_types[0], void_p, *_types[1:])
             for _index, _types in device_prototypes.items()},
        )

        create = ctypes.WinDLL("dinput8").DirectInput8Create
        create.argtypes = (void_p, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(void_p), void_p)
        create.restype = hresult
        get_module = ctypes.WinDLL("kernel32").GetModuleHandleW
        get_module.argtypes = (wintypes.LPCWSTR,)
        get_module.restype = void_p
        api = void_p()
        iid = guid("BF798031-483A-4DA2-AA99-5D64ED369700")  # IID_IDirectInput8W
        error = create(get_module(None), 0x0800, ctypes.byref(iid), ctypes.byref(api), None)
        if error < 0 or not api.value:
            raise OSError(f"DirectInput8Create failed ({error & 0xFFFFFFFF:#x})")
        self._api: int | None = api.value

        enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.POINTER(DIDEVICEINSTANCEW), void_p)

        def list_devices() -> list[tuple[bytes, str]]:
            found: list[tuple[bytes, str]] = []

            def add(instance, _context):
                found.append((bytes(instance.contents.guidInstance), instance.contents.tszProductName))
                return 1  # DIENUM_CONTINUE

            callback = enum_callback(add)
            # DI8DEVCLASS_GAMECTRL, DIEDFL_ATTACHEDONLY
            self._call_api(_DI_ENUM_DEVICES, 4, ctypes.cast(callback, void_p), None, 1)
            return found[:JOY_MAX_DEVICES]

        def create_device(device_guid: bytes) -> int | None:
            device = void_p()
            if self._call_api(_DI_CREATE_DEVICE, ctypes.byref(GUID.from_buffer_copy(device_guid)),
                              ctypes.byref(device), None) < 0 or not device.value:
                return None
            return device.value

        get_device_list = ctypes.WinDLL("user32").GetRawInputDeviceList
        get_device_list.argtypes = (void_p, ctypes.POINTER(wintypes.UINT), wintypes.UINT)
        get_device_list.restype = wintypes.UINT
        count = wintypes.UINT()
        count_ref = ctypes.byref(count)
        list_entry_size = ctypes.sizeof(void_p) * 2  # RAWINPUTDEVICELIST

        def input_count() -> int:
            """Number of Windows input devices (keyboards, mice, controllers), microseconds"""
            if get_device_list(None, count_ref, list_entry_size) != 0:
                return -1
            return count.value

        self._input_count = input_count
        self._list_devices = (list_devices, create_device)
        self._guids: list[bytes] = []
        self._names: list[str] = []
        self._devices: dict[bytes, int] = {}  # device guid: device interface pointer
        self._listed_count = -2
        self._enumerate()

    def _call(self, obj: int, index: int, *args) -> int:
        """Call COM method (vtable index) of a device interface"""
        ctypes = self._ctypes[0]
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return self._methods[1][index](vtable[index])(obj, *args)

    def _call_api(self, index: int, *args) -> int:
        """Call COM method (vtable index) of the DirectInput interface"""
        ctypes = self._ctypes[0]
        api = self._api
        if api is None:
            return -1
        vtable = ctypes.cast(api, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return self._methods[0][index](vtable[index])(api, *args)

    def device_names(self) -> list[str]:
        """Product names of listed devices, in device index order"""
        return list(self._names)

    def _enumerate(self):
        """List attached game controllers again, release devices no longer listed"""
        self._listed_count = self._input_count()
        listed = self._list_devices[0]()
        self._guids = [_guid for _guid, _ in listed]
        self._names = [_name for _, _name in listed]
        for device_guid in tuple(self._devices):
            if device_guid not in self._guids:
                self._release_device(device_guid)

    def _open_device(self, device_guid: bytes) -> int | None:
        device = self._list_devices[1](device_guid)
        if device is None:
            return None
        ctypes, DIDEVCAPS, DIPROPDWORD, _ = self._ctypes
        if self._call(device, _DID_SET_DATA_FORMAT, ctypes.byref(self._format[2])) < 0:
            self._call(device, _COM_RELEASE)
            return None
        # Read while another window (game) is in front, other apps keep reading it
        self._call(device, _DID_SET_COOPERATIVE_LEVEL, None, 0x08 | 0x02)  # DISCL_BACKGROUND | DISCL_NONEXCLUSIVE
        caps = DIDEVCAPS()
        caps.dwSize = ctypes.sizeof(DIDEVCAPS)
        # POV slot of a device without POV is no direction
        self._povs[device_guid] = self._call(device, _DID_GET_CAPABILITIES, ctypes.byref(caps)) >= 0 and caps.dwPOVs > 0
        buffer_size = DIPROPDWORD(ctypes.sizeof(DIPROPDWORD), 16, 0, 0, _DI_BUFFER_SIZE)  # DIPH_DEVICE
        self._call(device, _DID_SET_PROPERTY, 1, ctypes.byref(buffer_size))  # DIPROP_BUFFERSIZE, before acquire
        self._call(device, _DID_ACQUIRE)
        self._devices[device_guid] = device
        return device

    def _release_device(self, device_guid: bytes):
        device = self._devices.pop(device_guid, None)
        self._povs.pop(device_guid, None)
        if device is not None:
            self._call(device, _DID_UNACQUIRE)
            self._call(device, _COM_RELEASE)

    def close(self):
        for device_guid in tuple(self._devices):
            self._release_device(device_guid)
        if self._api is not None:
            self._call_api(_COM_RELEASE)
            self._api = None

    def __del__(self):
        with suppress(Exception):
            self.close()

    def _read(self, device: int) -> int | None:
        if self._input_count() != self._listed_count:  # device plugged or unplugged
            self._enumerate()
        if device >= len(self._guids):
            return None
        device_guid = self._guids[device]
        handle = self._devices.get(device_guid)
        if handle is None:
            handle = self._open_device(device_guid)
            if handle is None:
                return None
        ctypes = self._ctypes[0]
        state = self._state
        size = ctypes.sizeof(state)
        address = ctypes.addressof(state)
        self._call(handle, _DID_POLL)  # polled devices only, no effect on others
        self._latch_events(device, handle, self._povs.get(device_guid, False))
        if self._call(handle, _DID_GET_DEVICE_STATE, size, address) < 0:
            # Input lost (other app took it exclusive, sleep): acquired again, else unplugged
            if self._call(handle, _DID_ACQUIRE) < 0 or self._call(handle, _DID_GET_DEVICE_STATE, size, address) < 0:
                self._release_device(device_guid)  # opened again at next retry
                return None
        buttons = 0
        data = bytes(state.buttons)
        if any(data):
            for index, value in enumerate(data):
                if value & 0x80:
                    buttons |= 1 << index
        if self._povs.get(device_guid):
            buttons |= pov_buttons(state.pov[0])
        return buttons

    def _latch_events(self, device: int, handle: int, has_pov: bool):
        """Latch buttons & POV directions pressed since last read (buffered events, oldest first)"""
        ctypes = self._ctypes[0]
        events = self._events
        count = self._event_count
        bits = 0
        while True:
            count.value = _DI_BUFFER_SIZE
            if self._call(handle, _DID_GET_DEVICE_DATA, ctypes.sizeof(events[0]), ctypes.addressof(events),
                          ctypes.byref(count), 0) < 0:
                break  # input lost: state read acquires again
            for index in range(count.value):
                event = events[index]
                offset = event.dwOfs
                if offset >= _DI_POVS * 4:  # button byte
                    if event.dwData & 0x80:
                        bits |= 1 << (offset - _DI_POVS * 4)
                elif offset == 0 and has_pov:  # first POV angle
                    bits |= pov_buttons(event.dwData)
            if count.value < _DI_BUFFER_SIZE:
                break
        if bits:
            self._latch(device, bits)


class _WinJoystickReader(JoystickReader):
    """Windows multimedia joystick API (winmm), any DirectInput or XInput controller, 32 buttons
    (DirectInput fallback)"""

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
                    if value:  # press & release events of a tap both in this batch: pressed state lost, kept latched
                        buttons |= 1 << number
                        self._latch(device, 1 << number)
                    else:
                        buttons &= ~(1 << number)
                elif event_type == _JS_EVENT_AXIS:
                    if number == hat_x:
                        hats[0] = value
                    elif number == hat_y:
                        hats[1] = value
                    else:
                        continue
                    self._latch(device, _hat_bits(*hats))
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
            try:
                return _DirectInputReader()
            except (OSError, AttributeError) as error:
                logger.warning("HOTKEY: DirectInput not available, controllers read with 32 buttons (%s)", error)
            return _WinJoystickReader()
        if sys.platform.startswith("linux"):
            return _LinuxJoystickReader()
    except (OSError, AttributeError) as error:
        logger.warning("HOTKEY: game controllers not readable (%s)", error)
    return JoystickReader()
