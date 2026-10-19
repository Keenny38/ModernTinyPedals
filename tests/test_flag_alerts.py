"""Flag overlay: penalty, last lap, heavy damage, blue flag gap, speed limiter against pit speed limit (pit lane
driven without limiter), alert flash, most urgent first order, chip width, live size fitted to chips shown

Widgets are built on default settings (ui_env) with a neutral API reader. Nothing is ever asked to a real game.
"""

import pytest

from neopedal import realtime_state
from neopedal.module_info import minfo
from neopedal.penalty_info import Penalty
from neopedal.widget.flag import (
    LIMITER_HIDDEN,
    LIMITER_OFF,
    LIMITER_ON,
    LIMITER_OVER,
    PitLimiterWatch,
    heavy_damage,
    on_last_lap,
    pending_penalty,
)
from tests.test_modern_overlays_more import reader, update
from tests.test_modern_overlays_more import widgets as widgets  # fixture


@pytest.fixture(autouse=True)
def keep_minfo(ui_env, monkeypatch):
    """Neutral API reader, module outputs set by tests restored after"""
    monkeypatch.setattr(minfo.mapping, "pitSpeedLimit", 0.0)
    monkeypatch.setattr(minfo.vehicles, "finishTimeOffset", 0.0)
    monkeypatch.setattr(minfo.vehicles, "finishLapOffset", 0.0)


def chips(widget) -> dict:
    return {chip.key: chip for chip in widget.state}


# --- Penalty
def test_penalty_to_serve(monkeypatch):
    assert pending_penalty() == ""
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Stop/Go", 10))
    assert pending_penalty() == "SG10"
    reader(monkeypatch, "vehicle", "penalty", Penalty(2, "Drive Thru", 0))
    assert pending_penalty() == "DT\u00d72"
    reader(monkeypatch, "vehicle", "penalty", Penalty())  # results stream unread (rF2): count of game
    reader(monkeypatch, "vehicle", "number_penalties", 1)
    assert pending_penalty() == "PEN"
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Stop/Go", 10, disqualified=True))
    assert pending_penalty() == ""  # finish state shows DSQ


def test_penalty_chip_and_classic_bar(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Stop/Go", 10))
    widget = widgets("flag")
    update(widget)
    chip = chips(widget)["penalty"]
    assert (chip.caption, chip.value, chip.color, chip.alert) == ("Penalty", "SG10", "negative", True)
    classic = widgets("flag", modern=False)
    classic.show()
    classic.timerEvent(None)
    assert classic.bar_penalty.text == "PENSG10" and not classic.bar_penalty.isHidden()
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Drive Thru", 0))
    classic.timerEvent(None)
    assert classic.bar_penalty.text == "PEN DT"
    reader(monkeypatch, "vehicle", "penalty", Penalty())
    classic.timerEvent(None)
    assert classic.bar_penalty.isHidden()
    classic.hide()


# --- Last lap
def completed_laps(monkeypatch, laps: int):
    """Laps completed (scoring), lap number (telemetry: lap driven)"""
    reader(monkeypatch, "lap", "completed_laps", laps)
    reader(monkeypatch, "lap", "number", laps)


def lap_race(monkeypatch, laps: int):
    reader(monkeypatch, "session", "in_race", True)
    reader(monkeypatch, "session", "finish_type", True)
    completed_laps(monkeypatch, laps)
    reader(monkeypatch, "lap", "maximum", 20)
    reader(monkeypatch, "lap", "progress", 0.5)
    reader(monkeypatch, "timing", "current_laptime", 50.0)


def test_last_lap(monkeypatch):
    lap_race(monkeypatch, 18)
    assert not on_last_lap(True)
    lap_race(monkeypatch, 19)  # 19 laps done of 20: lap ends with the flag
    assert on_last_lap(True)
    assert not on_last_lap(False)  # not a race
    reader(monkeypatch, "vehicle", "finish_state", 1)
    assert not on_last_lap(True)  # finished


def test_last_lap_timed_race(monkeypatch):
    """Timed race: timer ends during this lap (100 s pace), finish line crossed after"""
    reader(monkeypatch, "session", "in_race", True)
    reader(monkeypatch, "session", "finish_type", False)
    completed_laps(monkeypatch, 5)
    reader(monkeypatch, "lap", "progress", 0.5)
    reader(monkeypatch, "timing", "current_laptime", 50.0)
    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)
    reader(monkeypatch, "session", "remaining", 30.0)
    assert on_last_lap(True)
    reader(monkeypatch, "session", "remaining", 130.0)
    assert not on_last_lap(True)


def test_last_lap_chip(widgets, monkeypatch):
    lap_race(monkeypatch, 19)
    widget = widgets("flag")
    update(widget)
    chip = chips(widget)["last_lap"]
    assert (chip.caption, chip.value, chip.color) == ("Session", "Last lap", "text")
    classic = widgets("flag", modern=False)
    classic.show()
    classic.timerEvent(None)
    assert classic.bar_last_lap.text == "LAST" and not classic.bar_last_lap.isHidden()
    classic.hide()


# --- Heavy damage
def test_heavy_damage(monkeypatch):
    assert heavy_damage() is None
    reader(monkeypatch, "vehicle", "damage_severity", (1, 1, 0, 0, 0, 0, 1, 0))  # light dents
    assert heavy_damage() is None
    reader(monkeypatch, "vehicle", "damage_severity", (2, 1, 0, 0, 0, 0, 1, 0))
    reader(monkeypatch, "vehicle", "aero_damage", 0.35)
    assert heavy_damage() == 0.35
    reader(monkeypatch, "vehicle", "damage_severity", (0,) * 8)
    reader(monkeypatch, "wheel", "is_detached", (False, True, False, False))
    reader(monkeypatch, "vehicle", "aero_damage", -1.0)  # unavailable
    assert heavy_damage() == -1.0


def test_damage_chip_and_classic_bar(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "damage_severity", (2, 0, 0, 0, 0, 0, 0, 0))
    reader(monkeypatch, "vehicle", "aero_damage", 0.35)
    widget = widgets("flag")
    update(widget)
    assert chips(widget)["damage"].value == "35%"
    classic = widgets("flag", modern=False)
    classic.show()
    classic.timerEvent(None)
    assert classic.bar_damage.text == "DMG 35%"
    reader(monkeypatch, "vehicle", "aero_damage", 0.0)  # wheel or body only
    update(widget)
    classic.timerEvent(None)
    assert chips(widget)["damage"].value == "Heavy" and classic.bar_damage.text == "DMG"
    classic.hide()


# --- Blue flag: gap of car lapping
def test_blue_flag_gap(widgets, monkeypatch):
    reader(monkeypatch, "session", "blue_flag", True)
    minfo.vehicles.nearestBlueClass = "Test Class"  # no class style: name as is
    minfo.vehicles.nearestTraffic = 0.84
    widget = widgets("flag")
    update(widget)
    chip = chips(widget)["blue_flag"]
    assert (chip.caption, chip.value) == ("Test Class", "0.8s")  # class on caption: value never cut
    classic = widgets("flag", modern=False)
    assert classic.blue_flag_text(12.0) == "Test0.8"
    minfo.vehicles.nearestTraffic = 99.0  # too far: time under blue flag
    update(widget)
    assert chips(widget)["blue_flag"].value == "0s"
    assert classic.blue_flag_text(12.0) == "Test 12"
    minfo.vehicles.nearestTraffic = 0.84
    no_gap = widgets("flag", show_blue_flag_gap=False)
    update(no_gap)
    assert chips(no_gap)["blue_flag"].value == "0s"


# --- Speed limiter
def pit_lane(monkeypatch, in_lane: bool, limiter: bool, speed: float):
    reader(monkeypatch, "vehicle", "in_paddock", 1 if in_lane else 0)
    reader(monkeypatch, "switch", "speed_limiter", int(limiter))
    reader(monkeypatch, "switch", "speed_limiter_available", True)
    reader(monkeypatch, "vehicle", "speed", speed)


def test_pit_limiter_watch(monkeypatch):
    watch = PitLimiterWatch()
    pit_lane(monkeypatch, False, False, 60.0)
    assert watch.update() == LIMITER_HIDDEN
    pit_lane(monkeypatch, True, False, 30.0)  # pit lane entered without limiter
    assert watch.update() == LIMITER_OFF
    pit_lane(monkeypatch, True, True, 25.0)  # switched on, still over limit
    minfo.mapping.pitSpeedLimit = 22.2
    assert watch.update() == LIMITER_OVER
    pit_lane(monkeypatch, True, True, 22.3)  # limiter oscillation tolerated
    assert watch.update() == LIMITER_ON
    pit_lane(monkeypatch, True, False, 25.0)  # released at lane exit: no warning
    assert watch.update() == LIMITER_HIDDEN
    pit_lane(monkeypatch, False, False, 40.0)
    assert watch.update() == LIMITER_HIDDEN
    pit_lane(monkeypatch, True, False, 0.5)  # standing in lane
    assert watch.update() == LIMITER_HIDDEN
    pit_lane(monkeypatch, True, False, 20.0)
    reader(monkeypatch, "switch", "speed_limiter_available", False)  # car without limiter
    assert watch.update() == LIMITER_HIDDEN


def test_limiter_chip_against_pit_speed_limit(widgets, monkeypatch):
    widget = widgets("flag")
    pit_lane(monkeypatch, True, False, 30.0)
    update(widget)
    chip = chips(widget)["speed_limiter"]
    assert (chip.value, chip.color, chip.alert) == ("Off", "negative", True)
    minfo.mapping.pitSpeedLimit = 22.2
    pit_lane(monkeypatch, True, True, 22.0)
    update(widget)
    chip = chips(widget)["speed_limiter"]
    assert (chip.value, chip.color, chip.alert) == ("-0.72", "positive", False)  # km/h under limit
    pit_lane(monkeypatch, True, True, 25.0)
    update(widget)
    chip = chips(widget)["speed_limiter"]
    assert (chip.value, chip.color, chip.alert) == ("+10.08", "negative", True)
    speed = widgets("flag", show_speed_limit_difference=False)
    update(speed)
    assert chips(speed)["speed_limiter"].value == "90.00"
    no_warning = widgets("flag", show_speed_limiter_off_warning=False)
    pit_lane(monkeypatch, True, False, 30.0)
    update(no_warning)
    assert "speed_limiter" not in chips(no_warning)


def test_classic_limiter_colors_and_texts(widgets, monkeypatch):
    widget = widgets("flag", modern=False)
    widget.show()
    minfo.mapping.pitSpeedLimit = 22.2
    pit_lane(monkeypatch, True, True, 22.0)
    widget.timerEvent(None)
    bar = widget.bar_limiter
    assert bar.text == "L -0.72" and bar.bg == widget.wcfg["background_color_speed_limiter"]
    pit_lane(monkeypatch, True, True, 25.0)
    widget.timerEvent(None)
    assert bar.text == "L+10.08" and bar.bg == widget.wcfg["background_color_speed_limiter_over"]
    pit_lane(monkeypatch, False, False, 25.0)
    widget.timerEvent(None)
    assert bar.isHidden()
    pit_lane(monkeypatch, True, False, 25.0)
    widget.timerEvent(None)
    assert bar.text == "NO LIM" and bar.bg == widget.wcfg["background_color_speed_limiter_over"]
    assert not bar.isHidden()
    widget.hide()


# --- Yellow flag arrow, pit closed text, sector yellow race only
def test_yellow_flag_behind_arrow(widgets, monkeypatch):
    reader(monkeypatch, "session", "yellow_flag", True)
    minfo.vehicles.nearestYellowAhead = 9999.0
    minfo.vehicles.nearestYellowBehind = -30.0
    widget = widgets("flag")
    update(widget)
    assert chips(widget)["yellow_flag"].value == "▼ 30m"


def test_pit_closed_custom_text(widgets, monkeypatch):
    widget = widgets("flag", pit_closed_text="NO PIT")
    reader(monkeypatch, "vehicle", "in_pits", True)
    reader(monkeypatch, "timing", "elapsed", 10.0)
    update(widget)
    reader(monkeypatch, "timing", "elapsed", 11.0)
    update(widget)
    chip = chips(widget)["pit_timer"]
    assert (chip.caption, chip.value) == ("NO PIT", "Closed")


def test_sector_yellow_own_race_only_option(widgets, monkeypatch):
    reader(monkeypatch, "session", "sector_yellow_flags", (False, True, False))
    widget = widgets("flag", show_yellow_flag_for_race_only=True)  # not race: yellow flag option no longer used
    update(widget)
    assert chips(widget)["sector_yellow_flags"].value == "S2"
    race_only = widgets("flag", show_sector_yellow_flags_for_race_only=True)
    update(race_only)
    assert "sector_yellow_flags" not in chips(race_only)


def test_sector_yellow_race_only_migrated():
    from neopedal.setting_preupdate import preupdate_user_setting

    user = {"flag": {"show_yellow_flag_for_race_only": True}}
    preupdate_user_setting((2, 51, 1), user)
    assert user["flag"]["show_sector_yellow_flags_for_race_only"] is True
    user = {"flag": {"show_yellow_flag_for_race_only": True, "show_sector_yellow_flags_for_race_only": False}}
    preupdate_user_setting((2, 51, 1), user)
    assert user["flag"]["show_sector_yellow_flags_for_race_only"] is False  # set by user: kept


# --- Alert flash, urgency order
def test_alert_flashes_when_raised(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "repair_time", 20.0)  # no alert
    widget = widgets("flag", new_flag_flash_duration=1.0)
    clock = {"now": 100.0}
    widget.clock = lambda: clock["now"]
    update(widget)
    assert not widget.state[0].flash  # picture (overlay not started): never
    widget.overlay_started = True
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Drive Thru", 0))
    update(widget)
    assert chips(widget)["penalty"].flash and not chips(widget)["scheduled_repairs"].flash
    clock["now"] = 100.3  # second flash period: normal colors
    update(widget)
    assert not chips(widget)["penalty"].flash
    clock["now"] = 100.6
    update(widget)
    assert chips(widget)["penalty"].flash
    clock["now"] = 101.1  # flash over
    update(widget)
    assert not chips(widget)["penalty"].flash
    reader(monkeypatch, "vehicle", "penalty", Penalty())
    update(widget)
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Drive Thru", 0))
    update(widget)
    assert chips(widget)["penalty"].flash  # raised again
    widget.overlay_started = False


def test_flash_off(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Drive Thru", 0))
    widget = widgets("flag", enable_new_flag_flash=False)
    widget.overlay_started = True
    update(widget)
    assert not chips(widget)["penalty"].flash
    widget.overlay_started = False


def test_urgency_order(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "repair_time", 20.0)
    reader(monkeypatch, "session", "yellow_flag_state", 7)
    reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Drive Thru", 0))
    widget = widgets("flag")
    update(widget)
    assert [chip.key for chip in widget.state] == ["scheduled_repairs", "full_course_yellow", "penalty"]
    urgent = widgets("flag", enable_urgency_order=True)
    update(urgent)
    assert [chip.key for chip in urgent.state] == ["full_course_yellow", "penalty", "scheduled_repairs"]


# --- Chip width, live size
def test_chip_fits_three_decimal_speed(widgets):
    widget = widgets("flag", decimal_places_speed=3)
    assert widget.text_width("strong", "888.888") <= widget.chip_w - widget.pad * 2
    assert widget.text_width("strong", "+88.888") <= widget.chip_w - widget.pad * 2


def test_live_size_fits_chips_shown(widgets, monkeypatch):
    widget = widgets("flag")
    full = widget.height()
    assert full == pytest.approx(widget.slots_size(15)[1], abs=1)
    update(widget)
    assert widget.height() == full  # picture (not started): every chip slot
    widget.overlay_started = True
    update(widget)
    assert widget.height() == pytest.approx(widget.chip_h, abs=1)  # nothing shown: one slot
    reader(monkeypatch, "vehicle", "repair_time", 20.0)
    reader(monkeypatch, "session", "yellow_flag_state", 4)
    update(widget)
    assert widget.height() == pytest.approx(widget.slots_size(2)[1], abs=1)
    monkeypatch.setattr(realtime_state, "editing", True)
    widget.should_hide()  # edit mode started (in garage, no update): every slot to place it
    assert widget.height() == full
    monkeypatch.setattr(realtime_state, "editing", False)
    widget.should_hide()
    assert widget.height() == pytest.approx(widget.slots_size(2)[1], abs=1)
    widget.overlay_started = False


# --- Sector yellow flags: game order
def test_sector_flag_order_seen_in_game():
    """LMU: game index 0 = sector 1 (shared memory & REST), not vehicle sector order (index 0 = sector 3)"""
    from neopedal.process.game_info import sector_yellow_flags
    from tests.test_readers import lmu_api

    sim, data = lmu_api()
    data.scoring.scoringInfo.mSectorFlag[0] = 1
    assert sim.reader().session.sector_yellow_flags() == (True, False, False)
    assert sector_yellow_flags(["YELLOW", "UNKNOWN", "UNKNOWN"]) == (True, False, False)
    assert sector_yellow_flags(["UNKNOWN", "YELLOW", "UNKNOWN"]) == (False, True, False)
    assert sector_yellow_flags(["UNKNOWN", "UNKNOWN", "YELLOW"]) == (False, False, True)
    assert sector_yellow_flags(None) == ()
