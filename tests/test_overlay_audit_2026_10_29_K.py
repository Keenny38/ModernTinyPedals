"""Overlay audit 2026-10-29, group K: tyre carcass, inner layer, temperature, temp trend, pressure, wear, overview,
load & tyre wear module (findings 71-85, 105-108)"""

import pytest

from neopedal import realtime_state
from neopedal.module_info import WheelsInfo, minfo
from neopedal.setting import cfg
from tests.test_module_wheels_wear import drive_lap, tele  # noqa: F401  (fixture)
from tests.test_race_aid_widgets import field, make, set_reader  # noqa: F401  (fixture)

COMPOUNDS_A = ("Hypercar - Medium",) * 4
COMPOUNDS_B = ("Hypercar - Soft",) * 4
TEMPS = (85.3, 86.1, 82.4, 83.0)


def tyre_readers(monkeypatch, compounds=COMPOUNDS_A, in_pits=False, temps=TEMPS, pressure=(175.3,) * 4):
    set_reader(monkeypatch, "vehicle", "in_pits", in_pits)
    set_reader(monkeypatch, "tyre", "compound_class", compounds)
    for name in ("surface_temperature_avg", "inner_temperature_avg", "carcass_temperature"):
        set_reader(monkeypatch, "tyre", name, temps)
    for name in ("surface_temperature_ico", "inner_temperature_ico"):
        set_reader(monkeypatch, "tyre", name, tuple(value for value in temps for _ in range(3)))
    set_reader(monkeypatch, "tyre", "pressure", pressure)
    set_reader(monkeypatch, "tyre", "optimal_temperature", (0.0,) * 4)


def compounds_shown(widget) -> tuple[str, ...]:
    """Compounds read by widget (modern: compound tracker, classic: last read)"""
    tracker = getattr(widget, "compounds", None)
    return tracker.names if tracker is not None else widget.last_compounds


# --- Compounds & heatmap read again for another followed car (finding 105, P11)
@pytest.mark.parametrize("name", ["tyre_temperature", "tyre_inner_layer", "tyre_carcass", "tyre_pressure",
                                  "tyre_overview", "tyre_temp_trend"])
@pytest.mark.parametrize("modern", [True, False])
def test_compounds_follow_spectated_car(field, monkeypatch, name, modern):  # noqa: F811
    monkeypatch.setattr(realtime_state, "resets", 5)
    tyre_readers(monkeypatch)
    widget = make(name, modern, show_tyre_compound=True) if name != "tyre_temp_trend" else make(name, modern)
    widget.timerEvent(None)
    assert compounds_shown(widget) == COMPOUNDS_A
    tyre_readers(monkeypatch, COMPOUNDS_B)  # other car followed, on track
    widget.timerEvent(None)
    assert compounds_shown(widget) == COMPOUNDS_A  # read only in pits (no reset yet)
    monkeypatch.setattr(realtime_state, "resets", 6)  # followed car changed (game sync)
    widget.timerEvent(None)
    assert compounds_shown(widget) == COMPOUNDS_B
    widget.deleteLater()


def test_auto_heatmap_follows_spectated_car(field, monkeypatch):  # noqa: F811
    from neopedal.userfile.heatmap import select_tyre_heatmap_name

    monkeypatch.setattr(realtime_state, "resets", 1)
    tyre_readers(monkeypatch)
    widget = make("tyre_temperature", False, enable_heatmap_auto_matching=True)
    widget.timerEvent(None)
    calls = []
    monkeypatch.setattr(widget, "update_heatmap", lambda compound, index: calls.append(compound))
    tyre_readers(monkeypatch, COMPOUNDS_B)
    monkeypatch.setattr(realtime_state, "resets", 2)
    widget.timerEvent(None)
    assert calls == list(COMPOUNDS_B)
    assert select_tyre_heatmap_name(COMPOUNDS_B[0])  # heatmap of new compound exists (default if none set)
    widget.deleteLater()


# --- Tyre wear per lap after followed car change: module reset proven (finding 106, P12)
def test_tyre_wear_reset_on_followed_car_change(tele):  # noqa: F811
    from neopedal.module.module_wheels import calc_tyre_wear

    output = WheelsInfo()
    gen = calc_tyre_wear(output, min_delta_distance=50, lock_threshold=-0.2)
    wear = drive_lap(tele, gen, 0.0, 1.0, 2.0, "tyre.wear", 100)
    drive_lap(tele, gen, 91.0, wear, 2.0, "tyre.wear", 100)
    assert output.estimatedTreadWear[0] == pytest.approx(2.0, abs=0.1)
    # Spectated car changed: other car, more worn (80% tread), mid lap; game sync bumped realtime_state.resets,
    # module_wheels sends it to the generator
    tele.update({"timing.start": 500.0, "timing.current_laptime": 40.0, "lap.distance": 2000.0,
                 "lap.progress": 0.5, "tyre.wear": (0.80,) * 4})
    gen.send(1)
    assert output.currentLapTreadWear[0] == 0.0  # 16% tread difference between cars not counted as wear
    assert output.estimatedTreadWear[0] == 0.0 and output.estimatedValidTreadWear[0] == 0.0
    assert output.currentTreadDepth[0] == pytest.approx(80.0)
    tele.update({"timing.current_laptime": 41.0, "lap.distance": 2050.0, "tyre.wear": (0.7999,) * 4})
    gen.send(1)
    assert output.currentLapTreadWear[0] == pytest.approx(0.01)  # wear of new car only


def test_module_wheels_sends_vehicle_resets_to_tyre_wear():
    """Module loop passes realtime_state.resets (bumped on followed car change by the game sync) to the generator"""
    import inspect

    from neopedal.adapter import _sync
    from neopedal.module import module_wheels

    assert "gen_tyre_wear.send(vehicle_resets)" in inspect.getsource(module_wheels)
    assert "vehicle_resets = realtime_state.resets" in inspect.getsource(module_wheels)
    assert "last_slot_id != slot_id" in inspect.getsource(_sync)


# --- Tyre load threshold in unit shown (finding 84, P13) & same gauge scale in both designs (85)
@pytest.mark.parametrize("modern", [True, False])
def test_tyre_load_threshold_and_gauge(field, monkeypatch, modern):  # noqa: F811
    from neopedal.widget.tyre_load import FULL_GAUGE_RATIO

    set_reader(monkeypatch, "tyre", "load", (2000.0, 2000.0, 2000.0, 0.5))
    widget = make("tyre_load", modern, show_tyre_load_ratio=True, low_load_threshold=1)
    widget.timerEvent(None)
    if modern:
        tiles = widget.state
        warned = [tile.colors[0] == widget.theme.negative for tile in tiles]
        assert tiles[0].level == pytest.approx(33.33 / FULL_GAUGE_RATIO, abs=0.001)
    else:
        bars = widget.bars_tload
        warned = [bar.bg_color == widget.wcfg["warning_color_low_load"] for bar in bars]
        width = bars[0].rect_bg.width()
        assert bars[0].rect_input.width() == pytest.approx(width * 33.33 / FULL_GAUGE_RATIO, abs=0.5)
        assert bars[1].rect_input.width() == pytest.approx(width * 33.33 / FULL_GAUGE_RATIO, abs=0.5)
    assert warned == [False, False, False, True]  # 1% of total load, not 1 Newton: wheel in the air only
    widget.deleteLater()


# --- Tyre overview redrawn only once a shown value changes (finding 80, P15)
@pytest.mark.parametrize("modern", [True, False])
def test_tyre_overview_redraws_on_shown_change_only(field, monkeypatch, modern):  # noqa: F811
    tyre_readers(monkeypatch)
    for attr, values in (("currentTreadDepth", [95.31] * 4), ("estimatedValidTreadWear", [0.731] * 4)):
        monkeypatch.setattr(minfo.wheels, attr, values)
    widget = make("tyre_overview", modern, show_wear=True, show_wear_per_lap=True, show_lifespan_laps=True,
                  show_pressure=True, show_carcass_temperature=True, show_inner_layer_temperature=True)
    painted = []
    monkeypatch.setattr(widget, "request_update" if modern else "update", lambda: painted.append(1))
    widget.timerEvent(None)
    assert len(painted) == 1
    tyre_readers(monkeypatch, temps=tuple(value + 0.1 for value in TEMPS), pressure=(175.33,) * 4)
    monkeypatch.setattr(minfo.wheels, "currentTreadDepth", [95.32] * 4)
    monkeypatch.setattr(minfo.wheels, "estimatedValidTreadWear", [0.7312] * 4)
    widget.timerEvent(None)
    assert len(painted) == 1  # same texts
    tyre_readers(monkeypatch, pressure=(176.0,) * 4)
    widget.timerEvent(None)
    assert len(painted) == 2
    card = widget.state[0]
    assert widget.pressure_text(card.pressure) == "176" and widget.wear_text(card.wear) == "0.73"
    assert widget.laps_text(card.laps) == "99+" and widget.remaining_text(card.remaining) == "95%"
    widget.deleteLater()


def test_tyre_overview_shown_values():
    from neopedal.widget.tyre_overview import TyreOverviewMixin, shown_laps, shown_wear

    assert shown_wear(0.004) > 0 and TyreOverviewMixin.wear_text(shown_wear(0.004)) == "0.00"
    assert shown_wear(-0.003) == 0.0 and shown_wear(0.7349) == 0.73
    assert shown_laps(-1.0) == -1.0 and shown_laps(9.94) == 9.9 and shown_laps(12.6) == 13.0
    assert TyreOverviewMixin.laps_text(shown_laps(150.0)) == "99+"
    for value in (0.0, 3.25, 9.96, 10.4, 57.5, 99.4):
        assert TyreOverviewMixin.laps_text(shown_laps(value)) in (
            TyreOverviewMixin.laps_text(value), "10")  # 9.96: "10" instead of "10.0"


# --- Fahrenheit: converted then rounded, not 1.8 degree steps (finding 107)
def test_shown_temperature_rounded_after_conversion():
    from neopedal import units
    from neopedal.widget._data import shown_temperature, temperature_text

    to_f = units.set_unit_temperature("Fahrenheit")
    for celsius in (85.3, 85.6, 20.0, -5.4, 112.77):
        assert temperature_text(shown_temperature(celsius, 1.8), to_f, 2, "", "-") == f"{to_f(celsius):02.0f}"
        assert temperature_text(shown_temperature(celsius, 1.0), units.pass_value, 2, "", "-") == f"{celsius:02.0f}"
    assert temperature_text(shown_temperature(85.3, 1.8), to_f, 2, "", "-") == "186"  # 85 C rounded first: 185


@pytest.mark.parametrize("name", ["tyre_temperature", "tyre_carcass", "tyre_overview"])
@pytest.mark.parametrize("modern", [True, False])
def test_fahrenheit_temperatures(field, monkeypatch, name, modern):  # noqa: F811
    monkeypatch.setitem(cfg.units, "temperature_unit", "Fahrenheit")
    tyre_readers(monkeypatch, temps=(85.3,) * 4)
    options = {"show_degree_sign": False}
    if name == "tyre_temperature":
        options["show_inner_center_outer"] = False
    widget = make(name, modern, **options)
    widget.timerEvent(None)
    if name == "tyre_overview":
        text = widget.temperature_text(widget.state[0].temps[0])
    elif modern:
        text = widget.state[0][0].texts[0]
    else:
        text = widget.bars_temp[0].text
    assert text == "186"
    widget.deleteLater()


# --- Carcass rate: steady in neutral color (finding 71)
def test_classic_carcass_steady_rate_neutral(field, monkeypatch):  # noqa: F811
    tyre_readers(monkeypatch)
    widget = make("tyre_carcass", False, show_rate_of_change=True)
    bar = widget.bars_rdiff[0]
    for rate, style in ((-0.01, 2), (0.01, 2), (0.5, 1), (-0.5, 0)):
        widget.update_rdiff(bar, rate)
        assert (bar.fg, bar.bg) == widget.bar_style_rtemp[style]
    widget.deleteLater()


# --- Modern compound badges colored by type option (findings 72, 73)
@pytest.mark.parametrize("name", ["tyre_carcass", "tyre_temperature", "tyre_inner_layer"])
def test_modern_compound_color_by_type(field, monkeypatch, name):  # noqa: F811
    tyre_readers(monkeypatch)
    widget = make(name, True, show_compound_color_by_type=False)
    assert "show_compound_color_by_type" in widget.options
    widget.timerEvent(None)
    assert widget.compounds.badges[0][0][1] == widget.theme.surface_raised
    widget.deleteLater()
    widget = make(name, True, show_compound_color_by_type=True)
    assert widget.compounds.badge_color is None
    widget.deleteLater()


# --- Simulated race: inner edge hottest on every tyre (finding 74)
def test_demo_inner_edge_hottest(ui_env):
    from neopedal import demo_data

    session = demo_data.demo_session(cfg.user.setting["standings"])
    for reader in ("surface_temperature_ico", "inner_temperature_ico"):
        temps = getattr(session.api.read.tyre, reader)()
        for wheel in range(4):
            left, center, right = temps[wheel * 3:wheel * 3 + 3]
            inner, outer = (right, left) if wheel % 2 == 0 else (left, right)  # left tyres: inner edge on right
            assert inner > center > outer


# --- Tyre temp trend preview: trend of simulated race (finding 75)
@pytest.mark.parametrize("by_lap", [False, True])
def test_temp_trend_demo_samples(field, monkeypatch, by_lap):  # noqa: F811
    from neopedal.widget import tyre_temp_trend

    tyre_readers(monkeypatch)
    widget = make("tyre_temp_trend", False, show_trend_by_lap=by_lap)
    monkeypatch.setattr(tyre_temp_trend, "drawing_demo", lambda: True)
    widget.timerEvent(None)
    samples = widget.trend.samples
    assert len(samples[0]) == widget.trend.size
    assert samples[0][-1] == pytest.approx(TEMPS[0], abs=0.2) and min(samples[0]) < TEMPS[0] - 10
    assert widget.charts[0].lines
    widget.deleteLater()


def test_temp_trend_live_not_filled(field, monkeypatch):  # noqa: F811
    tyre_readers(monkeypatch)
    widget = make("tyre_temp_trend", False)
    widget.timerEvent(None)
    assert len(widget.trend.samples[0]) == 1
    widget.deleteLater()


# --- Tyre pressure: deviation unsigned (finding 77), averages restart on leaving pits (78)
def test_modern_pressure_deviation_unsigned(field, monkeypatch):  # noqa: F811
    tyre_readers(monkeypatch, pressure=(175.0, 176.0, 170.0, 171.0))
    widget = make("tyre_pressure", True, show_pressure_deviation=True)
    widget.timerEvent(None)
    widget.timerEvent(None)
    assert all(not tile.sub.startswith(("±", "+", "-")) for tile in widget.state[0])
    widget.deleteLater()


@pytest.mark.parametrize("modern", [True, False])
def test_pressure_averages_restart_on_pit_exit(field, monkeypatch, modern):  # noqa: F811
    widget = make("tyre_pressure", modern, show_pressure_deviation=True, average_sampling_duration=10)
    tyre_readers(monkeypatch, in_pits=True, pressure=(150.0, 151.0, 152.0, 153.0))
    for _ in range(5):
        widget.timerEvent(None)
    tyre_readers(monkeypatch, in_pits=False, pressure=(180.0, 181.0, 182.0, 183.0))  # new tyres, pit exit
    widget.timerEvent(None)
    averages = widget.averages if modern else widget.tpavg
    assert averages == [180.0, 181.0, 182.0, 183.0]  # restarted from first reading, not from old tyres
    widget.timerEvent(None)
    assert averages is (widget.averages if modern else widget.tpavg)  # not reset again on track
    widget.deleteLater()


# --- Option page: tread warning used by tread gauge too (finding 83)
def test_tread_warning_dependency():
    from neopedal.template.widget.option_rules import ANY_OF, fixes_of

    assert fixes_of("tyre_overview", False)[1]["warning_threshold_remaining"] == "show_wear"
    assert fixes_of("tyre_overview", True)[1]["warning_threshold_remaining"] == ""
    assert ANY_OF["tyre_overview"]["warning_threshold_remaining"] == ("show_wear", "show_tread_gauge")
