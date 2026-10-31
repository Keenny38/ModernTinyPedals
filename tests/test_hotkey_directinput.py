"""SimHub Control Mapper buttons as hotkeys: its virtual controller ("SimHub Controller Remapper Bridge",
or vJoy) has 128 buttons, read with DirectInput (winmm reads 32 only); short pulses kept by the DirectInput
event buffer, also while capturing a binding"""

import sys

import pytest

from neopedal.hotkey import common, joystick, keymap
from neopedal.hotkey.common import load_hotkey, set_hotkey, validate_hotkey
from neopedal.hotkey.joystick import JOY_MAX_BUTTONS, joystick_code

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DirectInput")

GUID_BRIDGE = b"b" * 16
GUID_WHEEL = b"w" * 16


def test_buttons_above_32_bindable():
    assert JOY_MAX_BUTTONS == 128
    assert validate_hotkey("joy3_button_100") == "joy3_button_100"
    # Keyboard modifiers exist on Windows only (KEYMAP_MODIFIER is empty elsewhere): the Windows map is given
    assert validate_hotkey("ctrl+joy1_button_128", key_modifier=keymap._WIN_KEYMAP_MODIFIER) == "ctrl+joy1_button_128"
    assert validate_hotkey("joy1_button_129") == ""
    assert load_hotkey("joy3_button_100") == (joystick_code(2, 99),)
    assert set_hotkey(lambda code: code == joystick_code(2, 99)) == ("", "", "", "joy3_button_100")
    assert load_hotkey("joy1_pov_left") == (joystick_code(0, 131),)


def test_split_code_rejects_out_of_range():
    assert joystick.split_joystick_code(joystick_code(0, 131)) == (0, 131)
    assert joystick.split_joystick_code(joystick_code(0, 132)) == (-1, -1)
    assert joystick.split_joystick_code(joystick_code(16, 0)) == (-1, -1)


if sys.platform == "win32":

    class FakeDirectInput(joystick._DirectInputReader):
        """Real DirectInput setup, devices & COM calls faked: state & buffered events from the test"""

        __slots__ = ("devices", "count", "held", "pov", "events", "lists", "calls", "has_pov")

        def __init__(self, devices, pov=True):
            self.devices = devices
            self.count = 10
            self.held = {}  # device guid: held button indexes
            self.pov = 0xFFFFFFFF
            self.events = []  # (offset, data) of next buffer read
            self.lists = 0
            self.calls = []
            self.has_pov = pov
            super().__init__()

        def _enumerate(self):
            self._list_devices = (self._fake_list, lambda guid: id(guid) if guid in dict(self.devices) else None)
            self._input_count = lambda: self.count
            super()._enumerate()

        def _fake_list(self):
            self.lists += 1
            return list(self.devices)

        def _call(self, obj, index, *args):
            self.calls.append(index)
            if index == joystick._DID_GET_CAPABILITIES:
                caps = args[0]._obj
                caps.dwPOVs = int(self.has_pov)
            elif index == joystick._DID_GET_DEVICE_STATE:
                guid = next(_guid for _guid, _ in self.devices if id(_guid) == obj)
                state = self._state
                state.pov[0] = self.pov
                for button in range(JOY_MAX_BUTTONS):
                    state.buttons[button] = 0x80 if button in self.held.get(guid, ()) else 0
            elif index == joystick._DID_GET_DEVICE_DATA:
                events, self.events = self.events, []
                count = args[2]._obj
                for slot, (offset, data) in enumerate(events):
                    self._events[slot].dwOfs = offset
                    self._events[slot].dwData = data
                count.value = len(events)
            return 0

        def _call_api(self, index, *args):
            return 0

    def button_offset(button):
        return joystick._DI_POVS * 4 + button


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(joystick.time, "monotonic", lambda: now[0])
    return now


@windows_only
def test_reader_is_directinput_on_windows():
    reader = joystick.joystick_reader()
    try:
        assert isinstance(reader, joystick._DirectInputReader)
        assert reader.pressed(joystick_code(15, 127)) == 0  # absent device, no error
    finally:
        reader.close()


@windows_only
def test_button_above_32_pressed(clock):
    reader = FakeDirectInput([(GUID_WHEEL, "Wheel"), (GUID_BRIDGE, "SimHub Controller Remapper Bridge")])
    reader.held[GUID_BRIDGE] = {99}
    assert reader.device_names() == ["Wheel", "SimHub Controller Remapper Bridge"]
    assert reader.pressed(joystick_code(1, 99)) == 1
    assert reader.pressed(joystick_code(1, 31)) == 0
    assert reader.pressed(joystick_code(0, 99)) == 0


@windows_only
def test_short_pulse_between_reads_latched_once(clock):
    """Pulse pressed & released between two reads: only the DirectInput event buffer has it"""
    reader = FakeDirectInput([(GUID_BRIDGE, "SimHub Controller Remapper Bridge")])
    button = joystick_code(0, 70)
    assert reader.pressed(button, consume=True) == 0
    reader.events = [(button_offset(70), 0x80), (button_offset(70), 0)]
    clock[0] += 1.0
    assert reader.pressed(button) == 0  # sampled state: released
    assert reader.pressed(button, consume=True) == 1  # latched pulse
    assert reader.pressed(button, consume=True) == 0  # once


@windows_only
def test_pov_event_latched_only_with_pov(clock):
    up = joystick_code(0, JOY_MAX_BUTTONS)
    reader = FakeDirectInput([(GUID_BRIDGE, "Bridge")])
    reader.events = [(0, 0), (0, 0xFFFFFFFF)]  # up tapped
    assert reader.pressed(up, consume=True) == 1
    no_pov = FakeDirectInput([(GUID_BRIDGE, "Bridge")], pov=False)
    no_pov.pov = 0  # POV slot of device without POV: no direction
    no_pov.events = [(0, 0)]
    assert no_pov.pressed(up, consume=True) == 0


@windows_only
def test_devices_listed_again_only_when_windows_device_count_changes(clock):
    reader = FakeDirectInput([(GUID_WHEEL, "Wheel")])
    assert reader.lists == 1
    for _ in range(5):
        clock[0] += joystick.JOY_RETRY_INTERVAL
        assert reader.pressed(joystick_code(1, 0)) == 0
    assert reader.lists == 1  # absent device: no slow listing while nothing plugged
    reader.devices.append((GUID_BRIDGE, "Bridge"))
    reader.held[GUID_BRIDGE] = {40}
    reader.count += 1  # device plugged
    clock[0] += joystick.JOY_RETRY_INTERVAL
    assert reader.pressed(joystick_code(1, 40)) == 1
    assert reader.lists == 2


@windows_only
def test_unplugged_device_released(clock):
    reader = FakeDirectInput([(GUID_WHEEL, "Wheel"), (GUID_BRIDGE, "Bridge")])
    reader.held[GUID_BRIDGE] = {5}
    assert reader.pressed(joystick_code(0, 5)) == 0
    assert reader.pressed(joystick_code(1, 5)) == 1
    del reader.devices[1]
    reader.count -= 1
    clock[0] += 1.0
    assert reader.pressed(joystick_code(1, 5)) == 0
    assert GUID_BRIDGE not in reader._devices
    reader.close()
    assert reader.calls.count(joystick._COM_RELEASE) == 2  # both devices released


@windows_only
def test_key_state_latches_pulse_for_capture(clock):
    """Key capture (latch_controller_buttons, set by the hotkey page) catches a pulse shorter than its timer"""
    reader = FakeDirectInput([(GUID_BRIDGE, "Bridge")])
    key_state = common.KeyState(lambda code: 0, reader)
    key_state.latch_controller_buttons = True
    assert set_hotkey(key_state) == ()
    reader.events = [(button_offset(64), 0x80), (button_offset(64), 0)]
    clock[0] += 0.2
    assert set_hotkey(key_state) == ("", "", "", "joy1_button_65")


class PulseReader(joystick.JoystickReader):
    """Device 0 never held, pulses latched as by the DirectInput event buffer"""

    __slots__ = ("pulses",)

    def __init__(self):
        super().__init__()
        self.pulses = 0

    def _read(self, device):
        if device != 0:
            return None
        if self.pulses:
            self._latch(device, self.pulses)
            self.pulses = 0
        return 0


def test_capture_page_catches_pulse_shorter_than_its_timer(ui_env, monkeypatch, clock):
    """Hotkeys page capture: a SimHub Control Mapper pulse released before the 200 ms read is captured"""
    from PySide6.QtCore import QCoreApplication, QEvent

    from neopedal.setting import cfg
    from neopedal.ui.quick import hotkey_backend

    for action in ("reload", "enable", "disable"):
        monkeypatch.setattr(type(hotkey_backend.kctrl), action, lambda self: None)
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    reader = PulseReader()
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: common.KeyState(lambda code: 0, reader))
    page = hotkey_backend.HotkeyBackend(None)
    page.page_shown()
    cfg.application["enable_global_hotkey"] = True
    cfg.user.shortcuts["overlay_lock"]["bind"] = ""
    page.startCapture("overlay_lock")
    try:
        page.read_keys()
        assert page.capturedBinding == ""
        reader.pulses = 1 << 99
        clock[0] += 0.2
        page.read_keys()
        assert page.capturedBinding == "joy1_button_100"
    finally:
        page.cancelCapture()
        page.release()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
