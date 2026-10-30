"""Overlay audit 2026-10-29, group D: sectors, session, timing, track clock (findings 57-69), pace & track notes,
chat (findings 114-119)"""

import math
from time import time
from types import SimpleNamespace

import pytest

from neopedal import calculation as calc
from neopedal import realtime_state
from neopedal.calculation import sec2laptime
from neopedal.const_common import MAX_SECONDS
from neopedal.module import module_notes, module_sectors
from neopedal.module_info import NotesData, SectorData, minfo
from neopedal.userfile.track_notes import COLUMN_COMMENT, COLUMN_DISTANCE, COLUMN_PACENOTE, COLUMN_TRACKNOTE
from neopedal.widget._modern.base import NO_CLOCK
from tests.test_audit_sweep_fixes import reader, widgets  # noqa: F401  (fixture)
from tests.test_module_timing import tele  # noqa: F401  (fixture)
from tests.test_sectors_game_timing import cross, drive, lap, sector_data, shown  # noqa: F401  (fixture)


# --- Sectors: S3 set by game later than freeze duration still shown, tiles restored after it (finding 57, V4)
@pytest.mark.parametrize("modern", [True, False])
def test_sector3_set_late_still_shown(widgets, monkeypatch, sector_data, modern):  # noqa: F811
    widget = widgets("sectors", modern=modern, target_laptime="Theoretical", enable_all_time_best_sectors=False,
                     freeze_duration=3)
    reader(monkeypatch, "timing", "start", 0.0)
    data = sector_data
    data.deltaSectorBestTB[:] = [0.1, 0.2, 0.7]
    drive(widget, monkeypatch, data, 60.0, 2, 2)  # first update: synced
    reader(monkeypatch, "timing", "start", 90.0)
    drive(widget, monkeypatch, data, 90.5, 0, 2)  # line crossed, S3 not set yet
    drive(widget, monkeypatch, data, 94.0, 0, 2)  # freeze duration passed: best sectors shown meanwhile
    assert all(sec2laptime(best) in text for best, text in zip((30.0, 40.0, 20.0), shown(widget, modern)[0],
                                                                 strict=True))
    # Game sets S3 8 s after the line (module still waits for it): gap shown & frozen lap time
    data.sectorPrev[2] = 19.5
    data.deltaSectorBestTB[2] = -0.5
    data.sectorBestTB[2] = 19.5
    drive(widget, monkeypatch, data, 98.0, 0, 0)
    tiles, current = shown(widget, modern)
    assert "-0.500" in tiles[2]
    assert sec2laptime(89.5) in current
    # After freeze: best sectors back, with new best S3 (not old best kept for a whole lap)
    drive(widget, monkeypatch, data, 101.5, 0, 0)
    tiles, _ = shown(widget, modern)
    assert sec2laptime(19.5) in tiles[2]


# --- Sectors: resumed after pause, old gap never shown again nor time frozen (findings 59, 60)
@pytest.mark.parametrize("modern", [True, False])
def test_sectors_resume_without_old_gap(widgets, monkeypatch, sector_data, modern):  # noqa: F811
    widget = widgets("sectors", modern=modern, target_laptime="Theoretical", enable_all_time_best_sectors=False)
    reader(monkeypatch, "timing", "start", 0.0)
    data = sector_data
    data.deltaSectorBestTB[:] = [0.1, 0.4, 0.7]
    drive(widget, monkeypatch, data, 40.0, 1, 1)
    drive(widget, monkeypatch, data, 71.0, 2, 2)
    assert "+0.400" in shown(widget, modern)[0][1]
    widget.post_update()  # paused (garage), best sectors reloaded meanwhile
    data.sectorBestTB[:] = [29.0, 39.0, 19.0]
    drive(widget, monkeypatch, data, 300.0, 2, 2)
    tiles, _ = shown(widget, modern)
    assert all("+0.400" not in text for text in tiles)
    assert all(sec2laptime(best) in text for best, text in zip((29.0, 39.0, 19.0), tiles, strict=True))
    assert not widget.freeze_timer_start


# --- Sectors module: lap finished before load (back from garage) never taken as S3 (finding 58)
def test_sector3_not_from_lap_before_load(tele, tmp_path):  # noqa: F811
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    cross(tele, gen, 95.0, 70.0)  # loaded in S1, last lap (in lap, through pit lane) still reported by game
    assert session.sectorBestTB[2] == MAX_SECONDS and session.recordedIndex == -1
    lap(tele, gen, 30.0, 40.0)
    cross(tele, gen, 88.0, 70.0)
    assert session.sectorPrev == pytest.approx([30.0, 40.0, 18.0])
    assert session.recordedIndex == 0


# --- Running time formatted uncached: lap times of tables kept in cache (finding 61)
@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("name", ["timing", "sectors"])
def test_running_time_not_cached(widgets, monkeypatch, sector_data, modern, name):  # noqa: F811
    widget = widgets(name, modern=modern, **({"show_current": True, "show_estimated": True} if name == "timing" else {}))
    reader(monkeypatch, "timing", "start", 0.0)
    for elapsed in (10.0, 11.0):
        monkeypatch.setattr(minfo.delta, "lapTimeCurrent", elapsed)
        monkeypatch.setattr(minfo.delta, "lapTimeEstimated", elapsed + 80)
        drive(widget, monkeypatch, sector_data, elapsed, 0, 0)
    cached = calc.sec2laptime.cache_info().currsize
    for elapsed in (12.345, 13.456, 14.567):
        monkeypatch.setattr(minfo.delta, "lapTimeCurrent", elapsed)
        monkeypatch.setattr(minfo.delta, "lapTimeEstimated", elapsed + 80)
        drive(widget, monkeypatch, sector_data, elapsed, 0, 0)
    assert calc.sec2laptime.cache_info().currsize == cached


# --- Session: estimated time over 10 hours not cut, extra laps shown when changed while stopped (62, 64)
def session_texts(widget, modern: bool) -> list[str]:
    if modern:
        return [value.text for value in widget.state]
    return [bar.text for bar in (widget.bar_session_time, widget.bar_estimated_laps)]


@pytest.mark.parametrize("modern", [True, False])
def test_session_time_over_ten_hours(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("session", modern=modern, show_session_name=False, show_system_clock=False,
                     show_session_time=True, show_estimated_laps=True, show_predicted_extra_laps=True)
    reader(monkeypatch, "session", "remaining", 86000.0)
    monkeypatch.setattr(minfo.vehicles, "finishTimeOffset", 2000.0)
    monkeypatch.setattr(minfo.vehicles, "finishLapOffset", 0)
    widget.timerEvent(None)
    assert "~23:20:00" in session_texts(widget, modern)  # was ~23:20:0
    monkeypatch.setattr(minfo.vehicles, "finishLapOffset", 1)  # stopped: laps left unchanged
    widget.timerEvent(None)
    assert any(text.endswith("(+1)") for text in session_texts(widget, modern))


def test_system_clock_samples_cover_long_names():
    from neopedal.widget._common import system_clock_samples

    samples = system_clock_samples("%A %B %p")
    assert any(text.startswith("Wednesday September") for text in samples)
    assert {text.split()[-1] for text in samples} == {"AM", "PM"}
    assert system_clock_samples("%Q") == ("%Q",)


# --- Timing: session best cleared on new or restarted session (finding 65)
@pytest.mark.parametrize("modern", [True, False])
def test_session_best_cleared_on_new_session(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("timing", modern=modern, show_session_best=True, show_session_best_from_same_class_only=False)
    reader(monkeypatch, "vehicle", "total_vehicles", 1)
    reader(monkeypatch, "session", "identifier", (100, 0, 0))
    reader(monkeypatch, "session", "elapsed", 600.0)
    reader(monkeypatch, "timing", "best_laptime", 90.0)
    widget.timerEvent(None)
    assert widget.session_best.laptime == 90.0
    reader(monkeypatch, "session", "identifier", (204, 0, 0))  # next session (race)
    reader(monkeypatch, "timing", "best_laptime", 95.0)
    widget.timerEvent(None)
    assert widget.session_best.laptime == 95.0
    reader(monkeypatch, "session", "elapsed", 10.0)  # same session restarted
    reader(monkeypatch, "timing", "best_laptime", 97.0)
    widget.timerEvent(None)
    assert widget.session_best.laptime == 97.0


# --- Track clock: dashes without sun phases, phase color of period in progress in both designs (66, 69)
@pytest.mark.parametrize("modern", [True, False])
def test_track_clock_without_sun_phases(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("track_clock", modern=modern, show_sunlight_phase_countdown=True)
    reader(monkeypatch, "session", "track_time", 3600.0)
    monkeypatch.setattr(minfo.mapping, "sunlightPhases", None)
    widget.timerEvent(None)
    if modern:
        assert any(value.text == NO_CLOCK and not value.sub for value in widget.state)
    else:
        assert widget.bar_countdown.text == "--:--:--"


def test_track_clock_phase_colors_match():
    from neopedal.widget._modern.track_clock import PHASES

    night = {index for index, (_, is_night) in PHASES.items() if is_night}
    assert night == {0, 3}  # classic: night color before sunrise & midnight


def test_lmu_track_time_nan():
    from neopedal.adapter import lmu_reader

    session = lmu_reader.Session(SimpleNamespace(lmuScorInfo=SimpleNamespace(mTimeOfDay=math.nan)), None)
    assert session.track_time() == 0.0


# --- Pace & track notes (findings 114-117)
@pytest.fixture
def notes_reset(monkeypatch):
    for notes in (minfo.pacenotes, minfo.tracknotes):
        for data in (notes.out, notes.pit):
            monkeypatch.setattr(data, "currentNote", data.currentNote)
            monkeypatch.setattr(data, "nextNote", data.nextNote)
            monkeypatch.setattr(data, "currentIndex", data.currentIndex)
            data.reset()


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("name", ["pace_notes", "track_notes"])
def test_pit_lane_without_pit_notes(widgets, monkeypatch, notes_reset, name, modern):  # noqa: F811
    reader(monkeypatch, "vehicle", "in_pits", 1)
    reader(monkeypatch, "vehicle", "in_garage", False)
    widget = widgets(name, modern=modern, show_pit_notes_while_in_pit=True, enable_auto_hide_if_not_available=True)
    widget.timerEvent(None)
    assert widget.notes_hidden  # auto hidden in pit lane too
    widget = widgets(name, modern=modern, show_pit_notes_while_in_pit=True, enable_auto_hide_if_not_available=False)
    widget.timerEvent(None)
    assert not widget.notes_hidden
    notes = widget.notes_data()
    assert widget.note_text(notes.pit.currentNote, True) == "Pit Lane"


@pytest.mark.parametrize("name", ["pace_notes", "track_notes"])
def test_notes_default_texts_translated(widgets, monkeypatch, name):  # noqa: F811
    from neopedal.widget import track_notes

    monkeypatch.setattr(track_notes, "tr_overlay", lambda text: f"<{text}>")
    widget = widgets(name, modern=False, pit_comments_text="my comment")
    assert widget.pit_note_text == "<Pit Lane>" and widget.no_note_text == "<NOT AVAILABLE>"
    assert widget.pit_comment_text == "my comment"  # user text as it is


def test_single_note_shown_again_each_lap():
    output = NotesData()
    gen = module_notes.notes_selector(output, ({COLUMN_DISTANCE: 500.0, COLUMN_PACENOTE: "Only"},))
    indexes = []
    for position in (100.0, 600.0, 900.0, 50.0, 700.0, 20.0, 650.0):  # three laps
        gen.send(position)
        indexes.append(output.currentIndex)
        assert output.currentNote[COLUMN_PACENOTE] == "Only"
    # Index changes once per pass of the note (display duration & audio playback), not at line
    assert indexes == [0, -1, -1, -1, 0, 0, -1]


@pytest.mark.parametrize("modern", [True, False])
def test_single_note_display_duration_each_lap(widgets, monkeypatch, notes_reset, modern):  # noqa: F811
    reader(monkeypatch, "vehicle", "in_pits", 0)
    reader(monkeypatch, "vehicle", "in_garage", False)
    widget = widgets("track_notes", modern=modern, maximum_display_duration=5)
    gen = module_notes.notes_selector(minfo.tracknotes.out, ({COLUMN_DISTANCE: 500.0, COLUMN_TRACKNOTE: "T1"},))
    for position, elapsed, hidden in ((600.0, 10.0, False), (900.0, 20.0, True), (50.0, 70.0, True),
                                      (600.0, 110.0, False)):
        gen.send(position)
        reader(monkeypatch, "timing", "elapsed", elapsed)
        widget.timerEvent(None)
        assert widget.notes_hidden is hidden, position


def test_pace_notes_modern_card(widgets, monkeypatch, notes_reset):  # noqa: F811
    from neopedal.widget._modern.track_notes import Realtime as TrackNotesCard

    reader(monkeypatch, "vehicle", "in_pits", 0)
    minfo.pacenotes.out.currentNote = {COLUMN_DISTANCE: 100.0, COLUMN_PACENOTE: "3 Right", COLUMN_COMMENT: "Brake"}
    widget = widgets("pace_notes", modern=True, show_comments=True)
    assert isinstance(widget, TrackNotesCard)  # theme colors in light & dark themes, not restyled classic
    widget.timerEvent(None)
    assert widget.state[:2] == (("3 Right",), ("Brake",))


# --- Chat: long sender name never leaves no room for message, spectated driver not player (118, 119)
def test_chat_long_sender_name(widgets):  # noqa: F811
    widget = widgets("chat", modern=True, line_width=10)
    name = "Maximilian-Alexander Hohenberg"  # sender names up to 32 characters
    lines = widget.read_lines(((time(), f"{name}: hello there"),), time())
    assert widget.advance("name", lines[0].name) <= widget.text_w * 0.5 + 1
    assert lines[0].name != name and lines[0].text.startswith("he")  # was: no room left, word cut to nothing


def test_chat_spectated_driver_not_own(widgets, monkeypatch):  # noqa: F811
    widget = widgets("chat", modern=True)
    reader(monkeypatch, "vehicle", "driver_name", "M. Laurent")
    reader(monkeypatch, "session", "chat_messages", ((time(), "M. Laurent: sorry"),))
    monkeypatch.setattr(realtime_state, "spectating", True)
    widget.timerEvent(None)
    assert widget.state[0].kind != 1  # OWN
    monkeypatch.setattr(realtime_state, "spectating", False)
    widget.timerEvent(None)
    assert widget.state[0].kind == 1
