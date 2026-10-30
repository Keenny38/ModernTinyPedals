"""Global hotkey tests: key strings, key codes, commands"""

import sys

import pytest

from neopedal.hotkey import command
from neopedal.hotkey.common import (
    format_hotkey_name,
    load_hotkey,
    modifier_priority,
    set_hotkey,
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


def test_every_modifier_checked_for_exact_combo():
    """Modifiers not used by any hotkey still read: 'c' not run with Ctrl+C held"""
    assert sort_key_codes([(65,)], MODIFIER) == (17, 16, 18, 65)
    assert sort_key_codes([], MODIFIER) == ()


def test_modifier_released_before_key_not_in_combo(monkeypatch):
    """Modifier read as held only (pressed-since-last-check bit ignored), other keys read both bits"""
    from neopedal.hotkey import common

    states = {17: 1, 16: -32768, 65: 1}  # ctrl tapped & released, shift held, a tapped
    monkeypatch.setattr(common.PLATFORM, "WINDOWS", False)
    monkeypatch.setattr(common, "KEYMAP_MODIFIER", MODIFIER)
    monkeypatch.setattr(common, "_get_key_state_linux", lambda code: states.get(code, 0))
    get_key_state = common.get_key_state_function()
    assert not get_key_state(17) and get_key_state(16) and get_key_state(65)


def test_format_and_priority():
    assert format_hotkey_name("ctrl+page_up", delimiter=" + ") == "Ctrl + Page Up"
    assert format_hotkey_name("", notset="Not set") == "Not set"
    assert [modifier_priority(key) for key in ("ctrl", "shift", "alt", "x")] == [0, 1, 2, 0]


def test_set_hotkey_from_key_state():
    pressed = {17, 18, 65}
    assert set_hotkey(lambda code: -32768 if code in pressed else 0, GENERAL, MODIFIER) == ("ctrl", "", "alt", "a")
    assert set_hotkey(lambda code: -32768 if code == 17 else 0, GENERAL, MODIFIER) == ()  # modifier only


# --- Commands
@pytest.fixture
def commands(ui_env, monkeypatch, app_ctx):
    """Commands with signals & controls recorded"""
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(command, "app_signal", SimpleNamespace(
        refresh=SimpleNamespace(emit=lambda *args: calls.append("refresh")),
        spectate_changed=SimpleNamespace(emit=lambda slot: calls.append(("spectate", slot))),
        reload=SimpleNamespace(emit=lambda *args: calls.append("reload")),
        quitapp=SimpleNamespace(emit=lambda *args: calls.append("quit"))))
    monkeypatch.setattr(command, "overlay_signal", SimpleNamespace(
        hidden=SimpleNamespace(emit=lambda value: calls.append(("hidden", value))),
        locked=SimpleNamespace(emit=lambda value: calls.append(("locked", value))),
        iconify=SimpleNamespace(emit=lambda value: calls.append(("iconify", value)))))
    monkeypatch.setattr(type(command.api), "setup", lambda self: calls.append("setup"))
    app_ctx(wctrl=SimpleNamespace(reload=lambda name=None: calls.append(("reload widget", name))))
    return calls


def test_overlay_toggles(commands):
    from neopedal.setting import cfg

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
    from neopedal import realtime_state

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
    from neopedal.api_control import api
    from neopedal.setting import cfg

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
    assert "setup" in commands and ("spectate", cfg.api["player_index"]) in commands  # no app-wide refresh
    assert "refresh" not in commands


def test_spectate_driver_needs_spectate_mode(commands, monkeypatch):
    from neopedal.setting import cfg

    monkeypatch.setitem(cfg.api, "enable_player_index_override", False)
    command.hotkey_spectate_next_driver()
    command.hotkey_spectate_previous_driver()
    assert "setup" not in commands
    command.hotkey_spectate_mode()
    assert cfg.api["enable_player_index_override"] and "refresh" in commands
    assert "setup" in commands  # override applied at once


def test_cycle_deltabest_source(commands):
    from neopedal.regex_pattern import CFG_DELTABEST_SOURCE, CHOICE_COMMON
    from neopedal.setting import cfg

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
    from neopedal.setting import cfg

    loaded = []
    monkeypatch.setattr(type(cfg), "preset_files", lambda self, **kwargs: ["a", "b", "c"])
    monkeypatch.setattr(type(cfg), "set_next_to_load", lambda self, filename: loaded.append(filename))
    monkeypatch.setattr(cfg.filename, "setting", "c.json")
    command.hotkey_load_next_preset()
    command.hotkey_load_previous_preset()
    assert loaded == ["a.json", "b.json"]
    assert commands.count("reload") == 2


def test_load_shortcut_preset(commands, monkeypatch, tmp_path):
    from neopedal.setting import cfg

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
    from neopedal.setting import cfg

    key = next(iter(cfg.user.shortcuts))
    loaded = []
    monkeypatch.setattr(type(cfg), "set_next_to_load", lambda self, filename: loaded.append(filename))
    (tmp_path / "settings" / "brands.json").write_text("{}", encoding="utf-8")
    cfg.user.shortcuts[key]["preset"] = "brands"
    command.hotkey_load_preset(key)
    assert loaded == [] and "reload" not in commands
    assert cfg.user.shortcuts[key]["preset"] == ""


def test_pace_notes_playback_and_quit(commands):
    from neopedal.setting import cfg

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

    from neopedal import hotkey_control
    from neopedal.setting import cfg

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

    control._HotkeyControl__update_loop(SimpleNamespace(wait=wait))
    return ran


WINDOWS_KEYS = pytest.mark.skipif(sys.platform != "win32", reason="global hotkeys: Windows key codes only")


@WINDOWS_KEYS
def test_hotkey_runs_once_per_key_press(ui_env, monkeypatch):
    from neopedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, key_a = KEYMAP_MODIFIER["ctrl"], KEYMAP_GENERAL["a"]
    states = [set(), {ctrl}, {ctrl, key_a}, {ctrl, key_a}, {ctrl, key_a}, set(), {ctrl, key_a}]
    assert run_hotkeys(monkeypatch, states, {"overlay_lock": "ctrl+a"}) == ["overlay_lock"] * 2


@WINDOWS_KEYS
def test_hotkey_not_repeated_when_longer_combo_released(ui_env, monkeypatch):
    from neopedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, shift, key_a = KEYMAP_MODIFIER["ctrl"], KEYMAP_MODIFIER["shift"], KEYMAP_GENERAL["a"]
    states = [{ctrl, key_a}, {ctrl, shift, key_a}, {ctrl, key_a}, {ctrl, key_a}]
    binds = {"overlay_lock": "ctrl+a", "overlay_auto_hide": "ctrl+shift+a"}
    assert run_hotkeys(monkeypatch, states, binds) == ["overlay_lock", "overlay_auto_hide"]


@WINDOWS_KEYS
def test_hotkey_with_modifiers_in_any_order(ui_env, monkeypatch):
    from neopedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, shift, key_f1 = KEYMAP_MODIFIER["ctrl"], KEYMAP_MODIFIER["shift"], KEYMAP_GENERAL["f1"]
    states = [set(), {ctrl, shift, key_f1}]
    assert run_hotkeys(monkeypatch, states, {"overlay_lock": "shift+ctrl+f1"}) == ["overlay_lock"]


def test_controller_button_hotkey(ui_env, monkeypatch):
    """Wheel or button box button bound alone, on every platform"""
    from neopedal.hotkey.joystick import joystick_code

    button = joystick_code(1, 4)
    states = [set(), {button}, {button}, set(), {button}]
    assert run_hotkeys(monkeypatch, states, {"overlay_lock": "joy2_button_5"}) == ["overlay_lock"] * 2


@WINDOWS_KEYS
def test_controller_button_with_modifier_and_mouse_hotkey(ui_env, monkeypatch):
    from neopedal.hotkey.joystick import JOY_MAX_BUTTONS, joystick_code
    from neopedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, pov_up, mouse = KEYMAP_MODIFIER["ctrl"], joystick_code(0, JOY_MAX_BUTTONS), KEYMAP_GENERAL["mouse_back"]
    states = [{pov_up}, set(), {ctrl, pov_up}, set(), {mouse}]
    binds = {"overlay_lock": "ctrl+joy1_pov_up", "overlay_auto_hide": "mouse_back"}
    assert run_hotkeys(monkeypatch, states, binds) == ["overlay_lock", "overlay_auto_hide"]


@WINDOWS_KEYS
def test_hotkey_needs_exact_modifiers(ui_env, monkeypatch):
    """Ctrl+C never runs the 'c' hotkey, Ctrl+Shift+A never runs 'ctrl+a'"""
    from neopedal.hotkey.keymap import KEYMAP_GENERAL, KEYMAP_MODIFIER

    ctrl, shift = KEYMAP_MODIFIER["ctrl"], KEYMAP_MODIFIER["shift"]
    key_a, key_c = KEYMAP_GENERAL["a"], KEYMAP_GENERAL["c"]
    states = [{ctrl, key_c}, set(), {ctrl, shift, key_a}, set(), {key_c}, set(), {ctrl, key_a}]
    binds = {"overlay_lock": "c", "overlay_auto_hide": "ctrl+a"}
    assert run_hotkeys(monkeypatch, states, binds) == ["overlay_lock", "overlay_auto_hide"]


def test_hotkey_control_stops_without_commands(ui_env, monkeypatch):
    assert run_hotkeys(monkeypatch, [set(), set()], {}) == []


def test_hotkey_control_enable_disable(ui_env, monkeypatch, caplog):
    import threading

    from neopedal import hotkey_control, thread_guard
    from neopedal.setting import cfg

    control = hotkey_control.HotkeyControl()
    monkeypatch.setitem(cfg.application, "enable_global_hotkey", False)
    control.enable()
    assert control._stopped()  # disabled in config: no thread
    monkeypatch.setitem(cfg.application, "enable_global_hotkey", True)
    monkeypatch.setattr(hotkey_control, "run_supervised", lambda target, name, event: event.wait(5))
    control.enable()
    assert not control._stopped()
    control.reload()  # stopped & started again
    control.disable()
    assert control._stopped()
    # Thread stuck: disable gives up after timeout
    stuck = threading.Event()
    monkeypatch.setattr(hotkey_control, "run_supervised", lambda target, name, event: stuck.wait(5))
    monkeypatch.setattr(thread_guard, "STOP_TIMEOUT", 0.05)
    control.enable()
    control.disable()
    assert "not stopped" in caplog.text
    stuck.set()


def test_hotkey_control_old_thread_never_marks_new_stopped(ui_env, monkeypatch):
    """A thread stopping late (after reload started its replacement) never lets a third thread start"""
    import threading

    from neopedal import hotkey_control, thread_guard
    from neopedal.setting import cfg

    monkeypatch.setitem(cfg.application, "enable_global_hotkey", True)
    monkeypatch.setattr(thread_guard, "STOP_TIMEOUT", 0.05)
    release_first = threading.Event()
    running: list[threading.Event] = []

    def supervised(target, name, event):
        running.append(event)
        if len(running) == 1:
            release_first.wait(5)  # first thread slow to stop: ignores its event for a while
        else:
            event.wait(5)

    monkeypatch.setattr(hotkey_control, "run_supervised", supervised)
    control = hotkey_control.HotkeyControl()
    control.enable()
    first = control._thread
    control.reload()  # first thread not stopped in time: replaced
    second = control._thread
    assert second is not first and len(running) == 2
    release_first.set()
    first.join(2)
    control.enable()  # second thread still running: nothing started
    assert control._thread is second and second.is_alive()
    assert len(running) == 2
    control.disable()
    assert control._stopped()


def test_hotkey_held_across_restart_not_run_again(ui_env, monkeypatch):
    """Key still held when hotkey thread starts again (reload run by that hotkey) is no new press,
    so a held "load next preset" key never cycles presets on every reload"""
    from types import SimpleNamespace

    from neopedal import hotkey_control
    from neopedal.setting import cfg

    key = 65
    monkeypatch.setitem(cfg.user.shortcuts, "overlay_lock", {"bind": "held"})
    monkeypatch.setattr(hotkey_control, "load_hotkey", lambda bind: (key,) if bind == "held" else ())
    monkeypatch.setattr(hotkey_control, "COMMANDS_GENERAL", (("overlay_lock", lambda: "overlay_lock"),))
    for group in ("COMMANDS_PRESET", "COMMANDS_MODULE", "COMMANDS_WIDGET"):
        monkeypatch.setattr(hotkey_control, group, ())
    ran: list[str] = []
    monkeypatch.setattr(hotkey_control, "app_signal", SimpleNamespace(hotkey=SimpleNamespace(
        emit=lambda func: ran.append(func()))))
    monkeypatch.setattr(hotkey_control, "refresh_keystate", lambda func: None)
    pressed = {key}  # held since before thread started
    monkeypatch.setattr(hotkey_control, "get_key_state_function",
                        lambda: lambda code: -32768 if code in pressed else 0)
    states = iter([{key}, {key}, set(), {key}])
    stop_after = StopAfter(4)

    def wait(timeout=None):
        pressed.clear()
        pressed.update(next(states, set()))
        return stop_after.wait(timeout)

    hotkey_control.HotkeyControl()._HotkeyControl__update_loop(SimpleNamespace(wait=wait))
    assert ran == ["overlay_lock"]  # only pressed again after release


def test_show_main_window(monkeypatch):
    from PySide6.QtWidgets import QApplication

    shown = []

    class Window:
        def bring_to_front(self):
            shown.append(self)

    window = Window()
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: [object(), window, Window()]))
    command.hotkey_show_main_window()
    assert shown == [window]  # main window only, once
    assert "show_main_window" in dict(command.COMMANDS_GENERAL)


def test_main_window_brought_to_front(ui_env, monkeypatch):
    from types import SimpleNamespace

    from neopedal.ui import app as app_module

    calls = []
    window = SimpleNamespace(show_app=lambda: calls.append("show"), raise_=lambda: calls.append("raise"))
    monkeypatch.setattr(app_module, "force_foreground", lambda widget: calls.append("foreground"))
    app_module.AppWindow.bring_to_front(window)  # type: ignore[arg-type]
    assert calls == ["show", "raise", "foreground"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows foreground lock only")
def test_force_foreground_no_op_off_windows():
    from neopedal.ui import app as app_module

    app_module.force_foreground(None)  # never reads window


def test_held_controller_buttons():
    from neopedal.hotkey.common import held_controller_buttons
    from neopedal.hotkey.joystick import joystick_code

    keymap = {"a": 65, "joy1_button_1": joystick_code(0, 0), "joy1_button_2": joystick_code(0, 1)}
    pressed = {65, joystick_code(0, 1)}
    assert held_controller_buttons(lambda code: code in pressed, keymap) == {joystick_code(0, 1)}  # keyboard aside
