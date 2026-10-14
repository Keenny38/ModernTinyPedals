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
Black box widget, repaint regions

Each painted part (tyre corner, center column, chips, gauges, damage panel, trace, event log) has
its own state and bounding rect. An update repaints only parts whose state changed or that animate,
and paint skips parts outside the repainted region. Qt clears the region (translucent window) and
clips painting to it: background layer and every part reaching into it are drawn again, as in a
full repaint. A bounding rect holds everything its part may draw (turned & moving wheels, glows,
outlines, shadows), whatever its state.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget

from .._painter import DirtyRegion
from .common import REAR_MAX_STEER
from .status import icon_glow_rect

if TYPE_CHECKING:
    from ...template.widget_config_types import BlackBoxConfig

PART_MARGIN = 2  # widget pixels around a part: antialiased edges, rounding of scaled rects
WHEEL_PARTS = ("wheel0", "wheel1", "wheel2", "wheel3")
WHOLE_REPAINT_SHARE = 0.5  # changed parts covering more of the widget: whole widget repainted
PULSE_STEPS = 40  # visible steps of alert pulse strength (damage panel repainted only on step change)


class RegionMixin:
    """Repaint changed parts only"""

    # Attributes set by black box widget class (widget/black_box.py) or other parts
    abs_active: Any
    abs_level: Any
    abs_seen: Any
    alert_pulse: Any
    battery_charge: Any
    battery_highlight: Any
    battery_key: Any
    battery_state: Any
    battery_warning: Any
    body_damage: Any
    bottom_rows: Any
    brake: Any
    brake_bias: Any
    brake_cold: Any
    brake_fades: Any
    brake_heat_balance: Any
    brake_hot: Any
    brake_migration: Any
    browse_incident: Any
    center_key: Any
    center_order: Any
    clutch: Any
    damage_aero: Any
    damage_detached: Any
    damage_key: Any
    damage_puncture: Any
    damage_suspension: Any
    damper_key: Any
    delta_best: Any
    delta_shown: Any
    depth_effects: Any
    displayed_incident: Any
    devicePixelRatioF: Any
    energy: Any
    energy_available: Any
    energy_capacity: Any
    energy_gauge: Any
    energy_laps: Any
    energy_start: Any
    event_log: Any
    event_rows: Any
    fit: Any
    fuel: Any
    fuel_capacity: Any
    fuel_gauge: Any
    fuel_laps: Any
    fuel_start: Any
    gauge_key: Any
    gauge_low: Any
    gear: Any
    headlights: Any
    icons_height: Any
    ignition: Any
    impact_position: Any
    impact_visible: Any
    in_pits: Any
    incident_replay: Any
    laptime_current: Any
    led_h: Any
    leds_key: Any
    limiter: Any
    locking_front: Any
    locking_rear: Any
    max_steer: Any
    modules: Any
    motor_map_level: Any
    oil_temp: Any
    outline_width: Any
    presence: Any
    pulse: Any
    recorder: Any
    rect: Any
    rect_battery: Any
    rect_center: Any
    rect_damage: Any
    rect_leds: Any
    rect_trace: Any
    rects_disc: Any
    rects_susp: Any
    rects_tyre: Any
    refill: Any
    refuel: Any
    row_battery: Any
    row_damper: Any
    row_energy: Any
    row_fuel: Any
    row_stint: Any
    rpm: Any
    rpm_max: Any
    shadow_offset: Any
    show_battery_bar: Any
    show_damage_panel: Any
    setting_popup_fading: Any
    setting_popup_key: Any
    setting_popup_rect: Any
    show_event_log: Any
    show_setting_popup: Any
    show_recorder: Any
    show_suspension: Any
    showing_incident: Any
    side_gap: Any
    side_rows: Any
    side_rows_key: Any
    smooth_transition: Any
    speed: Any
    status_icon_boxes: Any
    status_icon_layout: Any
    status_key: Any
    stint_has_previous: Any
    stint_pressure: Any
    stint_pressure_delta: Any
    stint_row: Any
    stint_wear: Any
    stint_wear_delta: Any
    suspension_key: Any
    suspension_totaled: Any
    tc_active: Any
    tc_cut_level: Any
    tc_level: Any
    tc_seen: Any
    tc_slip_level: Any
    throttle: Any
    trace_version: Any
    tyre_diameters: Any
    tyre_fades: Any
    unit: Any
    update: Any
    water_temp: Any
    wcfg: BlackBoxConfig
    wheel_key: Any
    wheel_pad_front: Any
    wheel_pad_rear: Any
    wheel_targets: Any
    wheel_travel_px: Any
    wheels: Any
    width: Any
    height: Any

    dirty_region: DirtyRegion
    last_state: tuple
    last_parts: dict
    region_cache: tuple | None

    def repaint_changed(self):
        """Repaint parts whose state changed or that animate, whole widget after a layout change"""
        states = self.part_states()
        key = self.layout_key()
        if key != self.last_state:
            self.last_state = key
            self.last_parts = states
            self.update()
            return
        animated = self.animating_parts()
        last = self.last_parts
        changed = [name for name, state in states.items() if name in animated or state != last.get(name)]
        self.last_parts = states
        if changed:
            rects = self.part_rects()
            dirty = [rects[name] for name in changed if not rects[name].isEmpty()]
            bounding = QRect()
            for rect in dirty:
                bounding = bounding.united(rect)
            if bounding.width() * bounding.height() > self.width() * self.height() * WHOLE_REPAINT_SHARE:
                self.update()  # most of the widget: whole repaint, no clip (clipped drawing is slower)
                return
            self.dirty_region.update(cast(QWidget, self), dirty, self.uncut_cached)

    def uncut_cached(self, rects: list[QRect]) -> list[QRect]:
        """uncut, cached per layout & rects (the same parts change together update after update)"""
        self.part_rects()
        cache = cast(tuple, self.region_cache)[4]
        key = tuple(rect.getRect() for rect in rects)
        result = cache.get(key)
        if result is None:
            if len(cache) >= 256:
                cache.clear()
            result = cache[key] = self.uncut(rects)
        return result

    def uncut(self, rects: list[QRect]) -> list[QRect]:
        """Repaint rects grown over gradient shapes their edges would cut

        Raster engine steps a gradient from where a span starts, a span cut by the repaint region starts
        there: a level off a full repaint. Spans are rows: a shape is covered on the rows the region reaches
        into it, a turned one (tyre gloss) whole.
        """
        region = QRegion()
        for rect in rects:
            region += rect
        bands = self.gradient_bands()
        grown = True
        while grown:
            grown = False
            for band, turned in bands:
                overlap = region.intersected(band)
                if overlap.isEmpty():
                    continue
                strips = [band] if turned else [QRect(band.left(), row.top(), band.width(), row.height())
                                                for row in region_rects(overlap)]
                for strip in strips:
                    if not QRegion(strip).subtracted(region).isEmpty():
                        region += strip
                        grown = True
        return region_rects(region)

    def layout_key(self) -> tuple:
        """Anything that changes widget as a whole (repainted whole once changed)"""
        return self.modules.version, self.presence, self.fit, self.width(), self.height()

    def part_states(self) -> dict[str, tuple]:
        """What each shown part draws (see drawn): texts as displayed, colors, lengths"""
        states: dict[str, tuple] = {}
        if self.led_h:
            states["leds"] = self.leds_key()
        for index, (name, wheel) in enumerate(zip(WHEEL_PARTS, self.wheels)):
            states[name] = (self.wheel_key(index, wheel), self.suspension_key(index, wheel))
        if not self.rect_center.isNull():
            states["center"] = self.center_key()
        states["status"] = self.status_key()
        states["side_rows"] = self.side_rows_key()
        if self.row_battery:
            states["battery"] = self.battery_key(self.rect_battery)
        rows = iter(self.bottom_rows)
        if self.row_fuel:
            left, right = next(rows)
            states["fuel"] = self.gauge_key(left.united(right), self.fuel_gauge())
        if self.row_energy:
            left, right = next(rows)
            states["energy"] = (self.gauge_key(left.united(right), self.energy_gauge())
                                if self.energy_available else None,)
        if self.row_stint:
            next(rows)
            states["stint"] = self.stint_row()
        if self.row_damper:
            left, right = next(rows)
            states["damper"] = self.damper_key(left.united(right))
        if self.show_damage_panel:
            states["damage"] = (self.damage_key(), self.damage_pulse_step())
        if self.show_recorder:
            shown = self.displayed_incident()  # by time: a new incident in a full list keeps the count
            states["trace"] = (
                -1 if shown is not None else self.trace_version, len(self.recorder.incidents),
                shown.time if shown is not None else None,
                self.browse_incident.time if self.browse_incident is not None else None,
            )
        if self.show_event_log:
            states["events"] = tuple(self.event_log.events)  # same event logged again: rows shift
        if self.show_setting_popup:
            states["popup"] = self.setting_popup_key()
        return states

    def animating_parts(self) -> set[str]:
        """Parts moving on screen without data change: color fades, pulsing alerts, incident replay cursor,
        setting pop-up fade (shift flash & battery flow: in their keys)"""
        parts: set[str] = set()
        if self.smooth_transition:
            now = monotonic()
            for name, tyre_fade, brake_fade in zip(WHEEL_PARTS, self.tyre_fades, self.brake_fades):
                # both checked: each clears its pending final repaint
                if tyre_fade.needs_repaint(now) | brake_fade.needs_repaint(now):
                    parts.add(name)
        if self.incident_replay and self.show_recorder and self.showing_incident():
            parts.add("trace")
        if self.alert_pulse:
            for name, wheel in zip(WHEEL_PARTS, self.wheels):
                if wheel.warning or wheel.status or wheel.surface_hot or (self.show_suspension and (
                        wheel.susp_bump or wheel.susp_airborne or self.suspension_totaled(wheel))):
                    parts.add(name)
            if self.gauge_low():
                parts.update(("fuel", "energy"))
        if self.show_setting_popup and self.setting_popup_fading():
            parts.add("popup")
        return parts

    def damage_pulse_step(self) -> int:
        """Visible step of damage panel alert pulse (detached part, puncture): in damage state, repainted only when
        pulse changes visibly (PULSE_STEPS), not every update; 0 if not pulsing"""
        if self.alert_pulse and self.show_damage_panel and (
            any(self.damage_detached) or any(self.damage_puncture) or max(self.body_damage, default=0) >= 3
        ):
            return round(self.pulse() * PULSE_STEPS)
        return 0

    def animating(self) -> bool:
        """Something moves on screen without data change"""
        return bool(self.animating_parts())

    def part_rects(self) -> dict[str, QRect]:
        """Bounding rect of each part in widget coordinates (content fit applied, margin added),
        computed once per layout & size"""
        key = (self.fit, self.width(), self.height())
        cache = self.region_cache  # cleared on relayout
        if cache is not None and cache[0] == key:
            return cache[1]
        fit = self.fit
        widget = self.rect()
        rects = {}
        bounds = self.part_bounds()
        # Farthest point a turned wheel part draws from its pivot (tyre center, inside the bound)
        reaches = tuple(math.hypot(bounds[name].width(), bounds[name].height()) for name in WHEEL_PARTS)
        for name, bound in bounds.items():
            if bound.isEmpty():  # part not drawn (icons or chips without room)
                rects[name] = QRect()
                continue
            mapped = QRectF(fit.offset_x + bound.x() * fit.scale, fit.offset_y + bound.y() * fit.scale,
                            bound.width() * fit.scale, bound.height() * fit.scale)
            rects[name] = mapped.toAlignedRect().adjusted(
                -PART_MARGIN, -PART_MARGIN, PART_MARGIN, PART_MARGIN).intersected(widget)
        bands = [(self.mapped(shape).intersected(widget), turned) for shape, turned in self.gradient_shapes()]
        self.region_cache = (key, rects, reaches, [(band, turned) for band, turned in bands if not band.isEmpty()], {})
        return rects

    def mapped(self, rect: QRectF) -> QRect:
        """Widget pixels a content rect covers"""
        fit = self.fit
        return QRectF(fit.offset_x + rect.x() * fit.scale, fit.offset_y + rect.y() * fit.scale,
                      rect.width() * fit.scale, rect.height() * fit.scale).toAlignedRect()

    def gradient_bands(self) -> list[tuple[QRect, bool]]:
        """Widget rects of shapes filled with a gradient changing along x, turned or not (see uncut)"""
        self.part_rects()
        return cast(tuple, self.region_cache)[3]

    def gradient_shapes(self) -> list[tuple[QRectF, bool]]:
        """Content rects holding every shape filled with a gradient changing along x, whatever its state:
        center bars, gauge level shades, integrity gauge & impact cone, icon glows, (turned) tyre gloss & damper
        body, and whether it may be turned (mapped to the widget pixels they touch)"""
        shapes = []
        if not self.rect_center.isNull():
            shapes.append(self.rect_center)
        rows = iter(self.bottom_rows)
        for gauge, shown in ((True, self.row_fuel), (True, self.row_energy), (False, self.row_stint),
                             (False, self.row_damper)):
            if shown:
                left, right = next(rows)
                if gauge:
                    shapes.append(left.united(right))
        if self.show_damage_panel:
            shapes.append(self.rect_damage)
        for box in self.status_icon_layout()[:3]:  # icons with glow: headlights, wipers, engine
            if box is not None:
                shapes.append(icon_glow_rect(box))
        turned = len(shapes)
        for index, tyre in enumerate(self.rects_tyre):
            bound = self.wheel_bound(index)
            angle = self.max_steer if index < 2 else min(self.max_steer, REAR_MAX_STEER)
            pivot = tyre.center()
            if self.depth_effects:
                left, right = turned_span(tyre, pivot, angle, (0.0,))
                shapes.append(QRectF(left, bound.top(), right - left, bound.height()))
            susp = self.rects_susp[index]
            if not susp.isNull():
                travel = self.wheel_travel_px
                left, right = turned_span(susp, pivot, angle, (-travel, 0.0, travel))
                shapes.append(QRectF(left, bound.top(), right - left, bound.height()))
        return [(shape, index >= turned and self.max_steer > 0)
                for index, shape in enumerate(shapes)]

    def device_scale(self) -> float:
        """Device pixels per content unit"""
        return self.fit.scale * self.devicePixelRatioF()

    def wheel_reaches(self) -> tuple[float, ...]:
        """Farthest point each wheel part draws from its pivot (content units)"""
        self.part_rects()
        return cast(tuple, self.region_cache)[2]

    def part_shown(self, name: str, region: QRegion | None) -> bool:
        """Whether part reaches into region being painted (None: whole widget)"""
        return region is None or region.intersects(self.part_rects()[name])

    def part_bounds(self) -> dict[str, QRectF]:
        """Bounding rect of each part, content coordinates"""
        extra = self.unit * 0.1  # antialiased edges, outlines
        bounds = {}
        if self.led_h:
            glow = self.rect_leds.height() * 0.35 + extra  # glow around lit LEDs
            bounds["leds"] = self.rect_leds.adjusted(-glow, -glow, glow, glow)
        for index, name in enumerate(WHEEL_PARTS):
            bounds[name] = self.wheel_bound(index)
        if not self.rect_center.isNull():
            bounds["center"] = self.rect_center.adjusted(-extra, -extra, extra, extra)
        bounds["status"] = self.status_bound()
        bounds["side_rows"] = self.inflated(self.side_gap(True) if self.rects_tyre else QRectF(), extra)
        if self.row_battery:
            bounds["battery"] = self.rect_battery.adjusted(-extra, -extra, extra, extra)
        rows = iter(self.bottom_rows)
        for name, shown in (("fuel", self.row_fuel), ("energy", self.row_energy), ("stint", self.row_stint),
                            ("damper", self.row_damper)):
            if shown:
                left, right = next(rows)
                bounds[name] = left.united(right).adjusted(-extra, -extra, extra, extra)
        if self.show_damage_panel:
            bounds["damage"] = self.rect_damage.adjusted(-extra, -extra, extra, extra)
        if self.show_recorder:
            bounds["trace"] = self.rect_trace.adjusted(-extra, -extra, extra, extra)
        if self.show_event_log:
            events = QRectF()
            for row in self.event_rows:
                events = events.united(row)
            bounds["events"] = self.inflated(events, extra)
        if self.show_setting_popup:
            bounds["popup"] = self.setting_popup_rect().adjusted(-extra, -extra, extra, extra)
        return bounds

    def wheel_bound(self, index: int) -> QRectF:
        """Tyre, brake disc & coilover of a wheel: turned (corners reach outward), moved by wheel
        travel (reach above & below, see layout wheel pads), shadow & warning outline"""
        tyre = self.rects_tyre[index]
        bound = tyre.united(self.rects_disc[index])
        susp = self.rects_susp[index]
        if not susp.isNull():
            bound = bound.united(susp)
        reach = self.wheel_pad_front if index < 2 else self.wheel_pad_rear
        extra = self.shadow_offset * 1.3 + self.outline_width * 2 + self.unit * 0.1
        turn = tyre.width() * 0.5 if self.max_steer else 0.0  # turned corners, outer side (brake side has room)
        top, bottom = -reach - extra, reach + extra
        if index % 2:  # right side: tyre outside on the right
            return bound.adjusted(-extra, top, turn + extra, bottom)
        return bound.adjusted(-turn - extra, top, extra, bottom)

    def status_bound(self) -> QRectF:
        """Headlights & engine icons, with their glow (reaches beyond side gap)"""
        wcfg = self.wcfg
        if not self.rects_tyre or not (wcfg["show_headlights_indicator"] or wcfg["show_wipers_indicator"]
                                       or wcfg["show_engine_status"]):
            return QRectF()
        gap = self.side_gap(wcfg["status_icons_side"] == "Right")
        if gap.isNull():
            return gap
        glow = min(gap.width(), gap.height()) * 0.4 + self.unit * 0.1
        return gap.adjusted(-glow, -glow, glow, glow)

    @staticmethod
    def inflated(rect: QRectF, amount: float) -> QRectF:
        return rect.adjusted(-amount, -amount, amount, amount) if not rect.isNull() else rect


def region_rects(region: QRegion) -> list[QRect]:
    """Rects making up region"""
    return list(cast(Iterable[QRect], region))


def turned_span(rect: QRectF, pivot: QPointF, angle: float, shifts: tuple[float, ...]) -> tuple[float, float]:
    """Horizontal extent of rect moved vertically by shifts, turned around pivot by up to angle (degrees)
    either way"""
    xs: list[float] = []
    reach = 0.0
    steps = 16
    for shift in shifts:
        corners = [(x - pivot.x(), y + shift - pivot.y()) for x in (rect.left(), rect.right())
                   for y in (rect.top(), rect.bottom())]
        reach = max(reach, *(math.hypot(x, y) for x, y in corners))
        for step in range(steps + 1):
            radians = math.radians(angle * (2 * step / steps - 1))
            cos, sin = math.cos(radians), math.sin(radians)
            xs.extend(pivot.x() + x * cos - y * sin for x, y in corners)
    # Between sampled angles, a corner reaches at most reach x (1 - cos(half step)) further
    pad = reach * (1 - math.cos(math.radians(angle / steps))) + 0.5
    return min(xs) - pad, max(xs) + pad

