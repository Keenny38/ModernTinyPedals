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
Modern overlay design: fuel & virtual energy panel base

Top: remaining amount (large) & refill needed, level gauge with stint start & refill marks.
Below: estimate tiles (laps, minutes, consumption, saving target, pit stops, delta, end).
Low amount warning flashes the remaining value & gauge.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...i18n import tr_overlay as tr
from .._common import warning_flash
from .base import LEFT, RIGHT, ModernOverlay
from .draw import rounded
from .stats import Stat, StatsMixin, Value


class Names(NamedTuple):
    """Option names & labels of fuel or energy panel"""

    title: str  # remaining label
    refill: str  # refill label
    absolute: str  # option: show absolute refill
    refill_decimals: str  # option: refill decimals
    warning_flash: str  # option: low amount warning flash
    low_threshold: str  # option: low amount lap threshold
    level_bar: str  # option: show level bar
    start_mark: str  # option: show starting level mark
    refill_mark: str  # option: show refill level mark


COMMON_OPTIONS = (
    "font_size", "decimal_places_remaining", "decimal_places_estimated_laps", "decimal_places_estimated_minutes",
    "decimal_places_estimated_consumption", "decimal_places_saving_target", "show_estimated_pitstop_count",
    "decimal_places_pitstop_count", "decimal_places_early_pitstop_count", "show_delta_consumption_and_end_remaining",
    "decimal_places_delta_consumption", "decimal_places_end_remaining", "number_of_warning_flashes",
    "warning_flash_highlight_duration", "warning_flash_interval",
)


class ConsumptionPanel(StatsMixin, ModernOverlay):
    """Fuel or energy panel"""

    names: Names
    source: Any  # minfo.fuel or minfo.energy
    convert: Callable[[float], float]
    symbol: str

    def setup_panel(self, extra_stats: list[Stat]):
        """Geometry: hero section, gauge, estimate tiles"""
        wcfg = self.wcfg
        names = self.names
        unit = self.unit
        self.add_font("hero", 1.7, "bold")
        pad = unit * 0.3
        inner = unit * 0.55
        self.dec_remaining = max(int(wcfg["decimal_places_remaining"]), 0)
        self.dec_refill = max(int(wcfg[names.refill_decimals]), 0)
        self.refill_sign = "" if wcfg[names.absolute] else "+"
        if wcfg[names.warning_flash]:
            self.warn_flash = warning_flash(
                wcfg["warning_flash_highlight_duration"],
                wcfg["warning_flash_interval"],
                wcfg["number_of_warning_flashes"],
            )
        else:
            self.warn_flash = None

        stats = [
            Stat("laps", "Laps", "888.8"),
            Stat("minutes", "Minutes", "888.8"),
            Stat("used", "Per lap", "88.88"),
            Stat("save", "Save", "8.88"),
        ]
        if wcfg["show_estimated_pitstop_count"]:
            stats += [Stat("pits", "Pit stops", "88.88"), Stat("early", "Early", "88.88")]
        if wcfg["show_delta_consumption_and_end_remaining"]:
            stats += [Stat("delta", "Delta", "+8.88"), Stat("end", "End", "888.88")]
        stats += extra_stats
        self.keys = tuple(stat.key for stat in stats)
        columns = 4 if len(stats) <= 8 else 5

        hero_h = unit * 2.6
        gauge_h = max(unit * 0.42, 4.0) if wcfg[names.level_bar] else 0.0
        tiles_top = pad + hero_h + (gauge_h + unit * 0.45 if gauge_h else unit * 0.1)
        hero_w = self.text_width("hero", "888.88") + self.text_width("small", self.symbol) + self.text_width("value", "+888.88") + unit * 3
        width, height = self.build_stats(stats, columns=columns, top=tiles_top, min_width=hero_w)
        self.rect_hero = QRectF(pad + inner, pad, width - (pad + inner) * 2, hero_h)
        self.rect_gauge = QRectF(pad + inner, pad + hero_h + unit * 0.05, width - (pad + inner) * 2, gauge_h)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        self.paint_stats_static(painter)
        hero = self.rect_hero
        label_h = self.unit * 0.95
        self.draw_text(painter, QRectF(hero.left(), hero.top() + self.unit * 0.15, hero.width(), label_h),
                       tr(self.names.title), "label", theme.text_muted, LEFT)
        self.draw_text(painter, QRectF(hero.left(), hero.top() + self.unit * 0.15, hero.width(), label_h),
                       tr(self.names.refill), "label", theme.text_muted, RIGHT)
        if self.rect_gauge.height():
            rounded(painter, self.rect_gauge, self.rect_gauge.height() / 2, theme.surface_raised)

    def paint(self, painter: QPainter):
        theme = self.theme
        values, remaining, refill, low, level = self.state
        hero = self.rect_hero
        value_rect = QRectF(hero.left(), hero.top() + self.unit * 0.95, hero.width(), hero.height() - self.unit * 0.95)
        color = theme.negative if low else theme.text
        self.draw_text(painter, value_rect, remaining, "hero", color, LEFT)
        number_w = self.text_width("hero", remaining)
        symbol_rect = QRectF(value_rect.left() + number_w + self.unit * 0.2, value_rect.top() + self.unit * 0.25,
                             self.unit * 2, value_rect.height())
        self.draw_text(painter, symbol_rect, self.symbol, "small", theme.text_muted, LEFT)
        refill_color = theme.negative if low else (theme.accent if refill[1] > 0 else theme.positive)
        self.draw_text(painter, value_rect, refill[0], "strong", refill_color, RIGHT)
        if self.rect_gauge.height() and level is not None:
            self.draw_gauge(painter, level, low)
        self.draw_stats(painter, values)

    def draw_gauge(self, painter: QPainter, level: tuple[float, float, float], low: bool):
        """Level, stint start mark, refill target mark"""
        theme = self.theme
        gauge = self.rect_gauge
        current, start, refill = (min(max(value, 0.0), 1.0) for value in level)
        radius = gauge.height() / 2
        fill = QRectF(gauge.left(), gauge.top(), gauge.width() * current, gauge.height())
        color = theme.negative if low else theme.positive
        rounded(painter, fill, radius, color)
        if refill > current:
            target = QRectF(fill.right(), gauge.top(), gauge.width() * (refill - current), gauge.height())
            rounded(painter, target, radius, theme.tint(theme.accent, 90))
        mark_w = max(self.unit * 0.12, 2.0)
        mark_h = gauge.height() * 2.0
        if self.wcfg[self.names.start_mark] and start > 0:
            x = gauge.left() + gauge.width() * start
            rounded(painter, QRectF(x - mark_w / 2, gauge.center().y() - mark_h / 2, mark_w, mark_h), mark_w / 2, theme.text_dim)
        if self.wcfg[self.names.refill_mark] and refill > 0:
            x = gauge.left() + gauge.width() * refill
            rounded(painter, QRectF(x - mark_w / 2, gauge.center().y() - mark_h / 2, mark_w, mark_h), mark_w / 2, theme.accent)

    def read_panel(self, extra_values: list[Value]):
        """Update from data source"""
        wcfg = self.wcfg
        theme = self.theme
        data = self.source
        convert = self.convert
        low = data.estimatedLaps <= wcfg[self.names.low_threshold]
        if self.warn_flash is not None and data.estimatedValidConsumption:
            low = self.warn_flash.send(low)
        remaining = f"{convert(data.amountCurrent):.{self.dec_remaining}f}"
        if wcfg[self.names.absolute]:
            need = calc.sym_max(convert(data.neededAbsolute), 9999)
        else:
            need = calc.sym_max(convert(data.neededRelative), 9999)
        refill = (f"{need:{self.refill_sign}.{self.dec_refill}f}", need if self.refill_sign else data.neededRelative)
        level = None
        if wcfg[self.names.level_bar] and data.capacity:
            capacity = data.capacity
            level = (
                round(data.amountCurrent / capacity, 3),
                round(data.amountStart / capacity, 3),
                round((data.amountCurrent + data.neededRelative) / capacity, 3),
            )
        values = []
        for key in self.keys:
            if key == "laps":
                values.append(Value(f"{min(data.estimatedLaps, 9999):.{decimals(wcfg, 'estimated_laps')}f}",
                                    theme.negative if low else None))
            elif key == "minutes":
                values.append(Value(f"{min(data.estimatedMinutes, 9999):.{decimals(wcfg, 'estimated_minutes')}f}"))
            elif key == "used":
                values.append(Value(f"{convert(data.estimatedConsumption):.{decimals(wcfg, 'estimated_consumption')}f}"))
            elif key == "save":
                save = calc.zero_max(convert(data.oneLessPitConsumption), 99.99)
                values.append(Value(f"{save:.{decimals(wcfg, 'saving_target')}f}", theme.warning if save > 0 else theme.text_dim))
            elif key == "pits":
                values.append(Value(f"{calc.zero_max(data.estimatedNumPitStopsEnd, 99.99):.{decimals(wcfg, 'pitstop_count')}f}"))
            elif key == "early":
                values.append(Value(f"{calc.zero_max(data.estimatedNumPitStopsEarly, 99.99):.{decimals(wcfg, 'early_pitstop_count')}f}",
                                    theme.text_dim))
            elif key == "delta":
                delta = convert(data.deltaConsumption)
                values.append(Value(f"{delta:+.{decimals(wcfg, 'delta_consumption')}f}",
                                    theme.negative if delta > 0 else theme.positive))
            elif key == "end":
                values.append(Value(f"{convert(data.amountEndStint):.{decimals(wcfg, 'end_remaining')}f}"))
        values += extra_values
        self.refresh((tuple(values), remaining, refill, low, level))


def decimals(wcfg: dict, name: str) -> int:
    """Decimal places option"""
    return max(int(wcfg.get(f"decimal_places_{name}", 2)), 0)
