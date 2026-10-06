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

import contextlib
import functools
import json
import logging
import math
import os
from collections.abc import Callable, Sequence
from typing import NamedTuple

from PySide6.QtCore import QLocale, QMetaObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout

from .. import units
from ..i18n import current_language, tr, trm
from ..setting import cfg
from ..userfile.motec_import import import_ld_file
from ..userfile.telemetry_lap import IMPORT_FOLDER, LapData, LapFile, csv_number, lap_number_of, lap_stem, lap_time_of
from ._common import BaseDialog, UIScaler, singleton_dialog

logger = logging.getLogger(__name__)

LAP_COLORS = tuple(QColor(color) for color in (
    "#38BDF8", "#F97316", "#A3E635", "#E879F9", "#FACC15", "#F43F5E", "#2DD4BF", "#A78BFA",
    # 9th lap onward: hues & lightness apart from first 8
    "#6366F1", "#EC4899", "#10B981", "#D97706", "#06B6D4", "#DC2626", "#84CC16", "#C084FC",
))
COLOR_A = LAP_COLORS[0]  # reference lap
COLOR_B = LAP_COLORS[1]  # first compared lap
VIEWER_SETTING = ".lap_viewer.json"  # visible channels, in telemetry folder
LAP_CACHE_SIZE = 12  # loaded laps kept in memory
GAIN_WINDOW = 40.0  # meters, time gain/loss rate measured over this distance (smooths sampling noise)
GAIN_FULL_SCALE = 0.002  # seconds lost or gained per meter shown with full color
GAIN_COLOR = QColor("#22C55E")
LOSS_COLOR = QColor("#EF4444")
COLORBLIND_GAIN = QColor("#3B82F6")  # gain / loss colors told apart with red-green color blindness
COLORBLIND_LOSS = QColor("#F97316")
RELEASE_DELAY = 180_000  # ms hidden (page in background) before loaded laps are released
BACKGROUND_LOAD_COUNT = 1  # laps to read loaded in background from this count (window stays responsive)


class Channel(NamedTuple):
    """Plotted channel"""

    column: str  # CSV column, computed channel ("delta", "slip_fl"...) or combined panel ("all:...")
    title: str
    unit: str
    weight: float  # relative panel height
    fixed_range: tuple[float, float] | None = None
    group: str = ""  # menu group (per wheel channels)
    quantity: str = ""  # converted to user unit: speed, temperature, pressure, fuel (see display_units)
    sources: tuple[str, ...] = ()  # recorded columns needed (computed channels), column itself if empty
    parts: tuple[str, ...] = ()  # channels drawn together in one panel (combined panel)
    noisy: bool = False  # smoothed by smoothing setting


WHEELS = ("fl", "fr", "rl", "rr")


def wheel_channels(prefix: str, title: str, unit: str, quantity: str = "", sources: tuple[str, ...] = (),
                   noisy: bool = False) -> tuple[Channel, ...]:
    """Channel of each wheel, then the 4 wheels in one panel"""
    wheels = tuple(
        Channel(f"{prefix}_{wheel}", f"{title} {wheel.upper()}", unit, 0.8, group=title, quantity=quantity,
                sources=tuple(source.format(wheel=wheel) for source in sources), noisy=noisy)
        for wheel in WHEELS
    )
    combined = Channel(f"all:{prefix}", f"{title} \N{MULTIPLICATION SIGN}4", unit, 1.2, group=title,
                       quantity=quantity, parts=tuple(channel.column for channel in wheels))
    return (*wheels, combined)


CHANNELS = (
    Channel("delta", "Delta", "s", 1.2),
    Channel("delta_rate", "Time Gain/Loss", "s/100m", 1.0, noisy=True),
    Channel("speed_kph", "Speed", "km/h", 2.0, quantity="speed"),
    Channel("throttle", "Throttle", "", 1.0, (0.0, 1.0)),
    Channel("brake", "Brake", "", 1.0, (0.0, 1.0)),
    Channel("all:pedals", "Throttle & Brake", "", 1.2, (0.0, 1.0), parts=("throttle", "brake")),
    Channel("gear", "Gear", "", 0.8),
    Channel("steering", "Steering", "", 1.0, (-1.0, 1.0)),
    Channel("steering_rate", "Steering Rate", "%/s", 0.8, sources=("steering", "lap_time"), noisy=True),
    Channel("rpm", "RPM", "rpm", 1.0),
    Channel("clutch", "Clutch", "", 0.6, (0.0, 1.0)),
    Channel("fuel", "Fuel", "l", 0.8, quantity="fuel"),
    Channel("fuel_used", "Fuel Used", "l", 0.8, quantity="fuel", sources=("fuel",)),
    Channel("accel_lat", "Lateral G", "G", 1.0, noisy=True),
    Channel("accel_long", "Longitudinal G", "G", 1.0, noisy=True),
    Channel("tc_active", "TC Active", "", 0.5, (0.0, 1.0)),
    Channel("abs_active", "ABS Active", "", 0.5, (0.0, 1.0)),
    Channel("battery", "Battery", "%", 0.8),
    Channel("pos_z", "Elevation", "m", 0.8, quantity="distance"),
    Channel("track_position", "Track Position", "%", 1.0, (-100.0, 100.0), sources=("path_lateral", "track_edge")),
    Channel("path_lateral", "Distance to Center", "m", 0.8, quantity="distance"),
    *wheel_channels("tyre_temp", "Tyre Temp", "°C", "temperature"),
    Channel("tyre_temp_spread", "Tyre Temp Spread", "°C", 0.8, quantity="temperature_delta",
            sources=tuple(f"tyre_temp_{wheel}" for wheel in WHEELS)),
    *wheel_channels("tyre_pres", "Tyre Pressure", "kPa", "pressure"),
    *wheel_channels("tyre_wear", "Tyre Wear", "%"),
    *wheel_channels("brake_temp", "Brake Temp", "°C", "temperature"),
    *wheel_channels("wheel_speed", "Wheel Speed", "km/h", "speed"),
    *wheel_channels("slip", "Wheel Slip", "%", sources=("wheel_speed_{wheel}", "speed_kph"), noisy=True),
    *wheel_channels("ride_height", "Ride Height", "mm", "length"),
    *wheel_channels("susp_defl", "Suspension", "mm", "length"),
    # Recorded from this version: tread edges (camber), tyre load, body slip, driver settings, engine
    *wheel_channels("tyre_temp_in", "Tyre Temp Inner", "°C", "temperature"),
    *wheel_channels("tyre_temp_mid", "Tyre Temp Middle", "°C", "temperature"),
    *wheel_channels("tyre_temp_out", "Tyre Temp Outer", "°C", "temperature"),
    *wheel_channels("camber_spread", "Inner - Outer Temp", "°C", "temperature_delta",
                    sources=("tyre_temp_in_{wheel}", "tyre_temp_out_{wheel}")),
    *wheel_channels("tyre_load", "Tyre Load", "kN"),
    Channel("slip_angle", "Body Slip Angle", "°", 1.0, sources=("vel_lat", "vel_long"), noisy=True),
    Channel("brake_bias", "Brake Bias", "%", 0.6),
    Channel("tc_level", "TC Level", "", 0.5),
    Channel("abs_level", "ABS Level", "", 0.5),
    Channel("engine_map", "Engine Map", "", 0.5),
    Channel("water_temp", "Water Temp", "°C", 0.6, quantity="temperature"),
    Channel("oil_temp", "Oil Temp", "°C", 0.6, quantity="temperature"),
)
CHANNEL_MAP = {channel.column: channel for channel in CHANNELS}
MATH_PREFIX = "math:"  # math channels (user expressions, see quick/math_channels): added to CHANNEL_MAP
TRACK_WIDTH = 12.0  # meters, circuit drawn under driving lines
DEFAULT_CHANNELS = ("delta", "speed_kph", "throttle", "brake", "gear", "steering")
PERCENT_RANGES = ((0.0, 1.0), (-1.0, 1.0))  # pedals & steering fractions shown in percent (track position: %)
DELTA_CHANNELS = ("delta", "delta_rate")  # computed against reference lap, symmetric range
INTEGER_CHANNELS = ("gear", "tc_level", "abs_level", "engine_map")  # whole numbers, drawn as steps
SETTING_CHANNELS = ("tc_level", "abs_level", "engine_map")  # game gives -1 when car has no such setting
CHANNEL_PRESETS = {  # channel menu presets: name, visible channels
    "Default": DEFAULT_CHANNELS,
    "Pedals": ("delta", "speed_kph", "all:pedals", "steering", "gear", "all:slip"),
    "Tyres": ("speed_kph", "all:tyre_temp", "tyre_temp_spread", "all:tyre_pres", "all:tyre_wear"),
    "Brakes": ("speed_kph", "brake", "all:brake_temp", "abs_active", "all:slip"),
    "Suspension": ("speed_kph", "all:ride_height", "all:susp_defl", "accel_lat", "accel_long"),
    "Camber": ("speed_kph", "all:camber_spread", "all:tyre_temp_in", "all:tyre_temp_out", "all:tyre_load"),
    "Car Settings": ("delta", "speed_kph", "brake_bias", "tc_level", "abs_level", "engine_map"),
}
PART_COLORS = {  # sub-channel colors of combined panels when one lap is shown
    "throttle": "#22C55E", "brake": "#EF4444",
    "fl": "#38BDF8", "fr": "#F97316", "rl": "#A3E635", "rr": "#E879F9",
}
SMOOTHING_LEVELS = (0, 3, 7, 15, 31)  # moving average samples of noisy channels, by smoothing setting
DELTA_RATE_WINDOWS = (20, 40, 80, 150)  # meters, time gain/loss measured over (setting)


def math_channel(name: str, unit: str) -> Channel:
    """Plotted channel of a math channel (smoothed like noisy channels: derivatives are)"""
    return Channel(f"{MATH_PREFIX}{name}", name, unit, 1.0, noisy=True)


def set_math_channels(channels: Sequence[Channel]):
    """Math channels of viewer settings put in CHANNEL_MAP (charts, cursor, exports find them like recorded
    channels), former ones removed"""
    for column in [column for column in CHANNEL_MAP if column.startswith(MATH_PREFIX)]:
        del CHANNEL_MAP[column]
    CHANNEL_MAP.update((channel.column, channel) for channel in channels)


FEET_PER_METER = 3.280839895
MM_PER_INCH = 25.4


@functools.lru_cache(maxsize=8)
def _locale_decimal(code: str) -> str:
    return QLocale(code).decimalPoint() or "."


def decimal_point() -> str:
    """Decimal separator of app language (comma in French), numbers shown in pages"""
    return _locale_decimal(current_language())


def localized(text: str) -> str:
    """Number text with decimal separator of app language (lap times keep their dot)"""
    point = decimal_point()
    return text if point == "." else text.replace(".", point)


def number_text(value: float, decimals: int = 0) -> str:
    """Number with decimals, decimal separator of app language"""
    return localized(f"{value:.{decimals}f}")


def distance_unit() -> tuple[float, str]:
    """Factor from meters & symbol of user distance unit (setting: meter or feet)"""
    return (FEET_PER_METER, "ft") if cfg.units["distance_unit"] == "Feet" else (1.0, "m")


def distance_text(meters: float, decimals: int = 0, sign: bool = False) -> str:
    """Distance in user unit with symbol: "120 m", "394 ft", signed if sign ("+12 m", typeset minus sign)"""
    factor, symbol = distance_unit()
    if sign:
        return signed(meters * factor, decimals, f" {symbol}")
    return f"{number_text(meters * factor, decimals)} {symbol}"


def display_units() -> dict[str, tuple[Callable[[float], float] | None, str]]:
    """Conversion (None if same unit) & symbol of each quantity, from user units setting

    Lap files store km/h, °C, kPa, liters, meters (elevation, distance to center) & millimeters (ride height,
    suspension): feet & inches when user distance unit is feet.
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
    feet = cfg.units["distance_unit"] == "Feet"
    return {
        "distance": ((lambda value: value * FEET_PER_METER), "ft") if feet else (None, "m"),
        "length": ((lambda value: value / MM_PER_INCH), "in") if feet else (None, "mm"),
        "speed": speed_unit,
        "temperature": (
            units.set_unit_temperature(temperature) if temperature == "Fahrenheit" else None,
            units.set_symbol_temperature(temperature)),
        "temperature_delta": (  # temperature difference: no offset
            (lambda value: value * 1.8) if temperature == "Fahrenheit" else None,
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
    clean: bool = True  # valid lap, not out or in lap (may count in ideal lap & mini-sectors)


def lap_color(slot: int) -> QColor:
    """Color of shown lap by color slot: palette colors, then lighter & darker turns of them"""
    color = LAP_COLORS[slot % len(LAP_COLORS)]
    turn = slot // len(LAP_COLORS)
    if not turn:
        return QColor(color)
    return color.lighter(100 + 35 * ((turn + 1) // 2)) if turn % 2 else color.darker(100 + 35 * (turn // 2))


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


def part_label(column: str) -> str:
    """Short name of a combined panel sub-channel: FL, Throttle"""
    if column[-3:-2] == "_" and column[-2:] in WHEELS:
        return column[-2:].upper()
    return tr(CHANNEL_MAP[column].title) if column in CHANNEL_MAP else column


def part_color(column: str) -> str:
    """Sub-channel color of a combined panel (one lap shown)"""
    return PART_COLORS.get(column[-2:] if column[-3:-2] == "_" else column, "#9CA3AF")


def shade(color: QColor, index: int, count: int) -> QColor:
    """Lap color made lighter or darker for each sub-channel of a combined panel (several laps shown)"""
    if count <= 1:
        return QColor(color)
    factor = 140 - int(80 * index / (count - 1))  # 140% lighter to 60% darker
    return color.lighter(factor) if factor >= 100 else color.darker(int(10000 / factor))


def format_value(value: float) -> str:
    """Cursor value, 2 decimals, none for whole numbers (gear), decimal separator of app language"""
    text = f"{value:.2f}"
    return text[:-3] if text.endswith(".00") else localized(text)


def format_channel_value(channel: Channel, value: float) -> str:
    """Value of channel for cursor & axis labels: pedals & steering in percent, signed deltas"""
    if channel.fixed_range in PERCENT_RANGES:
        return f"{value * 100:.0f}%"
    if channel.column == "delta":
        return localized(f"{value:+.3f}")
    if channel.column == "delta_rate":
        return localized(f"{value:+.2f}")
    if channel.column in INTEGER_CHANNELS:
        return f"{value:.0f}"
    return format_value(value)


def format_axis_value(channel: Channel, value: float, span: float) -> str:
    """Value range label of channel panel"""
    if channel.fixed_range in PERCENT_RANGES or channel.column in DELTA_CHANNELS or channel.column in INTEGER_CHANNELS:
        return format_channel_value(channel, value)
    if span >= 20:
        return f"{value:.0f}"
    if span >= 2:
        return number_text(value, 1)
    return number_text(value, 2)


def format_laptime(seconds: float) -> str:
    """Lap time text, "-" if unknown"""
    if seconds <= 0:
        return "-"
    minutes, seconds = divmod(round(seconds, 3), 60)  # rounded first: 119.9996 is 2:00.000, not 1:60.000
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
    """Update lap viewer settings, other saved values kept

    Written to a temporary file then renamed: a crash while writing never leaves a broken file.
    """
    setting = load_viewer_setting(folder)
    setting.update(values)
    target = os.path.join(folder, VIEWER_SETTING)
    temporary = f"{target}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(setting, file)
        os.replace(temporary, target)
    except OSError as error:
        logger.warning("LAP VIEWER: unable to save setting: %s", error)
        with contextlib.suppress(OSError):
            os.remove(temporary)


def save_visible_channels(folder: str, columns: list[str]):
    save_viewer_setting(folder, channels=columns)



def delta_limit(series: Sequence[Sequence[float]]) -> float:
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


GAIN_SHADES = 64  # gain / loss color steps (colors shared, not made for each map point)
_gain_shades: dict[tuple[bool, bool], list[QColor]] = {}


def gain_color(rate: float, colorblind: bool = False) -> QColor:
    """Time gain / loss rate color (s/m): red when losing time, green when gaining, neutral grey when even

    Colorblind palette: orange losing, blue gaining. Returned color is shared: never change it.
    """
    shades = _gain_shades.get((rate > 0, colorblind))
    if shades is None:
        if colorblind:
            target = COLORBLIND_LOSS if rate > 0 else COLORBLIND_GAIN
        else:
            target = LOSS_COLOR if rate > 0 else GAIN_COLOR
        neutral = QColor("#9CA3AF")
        shades = _gain_shades[(rate > 0, colorblind)] = [QColor(
            round(neutral.red() + (target.red() - neutral.red()) * level / GAIN_SHADES),
            round(neutral.green() + (target.green() - neutral.green()) * level / GAIN_SHADES),
            round(neutral.blue() + (target.blue() - neutral.blue()) * level / GAIN_SHADES),
        ) for level in range(GAIN_SHADES + 1)]
    return shades[round(min(abs(rate) / GAIN_FULL_SCALE, 1.0) * GAIN_SHADES)]


def lap_positions(lap: LapData | None) -> list[tuple[float, float, float]]:
    """(distance, x, y) of lap, empty if positions not recorded"""
    if lap is None:
        return []
    xs, ys = lap.columns.get("pos_x"), lap.columns.get("pos_y")
    if not xs or not ys:
        return []
    return [(distance, x, y) for distance, x, y in zip(lap.distance, xs, ys) if x or y]


def signed(value: float, decimals: int = 0, unit: str = "") -> str:
    """Signed number text, minus sign as typeset, decimal separator of app language"""
    return f"{localized(f'{value:+.{decimals}f}')}{unit}".replace("-", chr(0x2212))  # minus sign


class LapEntry(NamedTuple):
    """Lap list entry"""

    file: LapFile
    info: dict
    external: bool = False
    foreign: bool = False  # imported from another driver's folder (teammate, shared folder)


def import_motec_log(window, filename: str) -> str:
    """Import MoTeC log (dropped on app) to imported laps in lap viewer page, returns message

    Log read in background by lap viewer page (a long log takes seconds): its laps are shown once read, result
    in page status line.
    """
    from .tools_view import open_tool

    name = os.path.basename(filename)
    try:
        os.stat(filename)
    except OSError as error:
        logger.error("LAP VIEWER: unable to import %s: %s", filename, error)
        return trm(f"Unable to import <b>{name}</b>: {error.strerror or error}")
    open_tool("lap_viewer.LapViewer", window)
    viewers = [  # LapViewer name is singleton wrapper, not class
        viewer for viewer in window.findChildren(BaseDialog)
        if type(viewer).__name__ == "LapViewer" and viewer.isVisibleTo(window)
    ]
    if viewers:
        viewers[-1].backend.import_motec([filename])
        return trm(f"Importing MoTeC log: <b>{name}</b>...")
    # Viewer not available: imported now
    try:
        paths = import_ld_file(filename, os.path.join(cfg.path.telemetry, IMPORT_FOLDER))
    except (OSError, ValueError) as error:
        logger.error("LAP VIEWER: unable to import %s: %s", filename, error)
        return trm(f"Unable to import <b>{name}</b>: {error}")
    if not paths:
        return trm(f"No complete lap in: {name}")
    return trm(f"MoTeC log imported: <b>{name}</b> ({len(paths)} laps)")


@singleton_dialog("lap_viewer")
class LapViewer(BaseDialog):
    """Recorded lap telemetry viewer (Qt Quick page)

    Loaded laps (several MB each) are released after a while in background, reloaded when shown again.
    Emits page_minimum_changed when page needs another width (language, toolbar buttons shown).
    """

    page_minimum_changed = Signal()

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
        self.view.setFocus()  # page keys work without clicking it first
        content = self.page_content()
        if content is not None:
            content.implicitWidthChanged.connect(self.page_minimum_changed)
        self.resize(UIScaler.size(90), UIScaler.size(48))
        # Deleted laps restored: shortcut of this page only (a QML shortcut also matched while another page of app
        # window was shown), text fields keep their own undo (shortcut override)
        self.undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.backend.undoDelete)
        self.backend.undoChanged.connect(self.update_undo_shortcut)
        self.update_undo_shortcut()
        self.backend.refresh()

    def update_undo_shortcut(self):
        self.undo_shortcut.setEnabled(self.backend.undoText != "")

    def page_content(self):
        """Toolbar, panels & status line of page (root ColumnLayout of LapViewer.qml), None if not loaded"""
        root = self.view.rootObject()
        if root is None:
            return None
        return next((item for item in root.childItems() if item.metaObject().className() == "QQuickColumnLayout"), None)

    def page_minimum_size(self) -> QSize:
        """Page area minimum while shown in app window (see app.DialogPage), cut below: toolbar at its
        full width (its buttons never shrink) and lap list, charts & side panel at their minimum width
        (LapViewer.qml SplitView, 62 em with handles & margins)"""
        width = UIScaler.size(64.6)
        content = self.page_content()
        if content is not None:  # toolbar, with page margins on both sides
            width = max(width, math.ceil(content.implicitWidth() + 2 * content.x()))
        return QSize(width, 0)

    def focus_charts(self):
        """Keys to charts: dialog shown as window gives them to first control of page (track list, lap search),
        page of app window shown has none"""
        if not self.isVisible():
            return
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        root = self.view.rootObject()
        if root is not None:
            QMetaObject.invokeMethod(root, "focusCharts")

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
        if not event.spontaneous():  # page shown (not app window restored): after focus given by dialog show
            QTimer.singleShot(0, self, self.focus_charts)

    def closeEvent(self, event):
        self.backend.release()
        super().closeEvent(event)
        if event.isAccepted():  # QML gone before the backend it binds to (deleted first: created first)
            self.view.setSource(QUrl())


def format_csv_number(value: float, decimal: str) -> str:
    """Number with up to 4 decimals, locale decimal separator"""
    return csv_number(value, decimal)

