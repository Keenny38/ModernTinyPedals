"""Audit H, lot A2: real-time game data pipeline (readers, connectors, vehicles module, command server, Rest poll)"""

import json
import socket
import threading

import pytest

from neopedal.module import module_vehicles
from tests.test_module_vehicles_field import field  # noqa: F401  (fixture)
from tests.test_readers import lmu_api, rf2_api


# --- 1. Vehicle count capped to mapped rows (garbage count never raises IndexError in loops)
def test_total_vehicles_capped_to_mapped_rows():
    from pyLMUSharedMemory.lmu_mmap import MAX_VEHICLES as LMU_MAX
    from pyRfactor2SharedMemory.rF2MMap import MAX_VEHICLES as RF2_MAX

    sim, data = lmu_api()
    reader = sim.reader().vehicle
    data.scoring.scoringInfo.mNumVehicles = 110
    assert reader.total_vehicles() == LMU_MAX == 104
    for index in range(reader.total_vehicles()):  # every listed row readable
        reader.slot_id(index)
    data.scoring.scoringInfo.mNumVehicles = -3
    assert reader.total_vehicles() == 0
    data.scoring.scoringInfo.mNumVehicles = 20
    assert reader.total_vehicles() == 20

    sim, info = rf2_api()
    reader = sim.reader().vehicle
    info._scor.data.mScoringInfo.mNumVehicles = 500
    assert reader.total_vehicles() == RF2_MAX == 128
    info._scor.data.mScoringInfo.mNumVehicles = -1
    assert reader.total_vehicles() == 0


# --- 2. Player index reset when no listed car is the player (never a stale index of another car)
def test_player_index_reset_without_player(field):  # noqa: F811
    from neopedal.api_control import api

    sync = api._api._shmmapi._sync
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    assert field.playerIndex == 0
    sync.player_scor_index = 2
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.1, True)
    assert field.playerIndex == 2 and field.dataSet[2].isPlayer
    sync.player_scor_index = 7  # player index beyond listed cars (car count shrank)
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.2, True)
    assert field.playerIndex == -1
    assert not any(car.isPlayer for car in field.dataSet[:field.totalVehicles])
    sync.player_scor_index = -1  # player not found yet
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.3, True)
    assert field.playerIndex == -1


def test_finish_time_without_player(field, monkeypatch):  # noqa: F811
    from neopedal.api_control import api
    from neopedal.module_info import minfo

    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    read_indexes = []

    class LapSpy:
        def __init__(self, lap):
            self._lap = lap

        def __getattr__(self, name):
            return getattr(self._lap, name)

        def progress(self, index=None):
            read_indexes.append(index)
            return self._lap.progress(index)

    monkeypatch.setattr(api, "read", api.read._replace(lap=LapSpy(api.read.lap)))
    monkeypatch.setattr(minfo.delta, "lapTimePace", 97.0)
    info = api._api._shmmapi._shmm.data.scoring.scoringInfo
    info.mMaxLaps = 2_000_000  # time only race
    info.mEndET = 3600.0
    field.playerIndex = -1
    field.leaderIndex = 1
    field.dataSet[1].lapTimeHistory.average = 96.0
    module_vehicles.update_finish_time(field, 60.0)
    assert -1 not in read_indexes  # never lap progress of the last row as if it were the player
    assert field.finishLapOffset == 0.0
    field.playerIndex = 0
    module_vehicles.update_finish_time(field, 60.0)
    assert read_indexes == [1, 0]


# --- 3. Slot id -> telemetry index: departed slots dropped, index owned by one slot only
def test_lmu_tele_indexes_purged():
    from neopedal.adapter import lmu_connector
    from pyLMUSharedMemory import lmu_data

    update = lmu_connector.SyncData._SyncData__update_tele_indexes
    telemetry = lmu_data.LMUTelemetryData()
    telemetry.activeVehicles = 2
    telemetry.telemInfo[0].mID, telemetry.telemInfo[1].mID = 7, 3
    indexes: dict = {}
    update(telemetry, indexes)
    assert indexes == {7: 0, 3: 1}
    telemetry.telemInfo[0].mID = 5  # car 7 left, car 5 took its index
    update(telemetry, indexes)
    assert indexes == {5: 0, 3: 1}
    telemetry.activeVehicles = 1  # car 3 left telemetry
    update(telemetry, indexes)
    assert indexes == {5: 0}


def test_rf2_tele_indexes_purged():
    from neopedal.adapter import rf2_connector
    from pyRfactor2SharedMemory import rF2data

    update = rf2_connector.SyncData._SyncData__update_tele_indexes
    tele = rF2data.rF2Telemetry()
    tele.mVehicles[0].mID, tele.mVehicles[1].mID = 7, 3
    indexes: dict = {}
    update(2, tele, indexes)
    assert indexes == {7: 0, 3: 1}
    tele.mVehicles[0].mID, tele.mVehicles[1].mID = 3, 9  # compacted: car 7 left, new car 9
    update(2, tele, indexes)
    assert indexes == {3: 0, 9: 1}
    update(0, tele, indexes)
    assert indexes == {}


# --- 4. Cut driver name shared by several drivers: no match (never another driver's incidents/penalties)
def incident_stream(*names: bytes) -> bytes:
    return b"\n".join(
        b'<Incident et="1.0">' + name + b"(12) reported contact (0.40) with another vehicle Other(3)</Incident>"
        for name in names)


def test_ambiguous_cut_name_not_matched():
    from neopedal.adapter.lmu_connector import DRIVER_NAME_SIZE, LMUResults

    cut = b"A" * (DRIVER_NAME_SIZE - 1)
    results = LMUResults()
    results.update(incident_stream(cut + b" One"))
    assert results.get(cut)["contact_vehicle"] == 1  # unique: matched (and cached)
    assert results.get(cut)["contact_vehicle"] == 1
    results.update(incident_stream(cut + b" One", cut + b" Two", cut + b" Two"))
    assert results.get(cut) is LMUResults.DEFAULT  # ambiguous now: cached lookup dropped
    assert results.get(cut + b" Two")["contact_vehicle"] == 2  # full names still exact
    assert results.penalty(cut) is not None
    results.clear()
    results.update(incident_stream(cut + b" Two"))
    assert results.get(cut)["contact_vehicle"] == 1


def test_cut_name_penalty_unique_only():
    from neopedal.adapter.lmu_connector import DRIVER_NAME_SIZE, LMUResults
    from neopedal.penalty_info import NO_PENALTY, Penalty

    cut = b"B" * (DRIVER_NAME_SIZE - 1)
    results = LMUResults()
    results.penalties[cut + b"x"] = Penalty(1, "Stop/Go", 10)
    assert results.penalty(cut) == Penalty(1, "Stop/Go", 10)
    results.penalties[cut + b"x"] = Penalty(2, "Stop/Go", 10)  # value replaced: never a cached old value
    assert results.penalty(cut).pending == 2
    results.penalties[cut + b"y"] = Penalty(1, "Drive Thru", 0)
    results.update(b"<Other/>")  # stream parsed: names may have changed
    assert results.penalty(cut) is NO_PENALTY


# --- 5. POST command with query string & body: routed, body read (client gets the answer)
@pytest.fixture
def local_server(monkeypatch):
    from neopedal import command_server

    monkeypatch.setattr(command_server.CommandHandler, "commands", {"overlay_lock": lambda: None})
    httpd = command_server.LocalHTTPServer(("127.0.0.1", 0), command_server.CommandHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.stop()


def raw_post(port: int, path: str, body: bytes, length: str | None = None) -> tuple[int, dict]:
    head = (
        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-NeoPedal: 1\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(body) if length is None else length}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(head + body)
        answer = b""
        while chunk := client.recv(65536):
            answer += chunk
    status_line, _, rest = answer.partition(b"\r\n")
    return int(status_line.split()[1]), json.loads(rest.partition(b"\r\n\r\n")[2])


def test_post_command_with_query_and_body(local_server):
    port = local_server.server_port
    status, data = raw_post(port, "/command/overlay_lock?src=deck", b'{"from": "stream deck"}' * 100)
    assert status == 200 and data == {"ok": True, "command": "overlay_lock"}
    status, data = raw_post(port, "/command/format_disk?x=1", b"{}")
    assert status == 404
    status, data = raw_post(port, "/command/overlay_lock", b"", length="abc")  # bad header ignored
    assert status == 200


# --- 6. Large Rest body (long race): read & parsed less often
def test_route_interval_scaled_with_body_size():
    from time import sleep

    from neopedal.energy_usage import CHECK_BYTES_PER_SECOND, CHECK_SECONDS, EnergyUsage

    now = [0.0]
    body = [b"{}"]
    fetched = []

    def fetch():
        fetched.append(now[0])
        return 200, body[0]

    poller = EnergyUsage(fetch, lambda: now[0])

    def tick(time):
        now[0] = time
        poller.poll()
        for _ in range(500):  # read done on poll worker
            if not poller._busy:
                break
            sleep(0.01)

    tick(0.0)
    tick(CHECK_SECONDS)
    assert fetched == [0.0, CHECK_SECONDS]  # small body: fixed interval
    body[0] = b'{"a": [' + b'{"ve": 0.5}, ' * (CHECK_BYTES_PER_SECOND * 2) + b'{"ve": 0.4}]}'
    tick(2 * CHECK_SECONDS)  # large body read: next read later
    wait = len(body[0]) / CHECK_BYTES_PER_SECOND
    assert wait > CHECK_SECONDS
    tick(3 * CHECK_SECONDS)
    assert len(fetched) == 3
    tick(2 * CHECK_SECONDS + wait)
    assert len(fetched) == 4
    assert poller.usage("a") is not None
