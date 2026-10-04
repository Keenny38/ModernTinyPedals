"""Track map viewer (Qt Quick page) & track map widget of track notes editor: load map, position, curve, slope"""

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
    dialog = TrackMapViewer(None, cfg.path.track_map, "Ring")
    dialog.resize(900, 700)
    yield dialog
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- Track Map Viewer page
def test_map_loaded(viewer):
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    assert not viewer.view.errors() and viewer.view.rootObject() is not None
    assert backend.loaded and backend.mapName == "Ring"
    assert backend.nodes == 200 and backend.length == pytest.approx(1990, abs=1)
    view = backend.view
    assert view["minX"] == pytest.approx(-400) and view["maxY"] == pytest.approx(250, abs=1)
    assert sum(view["sectorLengths"]) == pytest.approx(backend.length)
    assert view["sectorStarts"] == pytest.approx([0.0, 660.0, 1330.0])
    for key in ("road", "edge", "sectors", "start", "sectorLines", "elevation", "elevationLine"):
        assert VertexStore.get(view[key]).vertex_count > 0, key
    assert view["minZ"] == pytest.approx(-20, abs=0.1) and view["maxZ"] == pytest.approx(20, abs=0.1)


@pytest.mark.parametrize("position", [0, 300, 1000, 1900])
def test_position_curve_slope_info(viewer, position):
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    backend.setPosition(position)
    current = backend.current
    assert backend.position == position and current["distance"] == pytest.approx(position, abs=10)
    assert current["radiusDesc"].startswith(("Left", "Right"))  # counter-clockwise oval
    assert current["sector"] == 1 + (position >= 660) + (position >= 1330)
    assert current["curveLength"] == pytest.approx(100, abs=10)  # 10 nodes 10 m apart
    assert -50 < current["slope"] < 50 and current["slopeDesc"]
    assert VertexStore.get(backend.view["section"]).vertex_count > 0
    assert VertexStore.get(backend.view["circle"]).vertex_count > 0


def test_curve_radius_of_oval(viewer):
    backend = viewer.backend
    backend.setPosition(0.0)  # end of oval: tightest part (radius b² / a)
    assert backend.current["radius"] == pytest.approx(250 ** 2 / 400, rel=0.15)
    backend.setPosition(500.0)  # side of oval: wide
    assert backend.current["radius"] > 400
    backend.setPosition(-50.0)
    assert backend.position == 0.0  # kept on track
    backend.setPosition(1e6)
    assert backend.position == backend.length


def test_nodes_pick_scale_and_overlays(viewer, monkeypatch):
    backend = viewer.backend
    backend.setCurveNodes(25)
    assert backend.curveNodes == 25 and backend.current["curveLength"] == pytest.approx(250, abs=10)
    backend.setCurveNodes(1)
    assert backend.curveNodes == 3
    assert backend.pick(400.0, 0.0, 20.0) == pytest.approx(0.0)  # first node
    assert backend.pick(0.0, 0.0, 20.0) == -1.0  # center of oval: far from track
    backend.setScale(5.0)  # zoomed out: lines at least some pixels wide
    assert backend._meters_per_pixel == 5.0
    saved = []
    monkeypatch.setattr(type(cfg), "save", lambda self, **kwargs: saved.append(kwargs))
    menu = backend.overlayMenu
    assert len(menu) == 10 and all(item["checked"] for item in menu)
    backend.setOverlay("show_curve_section", False)
    assert not backend.overlays["show_curve_section"] and saved
    backend.setOverlay("unknown", False)  # ignored
    assert "unknown" not in backend.overlays
    assert backend.settings["circles"] == [50, 100, 200, 300, 400, 500, 1000]
    assert QColor(backend.colors["start_line_color"]).isValid()
    backend.reload_config()  # config edited


def test_open_other_map_and_invalid(viewer, monkeypatch, tmp_path):
    from tinypedal.ui.quick import track_map_backend
    from tinypedal.ui.quick.lines import VertexStore

    write_map(f"{tmp_path.as_posix()}/", "Other")
    monkeypatch.setattr(track_map_backend.QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Other.svg"), ""))
    backend = viewer.backend
    backend.openMap()
    assert backend.mapName == "Other"
    (tmp_path / "Bad.svg").write_text("<svg></svg>", encoding="utf-8")
    warnings = []
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(track_map_backend.QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Bad.svg"), ""))
    backend.openMap()
    assert warnings and backend.mapName == "" and not backend.loaded  # invalid map: warned, map cleared
    assert backend.view == {} and not VertexStore.has(backend.key("road"))
    assert not backend.load_map(f"{tmp_path.as_posix()}/", "Missing")


def test_closed_page_releases_vertices(viewer):
    from tinypedal.ui.quick.lines import VertexStore

    key = viewer.backend.view["road"]
    viewer.close()
    assert not VertexStore.has(key)


def test_svg_not_made_by_app_is_invalid_map(tmp_path):
    from tinypedal.userfile.track_map import load_track_map_file

    (tmp_path / "Logo.svg").write_text('<svg><path d="M0 0"/></svg>', encoding="utf-8")
    assert load_track_map_file(f"{tmp_path.as_posix()}/", "Logo") == (None, None, None)  # was TypeError


def test_geometry_helpers():
    from tinypedal.ui.track_map_geometry import config_grades, curve_description, section_indices

    assert section_indices(10, 4, 8) == [8, 9, 0, 1]  # wraps around lap end
    assert section_indices(5, 10, 0) == [0, 1, 2]  # at most nodes - 2
    grades = config_grades(cfg.default.config["track_map_viewer"])
    assert curve_description(5000, 1, grades["curve"]) == "Straight"
    assert curve_description(10, -1, grades["curve"]) == "Left Hairpin"
    assert curve_description(30, 1, grades["curve"]) == "Right 2"


# --- Track map widget (track notes editor)
@pytest.fixture
def widget(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.track_map_widget import MapView

    write_map(cfg.path.track_map)
    for key, value in cfg.user.config["track_map_viewer"].items():
        if key.startswith("show_") and isinstance(value, bool):
            cfg.user.config["track_map_viewer"][key] = True  # every overlay
    parent = QWidget()
    view = MapView(parent)
    view.resize(700, 600)
    view.load_trackmap(cfg.path.track_map, "Ring")
    yield view
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def drawn(widget) -> int:
    image = widget.grab().toImage()
    return sum(1 for y in range(0, image.height(), 7) for x in range(0, image.width(), 7)
               if QColor(image.pixel(x, y)).lightness() > 40)


def test_widget_map_drawn_with_position(widget):
    assert widget.map_filename == "Ring" and widget.edit_filename.text() == "Ring"
    assert widget.map_nodes == 200 and widget.map_length == pytest.approx(1990, abs=1)
    for position in (0, 1000, 1900):
        widget.spinbox_pos_dist.setValue(position)
        assert widget.slider_pos_dist.value() == position and widget.map_seek_dist == position
        widget.update_highlighted_coords()
        assert widget.highlighted_coords is not None
        assert drawn(widget) > 50


def test_widget_zoom_nodes_and_marks(widget):
    widget.spinbox_map_scale.setValue(3.0)
    widget.spinbox_nodes.setValue(25)
    assert widget.map_scale == 3.0 and widget.curve_nodes == 25
    widget.update_marked_coords({100.0, 900.0, 5000.0})  # out of track ignored
    assert len(widget.marked_coords) == 2
    assert drawn(widget) > 0
    menu = widget.set_context_menu()
    checkable = [action for action in menu.actions() if action.isCheckable()]
    assert len(checkable) == 11 and all(action.isChecked() for action in checkable)
    widget.load_config()  # config reloaded after edit
