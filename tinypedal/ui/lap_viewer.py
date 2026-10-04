#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Lap telemetry viewer: compare recorded laps along distance

Qt Quick page (ui/qml/LapViewer.qml) with charts, track map, G circle & corners drawn by GPU,
state in quick/lap_backend.py. This module keeps channels, value formats & viewer settings.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout

from .. import units
from ..i18n import tr, trm
from ..setting import cfg
from ..userfile.motec_import import import_ld_file
from ..userfile.telemetry_lap import IMPORT_FOLDER, LapData, LapFile, lap_number_of, lap_stem, lap_time_of
from ._common import BaseDialog, UIScaler, singleton_dialog

logger = logging.getLogger(__name__)

LAP_COLORS = tuple(QColor(color) for color in (
    "#38BDF8", "#F97316", "#A3E635", "#E879F9", "#FACC15", "#F43F5E", "#2DD4BF", "#A78BFA",
))
COLOR_A = LAP_COLORS[0]  # reference lap
COLOR_B = LAP_COLORS[1]  # first compared lap
VIEWER_SETTING = ".lap_viewer.json"  # visible channels, in telemetry folder
LAP_CACHE_SIZE = 12  # loaded laps kept in memory
GAIN_WINDOW = 40.0  # meters, time gain/loss rate measured over this distance (smooths sampling noise)
GAIN_FULL_SCALE = 0.002  # seconds lost or gained per meter shown with full color
GAIN_COLOR = QColor("#22C55E")
LOSS_COLOR = QColor("#EF4444")
RELEASE_DELAY = 180_000  # ms hidden (page in background) before loaded laps are released
BACKGROUND_LOAD_COUNT = 3  # laps to read at once loaded in background (window stays responsive)


class Channel(NamedTuple):
    """Plotted channel"""

    column: str  # CSV column, "delta" for computed time delta
    title: str
    unit: str
    weight: float  # relative panel height
    fixed_range: tuple[float, float] | None = None
    group: str = ""  # menu group (per wheel channels)
    quantity: str = ""  # converted to user unit: speed, temperature, pressure, fuel (see display_units)


def wheel_channels(prefix: str, title: str, unit: str, quantity: str = "") -> tuple[Channel, ...]:
    return tuple(
        Channel(f"{prefix}_{wheel}", f"{title} {wheel.upper()}", unit, 0.8, group=title, quantity=quantity)
        for wheel in ("fl", "fr", "rl", "rr")
    )


CHANNELS = (
    Channel("delta", "Delta", "s", 1.2),
    Channel("delta_rate", "Time Gain/Loss", "s/100m", 1.0),
    Channel("speed_kph", "Speed", "km/h", 2.0, quantity="speed"),
    Channel("throttle", "Throttle", "", 1.0, (0.0, 1.0)),
    Channel("brake", "Brake", "", 1.0, (0.0, 1.0)),
    Channel("gear", "Gear", "", 0.8),
    Channel("steering", "Steering", "", 1.0, (-1.0, 1.0)),
    Channel("rpm", "RPM", "rpm", 1.0),
    Channel("clutch", "Clutch", "", 0.6, (0.0, 1.0)),
    Channel("fuel", "Fuel", "l", 0.8, quantity="fuel"),
    Channel("accel_lat", "Lateral G", "G", 1.0),
    Channel("accel_long", "Longitudinal G", "G", 1.0),
    Channel("tc_active", "TC Active", "", 0.5, (0.0, 1.0)),
    Channel("abs_active", "ABS Active", "", 0.5, (0.0, 1.0)),
    Channel("battery", "Battery", "%", 0.8),
    Channel("pos_z", "Elevation", "m", 0.8),
    *wheel_channels("tyre_temp", "Tyre Temp", "°C", "temperature"),
    *wheel_channels("tyre_pres", "Tyre Pressure", "kPa", "pressure"),
    *wheel_channels("tyre_wear", "Tyre Wear", "%"),
    *wheel_channels("brake_temp", "Brake Temp", "°C", "temperature"),
    *wheel_channels("wheel_speed", "Wheel Speed", "km/h", "speed"),
    *wheel_channels("ride_height", "Ride Height", "mm"),
    *wheel_channels("susp_defl", "Suspension", "mm"),
)
CHANNEL_MAP = {channel.column: channel for channel in CHANNELS}
TRACK_WIDTH = 12.0  # meters, circuit drawn under driving lines
DEFAULT_CHANNELS = ("delta", "speed_kph", "throttle", "brake", "gear", "steering")
PERCENT_RANGES = ((0.0, 1.0), (-1.0, 1.0))  # pedals & steering fractions shown in percent
DELTA_CHANNELS = ("delta", "delta_rate")  # computed against reference lap, symmetric range


def display_units() -> dict[str, tuple[Callable[[float], float] | None, str]]:
    """Conversion (None if same unit) & symbol of each quantity, from user units setting

    Lap files store km/h, °C, kPa & liters.
    """
    speed = cfg.units["speed_unit"]
    if speed == "MPH":
        speed_unit: tuple[Callable[[float], float] | None, str] = (lambda value: value / 1.609344, "mph")
    elif speed == "m/s":
        speed_unit = (lambda value: value / 3.6, "m/s")
    else:
        speed_unit = (None, "km/h")
    temperature = cfg.units["temperature_unit"]
    pressure = cfg.units["tyre_pressure_unit"]
    fuel = cfg.units["fuel_unit"]
    return {
        "speed": speed_unit,
        "temperature": (
            units.set_unit_temperature(temperature) if temperature == "Fahrenheit" else None,
            units.set_symbol_temperature(temperature)),
        "pressure": (
            units.set_unit_pressure(pressure) if pressure in ("psi", "bar") else None,
            units.set_symbol_pressure(pressure)),
        "fuel": (units.set_unit_fuel(fuel) if fuel == "Gallon" else None, units.set_symbol_fuel(fuel)),
    }


def nice_step(span: float, count: float) -> float:
    """Round axis step (1, 2 or 5 x 10^n) giving about count steps over span"""
    raw = max(span / max(count, 1.0), 1e-9)
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 5, 10):
        if raw <= multiple * magnitude:
            return multiple * magnitude
    return 10 * magnitude


def format_axis_time(seconds: float) -> str:
    """Time axis label: 45s, 1:05"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}:{seconds:02.0f}"


def corner_label(number: int) -> str:
    """Short corner name: T1 (V1 in French)"""
    return trm(f"T{number}")


class PlotLap(NamedTuple):
    """Displayed lap"""

    key: str  # file path
    label: str
    data: LapData
    color: QColor


def lap_label(filename: str) -> str:
    """Short lap name from file name: "Lap 12 · 1:30.123" (file name if not a recorded lap name)"""
    number = lap_number_of(filename)
    if not number:
        return lap_stem(filename)
    text = trm(f"Lap {number}")
    lap_time = lap_time_of(filename)
    return f"{text} · {format_laptime(lap_time)}" if lap_time > 0 else text


def channel_title(channel: Channel) -> str:
    """Translated channel title, wheel suffix kept (Tyre Temp FL)"""
    if channel.group:
        return tr(channel.group) + channel.title[len(channel.group):]
    return tr(channel.title)


def format_value(value: float) -> str:
    """Cursor value, 2 decimals, none for whole numbers (gear)"""
    text = f"{value:.2f}"
    return text[:-3] if text.endswith(".00") else text


def format_channel_value(channel: Channel, value: float) -> str:
    """Value of channel for cursor & axis labels: pedals & steering in percent, signed deltas"""
    if channel.fixed_range in PERCENT_RANGES:
        return f"{value * 100:.0f}%"
    if channel.column == "delta":
        return f"{value:+.3f}"
    if channel.column == "delta_rate":
        return f"{value:+.2f}"
    if channel.column == "gear":
        return f"{value:.0f}"
    return format_value(value)


def format_axis_value(channel: Channel, value: float, span: float) -> str:
    """Value range label of channel panel"""
    if channel.fixed_range in PERCENT_RANGES or channel.column in DELTA_CHANNELS or channel.column == "gear":
        return format_channel_value(channel, value)
    if span >= 20:
        return f"{value:.0f}"
    if span >= 2:
        return f"{value:.1f}"
    return f"{value:.2f}"


def format_laptime(seconds: float) -> str:
    """Lap time text, "-" if unknown"""
    if seconds <= 0:
        return "-"
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}:{seconds:06.3f}" if minutes else f"{seconds:.3f}"


def load_visible_channels(folder: str) -> list[str]:
    """Visible channels saved in telemetry folder"""
    try:
        with open(os.path.join(folder, VIEWER_SETTING), encoding="utf-8") as file:
            columns = json.load(file).get("channels", [])
        columns = [column for column in columns if column in CHANNEL_MAP]
        return columns or list(DEFAULT_CHANNELS)
    except (OSError, ValueError, AttributeError):
        return list(DEFAULT_CHANNELS)


def load_viewer_setting(folder: str) -> dict:
    """Lap viewer settings (visible channels, corner sensitivity) saved in telemetry folder"""
    try:
        with open(os.path.join(folder, VIEWER_SETTING), encoding="utf-8") as file:
            setting = json.load(file)
        return setting if isinstance(setting, dict) else {}
    except (OSError, ValueError):
        return {}


def save_viewer_setting(folder: str, **values):
    """Update lap viewer settings, other saved values kept"""
    setting = load_viewer_setting(folder)
    setting.update(values)
    try:
        with open(os.path.join(folder, VIEWER_SETTING), "w", encoding="utf-8") as file:
            json.dump(setting, file)
    except OSError as error:
        logger.warning("LAP VIEWER: unable to save setting: %s", error)


def save_visible_channels(folder: str, columns: list[str]):
    save_viewer_setting(folder, channels=columns)



def delta_limit(series: list[list[float]]) -> float:
    """Delta chart half range: 95th percentile of each lap's delta, lowest median of laps

    An aberrant lap (cut short, spin) would otherwise flatten every other lap's delta;
    its line is clipped instead.
    """
    limits = []
    for values in series:
        if values:
            ordered = sorted(abs(value) for value in values)
            limits.append(ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)])
    if not limits:
        return 0.1
    limits.sort()
    return max(limits[(len(limits) - 1) // 2] * 1.15, 0.1)


def gain_color(rate: float) -> QColor:
    """Time gain / loss rate color (s/m): red when losing time, green when gaining, neutral grey when even"""
    amount = min(abs(rate) / GAIN_FULL_SCALE, 1.0)
    target = LOSS_COLOR if rate > 0 else GAIN_COLOR
    neutral = QColor("#9CA3AF")
    return QColor(
        round(neutral.red() + (target.red() - neutral.red()) * amount),
        round(neutral.green() + (target.green() - neutral.green()) * amount),
        round(neutral.blue() + (target.blue() - neutral.blue()) * amount),
    )


def lap_positions(lap: LapData | None) -> list[tuple[float, float, float]]:
    """(distance, x, y) of lap, empty if positions not recorded"""
    if lap is None:
        return []
    xs, ys = lap.columns.get("pos_x"), lap.columns.get("pos_y")
    if not xs or not ys:
        return []
    return [(distance, x, y) for distance, x, y in zip(lap.distance, xs, ys) if x or y]


def signed(value: float, decimals: int = 0, unit: str = "") -> str:
    """Signed number text, minus sign as typeset"""
    return f"{value:+.{decimals}f}{unit}".replace("-", chr(0x2212))  # minus sign


class LapEntry(NamedTuple):
    """Lap list entry"""

    file: LapFile
    info: dict
    external: bool = False


def import_motec_log(window, filename: str) -> str:
    """Import MoTeC log (dropped on app) to imported laps, shown in lap viewer page, returns message"""
    from .tools_view import open_tool

    name = os.path.basename(filename)
    try:
        paths = import_ld_file(filename, os.path.join(cfg.path.telemetry, IMPORT_FOLDER))
    except (OSError, ValueError) as error:
        logger.error("LAP VIEWER: unable to import %s: %s", filename, error)
        return trm(f"Unable to import <b>{name}</b>: {error}")
    if not paths:
        return trm(f"No complete lap in: {name}")
    open_tool("lap_viewer.LapViewer", window)
    viewers = [  # LapViewer name is singleton wrapper, not class
        viewer for viewer in window.findChildren(BaseDialog)
        if type(viewer).__name__ == "LapViewer" and viewer.isVisibleTo(window)
    ]
    if viewers:
        viewers[-1].add_external(paths, paths)
    return trm(f"MoTeC log imported: <b>{name}</b> ({len(paths)} laps)")


@singleton_dialog("lap_viewer")
class LapViewer(BaseDialog):
    """Recorded lap telemetry viewer (Qt Quick page)

    Loaded laps (several MB each) are released after a while in background, reloaded when shown again.
    """

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.lap_backend import LapViewerBackend

        super().__init__(parent)
        self.set_utility_title(tr("Lap Telemetry Viewer"))
        self.filepath = cfg.path.telemetry
        self.backend = LapViewerBackend(self, self.filepath)
        self.view = create_quick_view(self, "LapViewer.qml", {"backend": self.backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(90), UIScaler.size(48))
        self.backend.refresh()

    def is_loading(self) -> bool:
        return self.backend.is_loading()

    def add_external(self, lap_paths: list[str], reference_from: list[str] | None = None):
        """Show laps from other folders (imported log), fastest of reference_from laps as reference"""
        self.backend.add_external(lap_paths, reference_from)

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def showEvent(self, event):
        self.backend.page_shown()
        super().showEvent(event)

    def closeEvent(self, event):
        self.backend.release()
        super().closeEvent(event)


def format_csv_number(value: float, decimal: str) -> str:
    """Number with up to 4 decimals, locale decimal separator"""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", decimal) if decimal != "." else text

