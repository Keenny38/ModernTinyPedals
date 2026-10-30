"""Overlay audit 2026-10-29, group A: delta graph, deltabest, deltabest extended, driver rank, gap trend, speed
delta & delta module (findings 1-20, 120, 121)"""

import math

import pytest

from neopedal.const_common import MAX_SECONDS
from neopedal.module_info import minfo
from tests.test_delta_session import delta_info, driver, overlays, wall_clock  # noqa: F401  (fixtures)
from tests.test_race_aid_widgets import field, make, set_reader  # noqa: F401  (fixture)


# --- Delta graph: out lap (no delta) still follows laps (finding 1)
def test_delta_trace_follows_laps_while_no_delta():
    from neopedal.widget.delta_graph import DeltaTrace

    trace = DeltaTrace(10)
    trace.update(5, 0.05, 0.1)
    trace.update(5, 0.95, 0.4)  # pit in lap
    trace.update(6, 0.05, math.nan)  # out lap: no delta, in lap becomes previous lap
    assert trace.previous[9] == 0.4 and all(math.isnan(value) for value in trace.current)
    trace.update(6, 0.95, math.nan)
    trace.update(7, 0.05, -0.2)  # flying lap: previous lap is the out lap (no trace), not 2 laps cleared
    assert all(math.isnan(value) for value in trace.previous) and trace.current[0] == -0.2
    assert trace.last_lap == 7


def test_delta_graph_classic_reading_not_overlapping(field):  # noqa: F811
    widget = make("delta_graph", False, display_width=40, show_delta_reading=True, decimal_places=3)
    assert widget.width() >= widget.text_cell_width(len(widget.label) + 4 + 4)  # label, space, +99.999
    widget.deleteLater()


# --- Never -0.000 (finding 120, 2)
def test_deltas_never_negative_zero(overlays, field, monkeypatch):  # noqa: F811
    from neopedal.widget.deltabest_extended import fitted_delta
    from neopedal.widget.gap_trend import GapSeries

    delta_info(monkeypatch)
    modern = overlays("deltabest", deltabest_source="Best", show_game_deltabest_if_available=False)
    assert modern.delta_text(-0.00001) == "+0.000"
    classic = make("deltabest", False, decimal_places=3)
    assert classic.delta_text(-0.00001) == "+0.000" and classic.delta_text(None) == "-"
    assert fitted_delta(-0.00001, 3, 6) == "+0.000"
    graph = make("delta_graph", False, decimal_places=2)
    assert graph.delta_text(round(-0.004, 2)) == "+0.00"
    series = GapSeries(4)
    for gap in (2.0, 2.0001):
        series.add(gap, 1)
    assert f"{series.rate():+z.2f}" == "+0.00"
    for widget in (classic, graph):
        widget.deleteLater()


# --- Deltabest: lap time difference after line against a comparable reference (findings 4, 9, 7)
@pytest.mark.parametrize("modern", [True, False])
def test_last_lap_difference_not_against_out_lap(overlays, monkeypatch, modern):  # noqa: F811
    # Flying lap under way after an out lap: last lap (out lap) not comparable
    delta_info(monkeypatch, lapTimeLast=160.0, hasLastLap=False)
    if modern:
        widget = overlays("deltabest", deltabest_source="Last", freeze_duration=3)
    else:
        widget = make("deltabest", False, deltabest_source="Last", freeze_duration=3)
    widget.timerEvent(None)
    assert widget.last_laptime == 0.0
    # Line: flying lap of 98 s comparable, shown frozen: none (reference was the out lap), not -62
    delta_info(monkeypatch, lapTimeCurrent=1.0, lapTimeLast=98.0, hasLastLap=True)
    widget.timerEvent(None)
    value = widget.state[0] if modern else widget.delta_best
    assert value is None


def test_extended_last_column_not_against_out_lap(overlays, monkeypatch):  # noqa: F811
    delta_info(monkeypatch, lapTimeLast=160.0, hasLastLap=False)
    widget = overlays("deltabest_extended", show_deltalast=True, show_all_time_deltabest=True,
                      show_game_deltabest_if_available=False)
    widget.timerEvent(None)
    delta_info(monkeypatch, lapTimeCurrent=1.0, lapTimeLast=98.0, hasLastLap=True)
    widget.timerEvent(None)
    texts = dict(zip(widget.keys, (value.text for value in widget.state)))
    assert texts["all_time_deltabest"] == "+1.000"  # 98 - 97 best
    assert texts["deltalast"] != "-62.000" and not texts["deltalast"].startswith(("+", "-"))
    classic = make("deltabest_extended", False, show_deltalast=True)
    delta_info(monkeypatch, lapTimeLast=160.0, hasLastLap=False)
    classic.timerEvent(None)
    delta_info(monkeypatch, lapTimeCurrent=1.0, lapTimeLast=98.0, hasLastLap=True)
    classic.timerEvent(None)
    assert classic.bar_labest.text.endswith(" -")
    classic.deleteLater()


@pytest.mark.parametrize("modern", [True, False])
def test_game_delta_frozen_against_game_best(overlays, monkeypatch, modern):  # noqa: F811
    """Live game delta compares against game best lap: frozen value too (no jump at line)"""
    delta_info(monkeypatch)  # app best 97.0
    set_reader(monkeypatch, "timing", "delta_best", -0.3)
    set_reader(monkeypatch, "timing", "best_laptime", 97.5)
    if modern:
        widget = overlays("deltabest", deltabest_source="Best", show_game_deltabest_if_available=True)
    else:
        widget = make("deltabest", False, deltabest_source="Best", show_game_deltabest_if_available=True)
    widget.timerEvent(None)
    delta_info(monkeypatch, lapTimeCurrent=1.0, lapTimeLast=97.2)
    widget.timerEvent(None)
    value = widget.state[0] if modern else widget.delta_best
    assert value == pytest.approx(-0.3)
    # Game gives no delta (rF2): app reference
    set_reader(monkeypatch, "timing", "delta_best", 0.0)
    widget.new_lap = True
    delta_info(monkeypatch)
    widget.timerEvent(None)
    assert widget.last_laptime == 97.0


def test_classic_deltabest_repaints_on_shown_change_only(field, monkeypatch):  # noqa: F811
    widget = make("deltabest", False, deltabest_source="Best", decimal_places=3,
                  show_game_deltabest_if_available=False, show_delta_bar=True)
    delta_info(monkeypatch, deltaBest=0.40001)
    painted = []
    monkeypatch.setattr(widget, "update", lambda: painted.append(1))
    widget.timerEvent(None)
    delta_info(monkeypatch, deltaBest=0.40002)  # same text, bar moved less than a pixel
    widget.timerEvent(None)
    assert len(painted) == 1
    delta_info(monkeypatch, deltaBest=-0.6)  # gain: bar right of center
    widget.timerEvent(None)
    assert len(painted) == 2
    assert widget.rect_deltapos.normalized().width() >= 0
    monkeypatch.undo()
    widget.grab()
    widget.deleteLater()


# --- Deltabest extended classic: 10 s or more rounded, not cut (finding 10); redraw on text change (11)
def test_extended_wide_delta_rounded(field, monkeypatch):  # noqa: F811
    from neopedal.widget.deltabest_extended import fitted_delta

    assert fitted_delta(12.346, 3, 6) == "+12.35"
    assert fitted_delta(-1.234, 3, 6) == "-1.234"
    assert fitted_delta(99.999, 3, 6) == "+100.0"
    widget = make("deltabest_extended", False, show_all_time_deltabest=True, decimal_places=3)
    delta_info(monkeypatch, deltaBest=12.346)
    widget.timerEvent(None)
    assert widget.bar_atbest.text.endswith("+12.35")
    redrawn = []
    monkeypatch.setattr(widget.bar_atbest, "update", lambda: redrawn.append(1))
    delta_info(monkeypatch, deltaBest=12.3461)  # same text: not redrawn
    widget.timerEvent(None)
    assert not redrawn
    monkeypatch.undo()
    widget.deleteLater()


# --- Driver rank (findings 12, 13)
def test_driver_rank_limits_colors_and_width(field, monkeypatch):  # noqa: F811
    from neopedal.api_control import api

    monkeypatch.setattr(api.read.session, "cut_points", lambda *args: 0.0)
    monkeypatch.setattr(api.read.session, "limits_points", lambda: 1.0)
    monkeypatch.setattr(api.read.session, "in_race", lambda: True)
    modern = make("driver_rank", True, show_track_limits=True)
    value = modern.limits_value(0.0, 1.0)
    assert value.color != modern.theme.negative  # no point yet: not red
    assert modern.limits_value(0.5, 1.0).color == modern.theme.negative
    classic = make("driver_rank", False, show_progress=True, show_track_limits=True)
    assert classic.value_width == 10  # "10.25/12.5" fits
    classic.update_text(classic.bars["track_limits"], "10.25/12.5", classic.prefixes["track_limits"])
    assert classic.bars["track_limits"].text.endswith(" 10.25/12.5")
    for widget in (modern, classic):
        widget.deleteLater()


# --- Gap trend (findings 14, 15, 16, 17, 18)
@pytest.fixture
def gap_game(field, monkeypatch):  # noqa: F811
    game = {"lap": 0, "session": 360001}
    set_reader(monkeypatch, "lap", "completed_laps", lambda *args, **kwargs: game["lap"])
    set_reader(monkeypatch, "vehicle", "slot_id", lambda index=None: index)
    set_reader(monkeypatch, "session", "identifier", lambda *args: (game["session"], 100, game["lap"]))
    return game


def test_gap_trend_first_reading_not_recorded(gap_game, field):  # noqa: F811
    widget = make("gap_trend", True)
    widget.timerEvent(None)  # on grid / out of garage: no end of lap gap
    assert not widget.series[0].samples
    gap_game["lap"] = 1
    widget.timerEvent(None)
    assert len(widget.series[0].samples) == 1
    widget.deleteLater()


def test_gap_trend_pit_lap_left_out(gap_game, field):  # noqa: F811
    widget = make("gap_trend", True, show_gaps_in_class=False)
    cars = field.dataSet
    player = cars[field.playerIndex]
    widget.timerEvent(None)
    for step in range(3):
        player.gapBehindNext = 3.0 - step * 0.5
        gap_game["lap"] += 1
        widget.timerEvent(None)
    assert widget.read_gaps()[0].rate == "-0.50"
    player.inPit = 1  # pit stop during lap
    widget.timerEvent(None)
    player.inPit = 0
    player.gapBehindNext = 30.0
    gap_game["lap"] += 1
    widget.timerEvent(None)
    assert math.isnan(widget.series[0].samples[-1][0])
    assert widget.read_gaps()[0].rate == chr(0x2013)  # trend restarts, stop not counted as change per lap
    for gap in (29.5, 29.0):
        player.gapBehindNext = gap
        gap_game["lap"] += 1
        widget.timerEvent(None)
    assert widget.read_gaps()[0].rate == "-0.50"
    # Car ahead stops: its gap left out too
    cars[field.playerIndex - 1].inPit = 1
    widget.timerEvent(None)
    cars[field.playerIndex - 1].inPit = 0
    gap_game["lap"] += 1
    widget.timerEvent(None)
    assert math.isnan(widget.series[0].samples[-1][0])
    widget.deleteLater()


def test_gap_trend_new_session_clears_history(gap_game, field):  # noqa: F811
    widget = make("gap_trend", False)
    widget.timerEvent(None)
    for _ in range(3):
        gap_game["lap"] += 1
        widget.timerEvent(None)
    assert widget.series[0].samples
    gap_game["session"] = 7200002  # other session, joined at a later lap
    gap_game["lap"] = 9
    widget.timerEvent(None)
    assert not widget.series[0].samples
    widget.deleteLater()


def test_gap_trend_classic_columns_fit(field):  # noqa: F811
    widget = make("gap_trend", False, decimal_places=3, show_closing_rate=True)
    font_width = widget.font_m.width
    assert widget.cells["gap"][0].width() >= font_width * len("999.900")
    assert widget.cells["rate"][0].width() >= font_width * len("Per lap")
    widget.deleteLater()


@pytest.mark.parametrize("modern", [True, False])
def test_gap_trend_preview_has_trend(ui_env, bundled_fonts, modern):
    from neopedal import demo_data
    from neopedal.setting import cfg
    from neopedal.template.widget import registry
    from neopedal.ui.widget_preview import _with_preview_widget

    assert registry.demo_names(registry.DEMO_GAPS) == ("gap_trend",) == demo_data.GAP_WIDGETS
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    rows = _with_preview_widget(cfg, "gap_trend", dict(cfg.user.setting["gap_trend"]), 1.0,
                                lambda widget: (widget.read_gaps(), widget.charts))
    (ahead, behind), charts = rows
    assert ahead.rate.startswith("-") and behind.rate.startswith("+")  # catching car ahead, pulling away
    assert all(chart.lines for chart in charts)


def test_gap_replay_puts_state_back(ui_env):
    from neopedal import demo_data
    from neopedal.setting import cfg

    session = demo_data.DemoSession(cfg.default.setting["standings"])
    scor = session.data.scoring.vehScoringInfo[demo_data.PLAYER]
    player = session.minfo.vehicles.dataSet[demo_data.PLAYER]
    before = (scor.mTotalLaps, player.gapBehindNext, player.gapBehindNextInClass)
    updates = []
    demo_data.replay_gaps(object(), session.data, session.minfo, updates.append)
    assert len(updates) == demo_data.GAP_LAPS + 1
    assert (scor.mTotalLaps, player.gapBehindNext, player.gapBehindNextInClass) == before


# --- Speed delta (findings 19, 20)
@pytest.mark.parametrize("modern", [True, False])
def test_speed_delta_unknown_reference_speed_dash(field, monkeypatch, modern):  # noqa: F811
    delta_info(monkeypatch, speedDeltaBest=math.nan, speedDeltaSession=0.0)
    widget = make("speed_delta", modern, show_all_time_best=True, show_session_best=True)
    values = widget.speeds.read()
    assert values["all_time_best"] is None  # unknown here: dash, not +0.0
    assert values["session_best"] == 0.0
    if not modern:  # first difference of 0 drawn (not kept as dash)
        widget.timerEvent(None)
        assert widget.bars["session_best"].last == 0.0 and "+0" in widget.bars["session_best"].text
        assert widget.bars["all_time_best"].last is None
    widget.deleteLater()


# --- Delta module: pit lane laps never references (finding 121)
def test_pit_lap_never_stint_or_session_best(driver):  # noqa: F811
    for laptime in (100.0, 98.0, 99.0):  # first lap partial (not timed)
        driver.lap(laptime)
    driver.pit_stop()  # early in lap: lap now completed went through pit lane
    driver.lap(97.0)  # pit lap with a valid time from game (even faster): not a reference
    assert driver.bests() == (98.0, MAX_SECONDS) and driver.output.lapTimeBest == 98.0
    driver.lap(99.5)  # first flying lap of stint
    assert driver.bests() == (98.0, 99.5)
    driver.lap(97.5)
    assert driver.bests() == (97.5, 97.5) and driver.output.lapTimeBest == 97.5


def test_speed_delta_unknown_without_reference(driver):  # noqa: F811
    assert math.isnan(driver.output.speedDeltaBest)  # no reference lap yet: unknown, not 0
    assert minfo.delta is not driver.output
