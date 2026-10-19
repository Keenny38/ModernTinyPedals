"""Race calculator Python-QML bridge: history & team rows synced in place (no model reset), signals only on
change, QML items (tiles, tables, timeline, history & team rows) kept when values change, no QML warning"""

import pytest
from PySide6.QtCore import QCoreApplication, qInstallMessageHandler
from shiboken6 import getCppPointer

from neopedal.module_info import ConsumptionDataSet
from neopedal.process.team_usage import StintUsage
from tests.test_race_calculator import find_item, host, page, set_race  # noqa: F401 (host, page: fixtures)

STINTS = [StintUsage("A", 1, 1, 6, 4, 0.03, 0.04, 0.5), StintUsage("B", 2, 7, 12, 5, 0.04, 0.05, 0.6)]


def lap(number: int, valid: int = 1) -> ConsumptionDataSet:
    return ConsumptionDataSet(number, valid, 90.0 + number / 10, 3.0, 2.5, 1.0, 0.5, 0.4, 100.0)


def calls(signal) -> list:
    found: list = []
    signal.connect(lambda *args: found.append(args))
    return found


def role(model, name: str) -> int:
    return next(number for number, value in model.roleNames().items() if bytes(value.data()).decode() == name)


class Spy:
    """Notifications of a list model"""

    def __init__(self, model):
        self.resets = calls(model.modelReset)
        self.inserted = calls(model.rowsInserted)
        self.removed = calls(model.rowsRemoved)
        self.changed = calls(model.dataChanged)

    def roles(self) -> list[list[int]]:
        return [list(args[2]) for args in self.changed]


def test_history_new_lap_inserted_in_place(page, monkeypatch):  # noqa: F811
    backend = page.backend
    laps = [lap(3), lap(2), lap(1)]
    backend.refresh_history(laps)
    model = backend.history_model
    assert [row["cells"][0] for row in model.rows] == ["3", "2", "1"]
    spy, views = Spy(model), calls(backend.historyViewChanged)
    formatted: list = []
    format_row = backend.format_history_row

    def counted(*args):
        formatted.append(args)
        return format_row(*args)

    monkeypatch.setattr(backend, "format_history_row", counted)
    backend.refresh_history([lap(4), *laps])
    assert [row["cells"][0] for row in model.rows] == ["4", "3", "2", "1"]
    assert not spy.resets and len(spy.inserted) == 1 and not spy.changed  # one row inserted, others kept
    assert not views and len(formatted) == 1  # only the new lap formatted
    assert backend.history["rows"][0]["cells"][0] == "4"  # Python view follows


def test_history_selection_changes_one_role(page, monkeypatch):  # noqa: F811
    backend = page.backend
    backend.refresh_history([lap(3), lap(2), lap(1)])
    model = backend.history_model
    serials = [row["serial"] for row in model.rows]
    spy, selections, views = Spy(model), calls(backend.historySelectionChanged), calls(backend.historyViewChanged)
    monkeypatch.setattr(backend, "history_rows", lambda: pytest.fail("rows built again to select"))
    backend.selectLap(serials[0], 0)
    assert spy.roles() == [[role(model, "selected")]] and len(selections) == 1
    backend.selectLap(serials[0], 0)  # same selection: nothing notified
    assert len(spy.changed) == 1 and len(selections) == 1
    backend.selectLap(serials[2], 2)  # range: rows 1 & 2 selected
    assert len(spy.changed) == 2 and backend.historySelection == sorted(serials)  # rows 1 & 2 in one notice
    assert [row["selected"] for row in model.rows] == [True, True, True]
    backend.selectAllLaps()  # all selected already
    assert len(selections) == 2
    backend.clearLapSelection()
    assert not any(row["selected"] for row in model.rows) and len(selections) == 3
    assert not spy.resets and not spy.inserted and not views


def test_history_column_toggled_rows_untouched(page):  # noqa: F811
    backend = page.backend
    backend.refresh_history([lap(2), lap(1)])
    spy, views = Spy(backend.history_model), calls(backend.historyViewChanged)
    backend.toggleHistoryColumn("show_column_tyre_wear")
    assert len(views) == 1 and not spy.changed and not spy.resets
    column = next(column for column in backend.historyView["columns"] if column["key"] == "tyre")
    assert column["visible"] is False
    backend.sortHistory(0)  # lap number ascending: rows moved, not formatted again
    assert [row["cells"][0] for row in backend.history_model.rows] == ["1", "2"] and len(views) == 2


def test_team_refresh_synced_in_place(page):  # noqa: F811
    backend = page.backend
    backend.show_team_stints(STINTS, 100.0)
    model = backend.team_model
    assert [row["key"] for row in model.rows] == ["A|1", "B|2"] and backend.teamInfo["count"] == 2
    spy = Spy(model)
    infos, statuses = calls(backend.teamInfoChanged), calls(backend.teamStatusChanged)
    selections = calls(backend.teamSelectionChanged)
    backend.show_team_stints(STINTS, 100.0)  # same answer at next refresh: nothing shown again
    assert not spy.changed and not spy.resets and not spy.inserted and not infos and not selections
    backend.team_request_failed()  # status only
    assert len(statuses) == 1 and not infos and not spy.changed and backend.teamStatus
    backend.selectStint(1, 0)
    assert spy.roles() == [[role(model, "selected")]] and len(selections) == 1
    backend.selectStint(1, 0)
    assert len(spy.changed) == 1 and len(selections) == 1
    backend.show_team_stints([*STINTS, StintUsage("A", 3, 13, 15, 2, 0.03, 0.04, 0.5)], 100.0)
    assert len(spy.inserted) == 1 and not spy.resets and len(infos) == 1  # new stint, drivers totals
    assert backend.teamSelection == [1] and model.rows[1]["selected"]  # selection kept


def pointers(items) -> set:
    return {getCppPointer(item)[0] for item in items}


def find_items(root, name: str) -> list:
    """Items of the QML page with a property of that name"""
    found, stack = [], [root]
    while stack:
        item = stack.pop()
        if item.property(name) is not None:
            found.append(item)
        stack.extend(item.childItems())
    return found


def test_qml_items_kept_when_values_change(page):  # noqa: F811
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        page.show()
        view = page.ensure_view()
        view.resize(1400, 900)
        backend = page.backend
        set_race(backend, laps=40, wear=4.0, minimum=20)
        backend.refresh_history([lap(3), lap(2), lap(1)])
        for _ in range(3):
            QCoreApplication.processEvents()
        root = view.rootObject()
        timeline = find_item(root, "barWidth")
        tiles = find_items(root, "figure")  # key figure tiles (TpStatTile of the page)
        tables = find_items(root, "naturalWidths")
        table_rows = pointers(row for table in tables for row in find_items(table, "cells"))
        blocks = pointers(find_items(timeline, "stint"))
        laps = pointers(find_items(root, "serial"))
        assert len(tiles) == 6 and table_rows and blocks and len(laps) == 3
        backend.setInput("input_lap_time", 91.0)  # same stops, other times
        backend.refresh_history([lap(4), lap(3), lap(2), lap(1)])
        for _ in range(3):
            QCoreApplication.processEvents()
        assert pointers(find_items(root, "figure")) == pointers(tiles)
        assert pointers(row for table in tables for row in find_items(table, "cells")) == table_rows
        assert pointers(find_items(timeline, "stint")) == blocks
        assert laps < pointers(find_items(root, "serial"))  # new lap row added, others kept
        backend.setTab(1)  # tyre tab built (status chips, stock menu)
        QCoreApplication.processEvents()
        # Team tab: rows kept at each refresh
        backend.setTab(2)
        backend.show_team_stints(STINTS, 100.0)
        for _ in range(3):
            QCoreApplication.processEvents()
        stints = pointers(item for item in find_items(root, "usable"))
        assert len(stints) == 2
        backend.show_team_stints(STINTS, 100.0)
        backend.team_request_failed()
        QCoreApplication.processEvents()
        assert pointers(find_items(root, "usable")) == stints
        backend.setTab(0)
        assert not view.errors()
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages
