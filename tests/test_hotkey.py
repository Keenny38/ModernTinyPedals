"""Global hotkey tests: key strings, key codes, commands"""

import sys

import pytest

from tinypedal.hotkey import command
from tinypedal.hotkey.common import (
    format_hotkey_name,
    load_hotkey,
    modifier_priority,
    set_hotkey_win,
    sort_key_codes,
    validate_hotkey,
)

MODIFIER = {"ctrl": 17, "shift": 16, "alt": 18}
GENERAL = {"space": 32, "a": 65, "f1": 112}


# --- Key strings & codes
def test_validate_hotkey():
    assert validate_hotkey("ctrl+alt+space", GENERAL, MODIFIER) == "ctrl+alt+space"
    assert validate_hotkey("ctrl+win+a", GENERAL, MODIFIER) == "ctrl+a"  # unknown modifier dropped
    assert validate_hotkey("ctrl+nokey", GENERAL, MODIFIER) == ""
    assert validate_hotkey("", GENERAL, MODIFIER) == ""


def test_load_hotkey():
    assert load_hotkey("ctrl+shift+f1", GENERAL, MODIFIER) == (17, 16, 112)
    assert load_hotkey("win+a", GENERAL, MODIFIER) == (65,)
    assert load_hotkey("ctrl+nokey", GENERAL, MODIFIER) == ()
    assert load_hotkey("", GENERAL, MODIFIER) == ()


def test_modifiers_in_detected_order():
    """Modifiers sorted like detected key combo (modifier map order), duplicates removed"""
    assert validate_hotkey("shift+ctrl+f1", GENERAL, MODIFIER) == "ctrl+shift+f1"
    assert validate_hotkey("alt+ctrl+ctrl+a", GENERAL, MODIFIER) == "ctrl+alt+a"
    assert load_hotkey("shift+ctrl+f1", GENERAL, MODIFIER) == (17, 16, 112)
    assert load_hotkey("alt+shift+alt+a", GENERAL, MODIFIER) == (16, 18, 65)
    codes = sort_key_codes([load_hotkey("alt+shift+ctrl+a", GENERAL, MODIFIER)], MODIFIER)
    assert codes == load_hotkey("alt+shift+ctrl+a", GENERAL, MODIFIER)


def test_sort_key_codes_modifiers_first():
    codes = sort_key_codes([(17, 65), (16, 18, 32)], MODIFIER)
    assert codes[:3] == (17, 16, 18)
    assert set(codes[3:]) == {65, 32}


def test_format_and_priority():
    assert format_hotkey_name("ctrl+page_up", delimiter=" + ") == "Ctrl + Page Up"
    assert format_hotkey_name("", notset="Not set") == "Not set"
    assert [modifier_priority(key) for key in ("ctrl", "shift", "alt", "x")] == [0, 1, 2, 0]


def test_set_hotkey_from_key_state():
    pressed = {17, 18, 65}
    assert set_hotkey_win(lambda code: -32768 if code in pressed else 0, GENERAL, MODIFIER) == ("ctrl", "", "alt", "a")
    assert set_hotkey_win(lambda code: -32768 if code == 17 else 0, GENERAL, MODIFIER) == ()  # modifier only


# --- Commands
@pytest.fixture
def commands(ui_env, monkeypatch):
    """Commands with signals & controls recorded"""
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(command, "app_signal", SimpleNamespace(
        refresh=SimpleNamespace(emit=lambda *args: calls.append("refresh")),
        reload=SimpleNamespace(emit=lambda *args: calls.append("reload")),
        quitapp=SimpleNamespace(emit=lambda *args: calls.append("quit"))))
    monkeypatch.setattr(command, "overlay_signal", SimpleNamespace(
        hidden=SimpleNamespace(emit=lambda value: calls.append(("hidden", value))),
        locked=SimpleNamespace(emit=lambda value: calls.append(("locked", value))),
        iconify=SimpleNamespace(emit=lambda value: calls.append(("iconify", value)))))
    monkeypatch.setattr(type(command.api), "setup", lambda self: calls.append("setup"))
    monkeypatch.setattr(command, "wctrl", SimpleNamespace(reload=lambda name=None: calls.append(("reload widget", name))))
    return calls


def test_overlay_toggles(commands):
    from tinypedal.setting import cfg

    locked = cfg.overlay["fixed_position"]
    command.hotkey_overlay_lock()
    assert cfg.overlay["fixed_position"] is not locked and ("locked", not locked) in commands
    vr = cfg.overlay["vr_compatibility"]
    command.hotkey_vr_compatibility()
    assert ("iconify", not vr) in commands
    auto_hide = cfg.overlay["auto_hide"]
    command.hotkey_overlay_auto_hide()
    assert cfg.overlay["auto_hide"] is not auto_hide


def test_overlay_visibility(commands, monkeypatch):
    from tinypedal import realtime_state

    monkeypatch.setattr(realtime_state, "hidden", False)
    command.hotkey_overlay_visibility()
    assert realtime_state.hidden and ("hidden", True) in commands


@pytest.mark.parametrize("current, step, expected", [
    (2, 1, 3),
    (4, 1, 1),  # last place: back to leader
    (2, -1, 1),
    (1, -1, 4),  # leader: to last place
])
def test_spectate_driver_cycles_by_place(commands, monkeypatch, current, step, expected):
    from tinypedal.api_control import api
    from tinypedal.setting import cfg

    places = (3, 1, 4, 2)  # place of vehicle index 0..3
    slots = (17, 4, 9, 30)  # slot id of vehicle index 0..3, saved as spectated driver
    monkeypatch.setitem(cfg.api, "enable_player_index_override", True)
    api.read.vehicle.total_vehicles = lambda: 4
    api.read.vehicle.place = lambda index=None: current if index is None else places[index]
    api.read.vehicle.slot_id = lambda index=None: slots[index]
    if step > 0:
        command.hotkey_spectate_next_driver()
    else:
        command.hotkey_spectate_previous_driver()
    assert places[slots.index(cfg.api["player_index"])] == expected
    assert "setup" in commands and "refresh" in commands


def test_spectate_driver_needs_spectate_mode(commands, monkeypatch):
    from tinypedal.setting import cfg

    monkeypatch.setitem(cfg.api, "enable_player_index_override", False)
    command.hotkey_spectate_next_driver()
    command.hotkey_spectate_previous_driver()
    assert "setup" not in commands
    command.hotkey_spectate_mode()
    assert cfg.api["enable_player_index_override"] and "refresh" in commands
    assert "setup" in commands  # override applied at once


def test_cycle_deltabest_source(commands):
    from tinypedal.regex_pattern import CFG_DELTABEST_SOURCE, CHOICE_COMMON
    from tinypedal.setting import cfg

    sources = CHOICE_COMMON[CFG_DELTABEST_SOURCE]
    options = cfg.user.setting["deltabest"]
    options["deltabest_source"] = sources[0]
    seen = []
    for _ in sources:
        command.hotkey_cycle_deltabest_source()
        seen.append(options["deltabest_source"])
    assert seen == [*sources[1:], sources[0]]  # wraps around
    assert ("reload widget", "deltabest") in commands


def test_load_next_and_previous_preset(commands, monkeypatch):
    from tinypedal.setting import cfg

    loaded = []
    monkeypatch.setattr(type(cfg), "preset_files", lambda self, **kwargs: ["a", "b", "c"])
    monkeypatch.setattr(type(cfg), "set_next_to_load", lambda self, filename: loaded.append(filename))
    monkeypatch.setattr(cfg.filename, "setting", "c.json")
    command.hotkey_load_next_preset()
    command.hotkey_load_previous_preset()
    assert loaded == ["a.json", "b.json"]
    assert commands.count("reload") == 2


def test_load_shortcut_preset(commands, monkeypatch, tmp_path):
    from tinypedal.setting import cfg

    key = next(iter(cfg.user.shortcuts))
    loaded = []
    monkeypatch.setattr(type(cfg), "set_next_to_load", lambda self, filename: loaded.append(filename))
    cfg.user.shortcuts[key]["preset"] = ""
    command.hotkey_load_preset(key)  # not set
    cfg.user.shortcuts[key]["preset"] = "missing"
    command.hotkey_load_preset(key)  # file gone: shortcut cleared
    assert cfg.user.shortcuts[key]["preset"] == ""
    (tmp_path / "settings" / "race.json").write_text("{}", encoding="utf-8")
    cfg.user.shortcuts[key]["preset"] = "race"
    command.hotkey_load_preset(key)
    assert loaded == ["race.json"] and "reload" in commands


def test_load_shortcut_preset_rejects_reserved_name(commands, monkeypatch, tmp_path):
    """brands.json (style file) never loaded as a preset, then saved over"""
    from tinypedal.setting import cfg

    key = next(iter(cfg.user.shortcuts))
    loaded = []
    monkeypatch.setattr(type(cfg), "set_next_to_load", lambda self, filename: loaded.append(filename))
    (tmp_path / "settings" / "brands.json").write_text("{}", encoding="utf-8")
    cfg.user.shortcuts[key]["preset"] = "brands"
    command.hotkey_load_preset(key)
    assert loaded == [] and "reload" not in commands
    assert cfg.user.shortcuts[key]["preset"] == ""


def test_pace_notes_playback_and_quit(commands):
    from tinypedal.setting import cfg

    enabled = cfg.user.setting["pace_notes_playback"]["enable"]
    command.hotkey_pace_notes_playback()
    assert cfg.user.setting["pace_notes_playback"]["enable"] is not enabled
    command.hotkey_quit_application()
    assert "quit" in commands


def test_command_lists_are_unique():
    names = [name for name, _ in command.COMMANDS_GENERAL + command.COMMANDS_PRESET
             + command.COMMANDS_MODULE + command.COMMANDS_WIDGET]
    assert len(names) == len(set(names))


# --- Hotkey control (key polling thread)
class StopAfter:
    """Event replacement: wait() returns False (keep polling) a number of times, then True"""

    def __init__(self, runs: int):
        self.runs = runs

    def wait(self, timeout=None) -> bool:
        self.runs -= 1
        return self.runs < 0


def run_hotkeys(monkeypatch, key_states: list[set[int]], binds: dict[str, str]) -> list[str]:
    """Poll key states (one set of pressed keys per check), returns commands run"""
    from types import SimpleNamespace

    from tinypedal import hotkey_control
    from tinypedal.setting import cfg

    for name, bind in binds.items():
        monkeypatch.setitem(cfg.user.shortcuts, name, {"bind": bind})
    commands = tuple((name, lambda name=name: name) for name in binds)
    monkeypatch.setattr(hotkey_control, "COMMANDS_GENERAL", commands)
    for group in ("COMMANDS_PRESET", "COMMANDS_MODULE", "COMMANDS_WIDGET"):
        monkeypatch.setattr(hotkey_control, group, ())
    states = iter(key_states)
    pressed: set[int] = set()
    ran: list[str] = []
    monkeypatch.setattr(hotkey_control, "app_signal", SimpleNamespace(hotkey=SimpleNamespace(
        emit=lambda func: ran.append(func()))))
    monkeypatch.setattr(hotkey_control, "refresh_keystate", lambda func: None)
    monkeypatch.setattr(hotkey_control, "get_key_state_function",
                        lambda: lambda code: -32768 if code in pressed else 0)
    control = hotkey_control.HotkeyControl()
    stop_after = StopAfter(len(key_states))

    def wait(timeout=None):  # next key state at each check
        pressed.clear()
        pressed.update(next(states, set()))
        return stop_after.wait(timeout)

    control._event = SimpleNamespace(wait=wait)
    control._HotkeyControl__update_loop()
    assert control._stopped
    return ran


WINDOWS_KEYS = pytest.mark.skipif(sys.platform != "win32", reason="global hotkeys: Windows key codes only")


@WINDOWS_KEYS
def test_hotkey_runs_once_per_key_press(ui_env, monkeypatch):
    from tinypedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, key_a = KEYMAP_MODIFIER["ctrl"], KEYMAP_GENERAL["a"]
    states = [set(), {ctrl}, {ctrl, key_a}, {ctrl, key_a}, {ctrl, key_a}, set(), {ctrl, key_a}]
    assert run_hotkeys(monkeypatch, states, {"overlay_lock": "ctrl+a"}) == ["overlay_lock"] * 2


@WINDOWS_KEYS
def test_hotkey_not_repeated_when_longer_combo_released(ui_env, monkeypatch):
    from tinypedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, shift, key_a = KEYMAP_MODIFIER["ctrl"], KEYMAP_MODIFIER["shift"], KEYMAP_GENERAL["a"]
    states = [{ctrl, key_a}, {ctrl, shift, key_a}, {ctrl, key_a}, {ctrl, key_a}]
    binds = {"overlay_lock": "ctrl+a", "overlay_auto_hide": "ctrl+shift+a"}
    assert run_hotkeys(monkeypatch, states, binds) == ["overlay_lock", "overlay_auto_hide"]


@WINDOWS_KEYS
def test_hotkey_with_modifiers_in_any_order(ui_env, monkeypatch):
    from tinypedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, shift, key_f1 = KEYMAP_MODIFIER["ctrl"], KEYMAP_MODIFIER["shift"], KEYMAP_GENERAL["f1"]
    states = [set(), {ctrl, shift, key_f1}]
    assert run_hotkeys(monkeypatch, states, {"overlay_lock": "shift+ctrl+f1"}) == ["overlay_lock"]


def test_hotkey_control_stops_without_commands(ui_env, monkeypatch):
    assert run_hotkeys(monkeypatch, [set(), set()], {}) == []


def test_hotkey_control_enable_disable(ui_env, monkeypatch, caplog):
    from tinypedal import hotkey_control, thread_guard
    from tinypedal.setting import cfg

    control = hotkey_control.HotkeyControl()
    monkeypatch.setitem(cfg.application, "enable_global_hotkey", False)
    control.enable()
    assert control._stopped  # disabled in config: no thread
    monkeypatch.setitem(cfg.application, "enable_global_hotkey", True)
    monkeypatch.setattr(hotkey_control, "run_supervised", lambda target, name, event: event.wait(5))
    control.enable()
    assert not control._stopped
    control.reload()  # stopped & started again
    control.disable()
    assert control._stopped
    # Thread stuck: disable gives up after timeout
    monkeypatch.setattr(thread_guard, "STOP_TIMEOUT", 0.05)
    control._stopped = False
    control.disable()
    assert "not stopped" in caplog.text
