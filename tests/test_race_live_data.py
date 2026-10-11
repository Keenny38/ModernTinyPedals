"""Race calculator live data: LMU garage screens parsed (pit stop times, tyres offered, team, forecast,
tyre allocation, session settings), every live value against the calculator, filled in one by one, all
at once, by Load Live & Follow Live, values not followed left out, live tab of the page"""

import pytest

from tests.test_race_calculator import host, page, set_race  # noqa: F401 (host, page: fixtures)
from tinypedal.fuel_strategy import StrategyInput, stop_time
from tinypedal.race_live_data import (
    GarageData,
    compound_key,
    parse_garage,
    rain_period,
    tyre_offer,
)


def wheel(name: str, *texts: str) -> dict:
    return {"name": name, "currentSetting": 0, "settings": [{"text": text} for text in texts]}


# As LMU 1.x answers in French (10 h race, 4 drivers, seen live), trimmed
REFUEL_SCREEN = {
    "fuelInfo": {"currentFuel": 57.5, "maxFuel": 115.0, "maxVirtualEnergy": 901000000.0},
    "pitStopTimes": {"times": {
        "DriverChange": 25.0, "DriverConcurrent": 1.0, "FourTireChange": 12.0, "TwoTireChange": 4.5,
        "FuelFillRate": 4.0, "FuelTimeConcurrent": 1.0, "TireTimeConcurrent": 0.0,
        "virtualEnergyFillRate": 0.025,
    }},
    "pitMenu": {"pitMenu": [
        {"name": "DRIVER:", "currentSetting": 2, "settings": [{"text": "F Veninski"}, {"text": "K Hess"}]},
        wheel("FL TIRE:", "Aucun changement", "Neuf Tendre ", "Neuf Medium ", "Neuf Mouillé ", "INVALID"),
        wheel("FR TIRE:", "Aucun changement", "Neuf Tendre ", "Neuf Medium ", "Neuf Mouillé ", "Usé Tendre  84%"),
        wheel("RL TIRE:", "Aucun changement", "Neuf Tendre ", "Neuf Medium ", "Neuf Mouillé ", "Usé Tendre  83%"),
        wheel("RR TIRE:", "Aucun changement", "Neuf Tendre ", "Neuf Medium ", "Neuf Mouillé ", "Usé Tendre  90%"),
    ]},
    "teamInfo": {"driverNames": ["Flo Veninski", "Antoine Dumontier", "Keenny Hess", "Olivier Demolliens"],
                 "teamName": "Team", "vehicleName": "Car #397"},
    "weatherForecast": {"nodes": {"RainChance": [0, 0, 100, 0, 0], "Sky": [4, 3, 7, 3, 2]}},
}
TYRE_SCREEN = {"tireInventory": {"maxAvailableTires": 56}, "tireInvGarageOptions": {"newTiresRemaining": 40}}
SESSION_SETTINGS = {
    "SESSSET_formation": {"currentValue": 1, "stringValue": "Fast Rolling"},
    "SESSSET_race_starting_time": {"currentValue": 720, "stringValue": "12:00 PM"},
}


def test_garage_screens_parsed():
    garage = parse_garage(REFUEL_SCREEN, TYRE_SCREEN, SESSION_SETTINGS)
    assert garage.available
    assert garage.tank_capacity == 115.0 and garage.fuel_rate == 4.0
    assert garage.energy_rate == pytest.approx(2.5)  # fraction per second: % per second
    assert (garage.two_tyres, garage.four_tyres, garage.driver_change) == (4.5, 12.0, 25.0)
    assert garage.tyres_during_refuel is False  # tyre change not concurrent
    assert garage.driver_during_refuel is True
    assert len(garage.drivers) == 4
    assert garage.new_compounds == ("Soft", "Medium", "Wet")
    assert [[offer.tread for offer in offers] for offers in garage.used_tyres] == [[], [84.0], [83.0], [90.0]]
    assert garage.used_tyres[1][0].compound == "Soft" and garage.used_tyres[1][0].text == "Usé Tendre 84%"
    assert garage.rain == (0.0, 0.0, 1.0, 0.0, 0.0)
    assert (garage.tyres_allowed, garage.new_tyres_left) == (56, 40)
    assert (garage.formation_laps, garage.start_minutes) == (0.5, 720)


def test_garage_answers_missing_or_odd():
    assert parse_garage(None, None, None) == GarageData() and not GarageData().available
    odd = parse_garage({"fuelInfo": "x", "pitStopTimes": {"times": {"FuelFillRate": "nan"}}, "pitMenu": 3,
                        "teamInfo": {"driverNames": "A"}}, {"tireInventory": {}}, {"SESSSET_formation": 5})
    assert odd.fuel_rate == 0.0 and odd.drivers == () and odd.tyres_allowed == 0 and odd.formation_laps == -1
    assert parse_garage({}, None, {"SESSSET_formation": {"stringValue": "Rolling"}}).formation_laps == 1.0


def test_compounds_of_game_texts():
    assert compound_key("Neuf Mouillé") == "Wet" and compound_key("New Hard") == "Hard"
    assert compound_key("Weich") == "Soft" and compound_key("Intermédiaire") == "Intermediate"
    assert compound_key("Hypersoft") == ""  # unknown: left out
    assert tyre_offer("Aucun changement") is None and tyre_offer("INVALID") is None
    assert tyre_offer("Used Medium 61,5%").tread == 61.5


def test_rain_period_from_forecast():
    assert rain_period((0, 0, 1, 0, 0), 100) == (41, 20)  # middle fifth of the race
    assert rain_period((0, 0, 0, 0.6, 0.9), 100) == (61, 40)  # wet until the finish
    assert rain_period((0.1, 0.2), 50) == (0, 0)  # dry
    assert rain_period((), 50) is None and rain_period((1,), 0) is None


def test_driver_change_while_refuelling():
    setup = StrategyInput(pit_seconds=30, refuel_rate=2.0, drivers=2, driver_change_seconds=25)
    assert stop_time(setup, 0, 40.0, 0.0, False)[0] == pytest.approx(30 + 20 + 25)
    setup = StrategyInput(pit_seconds=30, refuel_rate=2.0, drivers=2, driver_change_seconds=25, driver_during_refuel=True)
    assert stop_time(setup, 0, 40.0, 0.0, False)[0] == pytest.approx(30 + 25)  # driver change longest
    assert stop_time(setup, 0, 80.0, 0.0, False)[0] == pytest.approx(30 + 40)  # refuelling longest


def row(backend, key: str) -> dict:
    return next(item for item in backend.liveData["rows"] if item["key"] == key)


def test_live_tab_fill_in(page, monkeypatch):  # noqa: F811
    from tinypedal.ui.quick.race_backend import TABS

    backend = page.backend
    set_race(backend, minutes=600, laptime=100.0, tank=100.0, fuel=3.0)
    backend.setTab(TABS.index("live"))
    backend.received_garage([REFUEL_SCREEN, TYRE_SCREEN, SESSION_SETTINGS])
    assert row(backend, "input_refuel_rate")["game"] == "4.00 L/s" and row(backend, "input_refuel_rate")["differs"]
    assert row(backend, "input_drivers")["tip"].startswith("Flo Veninski")
    assert backend.liveData["tyres"]["allowed"] == 56 and backend.liveData["tyres"]["used"] == 3
    assert not row(backend, "input_fuel_start")["known"]  # car on the grid only
    backend.setLiveFollowed("input_driver_change_seconds", False)
    assert not row(backend, "input_driver_change_seconds")["followed"]
    backend.applyAllLive()
    values = backend.values
    assert values["input_refuel_rate"] == pytest.approx(4.0) and values["input_energy_rate"] == pytest.approx(2.5)
    assert values["input_drivers"] == 4 and values["input_formation_laps"] == 0.5
    assert values["input_race_start_minutes"] == 720
    assert values["enable_driver_change_during_refuel"] is True and values["enable_tyres_during_refuel"] is False
    assert values["input_driver_change_seconds"] == 0.0  # not followed: left as it was
    rule = backend.tyres.rule
    assert (rule["maximum_tyre"], rule["tyre_change_time_2"], rule["tyre_change_time_4"]) == (56, 4.5, 12.0)
    assert values["enable_rain"] and values["input_rain_laps"] > 0  # wet middle of the race
    assert not row(backend, "input_refuel_rate")["differs"] and backend.liveData["differing"] == 0
    backend.applyLiveValue("input_driver_change_seconds")  # one row filled in, followed or not
    assert backend.values["input_driver_change_seconds"] == 25.0


def test_load_live_fills_in_garage_values_once_answered(page, monkeypatch):  # noqa: F811
    from tinypedal.api_control import api

    backend = page.backend
    monkeypatch.setattr(api.read.state, "active", lambda: True)
    asked = []
    monkeypatch.setattr(backend.garage_request, "start", lambda work=None: asked.append(1) or True)
    backend.loadLive()
    assert asked and backend._apply_garage
    backend.received_garage([REFUEL_SCREEN, None, None])
    assert backend.values["input_refuel_rate"] == pytest.approx(4.0) and not backend._apply_garage
    backend.received_garage([{**REFUEL_SCREEN, "pitStopTimes": {"times": {"FuelFillRate": 2.0}}}, None, None])
    assert backend.values["input_refuel_rate"] == pytest.approx(4.0)  # not asked, not followed live: kept


def test_follow_live_fills_in_garage_values(page, monkeypatch):  # noqa: F811
    backend = page.backend
    backend.setFollowLive(True)
    backend.received_garage([REFUEL_SCREEN, None, None])
    assert backend.values["input_refuel_rate"] == pytest.approx(4.0)


def test_garage_cleared_out_of_session(page):  # noqa: F811
    backend = page.backend
    backend.received_garage([REFUEL_SCREEN, None, None])
    assert backend.garage.available and backend.garage_time
    backend.refresh_garage()  # game not in a session (test reader)
    assert backend.garage == GarageData() and not backend.garage_time


def test_live_race_items(page, monkeypatch):  # noqa: F811
    from tinypedal.api_control import api

    backend = page.backend
    assert backend.live_race_items() == []  # out of a race
    read = api.read
    monkeypatch.setattr(read.state, "active", lambda: True)
    monkeypatch.setattr(read.session, "session_type", lambda: 4)
    monkeypatch.setattr(read.session, "in_race", lambda: True)
    monkeypatch.setattr(read.session, "elapsed", lambda: 3700.0)
    monkeypatch.setattr(read.session, "start", lambda: 100.0)
    monkeypatch.setattr(read.session, "remaining", lambda: 1800.0)
    monkeypatch.setattr(read.lap, "completed_laps", lambda *args: 30)
    monkeypatch.setattr(read.lap, "safety_car_active", lambda: True)
    monkeypatch.setattr(read.vehicle, "number_penalties", lambda *args: 1)
    monkeypatch.setattr(read.vehicle, "repair_time", lambda: 12.0)
    items = {item["title"]: item for item in backend.live_race_items()}
    assert items["Lap"]["value"] == "31" and items["Race Time"]["value"] == "1:00:00"
    assert items["Track"]["value"] == "Safety Car" and items["Track"]["warning"]
    assert items["Penalties"]["warning"] and items["Pending Repair"]["value"] == "12 s"


def test_live_tab_qml(page):  # noqa: F811
    """Live tab built in the page without QML warning, rows shown"""
    from PySide6.QtCore import QCoreApplication

    from tinypedal.ui.quick.race_backend import TABS

    view = page.ensure_view()
    page.backend.received_garage([REFUEL_SCREEN, TYRE_SCREEN, SESSION_SETTINGS])
    page.backend.setTab(TABS.index("live"))
    QCoreApplication.processEvents()
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str) and text:
            texts.add(text)
        stack.extend(item.childItems())
    assert "Game data" in texts and "Refuel Rate" in texts and "Tyres Available" in texts



def test_used_tyres_of_game_in_stock(page):  # noqa: F811
    from tinypedal.userfile.tyre_strategy import validate_tyre_strategy

    backend = page.backend
    set_race(backend, laps=40, wear=2.0, minimum=20)
    backend.received_garage([REFUEL_SCREEN, TYRE_SCREEN, None])
    backend.addGameTyres()
    tyres = backend.tyres
    assert sorted(tyres.treads.values()) == [83.0, 84.0, 90.0] and tyres.rule["maximum_tyre"] == 56
    used = [item for item in backend.tyrePlan["stock"] if item["tread"]]
    assert [item["tread"] for item in used] == ["84%", "83%", "90%"]
    name = used[0]["name"]
    assert backend.tyres.assign(0, 1, name) == ""
    tyres.refresh()
    assert tyres.cells[0][1]["remaining"] == pytest.approx(0.84)  # starts at its own tread, not new
    backend.addGameTyres()  # asked again: unfitted used tyres replaced, fitted one kept
    assert len(tyres.treads) == 4 and name in tyres.treads
    tyres.propose()
    assert all(cell not in tyres.treads for row in tyres.rows for cell in row)  # fitted by hand only
    data = validate_tyre_strategy(tyres.capture_data())
    assert data["tyre_tread"] == {key: value for key, value in tyres.treads.items() if key in tyres.stock}
    tyres.remove_tyres(list(tyres.treads))
    assert not tyres.treads
