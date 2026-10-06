"""Performance: modules skip ticks without new game data, parallel module stop, cached vehicle wrappers,
track map place numbers laid out once"""

import ctypes
import logging
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from tests.test_rf2_connector import MemoryDataSet, Zone
from tests.test_widget_track_map import track  # noqa: F401  (fixture)
from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.module_info import minfo


def wait_until(check, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    return False


def fake_reader(game: dict) -> SimpleNamespace:
    """Reader of data stamp values & vehicle count"""
    return SimpleNamespace(
        timing=SimpleNamespace(elapsed=lambda index=None: game["tele"]),
        session=SimpleNamespace(elapsed=lambda: game["scor"], in_race=lambda: False),
        vehicle=SimpleNamespace(player_index=lambda: game["player"], total_vehicles=lambda: game["total"]),
    )


def recording_generator(sends: list):
    def generator():
        while True:
            sends.append((yield None))

    gen = generator()
    next(gen)
    return gen


# Data stamp gate
def test_force_module_calculates_once_per_new_sample(ui_env, monkeypatch):
    """G force average (EMA) advances per telemetry sample, not per module tick"""
    from tinypedal.module import module_force
    from tinypedal.setting import cfg

    sends: list = []
    game = {"tele": 1.0, "scor": 10.0, "player": 0, "total": 1}
    monkeypatch.setattr(module_force, "calc_force", lambda **kwargs: recording_generator(sends))
    monkeypatch.setattr(api, "read", fake_reader(game))
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(realtime_state, "resets", 0)
    module = module_force.Realtime(cfg, "module_force")
    module.active_interval = module.idle_interval = 0.002
    module.start()
    try:
        assert wait_until(lambda: len(sends) == 1)
        time.sleep(0.1)  # many ticks, same data
        assert len(sends) == 1
        game["tele"] = 1.01  # new telemetry sample
        assert wait_until(lambda: len(sends) == 2)
        game["scor"] = 10.2  # new scoring
        assert wait_until(lambda: len(sends) == 3)
        game["player"] = 4  # other player (spectate), same time
        assert wait_until(lambda: len(sends) == 4)
        realtime_state.resets = 1  # vehicle reset
        assert wait_until(lambda: len(sends) == 5)
        assert sends[-1] == 1
        time.sleep(0.05)
        assert len(sends) == 5
    finally:
        module.stop()
        assert module.wait_closed(5)


def test_force_module_never_skips_first_tick_after_idle(ui_env, monkeypatch):
    from tinypedal.module import module_force
    from tinypedal.setting import cfg

    sends: list = []
    game = {"tele": 1.0, "scor": 10.0, "player": 0, "total": 1}
    monkeypatch.setattr(module_force, "calc_force", lambda **kwargs: recording_generator(sends))
    monkeypatch.setattr(api, "read", fake_reader(game))
    monkeypatch.setattr(realtime_state, "active", True)
    module = module_force.Realtime(cfg, "module_force")
    module.active_interval = module.idle_interval = 0.002
    module.start()
    try:
        assert wait_until(lambda: len(sends) == 1)
        realtime_state.active = False
        time.sleep(0.05)
        realtime_state.active = True  # driving again, data unchanged
        assert wait_until(lambda: len(sends) == 2)
    finally:
        module.stop()
        assert module.wait_closed(5)


def test_vehicles_data_version_only_changes_with_new_data(ui_env, monkeypatch):
    """Overlays redraw on dataSetVersion change: no bump while game data idle"""
    from tinypedal.module import module_vehicles
    from tinypedal.setting import cfg

    output = minfo.vehicles
    monkeypatch.setattr(output, "dataSetVersion", output.dataSetVersion)
    for name in ("totalVehicles", "finishTimeOffset", "finishAsLap", "finishLapOffset", "finishLapOffsetLeader"):
        monkeypatch.setattr(output, name, getattr(output, name))

    def fake_update(output, *args, **kwargs):
        output.dataSetVersion += 1

    game = {"tele": 1.0, "scor": 10.0, "player": 0, "total": 3}
    monkeypatch.setattr(module_vehicles, "update_vehicle_data", fake_update)
    monkeypatch.setattr(module_vehicles, "update_qualify_position", lambda output: None)
    monkeypatch.setattr(api, "read", fake_reader(game))
    monkeypatch.setattr(realtime_state, "paused", False)
    module = module_vehicles.Realtime(cfg, "module_vehicles")
    module.active_interval = module.idle_interval = 0.002
    module.start()
    try:
        assert wait_until(lambda: output.dataSetVersion == 0)  # -1 on start, first update
        time.sleep(0.1)
        assert output.dataSetVersion == 0
        game["tele"] = 1.01
        assert wait_until(lambda: output.dataSetVersion == 1)
        game["total"] = 4  # car joined
        assert wait_until(lambda: output.dataSetVersion == 2)
        time.sleep(0.05)
        assert output.dataSetVersion == 2
    finally:
        module.stop()
        assert module.wait_closed(5)


# Module stop
def test_wait_all_stopped_shares_deadline(caplog):
    from tinypedal.thread_guard import wait_all_stopped

    waits = []

    def stuck_wait(seconds):
        waits.append(seconds)
        time.sleep(seconds)
        return False

    with caplog.at_level(logging.ERROR):
        assert not wait_all_stopped([("a", lambda: False, stuck_wait), ("b", lambda: False, stuck_wait)], 0.1)
    assert sum(waits) <= 0.15  # second waits only what is left, not a full timeout
    assert sum("not stopped" in record.message for record in caplog.records) == 2


def test_wait_all_stopped_waits_events_and_polls():
    from tinypedal.thread_guard import wait_all_stopped

    done = threading.Event()
    state = {"polled": False}
    threading.Timer(0.05, done.set).start()
    threading.Timer(0.05, lambda: state.update(polled=True)).start()
    assert wait_all_stopped([("event", done.is_set, done.wait), ("poll", lambda: state["polled"], None)], 5)


def test_close_all_signals_every_module_before_waiting(monkeypatch):
    from tinypedal.const_file import ConfigType
    from tinypedal.module_control import ModuleControl

    calls: list[tuple] = []

    class Fake:
        def __init__(self, name):
            self.name = name
            self.closed = False
            self.done = threading.Event()

        def stop(self, discard=False):
            calls.append(("stop", self.name, discard))
            threading.Timer(0.05, self.finish).start()

        def finish(self):
            self.closed = True
            self.done.set()

        def wait_closed(self, timeout):
            calls.append(("wait", self.name))
            return self.done.wait(timeout)

    control = ModuleControl(SimpleNamespace(__all__=["module_a", "module_b"]), ConfigType.MODULE)
    fakes = {"module_a": Fake("module_a"), "module_b": Fake("module_b")}
    control._active_modules.update(fakes)
    control.close(discard=True)
    assert not control.active_modules
    assert all(fake.closed for fake in fakes.values())
    assert calls[:2] == [("stop", "module_a", True), ("stop", "module_b", True)]
    assert {call[0] for call in calls[2:]} == {"wait"}


def test_data_module_wait_closed(ui_env):
    from tinypedal.module._base import DataModule
    from tinypedal.setting import cfg

    class Looping(DataModule):
        def update_data(self):
            self._event.wait()

    module = Looping(cfg, "module_force")
    assert module.wait_closed(0)  # never started
    module.start()
    assert not module.wait_closed(0)
    module.stop()
    assert module.wait_closed(5) and module.closed


# Connector vehicle wrappers
def lmu_game():
    from pyLMUSharedMemory import lmu_data
    from tinypedal.adapter.lmu_connector import LMUInfo

    info = LMUInfo()
    zone = Zone(lmu_data.LMUObjectOut())
    info._sync.dataset.shmm = zone  # type: ignore[assignment]
    info._shmm = zone  # type: ignore[assignment]
    data = zone.data
    data.scoring.scoringInfo.mNumVehicles = data.telemetry.activeVehicles = 3
    for index, slot_id in enumerate((3, 5, 7)):
        data.scoring.vehScoringInfo[index].mID = slot_id
    for index, slot_id in enumerate((5, 7, 3)):
        data.telemetry.telemInfo[index].mID = slot_id
    return info, zone


def lmu_tick(info):
    sync = info._sync
    sync._SyncData__update_tele_indexes(sync.dataset.shmm.data.telemetry, sync._tele_indexes)
    sync._SyncData__update_tele_map()


def test_lmu_vehicle_wrappers_cached_and_matched():
    info, zone = lmu_game()
    lmu_tick(info)
    for index in range(3):
        assert info.lmuTeleVeh(index).mID == info.lmuScorVeh(index).mID
    assert info.lmuTeleVeh(0) is info.lmuTeleVeh(0)  # wrapper created once
    assert info.lmuScorVeh(1) is info.lmuScorVeh(1)
    # Wrappers read data copy updated in place
    zone.data.telemetry.telemInfo[2].mElapsedTime = 12.5
    assert info.lmuTeleVeh(0).mElapsedTime == 12.5
    # Cars reordered: matched again on next update tick
    for index, slot_id in enumerate((3, 5, 7)):
        zone.data.telemetry.telemInfo[index].mID = slot_id
    lmu_tick(info)
    assert [info.lmuTeleVeh(index).mID for index in range(3)] == [3, 5, 7]


def test_lmu_vehicle_wrappers_follow_data_structure():
    from pyLMUSharedMemory import lmu_data

    info, zone = lmu_game()
    lmu_tick(info)
    sync = info._sync
    from tinypedal.adapter.lmu_connector import EMPTY_TELE

    # Index beyond vehicles in session: matched on demand, slot without telemetry zeroed
    assert sync.sync_tele_index(5) == -1 and info.lmuTeleVeh(5) is EMPTY_TELE
    zone.data.scoring.vehScoringInfo[5].mID = 7  # slot with telemetry
    expected = zone.data.telemetry.telemInfo[sync.sync_tele_index(5)]
    assert ctypes.addressof(info.lmuTeleVeh(5)) == ctypes.addressof(expected)
    # Data structure replaced (close, replay): map of old structure ignored, wrappers of new structure
    old = zone.data
    zone.data = lmu_data.LMUObjectOut.from_buffer_copy(old)
    tele = info.lmuTeleVeh(0)
    base = ctypes.addressof(zone.data)
    assert base <= ctypes.addressof(tele) < base + ctypes.sizeof(zone.data)
    assert tele.mID == 3


def test_lmu_stop_releases_wrappers():
    from tinypedal.adapter.lmu_connector import NO_ROWS, NO_TELE_MAP

    info, _ = lmu_game()
    lmu_tick(info)
    info.lmuTeleVeh(0)
    sync = info._sync
    sync._updating = True  # started without thread
    sync.stop()
    assert sync._rows is NO_ROWS and sync.tele_map is NO_TELE_MAP  # mmap can close


def rf2_game():
    from tinypedal.adapter.rf2_connector import RF2Info

    info = RF2Info()
    dataset = MemoryDataSet()
    info._sync.dataset = dataset
    info.setReplay(None)
    scor, tele = dataset.scor.data, dataset.tele.data
    scor.mScoringInfo.mNumVehicles = tele.mNumVehicles = 3
    for index, slot_id in enumerate((3, 5, 7)):
        scor.mVehicles[index].mID = slot_id
    for index, slot_id in enumerate((5, 7, 3)):
        tele.mVehicles[index].mID = slot_id
    return info, dataset


def rf2_tick(info):
    sync = info._sync
    tele = sync.dataset.tele.data
    sync._SyncData__update_tele_indexes(tele.mNumVehicles, tele, sync._tele_indexes)
    sync._SyncData__update_tele_map()


def test_rf2_vehicle_wrappers_cached_and_matched():
    from tinypedal.adapter.rf2_connector import copy_struct

    info, dataset = rf2_game()
    rf2_tick(info)
    for index in range(3):
        assert info.rf2TeleVeh(index).mID == info.rf2ScorVeh(index).mID
    assert info.rf2TeleVeh(2) is info.rf2TeleVeh(2)
    assert info.rf2ScorVeh(2) is info.rf2ScorVeh(2)
    from tinypedal.adapter.rf2_connector import EMPTY_TELE

    assert info._sync.sync_tele_index(6) == -1 and info.rf2TeleVeh(6) is EMPTY_TELE  # no telemetry: zeroed
    dataset.scor.data.mVehicles[6].mID = 7  # slot with telemetry, beyond vehicles in session
    expected = dataset.tele.data.mVehicles[info._sync.sync_tele_index(6)]
    assert ctypes.addressof(info.rf2TeleVeh(6)) == ctypes.addressof(expected)
    # Telemetry zone replaced: map ignored, matched on new structure
    dataset.tele.data = copy_struct(dataset.tele.data)
    tele = info.rf2TeleVeh(1)
    base = ctypes.addressof(dataset.tele.data)
    assert base <= ctypes.addressof(tele) < base + ctypes.sizeof(dataset.tele.data)
    assert tele.mID == 5


# Track map place numbers
@pytest.mark.parametrize("font_size", [11, 15, 22, 40])
def test_track_map_place_number_same_pixels_as_draw_text(track, font_size):  # noqa: F811
    from tinypedal.setting import cfg
    from tinypedal.widget.track_map import Realtime

    cfg.user.setting["track_map"].update(font_size=font_size, show_vehicle_class_standings=True)
    widget = Realtime(cfg, "track_map")
    try:
        for place in (*range(1, 61), 100):
            images = []
            for cached in (False, True):
                image = QImage(200, 200, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                painter.setFont(widget.font())
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(QColor("white"))
                painter.translate(QPointF(100.3, 99.6))
                if cached:
                    widget.draw_place_number(painter, place)
                else:
                    painter.drawText(widget.veh_text_shape, Qt.AlignmentFlag.AlignCenter, f"{place}")
                painter.end()
                images.append(image)
            assert images[0] == images[1], place
        assert len(widget.place_texts) == 61
        if font_size == 40:  # wider than car shape: kept clipped by drawText
            assert widget.place_texts[100] is None
        else:
            assert widget.place_texts[8] is not None
    finally:
        widget.deleteLater()
