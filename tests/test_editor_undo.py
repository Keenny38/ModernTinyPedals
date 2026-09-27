"""Editor undo & redo tests"""

import pytest

from tinypedal.setting import cfg
from tinypedal.userfile.json_setting import copy_setting


@pytest.fixture
def class_editor(monkeypatch):
    from tinypedal.ui.vehicle_class_editor import VehicleClassEditor

    cfg.default.set_default()
    monkeypatch.setattr(cfg.user, "classes", {
        "Hypercar": {"alias": "HY", "color": "#FF0000", "preset": ""},
        "LMGT3": {"alias": "GT3", "color": "#00FF00", "preset": ""},
    }, raising=False)
    for name in ("config", "setting", "heatmap"):
        monkeypatch.setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)), raising=False)
    editor = VehicleClassEditor(None)
    yield editor
    editor.set_unmodified()
    editor.close()


def alias(editor, row):
    return editor.table_classes.item(row, 1).text()


def test_undo_redo_cell_edit(class_editor):
    class_editor.table_classes.item(0, 1).setText("HYPER")
    class_editor.table_classes.item(1, 1).setText("GT")
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HYPER", "GT")

    class_editor.undo()
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HYPER", "GT3")
    class_editor.undo()
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HY", "GT3")
    class_editor.undo()  # nothing more to undo
    assert alias(class_editor, 0) == "HY"

    class_editor.redo()
    class_editor.redo()
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HYPER", "GT")


def test_new_edit_clears_redo(class_editor):
    class_editor.table_classes.item(0, 1).setText("A")
    class_editor.undo()
    class_editor.table_classes.item(0, 1).setText("B")
    class_editor.redo()  # redo history cleared by new edit
    assert alias(class_editor, 0) == "B"


def test_heatmap_undo(monkeypatch):
    from tinypedal.ui.heatmap_editor import HeatmapEditor

    cfg.default.set_default()
    for name in ("config", "setting", "heatmap"):
        monkeypatch.setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)), raising=False)
    editor = HeatmapEditor(None)
    before = editor.capture_table()
    editor.table_heatmap.item(0, 0).setText("-99.0")
    assert editor.capture_table() != before
    editor.undo()
    assert editor.capture_table() == before
    editor.set_unmodified()
    editor.close()
