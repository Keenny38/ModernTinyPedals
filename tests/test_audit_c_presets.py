"""Audit fixes: preset deletion & rename, preset comparison saving, translations, theme colors"""

import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QMessageBox

from neopedal import app_signal, i18n
from neopedal.setting import cfg


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
    from neopedal.ui import preset_view

    for name in ("race.json", "practice.json"):
        write_preset(name)
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": ""}}
    cfg.user.tracks = {"Spa": {"preset": ""}}
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    widget.backend.set_active(True)  # presets read while page is shown
    yield widget
    widget.deleteLater()
    flush()


def choose(page, preset: str, text: str):
    """Run action of preset menu (English text)"""
    actions = {"Delete": page.backend.remove}
    actions[text](f"{preset}.json")


# Preset deletion
def test_delete_loaded_preset_refused(page, warnings, monkeypatch):
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    choose(page, "race", "Delete")
    assert exists("race.json")
    assert warnings and "loaded preset cannot be deleted" in warnings[0][1]


def test_delete_clears_primary_preset_references(page, warnings, ui_env, monkeypatch):
    cfg.user.tracks = {"Spa": {"preset": "practice"}, "Monza": {"preset": "race"}}
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": "practice"}}
    cfg.user.shortcuts["preset_1"]["preset"] = "practice"
    cfg.user.shortcuts["preset_2"]["preset"] = "race"
    choose(page, "practice", "Delete")
    assert not exists("practice.json") and not warnings
    assert cfg.user.tracks["Spa"]["preset"] == "" and cfg.user.classes["GT3"]["preset"] == ""
    assert cfg.user.shortcuts["preset_1"]["preset"] == ""
    assert cfg.user.tracks["Monza"]["preset"] == "race" and cfg.user.shortcuts["preset_2"]["preset"] == "race"
    assert {"tracks", "classes", "shortcuts"} <= set(ui_env)  # style presets saved


def test_delete_locked_file_warns(page, warnings, monkeypatch):
    from neopedal.userfile import preset_trash

    def locked(*args):
        raise PermissionError("used by another program")

    cfg.user.tracks = {"Spa": {"preset": "practice"}}
    monkeypatch.setattr(preset_trash.os, "replace", locked)  # deleted preset moved to trash
    choose(page, "practice", "Delete")
    assert exists("practice.json") and warnings and "used by another program" in warnings[0][1]
    assert cfg.user.tracks["Spa"]["preset"] == "practice"  # kept, preset still there


# Backups
def backups_panel(page, *backups: tuple[str, str]):
    for name, text in backups:
        with open(f"{cfg.path.settings}{name}", "w", encoding="utf-8") as file:
            file.write(text)
    toasts = []
    page.backend.toastShown.connect(lambda text, error, undo: toasts.append((text, error)))
    page.backend.backups.refresh()
    return page.backend.backups, toasts


def test_backup_delete_and_style_restore_errors_told(page, monkeypatch):
    from neopedal.ui import preset_management

    def locked(*args):
        raise PermissionError("used by another program")

    preset_backup = "race.json.backup-2026-10-03-12-00-00-000000"
    style_backup = "brakes.json.backup-2026-10-03-12-00-00-000000"
    backups, toasts = backups_panel(page, (preset_backup, "{}"), (style_backup, "{}"))
    reloaded = []
    app_signal.reload.connect(reloaded.append)
    try:
        monkeypatch.setattr(preset_management.os, "remove", locked)
        backups.remove(preset_backup)
        assert len(toasts) == 1 and toasts[0][1] and exists(preset_backup)  # error toast
        monkeypatch.setattr(preset_management.shutil, "move", locked)
        assert backups.prepareRestore(style_backup) == "style"  # page asks first
        backups.restoreStyle(style_backup)
        assert len(toasts) == 2 and "used by another program" in toasts[1][0] and exists(style_backup)
        assert not reloaded
    finally:
        app_signal.reload.disconnect(reloaded.append)


def test_backup_rows_marked_unreadable_and_style(page):
    backups, _ = backups_panel(
        page,
        ("race.json.backup-2026-10-03-12-00-00-000000", "broken"),
        ("brakes.json.backup-2026-10-03-12-00-00-000000", "{}"),
    )
    deadline = time.monotonic() + 5
    while backups.checking and time.monotonic() < deadline:  # files checked in background
        QCoreApplication.processEvents()
    rows = {row["key"]: row for row in backups.model.rows}
    assert rows["race.json.backup-2026-10-03-12-00-00-000000"]["status"] == "invalid"
    assert rows["brakes.json.backup-2026-10-03-12-00-00-000000"]["status"] == "valid"
    assert rows["brakes.json.backup-2026-10-03-12-00-00-000000"]["style"]
    assert not rows["race.json.backup-2026-10-03-12-00-00-000000"]["style"]


# Rename
def create(mode: str = "", source: str = "", name: str = "") -> str:
    from neopedal.ui.preset_management import apply_preset_name

    return apply_preset_name(name, mode, source)


def test_rename_preset_by_case_only(ui_env, warnings, monkeypatch):
    write_preset("race.json")
    write_preset("other.json")
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    cfg.user.tracks = {"Spa": {"preset": "race"}}
    reloaded = []
    app_signal.reload.connect(reloaded.append)
    try:
        assert create(mode="rename", source="race.json", name="Race") == ""
        assert exists("Race.json") and not exists("race.json")
        assert cfg.user.tracks["Spa"]["preset"] == "Race"  # references follow new name
        assert cfg._setting_to_load == "Race.json" and reloaded  # loaded preset follows new name
        # other preset, any case: refused
        assert create(mode="rename", source="Race.json", name="OTHER") == "Preset already exists."
        assert exists("Race.json") and exists("other.json")
        assert create(mode="rename", source="Race.json", name="Race") == "Preset already exists."  # same name
    finally:
        app_signal.reload.disconnect(reloaded.append)
        cfg.set_next_to_load("")
        flush()


# Preset comparison: compare panel of the Presets page (tests/test_ui_audit_2026_10_29_config_presets.py)


# Translations
def test_french_preset_dialog_titles(page, french):
    """Titles of preset name box (Presets page: new, duplicate, rename, restore backup) translated"""
    titles = ("Create new default preset", "Duplicate Preset", "Rename Preset", "Restore Backup")
    assert all(i18n.tr(title) != title for title in titles)
    assert page.backend.nameError("", "", "race") == i18n.tr("Preset already exists.") != "Preset already exists."
    flush()


def test_french_preset_access_error(ui_env, warnings, monkeypatch, french):
    from neopedal.ui import preset_management

    def locked(*args):
        raise PermissionError("locked")

    write_preset("race.json")
    monkeypatch.setattr(preset_management, "replace_retry", locked)
    assert create(mode="rename", source="race.json", name="other").startswith("Impossible d'accéder au fichier du preset")
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


def test_french_plugin_trust_prompt(ui_env, monkeypatch, french, tmp_path):
    from neopedal import plugin_loader
    from neopedal.ui.plugin_manager import PluginManager

    monkeypatch.setattr(plugin_loader, "PLUGIN_FOLDER", str(tmp_path / "plugins"))  # no plugin shipped with the app
    plugin = tmp_path / "plugins" / "gauge"
    plugin.mkdir(parents=True)
    (plugin / "setting.json").write_text("{}", encoding="utf-8")
    (plugin / "widget.py").write_text("Realtime = object\n", encoding="utf-8")
    asked = []

    def question(*args, **kwargs):
        asked.append(args[1:3])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: pytest.fail(f"warning: {args}")))
    flush()
    manager = PluginManager(None)
    try:
        manager.table.selectRow(0)  # plugin of this test
        manager.trust_selected()
        title, message = asked[0]
        assert title == "Approuver le plugin…"
        assert "accès complet à votre ordinateur" in message and "vous faites confiance à son auteur" in message
        assert "Fichiers de code :" in message and "SHA-256 : <code>" in message
        for english in ("Python code", "Only trust", "Code files", "Trust this plugin", "requires trusting"):
            assert english not in message
    finally:
        manager.close()
        flush()


# Plugin badges
def test_plugin_badge_colors_follow_window_theme(ui_env):
    from neopedal.ui import STATUS_COLORS, plugin_manager

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


def test_plugin_enabled_badge_is_palette_accent(ui_env, monkeypatch, app_ctx):
    from types import SimpleNamespace

    from neopedal.ui import plugin_manager

    monkeypatch.setattr(plugin_manager, "discover_plugins", lambda: ["plugin_on", "plugin_off"])
    app_ctx(wctrl=SimpleNamespace(names=["plugin_on", "plugin_off"]))
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
