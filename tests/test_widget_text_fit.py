"""Modern design text fits its cell with the widest values, in every unit & format

Widgets size cells from sample texts at creation. A sample written for one unit (2 digit
Celsius, meters, a 24 hour clock...) cuts the value shown in another one. Every modern
widget is rendered with all parts shown and large but real values (Le Mans gaps & distances,
hot brakes in Fahrenheit, 100% CPU...), and every text drawn must fit its cell.
"""

import os
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication, QTimerEvent

from tests.test_readers import lmu_api
from tests.test_widget_benchmark import drive, fill_field
from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.template.widget.modern import MODERN_DESIGNS
from tinypedal.widget._modern import base, create_widget, uses_modern_design

IMPERIAL = {
    "distance_unit": "Feet", "fuel_unit": "Gallon", "odometer_unit": "Mile", "power_unit": "Horsepower",
    "speed_unit": "MPH", "temperature_unit": "Fahrenheit", "turbo_pressure_unit": "psi",
    "tyre_pressure_unit": "psi", "weight_unit": "Pound",
}
UNITS = {"metric": {}, "imperial": IMPERIAL, "feet & kilometers": {"distance_unit": "Feet", "odometer_unit": "Kilometer"}}
# Options with formats or decimals that make values wider than defaults
WIDE_OPTIONS = {
    "session": {"system_clock_format": "%I:%M:%S %p"},
    "track_clock": {"track_clock_format": "%I:%M:%S %p", "enable_time_scaled_countdown": True},
    "suspension_force": {"decimal_places": 2, "show_force_ratio": False},
    "system_performance": {"average_samples": 1},
    "race_plan": {"layout": 1},
}
FIELD_ATTRIBUTES = {
    minfo.vehicles: (
        "dataSet", "dataSetVersion", "totalVehicles", "playerIndex", "leaderIndex", "leaderBestLapTime",
        "nearestLine", "nearestTraffic", "totalCompletedLaps",
    ),
    minfo.relative: ("standings", "drawOrder", "relativeAhead", "relativeBehind"),
}


@pytest.fixture
def live(ui_env, bundled_fonts, monkeypatch):
    """API reader on in-memory shared memory, field of cars in data module output"""
    from tinypedal.api_control import api

    sim, data = lmu_api()
    monkeypatch.setattr(api, "_api", sim)
    monkeypatch.setattr(api, "read", sim.reader())
    for owner, names in FIELD_ATTRIBUTES.items():
        for name in names:  # restored after test
            monkeypatch.setattr(owner, name, getattr(owner, name))
    fill_field(20)
    return data


def widest_values(data, monkeypatch):
    """Large but real readings: Le Mans field, hot car, 100% CPU"""
    import psutil

    info = data.scoring.scoringInfo
    info.mSession = 10  # race
    data.scoring.vehScoringInfo[0].mTotalLaps = 350
    info.mTrackTemp = 45.0  # 113 °F
    info.mAmbientTemp = 40.0
    tele = data.telemetry.telemInfo[0]
    tele.mSpeedLimiter = 1
    tele.mLocalVel.z = -95.0  # 342 km/h
    tele.mEngineRPM = 12000.0
    tele.mEngineMaxRPM = 12500.0
    tele.mEngineWaterTemp = 125.0
    tele.mEngineOilTemp = 135.0
    tele.mFuel = 110.0
    tele.mFuelCapacity = 110.0
    for wheel in tele.mWheels:
        wheel.mBrakeTemp = 273.15 + 1100
        wheel.mPressure = 260.0
        wheel.mTireCarcassTemperature = 273.15 + 130
        wheel.mSuspForce = 12345.67
        for layer in range(3):
            wheel.mTemperature[layer] = 273.15 + 135
            wheel.mTireInnerLayerTemperature[layer] = 273.15 + 135
    cars = minfo.vehicles.dataSet
    player = cars[minfo.vehicles.playerIndex]
    ahead, behind = cars[player.classAheadIndex], cars[player.classBehindIndex]  # also nearest on track
    ahead.gapBehindLeader = ahead.gapBehindNext = 150.4  # sparse field at Le Mans
    player.gapBehindNextInClass = 150.4
    behind.gapBehindNextInClass = 123.7
    ahead.qualifyInClass, ahead.positionInClass = 20, 2  # gained 18 places
    behind.inPit = 1
    behind.pitTimer.pitting = True
    behind.pitTimer.elapsed = 123.4  # long stop
    monkeypatch.setattr(minfo.relative, "relativeAhead", [(150.4, player.classAheadIndex)])
    monkeypatch.setattr(minfo.relative, "relativeBehind", [(-123.7, player.classBehindIndex)])
    monkeypatch.setattr(minfo.stats, "metersDriven", 2e9)  # odometer at its maximum digits
    monkeypatch.setattr(minfo.wheels, "currentSuspensionPosition", [123.45] * 4)
    monkeypatch.setattr(psutil, "cpu_percent", lambda *args, **kwargs: 100.0)
    # App on every core (a real reading depends on the machine: 1026.88% once on a CI runner)
    monkeypatch.setattr(psutil.Process, "cpu_percent", lambda self, *args, **kwargs: 100.0 * (os.cpu_count() or 1))


def wide_plan(widget):
    """Le Mans race plan, late in race: 3 digit stop laps, big refuel"""
    from tinypedal.fuel_strategy import PitStop, Strategy

    widget.refresh_plan = lambda: None
    widget.strategy = Strategy(race_laps=378, stints=[14] * 27,
                               stops=[PitStop(lap, 105.5, 100.0, True) for lap in range(14, 378, 14)])


WIDGET_SETUP = {"race_plan": wide_plan}


@pytest.fixture(params=["English", "Français"])
def language(request):
    """Overlay labels in each bundled language (French labels are often longer)"""
    from tinypedal import i18n

    i18n.set_language(request.param)
    yield request.param
    i18n.set_language("English")


@pytest.mark.parametrize("units", list(UNITS))
def test_modern_text_fits_cells(live, monkeypatch, language, units):
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    cfg.units.update(UNITS[units])
    cut = set()
    draw_text = base.ModernOverlay.draw_text

    def checked(self, painter, rect, text, role="value", color=None, align=base.LEFT, elide=True):
        if text:
            shown = text.upper() if role in self._caps_roles else text
            width = self.advance(role, shown)
            if width > rect.width() + 0.5:
                cut.add(f"{self.widget_name}: {text!r} ({role}) {width:.1f} > {rect.width():.1f} px")
        return draw_text(self, painter, rect, text, role, color, align, elide)

    monkeypatch.setattr(base.ModernOverlay, "draw_text", checked)
    widest_values(live, monkeypatch)
    event = QTimerEvent(0)
    for name in sorted(MODERN_DESIGNS):
        options = cfg.user.setting[name]
        for key, value in options.items():
            if isinstance(value, bool) and key.startswith(("show_", "column_")) and "caption" not in key:
                options[key] = True
        options.update(WIDE_OPTIONS.get(name, {}))
        if not uses_modern_design(cfg, name):
            continue
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        try:
            if name in WIDGET_SETUP:
                WIDGET_SETUP[name](widget)
            widget.adjustSize()
            for frame in range(3):
                drive(live, frame)
                widget.timerEvent(event)
                widget.grab()
        finally:
            widget.deleteLater()
    QCoreApplication.processEvents()
    assert not cut, f"text cut ({language}, {units}):\n" + "\n".join(sorted(cut))
