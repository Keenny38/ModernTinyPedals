"""Spectate page: drivers read while shown, rows synced in place, search & class filters, sort, spectate by
click, next / previous by place, spectate mode switch, data modules restarted, Qt Quick page"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tinypedal.setting import cfg

CARS = (
    # name, vehicle, class, place, slot
    ("Anna", "Ferrari 499P", "Hypercar", 2, 14),
    ("Ben", "Oreca 07", "LMP2", 3, 7),
    ("Carla", "Porsche 963", "Hypercar", 1, 22),
    ("Dario", "BMW M4 LMGT3", "LMGT3", 4, 3),
)


class Vehicle:
    def __init__(self, cars):
        self.cars = list(cars)
        self.followed = 0

    def total_vehicles(self):
        return len(self.cars)

    def slot_id(self, index=None):
        return self.cars[index][4]

    def driver_name(self, index=None):
        return self.cars[self.followed if index is None else index][0]

    def vehicle_name(self, index=None):
        return self.cars[index][1]

    def class_name(self, index=None):
        return self.cars[index][2]

    def place(self, index=None):
        return self.cars[index][3]

    def in_pits(self, index=None):
        return index == 1

    def in_garage(self, index=None):
        return False

    def is_player(self, index=0):
        return index == 3


class Timing:
    def best_laptime(self, index=None):
        return 200.0 + index

    def last_laptime(self, index=None):
        return 0.0


class Reader:
    def __init__(self, cars=CARS):
        self.vehicle = Vehicle(cars)
        self.timing = Timing()


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def setups(ui_env, monkeypatch):
    """API setups & module reloads done by the page"""
    from tinypedal import realtime_state
    from tinypedal.ui.quick import spectate_backend

    calls = []
    monkeypatch.setattr(realtime_state, "paused", False)  # game data updating
    monkeypatch.setattr(type(spectate_backend.api), "setup", lambda self: calls.append("setup"))
    monkeypatch.setattr(type(spectate_backend.mctrl), "reload", lambda self, name="": calls.append(name))
    cfg.api["enable_player_index_override"] = False
    cfg.api["player_index"] = -1
    yield calls
    cfg.api["enable_player_index_override"] = False
    cfg.api["player_index"] = -1


@pytest.fixture
def backend(setups):
    from tinypedal.ui.quick.spectate_backend import SpectateBackend

    reader = Reader()
    backend = SpectateBackend(None, lambda: reader)
    backend.reader = reader
    backend.set_active(True)
    yield backend
    backend.release()
    backend.deleteLater()
    flush()


def names(backend) -> list[str]:
    return [row["name"] for row in backend.model.rows]


def test_drivers_sorted_by_place_with_details(backend):
    assert names(backend) == ["Carla", "Anna", "Ben", "Dario"]
    ben = backend.model.rows[2]
    assert ben["status"] == "pit" and ben["bestLap"] == "3:21.000" and ben["lastLap"] == ""
    assert backend.model.rows[3]["player"] and backend.driverCount == 4
    backend.setSortByName(True)
    assert names(backend) == ["Anna", "Ben", "Carla", "Dario"]


def test_search_and_class_filters(backend):
    assert [chip["key"] for chip in backend.classes] == ["Hypercar", "LMGT3", "LMP2"]
    assert backend.classes[0]["count"] == 2
    backend.setClassFilter("Hypercar")
    assert names(backend) == ["Carla", "Anna"] and backend.filtered
    backend.setSearch("porsche")
    assert names(backend) == ["Carla"] and backend.shownCount == 1
    backend.clearFilters()
    assert len(names(backend)) == 4 and not backend.filtered
    backend.setSearch("DARIO")
    assert names(backend) == ["Dario"]


def test_rows_synced_in_place(backend):
    inserted, reset = [], []
    backend.model.rowsInserted.connect(lambda *args: inserted.append(args))
    backend.model.modelReset.connect(lambda: reset.append(1))
    backend.poll()  # nothing changed
    backend.reader.vehicle.cars.append(("Emma", "Alpine A424", "Hypercar", 5, 40))
    backend.poll()
    assert len(inserted) == 1 and not reset and names(backend)[-1] == "Emma"


def test_click_driver_turns_spectate_mode_on(backend, setups):
    backend.spectate(7)
    assert cfg.api["enable_player_index_override"] and cfg.api["player_index"] == 7
    assert "setup" in setups and backend.enabled and backend.spectatedSlot == 7
    assert [row["spectated"] for row in backend.model.rows] == [False, False, True, False]


def test_step_by_place_wraps(backend):
    cfg.api["enable_player_index_override"] = True
    backend.refresh()
    backend.spectate(22)  # leader
    backend.step(1)
    assert cfg.api["player_index"] == 14
    backend.step(-1)
    backend.step(-1)
    assert cfg.api["player_index"] == 3  # last place
    backend.stopSpectating()
    assert cfg.api["player_index"] == -1 and not backend.spectated["found"]


def test_spectated_card(backend):
    cfg.api["enable_player_index_override"] = True
    cfg.api["player_index"] = 14
    backend.refresh()
    card = backend.spectated
    assert card["found"] and card["name"] == "Anna" and card["place"] == 2 and card["classColor"]
    cfg.api["player_index"] = 99  # left session
    backend.refresh()
    assert not backend.spectated["found"] and backend.spectated["slot"] == 99


def test_data_modules_restarted_when_followed_driver_changes(backend, setups, monkeypatch):
    from tinypedal import realtime_state

    monkeypatch.setattr(realtime_state, "active", True)
    backend.setEnabled(True)
    assert "module_delta" in setups and "module_fuel" in setups
    setups.clear()
    backend.poll()  # same driver followed
    assert not [call for call in setups if call.startswith("module_")]
    backend.reader.vehicle.followed = 2
    backend.poll()
    assert "module_stint" in setups


def test_refresh_follows_other_changes_without_side_effects(backend, setups):
    setups.clear()
    cfg.api["enable_player_index_override"] = True  # hotkey
    backend.refresh()
    assert backend.enabled and setups == []


def test_not_read_while_hidden_or_paused(backend, monkeypatch):
    from tinypedal import realtime_state

    backend.set_active(False)
    backend.reader.vehicle.cars.pop()
    assert not backend._timer.isActive()
    backend.set_active(True)
    assert len(names(backend)) == 3
    monkeypatch.setattr(realtime_state, "paused", True)
    backend.reader.vehicle.cars.pop()
    backend.poll()
    assert len(names(backend)) == 3  # last drivers kept while data is paused


def test_empty_session(setups):
    from tinypedal.ui.quick.spectate_backend import SpectateBackend

    backend = SpectateBackend(None, lambda: Reader(()))
    backend.set_active(True)
    assert backend.driverCount == 0 and backend.classes == [] and not backend.spectated["found"]
    backend.step(1)  # nothing to spectate
    assert cfg.api["player_index"] == -1
    backend.release()


def item_texts(view) -> set[str]:
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def deleted_with_window(setups, unload: bool) -> list[str]:
    """QML warnings while a shown spectate page is deleted with its window (app quit)"""
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.app import AppWindow
    from tinypedal.ui.spectate_view import SpectateList

    reader = Reader()
    window = QWidget()
    page = SpectateList(window)
    page.backend._reader = lambda: reader
    window.resize(900, 600)
    window.show()
    page.show()
    for _ in range(10):
        QCoreApplication.processEvents()
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        if unload:
            AppWindow.unload_quick_views(window)  # type: ignore[arg-type]
        window.hide()
        window.deleteLater()
        flush()
    finally:
        qInstallMessageHandler(previous)
    return [text for text in messages if "Cannot read property" in text]


def test_rail_page_deleted_with_window(setups):
    """Rail pages get no close event at quit: backend deleted first, QML read a null backend"""
    assert deleted_with_window(setups, unload=False)  # issue shown without unloading
    assert not deleted_with_window(setups, unload=True)


def test_qml_page(setups):
    from tinypedal.ui.spectate_view import SpectateList

    reader = Reader()
    page = SpectateList(None)
    page.backend._reader = lambda: reader
    page.resize(900, 600)
    assert page.view is None
    page.show()
    try:
        assert page.view is not None and not page.view.errors(), [error.toString() for error in page.view.errors()]
        assert page.backend._timer.isActive()
        for _ in range(20):
            QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert {"Spectate", "Carla", "Porsche 963", "Turn On Spectate Mode"} <= texts
        page.hide()
        assert not page.backend._timer.isActive()  # nothing read while hidden
    finally:
        page.close()
        page.deleteLater()
        flush()
