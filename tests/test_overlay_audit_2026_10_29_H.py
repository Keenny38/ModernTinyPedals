"""Overlay audit 2026-10-29, group H: battery, cruise, electric motor, engine, engine temperature, fuel
energy saver & virtual energy, hybrid & fuel modules (findings 19-39, 44, 45, 101)

Widgets are built on default settings (ui_env) with a neutral API reader, then single readers and
data module outputs are set to the case under test. Nothing is ever asked to a real game.
"""

from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import realtime_state
from neopedal.api_control import api
from neopedal.module_info import FuelInfo, HybridInfo, minfo
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget
from neopedal.widget._modern.base import DASH
from tests.test_game_usage import tele  # noqa: F401  (fixture)
from tests.test_readers import lmu_api, rf2_api


@pytest.fixture
def widgets(ui_env, bundled_fonts, monkeypatch):
    """Build widgets by name (modern design unless modern=False), deleted after test; module outputs
    read by these widgets restored after test"""
    for name in ("hybrid", "energy", "fuel"):
        monkeypatch.setattr(minfo, name, type(getattr(minfo, name))())
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


def texts(widget) -> dict[str, str]:
    """Modern stat texts by key"""
    return {key: value.text for key, value in zip(widget.keys, widget.state)}


# --- 26, 27: electric motor power deployed from game electric power on LMU, regeneration only in Regen
def test_lmu_electric_power_from_game_power():
    sim, data = lmu_api()
    read = sim.reader()
    vehicle = data.telemetry.telemInfo[0]
    vehicle.mElectricBoostMotorTorque, vehicle.mElectricBoostMotorRPM = 1000.0, 12000.0  # x RPM: 1257 kW
    vehicle.mRegen = -196.0  # deploying
    assert read.emotor.power() == pytest.approx(196.0)
    assert read.emotor.regeneration_level() == 0.0
    vehicle.mRegen = 193.5  # regenerating
    assert read.emotor.power() == 0.0
    assert read.emotor.regeneration_level() == pytest.approx(193.5)
    vehicle.mRegen = 0.0
    assert str(read.emotor.power()) == "0.0"  # never -0.0


def test_rf2_electric_power_from_torque_and_rpm():
    sim, info = rf2_api()
    read = sim.reader()
    vehicle = info._tele.data.mVehicles[0]
    vehicle.mElectricBoostMotorTorque, vehicle.mElectricBoostMotorRPM = 100.0, 9549.3
    assert read.emotor.power() == pytest.approx(100.0)
    vehicle.mElectricBoostMotorTorque = -100.0  # regenerating
    assert read.emotor.power() == 0
    assert read.emotor.regeneration_level() == -1.0  # not available


def test_recorded_hypercar_power_within_limit(ui_env, monkeypatch):
    from tests.recorded_session import RecordedSession

    for name in ("active", "paused", "resets", "shown", "session_type", "in_pits"):  # set by game sync
        monkeypatch.setattr(realtime_state, name, getattr(realtime_state, name))
    session = RecordedSession("lmu_lusail_practice_pit", cfg.api)
    try:
        powers = [session.reader.emotor.power() for _ in session.frames(5)]
    finally:
        session.close()
    assert 150 < max(powers) <= 200  # 499P: 200 kW limit (torque x RPM: up to 1323 kW)


@pytest.mark.parametrize("modern", [True, False])
def test_electric_motor_power_and_regen_cells(widgets, monkeypatch, modern):
    widget = widgets("electric_motor", modern=modern)
    reader(monkeypatch, "emotor", "power", 195.88)
    reader(monkeypatch, "emotor", "regeneration_level", 0.0)
    reader(monkeypatch, "emotor", "torque", -2301.4)  # 28: no trailing point
    widget.timerEvent(None)
    if modern:
        values = texts(widget)
        power, regen, torque = values["power"], values["regeneration_level"], values["torque"]
    else:
        power, regen, torque = widget.bar_power.text, widget.bar_regen.text, widget.bar_torque.text
    assert power.strip() == "195.88kW" and regen.strip() == "0.00kW" and torque.strip() == "-2301Nm"
    reader(monkeypatch, "emotor", "regeneration_level", -1.0)  # rF2: not available
    widget.timerEvent(None)
    regen = texts(widget)["regeneration_level"] if modern else widget.bar_regen.text
    assert regen == DASH if modern else regen.strip() == "-kW"


# --- 44: virtual energy cleared once car has none, overlays show no value
def test_energy_cleared_when_not_available(monkeypatch):
    from neopedal.module.module_fuel import set_energy_available

    monkeypatch.setattr(minfo, "energy", FuelInfo())
    monkeypatch.setattr(minfo, "hybrid", HybridInfo())
    set_energy_available(True)
    minfo.energy.amountCurrent = 58.0
    minfo.energy.estimatedLaps = 1.0
    minfo.hybrid.fuelEnergyRatio, minfo.hybrid.fuelEnergyBias = 0.75, 0.5
    set_energy_available(True)
    assert minfo.energy.amountCurrent == 58.0
    set_energy_available(False)  # LMP2 after Hypercar
    assert not minfo.energy.available
    assert (minfo.energy.amountCurrent, minfo.energy.estimatedLaps) == (0.0, 0.0)
    assert (minfo.hybrid.fuelEnergyRatio, minfo.hybrid.fuelEnergyBias) == (0.0, 0.0)


@pytest.mark.parametrize("modern", [True, False])
def test_virtual_energy_without_energy_shows_no_value(widgets, modern):
    widget = widgets("virtual_energy", modern=modern, show_fuel_ratio=True, show_fuel_bias=True)
    minfo.energy.available = True
    minfo.energy.amountCurrent = 12.0
    minfo.energy.estimatedValidConsumption = 4.0
    minfo.energy.estimatedLaps = 0.5  # low energy warning
    minfo.hybrid.fuelEnergyRatio = 0.75
    widget.timerEvent(None)
    minfo.energy.available = False
    widget.timerEvent(None)
    if modern:
        values, remaining, _, low, level = widget.state
        assert remaining == DASH and not low and level is None
        assert all(value.text == DASH for value in values)
    else:
        assert all(cell.text == "-.--" for cell in widget.cells.values())
        assert widget.cells["remaining"].bg == widget.bar_style_curr[0]  # no low warning color


# --- 20: car without hybrid system: no battery charge, no low battery warning
@pytest.mark.parametrize("modern", [True, False])
def test_battery_without_hybrid(widgets, modern):
    widget = widgets("battery", modern=modern)
    for _ in range(3):
        widget.timerEvent(None)
    if modern:
        charge = widget.state[widget.keys.index("charge")]
        assert charge.text == DASH and charge.fill is None
    else:
        assert widget.bar_charge.text == "B      -"
        assert widget.bar_charge.bg == widget.bar_style_charge[0]
    minfo.hybrid.motorState = 2  # hybrid with empty battery: warning
    widget.timerEvent(None)
    if modern:
        assert widget.state[widget.keys.index("charge")].text == "0.00%"
    else:
        assert widget.bar_charge.text.endswith("0.00")


# --- 19: last lap usage of a lap recorded in part (module started mid-lap) not shown as last lap
def test_hybrid_partial_lap_not_last_lap(tele):  # noqa: F811
    from neopedal.module.module_hybrid import calc_motor

    output = HybridInfo()
    tele.update({"timing.current_laptime": 32.7, "emotor.state": 2, "emotor.battery_charge": 0.6})
    gen = calc_motor(output, 10.0)

    def tick(charge: float, lap_start: float = 10.0, laptime: float = 32.7):
        tele.update({"emotor.battery_charge": charge, "timing.start": lap_start, "timing.current_laptime": laptime})
        gen.send(0)

    tick(0.6)
    tick(0.4)  # half a lap: 20% drained
    tick(0.4, 100.0, 0.1)  # line
    assert output.batteryDrainLast == output.batteryRegenLast == 0.0
    tick(0.3, 100.0, 1.0)
    tick(0.3, 190.0, 0.1)  # full lap
    assert output.batteryDrainLast == pytest.approx(10.0)


@pytest.mark.parametrize("modern", [True, False])
def test_battery_after_partial_lap_shows_current_lap(widgets, monkeypatch, modern):
    widget = widgets("battery", modern=modern)
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 2.0)  # within freeze duration
    minfo.hybrid.motorState = 2
    minfo.hybrid.batteryDrain = 1.5  # no last lap
    widget.timerEvent(None)
    drain = texts(widget)["drain"] if modern else widget.bar_drain.text.strip()
    assert drain == "-1.50"


# --- 21: no sign on zero, net change none until recorded
def test_battery_change_text():
    from neopedal.widget.battery import change_text

    assert change_text(0.0, "-") == change_text(0.001, "+") == change_text(-0.001, "") == "0.00"
    assert change_text(1.5, "-") == "-1.50" and change_text(0.2, "+") == "+0.20"
    assert change_text(-0.5, "") == "-0.50" and change_text(0.5, "") == "+0.50"


@pytest.mark.parametrize("modern", [True, False])
def test_battery_net_change_none_until_recorded(widgets, modern):
    widget = widgets("battery", modern=modern)
    minfo.hybrid.motorState = 2
    widget.timerEvent(None)
    net = texts(widget)["net"] if modern else widget.bar_net.text
    assert net == DASH if modern else net == "N      -"
    minfo.hybrid.batteryNetChange = -0.004
    widget.timerEvent(None)
    net = texts(widget)["net"] if modern else widget.bar_net.text
    assert net.endswith(" 0.00") or net == "0.00"


# --- 24: preview state of charge same as battery charge
def test_demo_state_of_charge(ui_env, bundled_fonts):
    from neopedal.ui.widget_preview import _with_preview_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    setting = dict(cfg.user.setting["battery"], show_state_of_charge=True)
    values = _with_preview_widget(cfg, "battery", setting, 1.0, texts)
    assert values["soc"] == "64.0%"


# --- 25: compass never 360
def test_compass_heading_wraps_to_north():
    from math import radians

    from neopedal.widget.cruise import compass_heading

    assert compass_heading(radians(180 - 359.7)) == 0
    assert compass_heading(radians(180 - 359.4)) == 359
    assert compass_heading(radians(180 - 90.2)) == 90


# --- 26, 28: preview of electric motor power
def test_demo_electric_motor_power(ui_env, bundled_fonts):
    from neopedal.ui.widget_preview import _with_preview_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    values = _with_preview_widget(cfg, "electric_motor", dict(cfg.user.setting["electric_motor"]), 1.0, texts)
    assert values["power"] == "175.50kW" and values["regeneration_level"] == "0.00kW"


# --- 29: power to weight ratio unknown until static weight measured
@pytest.mark.parametrize("modern", [True, False])
def test_power_to_weight_ratio_without_weight(widgets, monkeypatch, modern):
    monkeypatch.setattr(minfo.wheels, "totalStaticWeight", 0.0)
    reader(monkeypatch, "engine", "torque", 500.0)
    reader(monkeypatch, "engine", "rpm", 7000.0)
    widget = widgets("engine", modern=modern)
    widget.timerEvent(None)
    ratio = texts(widget)["power_to_weight_ratio"] if modern else widget.bar_pwratio.text
    assert ratio == DASH if modern else ratio == "    -p/w"
    monkeypatch.setattr(minfo.wheels, "totalStaticWeight", 1000.0)
    widget.timerEvent(None)
    ratio = texts(widget)["power_to_weight_ratio"] if modern else widget.bar_pwratio.text
    assert ratio.startswith("0.132")  # peak power so far (smoothed) per kg


# --- 32: modern net change per lap colored by its own sign
def test_engine_temperature_net_change_color(widgets):
    widget = widgets("engine_temperature", show_rate_of_change=True, show_net_change_per_lap=True)
    theme = widget.theme
    assert widget.change_color("▼1.2") == theme.lap_behind and widget.change_color("Δ+3.5") == theme.orange
    assert widget.change_color("▲1.2") == theme.orange and widget.change_color("Δ-3.5") == theme.lap_behind
    assert widget.change_color("0.0") == widget.change_color("Δ0.0") == theme.text_dim
    widget.timerEvent(None)
    widget.grab()  # sub texts drawn in parts


# --- 34, 39: preview of fuel energy saver from consumption of lap so far
def test_demo_fuel_energy_saver_laps(ui_env, bundled_fonts):
    from neopedal.ui.widget_preview import _with_preview_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    laps = _with_preview_widget(cfg, "fuel_energy_saver", dict(cfg.user.setting["fuel_energy_saver"]), 1.0,
                                lambda widget: widget.state[0][widget.center_slot])
    assert laps == "0/15"  # 15.1 laps of energy left (virtual energy preview)


# --- 35-38: fuel energy saver texts
def test_fuel_energy_saver_signed_delta():
    from neopedal.widget.fuel_energy_saver import signed_delta

    assert signed_delta(-0.001, 2, 5) == ("0.00", 2) == signed_delta(0.004, 2, 5)
    assert signed_delta(0.5, 2, 5) == ("+0.50", 1) and signed_delta(-0.5, 2, 5) == ("-0.50", 0)


@pytest.mark.parametrize("modern", [True, False])
def test_fuel_energy_saver_last_lap_and_targets(widgets, modern):
    from neopedal.i18n import tr_overlay

    widget = widgets("fuel_energy_saver", modern=modern, number_of_less_laps=2)
    minfo.fuel.amountCurrent = 5.0
    minfo.fuel.estimatedConsumption = 3.0  # 1 lap left
    widget.timerEvent(None)
    less = widget.center_slot - 1
    if modern:
        laps, uses, deltas = widget.state
        assert uses[widget.column_last] == DASH and laps[less] == DASH
        assert deltas[widget.column_last][0] == tr_overlay("FUEL")
    else:
        assert widget.bars_target_use[widget.column_index_last].text == "-"
        assert widget.bars_target_lap[less].text == "-"


# --- 101: classic cells drawn again only when shown text changes
@pytest.mark.parametrize("name, bars, group, readers", [
    ("electric_motor", ("bar_motor", "bar_torque", "bar_power"), "emotor",
     ("motor_temperature", "torque", "power")),
    ("engine", ("bar_oil", "bar_torque"), "engine", ("oil_temperature", "torque")),
    ("engine_temperature", ("bar_oil_temp",), "engine", ("oil_temperature",)),
])
def test_classic_repaint_on_shown_change_only(widgets, monkeypatch, name, bars, group, readers):
    widget = widgets(name, modern=False)
    painted = []
    for bar in bars:
        monkeypatch.setattr(getattr(widget, bar), "update", lambda bar=bar: painted.append(bar))
    for value in (100.001, 100.002, 100.003):
        for method in readers:
            reader(monkeypatch, group, method, value)
        widget.timerEvent(None)
    assert sorted(painted) == sorted(bars)  # first update only
