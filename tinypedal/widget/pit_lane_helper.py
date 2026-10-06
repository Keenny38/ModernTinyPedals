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
Pit lane helper Widget

Shown while approaching pit lane (pit requested) and in pit lane: speed against pit speed limit,
speed limiter state, distance to pit box with a bar filling up on approach, planned services.
Nothing drawn otherwise (unless always shown, or overlay unlocked).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from .. import units
from ..api_control import api
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ._base import Overlay
from ._race_aids import ClassicCells, HiddenPreview, finite, option_colors

DASH = chr(0x2013)
SPEED_TOLERANCE = 0.2  # m/s over pit speed limit still shown as under (limiter oscillation)
BOX_PASSED = 20.0  # meters: distance to box grew by more than this, box is behind
# Speed & limiter state
UNKNOWN = 0
OK = 1
WARNING = 2
DANGER = 3


class PitReading(NamedTuple):
    """Pit lane readings, for drawing"""

    visible: bool = False
    speed: str = DASH
    speed_state: int = UNKNOWN  # OK under limit, DANGER over limit
    limit: str = DASH
    limiter: str = DASH
    limiter_state: int = UNKNOWN  # OK on, WARNING off (approaching), DANGER off in pit lane
    box: str = DASH
    box_fraction: float = -1.0  # 0-1 approach to pit box, -1 = unknown
    stop: str = DASH
    refuel: str = DASH
    repair: str = DASH


# Readings shown by options: (key, label, option)
ITEMS = (
    ("speed", "Speed", "show_speed"),
    ("limit", "Limit", "show_speed"),
    ("limiter", "Limiter", "show_limiter_state"),
    ("box", "Pit box", "show_pit_box_distance"),
    ("stop", "Stop", "show_planned_services"),
    ("refuel", "Refuel", "show_planned_services"),
    ("repair", "Repair", "show_planned_services"),
)


def box_distance(position: float, box: float, track_length: float) -> float:
    """Distance ahead to pit box along lap (meters), -1 if unknown"""
    if not (box >= 0 and track_length > 1 and finite(position) and finite(box)):
        return -1.0
    return (box - position) % track_length


class PitLaneMixin:
    """Pit lane readings, for classic & modern widget"""

    wcfg: Any
    cfg: Any

    def setup_pit(self):
        """Options, units"""
        wcfg = self.wcfg
        self.show_always = bool(wcfg["show_always"])
        self.approach = max(float(wcfg["approach_distance"]), 0.0)
        self.items = tuple((key, label) for key, label, option in ITEMS if wcfg[option])
        self.unit_speed = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.symbol_speed = units.set_symbol_speed(self.cfg.units["speed_unit"])
        self.unit_dist = units.set_unit_distance(self.cfg.units["distance_unit"])
        self.symbol_dist = units.set_symbol_distance(self.cfg.units["distance_unit"])
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.symbol_fuel = units.set_symbol_fuel(self.cfg.units["fuel_unit"])
        self.box_reference = 0.0  # distance to box when helper shown (bar empty)
        self.box_passed = False

    def labels(self) -> tuple[str, ...]:
        """Labels of shown readings (speed unit after speed & limit)"""
        return tuple(
            f"{tr(label)} {self.symbol_speed}" if key in ("speed", "limit") else tr(label)
            for key, label in self.items
        )

    def approaching(self, position: float, track_length: float, in_lane: bool) -> bool:
        """Pit requested (or limiter on) & close to pit entry"""
        if in_lane or not (api.read.vehicle.pit_request() or self.limiter_on()):
            return False
        entry = api.read.lap.pit_entry_distance()  # from game
        if not entry > 0:
            entry = minfo.mapping.pitEntryPosition  # learned
        if not (finite(position) and track_length > 1):
            return False
        if entry > 0:
            return (entry - position) % track_length <= self.approach
        return track_length - position <= self.approach  # entry unknown: near finish line

    @staticmethod
    def limiter_on() -> bool:
        """Speed limiter switched on"""
        return bool(api.read.switch.speed_limiter() or api.read.switch.speed_limiter_active())

    def read_pit(self) -> PitReading:
        """Readings & visibility"""
        position = api.read.lap.distance()
        track_length = api.read.lap.track_length()
        in_lane = api.read.vehicle.in_paddock() == 1
        # Box approach tracked only in lane or approaching it, also when shown always (else never reset)
        active = in_lane or self.approaching(position, track_length, in_lane)
        visible = active or self.show_always
        if not active:
            self.box_reference = 0.0
            self.box_passed = False
        speed = api.read.vehicle.speed()
        limit = minfo.mapping.pitSpeedLimit
        speed_text = f"{min(self.unit_speed(speed), 999):.0f}" if finite(speed) else DASH
        if finite(limit) and limit > 0:
            limit_text = f"{min(self.unit_speed(limit), 999):.0f}"
            speed_state = DANGER if speed > limit + SPEED_TOLERANCE else OK
        else:
            limit_text = DASH
            speed_state = UNKNOWN
        if not api.read.switch.speed_limiter_available():
            limiter, limiter_state = DASH, UNKNOWN
        elif self.limiter_on():
            limiter, limiter_state = tr("On"), OK
        else:
            limiter, limiter_state = tr("Off"), DANGER if in_lane and speed > 1 else WARNING
        box, fraction = self.read_box(position, track_length, active)
        return PitReading(
            visible=visible,
            speed=speed_text,
            speed_state=speed_state,
            limit=limit_text,
            limiter=limiter,
            limiter_state=limiter_state,
            box=box,
            box_fraction=fraction,
            stop=seconds_text(api.read.vehicle.pit_stop_time()),
            refuel=self.refuel_text(api.read.vehicle.absolute_refill()),
            repair=seconds_text(api.read.vehicle.repair_time()),
        )

    def read_box(self, position: float, track_length: float, active: bool) -> tuple[str, float]:
        """Distance to pit box & approach fraction (bar fills up to box), tracked while active
        (in lane or approaching it)"""
        distance = box_distance(position, api.read.lap.pit_box_distance(), track_length)
        if distance < 0:
            return DASH, -1.0
        if active and not self.box_passed:
            if self.box_reference and distance > self.box_reference + BOX_PASSED:
                self.box_passed = True  # stopped at box, or drove past it
            else:
                self.box_reference = max(self.box_reference, distance)
        if self.box_passed:
            return DASH, 1.0
        fraction = 1 - distance / self.box_reference if self.box_reference > 0 else 0.0
        return f"{min(self.unit_dist(distance), 99999):.0f}{self.symbol_dist}", round(min(max(fraction, 0.0), 1.0), 3)

    def refuel_text(self, refill: float) -> str:
        """Fuel (or virtual energy) added at next stop, from game pit menu"""
        if not (finite(refill) and refill > 0):
            return DASH
        if minfo.energy.available:
            added = refill - minfo.energy.amountCurrent
            return f"+{min(max(added, 0.0), 999):.0f}%"
        added = self.unit_fuel(refill - minfo.fuel.amountCurrent)
        return f"+{min(max(added, 0.0), 999):.0f}{self.symbol_fuel}"


def seconds_text(seconds: float) -> str:
    """Seconds of pit stop or repair, dash if none"""
    if not (finite(seconds) and seconds > 0):
        return DASH
    return f"{min(seconds, 999):.0f}s"


class Realtime(HiddenPreview, PitLaneMixin, ClassicCells, Overlay):
    """Draw widget"""

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()
        self.setup_pit()

        # Config variable
        wcfg = self.wcfg
        gap = 2
        row_h = round(font_m.height * 1.25)
        bar_h = max(round(font_m.height * 0.2), 2)
        self.cells = []
        left = 0.0
        for (key, _), label in zip(self.items, self.labels()):
            width = max(self.text_cell_width(6), self.text_cell_width(len(label)))
            self.cells.append((key, label, QRectF(left, 0, width, row_h), QRectF(left, row_h, width, row_h)))
            left += width + gap
        self.bar_rect = QRectF(0, row_h * 2 + gap, 0, bar_h)
        for key, _, _, value_rect in self.cells:
            if key == "box":
                self.bar_rect = QRectF(value_rect.left(), row_h * 2, value_rect.width(), bar_h)
        self.colors = option_colors(
            wcfg, "font_color_caption", "font_color_reading", "background_color", "font_color_under_limit",
            "font_color_over_limit", "background_color_limiter_on", "background_color_limiter_off",
            "pit_box_bar_color", "background_color_pit_box_bar",
        )

        # Config canvas
        has_bar = any(key == "box" for key, _ in self.items)
        self.resize(max(round(left - gap), 1), row_h * 2 + (bar_h if has_bar else 0))
        self.state = PitReading()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_pit()
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        state = self.state
        if not (state.visible or self.previewing()):
            return
        painter = QPainter(self)
        colors = self.colors
        background = colors["background_color"]
        for key, label, caption_rect, value_rect in self.cells:
            self.draw_cell(painter, caption_rect, label, colors["font_color_caption"], background)
            color = colors["font_color_reading"]
            fill = background
            if key == "speed" and state.speed_state:
                color = colors["font_color_over_limit" if state.speed_state == DANGER else "font_color_under_limit"]
            elif key == "limiter" and state.limiter_state:
                fill = colors["background_color_limiter_on" if state.limiter_state == OK else "background_color_limiter_off"]
            self.draw_cell(painter, value_rect, getattr(state, key), color, fill)
        if self.bar_rect.width() > 0:
            bar = self.bar_rect
            painter.fillRect(bar, colors["background_color_pit_box_bar"])
            if state.box_fraction > 0:
                painter.fillRect(QRectF(bar.left(), bar.top(), bar.width() * state.box_fraction, bar.height()),
                                 colors["pit_box_bar_color"])
