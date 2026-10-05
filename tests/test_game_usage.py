"""Game data of LMU Rest API: team stints (strategy usage), tyre allocation, game estimate of
fuel & energy per lap (tyre screen) used until a lap of car & track is recorded"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal import realtime_state
from tinypedal.adapter import lmu_restapi
from tinypedal.api_control import api
from tinypedal.module import module_fuel
from tinypedal.module_info import FuelInfo, minfo
from tinypedal.process import team_usage
from tinypedal.setting import cfg
from tinypedal.ui._common import BaseEditor


def entry(lap, stint, fuel, ve=1.0, tread=100.0, pit=False):
    return {"lap": lap, "stint": stint, "fuel": fuel, "ve": ve, "tyres": [tread] * 4, "pit": pit}


# Two drivers: stint 1 (A, laps 0-5, pit on lap 5), stint 2 (B, laps 6-9 after refuel & new tyres)
USAGE = {
    "Driver A": [
        entry(0, 1, 0.90, 1.00, 100.0),
        entry(1, 1, 0.86, 0.95, 99.0),  # out lap: left out
        entry(2, 1, 0.83, 0.92, 98.5),
        entry(3, 1, 0.80, 0.89, 98.0),
        entry(4, 1, 0.77, 0.86, 97.5),
        entry(5, 1, 0.75, 0.84, 97.2, pit=True),  # in lap: left out
    ],
    "Driver B": [
        entry(6, 2, 0.95, 0.98, 100.0, pit=True),  # out lap after refuel
        entry(7, 2, 0.91, 0.94, 99.4),  # last lap pitted: left out
        entry(8, 2, 0.87, 0.90, 98.8),
        entry(9, 2, 0.83, 0.86, 98.2),
    ],
}

TYRE_SCREEN = {
    "expectedUsage": {"fuelConsumption": 2.78, "fuelFractionPerLap": 0.0232,
                      "virtualEnergyFractionPerLap": 0.0326},
    "tireInventory": {"maxAvailableTires": 8, "newTires": 8},
    "tireInvGarageOptions": {"newTiresRemaining": 6},
}


# --- Team usage
def test_parse_usage_in_lap_order():
    laps = team_usage.parse_usage({**USAGE, "Bad": [{"lap": "x"}, "text"], "Other": "text"})
    assert [lap.lap for lap in laps] == list(range(10))
    assert laps[6] == team_usage.UsageLap("Driver B", 2, 6, 0.95, 0.98, 100.0, True)
    assert team_usage.parse_usage(None) == [] and team_usage.parse_usage([1]) == []


def test_stint_usage_leaves_out_laps_and_pits():
    stints = team_usage.stint_usage(team_usage.parse_usage(USAGE))
    assert [(usage.driver, usage.stint, usage.first_lap, usage.last_lap, usage.laps) for usage in stints] == [
        ("Driver A", 1, 0, 5, 3),  # laps 2-4
        ("Driver B", 2, 6, 9, 2),  # laps 8-9
    ]
    stint_a, stint_b = stints
    assert stint_a.fuel == pytest.approx(0.03)
    assert stint_a.energy == pytest.approx(0.03)
    assert stint_a.wear == pytest.approx(0.5)
    assert stint_b.fuel == pytest.approx(0.04)
    assert stint_b.wear == pytest.approx(0.6)


def test_refuel_without_pit_flag_left_out():
    laps = team_usage.parse_usage({"A": [entry(0, 1, 0.5), entry(1, 1, 0.48), entry(2, 1, 0.45),
                                         entry(3, 1, 0.9), entry(4, 1, 0.87)]})
    usage, = team_usage.stint_usage(laps)
    assert usage.laps == 2 and usage.fuel == pytest.approx(0.03)  # laps 2 & 4


def test_combine_and_driver_usage():
    stints = team_usage.stint_usage(team_usage.parse_usage(USAGE))
    combined = team_usage.combine_usage(stints)
    assert combined.laps == 5 and combined.stint == 0
    assert combined.fuel == pytest.approx((0.03 * 3 + 0.04 * 2) / 5)
    drivers = team_usage.driver_usage(stints)
    assert [(usage.driver, usage.laps, usage.stint) for usage in drivers] == [("Driver A", 3, 1), ("Driver B", 2, 2)]
    assert team_usage.combine_usage([]).laps == 0


def test_tyre_allocation_and_tank_capacity():
    assert team_usage.tyre_allocation(TYRE_SCREEN) == team_usage.TyreAllocation(8, 6)
    assert team_usage.tyre_allocation({"tireInventory": {"maxAvailableTires": 0}}) is None
    assert team_usage.tyre_allocation(None) is None
    assert team_usage.tank_capacity({"fuelInfo": {"maxFuel": 120.0}}) == 120.0
    assert team_usage.tank_capacity({"fuelInfo": {}}) == 0.0


# --- Game estimate per lap (Rest API data, readers)
def test_tyre_screen_task_gives_game_estimate():
    task = next(task for task in lmu_restapi.lmu_restapi_tasks() if task.path == "/rest/garage/UIScreen/TireManagement")
    assert task.repeated and task.condition == "enable_vehicle_info"
    data = lmu_restapi.RestAPIData()
    for output in task.outputs:
        output.update(data, TYRE_SCREEN)
    assert data.expectedFuelConsumption == pytest.approx(2.78)
    assert data.expectedEnergyConsumption == pytest.approx(0.0326)
    for output in task.outputs:
        output.update(data, {"expectedUsage": {"fuelConsumption": 0}})  # not a float: default
    assert data.expectedFuelConsumption == 0.0 and data.expectedEnergyConsumption == 0.0


def test_readers_give_game_estimate():
    from tinypedal import api_connector

    for sim in (api_connector.SimLMU(), api_connector.SimLMULegacy()):
        sim._restapi_dataset.expectedFuelConsumption = 2.5
        sim._restapi_dataset.expectedEnergyConsumption = 0.03
        engine = sim.reader().engine
        assert engine.expected_fuel_consumption() == 2.5
        assert engine.expected_energy_consumption() == pytest.approx(3.0)


# --- Fuel module: game estimate until a lap of car & track is recorded
class Group(SimpleNamespace):
    def __init__(self, tele: dict, prefix: str):
        super().__init__()
        self._tele = tele
        self._prefix = prefix

    def __getattr__(self, name):
        key = f"{self._prefix}.{name}"
        return lambda *args, **kwargs: self._tele.get(key, 0)


@pytest.fixture
def tele(monkeypatch):
    values: dict = {
        "session.combo_name": "SimTrack - SimCar",
        "engine.tank_capacity": 100.0,
        "engine.fuel": 60.0,
        "timing.start": 10.0,
        "timing.elapsed": 20.0,
        "timing.current_laptime": 10.0,
        "lap.distance": 500.0,
    }
    groups = ("session", "lap", "timing", "vehicle", "tyre", "emotor", "engine")
    monkeypatch.setattr(api, "read", SimpleNamespace(**{name: Group(values, name) for name in groups}))
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(realtime_state, "active", True)
    return values


def run_fuel(tmp_path) -> FuelInfo:
    output = FuelInfo()
    gen = module_fuel.calc_consumption(output, False, f"{tmp_path}/", ".fuel", 10.0, 0.0)
    gen.send(0)
    return output


def test_fuel_estimate_from_game_without_record(tele, tmp_path):
    tele["engine.expected_fuel_consumption"] = 3.0
    output = run_fuel(tmp_path)
    assert output.estimatedConsumption == pytest.approx(3.0)
    assert output.estimatedLaps == pytest.approx(20.0)
    assert output.lastLapConsumption == 0.0  # no lap driven


def test_fuel_estimate_without_game_estimate(tele, tmp_path):
    output = run_fuel(tmp_path)
    assert output.estimatedConsumption == 0.0


def test_fuel_estimate_from_record_first(tele, tmp_path):
    from tinypedal.userfile.fuel_delta import save_fuel_delta_file

    rows = (*((index * 100.0, index * 0.1) for index in range(20)), (2000.0, 2.5, 90.0))
    save_fuel_delta_file(f"{tmp_path}/", "SimTrack - SimCar", ".fuel", rows)
    tele["engine.expected_fuel_consumption"] = 3.0
    output = run_fuel(tmp_path)
    assert output.estimatedConsumption == pytest.approx(2.5)


# --- Race calculator: team tab, game estimate, tyre allocation
@pytest.fixture
def page(ui_env, monkeypatch):
    from tinypedal.ui import race_calculator, tyre_strategy_planner

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(tyre_strategy_planner, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    dialog = race_calculator.RaceCalculator(None)
    yield dialog
    dialog.set_unmodified()
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_request(request, timeout=5.0):
    """Game request answered (background thread, answer queued to UI thread)"""
    import time

    end = time.monotonic() + timeout
    while request.busy and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert not request.busy


def test_team_stints_from_game(page, monkeypatch):
    from tinypedal.i18n import tr
    from tinypedal.ui import game_rest

    answers = {"/rest/strategy/usage": USAGE, "/rest/garage/UIScreen/RepairAndRefuel": {"fuelInfo": {"maxFuel": 100.0}}}
    monkeypatch.setattr(game_rest, "request_game", answers.get)
    panel = page.panel_team
    assert page.tabs.tabText(2) == tr("Team")
    assert panel.table.isHidden() and not panel.label_empty.isHidden()  # nothing asked yet
    panel.refresh()
    wait_request(panel.request)
    assert panel.table.rowCount() == 2 and not panel.table.isHidden()
    assert panel.capacity == 100.0
    assert panel.table.item(0, 4).text() == "3.000"  # 0.03 of 100 L tank
    assert "Driver A" in panel.label_drivers.text() and "Driver B" in panel.label_drivers.text()
    # Fill in selected stint (B), then all stints
    calc = page.panel_calculator
    panel.table.selectRow(1)
    panel.fill_in()
    assert calc.input_fuel.fuel_used.value() == pytest.approx(4.0)
    assert calc.input_tyre.wear_lap.value() == pytest.approx(0.6)
    assert calc.input_fuel.capacity.value() == pytest.approx(100.0)
    panel.table.clearSelection()
    panel.fill_in()
    assert calc.input_fuel.fuel_used.value() == pytest.approx(3.4)  # (3 * 3 + 2 * 4) / 5


def test_team_stints_game_not_running(page, monkeypatch):
    from tinypedal.ui import game_rest

    monkeypatch.setattr(game_rest, "request_game", lambda resource: None)
    panel = page.panel_team
    panel.refresh()
    wait_request(panel.request)
    assert panel.table.rowCount() == 0 and not panel.button_fill.isEnabled()
    assert panel.label_status.text()


def test_fill_in_game_estimate_without_valid_lap(page, monkeypatch):
    calc = page.panel_calculator
    monkeypatch.setattr(api.read.engine, "expected_fuel_consumption", lambda: 2.78)
    monkeypatch.setattr(api.read.engine, "expected_energy_consumption", lambda: 3.26)
    monkeypatch.setattr(api.read.engine, "tank_capacity", lambda *args: 120.0)
    calc.fill_in_data([])
    assert calc.input_fuel.fuel_used.value() == pytest.approx(2.78, abs=0.01)
    assert calc.input_fuel.energy_used.value() == pytest.approx(3.26, abs=0.01)
    assert calc.input_fuel.capacity.value() == pytest.approx(120.0)
    assert calc.label_fill_source.text()
    # File source: no game estimate
    calc.input_fuel.fuel_used.setValue(0)
    calc.fill_in_data([], live=False)
    assert calc.input_fuel.fuel_used.value() == 0


def test_tyre_allocation_from_game(page, monkeypatch):
    from tinypedal.ui import game_rest

    rule_panel = page.tyre_planner.tyre_rule_panel
    monkeypatch.setattr(game_rest, "request_game", lambda resource: TYRE_SCREEN)
    rule_panel.button_game.click()
    wait_request(rule_panel._game_request)
    assert rule_panel.max_allowed() == 8
    monkeypatch.setattr(game_rest, "request_game", lambda resource: None)  # game not running: kept
    rule_panel.button_game.click()
    wait_request(rule_panel._game_request)
    assert rule_panel.max_allowed() == 8
