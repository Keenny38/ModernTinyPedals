"""Race calculator: refill of the next stop written to the LMU pit menu (as the game web UI does)

Menu entries as the game answers them (receivePitMenu): "PMC Value", "name", "currentSetting",
"settings" [{"text"}]. Not checked against the game in a session yet (user test owed).
"""

import json

import pytest

from neopedal import race_live_data
from neopedal.race_live_data import PMC_FUEL, PMC_VIRTUAL_ENERGY, pit_menu_refill, setting_amount
from tests.test_race_calculator import host, page, set_race  # noqa: F401 (host, page: fixtures)


def entry(pmc: int, name: str, texts: list[str], current: int = 0) -> dict:
    return {"PMC Value": pmc, "name": name, "currentSetting": current, "settings": [{"text": t} for t in texts],
            "default": 0}


ENERGY_MENU = [
    entry(5, "DRIVER:", ["Alice", "Bob"]),
    entry(PMC_VIRTUAL_ENERGY, "VIRTUAL ENERGY:", [f"{percent}%" for percent in range(101)], 40),
    entry(PMC_FUEL, "FUEL RATIO:", ["0.90", "0.95", "1.00"], 1),
]
FUEL_MENU = [entry(PMC_FUEL, "FUEL:", ["5.0L", "10.0L", "45.5L", "60.0L", "90.0L"], 1)]


def test_setting_amount():
    assert setting_amount("65%", False) == 65.0
    assert setting_amount("45,5L", True) == 45.5
    assert setting_amount("10.0gal", True) == pytest.approx(37.854, abs=0.001)
    assert setting_amount("No change", True) is None


def test_energy_car_sets_virtual_energy_only():
    refill = pit_menu_refill(ENERGY_MENU, 80.0, 72.4)
    assert refill.kind == "energy" and refill.entry["PMC Value"] == PMC_VIRTUAL_ENERGY
    assert refill.entry["currentSetting"] == 73 and refill.text == "73%"  # first reaching the plan
    assert ENERGY_MENU[1]["currentSetting"] == 40  # menu read left as it is
    assert pit_menu_refill(ENERGY_MENU, 80.0, 0.0) is None  # no energy planned: fuel entry is the ratio


def test_fuel_car_sets_fuel():
    refill = pit_menu_refill(FUEL_MENU, 45.0, 0.0)
    assert refill.kind == "fuel" and refill.entry["currentSetting"] == 2 and refill.value == 45.5
    assert pit_menu_refill(FUEL_MENU, 200.0, 0.0).entry["currentSetting"] == 4  # most the menu offers
    by_name = [{k: v for k, v in FUEL_MENU[0].items() if k != "PMC Value"}]  # older answers: entry name
    assert pit_menu_refill(by_name, 45.0, 0.0).entry["currentSetting"] == 2
    assert pit_menu_refill([], 45.0, 0.0) is None and pit_menu_refill(None, 45.0, 0.0) is None


class FakeGame:
    def __init__(self, menu, answered=True, accept=True):
        self.menu, self.answered, self.accept, self.sent = menu, answered, accept, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, resource):
        assert resource == race_live_data.PIT_MENU_READ
        return self.menu

    def send(self, method, resource, body=None):
        self.sent.append((method, resource, json.loads(body)))
        return self.accept


def test_write_pit_menu(monkeypatch):
    from neopedal import game_rest

    game = FakeGame(FUEL_MENU)
    monkeypatch.setattr(game_rest, "GameConnection", lambda: game)
    state, refill = race_live_data.write_pit_menu(45.0, 0.0)
    assert state == "set" and refill.text == "45.5L"
    method, resource, body = game.sent[0]
    assert (method, resource) == ("POST", race_live_data.PIT_MENU_WRITE)
    assert body == [dict(FUEL_MENU[0], currentSetting=2)]  # one entry, as read, setting changed
    monkeypatch.setattr(game_rest, "GameConnection", lambda: FakeGame(FUEL_MENU, accept=False))
    assert race_live_data.write_pit_menu(45.0, 0.0)[0] == "refused"
    monkeypatch.setattr(game_rest, "GameConnection", lambda: FakeGame("Invalid state"))
    assert race_live_data.write_pit_menu(45.0, 0.0)[0] == "missing"
    monkeypatch.setattr(game_rest, "GameConnection", lambda: FakeGame(None, answered=False))
    assert race_live_data.write_pit_menu(45.0, 0.0)[0] == "offline"


def test_page_button(page, host, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_live_tab
    from tests.test_race_calc_scenario_jobs import wait_jobs

    backend = page.backend
    calls = []

    def written(fuel, energy):
        calls.append((fuel, energy))
        return "set", race_live_data.PitMenuRefill({}, "fuel", 45.5, "45.5L <b>")

    monkeypatch.setattr(race_live_tab, "write_pit_menu", written)
    backend.setGamePitMenu()  # no plan yet
    assert host.toasts[-1] == "No pit stop in the plan" and not calls
    set_race(backend, laps=40)  # 3.0 per lap, 45 tank: stops at 15 & 30
    backend.setGamePitMenu()
    assert wait_jobs(backend)
    assert calls == [(pytest.approx(backend.strategy.stops[0].fuel_after), 0.0)]
    assert host.toasts[-1] == "Pit menu set for the next stop: 45.5L &lt;b&gt;"
