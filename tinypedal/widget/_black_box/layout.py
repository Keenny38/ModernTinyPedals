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

DAMAGE_PANEL_RATIO = 0.8  # damage panel width relative to its height
CENTER_WIDTH = 6.4  # center column width between tyres, in lines (room for merged rows like BB/BMIG)


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
    tyre_scale: float = 1.0  # tyres & brakes
    center_scale: float = 1.0  # center column width
    row_scale: float = 1.0  # gauge & stint rows height
    event_scale: float = 1.0  # event log line height
    corner_scale: float = 0.0  # background corner radius, relative to shorter side
    damage_position: str = "Bottom Right"  # corner of damage panel, outside main area
    suspension_scale: float = 0.0  # width of suspension (coilover) beside brake bar, 0 if hidden
    status_height: float = 0.0  # room for headlights & engine icons between axles, 0 if hidden


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
    rect_main: QRectF  # main card, without damage panel card (used for screen centering)
    path_bg: QPainterPath  # background shape: main area plus a tab under the damage panel
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
    rects_susp: list[QRectF] = field(default_factory=list)  # null rects if suspension hidden
    susp_extra: float = 0.0  # room taken by suspension inside brake column
    bottom_rows: list[tuple[QRectF, QRectF]] = field(default_factory=list)
    event_rows: list[QRectF] = field(default_factory=list)


def build_layout(spec: LayoutInput) -> Layout:
    """Compute widget geometry"""
    unit = spec.unit
    gap = round(unit * 0.25)
    tyre_unit = unit * spec.tyre_scale
    tyre_w, tyre_h = round(tyre_unit * 2.1), round(tyre_unit * 2.9)
    # Brake: thin vertical bar next to tyre, temperature written beside it
    brake_w, brake_h = round(tyre_unit * 2.1), round(tyre_h * 0.8)
    brake_bar_w = max(round(unit * 0.32), 3)
    brake_bar_gap = round(unit * 0.15)

    # Room around tyres, so turned tyres do not overlap brakes or widget edges
    # Exact extent of the turned rounded tyre (corner radius as in path_tyre), not a rough bound
    steer_sin = math.sin(math.radians(spec.max_steer))
    steer_cos = math.cos(math.radians(spec.max_steer))
    corner = tyre_w * 0.28
    core_w, core_h = tyre_w - corner * 2, tyre_h - corner * 2
    pad_x = max(math.ceil((core_w * steer_cos + core_h * steer_sin) / 2 + corner - tyre_w / 2), 0)
    pad_y = max(math.ceil((core_h * steer_cos + core_w * steer_sin) / 2 + corner - tyre_h / 2), 0)
    brake_gap = round(unit * 0.12)  # brake bar close to tyre (turned tyre may touch it at full lock)
    # Suspension: coilover drawn right beside the brake bar, before brake readings
    susp_w = max(round(unit * 0.5 * spec.suspension_scale), 4) if spec.suspension_scale > 0 else 0
    susp_extra = susp_w + brake_bar_gap if susp_w else 0
    brake_w += susp_extra
    side_w = pad_x + tyre_w + brake_gap + brake_w

    center_between_tyres = spec.has_center and spec.layout_mode == LAYOUT_NORMAL
    center_between = round(unit * CENTER_WIDTH * spec.center_scale) if center_between_tyres else round(unit * 0.8)
    content_w = side_w * 2 + center_between + gap * 2

    # Columns, left to right: [damage panel] [battery] content [battery] [damage panel]
    # Battery: gauge along the whole widget height. Damage panel: own column outside the main
    # area, on the left or right, flush with the chosen top or bottom corner of the widget.
    battery_bar_w = max(round(unit * spec.battery_bar_scale), 4) if spec.show_battery_bar else 0
    battery_extra = battery_bar_w + gap if spec.show_battery_bar else 0
    if spec.damage_panel_scale > 0:
        panel_h = max(round(unit * spec.damage_panel_scale), round(unit * 2))
        panel_w = round(panel_h * DAMAGE_PANEL_RATIO)
    else:
        panel_h = panel_w = 0
    damage_extra = panel_w  # panel card placed right against main card, no gap
    damage_left = spec.damage_position.endswith("Left")
    damage_top = spec.damage_position.startswith("Top")
    main_x = damage_extra if damage_left else 0  # main area starts after a left damage column
    content_x = main_x + (battery_extra if spec.show_battery_bar and spec.battery_bar_left else 0)
    width = content_w + battery_extra + damage_extra

    # Caption on top, then RPM LEDs (span content width, above everything else in it)
    caption_h = round(unit * 0.9) if spec.show_caption else 0
    rect_caption = QRectF(content_x, 0, content_w, caption_h)
    led_h = round(unit * 0.55) if spec.show_leds else 0
    led_y = caption_h + (gap if caption_h else 0)
    top_y = led_y + (led_h + gap if led_h else 0)
    rect_leds = QRectF(content_x + round(unit * 0.3), led_y + round(gap * 0.6), content_w - round(unit * 0.6), led_h)

    axle_gap = max(round(unit * 0.9) + pad_y * 2, math.ceil(spec.status_height))
    if center_between_tyres:  # taller if center column needs more room
        axle_gap += max(round(spec.center_height - (pad_y * 2 + tyre_h * 2 + axle_gap)), 0)
    body_h = pad_y + tyre_h * 2 + axle_gap + pad_y

    # All tyres share the same size, so the rounded path is built once instead of every frame
    local_tyre = QRectF(-tyre_w / 2, -tyre_h / 2, tyre_w, tyre_h)
    path_tyre = QPainterPath()
    path_tyre.addRoundedRect(local_tyre, tyre_w * 0.28, tyre_w * 0.28)

    right_x = content_x + content_w - side_w
    rects_tyre, rects_disc, rects_susp = [], [], []
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
        if susp_w:
            susp_x = (brake_x + brake_w - brake_bar_w - brake_bar_gap - susp_w if is_right
                      else brake_x + brake_bar_w + brake_bar_gap)
            rects_susp.append(QRectF(susp_x, top, susp_w, tyre_h))  # as tall as the tyre
        else:
            rects_susp.append(QRectF())

    # Center column
    inset = round(unit * 0.3)
    bottom_y: float = top_y + body_h
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

    # Bottom rows: fuel gauge, energy gauge (each spans both halves), stint comparison
    row_h = round(unit * 1.05 * spec.row_scale)
    row_w = (content_w - inset * 3) / 2
    bottom_rows = []
    for row in range(spec.bottom_rows):
        row_top = bottom_y + gap + row * (row_h + gap)
        bottom_rows.append((
            QRectF(content_x + inset, row_top, row_w, row_h),
            QRectF(content_x + content_w - inset - row_w, row_top, row_w, row_h),
        ))
    if spec.bottom_rows:
        bottom_y += spec.bottom_rows * (row_h + gap)

    # Incident trace: speed, throttle & brake over recorder duration
    if spec.trace_height_scale > 0:
        trace_h = max(round(unit * spec.trace_height_scale), round(unit))
        rect_trace = QRectF(content_x + inset, bottom_y + gap, content_w - inset * 2, trace_h)
        bottom_y = rect_trace.bottom()
    else:
        rect_trace = QRectF()

    # Event log, one line per event
    event_row_h = round(unit * 0.85 * spec.event_scale)
    event_rows = []
    for line in range(spec.event_lines):
        event_rows.append(QRectF(content_x + inset, bottom_y + gap + line * event_row_h,
                                 content_w - inset * 2, event_row_h))
    if spec.event_lines:
        bottom_y += gap + spec.event_lines * event_row_h

    height = max(bottom_y + (gap if bottom_y > car_bottom else 0), panel_h)
    if spec.show_battery_bar:
        battery_x = main_x if spec.battery_bar_left else content_x + content_w + gap
        rect_battery = QRectF(battery_x, 0, battery_bar_w, height)
    else:
        rect_battery = QRectF()
    if panel_w:
        rect_damage = QRectF(0 if damage_left else width - panel_w, 0 if damage_top else height - panel_h,
                             panel_w, panel_h)
    else:
        rect_damage = QRectF()
    path_bg = background_shape(width, height, damage_extra, panel_h, spec.corner_scale, damage_left, damage_top)
    rect_main = QRectF(main_x, 0, width - damage_extra, height)

    return Layout(
        unit=unit, gap=gap, width=width, height=height,
        brake_bar_w=brake_bar_w, brake_bar_gap=brake_bar_gap, led_h=led_h, row_h=row_h,
        event_row_h=event_row_h, rect_bg=QRectF(0, 0, width, height), rect_main=rect_main, path_bg=path_bg, rect_caption=rect_caption,
        rect_leds=rect_leds, rect_center=rect_center, rect_car_view=rect_car_view,
        rect_battery=rect_battery, rect_trace=rect_trace, rect_damage=rect_damage, path_tyre=path_tyre,
        local_tyre=local_tyre, rects_tyre=rects_tyre, rects_disc=rects_disc, rects_susp=rects_susp,
        susp_extra=susp_extra,
        bottom_rows=bottom_rows, event_rows=event_rows,
    )


def background_shape(width: float, height: float, column_w: float, panel_h: float, corner_scale: float,
                     left: bool = False, top: bool = False, gap: float = 0.0) -> QPainterPath:
    """Main card, plus a separate card for the damage panel beside it

    Two distinct rounded cards with the same background, placed against each other: the damage
    panel touches the widget without being merged into it. Room above or below the panel card
    stays transparent.
    """
    main_w = width - column_w
    main_x = column_w if left else 0
    path = QPainterPath()
    radius = min(main_w, height) * corner_scale
    path.addRoundedRect(QRectF(main_x, 0, main_w, height), radius, radius)
    if column_w and panel_h:
        card_w = column_w - gap
        card = QRectF(0 if left else width - card_w, 0 if top else height - panel_h, card_w, panel_h)
        card_radius = min(card_w, panel_h) * corner_scale
        path.addRoundedRect(card, card_radius, card_radius)
    return path
