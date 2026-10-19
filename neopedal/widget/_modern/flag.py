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
Flag Widget, modern design

Flag & race state chips, shown only while active, packed in display order (or most urgent first): solid flag
color (yellow, blue, green, red...), caption on top, value below (distance, time, speed, laps). Pit timer, low
fuel or energy, speed limiter (difference to pit speed limit, pit lane driven without it), yellow & blue flags,
start lights, incoming traffic, pit request, finish state, scheduled repairs, sector yellow flags, full course
yellow, penalty to serve, last lap, heavy damage. Alerts flash (colors swapped) for a moment when raised. Live
overlay is as large as its chips shown (whole size while unlocked, to place it).
"""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath

from ... import calculation as calc
from ... import realtime_state, units
from ...api_control import api
from ...const_common import MAX_SECONDS
from ...i18n import tr_overlay as tr
from ...module_info import minfo
from .._data import run_laps
from ..flag import (
    LIMITER_HIDDEN,
    LIMITER_OFF,
    LIMITER_OVER,
    BlueFlagTimer,
    GreenFlagTimer,
    PitLimiterWatch,
    PitTimer,
    TrafficTimer,
    blue_flag_gap,
    heavy_damage,
    is_low_amount,
    on_last_lap,
    pending_penalty,
    pit_speed_limit,
)
from .base import CENTER, DASH, ModernOverlay, display_order_options
from .draw import readable_on, rounded

if TYPE_CHECKING:
    from ...template.widget_config_types import FlagConfig

SHINE = QColor(255, 255, 255, 34)  # light top of chip, fading out at middle
CAPTION_ALPHA = 190  # caption over value, on chip color
FLASH_PERIOD = 0.25  # seconds: alert flash, colors swapped then normal
# Full course yellow phase (game state) -> value
FCY_PHASES = {
    1: "Pending", 2: "Pits closed", 3: "Leaders pit", 4: "Pits open", 5: "Last lap", 6: "Resume", 7: "Red flag",
}
# Item (display order option suffix), in design order
ITEMS = (
    "pit_timer", "low_fuel", "speed_limiter", "yellow_flag", "blue_flag", "start_lights", "traffic", "pit_request",
    "finish_state", "scheduled_repairs", "sector_yellow_flags", "full_course_yellow", "penalty", "last_lap", "damage",
)
# Item -> rank of most urgent first order (enable_urgency_order)
URGENCY = {key: rank for rank, key in enumerate((
    "full_course_yellow", "start_lights", "penalty", "speed_limiter", "yellow_flag", "sector_yellow_flags",
    "blue_flag", "traffic", "damage", "low_fuel", "last_lap", "finish_state", "pit_timer", "pit_request",
    "scheduled_repairs",
))}
# Items flashing when raised (speed limiter: only over pit speed limit or pit lane driven without it)
ALERTS = frozenset((
    "low_fuel", "yellow_flag", "blue_flag", "traffic", "sector_yellow_flags", "full_course_yellow", "penalty",
    "last_lap", "damage",
))

# Value samples (chip width), captions are measured too
VALUE_SAMPLES = ("888.88", "▲ 888m", "88.8s", "8.8 - 8.8", "Pits closed", "SG88", "PEN\u00d78", "88%")
# Item -> caption, sample value & color of picture drawn before any update (Overlays page)
PREVIEW_CHIPS = {
    "pit_timer": ("pit", "12.34", "positive"),
    "low_fuel": ("fuel", "3.50", "orange"),
    "speed_limiter": ("limiter", "-0.40", "positive"),
    "yellow_flag": ("yellow", "▲ 320m", "caution"),
    "blue_flag": ("blue", "0.8s", "blue"),
    "start_lights": ("lights", "3", "negative"),
    "traffic": ("traffic", "4.6s", "accent"),
    "pit_request": ("pit_request", "1.2 - 1.8", "positive"),
    "finish_state": ("finish", "", "text"),
    "scheduled_repairs": ("repairs", "32s", "warning"),
    "sector_yellow_flags": ("sectors", "S2", "caution"),
    "full_course_yellow": ("fcy", "", "warning"),
    "penalty": ("penalty", "SG10", "negative"),
    "last_lap": ("finish", "", "text"),
    "damage": ("damage", "35%", "orange"),
}


class Chip(NamedTuple):
    """Shown chip"""

    key: str  # item
    caption: str
    value: str
    color: str  # theme token
    alert: bool = False  # flashes when raised
    flash: bool = False  # drawn flashing (colors swapped)


class Item(NamedTuple):
    """Enabled item"""

    key: str


class Realtime(ModernOverlay):
    """Draw widget"""

    wcfg: FlagConfig

    options = (
        "font_size", "layout", "enable_urgency_order", "enable_new_flag_flash", "new_flag_flash_duration",
        "show_pit_timer", "pit_time_highlight_duration", "pit_in_text", "pit_out_text", "pit_closed_text",
        "show_low_fuel", "show_low_fuel_for_race_only", "low_fuel_volume_threshold", "low_fuel_lap_threshold",
        "low_energy_percentage_threshold",
        "low_fuel_text", "low_energy_text", "show_speed_limiter", "show_current_speed_while_limiter_on",
        "show_speed_limit_difference", "show_speed_limiter_off_warning", "speed_limiter_off_text",
        "decimal_places_speed", "speed_limiter_text", "show_yellow_flag", "show_yellow_flag_for_race_only",
        "yellow_flag_maximum_range_ahead", "yellow_flag_maximum_range_behind", "yellow_flag_text", "show_blue_flag",
        "show_blue_flag_for_race_only", "show_blue_flag_gap", "show_start_lights", "red_lights_text",
        "green_flag_text", "green_flag_duration",
        "show_traffic", "show_traffic_while_off_track", "traffic_maximum_time_gap", "traffic_extended_duration",
        "traffic_low_speed_threshold", "traffic_text", "show_pit_request", "show_finish_state", "finish_text",
        "disqualify_text", "show_scheduled_repairs", "scheduled_repairs_text", "show_sector_yellow_flags",
        "show_sector_yellow_flags_for_race_only", "sector_yellow_flags_text", "show_full_course_yellow",
        "full_course_yellow_text", "show_penalty", "penalty_text", "show_last_lap", "last_lap_text", "show_damage",
        "damage_text",
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
        self.urgency_order = bool(wcfg["enable_urgency_order"])
        self.captions = {
            "pit": self.user_text("pit_in_text", tr("Pit")),
            "pit_out": self.user_text("pit_out_text", tr("Pit time")),
            "pit_closed": self.user_text("pit_closed_text", tr("Pit lane")),
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
            "penalty": self.user_text("penalty_text", tr("Penalty")),
            "damage": self.user_text("damage_text", tr("Damage")),
        }
        self.green_text = self.user_text("green_flag_text", tr("Go"))
        self.finish_text = self.user_text("finish_text", tr("Finish"))
        self.dsq_text = self.user_text("disqualify_text", "DSQ")
        self.last_lap_text = self.user_text("last_lap_text", tr("Last lap"))
        self.limiter_off_text = self.user_text("speed_limiter_off_text", tr("Off"))
        decimals = f".{'8' * self.decimals_speed}" if self.decimals_speed else ""
        values = (
            *VALUE_SAMPLES, *(tr(text) for text in FCY_PHASES.values()), self.green_text, self.finish_text,
            self.last_lap_text, self.limiter_off_text, tr("Heavy"), f"888{decimals}", f"+88{decimals}",
        )
        pad = unit * 0.5
        self.chip_w = max(
            max(self.text_width("label", text) for text in self.captions.values()),
            self.text_width("strong", self.widest("strong", values)),
        ) + pad * 2
        self.chip_h = unit * 2.2
        self.gap = max(unit * 0.25, 2.0)
        self.vertical = wcfg["layout"] == 0
        count = max(len(self.keys), 1)
        step_w, step_h = (0.0, self.chip_h + self.gap) if self.vertical else (self.chip_w + self.gap, 0.0)
        self.slots = tuple(QRectF(step_w * index, step_h * index, self.chip_w, self.chip_h) for index in range(count))
        self.fitted = count  # chip slots of widget size
        self.set_size(*self.slots_size(count))
        self.pad = pad
        self.pit_timer = PitTimer(wcfg["pit_time_highlight_duration"])
        self.green_timer = GreenFlagTimer(wcfg["green_flag_duration"])
        self.blue_timer = BlueFlagTimer(wcfg["show_blue_flag_for_race_only"])
        self.traffic_timer = TrafficTimer(
            wcfg["traffic_maximum_time_gap"], wcfg["traffic_extended_duration"],
            wcfg["traffic_low_speed_threshold"], wcfg["show_traffic_while_off_track"],
        )
        self.limiter_watch = PitLimiterWatch()
        self.flash_seconds = max(float(wcfg["new_flag_flash_duration"]), 0.0) if wcfg["enable_new_flag_flash"] else 0.0
        self.alert_since: dict[tuple[str, str], float] = {}  # (item, color) of alert shown -> time raised
        self.clock = monotonic
        self.samples = tuple(self.sample_chip(key) for key in self.keys)

    def post_update(self):
        self.pit_timer.reset()
        self.blue_timer.reset()
        self.traffic_timer.reset()
        self.green_timer.reset()
        self.limiter_watch.reset()
        self.alert_since = {}

    def sample_chip(self, key: str) -> Chip:
        """Chip of item drawn before any update"""
        caption, value, color = PREVIEW_CHIPS[key]
        if key == "finish_state":
            value = self.finish_text
        elif key == "full_course_yellow":
            value = tr("Pits open")
        elif key == "last_lap":
            value = self.last_lap_text
        return Chip(key, self.captions[caption], value, color)

    # Size
    def slots_size(self, count: int) -> tuple[float, float]:
        """Widget size of first count chip slots"""
        if self.vertical:
            return self.chip_w, (self.chip_h + self.gap) * count - self.gap
        return (self.chip_w + self.gap) * count - self.gap, self.chip_h

    def fit_chips(self, count: int):
        """Live overlay as large as chips shown (one at least), every chip slot while unlocked or in edit mode
        (placement) and before start (pictures)"""
        if self.overlay_started and self.cfg.overlay["fixed_position"] and not realtime_state.editing:
            count = min(max(count, 1), len(self.slots))
        else:
            count = len(self.slots)
        if count != self.fitted:
            self.fitted = count
            self.set_size(*self.slots_size(count))
            self.update()  # resized: whole widget

    def should_hide(self) -> bool:
        """Asked on lock & edit mode changes (no update while in garage): size fitted then"""
        self.fit_chips(len(self.state or ()))
        return super().should_hide()

    # Paint
    def paintEvent(self, event):
        """Every item as sample chip before first update (picture of Overlays page, not live overlay), then active
        ones"""
        if self.state is None:
            if self.overlay_started:
                return
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
            text = readable_on(color)
            if chip.flash:  # colors swapped
                color, text = text, color
            rounded(painter, slot, radius, color)
            if self.depth_effects:
                self.shine(painter, slot, radius)
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

    # Update
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
        if self.urgency_order:
            chips.sort(key=lambda chip: URGENCY[chip.key])
        chips = self.flashed(chips)
        self.fit_chips(len(chips))
        self.refresh(tuple(chips))

    def flashed(self, chips: list[Chip]) -> list[Chip]:
        """Alerts raised less than flash duration ago (or changed color) flash, live overlay only"""
        if not self.flash_seconds or not self.overlay_started:
            return chips
        now = self.clock()
        last = self.alert_since
        since = {}
        result = []
        for chip in chips:
            if chip.alert:
                ident = (chip.key, chip.color)
                start = since[ident] = last.get(ident, now)
                age = now - start
                if age < self.flash_seconds and int(age / FLASH_PERIOD) % 2 == 0:
                    chip = chip._replace(flash=True)
            result.append(chip)
        self.alert_since = since
        return result

    # Items
    def read_pit_timer(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if in_pits and api.read.vehicle.in_garage():
            return None
        timer = self.pit_timer.update(in_pits, lap_etime)
        if timer == MAX_SECONDS:
            return None
        if timer < 0:  # left pit lane
            return Chip("pit_timer", self.captions["pit_out"], f"{-timer:.2f}", "surface_strong")
        if api.read.session.pit_open():
            return Chip("pit_timer", self.captions["pit"], f"{timer:.2f}", "positive")
        return Chip("pit_timer", self.captions["pit_closed"], tr("Closed"), "negative")

    def read_low_fuel(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        wcfg = self.wcfg
        if wcfg["show_low_fuel_for_race_only"] and not in_race:
            return None
        energy = minfo.energy.available and minfo.energy.estimatedLaps < minfo.fuel.estimatedLaps
        source = minfo.energy if energy else minfo.fuel
        amount = source.amountCurrent
        if not is_low_amount(wcfg, energy, amount, source.estimatedLaps, source.estimatedValidConsumption):
            return None
        if energy:
            return Chip("low_fuel", self.captions["energy"], f"{amount:.1f}%", "orange", True)
        return Chip("low_fuel", self.captions["fuel"], f"{self.unit_fuel(amount):.2f}{self.symbol_fuel}", "orange", True)

    def read_speed_limiter(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        state = self.limiter_watch.update()
        if state == LIMITER_HIDDEN:
            return None
        if state == LIMITER_OFF:  # pit lane driven without limiter
            if not self.wcfg["show_speed_limiter_off_warning"]:
                return None
            return Chip("speed_limiter", self.captions["limiter"], self.limiter_off_text, "negative", True)
        over = state == LIMITER_OVER
        return Chip("speed_limiter", self.captions["limiter"], self.limiter_value(), "negative" if over else "positive",
                    over)

    def limiter_value(self) -> str:
        """Difference to pit speed limit (if known & option on), current speed, else "On" """
        wcfg = self.wcfg
        if not wcfg["show_current_speed_while_limiter_on"]:
            return tr("On")
        speed = api.read.vehicle.speed()
        limit = pit_speed_limit()
        if wcfg["show_speed_limit_difference"] and limit:
            return f"{self.unit_speed(speed - limit):+.{self.decimals_speed}f}"
        return f"{self.unit_speed(speed):.{self.decimals_speed}f}"

    def read_yellow_flag(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        wcfg = self.wcfg
        if (wcfg["show_yellow_flag_for_race_only"] and not in_race) or not api.read.session.yellow_flag():
            return None
        distance = minfo.vehicles.nearestYellowAhead
        if distance > wcfg["yellow_flag_maximum_range_ahead"]:
            distance = minfo.vehicles.nearestYellowBehind
            if distance < -wcfg["yellow_flag_maximum_range_behind"]:
                return None
        arrow = "▲" if distance >= 0 else "▼"  # ahead, behind
        value = f"{arrow} {self.unit_dist(abs(distance)):.0f}{self.symbol_dist}"
        return Chip("yellow_flag", self.captions["yellow"], value, "caution", True)

    def read_blue_flag(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        seconds = self.blue_timer.update(in_race, lap_etime)
        if seconds == MAX_SECONDS:
            return None
        class_name = minfo.vehicles.nearestBlueClass
        class_style = self.cfg.user.classes.get(class_name)
        if class_style is not None:
            class_name = class_style["alias"]
        gap = blue_flag_gap() if self.wcfg["show_blue_flag_gap"] else MAX_SECONDS
        if gap == MAX_SECONDS:  # time under blue flag
            value = f"{seconds:.0f}s"
        else:  # gap of car lapping
            value = f"{gap:.1f}s" if gap < 9.95 else f"{gap:.0f}s"
        return Chip("blue_flag", class_name or self.captions["blue"], value, "blue", True)

    def read_start_lights(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        lights = self.green_timer.update(lap_etime)
        if lights > 0:
            return Chip("start_lights", self.captions["lights"], f"{lights}", "negative")
        if lights == 0:
            return Chip("start_lights", self.captions["green"], self.green_text, "positive")
        return None

    def read_traffic(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        gap = self.traffic_timer.update(in_pits, lap_etime)
        if gap == MAX_SECONDS:
            return None
        return Chip("traffic", self.captions["traffic"], f"{gap:.1f}s", "accent", True)

    def read_pit_request(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if not api.read.vehicle.pit_request():
            return None
        laps = run_laps(minfo.fuel, minfo.energy)
        safe = calc.pit_in_countdown_laps(laps, api.read.lap.progress())
        return Chip("pit_request", self.captions["pit_request"], f"{lap_text(safe)} - {lap_text(laps)}", "positive")

    def read_finish_state(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        state = api.read.vehicle.finish_state()
        if state == 1:
            return Chip("finish_state", self.captions["finish"], self.finish_text, "text")
        if state == 3:
            return Chip("finish_state", self.captions["finish"], self.dsq_text, "negative")
        return None

    def read_scheduled_repairs(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        seconds = api.read.vehicle.repair_time()
        if not seconds > 0:
            return None
        return Chip("scheduled_repairs", self.captions["repairs"], f"{seconds:.0f}s", "warning")

    def read_sector_yellow_flags(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if self.wcfg["show_sector_yellow_flags_for_race_only"] and not in_race:
            return None
        sectors = tuple(api.read.session.sector_yellow_flags())
        if not any(sectors):
            return None
        value = " ".join(f"S{index}" for index, flag in enumerate(sectors, start=1) if flag)
        return Chip("sector_yellow_flags", self.captions["sectors"], value, "caution", True)

    def read_full_course_yellow(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        phase = FCY_PHASES.get(api.read.session.yellow_flag_state())
        if phase is None:
            return None
        color = "negative" if phase == "Red flag" else "warning"
        return Chip("full_course_yellow", self.captions["fcy"], tr(phase), color, True)

    def read_penalty(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        penalty = pending_penalty()
        if not penalty:
            return None
        return Chip("penalty", self.captions["penalty"], penalty, "negative", True)

    def read_last_lap(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        if not on_last_lap(in_race):
            return None
        return Chip("last_lap", self.captions["finish"], self.last_lap_text, "text", True)

    def read_damage(self, lap_etime: float, in_pits: bool, in_race: bool) -> Chip | None:
        aero = heavy_damage()
        if aero is None:
            return None
        percent = round(aero * 100)
        value = f"{percent}%" if percent >= 1 else tr("Heavy")  # aero damage unknown or none: body, wheel
        return Chip("damage", self.captions["damage"], value, "orange", True)


def lap_text(laps: float) -> str:
    """Laps, one decimal under 10"""
    if not laps < 9999:  # also nan
        return DASH
    return f"{laps:.0f}" if laps > 9.94 else f"{laps:.1f}"
