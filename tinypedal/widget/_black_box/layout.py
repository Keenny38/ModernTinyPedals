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
Black box widget, geometry

Every rectangle of the widget is computed once here from the settings and the font line
height (unit), so painting code only reads positions and never works them out itself.
From top to bottom: caption, RPM LEDs, car view (tyres, brakes, center column), bottom
info rows, incident trace, event log. The battery gauge runs beside the car view.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath

from .common import LAYOUT_NORMAL


@dataclass
class LayoutInput:
    """Settings the geometry depends on, already clamped"""

    unit: float  # font line height
    layout_mode: int
    has_center: bool
    center_height: float  # height needed by center column items
    max_steer: float  # degrees, 0 if tyres never turn
    show_caption: bool
    show_leds: bool
    show_battery_bar: bool
    battery_bar_left: bool
    battery_bar_scale: float
    bottom_rows: int
    trace_height_scale: float  # 0 if no incident trace
    event_lines: int  # 0 if no event log
    damage_panel_scale: float = 0.0  # height in lines of damage panel, 0 if hidden


@dataclass
class Layout:
    """Widget geometry"""

    unit: float
    gap: int
    width: float
    height: float
    brake_bar_w: int
    brake_bar_gap: int
    led_h: int
    row_h: int
    event_row_h: int
    rect_bg: QRectF
    rect_caption: QRectF
    rect_leds: QRectF
    rect_center: QRectF
    rect_car_view: QRectF
    rect_battery: QRectF
    rect_trace: QRectF
    rect_damage: QRectF
    path_tyre: QPainterPath
    local_tyre: QRectF
    rects_tyre: list[QRectF] = field(default_factory=list)
    rects_disc: list[QRectF] = field(default_factory=list)
    bottom_rows: list[tuple[QRectF, QRectF]] = field(default_factory=list)
    event_rows: list[QRectF] = field(default_factory=list)


def build_layout(spec: LayoutInput) -> Layout:
    """Compute widget geometry"""
    unit = spec.unit
    gap = round(unit * 0.25)
    tyre_w, tyre_h = round(unit * 2.1), round(unit * 2.9)
    # Brake: thin vertical bar next to tyre, temperature written beside it
    brake_w, brake_h = round(unit * 2.1), round(tyre_h * 0.8)
    brake_bar_w = max(round(unit * 0.32), 3)
    brake_bar_gap = round(unit * 0.15)

    # Room around tyres, so turned tyres do not overlap brakes or widget edges
    steer_sin = math.sin(math.radians(spec.max_steer))
    pad_x = round(tyre_h * steer_sin / 2)
    pad_y = round(tyre_w * steer_sin / 2)
    brake_gap = round(unit * 0.12)  # brake bar close to tyre (turned tyre may touch it at full lock)
    side_w = pad_x + tyre_w + brake_gap + brake_w

    center_between_tyres = spec.has_center and spec.layout_mode == LAYOUT_NORMAL
    center_between = round(unit * 5.2) if center_between_tyres else round(unit * 0.8)
    content_w = side_w * 2 + center_between + gap * 2

    # Battery bar: full-height side gauge, outside the tyre/brake columns, left or right
    battery_bar_w = max(round(unit * spec.battery_bar_scale), 4) if spec.show_battery_bar else 0
    battery_extra = battery_bar_w + gap if spec.show_battery_bar else 0
    content_x = battery_extra if spec.show_battery_bar and spec.battery_bar_left else 0
    width = content_w + battery_extra

    # Caption on top, then RPM LEDs (span full width, above everything else)
    caption_h = round(unit * 0.9) if spec.show_caption else 0
    rect_caption = QRectF(0, 0, width, caption_h)
    led_h = round(unit * 0.55) if spec.show_leds else 0
    led_y = caption_h + (gap if caption_h else 0)
    top_y = led_y + (led_h + gap if led_h else 0)
    rect_leds = QRectF(content_x + round(unit * 0.3), led_y + round(gap * 0.6), content_w - round(unit * 0.6), led_h)

    axle_gap = round(unit * 0.9) + pad_y * 2
    if center_between_tyres:  # taller if center column needs more room
        axle_gap += max(round(spec.center_height - (pad_y * 2 + tyre_h * 2 + axle_gap)), 0)
    body_h = pad_y + tyre_h * 2 + axle_gap + pad_y

    # All tyres share the same size, so the rounded path is built once instead of every frame
    local_tyre = QRectF(-tyre_w / 2, -tyre_h / 2, tyre_w, tyre_h)
    path_tyre = QPainterPath()
    path_tyre.addRoundedRect(local_tyre, tyre_w * 0.28, tyre_w * 0.28)

    right_x = content_x + content_w - side_w
    rects_tyre, rects_disc = [], []
    for index in range(4):
        is_right = index % 2
        top = top_y + pad_y + (0 if index < 2 else tyre_h + axle_gap)
        if is_right:
            brake_x = right_x
            tyre_x = right_x + brake_w + brake_gap
        else:
            tyre_x = content_x + pad_x
            brake_x = content_x + pad_x + tyre_w + brake_gap
        brake_top = top + (tyre_h - brake_h) / 2
        rects_tyre.append(QRectF(tyre_x, top, tyre_w, tyre_h))
        rects_disc.append(QRectF(brake_x, brake_top, brake_w, brake_h))

    # Center column
    inset = round(unit * 0.3)
    bottom_y = top_y + body_h
    if center_between_tyres:
        rect_center = QRectF(content_x + side_w + gap, top_y, center_between, body_h)
    elif spec.has_center:  # vertical: below tyres, full content width
        rect_center = QRectF(content_x + inset, bottom_y + gap, content_w - inset * 2, spec.center_height)
        bottom_y = rect_center.bottom()
    else:
        rect_center = QRectF()
    # Car view: tyres, brakes & center column area
    edge = round(unit * 0.08)
    rect_car_view = QRectF(content_x + edge, top_y, content_w - edge * 2, body_h)
    car_bottom = bottom_y

    # Bottom rows: fuel gauge, energy gauge (each spans both halves), stint comparison.
    # Damage panel at bottom right, rows share the width left of it.
    row_h = round(unit * 1.05)
    rows_h = spec.bottom_rows * (row_h + gap) - gap if spec.bottom_rows else 0
    if spec.damage_panel_scale > 0:
        panel_h = max(round(unit * spec.damage_panel_scale), rows_h, round(unit * 2))
        panel_w = round(panel_h * 0.75)
        rect_damage = QRectF(content_x + content_w - inset - panel_w, bottom_y + gap, panel_w, panel_h)
        rows_right = rect_damage.left() - gap
    else:
        panel_h = 0
        rect_damage = QRectF()
        rows_right = content_x + content_w - inset
    row_w = (rows_right - content_x - inset - gap) / 2
    bottom_rows = []
    for row in range(spec.bottom_rows):
        row_top = bottom_y + gap + row * (row_h + gap)
        bottom_rows.append((
            QRectF(content_x + inset, row_top, row_w, row_h),
            QRectF(rows_right - row_w, row_top, row_w, row_h),
        ))
    block_h = max(rows_h, panel_h)
    if block_h:
        bottom_y += block_h + gap

    # Incident trace: speed, throttle & brake over recorder duration
    if spec.trace_height_scale > 0:
        trace_h = max(round(unit * spec.trace_height_scale), round(unit))
        rect_trace = QRectF(content_x + inset, bottom_y + gap, content_w - inset * 2, trace_h)
        bottom_y = rect_trace.bottom()
    else:
        rect_trace = QRectF()

    # Event log, one line per event
    event_row_h = round(unit * 0.85)
    event_rows = []
    for line in range(spec.event_lines):
        event_rows.append(QRectF(content_x + inset, bottom_y + gap + line * event_row_h,
                                 content_w - inset * 2, event_row_h))
    if spec.event_lines:
        bottom_y += gap + spec.event_lines * event_row_h

    height = bottom_y + (gap if bottom_y > car_bottom else 0)
    if spec.show_battery_bar:
        battery_x = 0 if spec.battery_bar_left else content_x + content_w + gap
        rect_battery = QRectF(battery_x, top_y, battery_bar_w, car_bottom - top_y)
    else:
        rect_battery = QRectF()

    return Layout(
        unit=unit, gap=gap, width=width, height=height,
        brake_bar_w=brake_bar_w, brake_bar_gap=brake_bar_gap, led_h=led_h, row_h=row_h,
        event_row_h=event_row_h, rect_bg=QRectF(0, 0, width, height), rect_caption=rect_caption,
        rect_leds=rect_leds, rect_center=rect_center, rect_car_view=rect_car_view,
        rect_battery=rect_battery, rect_trace=rect_trace, rect_damage=rect_damage, path_tyre=path_tyre,
        local_tyre=local_tyre, rects_tyre=rects_tyre, rects_disc=rects_disc,
        bottom_rows=bottom_rows, event_rows=event_rows,
    )
