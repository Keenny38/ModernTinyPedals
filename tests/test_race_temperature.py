"""Race calculator: air temperature trend of the forecast, lap time per °C added to track evolution"""

import pytest

from neopedal.fuel_strategy import strategy_input_from_values
from neopedal.process.weather import WeatherNode
from neopedal.race_live_data import temperature_trend

NODES = tuple(WeatherNode(start=index * 0.2, sky_type=1, temperature=20 + index, rain_chance=0.0)
              for index in range(5))


def test_temperature_trend():
    first, last, slope = temperature_trend(NODES, 4 * 3600)  # 4 °C from start to last node (3.2 h)
    assert (first, last) == (20, 24) and slope == pytest.approx(1.25)  # last node starts at 80 % of the session
    assert temperature_trend(NODES[:1], 3600) is None
    assert temperature_trend(NODES, 0) is None
    assert temperature_trend((WeatherNode(),) * 5, 3600) is None  # no forecast (default nodes)


def test_lap_time_per_degree_in_track_evolution():
    values = {"input_track_evolution": -0.2, "input_temp_effect": 0.05, "input_temp_slope": 2.0}
    assert strategy_input_from_values(values).track_evolution == pytest.approx(-0.1)
    assert strategy_input_from_values({"input_track_evolution": -0.2}).track_evolution == pytest.approx(-0.2)


def test_live_value(ui_env, monkeypatch):
    from neopedal.api_control import api
    from neopedal.race_live_data import collect_temperature

    session = api.read.session
    monkeypatch.setattr(session, "weather_forecast", lambda: NODES, raising=False)
    monkeypatch.setattr(session, "end", lambda: 4 * 3600.0, raising=False)
    monkeypatch.setattr(session, "start", lambda: 0.0, raising=False)
    value = collect_temperature()
    assert value.key == "input_temp_slope" and value.value == 1.25 and value.follow
    assert "20 → 24 °C" in value.text
    monkeypatch.setattr(session, "weather_forecast", lambda: (WeatherNode(),), raising=False)
    assert collect_temperature().value is None
