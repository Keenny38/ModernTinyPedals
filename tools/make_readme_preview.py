"""
Render README preview image from real widgets: images/readme_preview.png

Widgets are built with default modern settings on simulated LMU telemetry (a car at
speed in a 20 car race), then placed on a dark backdrop like an in game overlay.

Run from project root after visual changes to widgets:
    python tools/make_readme_preview.py
"""

from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication(sys.argv)

from tests.test_readers import lmu_api
from tests.test_widget_benchmark import fill_field
from tinypedal.api_control import api
from tinypedal.main import load_bundled_fonts
from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.userfile.json_setting import copy_setting

OUTPUT = os.path.join("images", "readme_preview.png")
WIDTH, HEIGHT = 1600, 900
KELVIN = 273.15

# Widget name: position (x, y) on the image
LAYOUT = {
    "relative": (40, 40),
    "weather": (1240, 40),
    "deltabest": (640, 250),
    "radar": (650, 330),
    "black_box": (40, 580),
    "pedal": (420, 620),
    "fuel": (1180, 760),
}


def set_telemetry(data):
    """A car at speed, mid corner exit"""
    tele = data.telemetry.telemInfo[0]
    tele.mLocalVel.z = -58.0  # m/s, about 209 km/h
    tele.mEngineRPM = 7150
    tele.mEngineMaxRPM = 8500
    tele.mGear = 5
    tele.mUnfilteredThrottle = tele.mFilteredThrottle = 0.92
    tele.mUnfilteredBrake = tele.mFilteredBrake = 0.0
    tele.mFuel = 42.3
    tele.mFuelCapacity = 90.0
    tele.mRearBrakeBias = 0.438
    tele.mEngineOilTemp = 104
    tele.mEngineWaterTemp = 88
    for index in range(4):
        wheel = tele.mWheels[index]
        front = index < 2
        wheel.mBrakeTemp = KELVIN + (520 if front else 410) + index * 6
        wheel.mPressure = 172 + index
        wheel.mWear = 0.87 - index * 0.01
        wheel.mTireLoad = 4200 if front else 4600
        for layer in range(3):
            wheel.mTemperature[layer] = KELVIN + 78 + layer * 2 + index
            wheel.mTireInnerLayerTemperature[layer] = KELVIN + 80 + layer + index
        wheel.mTireCarcassTemperature = KELVIN + 76 + index
        wheel.mSuspensionDeflection = 0.03
        wheel.mRideHeight = 0.045
    scoring = data.scoring.scoringInfo
    scoring.mNumVehicles = 20
    scoring.mTrackTemp = 31.5
    scoring.mAmbientTemp = 22.0
    scoring.mRaining = 0.0
    scoring.mEndET = 6 * 3600
    scoring.mCurrentET = 2 * 3600 + 1250
    scoring.mSession = 10  # race
    player = data.scoring.vehScoringInfo[0]
    player.mTotalLaps = 42
    player.mPlace = 11
    player.mBestLapTime = 95.412
    player.mLastLapTime = 95.874
    player.mInPits = 0


def place_nearby_cars():
    """Radar: one car alongside on the left, one close behind, the rest out of range"""
    vehicles = minfo.vehicles
    player = vehicles.playerIndex
    nearby = {player: (0.0, 0.0), player - 1: (-2.4, -1.5), player + 1: (0.6, 7.5)}
    for index, data in enumerate(vehicles.dataSet):
        data.relativeRotatedPositionX, data.relativeRotatedPositionY = nearby.get(index, (500.0, 500.0))
        data.relativeOrientationRadians = 0.0
    vehicles.nearestLine = 2.4


def set_modules():
    """Data module outputs the widgets read"""
    delta = minfo.delta
    delta.deltaBest = -0.284
    delta.lapTimeCurrent = 61.35
    delta.lapTimeLast = 95.874
    delta.lapTimeBest = 95.412
    delta.lapTimeEstimated = 95.13
    delta.lapTimeSession = 95.412
    delta.lapTimeStint = 95.6
    delta.deltaLast = -0.51
    delta.deltaSession = -0.284
    delta.deltaStint = -0.46
    delta.lapTimePace = 95.6
    delta.isValidLap = True
    fuel = minfo.fuel
    fuel.capacity = 90.0
    fuel.amountStart = 90.0
    fuel.amountCurrent = 42.3
    fuel.available = True
    fuel.neededRelative = 6.3
    fuel.neededAbsolute = 48.6
    fuel.amountUsedCurrent = 47.7
    fuel.amountEndStint = 1.8
    fuel.lastLapConsumption = 2.94
    fuel.estimatedConsumption = 2.91
    fuel.estimatedLaps = 14.5
    fuel.estimatedMinutes = 23.1
    fuel.estimatedValidConsumption = 2.91
    fuel.deltaConsumption = -0.03
    fuel.oneLessPitConsumption = 2.62
    fuel.estimatedNumPitStopsEnd = 1.53
    fuel.estimatedNumPitStopsEarly = 0.97


def backdrop() -> QPixmap:
    """Dark blurred cockpit-like background"""
    image = QPixmap(WIDTH, HEIGHT)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, 0, HEIGHT)
    sky.setColorAt(0.0, QColor(34, 48, 66))
    sky.setColorAt(0.45, QColor(62, 78, 92))
    sky.setColorAt(0.46, QColor(44, 48, 52))
    sky.setColorAt(1.0, QColor(18, 20, 23))
    painter.fillRect(image.rect(), sky)
    # Track: a road narrowing toward the horizon
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(58, 60, 64))
    painter.drawPolygon([QPointF(560, HEIGHT), QPointF(1180, HEIGHT), QPointF(860, 414), QPointF(820, 414)])
    glow = QRadialGradient(QPointF(840, 380), 520)
    glow.setColorAt(0.0, QColor(255, 210, 150, 60))
    glow.setColorAt(1.0, QColor(255, 210, 150, 0))
    painter.fillRect(image.rect(), glow)
    painter.end()
    return image


def main():
    load_bundled_fonts()
    cfg.default.set_default()
    for name in cfg.user.__slots__:
        setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)))
    fill_field(20)
    place_nearby_cars()
    set_modules()
    sim, data = lmu_api()
    api._api, api.read = sim, sim.reader()
    set_telemetry(data)

    from importlib import import_module

    from PySide6.QtCore import QTimerEvent

    image = backdrop()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for name, (x, y) in LAYOUT.items():
        widget = import_module(f"tinypedal.widget.{name}").Realtime(cfg, name)
        widget.adjustSize()
        for _ in range(3):  # a few updates, so smoothed values settle
            widget.timerEvent(QTimerEvent(0))
        # Render on transparent pixmap: grab() fills translucent areas with an opaque background
        pixmap = QPixmap(widget.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        widget.render(pixmap, renderFlags=QWidget.RenderFlag.DrawChildren)
        painter.drawPixmap(x, y, pixmap)
        widget.deleteLater()
    # Caption
    font = QFont("JetBrains Mono", 13)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 150))
    painter.drawText(QRectF(0, HEIGHT - 34, WIDTH - 24, 24), Qt.AlignmentFlag.AlignRight,
                     "Modern Tiny Pedals · simulated data")
    painter.end()
    image.save(OUTPUT)
    print(f"saved {OUTPUT} ({math.floor(os.path.getsize(OUTPUT) / 1024)} KB)")


if __name__ == "__main__":
    main()
