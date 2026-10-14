"""Lap viewer memory: page parts see their page weakly (no reference cycle), closing the page frees its laps at once,
map lines & derived data packed in arrays (same values), increasing samples cache forgotten"""

import gc
import math
import pickle
import types
import weakref
from array import array

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_imported_reference import track  # noqa: F401


def test_parts_see_page_weakly(track):  # noqa: F811
    backend, _ = track
    for part in backend.parts():
        assert isinstance(part._page, weakref.ProxyType)
        assert backend not in gc.get_referents(part)  # page reached through a proxy only


def test_part_never_keeps_page_alive(ui_env):
    from neopedal.ui.quick.lap_conditions import LapConditions

    class Page(types.SimpleNamespace):  # weak referenceable stand-in
        pass

    page = Page(data=types.SimpleNamespace(laps=[], reference=None), all_entries=list, short_label=str,
                optionsChanged=types.SimpleNamespace(connect=lambda slot: None))
    part = LapConditions(page, {})  # type: ignore[arg-type]
    page.part = part  # page keeps its part, like LapViewerBackend
    alive = weakref.ref(page)
    gc.disable()  # freed by reference counting, without a collection
    try:
        del page
        assert alive() is None
    finally:
        gc.enable()
    with pytest.raises(ReferenceError):
        getattr(part._page, "data")  # noqa: B009  (proxy of a freed page)


def test_closed_page_frees_laps_at_once(track):  # noqa: F811
    from neopedal.userfile import telemetry_lap

    backend, _ = track
    wait_loaded(backend)
    assert backend.data.laps and backend._lap_cache and backend._turned  # lines turned like map: kept per lap
    telemetry_lap.increasing_samples(backend.data.laps[0].data.distance)
    backend.release()
    assert backend._lap_cache == {} and backend.data.laps == [] and backend.data.reference is None
    assert backend._g_laps == {} and backend._turned == {} and backend._normals == {} and backend._grids == {}
    assert len(telemetry_lap._increasing) == 0


def test_forget_increasing():
    from neopedal.userfile import telemetry_lap

    distances = array("d", [0.0, 1.0, 0.5, 2.0])
    indexes, kept = telemetry_lap.increasing_samples(distances)
    assert indexes is not None and list(indexes) == [0, 1, 3] and list(kept) == [0.0, 1.0, 2.0]
    assert any(entry[0] is distances for entry in telemetry_lap._increasing.values())
    telemetry_lap.forget_increasing()
    assert not any(entry[0] is distances for entry in telemetry_lap._increasing.values())
    assert list(telemetry_lap.increasing_samples(distances)[0] or ()) == [0, 1, 3]  # found again


def packed_lap():
    from neopedal.userfile.telemetry_lap import LapData

    count = 400
    distance = array("d", [index * 10.0 for index in range(count)])
    xs = array("f", [6000.0 + 3000.0 * math.cos(index / count * math.tau) for index in range(count)])
    ys = array("f", [-4000.0 + 2000.0 * math.sin(index / count * math.tau) for index in range(count)])
    return LapData("a", {"distance": distance, "pos_x": xs, "pos_y": ys})


def test_map_line_packed_same_values():
    from neopedal.ui.quick import lap_map

    lap = packed_lap()
    line = lap_map.map_line(lap)
    assert line is not None
    assert (line.distances.typecode, line.xs.typecode, line.ys.typecode) == ("d", "f", "f")  # type: ignore[attr-defined]
    assert list(line.distances) == list(lap.distance)
    assert list(line.xs) == list(lap.columns["pos_x"]) and list(line.ys) == list(lap.columns["pos_y"])
    assert pickle.loads(pickle.dumps(line)) == line  # worker process results


def test_rotate_line_and_normals_packed():
    from neopedal.ui.quick import lap_map
    from neopedal.ui.quick.lines import normals

    line = lap_map.map_line(packed_lap())
    assert line is not None
    angle = 0.7
    turned = lap_map.rotate_line(line, angle)
    assert turned.distances is line.distances  # shared (map circuit told apart by it)
    cos, sin = math.cos(angle), math.sin(angle)
    for x, y, tx, ty in zip(line.xs, line.ys, turned.xs, turned.ys):  # single precision: under 1 mm off
        assert abs(tx - (x * cos - y * sin)) < 1e-3 and abs(ty - (x * sin + y * cos)) < 1e-3
    packed = lap_map.PackedNormals(turned.xs, turned.ys)
    exact = normals(turned.xs, turned.ys)
    assert len(packed) == len(exact)
    assert packed[5] == pytest.approx(exact[5], abs=1e-6) and packed[-1] == pytest.approx(exact[-1], abs=1e-6)
    assert all(pair == pytest.approx(other, abs=1e-6) for pair, other in zip(packed, exact))
    assert [value for pair in packed[2:4] for value in pair] == pytest.approx(
        [value for pair in exact[2:4] for value in pair], abs=1e-6)


def test_line_grid_packed_cells():
    from neopedal.ui.quick import lap_map

    line = lap_map.map_line(packed_lap())
    assert line is not None
    grid = lap_map.LineGrid(line)
    assert all(isinstance(indexes, array) for indexes in grid.cells.values())
    assert sum(len(indexes) for indexes in grid.cells.values()) == len(line.xs)
    assert grid.nearest(line.xs[17] + 0.5, line.ys[17], 5.0) == 17
