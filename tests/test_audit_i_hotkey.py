"""Audit i, lot H (BUG-002): game controller button tapped between two hotkey checks still runs its command,
once: presses latched by the reader (rising edges, Linux press events), consumed by the hotkey thread only,
checked at the device read rate (key capture consumes them too since the SimHub Control Mapper fix)"""

from __future__ import annotations

import os
import struct
import sys
from types import SimpleNamespace

import pytest

from neopedal.hotkey import common, joystick
from neopedal.hotkey.joystick import JOY_MAX_BUTTONS, JoystickReader, joystick_code


class FakeReader(JoystickReader):
    """Device states by time: {device: ((start, end, bits), ...)}, bits held while start <= now < end"""

    __slots__ = ("timeline", "reads", "clock")

    def __init__(self, timeline, clock):
        super().__init__()
        self.timeline = timeline
        self.reads = []
        self.clock = clock

    def _read(self, device):
        self.reads.append(device)
        presses = self.timeline.get(device)
        if presses is None:
            return None
        now = self.clock[0]
        state = 0
        for start, end, bits in presses:
            if start <= now < end:
                state |= bits
        return state


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(joystick.time, "monotonic", lambda: now[0])
    return now


def test_tap_between_reads_latched_and_consumed_once(clock):
    """Button 4 tapped (down between two reads of the device started by another button), seen once by the
    consuming caller, then released state"""
    button_a, button_b = joystick_code(0, 4), joystick_code(0, 7)
    reader = FakeReader({0: ((100.1, 100.2, 1 << 4),)}, clock)
    assert reader.pressed(button_a, consume=True) == 0
    clock[0] = 100.15  # another button of the device read while 4 held
    assert reader.pressed(button_b, consume=True) == 0
    clock[0] = 100.25  # 4 released before its next check
    assert reader.pressed(button_a, consume=True) == 1  # latched press
    clock[0] = 100.3
    assert reader.pressed(button_a, consume=True) == 0  # once only
    assert reader.pressed(button_b, consume=True) == 0


def test_held_button_not_repeated_by_latch(clock):
    """Latch adds nothing to a held button: state 1 while held, 0 once released (no extra press after release)"""
    button = joystick_code(0, 2)
    reader = FakeReader({0: ((100.0, 100.5, 1 << 2),)}, clock)
    assert reader.pressed(button, consume=True) == 1
    clock[0] = 100.2
    assert reader.pressed(button, consume=True) == 1
    clock[0] = 100.6
    assert reader.pressed(button, consume=True) == 0


def test_two_buttons_tapped_in_same_window_each_reported_once(clock):
    """Two buttons pressed between checks: each latched, consumed independently (one does not clear the other)"""
    button_a, button_b, button_c = joystick_code(0, 1), joystick_code(0, 5), joystick_code(0, 6)
    reader = FakeReader({0: ((100.1, 100.2, 1 << 1 | 1 << 5),)}, clock)
    for code in (button_a, button_b, button_c):
        assert reader.pressed(code, consume=True) == 0
    clock[0] = 100.15
    assert reader.pressed(button_c, consume=True) == 0  # read with both held
    clock[0] = 100.25
    assert reader.pressed(button_a, consume=True) == 1
    assert reader.pressed(button_b, consume=True) == 1
    assert reader.pressed(button_c, consume=True) == 0
    clock[0] = 100.3
    assert reader.pressed(button_a, consume=True) == 0
    assert reader.pressed(button_b, consume=True) == 0


def test_raw_state_does_not_consume_or_report_latch(clock):
    """Raw reads (consume=False) give the sampled state: a latched tap is neither reported nor cleared"""
    button_a, button_b = joystick_code(0, 4), joystick_code(0, 7)
    reader = FakeReader({0: ((100.1, 100.2, 1 << 4),)}, clock)
    reader.pressed(button_a)
    clock[0] = 100.15
    assert reader.pressed(button_b) == 0 and reader.pressed(button_a) == 1  # held: raw state 1
    clock[0] = 100.25
    assert reader.pressed(button_a) == 0  # released: raw state only
    assert reader.pressed(button_a, consume=True) == 1  # latch kept for the consuming caller
    assert reader.pressed(button_a, consume=True) == 0


def test_absent_device_clears_latch_and_reconnected_held_button_pressed_once(clock):
    """Device unplugged: press latched before is dropped (never run 2 s later once plugged back); device back
    with a button held: pressed once (rising edge from absent), then held state"""
    button = joystick_code(1, 3)
    timeline = {1: ((100.1, 100.2, 1 << 3),)}
    reader = FakeReader(timeline, clock)
    assert reader.pressed(button, consume=True) == 0
    clock[0] = 100.15
    assert reader.pressed(joystick_code(1, 0), consume=True) == 0  # read while 3 held
    del timeline[1]  # unplugged
    clock[0] = 100.25
    assert reader.pressed(button, consume=True) == 0
    assert reader.reads == [1, 1, 1]
    clock[0] = 100.5
    assert reader.pressed(button, consume=True) == 0 and reader.reads == [1, 1, 1]  # absent: retried later only
    timeline[1] = ((100.0, 200.0, 1 << 3),)  # plugged back, button held
    clock[0] = 100.25 + joystick.JOY_RETRY_INTERVAL
    assert reader.pressed(button, consume=True) == 1
    clock[0] += joystick.JOY_REFRESH_INTERVAL
    assert reader.pressed(button, consume=True) == 1  # held (hotkey thread never repeats a held key)
    assert reader.pressed(button) == 1


def test_event_press_and_release_in_one_read_latched(clock):
    """Event based reader (Linux): press & release both in one batch leave the state released, the press is
    latched by _latch and reported once"""

    class EventReader(JoystickReader):
        __slots__ = ("taps",)

        def __init__(self):
            super().__init__()
            self.taps = []

        def _read(self, device):
            for bits in self.taps:
                self._latch(device, bits)
            self.taps.clear()
            return 0

    button = joystick_code(0, 9)
    reader = EventReader()
    assert reader.pressed(button, consume=True) == 0
    reader.taps.append(1 << 9)
    clock[0] += joystick.JOY_REFRESH_INTERVAL
    assert reader.pressed(button) == 0  # raw state: released
    assert reader.pressed(button, consume=True) == 1
    assert reader.pressed(button, consume=True) == 0


def js_event(value, event_type, number):
    return struct.pack("IhBB", 0, value, event_type, number)


@pytest.mark.skipif(not hasattr(os, "pipe") or os.name == "nt", reason="Linux joystick device")
def test_linux_tap_in_one_batch_latched(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    monkeypatch.setattr(joystick.os, "open", lambda path, flags: read_fd)
    monkeypatch.setattr(joystick, "JOY_REFRESH_INTERVAL", 0)
    reader = joystick._LinuxJoystickReader()
    try:
        assert reader.pressed(joystick_code(0, 3), consume=True) == 0
        # Button 3 tapped & hat pushed up then centered between two reads
        os.write(write_fd, js_event(1, 0x01, 3) + js_event(0, 0x01, 3))
        hat_y = reader._hat_axes[0][1]
        if hat_y >= 0:
            os.write(write_fd, js_event(-32767, 0x02, hat_y) + js_event(0, 0x02, hat_y))
        assert reader.pressed(joystick_code(0, 3), consume=True) == 1
        assert reader.pressed(joystick_code(0, 3), consume=True) == 0
        assert reader.pressed(joystick_code(0, 3)) == 0
        if hat_y >= 0:
            assert reader.pressed(joystick_code(0, JOY_MAX_BUTTONS), consume=True) == 1
            assert reader.pressed(joystick_code(0, JOY_MAX_BUTTONS), consume=True) == 0
    finally:
        reader.close()
        os.close(write_fd)


def test_key_state_latches_controller_buttons_only_when_asked(clock):
    """KeyState (returned by get_key_state_function) consumes latched controller presses only for the hotkey
    thread (latch_controller_buttons), keyboard keys untouched"""
    button = joystick_code(2, 0)
    reader = FakeReader({2: ((100.1, 100.2, 1),)}, clock)
    keyboard = {65: 0x8001}
    key_state = common.KeyState(lambda code: keyboard.get(code, 0), reader)
    assert key_state(65) == 0x8001 and key_state(0x11) == 0  # VK_CONTROL: keyboard key not held
    assert key_state(button) == 0
    clock[0] = 100.15
    assert key_state(joystick_code(2, 1)) == 0  # device read while button held
    clock[0] = 100.25
    assert key_state(button) == 0  # latch not asked: sampled state
    key_state.latch_controller_buttons = True
    assert key_state(button) == 1  # hotkey thread & key capture: tap kept
    assert key_state(button) == 0


def test_get_key_state_function_returns_key_state(monkeypatch):
    monkeypatch.setattr(common, "joystick_reader", lambda: JoystickReader())
    key_state = common.get_key_state_function()
    assert isinstance(key_state, common.KeyState) and key_state.latch_controller_buttons is False
    assert key_state(joystick_code(0, 0)) == 0


def test_hotkey_loop_runs_tapped_controller_button_once(ui_env, monkeypatch, clock):
    """Wheel button held 100 ms between two 200 ms checks: hotkey thread checks at the device read rate (50 ms)
    while a controller button is bound, command run once and only once"""
    from neopedal import hotkey_control
    from neopedal.setting import cfg

    monkeypatch.setitem(cfg.user.shortcuts, "overlay_lock", {"bind": "joy1_button_5"})  # joystick_code(0, 4)
    monkeypatch.setattr(hotkey_control, "COMMANDS_GENERAL", (("overlay_lock", lambda: "overlay_lock"),))
    for group in ("COMMANDS_PRESET", "COMMANDS_MODULE", "COMMANDS_WIDGET"):
        monkeypatch.setattr(hotkey_control, group, ())
    ran: list[str] = []
    monkeypatch.setattr(hotkey_control, "app_signal", SimpleNamespace(hotkey=SimpleNamespace(
        emit=lambda func: ran.append(func()))))
    monkeypatch.setattr(hotkey_control, "refresh_keystate", lambda func: None)
    start = clock[0]
    reader = FakeReader({0: ((start + 0.21, start + 0.31, 1 << 4),)}, clock)  # 100 ms tap after check 0.2
    monkeypatch.setattr(hotkey_control, "get_key_state_function",
                        lambda: common.KeyState(lambda code: 0, reader))
    intervals: list[float] = []

    def wait(timeout=None):  # clock advanced by the loop's own wait
        intervals.append(timeout)
        clock[0] += timeout
        return clock[0] > start + 1.0

    hotkey_control.HotkeyControl()._HotkeyControl__update_loop(SimpleNamespace(wait=wait))
    assert set(intervals) == {joystick.JOY_REFRESH_INTERVAL}
    assert ran == ["overlay_lock"]


@pytest.mark.skipif(sys.platform != "win32", reason="keyboard bindings: KEYMAP_GENERAL has keys on Windows only")
def test_hotkey_loop_keeps_slow_checks_without_controller_buttons(ui_env, monkeypatch):
    """Keyboard only bindings: 200 ms checks kept (GetAsyncKeyState reports taps itself)"""
    from neopedal import hotkey_control
    from neopedal.setting import cfg

    monkeypatch.setitem(cfg.user.shortcuts, "overlay_lock", {"bind": "ctrl+a"})
    monkeypatch.setattr(hotkey_control, "COMMANDS_GENERAL", (("overlay_lock", lambda: "overlay_lock"),))
    for group in ("COMMANDS_PRESET", "COMMANDS_MODULE", "COMMANDS_WIDGET"):
        monkeypatch.setattr(hotkey_control, group, ())
    monkeypatch.setattr(hotkey_control, "refresh_keystate", lambda func: None)
    key_state = common.KeyState(lambda code: 0, JoystickReader())
    monkeypatch.setattr(hotkey_control, "get_key_state_function", lambda: key_state)
    intervals: list[float] = []

    def wait(timeout=None):
        intervals.append(timeout)
        return len(intervals) >= 2

    hotkey_control.HotkeyControl()._HotkeyControl__update_loop(SimpleNamespace(wait=wait))
    assert intervals == [0.2, 0.2]
    assert key_state.latch_controller_buttons is True
