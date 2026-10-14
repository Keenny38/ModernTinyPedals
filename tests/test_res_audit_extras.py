"""Shared game answers pruned by the RestAPI loop, cached game text decoder, incidents decoded & parsed
incrementally by Director & Replays pages, lap viewer trace data released, map band of packed normals"""

import json
import math
import threading
from types import SimpleNamespace

import pytest

from neopedal.adapter import restapi_connector
from neopedal.validator import bytes_to_str, cached_bytes_to_str


# --- Stale shared game answers dropped periodically (also while idle)
def test_rest_cache_pruned_at_most_every_interval(monkeypatch):
    pruned = []
    now = [100.0]
    monkeypatch.setattr(restapi_connector, "monotonic", lambda: now[0])
    monkeypatch.setattr(restapi_connector.rest_cache, "prune", lambda: pruned.append(now[0]))
    last = restapi_connector.prune_rest_cache(now[0])
    assert last == 100.0 and not pruned
    now[0] += restapi_connector.CACHE_PRUNE_INTERVAL - 1
    assert restapi_connector.prune_rest_cache(last) == last and not pruned
    now[0] += 1
    last = restapi_connector.prune_rest_cache(last)
    assert pruned == [now[0]] and last == now[0]


def test_idle_update_loop_prunes_rest_cache(monkeypatch):
    """Not on track: idle loop wakes (activity wait) & prunes once interval passed"""
    from neopedal import realtime_state

    pruned = []
    clock = [0.0]

    def fake_monotonic():
        clock[0] += 20.0  # each wake 20 s later
        return clock[0]

    monkeypatch.setattr(realtime_state, "active", False)
    monkeypatch.setattr(restapi_connector, "monotonic", fake_monotonic)
    monkeypatch.setattr(restapi_connector.rest_cache, "prune", lambda: pruned.append(clock[0]))
    event = threading.Event()
    waits = []

    def wait_change(timeout, wake=None, since=None):
        waits.append(timeout)
        if len(waits) >= 6:
            event.set()
        return False

    monkeypatch.setattr(type(realtime_state), "wait_change", lambda self, *args, **kwargs: wait_change(*args, **kwargs))
    connector = restapi_connector.RestAPIConnector((), SimpleNamespace())
    connector._event = event
    monkeypatch.setattr(restapi_connector.RestAPIConnector, "_reset_if_current", lambda *args: None)
    connector._RestAPIConnector__update_loop(event, restapi_connector.TaskState())
    assert len(waits) == 6
    assert 2 <= len(pruned) <= 4  # every ~30 s of 120 s, not on every wake


# --- Game text decoder: decoded names kept, same text
@pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "iso-8859-1"])
def test_cached_decoder_same_text_as_bytes_to_str(encoding):
    tostr = cached_bytes_to_str(encoding)
    samples = [b"", b"Driver  ", "\xe9t\xe9 ".encode(encoding), b"\xff\xfe bad", b"LMP2", None, 5, bytearray(b"x")]
    for _ in range(2):  # decoded, then cached
        for sample in samples:
            assert tostr(sample) == bytes_to_str(sample, encoding)


def test_cached_decoder_bounded():
    tostr = cached_bytes_to_str(max_size=8)
    cache = next(cell.cell_contents for cell in tostr.__closure__ if isinstance(cell.cell_contents, dict))
    for index in range(50):
        assert tostr(f"name {index}".encode()) == f"name {index}"
        assert len(cache) <= 8


def test_cached_decoder_decodes_once():
    tostr = cached_bytes_to_str()
    raw = b"Driver name"
    first = tostr(raw)
    assert tostr(bytes(raw)) is first  # same text object: not decoded again


def test_connector_readers_use_cached_decoder():
    from tests.test_audit_h_c3 import lmu_api

    sim, data = lmu_api()
    read = sim.reader()
    data.scoring.vehScoringInfo[0].mDriverName = b"Jos"
    name = read.vehicle.driver_name()
    assert name == "Jos" and read.vehicle.driver_name() is name
    sim.set_encoding("ISO-8859-1")
    data.scoring.vehScoringInfo[0].mDriverName = "Jos\xe9".encode("latin-1")
    assert read.vehicle.driver_name() == "Jos\xe9"


# --- Incidents of Director & Replays pages: decoded & parsed incrementally, same contacts
def incident(index: int, time_: float | None = None) -> dict:
    return {"et": float(index) if time_ is None else time_, "player": f"Driver {index}", "contactWith": "Immovable"}


class FakeConnection:
    """Game answers (text) by resource, decoded by given decoder"""

    answered = True

    def __init__(self, texts: dict):
        self.texts = texts

    def get(self, resource, decode=None):
        text = self.texts.get(resource)
        if text is None:
            return None
        return json.loads(text) if decode is None else decode(text)

    def send(self, *args, **kwargs):
        return True


@pytest.mark.parametrize("page", ["director", "replays"])
def test_page_incidents_parsed_incrementally_same_contacts(page, monkeypatch):
    from neopedal.adapter.restapi_connector import AppendedListDecoder
    from neopedal.process import game_info
    from neopedal.process.game_info import ContactsParser, parse_contacts

    if page == "director":
        from neopedal.ui.quick import director_game as module
        from neopedal.ui.quick import game_camera as gc
        incidents_route, active_route = gc.INCIDENTS_RESOURCE, gc.ACTIVE_RESOURCE

        def ask(connection, decode, parse):
            return module.ask_state(connection, decode_incidents=decode, contacts_of=parse)
    else:
        from neopedal.ui.quick import replays_backend as module
        incidents_route, active_route = module.INCIDENTS_RESOURCE, module.ACTIVE_RESOURCE

        def ask(connection, decode, parse):
            return module.ask_state(connection, (), frozenset(), False, None, decode, parse)

    parsed = []
    real = game_info._contacts_of
    monkeypatch.setattr(game_info, "_contacts_of", lambda entries: (parsed.append(len(entries)), real(entries))[1])
    decode, parse = AppendedListDecoder(), ContactsParser()
    entries = [incident(index) for index in range(60)]
    texts = {active_route: "false", incidents_route: json.dumps(entries[:50])}
    connection = FakeConnection(texts)
    for shown in (50, 55, 60):
        texts[incidents_route] = json.dumps(entries[:shown])
        parsed.clear()
        state = ask(connection, decode, parse)
        assert state["contacts"] == parse_contacts(entries[:shown], ())
    assert parsed[0] == 5  # only entries added parsed (5 then 5)
    # New session: other list parsed in full, still same contacts
    texts[incidents_route] = json.dumps([incident(3, 0.5)])
    assert ask(connection, decode, parse)["contacts"] == parse_contacts([incident(3, 0.5)], ())


# --- Lap viewer: trace data released without reading unit settings
def test_trace_data_release_same_as_no_lap(ui_env, monkeypatch):
    from neopedal.ui.quick import trace_data
    from neopedal.ui.quick.trace_data import TraceData

    data = TraceData()
    data._series[("lap", "speed")] = ([0.0], [1.0])
    data._xs[("lap", 0)] = ([0.0], [0.0])
    data._times["lap"] = ([0.0], [0.0])
    data._samples["lap"] = [0.0]
    data._ranges[("lap",)] = (0.0, 1.0)
    data.reference_deltas = data.deltas = {"lap": ([0.0], [0.0])}
    data.sector_lines = [1.0]
    data.prepared = ([], "", "", None)
    version = data.version

    def no_units():
        raise KeyError("units unloaded")

    monkeypatch.setattr(trace_data, "display_units", no_units)
    data.release()
    assert data.version != version
    assert data.laps == [] and data.reference is None and data.prepared is None
    assert not (data._series or data._xs or data._times or data._samples or data._ranges)
    assert data.deltas == {} and data.reference_deltas == {} and data.sector_lines == [] and data.scales == {}


# --- Map band of packed normals: read directly, same vertices
def test_band_part_packed_normals_same_vertices():
    from neopedal.ui.quick import lines
    from neopedal.ui.quick.lap_map import PackedNormals

    count = 500
    xs = [math.cos(index / 40) * 300 + index * 0.01 for index in range(count)]
    ys = [math.sin(index / 55) * 200 for index in range(count)]
    packed = PackedNormals(xs, ys)
    for indexes in (range(count), range(0, count, 7), [3, 9, 10, 400], [5], []):
        fast = lines.band_part(xs, ys, packed, indexes, 2.5)
        slow = lines.band_part(xs, ys, list(packed), indexes, 2.5)
        assert fast.vertex_count == slow.vertex_count
        assert fast.data.tobytes() == slow.data.tobytes()
