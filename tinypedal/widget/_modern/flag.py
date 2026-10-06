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
Flag Widget, modern design

Flag & race state chips, shown only while active, packed in display order: solid flag color
(yellow, blue, green, red...), caption on top, value below (distance, time, speed, laps).
Pit timer, low fuel or energy, speed limiter, yellow & blue flags, start lights, incoming
traffic, pit request, finish state, scheduled repairs, sector yellow flags, full course yellow.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_common import MAX_SECONDS
from ...i18n import tr_overlay as tr
from ...module_info import minfo
from ..flag import BlueFlagTimer, GreenFlagTimer, PitTimer, TrafficTimer
from .base import CENTER, DASH, ModernOverlay, display_order_options
from .draw import readable_on, rounded

SHINE = QColor(255, 255, 255, 34)  # light top of chip, fading out at middle
CAPTION_ALPHA = 190  # caption over value, on chip color
# Full course yellow phase (game state) -> value
FCY_PHASES = {
    1: "Pending", 2: "Pits closed", 3: "Leaders pit", 4: "Pits open", 5: "Last lap", 6: "Resume", 7: "Red flag",
}
# Item (display order option suffix), in design order
ITEMS = (
    "pit_timer", "low_fuel", "speed_limiter", "yellow_flag", "blue_flag", "start_lights", "traffic", "pit_request",
    "finish_state", "scheduled_repairs", "sector_yellow_flags", "full_course_yellow",
)
# Value samples (chip width), captions are measured too
VALUE_SAMPLES = ("888.88", "+888m", "88.8s", "8.8 - 8.8", "Pits closed")
# Item -> caption, sample value & color of picture drawn before any update (Overlays page)
PREVIEW_CHIPS = {
    "pit_timer": ("pit", "12.34", "positive"),
    "low_fuel": ("fuel", "3.50", "orange"),
    "speed_limiter": ("limiter", "80.00", "negative"),
    "yellow_flag": ("yellow", "+320m", "caution"),
    "blue_flag": ("blue", "3s", "blue"),
    "start_lights": ("lights", "3", "negative"),
    "traffic": ("traffic", "4.6s", "accent"),
    "pit_request": ("pit_request", "1.2 - 1.8", "positive"),
    "finish_state": ("finish", "", "text"),
    "scheduled_repairs": ("repairs", "32s", "warning"),
    "sector_yellow_flags": ("sectors", "S2", "caution"),
    "full_course_yellow": ("fcy", "", "warning"),
}


class Chip(NamedTuple):
    """Shown chip"""

    caption: str
    value: str
    color: str  # theme token


class Item(NamedTuple):
    """Enabled item"""

    key: str


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_pit_timer", "pit_time_highlight_duration", "pit_in_text", "pit_out_text",
        "show_low_fuel", "show_low_fuel_for_race_only", "low_fuel_volume_threshold", "low_fuel_lap_threshold",
        "low_fuel_text", "low_energy_text", "show_speed_limiter", "show_current_speed_while_limiter_on",
        "decimal_places_speed", "speed_limiter_text", "show_yellow_flag", "show_yellow_flag_for_race_only",
        "yellow_flag_maximum_range_ahead", "yellow_flag_maximum_range_behind", "yellow_flag_text", "show_blue_flag",
        "show_blue_flag_for_race_only", "show_start_lights", "red_lights_text", "green_flag_text", "green_flag_duration",
        "show_traffic", "show_traffic_while_off_track", "traffic_maximum_time_gap", "traffic_extended_duration",
        "traffic_low_speed_threshold", "traffic_text", "show_pit_request", "show_finish_state", "finish_text",
        "disqualify_text", "show_scheduled_repairs", "scheduled_repairs_text", "show_sector_yellow_flags",
        "sector_yellow_flags_text", "show_full_course_yellow", "full_course_yellow_text",
        *display_order_options("flag"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.symbol_fuel = units.set_symbol_fuel(self.cfg.units["fuel_unit"])
        self.unit_dist = units.set_unit_distance(self.cfg.units["distance_unit"])
        self.symbol_dist = units.set_symbol_distance(self.cfg.units["distance_unit"])
        self.unit_speed = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.decimals_speed = min(max(int(wcfg["decimal_places_speed"]), 0), 3)
        shown = [Item(key) for key in ITEMS if wcfg.get(f"show_{key}", False)]
        self.keys = tuple(item.key for item in self.display_ordered(shown))
        self.captions = {
            "pit": self.user_text("pit_in_text", tr("Pit")),
            "pit_out": self.user_text("pit_out_text", tr("Pit time")),
            "pit_closed": tr("Pit lane"),
            "fuel": self.user_text("low_fuel_text", tr("Low fuel")),
            "energy": self.user_text("low_energy_text", tr("Low energy")),
            "limiter": self.user_text("speed_limiter_text", tr("Limiter")),
            "yellow": self.user_text("yellow_flag_text", tr("Yellow")),
            "blue": tr("Blue flag"),
            "lights": self.user_text("red_lights_text", tr("Start")),
            "green": tr("Start"),
            "traffic": self.user_text("traffic_text", tr("Traffic")),
            "pit_request": tr("Pit request"),
            "finish": tr("Session"),
            "repairs": self.user_text("scheduled_repairs_text", tr("Repairs")),
            "sectors": self.user_text("sector_yellow_flags_text", tr("Sector yellow")).strip(),
            "fcy": self.user_text("full_course_yellow_text", "FCY"),
        }
        self.green_text = self.user_text("green_flag_text", tr("Go"))
        self.finish_text = self.user_text("finish_text", tr("Finish"))
        self.dsq_text = self.user_text("disqualify_text", "DSQ")
        values = (*VALUE_SAMPLES, *(tr(text) for text in FCY_PHASES.values()), self.green_text, self.finish_text)
        pad = unit * 0.5
        self.chip_w = max(
            max(self.text_width("label", text) for text in self.captions.values()),
            self.text_width("strong", self.widest("strong", values)),
        ) + pad * 2
        self.chip_h = unit * 2.2
        gap = max(unit * 0.25, 2.0)
        vertical = wcfg["layout"] == 0
        count = max(len(self.keys), 1)
        if vertical:
            self.slots = tuple(QRectF(0, (self.chip_h + gap) * index, self.chip_w, self.chip_h) for index in range(count))
            self.set_size(self.chip_w, (self.chip_h + gap) * count - gap)
        else:
            self.slots = tuple(QRectF((self.chip_w + gap) * index, 0, self.chip_w, self.chip_h) for index in range(count))
            self.set_size((self.chip_w + gap) * count - gap, self.chip_h)
        self.pad = pad
        self.pit_timer = PitTimer(wcfg["pit_time_highlight_duration"])
        self.green_timer = GreenFlagTimer(wcfg["green_flag_duration"])
        self.blue_timer = BlueFlagTimer(wcfg["show_blue_flag_for_race_only"])
        self.traffic_timer = TrafficTimer(
            wcfg["traffic_maximum_time_gap"], wcfg["traffic_extended_duration"],
            wcfg["traffic_low_speed_threshold"], wcfg["show_traffic_while_off_track"],
        )
        self.samples = tuple(self.sample_chip(key) for key in self.keys)

    def post_update(self):
        self.pit_timer.reset()
        self.blue_timer.reset()
        self.traffic_timer.reset()
        self.green_timer.reset()

    def sample_chip(self, key: str) -> Chip:
        """Chip of item drawn before any update"""
        caption, value, color = PREVIEW_CHIPS[key]
        if key == "finish_state":
            value = self.finish_text
        elif key == "full_course_yellow":
            value = tr("Pits open")
        return Chip(self.captions[caption], value, color)

    def paintEvent(self, event):
        """Every item as sample chip before first update (picture of Overlays page), then active ones"""
        if self.state is None:
            self.state = self.samples
            super().paintEvent(event)
            self.state = None
            return
        super().paintEvent(event)

    def paint(self, painter: QPainter):
        theme = self.theme
        radius = self.radius(0.45)
        pad = self.pad
        for slot, chip in zip(self.slots, self.state):
            color = getattr(theme, chip.color)
            rounded(painter, slot, radius, color)
            if self.depth_effects:
                self.shine(painter, slot, radius)
            text = readable_on(color)
            inner = slot.adjusted(pad, 0, -pad, 0)
            caption_h = slot.height() * 0.4
            self.draw_text(painter, QRectF(inner.left(), slot.top() + slot.height() * 0.06, inner.width(), caption_h),
                           chip.caption, "label", theme.tint(text, CAPTION_ALPHA), CENTER)
            self.draw_text(painter, QRectF(inner.left(), slot.top() + caption_h, inner.width(), slot.height() - caption_h),
                           chip.value, "strong", text, CENTER)

    @staticmethod
    def shine(painter: QPainter, rect: QRectF, radius: float):
        """Soft light on top of chip"""
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        gradient = QLinearGradient(0, rect.top(), 0, rect.center().y())
        gradient.setColorAt(0.0, SHINE)
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, QBrush(gradient))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        lap_etime = api.read.timing.elapsed()
        in_pits = api.read.vehicle.in_pits()
        in_race = api.read.session.in_race()
        chips = []
        for key in self.keys:
            chip = getattr(self, f"read_{key}")(lap_etime, in_pits, in_race)
            if chip is not None:
                chips.append(chip)
        self.refresh(tuple(chips))

    # Items
    def read_pit_timer(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if in_pits and api.read.vehicle.in_garage():
            return None
        timer = self.pit_timer.update(in_pits, lap_etime)
        if timer == MAX_SECONDS:
            return None
        if timer < 0:  # left pit lane
            return Chip(self.captions["pit_out"], f"{-timer:.2f}", "surface_strong")
        if api.read.session.pit_open():
            return Chip(self.captions["pit"], f"{timer:.2f}", "positive")
        return Chip(self.captions["pit_closed"], tr("Closed"), "negative")

    def read_low_fuel(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        wcfg = self.wcfg
        if wcfg["show_low_fuel_for_race_only"] and not in_race:
            return None
        energy = minfo.energy.available and minfo.energy.estimatedLaps < minfo.fuel.estimatedLaps
        source = minfo.energy if energy else minfo.fuel
        amount = source.amountCurrent
        if amount > wcfg["low_fuel_volume_threshold"] or source.estimatedLaps > wcfg["low_fuel_lap_threshold"]:
            return None
        if energy:
            return Chip(self.captions["energy"], f"{amount:.1f}%", "orange")
        return Chip(self.captions["fuel"], f"{self.unit_fuel(amount):.2f}{self.symbol_fuel}", "orange")

    def read_speed_limiter(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if not (api.read.switch.speed_limiter() or api.read.switch.speed_limiter_active()):
            return None
        if self.wcfg["show_current_speed_while_limiter_on"]:
            value = f"{self.unit_speed(api.read.vehicle.speed()):.{self.decimals_speed}f}"
        else:
            value = tr("On")
        return Chip(self.captions["limiter"], value, "negative")

    def read_yellow_flag(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        wcfg = self.wcfg
        if (wcfg["show_yellow_flag_for_race_only"] and not in_race) or not api.read.session.yellow_flag():
            return None
        distance = minfo.vehicles.nearestYellowAhead
        if distance > wcfg["yellow_flag_maximum_range_ahead"]:
            distance = minfo.vehicles.nearestYellowBehind
            if distance < -wcfg["yellow_flag_maximum_range_behind"]:
                return None
        return Chip(self.captions["yellow"], f"{self.unit_dist(distance):+.0f}{self.symbol_dist}", "caution")

    def read_blue_flag(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        seconds = self.blue_timer.update(in_race, lap_etime)
        if seconds == MAX_SECONDS:
            return None
        class_name = minfo.vehicles.nearestBlueClass
        class_style = self.cfg.user.classes.get(class_name)
        if class_style is not None:
            class_name = class_style["alias"]
        value = f"{class_name} {seconds:.0f}s" if class_name else f"{seconds:.0f}s"
        return Chip(self.captions["blue"], value, "blue")

    def read_start_lights(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        lights = self.green_timer.update(lap_etime)
        if lights > 0:
            return Chip(self.captions["lights"], f"{lights}", "negative")
        if lights == 0:
            return Chip(self.captions["green"], self.green_text, "positive")
        return None

    def read_traffic(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        gap = self.traffic_timer.update(in_pits, lap_etime)
        if gap == MAX_SECONDS:
            return None
        return Chip(self.captions["traffic"], f"{gap:.1f}s", "accent")

    def read_pit_request(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if not api.read.vehicle.pit_request():
            return None
        if minfo.energy.available:
            laps = min(minfo.fuel.estimatedLaps, minfo.energy.estimatedLaps)
        else:
            laps = minfo.fuel.estimatedLaps
        safe = calc.pit_in_countdown_laps(laps, api.read.lap.progress())
        return Chip(self.captions["pit_request"], f"{lap_text(safe)} - {lap_text(laps)}", "positive")

    def read_finish_state(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        state = api.read.vehicle.finish_state()
        if state == 1:
            return Chip(self.captions["finish"], self.finish_text, "text")
        if state == 3:
            return Chip(self.captions["finish"], self.dsq_text, "negative")
        return None

    def read_scheduled_repairs(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        seconds = api.read.vehicle.repair_time()
        if not seconds > 0:
            return None
        return Chip(self.captions["repairs"], f"{seconds:.0f}s", "warning")

    def read_sector_yellow_flags(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if self.wcfg["show_yellow_flag_for_race_only"] and not in_race:
            return None
        sectors = tuple(api.read.session.sector_yellow_flags())
        if not any(sectors):
            return None
        value = " ".join(f"S{index}" for index, flag in enumerate(sectors, start=1) if flag)
        return Chip(self.captions["sectors"], value, "caution")

    def read_full_course_yellow(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        phase = FCY_PHASES.get(api.read.session.yellow_flag_state())
        if phase is None:
            return None
        return Chip(self.captions["fcy"], tr(phase), "negative" if phase == "Red flag" else "warning")


def lap_text(laps: float) -> str:
    """Laps, one decimal under 10"""
    if not laps < 9999:  # also nan
        return DASH
    return f"{laps:.0f}" if laps > 9.94 else f"{laps:.1f}"
