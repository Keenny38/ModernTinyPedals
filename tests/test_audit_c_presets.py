"""Audit fixes: share code numbers, preset deletion & rename, preset comparison saving, translations, theme colors"""

import base64
import json
import os
import zlib

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QMenu, QMessageBox

from tinypedal import app_signal, i18n
from tinypedal.i18n import untr
from tinypedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


@pytest.fixture
def warnings(monkeypatch):
    """Warning messages (title, text), questions answered yes"""
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: shown.append(args[1:3])))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    return shown


def write_preset(name: str, data: dict | None = None):
    with open(f"{cfg.path.settings}{name}", "w", encoding="utf-8") as file:
        json.dump(data or {"speedometer": {"enable": True}}, file)


def exists(name: str) -> bool:
    return name in os.listdir(cfg.path.settings)  # exact case, also on Windows


@pytest.fixture
def page(ui_env, warnings, monkeypatch):
    """Preset page with presets "race" & "practice" ("default" loaded)"""
    from tinypedal.ui import preset_view

    for name in ("race.json", "practice.json"):
        write_preset(name)
    monkeypatch.setattr(preset_view, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": ""}}
    cfg.user.tracks = {"Spa": {"preset": ""}}
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    widget.refresh()
    yield widget
    widget.deleteLater()
    flush()


def choose(page, monkeypatch, preset: str, text: str):
    """Run context menu of preset, picking action by (English) text"""
    from tinypedal.ui import preset_view

    names = [page.listbox_preset.item(row).text() for row in range(page.listbox_preset.count())]
    page.listbox_preset.setCurrentRow(names.index(preset))
    item = page.listbox_preset.item(names.index(preset))

    class PickMenu(QMenu):
        def exec(self, *args):
            return next(action for action in self.actions() if untr(action.text()) == text)

    monkeypatch.setattr(preset_view, "QMenu", PickMenu)
    monkeypatch.setattr(page.listbox_preset, "itemAt", lambda pos: item)
    page.open_context_menu(page.listbox_preset.visualItemRect(item).center())


def share_code(raw: str) -> str:
    from tinypedal.userfile.preset_share import SHARE_PREFIX

    return SHARE_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw.encode("utf-8"))).decode("ascii")


# Share code
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999", "deep"])
def test_share_code_with_invalid_numbers_rejected(page, warnings, monkeypatch, value):
    from tinypedal.ui import preset_view

    if value == "deep":  # nested beyond recursion limit
        value = "[" * 100000 + "]" * 100000
    raw = f'{{"speedometer": {{"enable": true, "font_size": {value}}}}}'
    opened = []
    monkeypatch.setattr(preset_view, "TextInputDialog", lambda *args, **kwargs: opened.append(args))
    before = sorted(os.listdir(cfg.path.settings))
    assert page.share_code_entered(share_code(raw)) is False  # code input stays open
    assert warnings and "Invalid share code" in warnings[0][1]
    assert not opened and sorted(os.listdir(cfg.path.settings)) == before  # nothing imported


def test_share_code_valid_still_accepted(page, warnings, monkeypatch):
    from tinypedal.ui import preset_view

    opened = []
    monkeypatch.setattr(
        preset_view, "TextInputDialog", lambda *args, **kwargs: type("Dialog", (), {"open": lambda self: opened.append(1)})())
    assert page.share_code_entered(share_code('{"speedometer": {"enable": true, "font_size": 15.5}}'))
    assert opened and not warnings


# Preset deletion
def test_delete_loaded_preset_refused(page, warnings, monkeypatch):
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    choose(page, monkeypatch, "race", "Delete")
    assert exists("race.json")
    assert warnings and "loaded preset cannot be deleted" in warnings[0][1]


def test_delete_clears_primary_preset_references(page, warnings, ui_env, monkeypatch):
    cfg.user.tracks = {"Spa": {"preset": "practice"}, "Monza": {"preset": "race"}}
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": "practice"}}
    cfg.user.shortcuts["preset_1"]["preset"] = "practice"
    cfg.user.shortcuts["preset_2"]["preset"] = "race"
    choose(page, monkeypatch, "practice", "Delete")
    assert not exists("practice.json") and not warnings
    assert cfg.user.tracks["Spa"]["preset"] == "" and cfg.user.classes["GT3"]["preset"] == ""
    assert cfg.user.shortcuts["preset_1"]["preset"] == ""
    assert cfg.user.tracks["Monza"]["preset"] == "race" and cfg.user.shortcuts["preset_2"]["preset"] == "race"
    assert {"tracks", "classes", "shortcuts"} <= set(ui_env)  # style presets saved


def test_delete_locked_file_warns(page, warnings, monkeypatch):
    from tinypedal.userfile import preset_trash

    def locked(*args):
        raise PermissionError("used by another program")

    cfg.user.tracks = {"Spa": {"preset": "practice"}}
    monkeypatch.setattr(preset_trash.os, "replace", locked)  # deleted preset moved to trash
    choose(page, monkeypatch, "practice", "Delete")
    assert exists("practice.json") and warnings and "used by another program" in warnings[0][1]
    assert cfg.user.tracks["Spa"]["preset"] == "practice"  # kept, preset still there


# Backups
def backup_dialog(*backups: tuple[str, str]):
    from tinypedal.ui import preset_management

    for name, text in backups:
        with open(f"{cfg.path.settings}{name}", "w", encoding="utf-8") as file:
            file.write(text)
    dialog = preset_management.RestoreBackup(None)
    rows = {dialog.listbox_backup.item(row).text(): row for row in range(dialog.listbox_backup.count())}
    return dialog, rows


def test_backup_delete_and_style_restore_errors_warn(ui_env, warnings, monkeypatch):
    from tinypedal.ui import preset_management

    def locked(*args):
        raise PermissionError("used by another program")

    preset_backup = "race.json.backup-2026-10-03-12-00-00-000000"
    style_backup = "brakes.json.backup-2026-10-03-12-00-00-000000"
    dialog, rows = backup_dialog((preset_backup, "{}"), (style_backup, "{}"))
    reloaded = []
    app_signal.reload.connect(reloaded.append)
    try:
        monkeypatch.setattr(preset_management.os, "remove", locked)
        dialog.listbox_backup.setCurrentRow(rows[preset_backup])
        dialog.delete()
        assert len(warnings) == 1 and exists(preset_backup)
        monkeypatch.setattr(preset_management.shutil, "move", locked)
        dialog.listbox_backup.setCurrentRow(rows[style_backup])
        dialog.restore()
        assert len(warnings) == 2 and exists(style_backup) and not reloaded
    finally:
        app_signal.reload.disconnect(reloaded.append)
        dialog.close()
        flush()


def test_backup_list_colors_follow_window_theme(ui_env, warnings):
    from tinypedal.ui import STATUS_COLORS

    dialog, _ = backup_dialog(
        ("race.json.backup-2026-10-03-12-00-00-000000", "broken"),
        ("brakes.json.backup-2026-10-03-12-00-00-000000", "{}"),
    )
    try:
        for theme, window in (("Dark", "#202020"), ("Light", "#F4F5F8")):
            palette = QPalette(dialog.listbox_backup.palette())
            palette.setColor(QPalette.ColorRole.Window, QColor(window))
            dialog.listbox_backup.setPalette(palette)
            dialog.refresh()  # colors read again
            colors = {
                dialog.listbox_backup.item(row).text(): dialog.listbox_backup.item(row).foreground().color().name()
                for row in range(dialog.listbox_backup.count())
            }
            assert colors["race.json.backup-2026-10-03-12-00-00-000000"] == STATUS_COLORS[theme]["danger"].lower()
            assert colors["brakes.json.backup-2026-10-03-12-00-00-000000"] == STATUS_COLORS[theme]["info"].lower()
    finally:
        dialog.close()
        flush()


# Rename
def create(mode: str = "", source: str = "", name: str = "", title: str = "Test"):
    from tinypedal.ui.preset_management import CreatePreset

    dialog = CreatePreset(None, title=title, mode=mode, source_filename=source)
    dialog.preset_entry.setText(name)
    dialog.create_preset()
    return dialog


def test_rename_preset_by_case_only(ui_env, warnings, monkeypatch):
    write_preset("race.json")
    write_preset("other.json")
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    cfg.user.tracks = {"Spa": {"preset": "race"}}
    reloaded = []
    app_signal.reload.connect(reloaded.append)
    try:
        create(mode="rename", source="race.json", name="Race")
        assert not warnings
        assert exists("Race.json") and not exists("race.json")
        assert cfg.user.tracks["Spa"]["preset"] == "Race"  # references follow new name
        assert cfg._setting_to_load == "Race.json" and reloaded  # loaded preset follows new name
        create(mode="rename", source="Race.json", name="OTHER")  # other preset, any case: refused
        assert warnings and exists("Race.json") and exists("other.json")
        create(mode="rename", source="Race.json", name="Race")  # same name: refused
        assert len(warnings) == 2
    finally:
        app_signal.reload.disconnect(reloaded.append)
        cfg.set_next_to_load("")
        flush()


# Preset comparison
def test_preset_compare_save_keeps_changes_made_meanwhile(ui_env, warnings, monkeypatch):
    from tinypedal.ui import preset_compare

    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    other = {section: dict(options) for section, options in cfg.user.setting.items()}
    other["speedometer"]["font_size"] = 99
    other["speedometer"]["update_interval"] = 123
    write_preset("other.json", other)
    reloads = []
    monkeypatch.setattr(preset_compare.loader, "reload", lambda **kwargs: reloads.append(kwargs))
    flush()
    dialog = preset_compare.PresetCompare(None, preset_a="default.json", preset_b="other.json")
    try:
        rows = [dialog.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(dialog.table.rowCount())]
        dialog.table.selectRow(rows.index(("speedometer", "font_size")))
        dialog.copy_selected(to_a=True)  # to loaded preset
        dialog.table.clearSelection()
        rows = [dialog.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(dialog.table.rowCount())]
        dialog.table.selectRow(rows.index(("speedometer", "update_interval")))
        dialog.copy_selected(to_a=False)  # to other preset file
        # Changed after page opened: widget moved in loaded preset, other preset edited elsewhere
        cfg.user.setting["speedometer"]["position_x"] = 777
        cfg.user.setting["speedometer"]["opacity"] = 0.42
        other["speedometer"]["font_size"] = 55
        write_preset("other.json", other)
        dialog.saving()
        assert cfg.user.setting["speedometer"]["font_size"] == 99  # copied value
        assert cfg.user.setting["speedometer"]["position_x"] == 777  # kept
        assert cfg.user.setting["speedometer"]["opacity"] == 0.42  # kept
        assert "setting" in ui_env and reloads == [{"reload_preset": True}]
        with open(f"{cfg.path.settings}other.json", encoding="utf-8") as file:
            saved = json.load(file)["speedometer"]
        assert saved["update_interval"] == cfg.user.setting["speedometer"]["update_interval"]  # copied value
        assert saved["font_size"] == 55  # kept
        assert not dialog.is_modified() and not dialog.edits
    finally:
        dialog.set_unmodified()
        dialog.close()
        flush()


# Translations
def test_french_preset_dialog_titles(page, monkeypatch, french):
    from tinypedal.ui import preset_view

    titles = []
    monkeypatch.setattr(preset_view.CreatePreset, "open", lambda self: titles.append(self.windowTitle()))
    page.open_create_preset()
    choose(page, monkeypatch, "race", "Duplicate")
    choose(page, monkeypatch, "race", "Rename")
    assert titles == [i18n.tr("Create new default preset"), i18n.tr("Duplicate Preset"), i18n.tr("Rename Preset")]
    assert all(title != english for title, english in zip(
        titles, ("Create new default preset", "Duplicate Preset", "Rename Preset"), strict=True))
    flush()


def test_french_preset_access_error(ui_env, warnings, monkeypatch, french):
    from tinypedal.ui import preset_management

    def locked(*args):
        raise PermissionError("locked")

    write_preset("race.json")
    monkeypatch.setattr(preset_management.os, "rename", locked)
    create(mode="rename", source="race.json", name="other")
    assert warnings[0][1].startswith("Impossible d'accéder au fichier du preset")
    flush()


@pytest.mark.parametrize(("message", "expected"), [
    ("Unable to delete preset:<br>error", "Impossible de supprimer le preset :<br>error"),
    ("Unable to delete backup file:<br>error", "Impossible de supprimer la sauvegarde :<br>error"),
    ("Unable to restore backup file:<br>error", "Impossible de restaurer la sauvegarde :<br>error"),
    ("Unable to save preset shared.json", "Impossible d'enregistrer le preset shared.json"),
    ("No backup file selected.", "Aucune sauvegarde sélectionnée."),
    ("Selected backup file is invalid and cannot be restored.",
     "La sauvegarde sélectionnée est invalide et ne peut pas être restaurée."),
    ("No destination preset selected or found.", "Aucun preset de destination sélectionné ou trouvé."),
    ("No preset setting selected.<br><br>Select at least one setting and try again.",
     "Aucun réglage de preset sélectionné.<br><br>Sélectionnez au moins un réglage et réessayez."),
    ("No option type selected.<br><br>Select at least one option type and try again.",
     "Aucun type d'option sélectionné.<br><br>Sélectionnez au moins un type d'option et réessayez."),
    ("Unable to read plugin:<br>error", "Impossible de lire le plugin :<br>error"),
    ("Unable to save plugin trust:<br>error", "Impossible d'enregistrer la confiance accordée au plugin :<br>error"),
    ("Plugin loaded with error:<br>error", "Plugin chargé avec une erreur :<br>error"),
    ("Plugin reloaded with error:<br>error", "Plugin rechargé avec une erreur :<br>error"),
    ("Loaded: <b>race (locked)</b>", "Chargé : <b>race (locked)</b>"),
])
def test_french_preset_and_plugin_messages(french, message, expected):
    assert i18n.trm(message) == expected


def test_french_plugin_trust_prompt(ui_env, monkeypatch, french):
    from tinypedal.ui.plugin_manager import PluginManager

    asked = []

    def question(*args, **kwargs):
        asked.append(args[1:3])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: pytest.fail(f"warning: {args}")))
    flush()
    manager = PluginManager(None)
    try:
        manager.table.selectRow(0)  # bundled example plugin
        manager.trust_selected()
        title, message = asked[0]
        assert title == "Faire confiance..."
        assert "accès complet à votre ordinateur" in message and "vous faites confiance à son auteur" in message
        assert "Fichiers de code :" in message and "SHA-256 : <code>" in message
        for english in ("Python code", "Only trust", "Code files", "Trust this plugin", "requires trusting"):
            assert english not in message
    finally:
        manager.close()
        flush()


# Plugin badges
def test_plugin_badge_colors_follow_window_theme(ui_env):
    from tinypedal.ui import STATUS_COLORS, plugin_manager

    for theme, window in (("Dark", "#202020"), ("Light", "#F4F5F8")):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#123456"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FEDCBA"))
        for badge in plugin_manager.BADGE_COLORS.values():
            background, text = plugin_manager.badge_colors(badge, palette)
            if badge == plugin_manager.BADGE_ACCENT:
                assert (background.name(), text.name()) == ("#123456", "#fedcba")
            else:
                assert background.name() == STATUS_COLORS[theme][badge].lower()
                assert text.name() == STATUS_COLORS[theme]["badge_text"].lower()


def test_plugin_enabled_badge_is_palette_accent(ui_env, monkeypatch):
    from types import SimpleNamespace

    from tinypedal.ui import plugin_manager

    monkeypatch.setattr(plugin_manager, "discover_plugins", lambda: ["plugin_on", "plugin_off"])
    monkeypatch.setattr(plugin_manager, "wctrl", SimpleNamespace(names=["plugin_on", "plugin_off"]))
    cfg.user.setting["plugin_on"] = {"enable": True}
    cfg.user.setting["plugin_off"] = {"enable": False}
    flush()
    dialog = plugin_manager.PluginManager(None)
    try:
        rows = {dialog.table.item(row, 0).text(): row for row in range(dialog.table.rowCount())}
        assert dialog.table.item(rows["on"], 2).data(plugin_manager.ROLE_BADGE) == plugin_manager.BADGE_ACCENT
        assert dialog.table.item(rows["off"], 2).data(plugin_manager.ROLE_BADGE) == "badge_neutral"
        assert not dialog.grab().isNull()  # badges painted
    finally:
        dialog.close()
        flush()
