"""Audit I lot C: Game Replays backend & panels. Timeline markers & driver chips as models synced in place,
values computed once & told only when changed, selection as a row role (replays, incidents, markers, standings),
signals split per property, copy progress throttled, hover buttons kept by rows (no Loader per hover)"""

import copy
import re
from pathlib import Path

import pytest
from shiboken6 import getCppPointer

from tests.test_game_info import CONTACTS, GAME_ANSWERS, answered, replays_page, wait_requests  # noqa: F401
from tests.test_game_replays_perf import items_of, pump

QML = Path(__file__).resolve().parents[1] / "neopedal" / "ui" / "qml"


def counter(signal) -> list:
    calls: list = []
    signal.connect(lambda *args: calls.append(args))
    return calls


def model_events(model) -> dict:
    events: dict = {"reset": [], "inserted": [], "removed": [], "changed": []}
    model.modelReset.connect(lambda: events["reset"].append(True))
    model.rowsInserted.connect(lambda parent, first, last: events["inserted"].append((first, last)))
    model.rowsRemoved.connect(lambda parent, first, last: events["removed"].append((first, last)))
    model.dataChanged.connect(lambda first, last, roles: events["changed"].append((first.row(), last.row())))
    return events


def answers_with(**changes) -> dict:
    answers = copy.deepcopy(GAME_ANSWERS)
    answers.update(changes)
    return answers


def refresh(page, answers: dict):
    page.game.answers = answers
    page.backend.refresh_state()
    wait_requests(page.backend.request_state)


NEW_CONTACT = {"contactWith": "Immovable", "et": 1700.0, "player": "Zaac Latta"}


# --- Timeline end & markers (B5, architecture 4)
def test_timeline_end_function():
    from neopedal.ui.quick.replays_backend import timeline_end

    assert timeline_end(0.0, -1.0, 3600.0) == pytest.approx(3600.0)
    assert timeline_end(0.0, -1.0, -1.0) == 120.0  # a minute at least, a little room after, whole minutes
    ends = {timeline_end(1500.0, float(time), -1.0) for time in range(1700, 1760, 7)}
    assert len(ends) <= 2 and all(end % 60 == 0 for end in ends)  # replay time answers: span rarely changes


def test_markers_and_chips_synced_in_place(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    markers, chips = backend.incidentMarkers, backend.driverChips
    assert [row["shown"] for row in markers.rows] == [True, True] and backend.timelineEnd == pytest.approx(3600.0)
    assert chips.rows[0] == {"name": "Gabe Poblete", "incidents": 1, "mine": False, "car": ""}
    kept = list(markers.rows)
    marker_events, chip_events = model_events(markers), model_events(chips)
    incidents, ends = counter(backend.incidentsChanged), counter(backend.timelineEndChanged)
    refresh(replays_page, answers_with(**{"/rest/watch/getIncidentsList/1": [*CONTACTS, NEW_CONTACT]}))
    # New incident: its marker inserted, other markers kept (same rows, no reset), timeline span unchanged
    assert len(markers.rows) == 3 and markers.rows[1]["time"] == 1700.0
    assert marker_events["inserted"] == [(1, 1)] and not marker_events["reset"] and not marker_events["removed"]
    assert markers.rows[0] is kept[0] and markers.rows[2] is kept[1]
    assert not ends and incidents  # counts changed
    zaac = next(row for row in chips.rows if row["name"] == "Zaac Latta")
    assert zaac["incidents"] == 2 and zaac["mine"] and not chip_events["reset"]
    # Same answer again: nothing told
    for events in (marker_events, chip_events):
        for kind in events.values():
            kind.clear()
    incidents.clear()
    refresh(replays_page, answers_with(**{"/rest/watch/getIncidentsList/1": [*CONTACTS, NEW_CONTACT]}))
    backend.update_incidents()
    assert not incidents and not any(marker_events.values()) and not any(chip_events.values())


def test_filters_change_marker_roles_only(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    markers = backend.incidentMarkers
    events = model_events(markers)
    backend.setIncidentFilter(2)  # walls only: shown role of the contact between cars changed
    assert [row["shown"] for row in markers.rows] == [True, False]
    assert events["changed"] == [(1, 1)] and not events["reset"] and not events["inserted"]
    backend.setIncidentFilter(0)
    assert all(row["shown"] for row in markers.rows)


def test_counts_and_chips_computed_once(replays_page, monkeypatch):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    calls: list = []
    real = backend.player_name
    monkeypatch.setattr(backend, "player_name", lambda: calls.append(True) or real())
    first = backend.counts
    for _ in range(5):  # read by several bindings
        assert backend.counts is first
    assert first == {"all": 2, "cars": 1, "walls": 1, "mine": 1, "shown": 2} and not calls
    counted = backend.incident_counts()
    assert backend.incident_counts() is counted  # standings rows & chips share one count per incidents list


# --- Selection as a row role, split signals (B6, bridge, architecture 3)
def test_incident_selection_role_and_signal(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    rows, markers = backend.incidentRows, backend.incidentMarkers
    replay_selection, incident_selection = counter(backend.selectionChanged), counter(backend.incidentSelectionChanged)
    row_events, marker_events = model_events(rows), model_events(markers)
    first, second = rows.rows[0]["key"], rows.rows[1]["key"]
    backend.selectIncident(first)
    backend.selectIncident(first)  # same: nothing told
    assert len(incident_selection) == 1 and not replay_selection  # replay list bindings untouched
    assert [row["selected"] for row in rows.rows] == [True, False]
    assert [row["selected"] for row in markers.rows] == [True, False]
    assert row_events["changed"] == [(0, 0)] and marker_events["changed"] == [(0, 0)]
    backend.selectIncident(second)
    assert [row["selected"] for row in rows.rows] == [False, True]
    assert [row["selected"] for row in markers.rows] == [False, True]
    backend.setIncidentFilter(2)  # walls only: selected contact filtered out, no longer selected
    assert backend.selectedIncident == "" and len(incident_selection) == 3
    assert not any(row["selected"] for row in markers.rows) and not any(row["selected"] for row in rows.rows)


def test_standings_selection_energy_and_split_signals(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    model = backend.standingRows
    signals = {name: counter(getattr(backend, name)) for name in (
        "selectedCarChanged", "energyColumnChanged", "classFilterChanged", "carCountChanged")}
    events = model_events(model)
    backend.update_standings()
    assert not any(signals.values()) and not any(events.values())  # nothing changed: nothing told
    assert backend.carCount == 3 and not backend.hasEnergy
    backend.selectCar("4")
    assert [row["selected"] for row in model.rows] == [False, True, False] and backend.selectedCar == "4"
    backend.selectCar("7")
    assert [row["selected"] for row in model.rows] == [True, False, False]
    assert len(signals["selectedCarChanged"]) == 2 and events["changed"] == [(1, 1), (1, 1), (0, 0)]
    assert not signals["energyColumnChanged"] and not signals["classFilterChanged"]
    backend.setClassFilter("Hypercar")  # car selected filtered out: no longer selected
    assert len(signals["classFilterChanged"]) == 1 and backend.selectedCar == "" and len(signals["selectedCarChanged"]) == 3
    assert not signals["carCountChanged"]  # every car still in the session
    backend.setClassFilter("Hypercar")  # same class again: all
    assert backend.classFilter == "" and len(signals["classFilterChanged"]) == 2
    # Energy told by game for own car: column shown, told once
    standings = copy.deepcopy(GAME_ANSWERS["/rest/watch/standings"])
    standings[0]["veFraction"] = 0.5
    for _ in range(2):
        refresh(replays_page, answers_with(**{"/rest/watch/standings": standings}))
    assert backend.hasEnergy and len(signals["energyColumnChanged"]) == 1
    refresh(replays_page, answers_with(**{"/rest/watch/standings": standings[:2]}))
    assert backend.carCount == 2 and len(signals["carCountChanged"]) == 1


def test_replay_selection_role_checked_summary_and_signals(replays_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import replays_backend

    backend = answered(replays_page, GAME_ANSWERS)
    model = backend.replayRows
    algarve, bahrain = "Algarve P1 1", "Bahrain R1"
    assert [(row["key"], row["selected"]) for row in model.rows] == [(bahrain, True), (algarve, False)]
    selection, checked = counter(backend.selectionChanged), counter(backend.checkedChanged)
    protected = counter(backend.selectedProtectedChanged)
    backend.clickReplay(algarve, replays_backend.CTRL)
    assert [row["selected"] for row in model.rows] == [False, True]
    assert len(selection) == 1 and len(checked) == 1 and backend.checkedSummary == "2 · 65 MB"
    sums: list = []
    real = backend.checked_replays
    monkeypatch.setattr(backend, "checked_replays", lambda: sums.append(True) or real())
    for _ in range(5):  # summary read by bindings: sizes not summed again
        assert backend.checkedSummary == "2 · 65 MB" and backend.checkedCount == 2
    assert not sums
    backend.selectAllReplays()  # already all selected: count & size unchanged, not told
    assert len(checked) == 1
    backend.selectReplay(algarve)  # same replay clicked again: told (results page shows its session again)
    assert len(selection) == 2 and len(checked) == 2 and backend.checkedCount == 1
    backend.toggleProtected(algarve)
    assert backend.selectedProtected and len(protected) == 1 and len(selection) == 2
    backend.selectReplay(bahrain)
    assert not backend.selectedProtected and len(protected) == 2
    backend.toggleProtected(algarve)  # other replay: selected one unchanged, nothing told
    assert len(protected) == 2


# --- Copy progress throttled (one signal to the UI thread per change shown)
def test_progress_throttle_steps_interval_and_end():
    from neopedal.ui.quick.replay_files import PROGRESS_INTERVAL, ProgressThrottle

    told: list[float] = []
    now = [0.0]
    throttle = ProgressThrottle(told.append, clock=lambda: now[0])
    throttle(0.001)  # first: told
    throttle(0.002)  # same 0.5 % step
    now[0] += PROGRESS_INTERVAL / 2
    throttle(0.2)  # step moved, too soon
    now[0] += PROGRESS_INTERVAL
    throttle(0.3)
    throttle(0.4)  # too soon
    throttle(1.0)  # end: always told
    throttle(1.2)  # once (file grown during copy)
    assert told == [0.001, 0.3, 1.0]


def test_copy_progress_calls_throttled(tmp_path, monkeypatch):
    from neopedal.ui.quick import replay_files

    monkeypatch.setattr(replay_files, "CHUNK_SIZE", 100)
    folder, source = tmp_path / "Replays", tmp_path / "Downloads"
    folder.mkdir()
    source.mkdir()
    (source / "Spa R1 1.Vcr").write_bytes(b"x" * 100_000)  # 1000 chunks
    told: list[float] = []
    result = replay_files.copy_replays([str(source / "Spa R1 1.Vcr")], str(folder), told.append)
    assert result.added == ["Spa R1 1"] and told[0] == pytest.approx(0.001) and told[-1] == 1.0
    assert len(told) <= replay_files.PROGRESS_STEPS + 1 and told == sorted(told)


# --- QML: buttons kept by rows, markers kept, rows bind to roles
def test_panels_keep_rows_buttons_and_markers(replays_page):  # noqa: F811
    from PySide6.QtCore import qInstallMessageHandler

    def shown_buttons(tip_start: str = "", text: str = "") -> list:
        return [item for item in items_of(replays_page.view.rootObject())
                if item.metaObject().className().startswith("TpButton") and item.isVisible()
                and str(item.property("tip")).startswith(tip_start) and (not text or item.property("text") == text)]

    def marker_items() -> list:
        layer = next(item for item in items_of(replays_page.view.rootObject())
                     if item.objectName() == "incidentMarkers")
        return [item for item in layer.childItems() if item.metaObject().indexOfProperty("centerX") >= 0]

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        backend = answered(replays_page, GAME_ANSWERS)
        replays_page.resize(1400, 860)
        replays_page.show()
        pump(20)
        assert len(shown_buttons(text="Watch")) == 1  # selected replay row only (buttons of other rows hidden)
        timeline = next(item for item in items_of(replays_page.view.rootObject())
                        if item.metaObject().indexOfProperty("fullEnd") >= 0)
        assert timeline.property("fullEnd") == pytest.approx(backend.timelineEnd)
        markers = marker_items()
        assert len(markers) == 2 and timeline.markerAt(markers[0].property("centerX")
                                                       + timeline.property("pad"), timeline.property("railY"))
        pointers = {getCppPointer(item)[0] for item in markers}
        refresh(replays_page, answers_with(**{"/rest/watch/getIncidentsList/1": [*CONTACTS, NEW_CONTACT]}))
        pump()
        after = marker_items()
        assert len(after) == 3 and pointers <= {getCppPointer(item)[0] for item in after}  # dots kept
        key = backend.incidentRows.rows[0]["key"]
        backend.selectIncident(key)
        pump()
        assert [item.property("key") for item in marker_items() if item.property("selected")] == [key]
        assert timeline.labelOf(key).startswith("0:26:")
        backend.setPanel(1)  # standings: camera button on the selected row only
        pump(20)
        assert not shown_buttons("Camera on This Car")
        backend.selectCar("4")
        pump()
        assert len(shown_buttons("Camera on This Car")) == 1
    finally:
        qInstallMessageHandler(previous)
    qml = [text for text in messages if ".qml" in text]
    assert not qml, qml


def test_qml_rows_bind_to_roles():
    """No Loader made per hovered row, no per-row reading of backend selection or energy column"""
    texts = {name: (QML / folder / f"{name}.qml").read_text(encoding="utf-8") for folder, name in (
        ("director", "IncidentPanel"), ("director", "StandingsPanel"), ("analysis", "ReplayList"))}
    for name, text in texts.items():
        assert "sourceComponent: TpButton" not in text, name
        assert "required property bool selected" in text, name
    assert "=== replays.selectedIncident" not in texts["IncidentPanel"]
    assert not re.search(r"replays\.(timeline|drivers)\b", texts["IncidentPanel"])  # JS lists made per change
    assert "=== replays.selectedCar" not in texts["StandingsPanel"]
    assert texts["StandingsPanel"].count("replays.hasEnergy") == 1  # read once at panel root
    assert "=== replays.selectedReplay" not in texts["ReplayList"]
