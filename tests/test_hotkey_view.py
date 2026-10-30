"""Hotkeys page: list, enable switch, preset names, clear all, key capture (keys, controller buttons, held modifiers,
duplicates, preset), app keys kept while capturing, global hotkeys off only while capturing"""

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from neopedal.const_app import PLATFORM
from neopedal.setting import cfg
from neopedal.template.setting_shortcuts import SHORTCUTS_PRESET


@pytest.fixture
def backend(ui_env, monkeypatch):
    """Hotkeys page backend (shown), hotkey control & config saving recorded"""
    from neopedal.ui.quick import hotkey_backend

    calls = []
    for action in ("reload", "enable", "disable"):
        monkeypatch.setattr(type(hotkey_backend.kctrl), action, lambda self, _action=action: calls.append(_action))
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: calls.append("save"))
    page = hotkey_backend.HotkeyBackend(None)
    page.page_shown()
    yield page, calls
    page.release()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def rows(page) -> dict[str, dict]:
    return {row["key"]: row for row in page.model.rows if not row["header"]}


def test_list_and_enable_switch(backend):
    page, calls = backend
    assert len(rows(page)) == len(cfg.user.shortcuts) == page.totalCount
    cfg.application["enable_global_hotkey"] = False
    page.refresh()
    assert not page.enabled
    page.startCapture("overlay_lock")  # list disabled: no capture
    assert page.captureKey == ""
    page.setEnabled(True)  # user switch
    assert cfg.application["enable_global_hotkey"] is True and "reload" in calls and page.enabled


def test_preset_names_checked(backend):
    page, calls = backend
    name = next(iter(SHORTCUTS_PRESET))
    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        json.dump({}, file)
    cfg.user.shortcuts[name]["preset"] = "race"
    other = list(SHORTCUTS_PRESET)[1]
    cfg.user.shortcuts[other]["preset"] = "deleted"
    cfg.application["enable_global_hotkey"] = True
    page.refresh()
    found = rows(page)
    assert found[name]["preset"] == "race" and found[name]["isPreset"]
    assert found[other]["preset"] == "" and cfg.user.shortcuts[other]["preset"] == ""  # missing file
    assert "save" in calls


def test_clear_all_with_undo(backend):
    page, calls = backend
    cfg.application["enable_global_hotkey"] = True
    option = next(iter(cfg.user.shortcuts))
    cfg.user.shortcuts[option]["bind"] = "ctrl+f1"
    page.refresh()
    notices = []
    page.notice.connect(lambda text, undoable: notices.append((text, undoable)))
    page.clearAll()  # no question: undone from the toast
    assert all(not options["bind"] for options in cfg.user.shortcuts.values())
    assert rows(page)[option]["binding"] == "" and "reload" in calls and notices[-1][1] and page.canUndo
    page.undo()
    assert cfg.user.shortcuts[option]["bind"] == "ctrl+f1" and not page.canUndo


@pytest.fixture
def capture(backend, monkeypatch):
    """Key capture of first preset shortcut, pressed keys scripted"""
    from neopedal.ui.quick import hotkey_backend

    page, calls = backend
    keys = []
    monkeypatch.setattr(hotkey_backend, "set_hotkey", lambda get_state: tuple(keys))
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: 0)
    monkeypatch.setattr(hotkey_backend.PLATFORM, "WINDOWS", True)
    cfg.application["enable_global_hotkey"] = True
    name = next(iter(SHORTCUTS_PRESET))
    cfg.user.shortcuts[name]["bind"] = ""
    page.refresh()
    page.startCapture(name)
    assert page.captureKey == name and page.capturing
    yield page, keys, name, calls
    page.cancelCapture()


def test_key_capture_and_save(capture):
    page, keys, name, _ = capture
    keys.extend(("CTRL", "F5"))
    page.read_keys()
    assert page.capturedBinding == "CTRL+F5" and "F5" in page.captureText
    page.setPresetIndex(0)
    page.saveCapture()
    assert cfg.user.shortcuts[name]["bind"] == "CTRL+F5" and cfg.user.shortcuts[name]["preset"] == ""
    assert page.captureKey == "" and not page.capturing
    assert rows(page)[name]["binding"] == "Ctrl + F5"  # list updated


def test_duplicate_key_shown_before_saving(capture):
    page, keys, name, _ = capture
    other = next(option for option in cfg.user.shortcuts if option != name)
    cfg.user.shortcuts[other]["bind"] = "ALT+F9"
    keys.extend(("ALT", "F9"))
    page.read_keys()
    assert page.captureConflict  # dialog names the action, its button says "Assign Anyway"
    page.clearCapture()
    assert page.capturedBinding == "" and page.presetIndex == 0 and page.captureConflict == ""


def test_hidden_page_ignores_keys(capture):
    page, keys, _, calls = capture
    page.page_hidden()
    assert not page.capturing and calls[-1] == "enable"  # global hotkeys back on, page left open behind
    keys.extend(("CTRL", "A"))
    page.read_keys()
    assert page.capturedBinding == ""
    page.page_shown()
    assert page.capturing and calls[-1] == "disable"


def test_not_supported_text_on_linux(backend, monkeypatch):
    from neopedal.ui.quick import hotkey_backend

    page, _ = backend
    monkeypatch.setattr(hotkey_backend.PLATFORM, "WINDOWS", False)
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: 0)
    cfg.application["enable_global_hotkey"] = True
    cfg.user.shortcuts["overlay_lock"]["bind"] = ""
    page.startCapture("overlay_lock")
    assert "controller button" in page.captureText and "not supported" in page.captureText
    page.cancelCapture()
    assert PLATFORM is hotkey_backend.PLATFORM


def test_controller_button_held_at_start_ignored(backend, monkeypatch):
    """Button box switch held in a position never taken as the pressed button, until released & pressed"""
    from neopedal.hotkey.joystick import joystick_code
    from neopedal.ui.quick import hotkey_backend

    page, _ = backend
    switch, button = joystick_code(0, 0), joystick_code(0, 9)
    pressed = {switch}
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: int(code in pressed))
    cfg.application["enable_global_hotkey"] = True
    cfg.user.shortcuts["overlay_lock"]["bind"] = ""
    page.startCapture("overlay_lock")
    try:
        page.read_keys()
        assert page.capturedBinding == ""
        pressed.add(button)
        page.read_keys()
        assert page.capturedBinding == "joy1_button_10" and "Joy1 Button 10" in page.captureText
        pressed.clear()
        page.read_keys()  # switch released
        pressed.add(switch)
        page.read_keys()
        assert page.capturedBinding == "joy1_button_1"
    finally:
        page.cancelCapture()


def test_app_shortcuts_kept_from_app_while_capturing(backend, monkeypatch):
    """Ctrl+K, Ctrl+1, Alt, Enter... go to key capture only (any combination bindable), Esc still closes"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    from neopedal.ui.quick import hotkey_backend

    page, _ = backend
    capturing = [True]
    monkeypatch.setattr(hotkey_backend.HotkeyBackend, "capturing_keys", lambda self: capturing[0])

    def filtered(event_type, key, modifiers=Qt.KeyboardModifier.NoModifier):
        return page.eventFilter(None, QKeyEvent(event_type, key, modifiers))

    ctrl = Qt.KeyboardModifier.ControlModifier
    assert filtered(QEvent.Type.ShortcutOverride, Qt.Key.Key_K, ctrl)
    assert filtered(QEvent.Type.KeyPress, Qt.Key.Key_1, ctrl)
    assert filtered(QEvent.Type.KeyPress, Qt.Key.Key_Return)
    assert filtered(QEvent.Type.KeyRelease, Qt.Key.Key_Alt)
    assert not filtered(QEvent.Type.KeyPress, Qt.Key.Key_Escape)
    capturing[0] = False  # message box over it, or other window active
    assert not filtered(QEvent.Type.KeyPress, Qt.Key.Key_1, ctrl)


def test_capturing_keys_needs_page_window_active(backend, monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget

    from neopedal.ui.quick import hotkey_backend

    page, _ = backend
    window = QWidget()
    page._window = lambda: window
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: 0)
    cfg.application["enable_global_hotkey"] = True
    page.startCapture("overlay_lock")
    try:
        monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: window))
        assert page.capturing_keys()
        monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
        assert not page.capturing_keys()
    finally:
        page.cancelCapture()
        window.deleteLater()


def test_held_modifiers_shown_while_waiting_for_key(backend, monkeypatch):
    from neopedal.ui.quick import hotkey_backend

    page, _ = backend
    pressed = set()
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: int(code in pressed))
    monkeypatch.setattr(hotkey_backend, "held_modifiers",
                        lambda get_state: [name for name, code in (("ctrl", 17), ("shift", 16)) if get_state(code)])
    monkeypatch.setattr(hotkey_backend, "set_hotkey", lambda get_state: ("ctrl", "", "", "f5") if get_state(116) else ())
    cfg.application["enable_global_hotkey"] = True
    cfg.user.shortcuts["overlay_lock"]["bind"] = ""
    page.startCapture("overlay_lock")
    try:
        pressed.update((17, 16))
        page.read_keys()
        assert page.captureText == "Ctrl + Shift + …" and page.capturedBinding == ""
        pressed.add(116)
        page.read_keys()
        assert page.capturedBinding == "ctrl+f5"
        pressed.clear()
        page.read_keys()
        assert page.captureText == "Ctrl + F5"  # captured combo kept once released
    finally:
        page.cancelCapture()


def test_hotkeys_disabled_only_while_capturing(backend, monkeypatch):
    from neopedal.ui.quick import hotkey_backend

    page, calls = backend
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: 0)
    cfg.application["enable_global_hotkey"] = True
    calls.clear()
    page.startCapture("overlay_lock")
    assert calls == ["disable"]
    page.page_hidden()  # page left open behind another page
    assert calls == ["disable", "enable"]
    page.page_shown()
    assert calls[-1] == "disable"
    page.cancelCapture()
    assert calls[-1] == "enable"
