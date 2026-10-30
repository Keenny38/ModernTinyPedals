"""Data memory: results files parsed incrementally & shared, replay frame index packed, Director tables trimmed,
drivers history released, game Rest API answers dropped once stale"""

import os
import random
import time
import types
import xml.etree.ElementTree as ET

import pytest

from neopedal.process import director as dr
from neopedal.process import driver_history as dh
from neopedal.process import results_file as rf
from neopedal.replay import KEYFRAME_INTERVAL, ReplayFile, ReplayWriter
from tests.test_broadcast_director import director_page  # noqa: F401

DRIVER = """<Driver><Name>{name}</Name><CarClass>GT3</CarClass><Position>{position}</Position><isPlayer>1</isPlayer>
<Laps>2</Laps><Swap startLap="0" endLap="2">{name}</Swap>
<Lap num="2" p="{position}" et="190.0" s1="30.1" s2="40.2" s3="25.3" fcompound="0,Medium">95.6</Lap>
<Lap num="1" p="{position}" et="100.0" s1="31.0" s2="41.0" s3="26.0" fcompound="0,Soft" pit="1">98.0</Lap>
<ControlAndAids startLap="0" endLap="2">PlayerControl</ControlAndAids></Driver>"""


def results_xml(stream_first: bool = True) -> bytes:
    drivers = "".join(DRIVER.format(name=name, position=position)
                      for position, name in ((2, "Bob"), (1, "Ann"), (3, "Ann")))
    stream = ('<Stream><Incident et="120.0">Ann(0) reported contact (150.50) with another vehicle Bob(1)</Incident>'
              '<Penalty Driver="Bob" Penalty="Stop/Go" Time="10" et="400.0">Bob penalty</Penalty></Stream>')
    session = (stream + drivers) if stream_first else (drivers + stream)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE rF [\n<!ENTITY e "x">\n]>\n<rFactorXML><RaceResults>'
        "<Setting>Multi\x01player</Setting><TrackVenue>Spa</TrackVenue>"
        f"<Race><DateTime>1790000600</DateTime><Laps>20</Laps>{session}"
        "<MostLapsCompleted>2</MostLapsCompleted><Stream><Incident et=\"5.0\">ignored</Incident></Stream></Race>"
        "<Practice1><Driver><Name>Other</Name></Driver></Practice1></RaceResults><RaceResults><TrackVenue>Second</TrackVenue></RaceResults></rFactorXML>\x00"
    ).encode()


def whole_tree(data: bytes, path: str, names) -> rf.SessionResult:
    """Results parsed as one tree (reference of incremental parse)"""
    data = rf.DOCTYPE.sub(b"", data, count=1)
    data = rf.INVALID_CHARS.sub(b"", data[:data.rfind(rf.ROOT_END) + len(rf.ROOT_END)])
    results = ET.fromstring(data).find("RaceResults")
    session = next(child for child in results if rf.session_kind(child.tag))
    entries = rf.mark_player([rf.parse_entry(driver) for driver in session.findall("Driver")], names)
    entries.sort(key=rf.entry_order)
    return rf.SessionResult(
        path, rf.game_of_path(path), rf._text(results, "Setting"), rf._text(results, "ServerName"),
        rf._float(rf._text(session, "DateTime")) or rf._float(rf._text(results, "DateTime")), session.tag,
        rf.session_kind(session.tag), rf._text(results, "TrackEvent") or rf._text(results, "TrackVenue"),
        rf._text(results, "TrackVenue"), rf._text(results, "TrackCourse"), rf._float(rf._text(results, "TrackLength")),
        rf._text(results, "GameVersion"), rf._int(rf._text(session, "Minutes")), 20,
        rf._int(rf._text(session, "MostLapsCompleted")), tuple(entries), rf.parse_events(session.find("Stream")))


@pytest.mark.parametrize("stream_first", [True, False])
def test_incremental_parse_same_as_whole_tree(stream_first):
    data = results_xml(stream_first)
    for names in ((), ("ann",)):
        assert rf.parse_results(data, "x.xml", names) == whole_tree(data, "x.xml", names)
    result = rf.parse_results(data, "x.xml", ("ann",))
    assert [entry.name for entry in result.entries] == ["Ann", "Bob", "Ann"]
    assert [entry.player for entry in result.entries] == [True, False, False]  # first one of the file
    assert len(result.events) == 2 and result.entries[0].laps[0].number == 1


def test_parse_keeps_no_copy_when_nothing_to_remove(monkeypatch):
    data = results_xml().replace(b"\x01", b"").replace(b'<!DOCTYPE rF [\n<!ENTITY e "x">\n]>\n', b"")
    calls = []
    for name in ("DOCTYPE", "INVALID_CHARS"):
        pattern = getattr(rf, name)
        monkeypatch.setattr(rf, name, types.SimpleNamespace(
            search=pattern.search, sub=lambda *args, pattern=pattern: calls.append(1) or pattern.sub(*args)))
    assert rf.parse_results(data).entries
    assert not calls


def test_results_parsed_once_shared_and_bounded(tmp_path, monkeypatch):
    rf.forget_results()
    path = str(tmp_path / "2026_10_05_22_34_33-70R1.xml")
    with open(path, "wb") as file:
        file.write(results_xml())
    parsed = []
    real = rf._parse_raw
    monkeypatch.setattr(rf, "_parse_raw", lambda *args: parsed.append(1) or real(*args))
    first = rf.read_results(path, ("bob",))
    second = rf.read_results(path, ("ann",))
    assert len(parsed) == 1
    assert first.entries[1].player and not second.entries[1].player and second.entries[0].player
    assert first.entries[0].laps is second.entries[0].laps  # same parse shared by every reader
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))  # file changed: read again
    rf.read_results(path)
    assert len(parsed) == 2
    rf.forget_results()
    rf.read_results(path, keep=False)  # bulk scan: nothing kept
    rf.read_results(path, keep=False)
    assert len(parsed) == 4
    monkeypatch.setattr(rf, "CACHE_BYTES", 1)  # larger than budget: never kept
    rf.read_results(path)
    rf.read_results(path)
    assert len(parsed) == 6
    rf.forget_results()


def test_result_bytes_grows_with_laps():
    small = rf.parse_results(results_xml())
    big = small._replace(entries=small.entries * 10)
    assert rf.result_bytes(big) > rf.result_bytes(small) > 0


def test_results_page_keeps_full_results_within_byte_budget(monkeypatch):
    from neopedal.ui.quick import results_backend as rb

    result = rf.parse_results(results_xml())
    page = types.SimpleNamespace(kept=__import__("collections").OrderedDict(), _kept_bytes={})
    monkeypatch.setattr(rb, "KEPT_BYTES", rf.result_bytes(result) * 2)
    for index in range(4):
        rb.RaceResultsBackend.keep(page, f"p{index}", None, result)
    assert list(page.kept) == ["p2", "p3"] and set(page._kept_bytes) == {"p2", "p3"}
    monkeypatch.setattr(rb, "KEPT_BYTES", 1)
    rb.RaceResultsBackend.keep(page, "p4", None, result)
    assert list(page.kept) == ["p4"]  # last one always kept


# Replay frame index
def test_replay_index_packed_and_seek_fast(tmp_path):
    frames = [bytes((index * 7 + offset) % 256 for offset in range(256)) for index in range(KEYFRAME_INTERVAL * 20)]
    filename = str(tmp_path / "test.tpreplay")
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, len(frames[0]), rate=10)
        for index, frame in enumerate(frames):
            writer.write(index * 0.1, frame)
    replay = ReplayFile(filename)
    assert not hasattr(replay, "_sizes") and not hasattr(replay, "_crcs")
    per_frame = (replay.times.itemsize + replay._heads.itemsize + 1)
    assert per_frame <= 17
    picks = random.Random(1).sample(range(len(frames)), 60)
    start = time.perf_counter()
    for index in picks:
        assert replay.frame(index) == frames[index]
    assert time.perf_counter() - start < 2.0
    replay.close()


# Director
def test_lap_history_packed_and_bounded(monkeypatch):
    monkeypatch.setattr(dr, "LAP_LIMIT", 3)
    laps = dr.LapHistory()
    records = [dr.LapRecord(number, 90.0 + number, (20.0, 30.0, -1.0), number % 2 == 0, 0.04, number)
               for number in range(1, 6)]
    for record in records:
        laps.append(record)
    assert list(laps) == records[-3:] and list(reversed(laps)) == records[:1:-1]
    assert laps[-1] == records[-1] and laps[0] == records[2] and len(laps) == 3
    with pytest.raises(IndexError):
        laps[3]


def test_severity_and_seen_incidents_bounded(monkeypatch):
    watcher = dr.RaceWatcher()
    monkeypatch.setattr(dr, "FEED_LIMIT", 2)
    watcher.measuring = [dr.Event(f"contact|{index}", dr.CONTACT, 1.0, (1,), ("a",), "GT3") for index in range(4)]
    state = types.SimpleNamespace(speeds=[(0.5, 50.0), (1.5, 10.0)])
    watcher.cars = {1: state}
    watcher.measure_contacts([], 2.0)
    assert list(watcher.severity) == ["contact|2", "contact|3"]
    watcher.seen_incidents = {(float(index), "a", "b") for index in range(500)}
    contact = types.SimpleNamespace(time=1.0, driver="a", other="b", contacts=1)
    monkeypatch.setattr(dr, "merge_contacts", lambda contacts: [contact])
    watcher.contact_events(("listed",), [], 10.0, False)
    assert watcher.seen_incidents == {(1.0, "a", "b")}  # game list cut: gone incidents forgotten


def test_director_feed_cut_drops_texts_and_seen(monkeypatch):
    from neopedal.ui.quick.director_backend import DirectorBackend

    monkeypatch.setattr(dr, "FEED_LIMIT", 2)
    page = types.SimpleNamespace(
        event_index={}, events=[], _events_revision=0, _texts={}, seen=set(), _shown=False,
        _log=types.SimpleNamespace(log_events=False), update_unseen=lambda: None)
    events = [dr.Event(f"e{index}", dr.CONTACT, float(index), (), (), "") for index in range(4)]
    page._texts = {event.key: ("t", "d") for event in events}
    page.seen = {event.key for event in events}
    DirectorBackend.add_events(page, events)
    assert [event.key for event in page.events] == ["e2", "e3"]
    assert set(page._texts) == set(page.seen) == set(page.event_index) == {"e2", "e3"}


def test_drivers_history_cleared_while_scan_runs(monkeypatch, tmp_path):
    history = dh.DriverHistory()
    path = str(tmp_path / "2026_10_05_22_34_33-70R1.xml")
    with open(path, "wb") as file:
        file.write(b"x")
    monkeypatch.setattr(rf, "results_files", lambda folder: [path])

    def read(found):
        history.clear()  # Director page closed meanwhile
        return {"ann": dh.RaceRecord(found, 1.0, "Spa", "GT3", 1, True, 3)}

    monkeypatch.setattr(history, "read", read)
    assert not history.scan([str(tmp_path)])
    assert history.records("ann") == []


def test_director_release_keeps_drivers_history(director_page, monkeypatch, tmp_path):  # noqa: F811
    """Broadcast Director closed: race history of every driver kept (small records, up to 2000 race files
    parsed again at each opening before, see audit PERF-006)"""
    path = str(tmp_path / "2026_10_05_22_34_33-70R1.xml")
    with open(path, "wb") as file:
        file.write(b"x")
    monkeypatch.setattr(rf, "results_files", lambda folder: [path])
    monkeypatch.setattr(dh.history, "read", lambda found: {"ann": dh.RaceRecord(found, 1.0, "Spa", "GT3", 1, True, 3)})
    try:
        assert dh.history.scan([str(tmp_path)])
        assert len(dh.history.records("ann")) == 1
        director_page.backend.release()
        assert len(dh.history.records("ann")) == 1
        assert dh.history._files  # file stamps kept: unchanged files never parsed again
    finally:
        dh.DriverHistory.clear(dh.history)  # never left filled for later tests
