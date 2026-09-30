"""Black box widget: incident recorder robustness, race events, replay & comparison, state kept on rebuild"""

import json

import pytest

from tinypedal.widget._black_box import persist
from tinypedal.widget._black_box import recorder as rec
from tinypedal.widget._black_box.recorder import EventLog, RaceReadings, Recorder, Sample, log_race_events
from tinypedal.widget._black_box.trace import replay_time, sample_at


def sample(time, speed, throttle=0.0, brake=0.0, gear=3):
    return Sample(time, speed, throttle, brake, gear, False, False, "")


@pytest.fixture(autouse=True)
def clear_memory():
    persist.MEMORY.clear()
    yield
    persist.MEMORY.clear()


def new_widget(overrides=None):
    from tinypedal.setting import cfg
    from tinypedal.widget import black_box

    cfg.user.setting["black_box"].update({"enable_auto_resize": False, **(overrides or {})})
    return black_box.Realtime(cfg, "black_box")


# --- Recorder
def test_new_session_keeps_incident_still_recording():
    recorder = Recorder(duration=5.0, sample_interval=0.1, post_trigger=2.0)
    recorder.add(sample(0.0, 30.0), 0.0)
    recorder.add(sample(0.1, 30.0), 0.0, impact=True)
    assert recorder.pending is not None
    incident = recorder.reset()
    assert incident is not None and incident.reason == "impact"
    assert recorder.incidents[-1] is incident
    assert recorder.pending is None and not recorder.samples
    assert recorder.reset() is None  # nothing pending


def test_deceleration_and_game_impact_have_own_reason():
    recorder = Recorder(duration=5.0, sample_interval=0.05, post_trigger=0.0)
    time = 0.0
    for _ in range(10):
        recorder.add(sample(time, 50.0), 0.0)
        time += 0.05
    assert recorder.add(sample(time, 30.0), 0.0).reason == "decel"
    assert recorder.add(sample(time + 5.0, 30.0), 0.0, impact=True).reason == "impact"


def test_index_of_uses_identity():
    first = rec.Incident(1.0, "impact", 5.0, 1, 0.0, (sample(0.0, 1.0),))
    same_values = rec.Incident(*first)
    assert same_values == first and same_values is not first
    assert rec.index_of([same_values, first], first) == 1
    assert rec.index_of([same_values], first) == -1


def test_previous_incident():
    recorder = Recorder()
    older = rec.Incident(1.0, "impact", 5.0, 1, 0.0, ())
    newer = rec.Incident(9.0, "decel", 6.0, 2, 0.0, ())
    recorder.incidents.extend((older, newer))
    assert recorder.previous_incident(newer) is older
    assert recorder.previous_incident(older) is None


def test_exports_of_same_second_do_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(rec.time, "strftime", lambda _format: "20260930-120000")
    incident = rec.Incident(10.0, "impact", 6.3, 4, 250.0, (sample(9.0, 50.0), sample(10.0, 5.0)))
    first = rec.export_incident(incident, str(tmp_path), "Both")
    second = rec.export_incident(incident, str(tmp_path), "JSON")
    assert first.endswith("lap4.csv") and second.endswith("lap4-2.json")
    assert len(list(tmp_path.iterdir())) == 3


def test_export_queue_writes_in_background(tmp_path):
    incident = rec.Incident(10.0, "decel", 6.3, 4, 250.0, (sample(9.0, 50.0), sample(10.0, 5.0)))
    path = rec.ExportQueue().submit(incident, str(tmp_path), "JSON").result(timeout=5)
    with open(path, encoding="utf-8") as file:
        assert json.load(file)["reason"] == "decel"


# --- Race events
def test_race_events_logged_once_when_they_start():
    log = EventLog(20)

    def update(**readings):
        log_race_events(log, 3, 100.0, RaceReadings(**readings), {})

    base = dict(yellow=False, blue=False, in_pits=False, penalties=0, cut_points=0.0, limit_points=4.0,
                oil_hot=False, water_hot=False, oil=110.0, water=90.0)
    update(**base)
    assert not log.events  # first reading is the reference
    update(**{**base, "yellow": True})
    update(**{**base, "yellow": True})  # still out: logged once
    update(**{**base, "blue": True, "in_pits": True})
    update(**{**base, "penalties": 1, "cut_points": 2.0})
    update(**{**base, "penalties": 1, "cut_points": 4.0, "oil_hot": True, "oil": 127.0})
    texts = [event.text for event in log.events]
    assert texts == ["YELLOW", "BLUE", "PIT IN", "PIT OUT", "PENALTY 1", "LIMITS 2/4", "LIMITS 4/4", "OIL HOT 127"]
    critical = {event.text: event.critical for event in log.events}
    assert critical["PENALTY 1"] and critical["LIMITS 4/4"] and not critical["LIMITS 2/4"]
    assert critical["OIL HOT 127"] and not critical["YELLOW"]


def test_race_events_not_read_are_not_logged():
    log = EventLog(5)
    log_race_events(log, 1, 0.0, RaceReadings(), {})
    log_race_events(log, 1, 1.0, RaceReadings(in_pits=True), {})
    assert not log.events


def test_race_events_reference_forgotten_on_new_session():
    log = EventLog(5)
    log_race_events(log, 1, 0.0, RaceReadings(penalties=2), {})
    log.reset()
    log_race_events(log, 1, 0.0, RaceReadings(penalties=3), {})  # new reference, not a new penalty
    assert not log.events


def test_widget_logs_race_events(ui_env, monkeypatch):
    from tinypedal.api_control import api

    yellow = [False]
    monkeypatch.setattr(api.read.session, "yellow_flag", lambda: yellow[0])
    widget = new_widget({"show_event_log": True, "text_yellow_flag": "JAUNE"})
    try:
        widget.update_race_events(False)
        yellow[0] = True
        widget.update_race_events(False)
        assert widget.event_log.events[-1].text == "JAUNE"
        widget.grab()
    finally:
        widget.deleteLater()


def test_race_events_off_without_event_log(ui_env):
    widget = new_widget({"show_event_log": False})
    try:
        assert not widget.log_race_events
    finally:
        widget.deleteLater()


# --- Pause
def test_recorder_clock_stops_while_paused(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.widget._black_box import reader

    clock = [100.0]
    paused = [False]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api.read.state, "paused", lambda: paused[0])
    widget = new_widget({"show_incident_recorder": True, "enable_incident_file_export": False})
    try:
        widget.update_recorder(30.0)
        count = len(widget.recorder.samples)
        paused[0] = True
        clock[0] += 0.05
        widget.update_recorder(30.0)  # pause seen
        clock[0] += 60.0
        widget.update_recorder(30.0)
        assert len(widget.recorder.samples) == count  # nothing recorded while paused
        paused[0] = False
        clock[0] += 0.1
        widget.update_recorder(30.0)
        samples = widget.recorder.samples
        assert samples[-1].time - samples[-2].time == pytest.approx(0.05)  # no 60 s gap: clock stopped when pause seen
    finally:
        widget.deleteLater()


# --- Replay & comparison
def test_replay_time_sweeps_then_loops():
    assert replay_time(10.0, 20.0, 0.0) == 10.0
    assert replay_time(10.0, 20.0, 4.0) == 14.0
    assert replay_time(10.0, 20.0, 10.5) == 20.0  # rests at the end
    assert replay_time(10.0, 20.0, 11.0 + 2.0) == 12.0  # starts again


def test_sample_at():
    samples = (sample(1.0, 10.0), sample(2.0, 20.0), sample(3.0, 30.0))
    assert sample_at(samples, 0.0).speed == 10.0
    assert sample_at(samples, 2.5).speed == 20.0
    assert sample_at(samples, 9.0).speed == 30.0


def test_frozen_incident_replayed_and_compared(ui_env, monkeypatch):
    from tinypedal.widget._black_box import reader

    clock = [100.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    widget = new_widget({"show_incident_recorder": True, "enable_incident_file_export": False})
    try:
        older = rec.Incident(50.0, "impact", 4.0, 2, 10.0, tuple(sample(40.0 + t, 60.0 - t) for t in range(12)))
        newer = rec.Incident(99.0, "decel", 6.0, 3, 20.0, tuple(sample(89.0 + t, 50.0, 0.5, 0.2) for t in range(12)))
        widget.recorder.incidents.extend((older, newer))
        assert widget.compared_incident(newer) is older
        assert widget.animating()  # replay cursor moves
        widget.grab()
        assert widget.replay_cursor_time(newer) == pytest.approx(89.0 + (100.0 - 100.0))
    finally:
        widget.deleteLater()


def test_replay_and_comparison_can_be_turned_off(ui_env):
    widget = new_widget({"show_incident_recorder": True, "enable_incident_replay": False,
                         "show_previous_incident_trace": False})
    try:
        newer = rec.Incident(1.0, "impact", 4.0, 1, 0.0, ())
        widget.recorder.incidents.extend((rec.Incident(0.0, "impact", 4.0, 1, 0.0, ()), newer))
        assert widget.compared_incident(newer) is None
        widget.grab()
    finally:
        widget.deleteLater()


# --- State kept across rebuild, position saved later
def test_rebuilt_widget_keeps_incidents_and_events(ui_env):
    incident = rec.Incident(1.0, "impact", 4.0, 1, 0.0, ())
    first = new_widget({"show_incident_recorder": True, "show_event_log": True})
    try:
        first.recorder.incidents.append(incident)
        first.event_log.add(1, 5.0, "IMPACT 4.0g", False)
        first.event_log.last_damage = 0.5
        persist.keep_records("black_box", first.recorder, first.event_log)
    finally:
        first.deleteLater()
    second = new_widget({"show_incident_recorder": True, "show_event_log": True})
    try:
        assert second.recorder.incidents[-1] is incident
        assert second.event_log.events[-1].text == "IMPACT 4.0g"
        assert second.event_log.last_damage == second.recorder.last_damage == 0.5
    finally:
        second.deleteLater()


def test_auto_resize_position_saved_once_off_track(ui_env, monkeypatch):
    from tinypedal.setting import cfg

    saves = []
    monkeypatch.setattr(type(cfg), "save", lambda *args, **kwargs: saves.append(1))
    widget = new_widget({"resize_anchor": "Bottom Right"})
    try:
        widget.move_anchored(200, 200, 150, 150)
        widget.move_anchored(150, 150, 100, 100)
        assert widget.position_unsaved and not saves  # not while driving
        widget.post_update()
        widget.post_update()
        assert saves == [1] and not widget.position_unsaved
    finally:
        widget.deleteLater()


def test_open_incident_folder_in_menu(ui_env, monkeypatch):
    from tinypedal.widget import black_box

    opened = []
    monkeypatch.setattr(black_box, "open_folder", opened.append)
    widget = new_widget({"enable_incident_file_export": True})
    try:
        (name, action), = widget.menu_actions()
        action()
        assert name == "Open Incident Folder" and opened[0].endswith("blackbox")
    finally:
        widget.deleteLater()
    widget = new_widget({"enable_incident_file_export": False})
    try:
        assert widget.menu_actions() == ()
    finally:
        widget.deleteLater()


def test_open_folder_creates_it(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(rec.os, "startfile", opened.append, raising=False)
    folder = tmp_path / "blackbox"
    assert rec.open_folder(str(folder))
    assert folder.is_dir() and opened == [str(folder)]
