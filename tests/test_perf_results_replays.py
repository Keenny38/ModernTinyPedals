"""Shared list model sync notifications, preview store lock, positions place tables, replays map & timeline items,
stats canvases"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from neopedal.ui.quick import preview_provider, qml_path
from neopedal.ui.quick.models import DictListModel
from neopedal.ui.quick.preview_provider import PreviewStore


def changes_of(model):
    found: list = []
    model.dataChanged.connect(lambda first, last, roles: found.append((first.row(), last.row(), sorted(roles))))
    return found


def rows(count, value=0, skip=()):
    return [{"key": str(number), "value": value, "other": 0} for number in range(count) if number not in skip]


def test_sync_notifies_runs_of_kept_rows_once():
    model = DictListModel(("key", "value", "other"))
    model.sync(rows(40))
    changed = changes_of(model)
    inserted: list = []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last)))
    wanted = rows(40, value=1)
    wanted[3]["other"] = 5
    wanted.insert(20, {"key": "new", "value": 0, "other": 0})
    assert model.sync(wanted)
    value, other = (Qt.ItemDataRole.UserRole + 2, Qt.ItemDataRole.UserRole + 3)
    assert inserted == [(20, 20)]
    assert changed == [(0, 19, sorted({value, other})), (21, 40, [value])]  # one per run, not one per row
    assert [row["key"] for row in model.rows] == [row["key"] for row in wanted]
    assert model.rows[3]["other"] == 5 and model.rows[40]["value"] == 1
    assert not model.sync([dict(row) for row in wanted])  # nothing changed: nothing told
    assert len(changed) == 2


def test_sync_changes_after_removed_and_moved_rows():
    model = DictListModel(("key", "value", "other"))
    model.sync(rows(10))
    changed = changes_of(model)
    wanted = rows(10, value=2, skip=(4,))
    wanted.insert(0, wanted.pop(5))  # "6" first
    assert model.sync(wanted)
    assert [row["key"] for row in model.rows] == [row["key"] for row in wanted]
    assert all(row["value"] == 2 for row in model.rows)
    assert changed == [(0, 8, [Qt.ItemDataRole.UserRole + 2])]


def test_store_compares_pixels_outside_lock(monkeypatch):
    store = PreviewStore()
    first = QImage(64, 32, QImage.Format.Format_ARGB32_Premultiplied)
    first.fill(QColor("red"))
    url = store.put("a", first)
    held: list = []
    compare = preview_provider.same_picture

    def spy(current, image):
        held.append(store._lock.locked())
        return compare(current, image)

    monkeypatch.setattr(preview_provider, "same_picture", spy)
    again = first.copy()  # same pixels, other data
    assert store.put("a", again) == url
    assert held and not any(held)


def test_store_put_while_compared_keeps_newest(monkeypatch):
    store = PreviewStore()
    red = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    red.fill(QColor("red"))
    blue = red.copy()
    blue.fill(QColor("blue"))
    store.put("a", red)
    compare = preview_provider.same_picture
    calls: list = []

    def racing(current, image):
        if not calls:  # other put stores blue meanwhile
            calls.append(True)
            monkeypatch.setattr(preview_provider, "same_picture", compare)
            store.put("a", blue)
        return compare(current, image)

    monkeypatch.setattr(preview_provider, "same_picture", racing)
    url = store.put("a", red.copy())  # same as old picture, not as the one stored meanwhile
    stored = store.get("a")
    assert stored is not None and stored.pixelColor(0, 0) == QColor("red")
    assert url == store.put("a", red.copy())


def test_places_at_lap_from_python_tables():
    from neopedal.ui.quick.results_backend import RaceResultsBackend

    owner: Any = SimpleNamespace(chart_series={"series": [{"places": [2, 1, 1]}, {"places": [1, 2, 2]}, {"places": [0]}]})
    assert RaceResultsBackend.placesAt(owner, 1) == [1, 2, 0]
    assert RaceResultsBackend.placesAt(owner, 5) == [0, 0, 0] and RaceResultsBackend.placesAt(owner, -1) == [0, 0, 0]


def test_positions_chart_sent_without_place_tables(ui_env):
    from neopedal.ui.quick import results_backend as rb
    from tests.test_race_results import race

    backend = rb.RaceResultsBackend()
    try:
        backend.set_chart(rb.positions_chart(race(), ""))
        assert backend.chart["series"] and all("places" not in series for series in backend.chart["series"])
        assert backend.placesAt(0)[0] == backend.chart_series["series"][0]["places"][0]
    finally:
        backend.release()
        backend.deleteLater()


def test_qml_heavy_parts_gone():
    """Replays map moved by a 30 Hz timer without arrays per car, timeline markers as items, stats canvases
    painted by a thread, setup pictures loaded async at shown size"""
    panel = Path(qml_path("MapPanel.qml")).read_text(encoding="utf-8")
    assert "FrameAnimation" not in panel and "interval: 33" in panel and "return [" not in panel
    incidents = Path(qml_path("IncidentPanel.qml")).read_text(encoding="utf-8")
    assert "Canvas" not in incidents and 'objectName: "incidentMarkers"' in incidents
    for name in ("StatsChart.qml", "StatsActivity.qml"):
        text = Path(qml_path(name)).read_text(encoding="utf-8")
        assert text.count("Canvas {") == text.count("renderStrategy: Canvas.Threaded")
    backdrop = Path(qml_path("SetupBackdrop.qml")).read_text(encoding="utf-8")
    assert "asynchronous: true" in backdrop and "sourceSize.width" in backdrop and "mipmap" not in backdrop
    sessions = Path(qml_path("ResultsSessionList.qml")).read_text(encoding="utf-8")
    # Spinner of the list header (TpCardHeader busy, shared TpSpinner): turns only while the page is shown
    header = Path(qml_path("TpCardHeader.qml")).read_text(encoding="utf-8")
    spinner = Path(qml_path("TpSpinner.qml")).read_text(encoding="utf-8")
    assert "busy: backend.busy" in sessions and "TpSpinner {" in header
    assert "running: visible && pageState.active" in spinner
