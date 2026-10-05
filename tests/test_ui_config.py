"""Config dialog & preset management UI tests (headless)"""

import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.setting import cfg


@pytest.fixture
def no_message_box(monkeypatch):
    shown = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *args, _name=name, **kwargs: shown.append((_name, args))))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    return shown


def close_dialog(dialog):
    """Discard edits, close & delete dialog now, so singleton dialog can be opened again"""
    if hasattr(dialog, "history"):
        dialog.saved_state = dialog.history.capture()  # no "save changes?" question
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def open_config(section, reload_calls, classic=True):
    """Widget config dialog, of classic layout (every option) unless classic is False"""
    from tinypedal.const_file import ConfigType
    from tinypedal.ui.config import UserConfig

    if "enable_classic_layout" in cfg.user.setting[section]:
        cfg.user.setting[section]["enable_classic_layout"] = classic
    return UserConfig(
        parent=None, key_name=section, preset_name="default.json", config_type=ConfigType.WIDGET,
        user_setting=cfg.user.setting, default_setting=cfg.default.setting,
        reload_func=lambda: reload_calls.append(section),
    )


def test_config_dialog_save(ui_env, no_message_box):
    reloads = []
    dialog = open_config("speedometer", reloads)
    try:
        dialog.option_edit["font_size"].setText("21")
        dialog.save_setting()
        assert cfg.user.setting["speedometer"]["font_size"] == 21
        assert reloads == ["speedometer"]
        assert "setting" in ui_env  # saved
    finally:
        close_dialog(dialog)


def test_config_dialog_modern_design_options(ui_env):
    """Modern design shows only options it reads: no per cell colors, column toggles shown"""
    dialog = open_config("relative", [], classic=False)
    try:
        shown = set(dialog.option_edit)
        assert "column_time_gap" in shown and "enable_classic_layout" in shown
        assert not any("color" in key for key in shown)
        assert "font_name" not in shown
        assert "display_order_position" in shown  # modern columns follow display order once changed
        assert dialog.has_display_order()  # button shown: modern design lists display order options
    finally:
        close_dialog(dialog)
    dialog = open_config("relative", [], classic=True)
    try:
        shown = set(dialog.option_edit)
        assert "font_color_position" in shown and "enable_classic_layout" in shown
        assert "column_time_gap" not in shown  # modern design only
    finally:
        close_dialog(dialog)


def test_config_dialog_invalid_value(ui_env, no_message_box):
    reloads = []
    dialog = open_config("speedometer", reloads)
    try:
        before = cfg.user.setting["speedometer"]["font_color_speed"]
        dialog.option_edit["font_color_speed"].setText("not a color")
        assert dialog.save_setting() is False
        assert cfg.user.setting["speedometer"]["font_color_speed"] == before
        # Phase 2 (package C2): shown next to the value (no message box), Save disabled
        assert reloads == [] and not no_message_box and "font_color_speed" in dialog.option_errors
        assert not dialog.button_save.isEnabled()
    finally:
        close_dialog(dialog)


def test_config_dialog_search_and_french(ui_env):
    from tinypedal.i18n import set_language

    set_language("Français")
    try:
        dialog = open_config("speedometer", [])
        labels = [
            dialog.layout_option.itemAtPosition(row, 0).widget().text()
            for row in range(dialog.layout_option.rowCount())
            if dialog.layout_option.itemAtPosition(row, 0)
        ]
        assert "Couleur du texte : vitesse" in labels
        dialog.edit_search.setText("couleur vitesse")
        shown = [key for key, editor in dialog.option_edit.items() if not editor.isHidden()]
        assert "font_color_speed" in shown and "update_interval" not in shown
        close_dialog(dialog)
    finally:
        set_language("English")


def test_every_widget_config_opens(ui_env):
    """All widget & module config dialogs build without error"""
    from tinypedal.module_control import mctrl, wctrl

    for name in (*wctrl.names, *mctrl.names):
        dialog = open_config(name, [])
        assert dialog.option_edit, name
        close_dialog(dialog)


def test_every_option_accepts_its_own_default(ui_env):
    """Each option must get an editor that accepts its default value.

    An option whose key matches no known pattern falls through to the number editor, so a
    string default (for example a "Left"/"Right" position) is then rejected on save with
    "Invalid value for ... option", and the whole dialog refuses to save.
    """
    from tinypedal.module_control import mctrl, wctrl

    rejected = []
    for name in (*wctrl.names, *mctrl.names):
        dialog = open_config(name, [])
        try:
            for key, editor in dialog.option_edit.items():
                if editor.validate() is None:
                    rejected.append(f"{name}.{key}")
        finally:
            close_dialog(dialog)
    assert not rejected, f"options rejected by their own editor: {rejected}"


def test_rename_preset_updates_references(ui_env, no_message_box, monkeypatch):
    from tinypedal.ui.preset_management import CreatePreset

    settings = cfg.path.settings
    for name in ("race.json", "race.json.backup-auto-2026-01-01", "race.json.backup-2026-02-02"):
        with open(f"{settings}{name}", "w", encoding="utf-8") as file:
            file.write("{}")
    cfg.user.tracks["Spa"] = {"preset": "race"}
    cfg.user.classes["GT3"] = {"alias": "GT3", "color": "#FFFFFF", "preset": "race"}
    monkeypatch.setattr(type(cfg), "is_loaded", lambda self, name: False)
    dialog = CreatePreset(None, "Rename", "rename", "race.json")
    dialog.preset_entry.setText("endurance")
    dialog.create_preset()
    assert os.path.exists(f"{settings}endurance.json")
    assert os.path.exists(f"{settings}endurance.json.backup-auto-2026-01-01")
    assert os.path.exists(f"{settings}endurance.json.backup-2026-02-02")
    assert cfg.user.tracks["Spa"]["preset"] == "endurance"
    assert cfg.user.classes["GT3"]["preset"] == "endurance"


def test_rename_locked_file_shows_error(ui_env, no_message_box, monkeypatch):
    from tinypedal.ui import preset_management

    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        file.write("{}")

    def locked(*args):
        raise PermissionError(13, "file used by another process")

    monkeypatch.setattr(preset_management.os, "rename", locked)
    dialog = preset_management.CreatePreset(None, "Rename", "rename", "race.json")
    dialog.preset_entry.setText("endurance")
    dialog.create_preset()  # must not raise
    assert no_message_box and no_message_box[0][0] == "warning"
    assert os.path.exists(f"{cfg.path.settings}race.json")


def test_duplicate_does_not_create_default(ui_env, no_message_box, monkeypatch):
    from tinypedal.ui.preset_management import CreatePreset

    created = []
    monkeypatch.setattr(type(cfg), "create", lambda self, filename: created.append(filename))
    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        file.write('{"speedometer": {"font_size": 30}}')
    dialog = CreatePreset(None, "Duplicate", "duplicate", "race.json")
    dialog.preset_entry.setText("race copy")
    dialog.create_preset()
    assert created == []
    with open(f"{cfg.path.settings}race copy.json", encoding="utf-8") as file:
        assert "30" in file.read()


def test_restart_command_keeps_arguments(monkeypatch):
    import sys

    from tinypedal import loader

    monkeypatch.setattr(sys, "argv", ["run.py", "-l", "2"])
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Python\python.exe")
    assert loader.restart_command() == [r"C:\Program Files\Python\python.exe", "run.py", "-l", "2"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\TinyPedal\tinypedal.exe")
    monkeypatch.setattr(sys, "argv", [r"C:\Program Files\TinyPedal\tinypedal.exe", "-s", "0"])
    assert loader.restart_command() == [r"C:\Program Files\TinyPedal\tinypedal.exe", "-s", "0"]


def test_atomic_write_removes_temp_on_error(tmp_path):
    from tinypedal.userfile import atomic_write

    target = tmp_path / "data.csv"
    with pytest.raises(ValueError), atomic_write(str(target)) as file:
        file.write("partial")
        raise ValueError("boom")
    assert list(tmp_path.iterdir()) == []


def test_preview_timer_stopped_when_dialog_deleted(ui_env):
    """Live preview timer must stop when widget is deleted with dialog, see WidgetPreview

    Otherwise timer event is sent to deleted widget (access violation once memory is reused).
    """
    dialog = open_config("speedometer", [])
    preview = dialog.preview  # Python object outlives C++ widget deleted with dialog
    assert preview._timer.isActive()
    close_dialog(dialog)
    assert not preview._timer.isActive()


def test_integer_option_rejects_decimal_without_crashing(ui_env):
    """Typing a decimal in an integer option must be reported as invalid, not raise.

    is_string_number() accepts decimals but int() cannot parse them, so the dialog used to
    crash with ValueError instead of showing "Invalid value for ... option".
    """
    from tinypedal.ui._option import IntegerEdit

    editor = IntegerEdit(None)
    editor.setText("10.5")
    assert editor.validate() is None
    editor.setText("10")
    assert editor.validate() == 10
    editor.setText("abc")
    assert editor.validate() is None


def test_unit_hint_shown_in_dialog(ui_env, no_message_box):
    """Pressure thresholds are typed in kPa; the editor shows what that is in the user's unit"""
    cfg.units["tyre_pressure_unit"] = "psi"
    dialog = open_config("black_box", [])
    try:
        editor = dialog.option_edit["tyre_pressure_target_minimum"]
        assert editor.placeholderText() == "23.21 psi"  # 160 kPa as stored
        editor.setText("200")
        assert editor.placeholderText() == "29.01 psi"  # follows what is typed
        plain = dialog.option_edit["tyre_wear_warning_threshold"]
        assert plain.placeholderText() == ""  # a percentage, no unit to convert
    finally:
        cfg.units["tyre_pressure_unit"] = "kPa"
        close_dialog(dialog)


def test_black_box_config_has_sections(ui_env):
    """Widgets with many options show section titles, in option order"""
    from tinypedal.template.widget import WIDGET_OPTION_SECTIONS
    from tinypedal.ui._option import OptionSection

    sections = WIDGET_OPTION_SECTIONS["black_box"]
    assert set(sections) <= set(cfg.default.setting["black_box"])  # every section starts at a real option
    dialog = open_config("black_box", [])
    try:
        titles = [label.text() for label in dialog.findChildren(OptionSection)]
        assert titles == list(sections.values())
    finally:
        close_dialog(dialog)


# --- Option tools for widgets with many options (black box)
def black_box_dialog():
    return open_config("black_box", [])


def row_of(dialog, key):
    return next(row for row in dialog.rows if row.key == key)


def test_simple_mode_hides_advanced_options(ui_env):
    dialog = black_box_dialog()
    try:
        assert not dialog.show_advanced
        assert dialog.option_edit["tyre_wear_warning_color"].isHidden()  # color: advanced
        assert not dialog.option_edit["show_tyre_pressure"].isHidden()  # on/off: basic
        assert not dialog.option_edit["display_scale"].isHidden()  # common option: basic
        dialog.check_advanced.setChecked(True)
        assert not dialog.option_edit["tyre_wear_warning_color"].isHidden()
    finally:
        close_dialog(dialog)


def test_sections_collapse_and_search_finds_hidden(ui_env):
    dialog = black_box_dialog()
    try:
        section = row_of(dialog, "show_tyre_pressure").section
        dialog.toggle_section(section)
        assert dialog.option_edit["show_tyre_pressure"].isHidden()
        assert not dialog.section_headers[section].isHidden()  # header stays to expand again
        dialog.edit_search.setText("wear warning color")  # advanced option, in its section
        assert not dialog.option_edit["tyre_wear_warning_color"].isHidden()
        dialog.edit_search.setText("")
        dialog.toggle_section(section)
        assert not dialog.option_edit["show_tyre_pressure"].isHidden()
    finally:
        close_dialog(dialog)


def test_dependent_options_greyed_out(ui_env):
    dialog = black_box_dialog()
    try:
        show = dialog.option_edit["show_tyre_pressure"]
        target = dialog.option_edit["enable_tyre_pressure_target"]
        minimum = dialog.option_edit["tyre_pressure_target_minimum"]
        show.setChecked(True)
        target.setChecked(True)
        assert minimum.isEnabled()
        target.setChecked(False)
        assert not minimum.isEnabled()
        target.setChecked(True)
        show.setChecked(False)  # grand parent off: whole chain greyed
        assert not target.isEnabled() and not minimum.isEnabled()
    finally:
        close_dialog(dialog)


def test_profile_overridden_options_marked(ui_env):
    dialog = black_box_dialog()
    try:
        dialog.option_edit["display_profile"].setCurrentText("Minimal")
        row = row_of(dialog, "show_tyre_pressure")
        assert not row.editor.isEnabled() and row.label.font().italic()
        assert "Minimal" in row.label.toolTip()
        dialog.option_edit["display_profile"].setCurrentText("Custom")
        assert row.editor.isEnabled() and not row.label.font().italic()
    finally:
        close_dialog(dialog)


def test_color_theme_applied_to_editors(ui_env):
    from tinypedal.template.widget.black_box_ui import BLACK_BOX_COLOR_THEMES, theme_color

    dialog = black_box_dialog()
    try:
        index = dialog.combo_theme.findData("Colorblind Safe")
        dialog.apply_color_theme(index)
        default = cfg.default.setting["black_box"]["wheel_lock_color"]
        expected = theme_color(default, BLACK_BOX_COLOR_THEMES["Colorblind Safe"])
        assert dialog.option_edit["wheel_lock_color"].text() == expected != default
        cone = dialog.option_edit["damage_panel_impact_cone_color"].text()
        assert cone.startswith("#CC") and len(cone) == 9  # alpha kept
        assert dialog.combo_theme.currentIndex() == 0
    finally:
        close_dialog(dialog)


def test_section_reset_only_resets_its_section(ui_env, monkeypatch):
    dialog = black_box_dialog()
    try:
        monkeypatch.setattr(dialog, "confirm_operation", lambda **kwargs: True)
        dialog.option_edit["wheel_lock_color"].setText("#123456")
        dialog.option_edit["tyre_wear_warning_color"].setText("#654321")
        dialog.reset_section(row_of(dialog, "wheel_lock_color").section)
        assert dialog.option_edit["wheel_lock_color"].text() == cfg.default.setting["black_box"]["wheel_lock_color"]
        assert dialog.option_edit["tyre_wear_warning_color"].text() == "#654321"
    finally:
        close_dialog(dialog)


def test_compound_target_table_editor(ui_env):
    from tinypedal.ui._option import CompoundTargetDialog, CompoundTargetEdit

    dialog = black_box_dialog()
    try:
        assert isinstance(dialog.option_edit["tyre_target_by_compound"], CompoundTargetEdit)
    finally:
        close_dialog(dialog)
    table = CompoundTargetDialog(None, "S=160-190/75-105; W=150-175")
    assert table.table.rowCount() == 2
    table.add_row(("m", 165, 195, None, None))
    table.add_row(("", "bad", 1, None, None))  # incomplete: dropped
    assert table.result_text() == "S=160-190/75-105; W=150-175; M=165-195"
    table.deleteLater()


def test_other_widgets_keep_plain_dialog(ui_env):
    dialog = open_config("speedometer", [])
    try:
        assert dialog.option_ui is None and dialog.show_advanced
        assert not hasattr(dialog, "check_advanced")
        assert all(not row.editor.isHidden() for row in dialog.rows)
    finally:
        close_dialog(dialog)


def test_live_preview_right_of_option_list(ui_env):
    from PySide6.QtCore import QCoreApplication

    for name in ("black_box", "speedometer"):
        dialog = open_config(name, [])
        try:
            dialog.resize(900, 600)
            dialog.show()
            QCoreApplication.processEvents()
            scroll = dialog.preview.parentWidget().findChildren(type(dialog.preview.scroll_area))[0]
            assert dialog.preview.x() > scroll.x() + scroll.width() // 2, name  # beside, on the right
            assert dialog.preview.height() > dialog.height() // 2, name  # as tall as the list
        finally:
            close_dialog(dialog)


def test_config_dialog_undo_redo(ui_env):
    dialog = open_config("speedometer", [])
    try:
        history = dialog.history
        font_size = dialog.option_edit["font_size"]
        original = font_size.text()
        assert not dialog.button_undo.isEnabled()
        font_size.setText("3")
        font_size.setText("30")  # typing grouped into one step
        history.record()
        dialog.option_edit["enable"].setChecked(not dialog.option_edit["enable"].isChecked())
        history.record()
        assert len(history.undo_stack) == 2 and dialog.button_undo.isEnabled()
        history.undo()
        history.undo()
        assert font_size.text() == original
        assert dialog.button_redo.isEnabled()
        history.redo()
        assert font_size.text() == "30"
        assert cfg.user.setting["speedometer"]["font_size"] != 30  # not applied
    finally:
        close_dialog(dialog)


def test_undo_timer_deleted_with_dialog(ui_env):
    dialog = open_config("speedometer", [])
    timer = dialog.history.timer
    assert timer.parent() is dialog
    dialog.option_edit["font_size"].setText("33")
    assert timer.isActive()
    close_dialog(dialog)  # pending undo record must not run on deleted editors
    QCoreApplication.processEvents()


def test_unsaved_edits_asked_before_closing(ui_env, monkeypatch):
    answers = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: answers.pop(0)))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    dialog = open_config("speedometer", [])
    dialog.show()
    try:
        dialog.close()  # nothing edited: closes without question
        assert not dialog.isVisible()
        dialog.show()
        dialog.option_edit["font_size"].setText("23")
        assert dialog.is_modified()
        answers.append(QMessageBox.StandardButton.Cancel)
        dialog.reject()  # Esc / Cancel button: asked, cancelled, stays open
        assert dialog.isVisible()
        answers.append(QMessageBox.StandardButton.Save)
        dialog.close()  # asked, saved then closed
        assert not dialog.isVisible() and cfg.user.setting["speedometer"]["font_size"] == 23
    finally:
        close_dialog(dialog)


def test_invalid_value_keeps_dialog_open(ui_env, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: errors.append(args)))
    dialog = open_config("speedometer", [])
    dialog.show()
    try:
        font_size = cfg.user.setting["speedometer"]["font_size"]
        dialog.option_edit["font_size"].setText("")  # invalid
        dialog.option_edit["update_interval"].setText("77")
        dialog.saving()
        assert dialog.isVisible()  # Save & close aborted, edits kept
        assert not errors and dialog.option_errors == {"font_size": "Number required"}  # shown inline
        assert cfg.user.setting["speedometer"]["font_size"] == font_size
        assert cfg.user.setting["speedometer"]["update_interval"] != 77  # nothing saved
    finally:
        close_dialog(dialog)


def test_internal_application_options_hidden(ui_env):
    from tinypedal.const_file import ConfigType
    from tinypedal.ui.config import UserConfig

    dialog = UserConfig(
        parent=None, key_name="application", preset_name="config.json", config_type=ConfigType.CONFIG,
        user_setting=cfg.user.config, default_setting=cfg.default.config, reload_func=lambda: None)
    try:
        for key in ("position_x", "window_width", "last_page_index", "rail_items"):
            assert key not in dialog.option_edit
        assert "show_at_startup" in dialog.option_edit
        cfg.user.config["application"]["rail_items"] = "home"
        dialog.save_setting()
        assert cfg.user.config["application"]["rail_items"] == "home"  # hidden options kept as is
    finally:
        close_dialog(dialog)
