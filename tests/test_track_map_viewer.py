"""Track map viewer: load map, every overlay drawn (curve, slope, circles, marks), controls"""

import math

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor

from tinypedal.setting import cfg


def write_map(folder: str, name: str = "Ring"):
    """Oval 2 km track with elevation, sectors at 1/3 & 2/3"""
    from tinypedal.userfile.track_map import save_track_map_file

    nodes = 200
    coords, dists = [], []
    for index in range(nodes):
        angle = index / nodes * math.tau
        coords.append((400 * math.cos(angle), 250 * math.sin(angle)))
        dists.append((index * 10.0, 20 * math.sin(angle * 2)))
    save_track_map_file(folder, name, "-420 -270 840 540", tuple(coords), tuple(dists), (66, 133), decimals=2)


@pytest.fixture
def viewer(ui_env):
    from tinypedal.ui.track_map_viewer import TrackMapViewer

    write_map(cfg.path.track_map)
    for key, value in cfg.user.config["track_map_viewer"].items():
        if key.startswith("show_") and isinstance(value, bool):
            cfg.user.config["track_map_viewer"][key] = True  # every overlay
    dialog = TrackMapViewer(None, cfg.path.track_map, "Ring")
    dialog.resize(700, 600)
    yield dialog
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def drawn(widget) -> int:
    image = widget.grab().toImage()
    return sum(1 for y in range(0, image.height(), 7) for x in range(0, image.width(), 7)
               if QColor(image.pixel(x, y)).lightness() > 40)


def test_map_loaded_and_drawn(viewer):
    view = viewer.trackmap
    assert view.map_filename == "Ring" and view.edit_filename.text() == "Ring"
    assert view.map_nodes == 200 and view.map_length == pytest.approx(1990, abs=1)
    assert view.slider_pos_dist.maximum() == view.map_length
    assert drawn(view) > 50


@pytest.mark.parametrize("position", [0, 300, 1000, 1900])
def test_position_curve_slope_info(viewer, position):
    view = viewer.trackmap
    view.spinbox_pos_dist.setValue(position)
    assert view.slider_pos_dist.value() == position and view.map_seek_dist == position
    view.update_highlighted_coords()
    assert view.highlighted_coords is not None
    assert drawn(view) > 50


def test_zoom_nodes_and_marks(viewer):
    view = viewer.trackmap
    view.spinbox_map_scale.setValue(3.0)
    view.spinbox_nodes.setValue(25)
    assert view.map_scale == 3.0 and view.curve_nodes == 25
    view.update_marked_coords({100.0, 900.0, 5000.0})  # out of track ignored
    assert len(view.marked_coords) == 2
    view.update_marked_coords({100.0, 900.0, 5000.0})  # same marks: unchanged
    assert drawn(view) > 0
    view.load_config()  # config reloaded after edit


def test_open_other_map_and_invalid(viewer, monkeypatch, tmp_path):
    from tinypedal.ui import track_map_viewer

    write_map(f"{tmp_path.as_posix()}/", "Other")
    monkeypatch.setattr(track_map_viewer.QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Other.svg"), ""))
    view = viewer.trackmap
    view.open_trackmap()
    assert view.map_filename == "Other"
    (tmp_path / "Bad.svg").write_text("<svg></svg>", encoding="utf-8")
    warnings = []
    monkeypatch.setattr(track_map_viewer.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(track_map_viewer.QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Bad.svg"), ""))
    view.open_trackmap()
    assert warnings and view.map_filename == ""  # invalid map: warned, map cleared


def test_context_menu_lists_overlays(viewer):
    menu = viewer.trackmap.set_context_menu()
    checkable = [action for action in menu.actions() if action.isCheckable()]
    assert len(checkable) == 11 and all(action.isChecked() for action in checkable)


def test_svg_not_made_by_app_is_invalid_map(tmp_path):
    from tinypedal.userfile.track_map import load_track_map_file

    (tmp_path / "Logo.svg").write_text('<svg><path d="M0 0"/></svg>', encoding="utf-8")
    assert load_track_map_file(f"{tmp_path.as_posix()}/", "Logo") == (None, None, None)  # was TypeError
