"""Application UI audit fixes (package C): quit & restart with unsaved pages, config pages
during preset load, setup wizard, log, tables, hotkey & spectate pages, keyboard, theme colors,
message icons, VR mirror window, about"""

import warnings
from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QCloseEvent, QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QTableWidget, QTableWidgetItem

from tinypedal import app_signal, i18n
from tinypedal.const_file import ConfigType
from tinypedal.setting import cfg
from tinypedal.userfile.json_setting import copy_setting


def flush_deleted():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


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
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    with warnings.catch_warnings():  # already disconnected by quit
        warnings.simplefilter("ignore", RuntimeWarning)
        for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
            with suppress(RuntimeError, TypeError):
                signal.disconnect()
    main.deleteLater()
    flush_deleted()


@pytest.fixture
def answers(monkeypatch):
    """Message boxes recorded, questions answered with answers.reply"""

    class Answers:
        reply = QMessageBox.StandardButton.Cancel
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


def open_editor_page(window, path="heatmap_editor.HeatmapEditor"):
    from tinypedal.ui.tools_view import open_tool

    open_tool(path, window)
    return window.centralWidget().dialog_pages()[-1].dialog


def open_config_page(window, name="speedometer"):
    from tinypedal.ui.config import UserConfig

    UserConfig(parent=window, key_name=name, preset_name=cfg.filename.setting, config_type=ConfigType.WIDGET,
               user_setting=cfg.user.setting, default_setting=cfg.default.setting, reload_func=lambda: None).open()
    view = window.centralWidget()
    return next(page.dialog for page in view.dialog_pages() if getattr(page.dialog, "key_name", "") == name)


# Item 1: Cancel on unsaved changes keeps window (and tray icon)
def test_close_cancelled_keeps_window(window, answers, monkeypatch):
    from tinypedal.ui import app as app_module

    quits = []
    monkeypatch.setattr(app_module.loader, "close", lambda: quits.append("loader"))
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quits.append("quit")))
    cfg.application["minimize_to_tray"] = False
    editor = open_editor_page(window)
    editor.set_modified()
    event = QCloseEvent()
    window.closeEvent(event)
    assert answers.questions and not event.isAccepted() and not quits  # cancelled: window kept
    assert window.findChild(QSystemTrayIcon) is not None
    assert window.centralWidget().track_pages  # pages followed again
    editor.set_unmodified()
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() and quits == ["loader", "quit"]


# Item 6: restart asks for unsaved pages first
def test_restart_asks_unsaved_pages(window, answers, monkeypatch):
    from tinypedal.ui import app as app_module

    restarts = []
    monkeypatch.setattr(app_module.loader, "restart", lambda: restarts.append(cfg.application["open_pages"]))
    cfg.application["remember_open_pages"] = True
    editor = open_editor_page(window, "brake_editor.BrakeEditor")
    editor.set_modified()
    assert window.restart_app() is False and not restarts  # cancelled
    assert window.centralWidget().dialog_pages()
    answers.reply = QMessageBox.StandardButton.Discard
    assert window.restart_app() is True
    assert restarts and "brake_editor.BrakeEditor" in restarts[0]  # page reopened after restart
    assert not window.centralWidget().dialog_pages()


# Item 2: config pages registered, preset load guarded, save into loaded preset
def test_config_pages_registered(window):
    from tinypedal.ui._common import DialogSingleton

    assert not DialogSingleton.is_opened(ConfigType.CONFIG)
    dialog = open_config_page(window)
    assert DialogSingleton.is_opened(ConfigType.CONFIG)
    assert window.config_dialogs(preset_only=True) == [dialog]
    dialog.close()
    flush_deleted()
    assert not DialogSingleton.is_opened(ConfigType.CONFIG)


def test_preset_load_with_unsaved_config_page(window, answers, monkeypatch):
    from tinypedal.ui import app as app_module

    reloads = []
    monkeypatch.setattr(app_module.loader, "reload", lambda reload_preset=False: reloads.append(reload_preset))
    edited = open_config_page(window, "speedometer")
    unchanged = open_config_page(window, "relative")
    edited.option_edit["opacity"].setText("0.5")
    assert edited.is_modified() and not unchanged.is_modified()
    cfg.set_next_to_load("other.json")
    window.reload_preset(True)  # asked by user: refused, edited page shown
    assert not reloads and answers.warnings and "unsaved changes" in answers.warnings[0]
    assert window.centralWidget()._pages.currentWidget().dialog is edited
    assert cfg._setting_to_load == ""
    window.reload_preset(False)  # auto-load goes on
    assert reloads == [True]
    flush_deleted()
    pages = [page.dialog for page in window.centralWidget().dialog_pages()]
    assert edited in pages and unchanged not in pages  # unchanged page of previous preset closed


def test_config_saved_into_loaded_preset(window, answers, monkeypatch):
    dialog = open_config_page(window, "speedometer")
    old_setting = cfg.user.setting
    dialog.option_edit["opacity"].setText("0.5")
    # Another preset loaded meanwhile (auto-load): new dictionary, widget moved there
    new_setting = copy_setting(old_setting)
    new_setting["speedometer"]["position_x"] = 777
    monkeypatch.setattr(cfg.user, "setting", new_setting)
    monkeypatch.setattr(cfg.filename, "setting", "other.json")
    answers.reply = QMessageBox.StandardButton.No
    assert not dialog.save_setting()  # asked first, refused: nothing saved
    assert new_setting["speedometer"]["opacity"] != 0.5
    answers.reply = QMessageBox.StandardButton.Yes
    assert dialog.save_setting()
    assert new_setting["speedometer"]["opacity"] == 0.5  # into loaded preset
    assert new_setting["speedometer"]["position_x"] == 777  # unedited option kept
    assert old_setting["speedometer"]["opacity"] != 0.5
    assert "other" in answers.questions[0]


def test_config_save_keeps_options_changed_elsewhere(window):
    dialog = open_config_page(window, "speedometer")
    cfg.user.setting["speedometer"]["position_x"] = 321  # widget dragged while page is open
    dialog.option_edit["opacity"].setText("0.25")
    assert dialog.save_setting()
    assert cfg.user.setting["speedometer"]["position_x"] == 321
    assert cfg.user.setting["speedometer"]["opacity"] == 0.25


def test_font_config_unsaved_state(window, answers):
    from tinypedal.ui.config import FONT_NO_CHANGE, FontConfig

    dialog = FontConfig(parent=window, user_setting=cfg.user.setting, reload_func=lambda: None)
    dialog.open()
    try:
        assert dialog.is_preset_setting() and not dialog.is_modified()
        dialog.edit_fontsize.setValue(2)
        assert dialog.is_modified() and window.modified_config_dialogs(preset_only=True) == [dialog]
        assert dialog.selected_choice(dialog.edit_fontname) == FONT_NO_CHANGE
        assert dialog.applying() and not dialog.is_modified()
    finally:
        dialog.close()


def test_screen_change_waits_for_unsaved_config(window, monkeypatch):
    from tinypedal.ui import app as app_module

    reloads = []
    monkeypatch.setattr(app_module.loader, "reload", lambda reload_preset=False: reloads.append(1))
    monkeypatch.setattr(app_module, "screen_key", lambda: "new screens")
    cfg.application["enable_layout_per_screen_setup"] = True
    dialog = open_config_page(window)
    dialog.option_edit["opacity"].setText("0.5")
    window.check_screen_setup()
    assert not reloads  # retried later
    dialog.option_edit["opacity"].setText(dialog.saved_state["opacity"])
    window.check_screen_setup()
    assert reloads


def test_singleton_error_shows_dialog_title(ui_env, answers):
    from tinypedal.ui._common import BaseDialog, DialogSingleton, DialogSingletonError

    assert DialogSingletonError("lap_viewer")._title() == "Lap Viewer"
    dialog = BaseDialog(None)
    dialog.set_utility_title("Visionneuse de tours")
    DialogSingleton.register("test_viewer", dialog)
    dialog.show()
    try:
        DialogSingletonError("test_viewer").open()
        assert "Visionneuse de tours dialog" in answers.warnings[0] and "test_viewer" not in answers.warnings[0]
    finally:
        dialog.close()
        flush_deleted()


# Item 4: capture screen keeps layout editor page
def test_capture_screen_keeps_layout_editor_page(window, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    editor = open_editor_page(window, "layout_editor.LayoutEditor")
    window.show()
    screen = QGuiApplication.primaryScreen()
    grabbed = []
    monkeypatch.setattr(type(screen), "grabWindow", lambda self, *args: grabbed.append(window.isVisible()) or QImage())
    editor.capture_screen()
    assert grabbed == [False]  # main window hidden while capturing
    assert window.isVisible()
    assert editor in [page.dialog for page in window.centralWidget().dialog_pages()]  # page not closed
    window.hide()


# Item 9: setup wizard
def test_setup_wizard_checks_name_while_typing(ui_env):
    from tinypedal.ui.setup_wizard import SetupWizard

    wizard = SetupWizard(None)
    try:
        assert wizard.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        page = wizard.page_preset
        page.preset.setCurrentIndex(0)
        changes = []
        page.completeChanged.connect(lambda: changes.append(page.isComplete()))
        page.new_name.setText("default")
        page.new_name.setText("new one")
        assert changes == [False, True]
        assert wizard.choices().window_theme in ("Dark", "Light", "System")
    finally:
        wizard.deleteLater()
        flush_deleted()


def test_setup_wizard_translated_choices(ui_env, french):
    from tinypedal.ui.setup_wizard import SetupWizard

    cfg.application["window_color_theme"] = "Light"
    wizard = SetupWizard(None)
    try:
        combo = wizard.page_language.window_theme
        assert combo.currentText() == "Clair" and wizard.choices().window_theme == "Light"
        assert wizard.page_preset.new_name.text() == "mon overlay"
    finally:
        wizard.deleteLater()
        flush_deleted()


def test_setup_language_set_before_overlays_reload(ui_env, monkeypatch):
    from tinypedal.ui import setup_wizard

    languages = []
    monkeypatch.setattr(setup_wizard.loader, "reload", lambda reload_preset=False: languages.append(i18n.current_language()))
    choices = setup_wizard.SetupChoices(
        language="Français", api_name="", window_theme="Dark", overlay_theme="Modern Dark",
        modern_font=False, preset="", new_preset="", widgets=(),
    )
    try:
        setup_wizard.run_setup(choices)
        assert languages == ["fr"]  # overlays created with French labels
    finally:
        i18n.set_language("English")


def test_language_change_reloads_running_overlays(window, monkeypatch):
    from tinypedal.ui import app as app_module

    reloaded = []
    monkeypatch.setattr(type(app_module.wctrl), "reload", lambda self, name="": reloaded.append(name))
    monkeypatch.setattr(app_module.wctrl, "active_modules", {"relative": object(), "fuel": object()})
    window.retranslate()
    assert sorted(reloaded) == ["fuel", "relative"]


# Item 8: saving log never moves log stream
def test_log_save_keeps_stream(ui_env, monkeypatch, tmp_path, answers):
    from tinypedal.ui import log_info

    stream = log_info.log_stream
    stream.write("first line\n")
    position = stream.tell()
    target = tmp_path / "saved.log"
    monkeypatch.setattr(log_info.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    dialog = log_info.LogInfo(None)
    try:
        dialog.save_log()
        assert "first line" in target.read_text(encoding="utf-8")
        assert stream.tell() == position
        stream.write("second line\n")
        assert stream.getvalue().count("first line") == 1 and "second line" in stream.getvalue()
        missing = tmp_path / "missing" / "x.log"
        monkeypatch.setattr(log_info.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(missing), "")))
        dialog.save_log()
        assert answers.warnings and "Unable to save log" in answers.warnings[0]
    finally:
        dialog.close()
        flush_deleted()


# Items 13, 14: batch replace text, float cells
def test_batch_replace_is_plain_text(ui_env):
    from tinypedal.ui._common import TableBatchReplace

    table = QTableWidget(2, 1)
    table.setItem(0, 0, QTableWidgetItem("AF Corse"))
    table.setItem(1, 0, QTableWidgetItem("Other"))
    dialog = TableBatchReplace(None, {"Name": 0}, table)
    try:
        dialog.search_selector.setCurrentText("AF Corse")
        dialog.replace_entry.setText("A\\1 \\")
        dialog.replacing()
        assert table.item(0, 0).text() == "A\\1 \\" and table.item(1, 0).text() == "Other"
    finally:
        dialog.close()
        flush_deleted()


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "1e999", "abc"])
def test_float_cell_rejects_non_finite(text):
    from tinypedal.ui._common import FloatTableItem

    item = FloatTableItem(1.5)
    item.setText(text)
    item.validate()
    assert item.value() == 1.5 and item.text() == "1.5"
    item.setText("2.5")
    item.validate()
    assert item.value() == 2.5


# Item 17: refresh never runs toggle side effects
def test_hotkey_and_spectate_refresh_without_side_effects(ui_env, monkeypatch):
    from tinypedal.ui import hotkey_view, spectate_view

    calls = []
    for action in ("reload", "enable", "disable"):
        monkeypatch.setattr(type(hotkey_view.kctrl), action, lambda self, _action=action: calls.append(_action))
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: calls.append("save"))
    monkeypatch.setattr(type(spectate_view.api), "setup", lambda self: calls.append("api"))
    cfg.application["enable_global_hotkey"] = True
    cfg.api["enable_player_index_override"] = False
    hotkeys = hotkey_view.HotkeyList(None)
    spectate = spectate_view.SpectateList(None)
    try:
        hotkeys.refresh()
        spectate.refresh()
        assert hotkeys.button_toggle.isChecked() and not spectate.button_toggle.isChecked()
        assert "reload" not in calls and "save" not in calls and "api" not in calls
        hotkeys.button_toggle.click()  # user click still applies
        assert "reload" in calls and cfg.application["enable_global_hotkey"] is False
    finally:
        hotkeys.deleteLater()
        spectate.deleteLater()
        flush_deleted()


def test_spectate_texts_translated(ui_env, french, monkeypatch):
    from tinypedal.ui import spectate_view

    monkeypatch.setattr(type(spectate_view.api), "setup", lambda self: None)
    cfg.api["enable_player_index_override"] = True
    page = spectate_view.SpectateList(None)
    try:
        page.refresh()
        assert page.button_toggle.text() == "Activé"
        assert page.listbox_spectate.item(0).text() == "Anonyme"
    finally:
        page.set_enable_state(False)
        page.deleteLater()
        flush_deleted()


# Item 18: global hotkeys off only while capturing a key
def test_hotkeys_disabled_only_while_capturing(ui_env, monkeypatch):
    from tinypedal.template.setting_shortcuts import SHORTCUTS_GENERAL
    from tinypedal.ui import hotkey_view

    calls = []
    for action in ("enable", "disable"):
        monkeypatch.setattr(type(hotkey_view.kctrl), action, lambda self, _action=action: calls.append(_action))
    dialog = hotkey_view.ConfigHotkey(None, option_name=next(iter(SHORTCUTS_GENERAL)), hotkey_name="",
                                      reload_func=lambda: None)
    dialog.show()
    assert calls == ["disable"]
    dialog.hide()  # page left open behind another page
    assert calls == ["disable", "enable"]
    dialog.show()
    assert calls[-1] == "disable"
    dialog.close()
    assert calls[-1] == "enable"


# Item 21: same page already open gets the call
def test_option_finder_filters_open_page(window):
    from tinypedal.ui import option_finder

    entries = option_finder.search_options(option_finder.build_index(), "speedometer opacity")
    first = option_finder.open_option(window, entries[0])
    first.edit_search.setText("")
    second = option_finder.open_option(window, entries[0])
    flush_deleted()
    assert second is first and first.edit_search.text() == entries[0].key


def test_option_finder_hides_app_kept_options(ui_env):
    from tinypedal.ui import option_finder

    keys = {(entry.section, entry.key) for entry in option_finder.build_index()}
    assert ("vr_overlay", "mirror_position_x") not in keys and ("vr_overlay", "enable_vr_overlay") in keys


def test_plugin_drop_installed_from_open_page(window, monkeypatch, tmp_path):
    from tinypedal.ui import file_drop

    installs = []
    monkeypatch.setattr(file_drop, "classify", lambda path: file_drop.DROP_PLUGIN)
    opened = open_editor_page(window, "plugin_manager.PluginManager")
    monkeypatch.setattr(type(opened), "install_file", lambda self, path: installs.append(self))
    file_drop.handle_drop(window, [str(tmp_path / "plugin.zip")])
    flush_deleted()
    assert installs == [opened]


# Item 24: invalid custom theme colors never block loading
def test_custom_theme_null_colors(tmp_path):
    from tinypedal.userfile.overlay_theme import FILENAME, import_themes, load_custom_themes, validate_themes

    builtin = ("Modern Dark",)
    themes = validate_themes({"Mine": {"base": None, "colors": None}, "List": {"colors": [1, 2]}}, builtin)
    assert themes == {"Mine": {"base": "Modern Dark", "colors": {}}, "List": {"base": "Modern Dark", "colors": {}}}
    (tmp_path / FILENAME).write_text('{"Mine": {"colors": null}}', encoding="utf-8")
    assert load_custom_themes(f"{tmp_path}/", builtin) == {"Mine": {"base": "Modern Dark", "colors": {}}}
    nested = tmp_path / "nested.json"
    nested.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    with pytest.raises(ValueError):
        import_themes(str(nested), builtin)


# Item 26: empty path never points to drive root
@pytest.mark.parametrize("text", ["", "  ", "/", "C:/"])
def test_empty_or_root_path_rejected(ui_env, text):
    from tinypedal.ui._option import FilePathEdit

    editor = FilePathEdit(None, "settings/")
    editor.setText(text)
    assert editor.validate() is None


def test_valid_path_accepted(ui_env, tmp_path):
    from tinypedal.ui._option import FilePathEdit

    editor = FilePathEdit(None, "settings/")
    editor.setText(tmp_path.as_posix())
    assert editor.validate()


# Item 27: API menu reset frees its action group
def test_api_menu_reset_frees_action_group(window):
    from PySide6.QtGui import QActionGroup

    from tinypedal.ui.menu import APIMenu

    menu = APIMenu("API", window)
    count = len(menu.findChildren(QActionGroup))
    for _ in range(3):
        menu.reset_menu()
    flush_deleted()
    assert len(menu.findChildren(QActionGroup)) == count
    menu.refresh_menu()
    menu.deleteLater()


# Item 29: titles & literals translated
def test_titles_translated(window, french):
    from tinypedal.ui.config import FontConfig
    from tinypedal.ui.display_order import DisplayOrder

    font = FontConfig(parent=window, user_setting=cfg.user.setting, reload_func=lambda: None)
    try:
        assert font.windowTitle().startswith("Police globale")
        assert font.edit_fontname.itemText(0) == "aucun changement"
        assert font.edit_autooffset.itemText(1) == "activer"
        config = open_config_page(window, "relative")
        order = DisplayOrder(config, user_orders={}, default_orders={})
        assert order.windowTitle().startswith("Ordre d'affichage")
        order.close()
    finally:
        font.close()
    from tinypedal.ui.menu import OverlayMenu

    menu = OverlayMenu("Overlay", window)
    assert "Réinitialiser les données" in [action.text() for action in menu.actions()]
    menu.deleteLater()


def test_messages_translated(french):
    assert i18n.trm(
        "Cannot load preset while <b>Relative</b> has unsaved changes.<br><br>Save or cancel its changes first."
    ) == (
        "Impossible de charger un preset tant que <b>Relative</b> a des modifications non enregistrées."
        "<br><br>Enregistrez ou annulez d'abord ses modifications."
    )
    assert i18n.trm("Preset <b>race</b> was loaded since this page was opened.<br><br>Save changed options to "
                    "<b>race</b>?").startswith("Le preset <b>race</b> a été chargé")
    assert i18n.trm("Unable to save log: denied") == "Impossible d'enregistrer le journal : denied"
    assert i18n.trm("Replay recorded with LMU API, select LMU API to play it.") == (
        "Rejeu enregistré avec l'API LMU, sélectionnez l'API LMU pour le lire.")
    assert i18n.trm("Already opened <b>Visionneuse de tours dialog</b>.") == (
        "La fenêtre <b>Visionneuse de tours</b> est déjà ouverte.")


# Item 30: status colors readable on light theme
def contrast(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        rgb = QColor(color)
        channels = []
        for value in (rgb.redF(), rgb.greenF(), rgb.blueF()):
            channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_status_text_colors_contrast():
    from tinypedal.ui import STATUS_COLORS, palette_dark, palette_light

    for theme, palette in (("Dark", palette_dark()), ("Light", palette_light())):
        backgrounds = [row[0] for row in palette if row[3].name in ("Window", "Base")]
        for name in ("success", "danger", "warning", "info"):
            for background in backgrounds:
                assert contrast(STATUS_COLORS[theme][name], background) >= 4.5, (theme, name)
        for name in ("badge_success", "badge_danger", "badge_warning", "badge_neutral"):
            assert contrast(STATUS_COLORS[theme][name], STATUS_COLORS[theme]["badge_text"]) >= 4.5


def test_running_pill_follows_theme(ui_env):
    from tinypedal.ui import set_style_palette, set_style_window, status_color

    try:
        set_style_palette("Light")
        assert status_color("success") == "#16702F"
        assert "#16702F" in set_style_window(9) and "#3DDC84" not in set_style_window(9)
        set_style_palette("Dark")
        assert status_color("success") == "#3DDC84"
    finally:
        set_style_palette("Dark")


# Item 31: keyboard
def render(widget) -> QImage:
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    widget.render(image)
    return image


def test_focus_ring_drawn_for_keyboard_focus(ui_env, monkeypatch):
    from tinypedal.ui import has_keyboard_focus
    from tinypedal.ui.app import NavButton
    from tinypedal.ui.tools_view import ToolCard

    for button in (NavButton("Home", "", "H", ""), ToolCard("Tool", "", "")):
        button.resize(button.sizeHint())
        before = render(button)
        monkeypatch.setattr(button, "hasFocus", lambda: True)
        button.window().setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, True)
        assert has_keyboard_focus(button)
        after = render(button)
        assert before != after  # ring drawn
        button.window().setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, False)
        assert not has_keyboard_focus(button)  # focus from mouse click: no ring
        button.deleteLater()
    flush_deleted()


def test_module_list_keyboard(ui_env, monkeypatch):
    from tinypedal.module_control import mctrl
    from tinypedal.ui import module_view

    toggled, configs = [], []
    monkeypatch.setattr(module_view.ModuleControlItem, "toggle_state", lambda self: toggled.append(self.module_name))
    monkeypatch.setattr(module_view.ModuleControlItem, "open_config_dialog",
                        lambda self: configs.append(self.module_name))
    page = module_view.ModuleList(None, mctrl)
    try:
        assert page.listbox_module.focusPolicy() == Qt.FocusPolicy.TabFocus
        assert all(chip.focusPolicy() == Qt.FocusPolicy.TabFocus for chip in page.filter_group.buttons())
        assert page.list_key_pressed(Qt.Key.Key_Down)  # first key shows first row
        first = page.listbox_module.currentItem().data(Qt.ItemDataRole.UserRole)
        assert page.list_key_pressed(Qt.Key.Key_Space) and toggled == [first]
        assert page.list_key_pressed(Qt.Key.Key_Return) and configs == [first]
        assert not page.list_key_pressed(Qt.Key.Key_A)
    finally:
        page.deleteLater()
        flush_deleted()


def test_tray_single_click_shows_window(window, monkeypatch):
    shown = []
    monkeypatch.setattr(window, "show_app", lambda: shown.append(1))
    window.tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    window.tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    window.tray_activated(QSystemTrayIcon.ActivationReason.Context)
    assert shown == [1, 1]


# Item 32: message box icons drawn in theme
def test_message_icons_follow_theme(window):
    from tinypedal.ui import STATUS_COLORS, set_style_palette

    try:
        for theme in ("Dark", "Light"):
            set_style_palette(theme)
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)  # icon of message box (app style sheet applied)
            pixmap = box.iconPixmap()
            box.deleteLater()
            assert not pixmap.isNull()
            image = pixmap.toImage()
            edge = image.pixelColor(round(image.width() * 0.12), image.height() // 2)
            assert edge.name().upper() == STATUS_COLORS[theme]["badge_danger"]
    finally:
        set_style_palette("Dark")


# Item 33: VR mirror window kept on reload, position remembered
def test_mirror_window_kept_and_position_saved(ui_env, monkeypatch):
    from tinypedal.vr_overlay import MirrorWindow, VROverlay

    saved = copy_setting(cfg.user.config["vr_overlay"])
    cfg.user.config["vr_overlay"].update(enable_vr_overlay=False, enable_vr_mirror_window=True)
    control = VROverlay()
    try:
        control.enable()
        mirror = control._mirror
        control.disable()  # reload: window kept, updates stopped
        assert control._mirror is mirror and not control._timer.isActive()
        cfg.user.config["vr_overlay"]["mirror_background_color"] = "#112233"
        control.enable()
        assert control._mirror is mirror and mirror.background.name() == "#112233"
        mirror.move(QPoint(40, 50))
        mirror.save_position()
        position = (cfg.user.config["vr_overlay"]["mirror_position_x"], cfg.user.config["vr_overlay"]["mirror_position_y"])
        assert position == (mirror.x(), mirror.y())
        other = MirrorWindow("#000000", lambda: None)
        assert other.pos() == mirror.pos()  # restored
        other.deleteLater()
        cfg.user.config["vr_overlay"]["enable_vr_mirror_window"] = False
        control.enable()  # turned off in setting
        assert control._mirror is None
    finally:
        control.disable(close_mirror=True)
        cfg.user.config["vr_overlay"] = saved
        flush_deleted()


# Item 34: about shows modified version notice & both links
def test_about_modified_version_notice(ui_env, french):
    from PySide6.QtWidgets import QLabel

    from tinypedal.const_app import URL_FORK, URL_WEBSITE
    from tinypedal.ui.about import About

    dialog = About(None)
    try:
        text = dialog.findChild(QLabel, "labelAbout").text()
        assert URL_FORK in text and URL_WEBSITE in text
        assert "version modifiée de TinyPedal" in text and "Steven Vezzu" in text
        assert "TinyPedal developers" in text  # upstream copyright kept
    finally:
        dialog.close()
        flush_deleted()


def test_layout_editor_capture_window_mode(ui_env, monkeypatch):
    """Separate window (not a page): the editor itself is hidden while capturing"""
    from PySide6.QtGui import QGuiApplication

    from tinypedal.ui.layout_editor import LayoutEditor

    editor = LayoutEditor(None)
    editor.show()
    screen = QGuiApplication.primaryScreen()
    grabbed = []
    monkeypatch.setattr(type(screen), "grabWindow", lambda self, *args: grabbed.append(editor.isVisible()) or QImage())
    try:
        editor.capture_screen()
        assert grabbed == [False] and editor.isVisible()
    finally:
        editor.close()
        flush_deleted()


def test_focus_ring_painter_restored(ui_env):
    """Ring drawing keeps painter state for drawing after it"""
    from tinypedal.ui import draw_focus_ring
    from tinypedal.ui.app import NavButton

    button = NavButton("Home", "", "H", "")
    image = QImage(40, 40, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    pen = painter.pen()
    draw_focus_ring(painter, button, QRectF(0, 0, 40, 40), 4)
    assert painter.pen() == pen
    painter.end()
    button.deleteLater()
    flush_deleted()
