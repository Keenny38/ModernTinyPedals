"""Web dashboard page & values: app language, units of the user, virtual energy, official delta,
invalid lap (no server needed)"""

import json
import re

import pytest

from tinypedal import web_dashboard
from tinypedal.api_control import api
from tinypedal.i18n import set_language
from tinypedal.module_info import FuelInfo, minfo
from tinypedal.setting import cfg
from tinypedal.web_dashboard import dashboard_html, login_html, telemetry_snapshot


@pytest.fixture
def french():
    set_language("Français")
    yield
    set_language("English")


def script_texts(page: str) -> dict:
    """Text of page script (JSON in "const T=")"""
    return json.loads(re.search(r"const T=(\{.*?\});", page).group(1))


def test_page_in_english(ui_env):
    page = dashboard_html()
    assert '<html lang="en">' in page and "<title>Modern Tiny Pedals Dashboard</title>" in page
    assert "@@" not in page and ">Current lap<" in page
    assert script_texts(page)["waiting"] == "Waiting for session…"
    assert '<html lang="en">' in login_html() and 'placeholder="Access code"' in login_html()


def test_page_in_french(ui_env, french):
    page = dashboard_html()
    assert '<html lang="fr">' in page and "<title>Tableau de bord Modern Tiny Pedals</title>" in page
    assert ">Tour en cours<" in page and ">Delta officiel<" in page and "@@" not in page
    texts = script_texts(page)
    assert texts["expired"] == "Session expirée" and texts["energy"] == "Énergie · tours restants"
    assert 'placeholder="Code d&#x27;accès"' in login_html()


def test_page_text_escaped(ui_env, monkeypatch):
    """A translation (language pack) never breaks out of html or script"""
    monkeypatch.setattr(web_dashboard, "tr", lambda text: "</script><b>x</b>")
    page = dashboard_html()
    assert "<b>x</b>" not in page and "&lt;/script&gt;&lt;b&gt;x&lt;/b&gt;" in page
    assert page.count("</script>") == 1  # page script end only
    assert script_texts(page)["lost"] == "</script><b>x</b>"


def test_page_language_of_language_pack(monkeypatch):
    monkeypatch.setattr(web_dashboard, "current_language", lambda: "pt_BR")
    assert web_dashboard.page_language() == "pt-BR"


@pytest.fixture
def car(ui_env, monkeypatch):
    """Car at 10 m/s, 80 Celsius tyres & 400 Celsius brakes, 37.85 liters of fuel"""
    monkeypatch.setattr(api.read.vehicle, "speed", lambda *args, **kwargs: 10.0, raising=False)
    monkeypatch.setattr(api.read.tyre, "surface_temperature_avg", lambda *args, **kwargs: (80.0,) * 4, raising=False)
    monkeypatch.setattr(api.read.brake, "temperature", lambda *args, **kwargs: (400.0,) * 4, raising=False)
    monkeypatch.setattr(api.read.session, "track_temperature", lambda *args, **kwargs: 30.0, raising=False)
    fuel, energy = FuelInfo(), FuelInfo()
    fuel.amountCurrent, fuel.estimatedLaps, fuel.estimatedConsumption = 37.85411784, 12.0, 3.785411784
    energy.amountCurrent, energy.estimatedLaps, energy.estimatedConsumption = 55.0, 9.5, 5.5
    monkeypatch.setattr(minfo, "fuel", fuel)
    monkeypatch.setattr(minfo, "energy", energy)
    return fuel, energy


def test_values_in_units_of_user(car):
    cfg.units.update(speed_unit="MPH", temperature_unit="Fahrenheit", fuel_unit="Gallon")
    data = telemetry_snapshot()
    shown = data["display"]
    assert shown["speed"] == pytest.approx(22.4, abs=0.05) and shown["speed_unit"] == "mph"
    assert shown["tyre_temp"] == [176.0] * 4 and shown["brake_temp"] == [752.0] * 4
    assert shown["track_temp"] == 86.0 and shown["temperature_unit"] == "°F"
    assert shown["fuel"] == pytest.approx(10.0) and shown["fuel_unit"] == "gal"
    assert shown["fuel_per_lap"] == pytest.approx(1.0) and shown["fuel_laps"] == 12.0
    assert not shown["energy"]
    # Fields of before keep their units (command server stream)
    assert data["speed"] == 36.0 and data["tyre_temp"] == [80.0] * 4 and data["fuel"] == pytest.approx(37.85)


def test_default_units(car):
    shown = telemetry_snapshot()["display"]
    assert shown["speed"] == 36.0 and shown["speed_unit"] == "km/h"
    assert shown["tyre_temp"] == [80.0] * 4 and shown["temperature_unit"] == "°C"
    assert shown["fuel_unit"] == "L"


def test_virtual_energy_instead_of_fuel(car):
    _, energy = car
    energy.available = True
    cfg.units.update(fuel_unit="Gallon")
    shown = telemetry_snapshot()["display"]
    assert shown["energy"] and shown["fuel_unit"] == "%"
    assert shown["fuel"] == 55.0 and shown["fuel_laps"] == 9.5 and shown["fuel_per_lap"] == 5.5


def test_official_delta_and_invalid_lap(car, monkeypatch):
    monkeypatch.setattr(api.read.timing, "delta_best", lambda *args, **kwargs: -0.4567, raising=False)
    monkeypatch.setattr(api.read.lap, "invalidated", lambda *args, **kwargs: True, raising=False)
    monkeypatch.setattr(type(api), "name", property(lambda self: "Le Mans Ultimate"))
    data = telemetry_snapshot()
    assert data["delta_official"] == -0.457 and data["lap_invalid"] is True
    monkeypatch.setattr(type(api), "name", property(lambda self: "rFactor 2"))
    data = telemetry_snapshot()
    assert data["delta_official"] is None  # not given by the game
    json.dumps(data)  # sent as JSON: null


def test_snapshot_without_units_setting(car, monkeypatch):
    monkeypatch.setattr(type(cfg), "units", property(lambda self: {}["units"]))
    assert telemetry_snapshot()["display"]["speed_unit"] == "km/h"
