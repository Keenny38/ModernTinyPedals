"""Audit fixes (package C), editors: notes saving errors, heatmap presets, duplicate names & colors,
track map marks, Rest API import in background, translated tables & messages"""

import sys
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from neopedal import i18n
from neopedal.setting import cfg
from neopedal.ui._common import BaseEditor


class Env:
    def __init__(self, saved, warnings):
        self.saved = saved
        self.warnings = warnings


@pytest.fixture
def env(ui_env, monkeypatch):
    """Editors confirm every question, warnings recorded, no module reload after saving

    Exceptions raised in Qt slots or in background threads fail the test.
    """
    warnings = []
    errors = []
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(BaseEditor, "reloading", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard))
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: errors.append(exc_info[1]))
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    yield Env(saved=ui_env, warnings=warnings)
    assert not errors


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


def close_editor(editor):
    editor.set_unmodified()
    editor.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_until(condition, timeout: float = 5.0) -> bool:
    """Process Qt events until condition is true (answers from background threads)"""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return True


def join_request_threads():
    for thread in threading.enumerate():
        if thread.name == "Game request":
            thread.join(5)


# --- Track notes editor (item 3), Qt Quick page since the UI/UX audit of 2026-10-29 (state in track_notes_backend)
@pytest.fixture
def notes_editor(env):
    from neopedal.ui import track_notes_editor

    editor = track_notes_editor.TrackNotesEditor(None)
    yield editor
    close_editor(editor)


def first_key(editor) -> int:
    return editor.backend.rows[0]["key"]


def test_notes_save_error_on_close_keeps_editor_open(notes_editor, env, tmp_path, monkeypatch):
    from neopedal.ui.quick import track_notes_backend

    def read_only(**kwargs):
        raise PermissionError(13, "Permission denied")

    backend = notes_editor.backend
    backend.create("Pace Notes")
    backend.setValue(first_key(notes_editor), "note", "R3")
    assert notes_editor.is_modified()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Save))
    monkeypatch.setattr(track_notes_backend.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Spa.tppn"), "NeoPedal Pace Notes (*.tppn)"))
    monkeypatch.setattr(track_notes_backend, "save_notes_file", read_only)
    assert notes_editor.close() is False  # saving failed: treated as cancel
    assert len(env.warnings) == 1 and "Unable to save notes at:" in env.warnings[0]
    assert notes_editor.is_modified()
    assert backend.rows[0]["note"] == "R3"  # notes kept


def test_notes_save_error_from_button(notes_editor, env, tmp_path, monkeypatch):
    from neopedal.ui.quick import track_notes_backend

    backend = notes_editor.backend
    backend.create("Pace Notes")
    backend.setValue(first_key(notes_editor), "note", "R3")
    target = tmp_path / "missing folder" / "Spa.tppn"  # folder does not exist
    monkeypatch.setattr(track_notes_backend.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(target), "NeoPedal Pace Notes (*.tppn)"))
    assert not backend.save()
    assert env.warnings and notes_editor.is_modified()
    monkeypatch.setattr(track_notes_backend.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Spa.tppn"), "NeoPedal Pace Notes (*.tppn)"))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Save))
    assert notes_editor.confirm_discard()  # saved this time
    assert (tmp_path / "Spa.tppn").exists() and not notes_editor.is_modified()


def test_notes_metadata_edit_marks_modified(notes_editor):
    backend = notes_editor.backend
    backend.create("Pace Notes")
    assert not notes_editor.is_modified()
    backend.setMetadata(dict(backend.metadata))  # nothing changed
    assert not notes_editor.is_modified()
    backend.setMetadata({**backend.metadata, "AUTHOR": "Steven"})
    assert backend.metadata["AUTHOR"] == "Steven"
    assert notes_editor.is_modified()


def test_notes_delete_last_note_clears_map_marks(notes_editor):
    backend = notes_editor.backend
    trackmap = backend.trackMap
    trackmap.raw_coords = [(float(index), 0.0) for index in range(20)]
    trackmap.raw_dists = [(index * 10.0, 0.0) for index in range(20)]
    trackmap.map_length = 190.0
    backend.create("Pace Notes")
    backend.setValue(first_key(notes_editor), "distance", "50")
    assert len(backend.marks) == 1
    backend.setValue(first_key(notes_editor), "distance", "999")  # out of track: no mark
    assert backend.marks == []
    backend.setValue(first_key(notes_editor), "distance", "50")
    backend.select(first_key(notes_editor), 0)
    backend.deleteSelected()
    assert backend.rowCount == 0 and backend.marks == []


def test_notes_show_map_button_translated(notes_editor, french):
    backend = notes_editor.backend
    assert backend.mapShown
    backend.toggleMap()
    assert not backend.mapShown and i18n.tr("Show Map") == "Afficher la carte"
    backend.toggleMap()
    assert backend.mapShown and i18n.tr("Hide Map") == "Masquer la carte"


def test_map_menu_translated_without_key_lookup(notes_editor, french):
    """Show menu of the notes map: translated texts, config keys carried by each entry (never found back from
    the text with untr)"""
    from neopedal.ui.quick.track_map_backend import OVERLAYS

    trackmap = notes_editor.backend.trackMap
    entries = trackmap.overlayMenu
    assert [entry["key"] for entry in entries] == [key for key, _ in OVERLAYS]
    assert all(entry["key"] in trackmap.ecfg for entry in entries)
    assert [entry["text"] for entry in entries] == [i18n.tr(text) for _, text in OVERLAYS]
    assert sum(entry["text"] != text for entry, (_, text) in zip(entries, OVERLAYS)) >= len(OVERLAYS) - 1  # French
    assert i18n.tr("Marked Coordinates") == "Positions marquées"


# --- Heatmap editor (item 12)
@pytest.fixture
def heatmap_editor(env):
    from neopedal.ui.heatmap_editor import HeatmapEditor

    editor = HeatmapEditor(None)
    yield editor
    close_editor(editor)


def set_cell(editor, row: int, column: int, text: str) -> bool:
    backend = editor.backend
    return backend.setCell(backend.keys[row], column, text)


def test_heatmap_switch_preset_not_modified(heatmap_editor):
    backend = heatmap_editor.backend
    assert not heatmap_editor.is_modified()
    assert backend.selectPreset(1)
    assert backend.selected_key == backend.presetNames[1] and backend.presetIndex == 1
    assert backend.selectPreset(0)
    assert not heatmap_editor.is_modified()


def test_heatmap_new_name_checked_against_unsaved_presets(heatmap_editor, env):
    backend = heatmap_editor.backend
    assert backend.checkPresetName("") and backend.checkPresetName("bad name")  # letters, digits & _ only
    backend.createPreset("custom", False)
    assert backend.selected_key == "custom" and heatmap_editor.is_modified()
    backend.addRow()
    assert set_cell(heatmap_editor, 1, 0, "55")
    assert backend.checkPresetName("custom") == "Preset already exists."  # not saved yet, but exists
    backend.createPreset("custom", False)
    assert env.warnings == ["Preset already exists."]
    assert backend.presetNames.count("custom") == 1
    assert backend.rows[1][0] == 55  # edits kept
    backend.deletePreset()  # no other "custom" entry left behind
    assert "custom" not in backend.presetNames
    assert "custom" not in backend.heatmap_temp


def test_heatmap_copy_includes_table_edits(heatmap_editor):
    backend = heatmap_editor.backend
    source = backend.selected_key
    assert set_cell(heatmap_editor, 1, 0, "45")
    backend.createPreset("copied", True)
    assert backend.selected_key == "copied"
    assert "45.0" in backend.heatmap_temp["copied"]
    assert "45.0" in backend.heatmap_temp[source]
    heatmap_editor.applying()
    assert "45.0" in cfg.user.heatmap["copied"]


def test_heatmap_duplicate_temperature_refused(heatmap_editor, env):
    backend = heatmap_editor.backend
    source = backend.selected_key
    rows = len(backend.rows)
    assert set_cell(heatmap_editor, 1, 0, backend.display(0, backend.rows[2][0]))
    assert backend.model.rows[1]["marks"][0] == "error"  # shown at once
    assert not backend.save()
    assert "heatmap" not in env.saved
    assert env.warnings[-1].startswith("Temperature <b>") and "listed more than once" in env.warnings[-1]
    assert not backend.selectPreset(1)  # cannot leave preset either
    assert backend.selected_key == source and backend.presetIndex == 0
    assert len(backend.rows) == rows and len(env.warnings) == 2
    backend.createPreset("copied", True)
    assert len(env.warnings) == 3 and "copied" not in backend.heatmap_temp
    assert set_cell(heatmap_editor, 1, 0, "1")
    assert backend.save()
    assert len(cfg.user.heatmap[source]) == rows


def test_heatmap_invalid_color_refused(heatmap_editor, env):
    backend = heatmap_editor.backend
    source = backend.selected_key
    assert not set_cell(heatmap_editor, 0, 1, "#12")  # refused while typing
    backend.rows[0][1] = "#12"  # invalid color of a file edited by hand
    backend.refresh()
    assert backend.model.rows[0]["marks"][1] == "error"
    saved_colors = dict(cfg.user.heatmap[source])
    heatmap_editor.applying()
    assert "heatmap" not in env.saved and cfg.user.heatmap[source] == saved_colors
    assert env.warnings[-1].startswith("Invalid color <b>#12</b>")
    assert set_cell(heatmap_editor, 0, 1, "#123")
    heatmap_editor.applying()
    assert "heatmap" in env.saved and "#123" in cfg.user.heatmap[source].values()


# --- Duplicate names & colors (item 12, 22)
EDITORS = {
    "brakes": ("brake_editor", "BrakeEditor"),
    "brands": ("vehicle_brand_editor", "VehicleBrandEditor"),
    "classes": ("vehicle_class_editor", "VehicleClassEditor"),
    "compounds": ("tyre_compound_editor", "TyreCompoundEditor"),
    "tracks": ("track_info_editor", "TrackInfoEditor"),
}


def build_editor(config_type: str):
    import importlib

    module_name, class_name = EDITORS[config_type]
    module = importlib.import_module(f"neopedal.ui.{module_name}")
    editor = getattr(module, class_name)(None)
    return editor, editor.backend


def add_row(backend, name: str):
    backend.append_rows([backend.new_row(name)])


@pytest.mark.parametrize("config_type", list(EDITORS))
def test_duplicate_name_refused(config_type, env):
    editor, backend = build_editor(config_type)
    try:
        saved_data = dict(getattr(cfg.user, config_type))
        add_row(backend, "Duplicated")
        add_row(backend, "Duplicated")
        rows = len(backend.rows)
        editor.saving()
        assert config_type not in env.saved and editor.is_modified()
        assert env.warnings == ["<b>Duplicated</b> is listed more than once.<br><br>"
                                "Each name can only be listed once, rename or delete duplicate rows."]
        assert getattr(cfg.user, config_type) == saved_data and len(backend.rows) == rows
        assert backend.currentIndex == rows - 1  # duplicate row shown
        assert backend.setCell(backend.keys[-1], 0, "Renamed")
        editor.saving()
        assert config_type in env.saved and not editor.is_modified()
        assert {"Duplicated", "Renamed"} <= set(getattr(cfg.user, config_type))
    finally:
        close_editor(editor)


@pytest.mark.parametrize("config_type", ["classes", "compounds"])
def test_invalid_color_refused(config_type, env):
    editor, backend = build_editor(config_type)
    try:
        add_row(backend, "Colored")
        key = backend.keys[-1]
        assert not backend.checkCell(2, "#12") and not backend.setCell(key, 2, "#12")
        assert not backend.setCell(key, 2, "")
        backend.rows[-1][2] = "#12"  # from a file edited by hand
        editor.applying()
        assert config_type not in env.saved and "Colored" not in getattr(cfg.user, config_type)
        assert env.warnings[-1].startswith("Invalid color <b>#12</b> for <b>Colored</b>.")
        assert backend.setCell(key, 2, "#80112233")
        editor.applying()
        assert getattr(cfg.user, config_type)["Colored"]["color"] == "#80112233"
    finally:
        close_editor(editor)


def test_brand_import_refused_with_duplicate_names(env):
    editor, backend = build_editor("brands")
    try:
        add_row(backend, "Duplicated")
        add_row(backend, "Duplicated")
        rows = len(backend.rows)
        backend.import_vehicles([{"desc": "Porsche 963 #6", "manufacturer": "Porsche"}])
        assert len(backend.rows) == rows and "listed more than once" in env.warnings[-1]
    finally:
        close_editor(editor)


# --- Vehicle brand Rest API import (item 28)
@pytest.fixture
def brand_editor(env, monkeypatch):
    from neopedal.ui import vehicle_brand_editor

    monkeypatch.setattr(cfg.user, "brands", {"Ferrari 296 #51": "Ferrari"}, raising=False)
    editor = vehicle_brand_editor.VehicleBrandEditor(None)
    yield editor
    join_request_threads()
    QCoreApplication.processEvents()  # answer delivered before editor is deleted
    close_editor(editor)


def test_brand_restapi_import_in_background(brand_editor, env, monkeypatch):
    from neopedal.ui import vehicle_brand_editor

    answer = threading.Event()
    requested = []

    def slow_game(url_host, url_port, resource_name):
        requested.append(resource_name)
        answer.wait(5)
        return [{"desc": "Porsche 963 #6", "manufacturer": "Porsche"}]

    backend = brand_editor.backend
    monkeypatch.setattr(vehicle_brand_editor, "request_vehicle_data", slow_game)
    backend.importFrom(0)  # returns at once, game still answering
    assert backend.busy  # Import disabled
    backend.importFrom(1)  # one request at a time
    answer.set()
    assert wait_until(lambda: not backend.busy)
    assert requested == ["/rest/race/car"]
    assert len(backend.rows) == 2 and brand_editor.is_modified()
    assert not env.warnings


def test_brand_restapi_unreachable_warns(brand_editor, env, monkeypatch):
    from neopedal.ui import vehicle_brand_editor

    def refused(*args):
        raise OSError("refused")

    monkeypatch.setattr(vehicle_brand_editor, "resolve_hostname", refused)
    brand_editor.backend.importFrom(0)
    assert wait_until(lambda: env.warnings)
    assert env.warnings == ["Unable to import vehicle data from LMU Rest API.<br><br>"
                            "Make sure game is running and try again."]
    assert not brand_editor.backend.busy and len(brand_editor.backend.rows) == 1


def test_brand_restapi_invalid_answer_warns(brand_editor, env, monkeypatch):
    from neopedal.ui import vehicle_brand_editor

    monkeypatch.setattr(vehicle_brand_editor, "request_vehicle_data", lambda *args: [{"other": 1}])
    brand_editor.backend.importFrom(2)  # rFactor 2
    assert wait_until(lambda: env.warnings)
    assert "RF2 Rest API" in env.warnings[0] and len(brand_editor.backend.rows) == 1


def test_brand_restapi_answer_after_editor_closed(env, monkeypatch):
    from neopedal.ui import vehicle_brand_editor

    answer = threading.Event()
    answered = threading.Event()

    def slow_game(url_host, url_port, resource_name):
        answer.wait(5)
        answered.set()
        return [{"desc": "Porsche 963 #6", "manufacturer": "Porsche"}]

    monkeypatch.setattr(vehicle_brand_editor, "request_vehicle_data", slow_game)
    editor = vehicle_brand_editor.VehicleBrandEditor(None)
    editor.backend.importFrom(0)
    close_editor(editor)  # deleted while game still answering
    answer.set()
    assert answered.wait(5)
    join_request_threads()
    QCoreApplication.processEvents()  # nothing left to deliver, no error
    assert not env.warnings


# --- Translated tables, titles & messages (item 29)
@pytest.mark.parametrize("module_name, class_name, headers", [
    ("brake_editor", "BrakeEditor", ["Nom du frein", "Épaisseur de rupture (mm)", "Nom de la heatmap"]),
    ("heatmap_editor", "HeatmapEditor", ["Température (°C)", "Couleur"]),
    ("track_info_editor", "TrackInfoEditor", [
        "Nom du circuit", "Entrée des stands (m)", "Sortie des stands (m)", "Vitesse dans les stands (km/h)",
        "Radar de vitesse (m)", "Orientation de la carte (°)", "Lever du soleil", "Coucher du soleil",
        "Preset principal"]),
    ("tyre_compound_editor", "TyreCompoundEditor", ["Nom de la gomme", "Symbole", "Couleur", "Nom de la heatmap"]),
    ("vehicle_brand_editor", "VehicleBrandEditor", ["Nom du véhicule", "Marque"]),
    ("vehicle_class_editor", "VehicleClassEditor", ["Nom de la catégorie", "Alias", "Couleur"]),
])
def test_table_headers_translated(module_name, class_name, headers, env, french):
    import importlib

    module = importlib.import_module(f"neopedal.ui.{module_name}")
    editor = getattr(module, class_name)(None)
    try:
        assert [column["header"] for column in editor.backend.columns] == headers
    finally:
        close_editor(editor)


def test_replace_in_translated_column(env, french):
    from neopedal.ui.tyre_compound_editor import TyreCompoundEditor

    editor = TyreCompoundEditor(None)
    try:
        backend = editor.backend
        assert backend.replaceColumns == [{"index": 1, "header": "Symbole"}]
        backend.append_rows([["Medium", "M", "#FFFF00", "HEATMAP_DEFAULT_TYRE"]])
        assert backend.replace(1, "M", "D", True, True) >= 1
        assert backend.rows[-1][1] == "D"
    finally:
        close_editor(editor)


def test_heatmap_preset_texts_translated(heatmap_editor, french):
    assert i18n.tr("Create Heatmap Preset") == "Créer une heatmap"
    assert i18n.tr("Duplicate Heatmap Preset") == "Dupliquer la heatmap"
    assert heatmap_editor.backend.checkPresetName("x y") == "Nom de preset invalide."


@pytest.mark.parametrize("message, translated", [
    ("Cannot open selected file.<br><br>Invalid notes file.",
     "Impossible d'ouvrir le fichier sélectionné.<br><br>Fichier de notes invalide."),
    ("Cannot import selected file.<br><br>Invalid vehicle data file.",
     "Impossible d'importer le fichier sélectionné.<br><br>Fichier de données véhicules invalide."),
    ("Set position at <b>12.5</b> from map?", "Placer la position à <b>12.5</b> depuis la carte ?"),
    ("Set position at <b>12.5</b> from telemetry?", "Placer la position à <b>12.5</b> depuis la télémétrie ?"),
    ("Set speed trap at position <b>1234.5</b><br>for <b>Spa</b>?",
     "Placer le radar de vitesse à la position <b>1234.5</b><br>pour <b>Spa</b> ?"),
    ("Unable to save notes at:<br><b>C:/notes/Spa.tppn</b><br><br>"
     "Make sure the folder is writable, or save notes to another folder.",
     "Impossible d'enregistrer les notes dans :<br><b>C:/notes/Spa.tppn</b><br><br>"
     "Vérifiez que le dossier est accessible en écriture, ou enregistrez les notes dans un autre dossier."),
    ("Temperature <b>80.0</b> is listed more than once.<br><br>"
     "Each temperature can only be listed once, change or remove duplicate rows.",
     "La température <b>80.0</b> apparaît plusieurs fois.<br><br>"
     "Chaque température ne peut apparaître qu'une fois, modifiez ou retirez les lignes en double."),
    ("<b>Soft</b> is listed more than once.<br><br>"
     "Each name can only be listed once, rename or delete duplicate rows.",
     "<b>Soft</b> apparaît plusieurs fois.<br><br>"
     "Chaque nom ne peut apparaître qu'une fois, renommez ou supprimez les lignes en double."),
    ("Invalid color <b>#12</b> for <b>80.0 °C</b>.<br><br>Use #RGB, #RRGGBB or #AARRGGBB format.",
     "Couleur invalide <b>#12</b> pour <b>80.0 °C</b>.<br><br>Utilisez le format #RVB, #RRVVBB ou #AARRVVBB."),
])
def test_editor_messages_translated(message, translated, french):
    assert i18n.trm(message) == translated
