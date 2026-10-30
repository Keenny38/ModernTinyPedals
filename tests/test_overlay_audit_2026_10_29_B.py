"""Overlay audit 2026-10-29, group B: laps & position, lap time history, pit stop estimate, race plan,
stint history & stint timer (findings 21-41)

Widgets are built on default settings (ui_env) with a neutral API reader, then single readers and
data module outputs are set to the case under test. Nothing is ever asked to a real game.
"""

from collections import deque
from importlib import import_module
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import realtime_state
from neopedal.api_control import api
from neopedal.fuel_strategy import StrategyInput
from neopedal.module_info import ConsumptionDataSet, StintDataSet, minfo
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget


@pytest.fixture
def widgets(ui_env, bundled_fonts):
    """Build widgets by name (modern design unless modern=False), deleted after test"""
    created = []

    def make(name: str, modern: bool = True, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def reader(monkeypatch, group: str, name: str, value):
    """Neutral API reader returns value"""
    monkeypatch.setattr(getattr(api.read, group), name, lambda *args, **kwargs: value)


def lap(number: int, laptime: float = 90.0, fuel: float = 3.0, valid: int = 1) -> ConsumptionDataSet:
    return ConsumptionDataSet(lapNumber=number, isValidLap=valid, lapTimeLast=laptime, lastLapUsedFuel=fuel)


# --- 21: final lap highlight from completed laps, not telemetry lap number (one more in demo data)
@pytest.mark.parametrize("modern", [True, False])
def test_final_lap_highlight_from_completed_laps(widgets, monkeypatch, modern):
    widget = widgets("laps_and_position", modern=modern, show_laps=True)
    reader(monkeypatch, "lap", "maximum", 10)
    reader(monkeypatch, "lap", "number", 9)  # lap number one above completed laps: lit a lap early
    reader(monkeypatch, "lap", "completed_laps", 8)
    reader(monkeypatch, "session", "finish_type", 1)

    def final() -> bool:
        if modern:
            return widget.laps_value().fill is not None
        widget.update_laps(widget.bar_laps)
        return widget.bar_laps.bg == widget.bar_style_laps[1]

    assert not final()
    reader(monkeypatch, "lap", "completed_laps", 9)
    assert final()


# --- 22: timed race without lap pace: dash, not the completed laps as finish lap
@pytest.mark.parametrize("modern", [True, False])
def test_timed_race_finish_lap_unknown_without_pace(widgets, monkeypatch, modern):
    widget = widgets("laps_and_position", modern=modern, show_laps=True, show_predicted_extra_laps=False)
    reader(monkeypatch, "session", "finish_type", 0)
    reader(monkeypatch, "lap", "progress", 0.43)
    reader(monkeypatch, "session", "remaining", 1800.0)
    monkeypatch.setattr(minfo.delta, "lapTimePace", 0.0)

    def text() -> str:
        if modern:
            return widget.laps_value().text
        widget.update_laps(widget.bar_laps)
        return widget.bar_laps.text

    assert "0.00" not in text().split("/")[1] and "~" in text()
    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)
    assert text().split("/")[1].strip().startswith("~19.00")  # 18 laps timed + lap in progress


# --- 24, 25, 26: lap numbers, placeholder row, invalid color
@pytest.mark.parametrize("modern", [True, False])
def test_lap_history_current_lap_number_and_placeholder(widgets, monkeypatch, modern):
    widget = widgets("lap_time_history", modern=modern, show_laps=True, show_empty_history=False)
    reader(monkeypatch, "lap", "number", 7)  # never read: lap number differs between games & demo data
    reader(monkeypatch, "lap", "completed_laps", 5)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", deque([lap(5), ConsumptionDataSet()], 100))
    monkeypatch.setattr(minfo.history, "consumptionDataVersion", minfo.history.consumptionDataVersion + 1)
    widget.timerEvent(None)
    if modern:
        current, _ = widget.state
        assert current.cells[0].text == "6"
        assert len(widget.history_rows) == 1  # placeholder of a single lap history left out
        assert widget.history_rows[0].cells[0].text == "5"
    else:
        assert widget.bars_laps[0].text == "006" and widget.bars_laps[1].text == "005"
        assert widget.bars_laps[2].isHidden()  # placeholder: no "000 / 0:00.000" ghost row


def test_classic_lap_history_validity_change_recolors(widgets, monkeypatch):
    widget = widgets("lap_time_history", modern=False, show_time=True)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", deque([lap(5, valid=1), lap(4)], 100))
    monkeypatch.setattr(minfo.history, "consumptionDataVersion", minfo.history.consumptionDataVersion + 1)
    widget.timerEvent(None)
    assert widget.bars_time[1].fg == widget.bar_style_time[1][0]
    monkeypatch.setattr(minfo.history, "consumptionDataSet", deque([lap(5, valid=0), lap(4)], 100))  # same time
    monkeypatch.setattr(minfo.history, "consumptionDataVersion", minfo.history.consumptionDataVersion + 1)
    widget.timerEvent(None)
    assert widget.bars_time[1].fg == widget.bar_style_time[2][0]


# --- 28, 29: pit stop estimate, 24 h race refill fits, total of a session started in garage
def test_modern_pit_estimate_large_values_fit(widgets, monkeypatch):
    widget = widgets("pit_stop_estimate", show_relative_refilling=True, decimal_places_total_relative_refill=2)
    assert widget.number("total_relative_refill", 2400.0, "+") == "+2400"
    assert widget.number("total_relative_refill", 24.5, "+") == "+24.50"
    assert widget.number("estimated_laps", 1e9) == "99999"


@pytest.mark.parametrize("modern", [True, False])
def test_pit_total_updated_in_garage(widgets, monkeypatch, modern):
    widget = widgets("pit_stop_estimate", modern=modern, additional_pitstop_time=0)
    reader(monkeypatch, "vehicle", "pit_stop_time", 40.0)
    monkeypatch.setattr(minfo.mapping, "pitPassTime", 30.0)
    widget.timerEvent(None)  # on track: 70 s total

    def total() -> float:
        widget.timerEvent(None)
        return widget.minimum_total if modern else widget.bar_minpit.last

    assert total() == pytest.approx(70.0)
    reader(monkeypatch, "vehicle", "in_pits", True)
    reader(monkeypatch, "vehicle", "pit_stop_time", 10.0)
    assert total() == pytest.approx(70.0)  # stop under way: kept
    reader(monkeypatch, "vehicle", "in_garage", True)  # new session in garage (other track)
    monkeypatch.setattr(minfo.mapping, "pitPassTime", 20.0)
    assert total() == pytest.approx(30.0)


# --- 31: race plan pit menu & target in the same unit, menu unit from car
def test_race_plan_menu_unit_from_car(monkeypatch):
    from neopedal.widget import race_plan

    stop = SimpleNamespace(fuel_after=45.0, energy_after=80.0)
    both = StrategyInput(fuel_per_lap=3.0, energy_per_lap=4.0)
    fuel_only = StrategyInput(fuel_per_lap=3.0)
    monkeypatch.setattr(api, "read", SimpleNamespace(vehicle=SimpleNamespace(absolute_refill=lambda: 80.0)))
    monkeypatch.setattr(minfo.energy, "available", True)  # pit menu refills virtual energy (%)
    assert race_plan.pit_menu_check(both, stop, float, "L") == (80.0, 80.0, "%")
    assert race_plan.pit_menu_check(fuel_only, stop, float, "L") is None  # never "80>45L"
    assert race_plan.energy_plan(both)  # target in energy, as pit menu
    monkeypatch.setattr(minfo.energy, "available", False)
    assert race_plan.pit_menu_check(both, stop, float, "L") == (80.0, 45.0, "L")
    assert not race_plan.energy_plan(both)
    assert race_plan.energy_plan(StrategyInput(energy_per_lap=4.0))


# --- 32: live consumption from laps of the race only
def test_race_plan_session_laps():
    from neopedal.widget.race_plan import session_laps

    history = [lap(12), lap(11), lap(9), lap(8), ConsumptionDataSet()]  # race laps 12-8 (10 not recorded)
    assert [item.lapNumber for item in session_laps(history, 12)] == [12, 11, 9, 8]
    qualifying_after = [lap(3), lap(2), lap(1), lap(14), lap(13)]  # race at lap 3, then qualifying laps
    assert [item.lapNumber for item in session_laps(qualifying_after, 3)] == [3, 2, 1]
    assert session_laps([lap(8), lap(7)], 0) == []  # race just started: practice laps only


# --- 33: race state text only when asked
def test_race_state_text_not_built_for_overlays(ui_env, monkeypatch):
    from neopedal import race_live

    calls = []
    monkeypatch.setattr(race_live, "clock", lambda seconds: calls.append(seconds) or "0:00:00")
    reader(monkeypatch, "session", "session_type", race_live.RACE_SESSION)
    reader(monkeypatch, "session", "in_race", True)
    live = race_live.read_race_state(float, race_live.StopCounter(), describe=False)
    assert live.text == "" and not calls
    assert race_live.read_race_state(float, race_live.StopCounter()).text and calls


# --- 34: classic race plan, translated END & target unit
def test_classic_race_plan_target_unit(widgets, monkeypatch):
    widget = widgets("race_plan", modern=False, show_target=True)
    widget.setup = StrategyInput(fuel_per_lap=3.0, tank_capacity=100.0)
    reader(monkeypatch, "engine", "fuel", 30.0)
    widget.update_target(SimpleNamespace(ready=True, last_lap=20), SimpleNamespace(lap=10), 0.0)
    assert widget.bar_target.text.endswith(widget.symbol_fuel)


# --- 35, 36, 37, 38: stint history
def test_stint_time_over_100_minutes():
    from neopedal.widget.stint_history import stint_time_text

    assert stint_time_text(5999.0) == "99:59"
    assert stint_time_text(6000.0) == "1h40"
    assert len(stint_time_text(36000.0 * 9.99)) <= 5


def test_modern_stint_history_static_rows_and_delta(widgets, monkeypatch):
    widget = widgets("stint_history", show_delta=True, decimal_places_delta=2)
    stint = StintDataSet(10, 900.0, 30.0, 0.0, 5.0, 12.345, 98.7, "MMMM", ())
    monkeypatch.setattr(minfo.history, "stintDataSet", deque([stint], 100))
    monkeypatch.setattr(minfo.history, "stintDataVersion", minfo.history.stintDataVersion + 1)
    widget.timerEvent(None)
    version = widget.history_version
    assert widget.state[1] == version and len(widget.state) == 2  # history drawn in static layer
    delta = next(column for column in widget.table.columns if column.key == "delta")
    assert widget.text_width("dim", "+12.35") <= delta.width
    widget.timerEvent(None)
    assert widget.history_version == version  # no change: static layer kept
    widget.grab()


def test_demo_stint_consistency_in_percent():
    from neopedal import demo_data
    from neopedal.module_info import ModuleInfo

    info = ModuleInfo()
    demo_data.set_modules(info)
    assert info.history.stintDataCurrent.lapTimeConsistency > 50
    assert all(stint.lapTimeConsistency > 50 for stint in info.history.stintDataSet)


# --- 39, 40: stint timer
@pytest.mark.parametrize("modern", [True, False])
def test_stint_timer_spectated_drivers_not_added(widgets, monkeypatch, modern):
    from neopedal.widget import stint_timer

    monkeypatch.setattr(stint_timer, "DRIVER_TIMES", stint_timer.DriverTimes())
    clock = {"elapsed": 0.0}
    monkeypatch.setattr(api.read.session, "elapsed", lambda: clock["elapsed"])
    reader(monkeypatch, "session", "identifier", (9, 0, 0))
    reader(monkeypatch, "vehicle", "driver_name", "Watched Driver")
    reader(monkeypatch, "vehicle", "player_has_vehicle", True)
    monkeypatch.setattr(realtime_state, "spectating", True)
    widget = widgets("stint_timer", modern=modern, number_of_drivers=0)
    for step in range(5):
        clock["elapsed"] = step * 1.0
        widget.timerEvent(None)
    assert widget.read_stint().drivers == ()
    monkeypatch.setattr(realtime_state, "spectating", False)
    for step in range(5, 8):
        clock["elapsed"] = step * 1.0
        widget.timerEvent(None)
    assert [row.name for row in widget.read_stint().drivers] == ["Watched Driver"]


def test_stint_timer_fair_share_races_only(widgets, monkeypatch):
    widget = widgets("stint_timer", number_of_drivers=2)
    reader(monkeypatch, "session", "end", 3600.0)
    reader(monkeypatch, "session", "finish_type", 0)
    reader(monkeypatch, "session", "in_race", False)
    assert widget.fair_share() == 0.0
    reader(monkeypatch, "session", "in_race", True)
    assert widget.fair_share() == pytest.approx(1800.0)
