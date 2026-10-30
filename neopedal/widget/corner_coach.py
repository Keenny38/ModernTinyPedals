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
Corner coach Widget

Next corner of reference lap (lap telemetry viewer reference, as telemetry comparison): official number or
name (else number of corner found on reference lap), distance to its apex, distance to reference braking point,
then where you braked against it; after each corner, your minimum (apex) speed against reference lap.

Reference corners are prepared once per reference lap in background thread (userfile.corner_coach): an update
only follows car along prepared corners.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from .. import units
from ..api_control import api
from ..demo_state import drawing_demo
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ..userfile.corner_coach import (
    CoachCorner,
    CoachReference,
    CoachState,
    CornerResult,
    CornerTracker,
    ReferenceCorners,
    official_text,
)
from ..userfile.reference_trace import ReferenceLoader, stop_loading
from ..userfile.telemetry_lap import lap_folder_name
from ._base import Overlay
from ._race_aids import LEFT, RIGHT, ClassicCells, finite, option_colors

if TYPE_CHECKING:
    from ..template.widget_config_types import CornerCoachConfig

REFERENCE_STEP = 10.0  # meters between resampled values of reference trace (only its lap file is used)
TRACK_CHECK = 1.0  # seconds between reads of track & class name
DISTANCE_STEP = 5  # distances shown rounded to it (meters or feet)
CAPTIONS = {"next": "Next", "brake": "Brake", "apex": "Apex"}
VALUE_CHARS = 18  # characters of reading cells (classic layout)

# Braking kinds (color of braking text)
BRAKE_AHEAD = "ahead"  # reference braking point ahead
BRAKE_NOW = "now"  # reference braking point passed, not braked yet
BRAKE_ON_POINT = "on_point"  # braked within tolerance of reference braking point
BRAKE_EARLY = "early"
BRAKE_LATE = "late"
BRAKE_NONE = "none"  # reference lap does not brake for this corner


class CoachView(NamedTuple):
    """Texts drawn (repaint key)"""

    status: str = ""  # shown instead of rows (no reference lap)
    corner: str = ""  # next corner
    distance: str = ""  # to its apex
    brake: str = ""
    brake_kind: str = ""
    apex_corner: str = ""  # last corner driven
    apex_speed: str = ""  # minimum speed there
    apex_delta: str = ""  # against reference lap
    apex_gain: int = 0  # 1 faster, -1 slower, 0 same


class CornerCoachMixin:
    """Reference corners & current lap tracking, texts of classic & modern widget"""

    wcfg: CornerCoachConfig
    cfg: Any

    def setup_coach(self):
        wcfg = self.wcfg
        telemetry = self.cfg.path.telemetry
        self.loader = ReferenceLoader(telemetry, wcfg["reference_lap_source"], REFERENCE_STEP)
        self.prepared = ReferenceCorners(telemetry)
        self.tracker = CornerTracker()
        self.reference: CoachReference | None = None  # corners tracker follows
        self.tolerance = max(float(wcfg["braking_point_tolerance"]), 0.0)
        shown = (("next", wcfg["show_next_corner"]), ("brake", wcfg["show_braking_point"]),
                 ("apex", wcfg["show_apex_speed"]))
        self.rows = tuple(row for row, show in shown if show) or ("next",)
        self.captions = {row: tr(CAPTIONS[row]) for row in self.rows}
        self.unit_dist = units.set_unit_distance(self.cfg.units["distance_unit"])
        self.symbol_dist = units.set_symbol_distance(self.cfg.units["distance_unit"])
        self.speed_unit = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.speed_symbol = units.set_symbol_speed(self.cfg.units["speed_unit"])
        self.track = ""
        self.track_time = -TRACK_CHECK

    def stop(self):
        stop_loading()
        super().stop()  # type: ignore[misc]

    def vehicle_reset(self):
        """Driving of previous car or session forgotten (next corner braking, last corner driven)"""
        self.tracker.clear()
        self.tracker.last = None

    def read_coach(self) -> CoachView:
        """Sample car, follow it along reference corners: texts drawn"""
        reference = self.demo_reference() if drawing_demo() else self.poll_reference()
        if reference is not self.reference:
            self.reference = reference
            if reference is None:
                self.tracker.reset((), 0.0)
            else:  # new reference lap (new record): last corner driven still shown
                last = self.tracker.last
                self.tracker.reset(reference.corners, reference.length)
                self.tracker.last = self.demo_last() if drawing_demo() else last
        if reference is None or not reference.corners:
            return CoachView(status=tr("No reference lap"))
        distance = self.lap_distance()
        if finite(distance) and reference.length > 0:
            distance %= reference.length  # estimated distance goes a bit past lap line before game resets it
        read = api.read
        self.tracker.update(distance, read.vehicle.speed() * 3.6, read.inputs.brake_raw())
        return self.view(self.tracker.state(distance))

    def poll_reference(self) -> CoachReference | None:
        """Reference lap of current track & class, its corners prepared in background thread"""
        now = time.monotonic()
        if now - self.track_time >= TRACK_CHECK:
            self.track_time = now
            self.track = lap_folder_name(api.read.session.combo_name())
        self.loader.poll(self.track, now, api.read.lap.track_length())
        track_map = minfo.mapping.trackMap  # taken once: coordinates & distances of the same map
        self.prepared.poll(self.loader.trace, self.track, track_map.coordinates, track_map.elevations)
        return self.prepared.reference

    def demo_reference(self) -> CoachReference:
        """Reference corners of simulated race (overlay pictures)"""
        from ..demo_data import COACH_CORNERS, TRACK_LENGTH

        if self.reference is not None:
            return self.reference
        return CoachReference("", (0, 0), TRACK_LENGTH, tuple(
            CoachCorner(official_text(label, True), *values) for label, *values in COACH_CORNERS))

    @staticmethod
    def demo_last() -> CornerResult:
        from ..demo_data import COACH_LAST

        label, min_speed, reference_speed = COACH_LAST
        return CornerResult(official_text(label, True), min_speed, reference_speed)

    def lap_distance(self) -> float:
        """Car lap distance: estimated between game updates (delta module), smooth at any speed"""
        if self.cfg.user.setting["module_delta"]["enable"]:
            return minfo.delta.lapDistance
        return api.read.lap.distance()

    def view(self, state: CoachState | None) -> CoachView:
        """Texts of coaching state"""
        if state is None:
            return CoachView(status=tr("No reference lap"))
        brake, kind = self.brake_text(state)
        apex_corner = apex_speed = apex_delta = ""
        apex_gain = 0
        last = state.last
        if last is not None:
            speed = round(self.speed_unit(last.min_speed / 3.6))
            delta = speed - round(self.speed_unit(last.reference_speed / 3.6))
            apex_corner = last.label
            apex_speed = f"{speed} {self.speed_symbol}"
            apex_delta = f"{delta:+d}" if delta else "0"
            apex_gain = (delta > 0) - (delta < 0)
        return CoachView("", state.label, self.distance_text(state.to_corner), brake, kind, apex_corner, apex_speed,
                         apex_delta, apex_gain)

    def brake_text(self, state: CoachState) -> tuple[str, str]:
        """Braking text & kind: distance to reference braking point, then braking against it"""
        if state.to_brake is None:
            return tr("No braking"), BRAKE_NONE
        gap = state.brake_gap
        if gap is not None:
            if abs(gap) <= self.tolerance:
                return tr("On point"), BRAKE_ON_POINT
            if gap > 0:
                return f"{self.distance_text(gap)} {tr('late')}", BRAKE_LATE
            return f"{self.distance_text(-gap)} {tr('early')}", BRAKE_EARLY
        if state.to_brake > 0:
            return self.distance_text(state.to_brake), BRAKE_AHEAD
        return tr("Now"), BRAKE_NOW

    def distance_text(self, meters: float) -> str:
        """Distance in user unit, rounded to DISTANCE_STEP"""
        value = round(self.unit_dist(max(meters, 0.0)) / DISTANCE_STEP) * DISTANCE_STEP
        return f"{value} {self.symbol_dist}"


class Realtime(CornerCoachMixin, ClassicCells, Overlay):
    """Draw widget"""

    wcfg: CornerCoachConfig

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()
        self.setup_coach()

        # Config variable
        wcfg = self.wcfg
        gap = max(int(wcfg["bar_gap"]), 0)
        self.colors = option_colors(
            wcfg, "font_color_caption", "background_color_caption", "font_color_reading", "background_color",
            "font_color_time_gain", "font_color_time_loss", "font_color_warning",
        )
        caption_w = self.text_cell_width(max(len(caption) for caption in self.captions.values()))
        value_w = self.text_cell_width(VALUE_CHARS)
        self.rect_rows = {}
        top = 0.0
        for row in self.rows:
            self.rect_rows[row] = (QRectF(0, top, caption_w, font_m.height),
                                   QRectF(caption_w, top, value_w, font_m.height))
            top += font_m.height + gap
        self.rect_status = QRectF(0, 0, caption_w + value_w, font_m.height)

        # Config canvas
        self.resize(int(caption_w + value_w), max(int(top - gap), 1))
        self.state = CoachView()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_coach()
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        colors = self.colors
        state = self.state
        if state.status:
            self.draw_cell(painter, self.rect_status, state.status, colors["font_color_reading"],
                           colors["background_color"])
            return
        for row, (caption, value) in self.rect_rows.items():
            self.draw_cell(painter, caption, self.captions[row], colors["font_color_caption"],
                           colors["background_color_caption"])
            painter.fillRect(value, colors["background_color"])
            if row == "next":
                self.draw_pair(painter, value, state.corner, state.distance, colors["font_color_reading"])
            elif row == "brake":
                self.draw_cell(painter, value, state.brake, self.brake_color(state.brake_kind), None, RIGHT)
            elif state.apex_speed:
                delta_w = self.font_m.width * (len(state.apex_delta) + 1)
                self.draw_pair(painter, value.adjusted(0, 0, -delta_w, 0), state.apex_corner, state.apex_speed,
                               colors["font_color_reading"], len(state.apex_delta) + 1)
                self.draw_cell(painter, value, state.apex_delta, self.gain_color(state.apex_gain), None, RIGHT)

    def draw_pair(self, painter: QPainter, rect: QRectF, left: str, right: str, color: QColor, used: int = 0):
        """Name on left (cut to room left), reading on right (used: characters of cell already taken)"""
        room = VALUE_CHARS - used - len(right) - 1
        if len(left) > room:
            left = f"{left[:max(room - 1, 0)]}…" if room > 1 else ""
        self.draw_cell(painter, rect, left, self.colors["font_color_reading"], None, LEFT)
        self.draw_cell(painter, rect, right, color, None, RIGHT)

    def brake_color(self, kind: str) -> QColor:
        colors = self.colors
        if kind == BRAKE_ON_POINT:
            return colors["font_color_time_gain"]
        if kind in (BRAKE_NOW, BRAKE_EARLY, BRAKE_LATE):
            return colors["font_color_warning"]
        return colors["font_color_reading"]

    def gain_color(self, gain: int) -> QColor:
        colors = self.colors
        if gain > 0:
            return colors["font_color_time_gain"]
        if gain < 0:
            return colors["font_color_time_loss"]
        return colors["font_color_reading"]

