"""Application UI improvements (phase 2, package C2): unsaved changes marker & Ctrl+S, inline
validation of config pages, preset trash with undo, skip update version & download progress,
remaining English texts, keyboard focus of new controls"""

import hashlib
import io
import json
import os
import threading
import time
import warnings
from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QSystemTrayIcon

from tinypedal import app_signal, i18n, update
from tinypedal.const_file import ConfigType
from tinypedal.setting import cfg


def flush_deleted():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return condition()


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


@pytest.fixture
def answers(monkeypatch):
    """Message boxes recorded, questions answered with answers.reply"""

    class Answers:
        reply = QMessageBox.StandardButton.Yes
        warnings: list = []
        questions: list = []

    found = Answers()
    found.warnings, found.questions = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda parent, title, text, *a, **k: found.warnings.append(text)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))

    def question(parent, title, text, *args, **kwargs):
        found.questions.append(text)
        return found.reply

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return found


@pytest.fixture
def window(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    view = main.centralWidget()
    for page in view.dialog_pages():
        if page.dialog is not None:
            with suppress(AttributeError):
                page.dialog.set_unmodified()
            with suppress(AttributeError):
                page.dialog.saved_state = page.dialog.history.capture()
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
            with suppress(RuntimeError, TypeError):
                signal.disconnect()
    main.deleteLater()
    flush_deleted()


def open_tool_page(window, path: str):
    from tinypedal.ui.tools_view import open_tool

    open_tool(path, window)
    view = window.centralWidget()
    name = path.rsplit(".", 1)[-1]
    return next(page for page in view.dialog_pages() if type(page.dialog).__name__ == name)


def open_config_page(window, name="speedometer", config_type=ConfigType.WIDGET, user_setting=None, default=None):
    from tinypedal.ui.config import UserConfig

    UserConfig(parent=window, key_name=name, preset_name=cfg.filename.setting, config_type=config_type,
               user_setting=user_setting if user_setting is not None else cfg.user.setting,
               default_setting=default if default is not None else cfg.default.setting,
               reload_func=lambda: None).open()
    view = window.centralWidget()
    return next(page for page in view.dialog_pages() if getattr(page.dialog, "key_name", "") == name)


# --- Item 1: unsaved changes marker, Ctrl+S
def test_editor_page_marker_title_and_open_pages(window):
    from tinypedal.ui._common import MODIFIED_MARKER

    view = window.centralWidget()
    page = open_tool_page(window, "brake_editor.BrakeEditor")
    editor = page.dialog
    label = page.findChild(QLabel, "dialogPageTitle")
    assert not label.text().startswith(MODIFIED_MARKER) and page.display_title() == page.title
    editor.set_modified()
    assert label.text() == f"{MODIFIED_MARKER}{page.title}" and page.display_title().startswith(MODIFIED_MARKER)
    assert "Unsaved changes: 1" in view._button_pages.toolTip()
    editor.set_unmodified()
    assert label.text() == page.title and "Unsaved" not in view._button_pages.toolTip()
    assert page.title == "Brake Editor"  # page title (and its matching) never carries the marker


def test_undo_back_to_saved_state_keeps_marker_logic(window):
    page = open_tool_page(window, "heatmap_editor.HeatmapEditor")
    editor = page.dialog
    editor.set_modified()
    assert page.is_modified()
    editor.undo()  # restored state still counts as edited until saved
    assert page.is_modified() == editor.is_modified()


def test_rail_tool_entry_marker(window):
    from tinypedal.ui._common import MODIFIED_MARKER
    from tinypedal.ui.app import NavButton

    page = open_tool_page(window, "race_calculator.RaceCalculator")
    button = window.findChild(NavButton, "railTool:race_calculator.RaceCalculator")
    assert not button.modified
    page.dialog.set_modified()
    assert button.modified and button.toolTip().startswith(MODIFIED_MARKER)
    image_marked = button.grab().toImage()
    page.dialog.set_unmodified()
    assert not button.modified and not button.toolTip().startswith(MODIFIED_MARKER)
    assert button.grab().toImage() != image_marked  # label drawn with marker


def test_rail_marker_kept_after_rail_rebuilt(window):
    from tinypedal.ui.app import NavButton

    page = open_tool_page(window, "race_calculator.RaceCalculator")
    page.dialog.set_modified()
    window.centralWidget().build_rail_items()
    button = window.findChild(NavButton, "railTool:race_calculator.RaceCalculator")
    assert button.modified
    page.dialog.set_unmodified()


def save_shortcut(widget) -> QShortcut:
    return next(
        shortcut for shortcut in widget.findChildren(QShortcut)
        if shortcut.key() == QKeySequence(QKeySequence.StandardKey.Save) and shortcut.parent() is widget)


@pytest.fixture
def saved(ui_env):
    """Config types saved (ui_env records saves)"""
    return ui_env


def test_ctrl_s_saves_editor_page(window, saved, monkeypatch):
    from tinypedal.ui._common import BaseEditor

    monkeypatch.setattr(BaseEditor, "reloading", staticmethod(lambda *args, **kwargs: None))
    page = open_tool_page(window, "brake_editor.BrakeEditor")
    editor = page.dialog
    editor.set_modified()
    save_shortcut(window).activated.emit()  # main window Ctrl+S: shown page
    assert not editor.is_modified() and not page.is_modified()
    assert ConfigType.BRAKES in saved
    assert window.centralWidget().dialog_pages()  # Apply: page kept open


def test_ctrl_s_config_page_saves_and_clears_marker(window, saved):
    page = open_config_page(window)
    dialog = page.dialog
    editor = dialog.option_edit["font_size"]
    editor.setText(str(int(editor.text()) + 3))
    assert dialog.is_modified() and page.is_modified()
    assert window.save_current_page()
    assert not page.is_modified()
    assert cfg.user.setting["speedometer"]["font_size"] == int(editor.text())
    assert window.centralWidget().dialog_pages()  # kept open


def test_ctrl_s_without_save_action(window):
    view = window.centralWidget()
    assert not window.save_current_page()  # app page (home): nothing to save
    open_tool_page(window, "preset_compare.PresetCompare")
    view.set_current_index(0)
    assert not window.save_current_page()


def test_separate_window_has_own_save_shortcut(ui_env):
    from tinypedal.ui.brake_editor import BrakeEditor
    from tinypedal.ui.track_notes_editor import TrackNotesEditor

    editor = BrakeEditor(None)
    try:
        editor.show()
        assert editor.save_action() == editor.applying
        assert save_shortcut(editor) is not None
    finally:
        editor.set_unmodified()
        editor.close()
        flush_deleted()
    notes = TrackNotesEditor(None)
    try:
        assert notes.save_action() == notes.saving  # file name asked, editor kept open
    finally:
        notes.set_unmodified()
        notes.close()
        flush_deleted()


def test_font_config_marker(window, answers):
    from tinypedal.ui.config import FontConfig

    FontConfig(window, cfg.user.setting, lambda: None).open()
    page = window.centralWidget().dialog_pages()[-1]
    dialog = page.dialog
    dialog.edit_fontsize.setValue(2)
    assert page.is_modified()
    dialog.edit_fontsize.setValue(0)
    assert not page.is_modified()


# --- Item 2: inline validation of config pages
def test_option_limits_table():
    from tinypedal.ui.option_limits import NO_LIMIT, limit_error, option_limit

    assert option_limit("opacity").maximum == 1
    assert option_limit("web_dashboard_port") == option_limit("remote_control_port")
    assert option_limit("display_order_time_scale") is NO_LIMIT  # not a scale
    assert option_limit("minimum_update_interval").maximum == 1000
    assert option_limit("font_size_battery").integer
    assert limit_error("opacity", 1.5) == "Between 0 and 1"
    assert limit_error("opacity", 0.5) == ""
    assert limit_error("font_size", 12.5) == "Whole number required"
    assert limit_error("bar_gap", -1) == "Minimum 0"
    assert limit_error("unknown_option", -1e9) == ""


def test_default_values_within_limits():
    """Every default option value is valid, so a fresh preset never shows errors"""
    from tinypedal.ui.option_limits import limit_error

    cfg.default.set_default()
    bad = [
        (section, key, value)
        for name in ("config", "setting")
        for section, options in dict(getattr(cfg.default, name)).items() if isinstance(options, dict)
        for key, value in options.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool) and limit_error(key, value)
    ]
    assert not bad


def test_invalid_value_marked_inline(window, answers):
    page = open_config_page(window)
    dialog = page.dialog
    opacity = dialog.option_edit["opacity"]
    opacity.setText("1.5")
    assert dialog.option_errors == {"opacity": "Between 0 and 1"}
    assert opacity.property("invalid") is True
    mark = dialog.error_marks["opacity"]
    assert not mark.isHidden() and "Between 0 and 1" in mark.text() and "Opacity" in mark.toolTip()
    assert not dialog.button_save.isEnabled() and not dialog.button_apply.isEnabled()
    assert not dialog.label_invalid.isHidden() and "1 invalid" in dialog.label_invalid.text()
    assert dialog.save_setting() is False and not answers.warnings  # no modal: shown inline
    assert window.focusWidget() in (opacity, None)
    font_size = dialog.option_edit["font_size"]
    font_size.setText("12.5")
    assert dialog.option_errors["font_size"] == "Whole number required"
    font_size.setText("abc")
    assert dialog.option_errors["font_size"] == "Number required"
    font_size.setText("14")
    opacity.setText("0.8")
    assert not dialog.option_errors and opacity.property("invalid") is False and mark.isHidden()
    assert dialog.button_save.isEnabled() and dialog.label_invalid.isHidden()
    assert dialog.save_setting()
    assert cfg.user.setting["speedometer"]["opacity"] == 0.8


def test_invalid_color_and_reason_translated(window, french):
    page = open_config_page(window, "notification", ConfigType.CONFIG, cfg.user.config, cfg.default.config)
    dialog = page.dialog
    key = "font_color_locked_preset"
    dialog.option_edit[key].setText("#12")
    assert dialog.option_errors[key].startswith("Color as")
    assert "Couleur au format" in dialog.error_marks[key].text()
    page = open_config_page(window)
    speedometer = page.dialog
    speedometer.option_edit["opacity"].setText("3")
    speedometer.option_edit["font_size"].setText("0")
    assert "Entre 0 et 1" in speedometer.error_marks["opacity"].text()
    assert "Corrigez 2 valeur(s)" in speedometer.label_invalid.text()
    dialog.option_edit[key].setText("#123")
    speedometer.option_edit["opacity"].setText("1")
    speedometer.option_edit["font_size"].setText("15")


def test_save_reveals_hidden_invalid_option(window, answers):
    """Invalid option in a collapsed section or hidden by search is shown when saving"""
    page = open_config_page(window)
    dialog = page.dialog
    dialog.edit_search.setText("font")
    assert dialog.option_edit["opacity"].isHidden()
    dialog.option_edit["opacity"].setText("-1")
    assert dialog.error_marks["opacity"].isHidden()  # row hidden by search
    assert not dialog.save_setting()
    assert dialog.edit_search.text() == "" and not dialog.option_edit["opacity"].isHidden()
    assert not dialog.error_marks["opacity"].isHidden()
    dialog.option_edit["opacity"].setText("1")


def test_path_options_checked_when_saving_only(window, answers):
    """Folder path validation creates the folder: not checked while typing, modal kept"""
    page = open_config_page(window, "user_path", ConfigType.CONFIG, cfg.user.config, cfg.default.config)
    dialog = page.dialog
    editor = dialog.option_edit["settings_path"]
    editor.setText("   ")
    assert "settings_path" not in dialog.option_errors and dialog.button_save.isEnabled()
    assert dialog.save_setting() is False and answers.warnings  # modal fallback
    editor.setText(cfg.user.config["user_path"]["settings_path"])


def test_global_config_title_and_hidden_options(window):
    from tinypedal.ui.config import HIDDEN_OPTIONS

    assert "skipped_update_version" in HIDDEN_OPTIONS["application"]
    page = open_config_page(window, "application", ConfigType.CONFIG, cfg.user.config, cfg.default.config)
    assert "skipped_update_version" not in page.dialog.option_edit
    assert "number_of_days_to_keep_deleted_presets" in page.dialog.option_edit
    assert page.title.endswith("(global)")


def test_choice_lists_translated_value_kept(window, french):
    page = open_config_page(window, "application", ConfigType.CONFIG, cfg.user.config, cfg.default.config)
    dialog = page.dialog
    combo = dialog.option_edit["window_color_theme"]
    combo.setCurrentText("Modern Light")
    assert combo.currentText() == i18n.tr("Modern Light") != "Modern Light"
    assert combo.validate() == "Modern Light"  # English value saved
    texts = [combo.itemText(index) for index in range(combo.count())]
    assert texts == ["Moderne sombre", "Moderne clair", "Classique sombre", "Classique clair"]
    language = dialog.option_edit["language"]
    assert language.validate() in i18n.LANGUAGES  # names never translated
    combo.reset_to_default()
    assert combo.validate() == cfg.default.config["application"]["window_color_theme"]


def test_choice_undo_restores_translated_choice(window, french):
    page = open_config_page(window, "application", ConfigType.CONFIG, cfg.user.config, cfg.default.config)
    dialog = page.dialog
    combo = dialog.option_edit["window_color_theme"]
    before = combo.validate()
    combo.setCurrentText("Legacy Light" if before != "Legacy Light" else "Modern Light")
    dialog.history.undo()
    assert combo.validate() == before and not page.is_modified()


# --- Item 3: preset trash with undo
def write_preset(name: str):
    with open(f"{cfg.path.settings}{name}", "w", encoding="utf-8") as file:
        json.dump({"speedometer": {"enable": True}}, file)


def test_trash_move_list_restore_purge(tmp_path):
    from tinypedal.userfile import preset_trash

    settings = f"{tmp_path.as_posix()}/"
    (tmp_path / "race.json").write_text("{}", encoding="utf-8")
    (tmp_path / "race.layouts").write_text("{}", encoding="utf-8")
    entry = preset_trash.move_to_trash(settings, "race.json", {"tracks": ["Spa"]})
    assert not (tmp_path / "race.json").exists() and not (tmp_path / "race.layouts").exists()
    assert os.path.isdir(entry.folder) and entry.name == "race"
    listed = preset_trash.list_trash(settings)
    assert len(listed) == 1 and listed[0].references == {"tracks": ["Spa"]}
    # Name used meanwhile: restored with free name
    (tmp_path / "RACE.json").write_text("{}", encoding="utf-8")
    assert preset_trash.free_preset_name(settings, "race.json") == "race (2).json"
    with pytest.raises(FileExistsError):
        preset_trash.restore_from_trash(settings, listed[0])
    assert preset_trash.restore_from_trash(settings, listed[0], "race (2).json") == "race (2).json"
    assert (tmp_path / "race (2).json").exists() and (tmp_path / "race (2).layouts").exists()
    assert not preset_trash.list_trash(settings) and not os.path.exists(entry.folder)
    # Purge by age, invalid entries too
    old = preset_trash.move_to_trash(settings, "race (2).json")
    (tmp_path / "trash" / "broken").mkdir()
    assert preset_trash.purge_trash(settings, 30) == 0  # recent
    assert preset_trash.purge_trash(settings, 30, now=time.time() + 31 * 86400) == 2
    assert not os.path.exists(old.folder)
    with pytest.raises(FileNotFoundError):
        preset_trash.move_to_trash(settings, "missing.json")


def test_trash_failed_move_leaves_no_entry(tmp_path, monkeypatch):
    from tinypedal.userfile import preset_trash

    settings = f"{tmp_path.as_posix()}/"
    (tmp_path / "race.json").write_text("{}", encoding="utf-8")

    def locked(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(preset_trash.os, "replace", locked)
    with pytest.raises(OSError):
        preset_trash.move_to_trash(settings, "race.json")
    assert (tmp_path / "race.json").exists() and not os.listdir(tmp_path / "trash")


@pytest.fixture
def preset_page(ui_env, answers, monkeypatch):
    from tinypedal.ui import preset_view

    for name in ("race.json", "practice.json"):
        write_preset(name)
    toasts = []
    monkeypatch.setattr(preset_view, "show_toast", lambda *args, **kwargs: toasts.append((args, kwargs)))
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": "practice"}}
    cfg.user.tracks = {"Spa": {"preset": "practice"}}
    cfg.user.filelock = {}
    cfg.user.shortcuts["preset_1"]["preset"] = "practice"
    widget = preset_view.PresetList(None)
    widget.backend.set_active(True)  # presets read while page is shown
    widget.toasts = toasts
    yield widget
    widget.deleteLater()
    flush_deleted()


def test_delete_moves_to_trash_and_undo_restores_references(preset_page):
    from tinypedal.userfile.preset_trash import list_trash

    assert preset_page.delete_preset("practice.json")
    assert not os.path.exists(f"{cfg.path.settings}practice.json")
    assert [entry.name for entry in list_trash(cfg.path.settings)] == ["practice"]
    assert cfg.user.tracks["Spa"]["preset"] == "" and cfg.user.classes["GT3"]["preset"] == ""
    assert cfg.user.shortcuts["preset_1"]["preset"] == ""
    args, kwargs = preset_page.toasts[-1]
    assert "moved to trash" in args[1] and kwargs["action_text"] and callable(kwargs["action"])
    assert preset_page.shortcut_undo.isEnabled()
    cfg.user.classes["GT3"]["preset"] = "race"  # set to another preset meanwhile: kept
    kwargs["action"]()  # undo button of toast
    assert os.path.exists(f"{cfg.path.settings}practice.json") and not list_trash(cfg.path.settings)
    assert cfg.user.tracks["Spa"]["preset"] == "practice" and cfg.user.shortcuts["preset_1"]["preset"] == "practice"
    assert cfg.user.classes["GT3"]["preset"] == "race"
    assert not preset_page.shortcut_undo.isEnabled()
    assert not preset_page.undo_delete()  # nothing left to undo


def test_ctrl_z_undoes_last_delete(preset_page):
    assert preset_page.delete_preset("race.json")
    shortcut = preset_page.shortcut_undo
    assert shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    shortcut.activated.emit()
    assert os.path.exists(f"{cfg.path.settings}race.json")


def test_undo_after_preset_removed_from_trash(preset_page):
    from tinypedal.userfile.preset_trash import list_trash, remove_entry

    preset_page.delete_preset("race.json")
    remove_entry(list_trash(cfg.path.settings)[0])
    assert not preset_page.undo_delete()
    assert not os.path.exists(f"{cfg.path.settings}race.json")


def test_loaded_preset_still_refused(preset_page, answers, monkeypatch):
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    preset_page.backend.remove("race.json")
    assert os.path.exists(f"{cfg.path.settings}race.json") and answers.warnings


def test_trash_dialog_restore_delete_empty(ui_env, answers, monkeypatch):
    from tinypedal.ui import preset_management
    from tinypedal.userfile.preset_trash import list_trash

    monkeypatch.setattr(preset_management, "show_toast", lambda *args, **kwargs: None)
    cfg.user.tracks = {"Spa": {"preset": "race"}}
    for name in ("race.json", "practice.json", "qualy.json"):
        write_preset(name)
        preset_management.trash_preset(name)
    write_preset("race.json")  # new preset with same name meanwhile
    dialog = preset_management.PresetTrash(None)
    try:
        assert dialog.listbox_trash.count() == 3 and "day(s) left" in dialog.listbox_trash.item(0).text()
        row = next(row for row, entry in enumerate(dialog.entries) if entry.name == "race")
        dialog.listbox_trash.setCurrentRow(row)
        dialog.restore()
        assert os.path.exists(f"{cfg.path.settings}race (2).json")
        assert cfg.user.tracks["Spa"]["preset"] == "race (2)"  # reference set again, to restored name
        assert dialog.listbox_trash.count() == 2
        answers.reply = QMessageBox.StandardButton.No
        dialog.delete()
        assert dialog.listbox_trash.count() == 2  # cancelled
        answers.reply = QMessageBox.StandardButton.Yes
        dialog.delete()
        assert dialog.listbox_trash.count() == 1 and len(list_trash(cfg.path.settings)) == 1
        dialog.empty()
        assert dialog.listbox_trash.count() == 0 and not dialog.button_empty.isEnabled()
        assert not dialog.button_restore.isEnabled()
    finally:
        dialog.close()
        flush_deleted()


def test_trash_keep_days_option(ui_env):
    from tinypedal.ui.preset_management import days_left, trash_keep_days

    assert cfg.default.config["application"]["number_of_days_to_keep_deleted_presets"] == 30
    cfg.application["number_of_days_to_keep_deleted_presets"] = 7
    assert trash_keep_days() == 7
    cfg.application["number_of_days_to_keep_deleted_presets"] = 0  # invalid: default
    assert trash_keep_days() == 30
    now = time.time()
    assert days_left(now, 30, now) == 30 and days_left(now - 29.5 * 86400, 30, now) == 1
    assert days_left(now - 40 * 86400, 30, now) == 0
    cfg.application["number_of_days_to_keep_deleted_presets"] = 30


def test_action_toast_runs_once_and_stays_while_focused(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.toast import ActionToast, Toast, show_toast

    host = QWidget()
    host.resize(600, 400)
    calls = []
    try:
        assert isinstance(show_toast(host, "Plain"), Toast)
        toast = show_toast(host, "Deleted", action_text="Undo", action=lambda: calls.append(1))
        assert isinstance(toast, ActionToast) and toast.button.focusPolicy() != Qt.FocusPolicy.NoFocus
        toast.button.click()
        toast.button.click()
        assert calls == [1] and not toast.button.isEnabled()
        other = show_toast(host, "Deleted", action_text="Undo", action=lambda: None)
        other.is_busy = lambda: True  # hovered or focused: kept
        other.hide_if_idle()
        assert not other._hiding and other._timer.isActive()
        other.is_busy = lambda: False
        other.hide_if_idle()
        assert other._hiding
    finally:
        host.deleteLater()
        flush_deleted()


# --- Item 4: updates
ASSET = update.InstallerAsset("Setup.exe", "https://github.com/x/Setup.exe", "a" * 64)


@pytest.fixture
def updates(ui_env, monkeypatch):
    from tinypedal.ui import notification

    checker = update.update_checker
    monkeypatch.setattr(checker, "_update_available", True)
    monkeypatch.setattr(checker, "_disabled", False)
    monkeypatch.setattr(checker, "_manual_checking", False)
    monkeypatch.setattr(checker, "_last_checked_version", (99, 1, 2))
    monkeypatch.setattr(checker, "_last_checked_date", (2099, 1, 2))
    monkeypatch.setattr(checker, "installer", ASSET)
    monkeypatch.setattr(checker, "release_notes", "### Added\n\n- New")
    monkeypatch.setattr(notification, "can_auto_update", lambda: True)
    monkeypatch.setattr(notification, "is_portable_copy", lambda: False)
    monkeypatch.setattr(notification.UpdatesNotifyButton, "prompted_version", "")
    monkeypatch.setattr(notification.UpdatesNotifyButton, "dismissed_message", "")
    installer = notification.UpdateInstaller()
    monkeypatch.setattr(notification, "_update_installer", installer)
    cfg.application["skipped_update_version"] = 0
    yield installer
    cfg.application["skipped_update_version"] = 0


def test_version_number_and_skip(updates):
    assert update.version_number((2, 5, 13)) == 2_005_013
    assert not update.update_checker.is_skipped()
    update.skip_version((99, 1, 2))
    assert cfg.application["skipped_update_version"] == 99_001_002 and update.update_checker.is_skipped()
    update.update_checker._manual_checking = True  # checked by hand: shown anyway
    assert not update.update_checker.is_skipped()
    update.update_checker._manual_checking = False
    update.update_checker._last_checked_version = (99, 1, 3)  # newer version: shown
    assert not update.update_checker.is_skipped()


def test_skipped_version_not_shown_nor_prompted(updates, monkeypatch):
    from tinypedal.ui import notification

    prompts = []
    monkeypatch.setattr(notification.UpdatesNotifyButton, "prompt_update", lambda self: prompts.append(1))
    button = notification.UpdatesNotifyButton("")
    try:
        button.checking(False)
        assert button.isVisibleTo(button.parentWidget() or button) or not button.isHidden()
        assert prompts == [1] and button.skip_update.isVisible()
        button.skip()
        assert button.isHidden() and cfg.application["skipped_update_version"] == 99_001_002
        button.checking(False)
        assert button.isHidden() and prompts == [1]  # not shown, not asked again
        button.restore()
        assert button.isHidden()
        update.update_checker._last_checked_version = (99, 2, 0)
        button.checking(False)
        assert not button.isHidden() and prompts == [1, 1]  # newer version shown again
    finally:
        button.deleteLater()
        flush_deleted()


def test_release_notes_skip_button(updates):
    from tinypedal.ui import notification

    button = notification.UpdatesNotifyButton("")
    dialog = button.release_notes_dialog(prompt=True)
    try:
        assert not dialog.button_skip.isHidden()
        dialog.button_skip.click()
        assert cfg.application["skipped_update_version"] == 99_001_002 and button.isHidden()
    finally:
        dialog.deleteLater()
        button.deleteLater()
        flush_deleted()


class FakeResponse(io.BytesIO):
    """urlopen response with Content-Length header"""

    def __init__(self, data: bytes, length: bool = True):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))} if length else {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_download_progress_and_cancel(monkeypatch, tmp_path):
    content = b"x" * (1 << 18)
    digest = hashlib.sha256(content).hexdigest()
    asset = ASSET._replace(sha256=digest)
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda url, timeout=0: FakeResponse(content))
    reports = []
    path = update.download_installer(asset, str(tmp_path), progress=lambda *args: reports.append(args))
    assert os.path.exists(path) and reports[-1] == (len(content), len(content)) and len(reports) == 4
    os.remove(path)
    cancel = threading.Event()

    def cancel_after_first(received, total):
        cancel.set()

    with pytest.raises(update.DownloadCancelled):
        update.download_installer(asset, str(tmp_path), progress=cancel_after_first, cancelled=cancel)
    assert not list(tmp_path.iterdir())  # partial file removed
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda url, timeout=0: FakeResponse(content, length=False))
    reports.clear()
    update.download_installer(asset, str(tmp_path), progress=lambda *args: reports.append(args))
    assert reports[-1] == (len(content), 0)  # size unknown


def test_progress_text(french):
    from tinypedal.ui.notification import download_progress_text

    i18n.set_language("English")
    assert download_progress_text(12_300_000, 29_100_000) == "42% (12.3 / 29.1 MB)"
    assert download_progress_text(5_000_000, 0) == "5.0 MB"
    i18n.set_language("Français")
    assert download_progress_text(12_300_000, 29_100_000) == "42 % (12,3 / 29,1 Mo)"
    assert download_progress_text(5_000_000, 0) == "5,0 Mo"


def test_cancel_download_no_warning(updates, monkeypatch, answers):
    from tinypedal.ui import notification

    started = threading.Event()

    def download(asset, progress=None, cancelled=None):
        progress(1_000_000, 4_000_000)
        started.set()
        while not cancelled.is_set():
            time.sleep(0.005)
        raise update.DownloadCancelled("download cancelled")

    monkeypatch.setattr(notification, "download_installer", download)
    monkeypatch.setattr(notification, "main_window", lambda: None)
    button = notification.UpdatesNotifyButton("")
    button.install_update.setVisible(True)
    try:
        assert not updates.cancel()  # not downloading
        assert updates.download()
        assert started.wait(5)
        assert wait_for(lambda: updates.received == 1_000_000)
        assert "25%" in button.text() and "1.0 / 4.0 MB" in button.text()
        assert button.cancel_download.isVisible()
        assert updates.cancel()
        assert wait_for(lambda: not updates.busy)
        assert not answers.warnings and not button.cancel_download.isVisible()
    finally:
        updates.cancel()
        button.deleteLater()
        flush_deleted()


def test_release_notes_page_shows_progress(updates, monkeypatch):
    from tinypedal.ui import notification

    downloads = []
    monkeypatch.setattr(updates, "download", lambda auto_install=False: downloads.append(auto_install) or True)
    button = notification.UpdatesNotifyButton("")
    dialog = button.release_notes_dialog(prompt=True)
    closed = []
    dialog.finished.connect(lambda *_: closed.append(1))
    try:
        assert dialog.download_box.isHidden()
        dialog.button_install.click()
        assert downloads and downloads[-1] is True and not closed  # page kept open
        updates.busy = True
        updates.busy_changed.emit(True)
        updates.progress.emit(2_000_000, 4_000_000)
        assert not dialog.download_box.isHidden() and not dialog.button_install.isEnabled()
        assert dialog.progress_bar.value() == 500 and "50%" in dialog.label_progress.text()
        cancels = []
        monkeypatch.setattr(updates, "cancel", lambda: cancels.append(1) or True)
        dialog.button_cancel.click()
        assert cancels == [1]
        updates.busy = False
        updates.busy_changed.emit(False)
        assert dialog.download_box.isHidden() and dialog.button_install.isEnabled()
    finally:
        dialog.deleteLater()
        button.deleteLater()
        flush_deleted()


def test_release_notes_opened_while_downloading(updates):
    from tinypedal.ui import notification

    updates.busy = True
    updates.received, updates.total = 1_000_000, 0
    button = notification.UpdatesNotifyButton("")
    dialog = button.release_notes_dialog()
    try:
        assert not dialog.download_box.isHidden() and dialog.progress_bar.maximum() == 0  # size unknown
        assert "1.0 MB" in dialog.label_progress.text()
    finally:
        updates.busy = False
        dialog.deleteLater()
        button.deleteLater()
        flush_deleted()


# --- Item 5: remaining English texts
def test_track_notes_labels_translated(ui_env, french, monkeypatch):
    from tinypedal.ui import track_notes_editor

    editor = track_notes_editor.TrackNotesEditor(None)
    try:
        headers = [editor.table_notes.horizontalHeaderItem(index).text()
                   for index in range(editor.table_notes.columnCount())]
        assert headers == ["Distance", "Note de pilotage", "Commentaire", "Étiquettes"]
        assert "notes de pilotage" in editor.status_bar.currentMessage()
        assert editor.filename_entry.placeholderText() == "Nom des notes de pilotage"
        replace = []
        monkeypatch.setattr(track_notes_editor, "TableBatchReplace", lambda parent, selector, table: type(
            "Dialog", (), {"open": lambda self: replace.append(selector)})())
        editor.open_replace_dialog()
        assert replace == [{"Note de pilotage": 1, "Commentaire": 2}]
        info = track_notes_editor.MetaDataEditor(editor, editor.notes_metadata, lambda: None)
        labels = {label.text() for label in info.findChildren(QLabel)}
        assert {"Titre :", "Auteur :", "Date :", "Description :"} <= labels
        info.close()
    finally:
        editor.set_unmodified()
        editor.close()
        flush_deleted()


def test_file_filters_translated_and_mapped_back(french):
    from tinypedal.const_file import FileFilter
    from tinypedal.ui._common import original_filter, translate_filter
    from tinypedal.userfile.track_notes import NOTESTYPE_TRACK, set_notes_filter

    notes_filter = set_notes_filter(NOTESTYPE_TRACK)
    shown = translate_filter(notes_filter)
    assert "Notes de piste Modern Tiny Pedals (*.tptn)" in shown and "Tous les fichiers (*.*)" in shown
    for original, translated in zip(notes_filter.split(";;"), shown.split(";;")):
        assert original_filter(notes_filter, translated) == original
    assert original_filter(notes_filter, "unknown") == "unknown"
    assert translate_filter(FileFilter.JSON) == "Fichier JSON (*.json)"


def test_brand_import_menu_and_transfer_headers_translated(ui_env, french):
    from tinypedal.ui.preset_management import ListHeader, PresetTransfer
    from tinypedal.ui.vehicle_brand_editor import VehicleBrandEditor

    editor = VehicleBrandEditor(None)
    transfer = PresetTransfer(None)
    try:
        actions = [action.text() for action in editor.button_import.menu().actions()]
        assert actions[:3] == ["API Rest RF2", "API Rest LMU (principale)", "API Rest LMU (alternative)"]
        titles = {label.text() for header in transfer.findChildren(ListHeader) for label in header.findChildren(QLabel)}
        assert titles == {"Choisir les réglages", "Choisir les types d'option"}
        option_texts = [transfer.listbox_options.itemWidget(transfer.listbox_options.item(row)).text()
                        for row in range(transfer.listbox_options.count())]
        assert "Autres options" in option_texts and "Polices" in option_texts
        keys = [transfer.listbox_options.itemWidget(transfer.listbox_options.item(row)).key_name
                for row in range(transfer.listbox_options.count())]
        assert "other_options" in keys  # keys kept for transfer
    finally:
        editor.set_unmodified()
        editor.close()
        transfer.close()
        flush_deleted()


def test_new_texts_translated(french):
    from tinypedal.i18n import tr, trm

    assert tr("Skip This Version") == "Ignorer cette version"
    assert tr("Unsaved changes") == "Modifications non enregistrées"
    assert trm("Unsaved changes: 2") == "Modifications non enregistrées : 2"
    assert trm("Preset <b>race</b> moved to trash") == "Preset <b>race</b> mis à la corbeille"
    assert trm("Delete all <b>3</b> preset(s) in trash permanently?<br><br>This cannot be undone!") == (
        "Supprimer définitivement les <b>3</b> preset(s) de la corbeille ?<br><br>Cette action est irréversible !")
    assert trm("Fix 1 invalid value(s) to save") == "Corrigez 1 valeur(s) invalide(s) pour enregistrer"
    assert trm("Deleted presets are kept for 30 day(s), then removed.").startswith("Les presets supprimés")
    assert trm("race · deleted 05/10/2026 10:00 · 29 day(s) left") == (
        "race · supprimé le 05/10/2026 10:00 · 29 jour(s) restant(s)")
    assert tr("Press a key or key combination").startswith("Appuyez")


# --- From package B2: safe mode keeps tool pages closed, plugin errors translated
def test_safe_mode_skips_reopening_pages(window, monkeypatch):
    import sys
    import types

    import tinypedal
    from tinypedal.ui import app as app_module

    view = window.centralWidget()
    restored = []
    monkeypatch.setattr(view, "restore_pages", lambda paths: restored.append(paths))
    cfg.application["remember_open_pages"] = True
    cfg.application["open_pages"] = "*heatmap_editor.HeatmapEditor"
    fake = types.ModuleType("tinypedal.safe_mode")
    fake.state = types.SimpleNamespace(enabled=True)
    monkeypatch.setitem(sys.modules, "tinypedal.safe_mode", fake)
    monkeypatch.setattr(tinypedal, "safe_mode", fake, raising=False)
    assert app_module.safe_mode_enabled()
    window.restore_open_pages()
    assert not restored and view.track_pages
    fake.state.enabled = False
    window.restore_open_pages()
    assert restored == [["*heatmap_editor.HeatmapEditor"]]
    cfg.application["open_pages"] = ""


def test_plugin_error_text_translated(ui_env, french, monkeypatch):
    from tinypedal.module_control import wctrl
    from tinypedal.ui import plugin_manager

    monkeypatch.setitem(plugin_manager.PLUGIN_ERRORS, "plugin_test", "Unexpected error")
    monkeypatch.setattr(type(wctrl), "names", property(lambda self: ("plugin_test",)), raising=False)
    kind, _, detail = plugin_manager.plugin_status_kind("plugin_test")
    assert kind == "error" and detail == i18n.tr("Unexpected error") != "Unexpected error"
    monkeypatch.setitem(plugin_manager.PLUGIN_ERRORS, "plugin_test", "SyntaxError: line 3")
    assert plugin_manager.plugin_status_kind("plugin_test")[2] == "SyntaxError: line 3"  # unknown: as is


# --- Item 6: keyboard reachable new controls, visible focus ring
def render(widget) -> QImage:
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    widget.render(image)
    return image


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_focus_ring_on_new_buttons(ui_env, monkeypatch, theme):
    from tinypedal.ui import has_keyboard_focus, set_style_palette, set_style_window
    from tinypedal.ui._common import FocusRingButton

    app = QApplication.instance()
    style_sheet = app.styleSheet()
    set_style_palette(theme)
    app.setStyleSheet(set_style_window(QApplication.font().pointSize()))
    button = FocusRingButton("Undo")
    try:
        assert button.focusPolicy() & Qt.FocusPolicy.TabFocus
        button.resize(button.sizeHint())
        before = render(button)
        monkeypatch.setattr(button, "hasFocus", lambda: True)
        button.window().setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, True)
        assert has_keyboard_focus(button)
        assert render(button) != before  # ring drawn
        button.window().setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, False)
        assert render(button) == before  # focus from mouse: no ring
    finally:
        button.deleteLater()
        app.setStyleSheet(style_sheet)
        set_style_palette("Dark")
        flush_deleted()


def test_new_controls_keyboard_reachable(ui_env, updates):
    from tinypedal.ui import notification
    from tinypedal.ui.preset_management import PresetTrash

    dialog = PresetTrash(None)
    button = notification.UpdatesNotifyButton("")
    notes = button.release_notes_dialog(prompt=True)
    try:
        for widget in (dialog.listbox_trash, dialog.button_restore, dialog.button_delete, dialog.button_empty,
                       notes.button_skip, notes.button_cancel):
            assert widget.focusPolicy() & Qt.FocusPolicy.TabFocus
    finally:
        dialog.close()
        notes.deleteLater()
        button.deleteLater()
        flush_deleted()


def test_release_notes_page_kept_by_language_change_still_installs(window, updates, monkeypatch):
    """What's new page waiting inside app kept by a language change: its Install & Skip buttons still work (was:
    connected to update button of replaced view, deleted with it: clicks did nothing)"""
    from tinypedal.ui.notification import UpdatesNotifyButton
    from tinypedal.ui.release_notes import ReleaseNotesDialog

    window.show()
    button = window.centralWidget().findChild(UpdatesNotifyButton)
    button.checking(False)  # update found: what's new page shown (prompt)
    flush_deleted()
    downloads = []
    monkeypatch.setattr(updates, "download", lambda auto_install=False: downloads.append(auto_install))
    language = cfg.application["language"]
    try:
        cfg.application["language"] = "Français"
        window.last_language = "Français"
        window.retranslate()
        flush_deleted()
        pages = [page for page in window.centralWidget().dialog_pages()
                 if isinstance(page.dialog, ReleaseNotesDialog)]
        assert len(pages) == 1
        pages[0].dialog.install_requested.emit()
        assert downloads == [True]
        pages[0].dialog.skip_requested.emit()
        assert cfg.application["skipped_update_version"] == 99_001_002
        assert window.centralWidget().findChild(UpdatesNotifyButton).isHidden()
    finally:
        cfg.application["language"] = language
        window.last_language = language
        window.retranslate()  # back to English for other tests
        flush_deleted()
