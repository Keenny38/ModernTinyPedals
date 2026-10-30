"""Editor undo & redo tests (table editor pages: snapshots of backend rows)"""

import pytest

from neopedal.setting import cfg
from neopedal.userfile.json_setting import copy_setting


@pytest.fixture
def class_editor(monkeypatch):
    from neopedal.ui.vehicle_class_editor import VehicleClassEditor

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
    return editor.backend.rows[row][1]


def set_alias(editor, row, text):
    backend = editor.backend
    assert backend.setCell(backend.keys[row], 1, text)


def test_undo_redo_cell_edit(class_editor):
    set_alias(class_editor, 0, "HYPER")
    set_alias(class_editor, 1, "GT")
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HYPER", "GT")
    assert class_editor.backend.canUndo and not class_editor.backend.canRedo

    class_editor.undo()
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HYPER", "GT3")
    class_editor.undo()
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HY", "GT3")
    assert not class_editor.backend.canUndo and class_editor.backend.canRedo
    class_editor.undo()  # nothing more to undo
    assert alias(class_editor, 0) == "HY"

    class_editor.backend.redo()  # Redo button of page
    class_editor.redo()
    assert (alias(class_editor, 0), alias(class_editor, 1)) == ("HYPER", "GT")


def test_new_edit_clears_redo(class_editor):
    set_alias(class_editor, 0, "A")
    class_editor.undo()
    set_alias(class_editor, 0, "B")
    class_editor.redo()  # redo history cleared by new edit
    assert alias(class_editor, 0) == "B"


def test_heatmap_undo(monkeypatch):
    from neopedal.ui.heatmap_editor import HeatmapEditor

    cfg.default.set_default()
    for name in ("config", "setting", "heatmap"):
        monkeypatch.setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)), raising=False)
    editor = HeatmapEditor(None)
    backend = editor.backend
    before = backend.capture_state()
    assert backend.setCell(backend.keys[0], 0, "-99")
    assert backend.capture_state() != before
    editor.undo()
    assert backend.capture_state() == before
    editor.set_unmodified()
    editor.close()
