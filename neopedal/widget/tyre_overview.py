#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
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
Tyre overview Widget

One card per tyre, placed as on the car (front left, front right, rear left, rear right): compound & alert
(puncture, flat spot, detached wheel), surface temperatures (inner / center / outer) colored by heatmap,
carcass & inner layer temperatures, hot pressure against target range, tread left with wear per lap and laps
left. Each part can be turned off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from .. import units
from ..api_control import api
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ..template.widget.black_box_ui import parse_compound_targets, pressure_target_kpa
from ..userfile.heatmap import select_compound_symbol
from ._base import Overlay
from ._common import tyre_punctured
from ._data import shown_temperature
from ._modern.draw import readable_on
from ._modern.quad import heat_color
from ._modern.rows import compound_badge
from ._modern.wheels import TyreCompounds
from ._race_aids import CENTER, LEFT, RIGHT, ClassicCells, option_colors

if TYPE_CHECKING:
    from ..template.widget_config_types import TyreOverviewConfig

DASH = chr(0x2013)
WHEELS = ("FL", "FR", "RL", "RR")
ALERTS = {"detached": "Detached", "puncture": "Puncture", "flat": "Flat spot"}  # most important first
NO_READING = -100.0  # Celsius, temperature under this is not read
PRESSURE_LOW, PRESSURE_OK, PRESSURE_HIGH = -1, 0, 1


class WheelCard(NamedTuple):
    """Values of one tyre card (one update), rounded as shown: card drawn again only once a text changes"""

    compound: str = ""  # compound symbol ("" unknown or not shown)
    compound_color: QColor | None = None
    alert: str = ""  # ALERTS key, "" none
    temps: tuple[float, ...] = ()  # surface temperatures (Celsius, rounded): inner, center, outer or average
    carcass: float = NO_READING
    inner: float = NO_READING
    pressure: float = 0.0  # kPa
    pressure_state: int = PRESSURE_OK
    remaining: float = -1.0  # tread left (percent), -1 unknown
    wear: float = 0.0  # tread worn per lap (percent)
    laps: float = -1.0  # estimated laps left on this tread, -1 unknown


def shown_wear(value: float) -> float:
    """Wear per lap rounded as shown (2 decimals), wear under 0.005 kept above 0 (shown 0.00, not as none)"""
    return round(value, 2) or (0.001 if value > 0 else 0.0)


def shown_laps(value: float) -> float:
    """Laps left rounded as shown: 1 decimal under 10, whole laps under 100, 100 for 99+ (-1 unknown kept)"""
    if value >= 100:
        return 100.0
    return round(value, 0) if value >= 10 else round(value, 1)


def temperature_valid(value: float) -> bool:
    return NO_READING < value < 1000


def pressure_state(pressure: float, target: tuple[float, float]) -> int:
    """Pressure against target range (kPa), PRESSURE_OK without reading or range"""
    low, high = target
    if pressure <= 0 or high <= 0:
        return PRESSURE_OK
    if pressure < low:
        return PRESSURE_LOW
    if pressure > high:
        return PRESSURE_HIGH
    return PRESSURE_OK


def tyre_alert(detached: bool, puncture: bool, locking_wear: float, flat_threshold: float) -> str:
    """Tyre alert, most important first ("" none)"""
    if detached:
        return "detached"
    if puncture:
        return "puncture"
    if flat_threshold > 0 and locking_wear >= flat_threshold:
        return "flat"
    return ""


class TyreOverviewMixin:
    """Readings of the four tyre cards, for classic & modern widget"""

    wcfg: TyreOverviewConfig
    cfg: Any

    def setup_overview(self):
        """Options, compound tracking, pressure targets"""
        wcfg = self.wcfg
        self.show_label = bool(wcfg["show_wheel_label"])
        self.show_compound = bool(wcfg["show_tyre_compound"])
        self.show_alerts = bool(wcfg["show_tyre_alerts"])
        self.flat_threshold = max(float(wcfg["flat_spot_threshold"]), 0.0)
        self.show_surface = bool(wcfg["show_surface_temperature"])
        self.ico = bool(wcfg["show_inner_center_outer"])
        self.show_carcass = bool(wcfg["show_carcass_temperature"])
        self.show_inner = bool(wcfg["show_inner_layer_temperature"])
        self.show_pressure = bool(wcfg["show_pressure"])
        self.show_pressure_unit = bool(wcfg["show_pressure_unit"])
        self.use_target = self.show_pressure and bool(wcfg["enable_tyre_pressure_target"])
        self.show_wear = bool(wcfg["show_wear"])
        self.show_wear_lap = bool(wcfg["show_wear_per_lap"])
        self.show_laps = bool(wcfg["show_lifespan_laps"])
        self.need_wear = self.show_wear or self.show_wear_lap or self.show_laps
        self.show_caption = self.show_label or self.show_compound or self.show_alerts
        self.warn_remaining = float(wcfg["warning_threshold_remaining"])
        self.warn_laps = float(wcfg["warning_threshold_laps"])
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.temp_scale = 1.8 if self.cfg.units["temperature_unit"] == "Fahrenheit" else 1.0  # unit degrees per Celsius
        self.sign = "°" if wcfg["show_degree_sign"] else ""
        pressure_unit = self.cfg.units["tyre_pressure_unit"]
        self.unit_pres = units.set_unit_pressure(pressure_unit)
        self.symbol_pres = units.set_symbol_pressure(pressure_unit)
        self.pressure_decimals = 0 if pressure_unit == "kPa" else 1 if pressure_unit == "psi" else 2
        self.pressure_steps = self.unit_pres(1.0) * 10 ** self.pressure_decimals  # shown steps per kPa
        self.compounds = TyreCompounds(
            wcfg["enable_heatmap_auto_matching"], wcfg["heatmap_name"], wcfg["enable_heatmap_from_optimal_temperature"])
        # Pressure target range per wheel (kPa, entered in kPa, psi or bar), compound one if set
        front = (pressure_target_kpa(wcfg["tyre_pressure_target_minimum"]),
                 pressure_target_kpa(wcfg["tyre_pressure_target_maximum"]))
        rear = (pressure_target_kpa(wcfg["tyre_pressure_target_rear_minimum"]) or front[0],
                pressure_target_kpa(wcfg["tyre_pressure_target_rear_maximum"]) or front[1])
        self.default_targets = (front, rear)
        self.compound_targets = {
            symbol: (pressure_target_kpa(p_min), pressure_target_kpa(p_max))
            for symbol, (p_min, p_max, _, _) in parse_compound_targets(wcfg["tyre_target_by_compound"]).items()
        }
        self.targets = [front, front, rear, rear]
        self.target_names: tuple[str, ...] = ()

    def vehicle_reset(self):
        """Compounds read again (followed car changed while spectating, session changed, back to garage)"""
        self.compounds.reset()

    def compound_target(self, name: str, rear: bool) -> tuple[float, float]:
        """Pressure range of compound (symbol or full name, "symbol:R" for rear), default range if none"""
        symbol = select_compound_symbol(name).upper()
        target = None
        if rear:
            target = self.compound_targets.get(f"{symbol}:R") or self.compound_targets.get(f"{name.upper()}:R")
        target = target or self.compound_targets.get(symbol) or self.compound_targets.get(name.upper())
        return target or self.default_targets[rear]

    def read_cards(self) -> tuple[WheelCard, ...]:
        """Readings of the four tyres"""
        self.compounds.update()
        names = self.compounds.names
        if self.compound_targets and names != self.target_names:
            self.target_names = names
            self.targets = [self.compound_target(name, index >= 2) for index, name in enumerate(names[:4])]
        tyre = api.read.tyre
        surface = (tyre.surface_temperature_ico() if self.ico else tyre.surface_temperature_avg()) \
            if self.show_surface else ()
        carcass = tyre.carcass_temperature() if self.show_carcass else ()
        inner = tyre.inner_temperature_avg() if self.show_inner else ()
        pressures = tyre.pressure() if self.show_pressure else ()
        detached: tuple[bool, ...] = (False,) * 4
        puncture: tuple[bool, ...] = (False,) * 4
        locking: Any = (0.0,) * 4
        if self.show_alerts:
            detached = api.read.wheel.is_detached()
            puncture = tyre_punctured()
            locking = minfo.wheels.lockingTreadWear
        wheels = minfo.wheels
        parts = 3 if self.ico else 1
        scale = self.temp_scale
        steps = self.pressure_steps
        cards = []
        for index in range(4):
            name = names[index] if index < len(names) else ""
            badge = compound_badge(name) if self.show_compound and name else None
            temps = tuple(shown_temperature(value, scale)
                          for value in surface[index * parts:index * parts + parts]) if surface else ()
            pressure = pressures[index] if index < len(pressures) else 0.0
            card = WheelCard(
                compound=badge[0] if badge else "",
                compound_color=badge[1] if badge else None,
                alert=tyre_alert(detached[index], puncture[index], locking[index], self.flat_threshold),
                temps=temps,
                carcass=shown_temperature(carcass[index], scale) if carcass else NO_READING,
                inner=shown_temperature(inner[index], scale) if inner else NO_READING,
                pressure=round(pressure * steps, 0) / steps,  # state from pressure read (not rounded)
                pressure_state=pressure_state(pressure, self.targets[index]) if self.use_target else PRESSURE_OK,
            )
            if self.need_wear:
                remaining = wheels.currentTreadDepth[index]
                wear = wheels.estimatedValidTreadWear[index]  # valid laps only (no pit, no off track)
                laps = min(max(remaining, 0) / wear, 999.0) if wear > 0 else -1.0
                card = card._replace(remaining=round(remaining, 0) + 0.0, wear=shown_wear(wear), laps=shown_laps(laps))
            cards.append(card)
        return tuple(cards)

    # Texts
    def temperature_text(self, value: float) -> str:
        if not temperature_valid(value):
            return DASH
        return f"{self.unit_temp(value):.0f}{self.sign}"

    def pressure_text(self, value: float) -> str:
        if value <= 0:
            return DASH
        return f"{self.unit_pres(value):.{self.pressure_decimals}f}"

    @staticmethod
    def remaining_text(value: float) -> str:
        return DASH if value < 0 else f"{value:.0f}%"

    @staticmethod
    def wear_text(value: float) -> str:
        return DASH if value <= 0 else f"{value:.2f}"[:4].rstrip(".")

    @staticmethod
    def laps_text(value: float) -> str:
        if value < 0:
            return DASH
        if value >= 100:  # wear barely measured yet (first laps): no meaningful count
            return "99+"
        return f"{value:.0f}" if value >= 10 else f"{value:.1f}"

    def heat(self, index: int, value: float) -> QColor | None:
        """Heatmap color of tyre temperature, None without reading"""
        if not temperature_valid(value):
            return None
        return heat_color(self.compounds.heat[index], value)


class Realtime(TyreOverviewMixin, ClassicCells, Overlay):
    """Draw widget"""

    wcfg: TyreOverviewConfig

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()
        self.setup_overview()

        # Config variable
        wcfg = self.wcfg
        gap = max(int(wcfg["bar_gap"]), 0)
        row_h = round(font_m.height * 1.15)
        card_w = self.text_cell_width(15)
        self.rows = [row for row, shown in (
            ("caption", self.show_caption), ("surface", self.show_surface), ("layers", self.show_carcass or self.show_inner),
            ("pressure", self.show_pressure), ("wear", self.show_wear or self.show_wear_lap or self.show_laps),
        ) if shown]
        card_h = row_h * max(len(self.rows), 1)  # every part off: empty cards
        self.cards = []
        for index in range(4):
            left = (card_w + gap) * (index % 2)
            top = (card_h + gap) * (index // 2)
            self.cards.append(tuple(QRectF(left, top + row_h * row, card_w, row_h) for row in range(len(self.rows))))
        self.labels = tuple(tr(label) for label in WHEELS)
        self.alert_labels = {key: tr(label) for key, label in ALERTS.items()}
        self.colors = option_colors(wcfg, "font_color_caption", "background_color_caption", "font_color_value",
                                    "background_color_value", "font_color_warning", "tyre_pressure_low_color",
                                    "tyre_pressure_high_color")

        # Config canvas
        self.resize(round(card_w * 2 + gap), round(card_h * 2 + gap))
        self.state: tuple[WheelCard, ...] | None = None

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_cards()
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        cards = self.state if self.state is not None else (WheelCard(),) * 4
        for index, (rects, card) in enumerate(zip(self.cards, cards)):
            for row, rect in zip(self.rows, rects):
                getattr(self, f"draw_{row}")(painter, rect, index, card)

    def draw_caption(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        colors = self.colors
        self.draw_cell(painter, rect, self.labels[index] if self.show_label else "", colors["font_color_caption"],
                       colors["background_color_caption"], LEFT)
        if card.alert:
            self.draw_cell(painter, rect, self.alert_labels[card.alert], colors["font_color_warning"], None, RIGHT)
        elif card.compound and card.compound_color is not None:
            self.draw_cell(painter, rect, card.compound, card.compound_color, None, RIGHT)

    def draw_surface(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        temps = card.temps or (NO_READING,) * (3 if self.ico else 1)
        width = rect.width() / len(temps)
        for part, value in enumerate(temps):
            cell = QRectF(rect.left() + width * part, rect.top(), width, rect.height())
            fill = self.heat(index, value)
            self.draw_cell(painter, cell, self.temperature_text(value),
                           readable_on(fill) if fill is not None else self.colors["font_color_value"],
                           fill or self.colors["background_color_value"])

    def draw_layers(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        colors = self.colors
        painter.fillRect(rect, colors["background_color_value"])
        values = [value for value, shown in ((card.carcass, self.show_carcass), (card.inner, self.show_inner)) if shown]
        width = rect.width() / len(values)
        for part, value in enumerate(values):
            cell = QRectF(rect.left() + width * part, rect.top(), width, rect.height())
            self.draw_cell(painter, cell, self.temperature_text(value), self.heat(index, value)
                           or colors["font_color_value"])

    def draw_pressure(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        colors = self.colors
        color = (colors["tyre_pressure_low_color"] if card.pressure_state == PRESSURE_LOW
                 else colors["tyre_pressure_high_color"] if card.pressure_state == PRESSURE_HIGH
                 else colors["font_color_value"])
        text = self.pressure_text(card.pressure)
        self.draw_cell(painter, rect, f"{text} {self.symbol_pres}" if self.show_pressure_unit else text, color,
                       colors["background_color_value"])

    def draw_wear(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        colors = self.colors
        painter.fillRect(rect, colors["background_color_value"])
        cells = [
            (self.remaining_text(card.remaining), 0 <= card.remaining <= self.warn_remaining, self.show_wear),
            (self.wear_text(card.wear), False, self.show_wear_lap),
            (self.laps_text(card.laps), 0 <= card.laps <= self.warn_laps, self.show_laps),
        ]
        shown = [(text, warn) for text, warn, show in cells if show]
        width = rect.width() / len(shown)
        for part, (text, warn) in enumerate(shown):
            cell = QRectF(rect.left() + width * part, rect.top(), width, rect.height())
            self.draw_cell(painter, cell, text, colors["font_color_warning"] if warn else colors["font_color_value"],
                           None, CENTER)
