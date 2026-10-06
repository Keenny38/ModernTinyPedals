"""Lap viewer lap list (audit J, B2): rows changed in place, collapsed sessions out of model, Shift+click range,
search text kept, lap infos index, other circuit hint, no match hint"""

import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QMetaObject, qInstallMessageHandler
from PySide6.QtTest import QTest

from tests.test_lap_viewer import wait_loaded
from tinypedal.module import module_recorder
from tinypedal.setting import cfg

TRACK = "Atlanta - Hyper"
BASE = time.mktime((2026, 10, 3, 14, 0, 0, 0, 0, -1))


def save(number: int, lap_time: float, timestamp: float, start: float, folder: str = "", combo: str = TRACK,
         track: str = "Atlanta", vehicle: str = "Porsche 963") -> str:
    folder = folder or cfg.path.telemetry.rstrip("/")
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    info = {"kind": "lap", "session": "Practice", "vehicle": vehicle, "session_start": start, "track": track,
            "combo": combo, "track_length": 490.0}
    module_recorder.save_lap(f"{folder}/", combo, number, lap_time, rows, max_saved_laps=99, info=info,
                             timestamp=timestamp)
    return os.path.join(f"{folder}/{combo}", module_recorder.lap_filename(number, lap_time, True, timestamp))


@pytest.fixture
def sessions(ui_env):
    """3 practice sessions of 3 laps, newest first: fastest lap in newest session"""
    groups = []
    for session, start in enumerate((BASE + 7200, BASE + 3600, BASE)):
        groups.append([save(number, 60.0 + session + number / 10, start + number * 70, start)
                       for number in (1, 2, 3)])
    return groups


def open_page(parent):
    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    page = LapViewerBackend(parent, cfg.path.telemetry)
    page.refresh()
    wait_loaded(page)
    return page


@pytest.fixture
def page(sessions):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    backend = open_page(parent)
    yield backend
    backend.release()
    parent.deleteLater()


def headers(page) -> list[str]:
    return [row["session"] for row in page.lap_model.all_rows if row["kind"] == "session"]


def test_sync_batches_rows_and_keeps_kept_ones():
    from tinypedal.ui.quick.models import DictListModel, FoldedListModel

    model = DictListModel(("key", "value"))
    model.sync([{"key": key, "value": 0} for key in "abcdef"])
    kept = model.rows[2]
    inserted, removed = [], []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last)))
    model.rowsRemoved.connect(lambda parent, first, last: removed.append((first, last)))
    model.sync([{"key": key, "value": 1 if key == "c" else 0} for key in "axyczf"])
    assert [row["key"] for row in model.rows] == list("axyczf")
    assert removed == [(3, 4), (1, 1)] and inserted == [(1, 2), (4, 4)]  # runs together, from last removed
    assert model.rows[3] is kept and kept["value"] == 1  # changed in place
    model.sync([{"key": key, "value": 0} for key in "fa"])  # moved
    assert [row["key"] for row in model.rows] == ["f", "a"]
    folded = FoldedListModel(("key", "value"), "key")
    folded.set_rows([{"key": key, "value": 0} for key in "abc"], lambda row: row["key"] != "b")
    assert [row["key"] for row in folded.rows] == ["a", "c"]
    folded.update_rows(lambda row: {"value": 2})
    assert [row["value"] for row in folded.all_rows] == [2, 2, 2]  # hidden row too
    folded.set_rows(folded.all_rows, lambda row: True)
    assert [(row["key"], row["value"]) for row in folded.rows] == [("a", 2), ("b", 2), ("c", 2)]


def test_list_changes_keep_rows_in_place(page, sessions):
    """J16: list never reset (a reset scrolled list back to top): keep, search, quick selection, new lap"""
    resets = []
    page.lap_model.modelAboutToBeReset.connect(lambda: resets.append(True))
    fills = []
    fill_list = page.fill_list

    def filling():
        fills.append(True)
        fill_list()

    page.fill_list = filling
    path = sessions[0][1]
    page.keepLap(path, True)
    assert not fills  # marks only: row changed in place
    assert "kept" in next(row for row in page.lap_model.rows if row["path"] == path)["info"]
    page.keepChecked(True)
    page.sessionAction(headers(page)[0], "unkeep")
    assert not fills and "kept" not in next(row for row in page.lap_rows() if row["path"] == path)["info"]
    page.setFilter("kept")  # marks are searched: list built again while searching
    assert path not in {row["path"] for row in page.lap_rows()}
    page.keepLap(path, True)
    assert path in {row["path"] for row in page.lap_rows()}
    page.setFilter("")
    page.setHideUnclean(True)
    page.setHideUnclean(False)
    page.compareBest(2)
    wait_loaded(page)
    new = save(4, 59.0, BASE + 7200 + 4 * 70, BASE + 7200)  # lap recorded while page is open
    page.auto_refresh()
    wait_loaded(page)
    assert new in {row["path"] for row in page.lap_model.rows}
    assert fills and not resets


def test_collapsed_sessions_out_of_model(page, sessions):
    """J55: lap rows of collapsed sessions are not in list model (no delegate), still known for charts"""
    model = page.lap_model
    newest, middle, oldest = headers(page)
    assert page.expanded == [newest]
    assert [row["kind"] for row in model.rows] == ["session", "lap", "lap", "lap", "session", "session"]
    assert [row["open"] for row in model.rows if row["kind"] == "session"] == [True, False, False]
    assert len(page.lap_rows()) == 9
    inserted, removed = [], []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last)))
    model.rowsRemoved.connect(lambda parent, first, last: removed.append((first, last)))
    page.toggleSession(middle)
    assert inserted == [(5, 7)] and model.rows[4]["open"]  # inserted together, under its header
    page.toggleSession(middle)
    assert removed == [(5, 7)] and not model.rows[4]["open"]
    # Checked lap of a session collapsed afterwards: still shown in charts, its row kept up to date
    page.toggleSession(oldest)
    lap = sessions[2][0]
    page.setLapChecked(lap, True)
    wait_loaded(page)
    page.toggleSession(oldest)
    assert lap not in {row["path"] for row in model.rows}
    page.toggleLap(sessions[0][2])
    wait_loaded(page)
    assert lap in page.ordered_checked() and lap in {plotted.key for plotted in page.data.laps}
    page.clearSelection()
    wait_loaded(page)
    page.toggleSession(oldest)
    assert not next(row for row in model.rows if row["path"] == lap)["checked"]


def test_shift_range_skips_collapsed_sessions(page, sessions):
    """J20: Shift+click range checks laps seen only, unchecking a range never unchecks reference lap"""
    page.toggleSession(headers(page)[2])  # oldest session expanded, middle one collapsed
    reference = page.reference_key
    first, last = sessions[0][0], sessions[2][1]
    assert reference == first
    page.selectRange(first, last, True)
    wait_loaded(page)
    assert not set(sessions[1]) & page.checked  # collapsed session between left as it was
    assert {*sessions[0], *sessions[2][:2]} <= page.checked
    page.selectRange(first, last, False)
    wait_loaded(page)
    assert page.checked == {reference} and page.reference_key == reference


def test_lap_infos_index(sessions, monkeypatch):
    """J60: lap infos read once, then from track index while lap files stay the same (damaged index ignored)"""
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import lap_backend

    parent = QWidget()
    pages = []
    calls: list[str] = []
    reading = lap_backend.read_lap_info

    def counted(path: str) -> dict:
        calls.append(path)
        return reading(path)

    try:
        pages.append(open_page(parent))
        index = os.path.join(cfg.path.telemetry, ".lap_cache", "info", f"{TRACK}.json")
        assert os.path.isfile(index)
        infos = [entry.info for entry in pages[0].entries]
        monkeypatch.setattr(lap_backend, "read_lap_info", counted)
        pages.append(open_page(parent))
        assert not calls and [entry.info for entry in pages[1].entries] == infos
        changed = save(2, 60.2, BASE + 7200 + 140, BASE + 7200, vehicle="Cadillac")  # same file written again
        os.utime(changed, (time.time() + 10, time.time() + 10))
        pages.append(open_page(parent))
        assert [os.path.normpath(path) for path in calls] == [os.path.normpath(changed)]
        assert any(entry.info.get("vehicle") == "Cadillac" for entry in pages[2].entries)
        with open(index, "w", encoding="utf-8") as file:
            file.write("{damaged")
        calls.clear()
        pages.append(open_page(parent))
        assert len(calls) == 9 and len(pages[3].entries) == 9
        with open(index, encoding="utf-8") as file:
            assert file.read().startswith("{\"")  # saved again
    finally:
        for page in pages:
            page.release()
        parent.deleteLater()


def test_other_circuit_lap_hint(page, sessions, tmp_path):
    """J64: added lap of another circuit than reference lap dimmed with a lasting hint (unchecked, not compared)"""
    other = save(1, 50.0, BASE, BASE, folder=str(tmp_path / "other"), combo="Other - Hyper", track="Other")
    page.add_external([other])
    wait_loaded(page)
    rows = {row["path"]: row for row in page.lap_rows()}
    other = os.path.normpath(other)
    assert rows[other]["hint"] == "Another circuit than reference lap: not compared"
    assert other not in page.checked  # unchecked by reference lap circuit
    assert not any(row["hint"] for path, row in rows.items() if path != other)


def test_no_match_hint(page, sessions):
    """J65: search or clean only leaving no lap is told (checked laps stay listed)"""
    assert not page.noMatch
    page.setFilter("nothing like this")
    assert page.noMatch and {row["path"] for row in page.lap_rows()} == page.checked
    page.setFilter("")
    assert not page.noMatch
    for entry in page.entries:
        entry.info["kind"] = "out"
    page.setHideUnclean(True)
    assert page.noMatch and page.filterText == ""
    page.setHideUnclean(False)
    assert not page.noMatch


def test_lap_list_qml(page, sessions):
    """Delegates of shown rows only (J55), search text kept as typed (J10), no match hint & action (J65)"""
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import create_quick_view

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    parent = QWidget()
    try:
        view = create_quick_view(parent, "LapViewer.qml", {"backend": page})
        parent.resize(1300, 800)
        view.resize(1300, 800)
        parent.show()
        settle()
        items = everything(view.rootObject())
        listing = next(item for item in items if item.property("model") is page.lap_model)
        delegates = [item for item in listing.property("contentItem").childItems() if item.property("kind") is not None]
        assert len(delegates) == page.lap_model.rowCount() == 6  # collapsed sessions: header only
        search = next(item for item in items if str(item.property("placeholderText") or "").startswith("Search laps"))
        view.setFocus()
        QMetaObject.invokeMethod(search, "forceActiveFocus")
        QTest.keyClicks(view, "porsche ")
        settle(0.6)  # search applied after a pause in typing
        assert page.filterText == "porsche" and search.property("text") == "porsche "  # next word not glued
        search.setProperty("text", "nothing like this")
        page.setFilter("nothing like this")
        settle()
        hint = next(item for item in everything(listing) if item.property("actionText") is not None)
        assert hint.property("visible") and hint.property("title") == "No lap matches the search"
        QMetaObject.invokeMethod(hint, "action")
        settle()
        assert page.filterText == "" and search.property("text") == "" and not hint.property("visible")
    finally:
        qInstallMessageHandler(previous)
        parent.deleteLater()
    assert not [text for text in messages if ".qml" in text], messages


def settle(seconds: float = 0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def everything(root) -> list:
    found, stack = [], [root]
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found
