"""Game controller buttons as hotkey keys: key names & codes, POV, device reads"""

import os
import struct

import pytest

from neopedal.hotkey import joystick
from neopedal.hotkey.common import format_hotkey_name, load_hotkey, set_hotkey, validate_hotkey
from neopedal.hotkey.joystick import (
    JOY_CODE_BASE,
    JOY_MAX_BUTTONS,
    JoystickReader,
    joystick_code,
    joystick_keymap,
    pov_buttons,
    split_joystick_code,
)
from neopedal.hotkey.keymap import KEYMAP_GENERAL


def test_key_names_and_codes():
    keymap = joystick_keymap()
    assert keymap["joy1_button_1"] == JOY_CODE_BASE
    assert keymap["joy2_button_5"] == joystick_code(1, 4)
    assert keymap["joy16_pov_left"] == joystick_code(15, JOY_MAX_BUTTONS + 3)
    assert len(set(keymap.values())) == len(keymap) == 16 * 36  # no shared code
    assert min(keymap.values()) > 255  # above keyboard & mouse codes
    assert all(split_joystick_code(code) == divmod(code - JOY_CODE_BASE, 64) for code in keymap.values())
    assert split_joystick_code(65) == (-1, -1)
    assert split_joystick_code(joystick_code(16, 0)) == (-1, -1)


def test_buttons_bindable_on_every_platform():
    assert validate_hotkey("joy1_button_12") == "joy1_button_12"
    assert load_hotkey("joy3_pov_down") == (joystick_code(2, JOY_MAX_BUTTONS + 2),)
    assert format_hotkey_name("joy1_button_12", delimiter=" + ") == "Joy1 Button 12"
    assert validate_hotkey("joy17_button_1") == ""
    assert "joy1_button_1" in KEYMAP_GENERAL


def test_button_detected_as_key():
    pressed = {joystick_code(0, 6)}
    assert set_hotkey(lambda code: code in pressed) == ("", "", "", "joy1_button_7")


@pytest.mark.parametrize("angle, directions", [
    (65535, ()),  # centered
    (0, ("up",)),
    (9000, ("right",)),
    (13500, ("right", "down")),  # diagonal
    (27000, ("left",)),
    (31500, ("up", "left")),
])
def test_pov_directions(angle, directions):
    bits = pov_buttons(angle) >> JOY_MAX_BUTTONS
    assert [name for index, name in enumerate(joystick.JOY_POV_DIRECTIONS) if bits >> index & 1] == list(directions)


class FakeReader(JoystickReader):
    __slots__ = ("reads", "states")

    def __init__(self, states):
        super().__init__()
        self.reads = []
        self.states = states

    def _read(self, device):
        self.reads.append(device)
        return self.states.get(device)


def test_reader_reads_device_once_per_pass(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(joystick.time, "monotonic", lambda: now[0])
    reader = FakeReader({0: 0b101})
    assert [reader.pressed(joystick_code(0, button)) for button in range(4)] == [1, 0, 1, 0]
    assert reader.reads == [0]  # one read for all buttons
    assert reader.pressed(joystick_code(1, 0)) == 0  # absent device
    now[0] += 1.0
    reader.pressed(joystick_code(0, 0))
    reader.pressed(joystick_code(1, 0))
    assert reader.reads == [0, 1, 0]  # absent device not checked again at once
    now[0] += joystick.JOY_RETRY_INTERVAL
    reader.pressed(joystick_code(1, 0))
    assert reader.reads == [0, 1, 0, 1]
    assert reader.pressed(65) == 0  # keyboard code


def js_event(value, event_type, number):
    return struct.pack("IhBB", 0, value, event_type, number)


@pytest.mark.skipif(not hasattr(os, "pipe") or os.name == "nt", reason="Linux joystick device")
def test_linux_device_events(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    opened = []

    def fake_open(path, flags):
        opened.append(path)
        return read_fd

    monkeypatch.setattr(joystick.os, "open", fake_open)
    monkeypatch.setattr(joystick, "JOY_REFRESH_INTERVAL", 0)
    reader = joystick._LinuxJoystickReader()
    try:
        # Initial state (held button), then a press & a release
        os.write(write_fd, js_event(1, 0x81, 2) + js_event(0, 0x81, 3) + js_event(1, 0x01, 3))
        assert reader.pressed(joystick_code(0, 2)) == 1 and reader.pressed(joystick_code(0, 3)) == 1
        os.write(write_fd, js_event(0, 0x01, 2))
        assert reader.pressed(joystick_code(0, 2)) == 0 and reader.pressed(joystick_code(0, 3)) == 1
        assert opened == ["/dev/input/js0"]
    finally:
        reader.close()
        os.close(write_fd)


def test_hat_axes():
    assert joystick._hat_bits(0, -32767) >> JOY_MAX_BUTTONS == 0b0001  # up
    assert joystick._hat_bits(32767, 32767) >> JOY_MAX_BUTTONS == 0b0110  # right & down
    assert joystick._hat_bits(0, 0) == 0


def test_unavailable_reader_never_pressed():
    reader = JoystickReader()
    assert reader.pressed(joystick_code(0, 0)) == 0
