"""Key bindings page: list, enable toggle, preset names, clear all, key binding input (capture, duplicates, preset)"""

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimerEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.const_app import PLATFORM
from tinypedal.setting import cfg
from tinypedal.template.setting_shortcuts import SHORTCUTS_PRESET


@pytest.fixture
def page(ui_env, monkeypatch):
    """Key bindings page, hotkey control & config saving recorded"""
    from tinypedal.ui import hotkey_view

    calls = []
    for action in ("reload", "enable", "disable"):
        monkeypatch.setattr(type(hotkey_view.kctrl), action, lambda self, _action=action: calls.append(_action))
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: calls.append("save"))
    widget = hotkey_view.HotkeyList(None)
    yield widget, calls
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def items(widget):
    from tinypedal.ui.hotkey_view import HotkeyConfigItem

    found = {}
    for row in range(widget.listbox_hotkey.count()):
        item_widget = widget.listbox_hotkey.itemWidget(widget.listbox_hotkey.item(row))
        if isinstance(item_widget, HotkeyConfigItem):
            found[item_widget.option_name] = (widget.listbox_hotkey.item(row), item_widget)
    return found


def test_list_and_enable_toggle(page):
    widget, calls = page
    assert len(items(widget)) == len(cfg.user.shortcuts)
    cfg.application["enable_global_hotkey"] = False
    widget.refresh()
    assert not widget.listbox_hotkey.isEnabled() and not widget.button_toggle.isChecked()
    widget.button_toggle.setChecked(True)  # user enables
    assert cfg.application["enable_global_hotkey"] is True and "reload" in calls
    widget.refresh()
    assert widget.listbox_hotkey.isEnabled()


def test_preset_names_checked(page):
    widget, _ = page
    name = next(iter(SHORTCUTS_PRESET))
    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        json.dump({}, file)
    cfg.user.shortcuts[name]["preset"] = "race"
    other = list(SHORTCUTS_PRESET)[1]
    cfg.user.shortcuts[other]["preset"] = "deleted"
    cfg.application["enable_global_hotkey"] = True
    widget.refresh()
    found = items(widget)
    assert found[name][0].text().endswith(": race")
    assert found[other][0].text().endswith(": -") and cfg.user.shortcuts[other]["preset"] == ""  # missing file


def test_clear_all(page, monkeypatch):
    widget, calls = page
    option = next(iter(cfg.user.shortcuts))
    cfg.user.shortcuts[option]["bind"] = "CTRL+F1"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    widget.reset_hotkey()
    assert all(not options["bind"] for options in cfg.user.shortcuts.values())
    assert items(widget)[option][1].button_config.text().strip() != "CTRL + F1" and "reload" in calls


@pytest.fixture
def binding(page, monkeypatch):
    """Key binding input of first preset shortcut, pressed keys scripted"""
    from tinypedal.ui import hotkey_view

    keys = []
    monkeypatch.setattr(hotkey_view, "set_hotkey_win", lambda get_state: tuple(keys))
    monkeypatch.setattr(hotkey_view.PLATFORM, "WINDOWS", True)
    name = next(iter(SHORTCUTS_PRESET))
    cfg.user.shortcuts[name]["bind"] = ""
    reloaded = []
    dialog = hotkey_view.ConfigHotkey(None, option_name=name, hotkey_name="", reload_func=lambda: reloaded.append(1))
    dialog.show()
    yield dialog, keys, name, reloaded
    if dialog.__dict__:
        dialog.close()


def test_key_capture_and_save(binding):
    dialog, keys, name, reloaded = binding
    keys.extend(("CTRL", "F5"))
    dialog.timerEvent(QTimerEvent(0))
    assert dialog.temp_hotkey == "CTRL+F5" and "F5" in dialog.hotkey_entry.text()
    dialog.preset_selector.setCurrentIndex(0)
    dialog.saving()
    assert cfg.user.shortcuts[name]["bind"] == "CTRL+F5" and cfg.user.shortcuts[name]["preset"] == ""
    assert reloaded  # list item updated


def test_duplicate_key_asks(binding, monkeypatch):
    dialog, keys, name, _ = binding
    other = next(option for option in cfg.user.shortcuts if option != name)
    cfg.user.shortcuts[other]["bind"] = "ALT+F9"
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Cancel))
    keys.extend(("ALT", "F9"))
    dialog.timerEvent(QTimerEvent(0))
    dialog.saving()  # cancelled: kept open, not saved
    assert cfg.user.shortcuts[name]["bind"] == "" and dialog.__dict__
    dialog.reset()
    assert dialog.temp_hotkey == "" and dialog.preset_selector.currentIndex() == 0


def test_hidden_input_ignores_keys(binding):
    dialog, keys, _, _ = binding
    dialog.hide()
    keys.extend(("CTRL", "A"))
    dialog.timerEvent(QTimerEvent(0))
    assert dialog.temp_hotkey == ""


def test_not_supported_text_on_linux(page, monkeypatch):
    from tinypedal.ui import hotkey_view

    monkeypatch.setattr(hotkey_view.PLATFORM, "WINDOWS", False)
    dialog = hotkey_view.ConfigHotkey(None, option_name="overlay_lock", hotkey_name="", reload_func=lambda: None)
    assert "not supported" in dialog.hotkey_entry.text()
    dialog.close()
    assert PLATFORM is hotkey_view.PLATFORM
