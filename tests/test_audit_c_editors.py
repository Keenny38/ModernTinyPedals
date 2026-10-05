"""Audit fixes (package C), editors: notes saving errors, heatmap presets, duplicate names & colors,
track map marks, Rest API import in background, translated tables & messages"""

import sys
import threading
import time
from typing import cast

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QMessageBox

from tinypedal import i18n
from tinypedal.setting import cfg
from tinypedal.ui._common import BaseEditor, TableBatchReplace
from tinypedal.ui._option import ColorEdit


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


# --- Track notes editor (item 3)
@pytest.fixture
def notes_editor(env, monkeypatch):
    from tinypedal.ui import track_notes_editor

    monkeypatch.setattr(track_notes_editor, "show_toast", lambda *args, **kwargs: None)
    editor = track_notes_editor.TrackNotesEditor(None)
    yield editor
    close_editor(editor)


def test_notes_save_error_on_close_keeps_editor_open(notes_editor, env, tmp_path, monkeypatch):
    from tinypedal.ui import track_notes_editor

    def read_only(**kwargs):
        raise PermissionError(13, "Permission denied")

    notes_editor.create_pacenotes()
    notes_editor.table_notes.item(0, 1).setText("R3")
    assert notes_editor.is_modified()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Save))
    monkeypatch.setattr(track_notes_editor.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Spa.tppn"), "TinyPedal Pace Notes (*.tppn)"))
    monkeypatch.setattr(track_notes_editor, "save_notes_file", read_only)
    assert notes_editor.close() is False  # saving failed: treated as cancel
    assert len(env.warnings) == 1 and "Unable to save notes at:" in env.warnings[0]
    assert notes_editor.is_modified()
    assert notes_editor.table_notes.item(0, 1).text() == "R3"  # notes kept


def test_notes_save_error_from_button(notes_editor, env, tmp_path, monkeypatch):
    from tinypedal.ui import track_notes_editor

    notes_editor.create_pacenotes()
    notes_editor.table_notes.item(0, 1).setText("R3")
    target = tmp_path / "missing folder" / "Spa.tppn"  # folder does not exist
    monkeypatch.setattr(track_notes_editor.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(target), "TinyPedal Pace Notes (*.tppn)"))
    notes_editor.saving()
    assert env.warnings and notes_editor.is_modified()
    monkeypatch.setattr(track_notes_editor.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Spa.tppn"), "TinyPedal Pace Notes (*.tppn)"))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Save))
    assert notes_editor.confirm_discard()  # saved this time
    assert (tmp_path / "Spa.tppn").exists() and not notes_editor.is_modified()


def test_notes_metadata_edit_marks_modified(notes_editor):
    from tinypedal.ui.track_notes_editor import MetaDataEditor

    notes_editor.create_pacenotes()
    assert not notes_editor.is_modified()
    notes_editor.open_metadata_dialog()
    notes_editor.findChild(MetaDataEditor).saving()  # nothing changed
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # closed dialog deleted
    assert not notes_editor.is_modified()
    notes_editor.open_metadata_dialog()
    dialog = notes_editor.findChild(MetaDataEditor)
    dialog.option_metadata["AUTHOR"].setText("Steven")
    dialog.saving()
    assert notes_editor.notes_metadata["AUTHOR"] == "Steven"
    assert notes_editor.is_modified()


def test_notes_delete_last_note_clears_map_marks(notes_editor):
    trackmap = notes_editor.trackmap
    trackmap.raw_coords = [(float(index), 0.0) for index in range(20)]
    trackmap.raw_dists = [(index * 10.0, 0.0) for index in range(20)]
    trackmap.map_nodes = 20
    trackmap.map_length = 190.0
    notes_editor.create_pacenotes()
    notes_editor.table_notes.item(0, 0).setText("50")
    assert len(trackmap.marked_coords) == 1
    notes_editor.table_notes.selectRow(0)
    notes_editor.delete_notes()
    assert notes_editor.table_notes.rowCount() == 0
    assert trackmap.marked_coords == [] and trackmap.marked_dists == set()


def test_notes_show_map_button_translated(notes_editor, french):
    notes_editor.toggle_trackmap_panel(False)
    assert notes_editor.button_showmap.text() == "Afficher la carte"
    notes_editor.toggle_trackmap_panel(True)
    assert notes_editor.button_showmap.text() == "Masquer la carte"


# --- Track map widget (item 25, 29)
@pytest.fixture
def map_view(env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.track_map_widget import MapView

    parent = QWidget()
    view = MapView(parent)
    view.raw_coords = [(float(index), 0.0) for index in range(20)]
    view.raw_dists = [(index * 10.0, 0.0) for index in range(20)]
    view.map_nodes = 20
    view.map_length = 190.0
    yield view
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_map_marks_cleared_without_distance(map_view):
    map_view.update_marked_coords({10.0, 50.0, 999.0})  # out of track ignored
    assert len(map_view.marked_coords) == 2
    map_view.update_marked_coords(set())
    assert map_view.marked_coords == [] and map_view.marked_dists == set()


class FakePainter:
    def __init__(self):
        self.texts = []

    def drawText(self, rect, flags, text):
        self.texts.append(text)


def test_map_menu_and_info_translated(map_view, french, monkeypatch):
    for key in ("show_map_info", "show_curve_info", "show_slope_info", "show_position_info"):
        monkeypatch.setitem(map_view.ecfg, key, True)
    menu = map_view.set_context_menu()
    texts = [action.text() for action in menu.actions() if action.isCheckable()]
    assert "Fond sombre" in texts and "Positions marquées" in texts
    for text in texts:  # menu action dispatch finds config key back
        assert "show_" + i18n.untr(text).replace(" ", "_").lower() in map_view.ecfg
    painter = FakePainter()
    map_view.draw_map_info(painter)
    map_view.draw_curve_info(painter, 120.0, 30.0, 45.0, "Right Hairpin", "Short")
    map_view.draw_slope_info(painter, 0.02, 1.1, 2.4, "Gentle")
    map_view.draw_position_info(painter, 1.0, 2.0, 3.0, 4.0)
    text = "\n".join(painter.texts)
    for french_text in ("nœuds", "Courbe :", "Courte", "Rayon :", "Droite Épingle", "Angle :", "Pente :",
                        "Douce", "Delta :", "nœud 1"):
        assert french_text in text
    for english_text in ("Curve:", "Radius:", "Slope:", "Delta:", "node", "Short", "Hairpin"):
        assert english_text not in text


# --- Heatmap editor (item 12)
@pytest.fixture
def heatmap_editor(env):
    from tinypedal.ui.heatmap_editor import HeatmapEditor

    editor = HeatmapEditor(None)
    yield editor
    close_editor(editor)


def combo_texts(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def create_preset(editor, name: str, mode: str = ""):
    from tinypedal.ui.heatmap_editor import CreateHeatmapPreset

    dialog = CreateHeatmapPreset(editor, "test", mode)
    dialog.preset_entry.setText(name)
    dialog.creating()
    dialog.deleteLater()


def test_heatmap_switch_preset_not_modified(heatmap_editor):
    assert not heatmap_editor.is_modified()
    heatmap_editor.heatmap_list.setCurrentIndex(1)
    assert heatmap_editor.selected_heatmap_key == heatmap_editor.heatmap_list.itemText(1)
    heatmap_editor.heatmap_list.setCurrentIndex(0)
    assert not heatmap_editor.is_modified()


def test_heatmap_new_name_checked_against_unsaved_presets(heatmap_editor, env):
    from tinypedal.ui._common import FloatTableItem, table_item

    create_preset(heatmap_editor, "custom")
    assert heatmap_editor.selected_heatmap_key == "custom" and heatmap_editor.is_modified()
    heatmap_editor.add_temperature()
    table_item(heatmap_editor.table_heatmap, 1, 0).setText("55")
    create_preset(heatmap_editor, "custom")  # not saved yet, but exists
    assert env.warnings == ["Preset already exists."]
    assert combo_texts(heatmap_editor.heatmap_list).count("custom") == 1
    assert table_item(heatmap_editor.table_heatmap, 1, 0, FloatTableItem).value() == 55  # edits kept
    heatmap_editor.delete_heatmap()  # no other "custom" entry left behind
    assert "custom" not in combo_texts(heatmap_editor.heatmap_list)
    assert "custom" not in heatmap_editor.heatmap_temp


def test_heatmap_copy_includes_table_edits(heatmap_editor):
    source = heatmap_editor.selected_heatmap_key
    heatmap_editor.table_heatmap.item(1, 0).setText("45")
    create_preset(heatmap_editor, "copied", "duplicate")
    assert heatmap_editor.selected_heatmap_key == "copied"
    assert "45.0" in heatmap_editor.heatmap_temp["copied"]
    assert "45.0" in heatmap_editor.heatmap_temp[source]
    heatmap_editor.applying()
    assert "45.0" in cfg.user.heatmap["copied"]


def test_heatmap_duplicate_temperature_refused(heatmap_editor, env, monkeypatch):
    accepted = []
    monkeypatch.setattr(heatmap_editor, "accept", lambda: accepted.append(True))
    table = heatmap_editor.table_heatmap
    source = heatmap_editor.selected_heatmap_key
    rows = table.rowCount()
    table.item(1, 0).setText(table.item(2, 0).text())
    heatmap_editor.saving()
    assert not accepted and "heatmap" not in env.saved
    assert env.warnings[-1].startswith("Temperature <b>") and "listed more than once" in env.warnings[-1]
    heatmap_editor.heatmap_list.setCurrentIndex(1)  # cannot leave preset either
    assert heatmap_editor.selected_heatmap_key == source == heatmap_editor.heatmap_list.currentText()
    assert table.rowCount() == rows and len(env.warnings) == 2
    heatmap_editor.open_copy_dialog()
    assert len(env.warnings) == 3
    table.item(1, 0).setText("1")
    heatmap_editor.saving()
    assert accepted and len(cfg.user.heatmap[source]) == rows


def test_heatmap_invalid_color_refused(heatmap_editor, env):
    source = heatmap_editor.selected_heatmap_key
    saved_colors = dict(cfg.user.heatmap[source])
    color_edit = cast(ColorEdit, heatmap_editor.table_heatmap.cellWidget(0, 1))
    color_edit.setText("#12")
    heatmap_editor.applying()
    assert "heatmap" not in env.saved and cfg.user.heatmap[source] == saved_colors
    assert env.warnings[-1].startswith("Invalid color <b>#12</b>")
    color_edit.setText("#123")
    heatmap_editor.applying()
    assert "heatmap" in env.saved and "#123" in cfg.user.heatmap[source].values()


# --- Duplicate names & colors (item 12, 22)
EDITORS = {
    "brakes": ("brake_editor", "BrakeEditor", "table_brakes",
               lambda editor, row, name: editor.add_brake_entry(row, name, 0)),
    "brands": ("vehicle_brand_editor", "VehicleBrandEditor", "table_brands",
               lambda editor, row, name: editor.add_vehicle_entry(row, name, "Brand")),
    "classes": ("vehicle_class_editor", "VehicleClassEditor", "table_classes",
                lambda editor, row, name: editor.add_vehicle_entry(row, name, "NAME", "#FFFFFF")),
    "compounds": ("tyre_compound_editor", "TyreCompoundEditor", "table_compounds",
                  lambda editor, row, name: editor.add_compound_entry(row, name)),
    "tracks": ("track_info_editor", "TrackInfoEditor", "table_tracks",
               lambda editor, row, name: editor.add_track_entry(row, name, {})),
}


def build_editor(config_type: str):
    import importlib

    module_name, class_name, table_name, add_row = EDITORS[config_type]
    module = importlib.import_module(f"tinypedal.ui.{module_name}")
    editor = getattr(module, class_name)(None)
    return editor, getattr(editor, table_name), add_row


@pytest.mark.parametrize("config_type", list(EDITORS))
def test_duplicate_name_refused(config_type, env, monkeypatch):
    editor, table, add_row = build_editor(config_type)
    try:
        accepted = []
        monkeypatch.setattr(editor, "accept", lambda: accepted.append(True))
        saved_data = dict(getattr(cfg.user, config_type))
        add_row(editor, 0, "Duplicated")
        add_row(editor, 1, "Duplicated")
        rows = table.rowCount()
        editor.saving()
        assert not accepted and config_type not in env.saved
        assert env.warnings == ["<b>Duplicated</b> is listed more than once.<br><br>"
                                "Each name can only be listed once, rename or delete duplicate rows."]
        assert getattr(cfg.user, config_type) == saved_data and table.rowCount() == rows
        assert table.currentRow() == 1  # duplicate row shown
        table.item(1, 0).setText("Renamed")
        editor.saving()
        assert accepted and config_type in env.saved
        assert {"Duplicated", "Renamed"} <= set(getattr(cfg.user, config_type))
    finally:
        close_editor(editor)


@pytest.mark.parametrize("config_type", ["classes", "compounds"])
def test_invalid_color_refused(config_type, env):
    editor, table, add_row = build_editor(config_type)
    try:
        add_row(editor, 0, "Colored")
        color_edit = cast(ColorEdit, table.cellWidget(0, 2))
        color_edit.setText("#12")
        editor.applying()
        assert config_type not in env.saved and "Colored" not in getattr(cfg.user, config_type)
        assert env.warnings[-1].startswith("Invalid color <b>#12</b> for <b>Colored</b>.")
        color_edit.setText("")
        editor.applying()
        assert config_type not in env.saved and len(env.warnings) == 2
        color_edit.setText("#80112233")
        editor.applying()
        assert getattr(cfg.user, config_type)["Colored"]["color"] == "#80112233"
    finally:
        close_editor(editor)


def test_brand_import_refused_with_duplicate_names(env):
    editor, table, add_row = build_editor("brands")
    try:
        add_row(editor, 0, "Duplicated")
        add_row(editor, 1, "Duplicated")
        rows = table.rowCount()
        editor.parse_brand_data([{"desc": "Porsche 963 #6", "manufacturer": "Porsche"}])
        assert table.rowCount() == rows and "listed more than once" in env.warnings[-1]
    finally:
        close_editor(editor)


# --- Vehicle brand Rest API import (item 28)
@pytest.fixture
def brand_editor(env, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    monkeypatch.setattr(vehicle_brand_editor, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(cfg.user, "brands", {"Ferrari 296 #51": "Ferrari"}, raising=False)
    editor = vehicle_brand_editor.VehicleBrandEditor(None)
    yield editor
    join_request_threads()
    QCoreApplication.processEvents()  # answer delivered before editor is deleted
    close_editor(editor)


def test_brand_restapi_import_in_background(brand_editor, env, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    answer = threading.Event()
    requested = []

    def slow_game(url_host, url_port, resource_name):
        requested.append(resource_name)
        answer.wait(5)
        return [{"desc": "Porsche 963 #6", "manufacturer": "Porsche"}]

    monkeypatch.setattr(vehicle_brand_editor, "request_vehicle_data", slow_game)
    brand_editor.import_from_lmu()  # returns at once, game still answering
    assert not brand_editor.button_import.isEnabled()
    assert brand_editor.cursor().shape() == Qt.CursorShape.BusyCursor
    brand_editor.import_from_lmu()  # one request at a time
    answer.set()
    assert wait_until(brand_editor.button_import.isEnabled)
    assert requested == ["/rest/race/car"]
    assert brand_editor.cursor().shape() != Qt.CursorShape.BusyCursor
    assert brand_editor.table_brands.rowCount() == 2 and brand_editor.is_modified()
    assert not env.warnings


def test_brand_restapi_unreachable_warns(brand_editor, env, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    def refused(*args):
        raise OSError("refused")

    monkeypatch.setattr(vehicle_brand_editor, "resolve_hostname", refused)
    brand_editor.import_from_lmu()
    assert wait_until(lambda: env.warnings)
    assert env.warnings == ["Unable to import vehicle data from LMU Rest API.<br><br>"
                            "Make sure game is running and try again."]
    assert brand_editor.button_import.isEnabled() and brand_editor.table_brands.rowCount() == 1


def test_brand_restapi_invalid_answer_warns(brand_editor, env, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    monkeypatch.setattr(vehicle_brand_editor, "request_vehicle_data", lambda *args: [{"other": 1}])
    brand_editor.import_from_rf2()
    assert wait_until(lambda: env.warnings)
    assert "RF2 Rest API" in env.warnings[0] and brand_editor.table_brands.rowCount() == 1


def test_brand_restapi_answer_after_editor_closed(env, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    answer = threading.Event()
    answered = threading.Event()

    def slow_game(url_host, url_port, resource_name):
        answer.wait(5)
        answered.set()
        return [{"desc": "Porsche 963 #6", "manufacturer": "Porsche"}]

    monkeypatch.setattr(vehicle_brand_editor, "request_vehicle_data", slow_game)
    editor = vehicle_brand_editor.VehicleBrandEditor(None)
    editor.import_from_lmu()
    close_editor(editor)  # deleted while game still answering
    answer.set()
    assert answered.wait(5)
    join_request_threads()
    QCoreApplication.processEvents()  # nothing left to deliver, no error
    assert not env.warnings


# --- Translated tables, titles & messages (item 29)
@pytest.mark.parametrize("module_name, class_name, table_name, header_name", [
    ("brake_editor", "BrakeEditor", "table_brakes", "HEADER_BRAKES"),
    ("heatmap_editor", "HeatmapEditor", "table_heatmap", "HEADER_HEATMAP"),
    ("track_info_editor", "TrackInfoEditor", "table_tracks", "HEADER_TRACKS"),
    ("tyre_compound_editor", "TyreCompoundEditor", "table_compounds", "HEADER_COMPOUNDS"),
    ("vehicle_brand_editor", "VehicleBrandEditor", "table_brands", "HEADER_BRANDS"),
    ("vehicle_class_editor", "VehicleClassEditor", "table_classes", "HEADER_CLASSES"),
])
def test_table_headers_translated(module_name, class_name, table_name, header_name, env, french):
    import importlib

    from tinypedal.i18n.fr import TRANSLATION

    module = importlib.import_module(f"tinypedal.ui.{module_name}")
    editor = getattr(module, class_name)(None)
    try:
        table = getattr(editor, table_name)
        header = getattr(module, header_name)
        labels = [table.horizontalHeaderItem(index).text() for index in range(table.columnCount())]
        assert labels == [TRANSLATION[name] for name in header]
    finally:
        close_editor(editor)


def test_batch_replace_with_translated_column(env, french):
    from tinypedal.ui.tyre_compound_editor import TyreCompoundEditor

    editor = TyreCompoundEditor(None)
    try:
        editor.add_compound_entry(0, "Medium", "M")
        editor.open_replace_dialog()
        dialog = editor.findChild(TableBatchReplace)
        assert dialog.column_selector.currentText() == "Symbole"
        dialog.search_selector.setCurrentText("M")
        dialog.replace_entry.setText("D")
        dialog.replacing()
        assert editor.table_compounds.item(0, 1).text() == "D"
        dialog.close()
    finally:
        close_editor(editor)


def test_heatmap_dialog_titles_translated(heatmap_editor, french):
    from tinypedal.ui.heatmap_editor import CreateHeatmapPreset

    heatmap_editor.open_create_dialog()
    heatmap_editor.open_copy_dialog()
    titles = {dialog.windowTitle() for dialog in heatmap_editor.findChildren(CreateHeatmapPreset)}
    assert titles == {"Créer une heatmap", "Dupliquer la heatmap"}
    for dialog in heatmap_editor.findChildren(CreateHeatmapPreset):
        dialog.reject()


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
