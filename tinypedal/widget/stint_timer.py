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
Stint timer Widget

For endurance races: current stint time & laps, countdown to maximum stint length, driving
time of each driver of the car this session against a fair share (race length divided by
drivers) or a minimum driving time.

Driving time is counted from the driver name of the player car (teammates included while they
drive it), from the moment the widget runs: kept while widget reloads, reset on new session.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from .. import calculation as calc
from ..api_control import api
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ._base import Overlay
from ._race_aids import LEFT, RIGHT, ClassicCells, finite, option_colors

DASH = chr(0x2013)
MAX_STEP = 5.0  # seconds: longer jump of session time is not driving (pause, replay, rewind)
MAX_DRIVERS = 6  # driver rows shown at most
# Countdown & target state
NORMAL = 0
MET = 1
WARNING = 2
OVER = 3


class DriverTimes:
    """Driving time & laps of each driver of player car in current session, drivers in order seen"""

    def __init__(self):
        self.times: dict[str, float] = {}
        self.laps: dict[str, int] = {}
        self.session = None
        self.last_elapsed = -1.0
        self.last_lap = -1
        self.version = 0  # changed when drivers or times change

    def reset(self):
        self.times.clear()
        self.laps.clear()
        self.last_elapsed = -1.0
        self.last_lap = -1
        self.version += 1

    def update(self, session: Any, elapsed: float, driver: str, driving: bool, lap: int):
        """Add time since last update to driver (if driving), laps completed meanwhile"""
        if not finite(elapsed):
            return
        if session != self.session or elapsed < self.last_elapsed - MAX_STEP:  # new or restarted session
            self.session = session
            self.reset()
        if driver and driver not in self.times:
            self.times[driver] = 0.0
            self.laps[driver] = 0
            self.version += 1
        step = elapsed - self.last_elapsed
        if driving and driver and self.last_elapsed >= 0 and 0 < step < MAX_STEP:
            self.times[driver] += step
            self.version += 1
        if driver and self.last_lap >= 0 and 0 < lap - self.last_lap < 3:
            self.laps[driver] += lap - self.last_lap
        self.last_elapsed = elapsed
        self.last_lap = lap


DRIVER_TIMES = DriverTimes()  # shared by widget instances: kept while widget reloads


class DriverRow(NamedTuple):
    """Driving time of one driver, for drawing"""

    name: str
    driven: str
    remaining: str
    state: int  # NORMAL, MET (target reached)
    fraction: float  # driven part of target, -1 = no target
    current: bool  # driving now


class StintReading(NamedTuple):
    """Stint & driver readings, for drawing"""

    stint: str = DASH
    laps: str = DASH
    countdown: str = DASH
    countdown_state: int = NORMAL
    fair_share: str = DASH
    drivers: tuple[DriverRow, ...] = ()


class StintTimerMixin:
    """Stint & driving time readings, for classic & modern widget"""

    wcfg: Any

    def setup_stint(self):
        """Options"""
        wcfg = self.wcfg
        self.max_stint = max(float(wcfg["maximum_stint_minutes"]), 0.0) * 60
        self.stint_warning = max(float(wcfg["stint_warning_minutes"]), 0.0) * 60
        self.show_laps = bool(wcfg["show_stint_laps"])
        self.show_countdown = bool(wcfg["show_stint_countdown"])
        self.show_drivers = bool(wcfg["show_driver_times"])
        self.drivers_option = min(max(int(wcfg["number_of_drivers"]), 0), MAX_DRIVERS)
        self.minimum_drive = max(float(wcfg["minimum_driving_minutes"]), 0.0) * 60
        self.driver_times = DRIVER_TIMES

    def driver_rows(self) -> int:
        """Driver rows shown: number of drivers option, or drivers seen"""
        if not self.show_drivers:
            return 0
        return min(max(self.drivers_option, len(self.driver_times.times), 1), MAX_DRIVERS)

    def read_stint(self) -> StintReading:
        """Update driving times, readings"""
        times = self.driver_times
        driver = api.read.vehicle.driver_name()
        driving = api.read.vehicle.player_has_vehicle() and api.read.vehicle.in_paddock() != 2
        times.update(api.read.session.identifier()[0], api.read.session.elapsed(), driver, driving,
                     api.read.lap.completed_laps())
        stint = minfo.history.stintDataCurrent
        stint_time = stint.totalTime if finite(stint.totalTime) else 0.0
        countdown, countdown_state = self.countdown(stint_time)
        fair_share = self.fair_share()
        target = self.minimum_drive or fair_share
        rows = []
        for name, driven in tuple(times.times.items())[:MAX_DRIVERS]:
            if target > 0:
                left = target - driven
                rows.append(DriverRow(
                    name, calc.sec2countdown(driven), calc.sec2countdown(max(left, 0.0)),
                    MET if left <= 0 else NORMAL, round(min(driven / target, 1.0), 3), name == driver,
                ))
            else:
                rows.append(DriverRow(name, calc.sec2countdown(driven), DASH, NORMAL, -1.0, name == driver))
        return StintReading(
            stint=calc.sec2countdown(max(stint_time, 0.0)),
            laps=f"{max(min(stint.totalLaps, 999), 0)}",
            countdown=countdown,
            countdown_state=countdown_state,
            fair_share=calc.sec2countdown(fair_share) if fair_share > 0 else DASH,
            drivers=tuple(rows),
        )

    def countdown(self, stint_time: float) -> tuple[str, int]:
        """Time left to maximum stint length"""
        if not self.max_stint:
            return DASH, NORMAL
        left = self.max_stint - stint_time
        if left < 0:
            return f"-{calc.sec2countdown(-left)}", OVER
        return calc.sec2countdown(left), WARNING if left <= self.stint_warning else NORMAL

    def fair_share(self) -> float:
        """Race length divided by drivers (seconds), 0 if race length unknown (lap race)"""
        if api.read.session.finish_type() == 1:  # laps only
            return 0.0
        length = api.read.session.end()
        if not (finite(length) and 0 < length < 360000):
            return 0.0
        drivers = self.drivers_option or max(len(self.driver_times.times), 1)
        return length / drivers


class Realtime(StintTimerMixin, ClassicCells, Overlay):
    """Draw widget"""

    update_while_hidden = True  # driving time counted while hidden

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()
        self.setup_stint()

        # Config variable
        wcfg = self.wcfg
        self.gap = 2
        self.row_h = round(font_m.height * 1.25)
        width = self.text_cell_width(9)
        self.stats = [("stint", tr("Stint"))]
        if self.show_laps:
            self.stats.append(("laps", tr("Laps")))
        if self.show_countdown:
            self.stats.append(("countdown", tr("Max stint")))
        if self.show_drivers:
            self.stats.append(("fair_share", tr("Fair share")))
        self.stat_rects = tuple(
            (QRectF((width + self.gap) * index, 0, width, self.row_h),
             QRectF((width + self.gap) * index, self.row_h, width, self.row_h))
            for index in range(len(self.stats))
        )
        self.name_width = self.text_cell_width(14)
        self.time_width = self.text_cell_width(9)
        self.width_total = max(
            (width + self.gap) * len(self.stats) - self.gap,
            self.name_width + (self.time_width + self.gap) * 2,
        )
        self.colors = option_colors(
            wcfg, "font_color_caption", "background_color_caption", "font_color_reading", "background_color_reading",
            "font_color_current_driver", "font_color_target_met", "font_color_warning", "driving_time_bar_color",
        )
        self.rows = -1
        self.resize_rows(self.driver_rows())
        self.state = StintReading()

    def resize_rows(self, rows: int):
        """Widget height for number of driver rows"""
        if rows != self.rows:
            self.rows = rows
            self.resize(round(self.width_total), (self.row_h + self.gap) * (2 + rows) - self.gap)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_stint()
        self.resize_rows(self.driver_rows())
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        colors = self.colors
        state = self.state
        for (key, label), (caption_rect, value_rect) in zip(self.stats, self.stat_rects):
            self.draw_cell(painter, caption_rect, label, colors["font_color_caption"], colors["background_color_caption"])
            color = colors["font_color_reading"]
            if key == "countdown" and state.countdown_state in (WARNING, OVER):
                color = colors["font_color_warning"]
            self.draw_cell(painter, value_rect, getattr(state, key), color, colors["background_color_reading"])
        top = (self.row_h + self.gap) * 2
        for index in range(self.rows):
            row = state.drivers[index] if index < len(state.drivers) else None
            y = top + (self.row_h + self.gap) * index
            name_rect = QRectF(0, y, self.name_width, self.row_h)
            driven_rect = QRectF(name_rect.right() + self.gap, y, self.time_width, self.row_h)
            left_rect = QRectF(driven_rect.right() + self.gap, y, self.width_total - driven_rect.right() - self.gap,
                               self.row_h)
            background = colors["background_color_reading"]
            if row is None:
                for rect in (name_rect, driven_rect, left_rect):
                    self.draw_cell(painter, rect, DASH if rect is name_rect else "", colors["font_color_caption"],
                                   background)
                continue
            name_color = colors["font_color_current_driver"] if row.current else colors["font_color_reading"]
            name = self.fontMetrics().elidedText(
                row.name, Qt.TextElideMode.ElideRight, round(self.name_width - self.cell_padding() * 2))
            self.draw_cell(painter, name_rect, name, name_color, background, LEFT)
            self.draw_cell(painter, driven_rect, row.driven, colors["font_color_reading"], background, RIGHT)
            if row.fraction > 0:  # driven part of target
                painter.fillRect(QRectF(driven_rect.left(), driven_rect.bottom() - 2,
                                        driven_rect.width() * row.fraction, 2), colors["driving_time_bar_color"])
            color = colors["font_color_target_met"] if row.state == MET else colors["font_color_reading"]
            self.draw_cell(painter, left_rect, row.remaining, color, background, RIGHT)
