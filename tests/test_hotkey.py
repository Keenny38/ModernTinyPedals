"""Global hotkey tests: key strings, key codes, commands"""

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

    places = (3, 1, 4, 2)  # place of player index 0..3
    monkeypatch.setitem(cfg.api, "enable_player_index_override", True)
    api.read.vehicle.total_vehicles = lambda: 4
    api.read.vehicle.place = lambda index=None: current if index is None else places[index]
    if step > 0:
        command.hotkey_spectate_next_driver()
    else:
        command.hotkey_spectate_previous_driver()
    assert places[cfg.api["player_index"]] == expected
    assert "setup" in commands


def test_spectate_driver_needs_spectate_mode(commands, monkeypatch):
    from tinypedal.setting import cfg

    monkeypatch.setitem(cfg.api, "enable_player_index_override", False)
    command.hotkey_spectate_next_driver()
    command.hotkey_spectate_previous_driver()
    assert "setup" not in commands
    command.hotkey_spectate_mode()
    assert cfg.api["enable_player_index_override"] and "refresh" in commands


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
