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
Trailing Widget
"""

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from ..api_control import api
from ..module_info import minfo
from ._base import Overlay
from ._painter import fill_pixmap
from ._pedal_alert import PedalAlertMixin

if TYPE_CHECKING:
    from ..template.widget_config_types import TrailingConfig

PLOT_NAMES = (
    "tc_activation",
    "abs_activation",
    "throttle",
    "brake",
    "clutch",
    "ffb",
    "steering",
    "speed",
    "wheel_lock",
    "wheel_slip",
    "slip_angle_difference",
)

HIDDEN = -999.0  # plot value of mark not shown (wheel lock, slip, TC & ABS activation)
PEDAL_BARS = ("ffb", "clutch", "brake", "throttle")  # pedal bars, in drawn order


class TrailingMixin(PedalAlertMixin):
    """Input sampling & time scale, pedal bars, for classic & modern widget"""

    wcfg: "TrailingConfig"
    cfg: Any

    def setup_trailing(self):
        """Shown plots, plot step per update (pixels), update interval of time scale"""
        time_scale = max(self.wcfg["time_scale"], 0.01)
        self._update_interval = max(
            round(self.wcfg["update_interval"] / time_scale),
            self.cfg.application["minimum_update_interval"],
            1,
        )
        # Plot speed: display scale pixels per 20 ms at time scale 1, multiplied by time scale, whatever the
        # (minimum) update interval used
        self.display_scale = max(round(self.wcfg["display_scale"] * time_scale * self._update_interval / 20), 1)
        self.max_slip_angle = max(self.wcfg["maximum_slip_angle_difference"], 1) * 2
        self.max_paused_frames = max(self.wcfg["maximum_paused_frames"], 0)
        self.plot_names = tuple(name for name in PLOT_NAMES if self.wcfg[f"show_{name}"])
        # Pedal bars beside newest samples
        self.bar_keys = tuple(
            name for name in PEDAL_BARS if self.wcfg["show_pedal_bars"] and self.wcfg[f"show_{name}_bar"])
        self.setup_alerts(self.bar_keys)
        self.max_brake_pressure = 0.01
        self.max_speed = 0.0
        # Last data
        self.last_lap_etime = -1.0
        self.update_plot = 0

    def post_update(self):
        """Peak brake pressure found again for next car"""
        self.max_brake_pressure = 0.01

    def plot_paused(self) -> bool:
        """Whether plot stops: elapsed time unchanged (game paused) for more than max paused frames"""
        # Use elapsed time to determine whether data paused
        # Add 1 extra update compensation
        lap_etime = api.read.timing.elapsed()
        if self.last_lap_etime != lap_etime:
            self.last_lap_etime = lap_etime
            self.update_plot = self.max_paused_frames
        if self.update_plot >= 0:
            self.update_plot -= 1
            return False
        return True

    def read_inputs(self) -> list[float]:
        """Values of shown plots (plot_names order): 0 to 1, below 0 for marks not shown"""
        wcfg = self.wcfg
        inputs = api.read.inputs
        throttle_raw = inputs.throttle_raw()
        brake_raw = inputs.brake_raw()
        throttle = throttle_raw if wcfg["show_raw_throttle"] else inputs.throttle()
        brake = brake_raw if wcfg["show_raw_brake"] else inputs.brake()
        values = []
        for plot_name in self.plot_names:
            if plot_name == "tc_activation":
                values.append(throttle if api.read.switch.tc_active() else -1.0)
            elif plot_name == "abs_activation":
                values.append(brake if api.read.switch.abs_active() else -1.0)
            elif plot_name == "throttle":
                values.append(throttle)
            elif plot_name == "brake":
                values.append(brake)
            elif plot_name == "clutch":
                values.append(inputs.clutch_raw() if wcfg["show_raw_clutch"] else inputs.clutch())
            elif plot_name == "ffb":
                if wcfg["show_absolute_ffb"]:
                    values.append(abs(inputs.force_feedback()))
                else:
                    values.append((inputs.force_feedback() + 1) / 2)
            elif plot_name == "steering":
                steering = (inputs.steering() + 1) / 2
                values.append(1 - steering if wcfg["show_inverted_steering"] else steering)
            elif plot_name == "speed":
                speed = api.read.vehicle.speed()
                if self.max_speed < speed:
                    self.max_speed = speed
                if speed < 0.1:  # reset if stopped
                    self.max_speed = 0
                elif self.max_speed > 0:
                    speed /= self.max_speed
                else:
                    speed = 0
                values.append(speed)
            elif plot_name == "wheel_lock":
                wheel_lock = min(abs(min(minfo.wheels.slipRatio)), 1)
                if wheel_lock < wcfg["wheel_lock_threshold"] or brake_raw <= 0.02:
                    wheel_lock = HIDDEN
                values.append(wheel_lock)
            elif plot_name == "wheel_slip":
                wheel_slip = min(max(minfo.wheels.slipRatio), 1)
                if wheel_slip < wcfg["wheel_slip_threshold"] or throttle_raw <= 0.02:
                    wheel_slip = HIDDEN
                values.append(wheel_slip)
            elif plot_name == "slip_angle_difference":
                values.append(minfo.wheels.slipAngleDifference / self.max_slip_angle + 0.5)
        return values

    def read_bars(self) -> tuple[tuple[float, float, str], ...]:
        """Pedal bars (bar_keys order): (input as plotted or brake pressure share of peak, raw input,
        alert lit), force feedback absolute"""
        wcfg = self.wcfg
        inputs = api.read.inputs
        values = []
        for name in self.bar_keys:
            if name == "throttle":
                raw = inputs.throttle_raw()
                values.append((raw if wcfg["show_raw_throttle"] else inputs.throttle(), raw))
            elif name == "brake":
                raw = inputs.brake_raw()
                if wcfg["show_pedal_bar_brake_pressure"]:
                    pressure = sum(api.read.brake.pressure())
                    self.max_brake_pressure = max(self.max_brake_pressure, pressure)
                    values.append((pressure / self.max_brake_pressure, raw))
                else:
                    values.append((raw if wcfg["show_raw_brake"] else inputs.brake(), raw))
            elif name == "clutch":
                raw = inputs.clutch_raw()
                values.append((raw if wcfg["show_raw_clutch"] else inputs.clutch(), raw))
            else:
                ffb = abs(inputs.force_feedback())
                values.append((ffb, ffb))
        return tuple((round(filtered, 3), round(raw, 3), alert)
                     for (filtered, raw), alert in zip(values, self.read_alerts()))


class Realtime(TrailingMixin, Overlay):
    """Draw widget"""

    wcfg: "TrailingConfig"

    update_while_hidden = True  # input history keeps recording

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)

        # Config variable
        self.setup_trailing()
        self.margin = max(int(self.wcfg["display_margin"]), 0)
        self.display_height = max(int(self.wcfg["display_height"]), 2)
        self.area_width = max(int(self.wcfg["display_width"]), 2)
        self.area_height = self.display_height + self.margin * 2

        max_line_width = int(max(1, *(self.wcfg[f"{plot_name}_line_width"] for plot_name in PLOT_NAMES)))
        max_samples = 3 + max_line_width  # 3 offset + max line width
        self.samples_offset = max_samples - 2

        # Pedal bars: beside newest samples (right side while trailing inverted), over plot range;
        # maximum indicator beyond full input end, readings beyond empty end (grow widget if margin too small)
        count = len(self.bar_keys)
        self.bar_raw_width = max(int(self.wcfg["pedal_bar_width_unfiltered"]), 1)
        self.bar_width = self.bar_raw_width + max(int(self.wcfg["pedal_bar_width_filtered"]), 1)
        bar_gap = max(int(self.wcfg["pedal_bar_gap"]), 0)
        self.max_height = max(int(self.wcfg["pedal_bar_maximum_indicator_height"]), 0) if count else 0
        max_gap = max(int(self.wcfg["pedal_bar_inner_gap"]), 0) if self.max_height else 0
        self.show_bar_readings = bool(count and self.wcfg["show_pedal_bar_readings"])
        column = self.bar_width
        reading_height = 0
        reading_offset = 0
        if self.show_bar_readings:
            self.bar_font = self.config_font(
                self.wcfg["font_name"], self.wcfg["font_size"], self.wcfg["font_weight"])
            font_m = self.get_font_metrics(self.bar_font)
            column = max(column, font_m.width * 3 + 2)
            reading_height = font_m.height
            reading_offset = font_m.voffset
        full_end = self.max_height + max_gap if self.max_height else 0
        empty_end = reading_height
        from_top = bool(self.wcfg["show_inverted_pedal"])  # full input at bottom
        top_end, bottom_end = (empty_end, full_end) if from_top else (full_end, empty_end)
        self.extra_top = max(top_end - self.margin, 0)
        extra_bottom = max(bottom_end - self.margin, 0)
        height = self.area_height + self.extra_top + extra_bottom
        side = count * column + (count + 1) * bar_gap if count else 0
        newest_right = bool(self.wcfg["show_inverted_trailing"])
        self.chart_offset = 0 if newest_right else side
        self.rect_bars = QRectF(self.area_width if newest_right else 0, 0, side, height)
        track_top = self.extra_top + self.margin
        self.bar_left = tuple(self.rect_bars.left() + bar_gap + index * (column + bar_gap) + (column - self.bar_width) // 2
                              for index in range(count))
        self.bar_tracks = tuple(QRectF(left, track_top, self.bar_width, self.display_height) for left in self.bar_left)
        if from_top:
            max_top = track_top + self.display_height + max_gap
            reading_top = track_top - reading_height
        else:
            max_top = track_top - max_gap - self.max_height
            reading_top = track_top + self.display_height
        self.max_rects = tuple(QRectF(left, max_top, self.bar_width, self.max_height) for left in self.bar_left)
        self.reading_rects = tuple(
            QRectF(left + (self.bar_width - column) / 2, reading_top + reading_offset, column, reading_height)
            for left in self.bar_left)
        # Background strips above & below plot when widget grown
        self.rect_strips = tuple(rect for rect in (
            QRectF(self.chart_offset, 0, self.area_width, self.extra_top),
            QRectF(self.chart_offset, self.extra_top + self.area_height, self.area_width, extra_bottom),
        ) if rect.height() > 0)
        self.bar_colors = tuple(QColor(self.wcfg[f"{name}_color"]) for name in self.bar_keys)
        self.alert_colors = {
            alert: QColor(self.wcfg[f"{alert}_color"])
            for alert in ("tc_activation", "abs_activation", "wheel_lock", "wheel_slip")}
        self.ffb_clipping_color = QColor(self.wcfg["ffb_clipping_color"])
        self.bar_track_color = QColor(0, 0, 0, 90)
        self.bar_background_color = QColor(self.wcfg["background_color"])
        self.bar_reading_color = QColor(self.wcfg["font_color_pedal_bar_readings"])
        self.bar_values: tuple[tuple[float, float, str], ...] = ()

        # Config canvas
        self.resize(self.area_width + side, height)
        self.rect_viewport = self.set_viewport_orientation()

        self.pixmap_background = QPixmap(self.area_width, self.area_height)
        self.pixmap_plot = QPixmap(self.area_width, self.area_height)
        self.pixmap_plot.fill(Qt.GlobalColor.transparent)
        self.pixmap_plot_section = QPixmap(self.display_scale * 3, self.area_height)
        self.pixmap_plot_section.fill(Qt.GlobalColor.transparent)

        for plot_name in self.plot_names:
            setattr(self, f"data_{plot_name}", self.create_data_samples(max_samples))

        self.draw_queue = tuple(d[1:] for d in sorted(self.config_display_order(PLOT_NAMES), reverse=True))
        self.draw_background()

    def timerEvent(self, event):
        """Update when vehicle on track (pedal bars while plot paused too)"""
        bars_changed = False
        if self.bar_keys:
            bar_values = self.read_bars()
            bars_changed = bar_values != self.bar_values
            self.bar_values = bar_values
        if self.plot_paused():
            if bars_changed:
                self.update()
            return
        for plot_name, value in zip(self.plot_names, self.read_inputs()):
            self.update_sample(getattr(self, f"data_{plot_name}"), value)
        # Update after all pedal data set
        self.draw_plot_section()
        self.draw_plot()
        self.update()  # trigger paint event

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        if self.bar_keys:
            self.draw_bars(painter)
        painter.setViewport(self.rect_viewport)
        painter.setWindow(0, 0, self.area_width, self.area_height)
        painter.drawPixmap(0, 0, self.pixmap_background)
        painter.drawPixmap(0, 0, self.pixmap_plot)

    def draw_bars(self, painter: QPainter):
        """Pedal bars over plot range: raw input (narrow part) & input as plotted, as pedal widget;
        flashing alert color, force feedback clipping color, maximum indicator lit at full travel, readings"""
        background = self.bar_background_color
        painter.fillRect(self.rect_bars, background)
        for strip in self.rect_strips:
            painter.fillRect(strip, background)
        height = self.display_height
        from_top = self.wcfg["show_inverted_pedal"]  # full input at bottom
        raw_width = self.bar_raw_width
        if self.show_bar_readings:
            painter.setFont(self.bar_font)
            painter.setPen(self.bar_reading_color)
        values = self.bar_values or ((0.0, 0.0, ""),) * len(self.bar_keys)
        for index, (key, track, color, (filtered, raw, alert)) in enumerate(
                zip(self.bar_keys, self.bar_tracks, self.bar_colors, values)):
            clipping = key == "ffb" and filtered >= 1
            if alert:
                color = self.alert_colors[alert]
            elif clipping:
                color = self.ffb_clipping_color
            painter.fillRect(track, self.bar_track_color)
            left, top = track.left(), track.top()
            for x, width, value in (
                    (left, raw_width, raw), (left + raw_width, self.bar_width - raw_width, filtered)):
                length = height * min(max(value, 0.0), 1.0)
                if length > 0:
                    y = top if from_top else top + height - length
                    painter.fillRect(QRectF(x, y, width, length), color)
            if self.max_height:
                lit = raw >= 1 or clipping
                painter.fillRect(self.max_rects[index], color if lit else self.bar_track_color)
            if self.show_bar_readings:
                painter.drawText(self.reading_rects[index], Qt.AlignmentFlag.AlignCenter, f"{filtered * 100:.0f}")

    def draw_background(self):
        """Draw background"""
        fill_pixmap(self.pixmap_background, self.wcfg["background_color"])
        painter = QPainter(self.pixmap_background)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Draw reference line
        if self.wcfg["show_reference_line"]:
            pen = QPen()
            for idx in range(1, 6):
                self.draw_reference_line(
                    painter, pen,
                    self.wcfg[f"reference_line_{idx}_style"],
                    self.wcfg[f"reference_line_{idx}_offset"],
                    self.wcfg[f"reference_line_{idx}_width"],
                    self.wcfg[f"reference_line_{idx}_color"]
                )

    def draw_reference_line(self, painter, pen, style, offset, width, color):
        """Draw reference line"""
        if width > 0:
            pen.setStyle(Qt.PenStyle.DashLine if style else Qt.PenStyle.SolidLine)
            pen.setWidth(width)
            pen.setColor(color)
            painter.setPen(pen)
            pos_offset = self.display_height * offset + self.margin
            painter.drawLine(0, pos_offset, self.area_width, pos_offset)

    def draw_plot(self):
        """Draw final plot"""
        painter = QPainter(self.pixmap_plot)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        # Draw last plot, +3 sample offset, -2 sample crop
        painter.drawPixmap(
            self.display_scale * 3, 0, self.pixmap_plot,
            self.display_scale * 2, 0, 0 ,0)
        # Draw section plot
        painter.drawPixmap(0, 0, self.pixmap_plot_section)

    def draw_plot_section(self):
        """Draw section plot"""
        self.pixmap_plot_section.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.pixmap_plot_section)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for data, pen, line_style in self.draw_queue:
            painter.setPen(pen)
            if line_style:
                painter.drawPoints(data)
            else:
                painter.drawPolyline(data)

    # Additional methods
    def create_data_samples(self, max_samples):
        """Create data sample list"""
        return tuple(QPointF(index * self.display_scale, 0) for index in range(max_samples))

    def update_sample(self, dataset, value):
        """Update input position samples"""
        # Scale & set new input position
        dataset[0].setY(value * self.display_height + self.margin)
        # Move old input data (Y) 1 display unit to right
        for index in range(self.samples_offset, -1, -1):
            dataset[index + 1].setY(dataset[index].y())

    def set_viewport_orientation(self):
        """Set viewport orientation"""
        if self.wcfg["show_inverted_pedal"]:
            y_pos = 0
            height = self.area_height
        else:
            y_pos = self.area_height
            height = -self.area_height
        if self.wcfg["show_inverted_trailing"]:  # right alignment
            x_pos = self.area_width
            width = -self.area_width
        else:
            x_pos = 0
            width = self.area_width
        x_pos += self.chart_offset  # pedal bars on left side
        y_pos += self.extra_top  # room for bar maximum indicator or readings
        return QRect(x_pos, y_pos, width, height)

    def config_display_order(self, plot_names):
        """Config plot display order"""
        for plot_name in plot_names:
            if not self.wcfg[f"show_{plot_name}"]:
                continue
            pen = QPen()
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setWidth(self.wcfg[f"{plot_name}_line_width"])
            pen.setColor(self.wcfg[f"{plot_name}_color"])
            yield (
                self.wcfg[f"display_order_{plot_name}"],  # index
                getattr(self, f"data_{plot_name}"),  # data
                pen,  # pen style
                self.wcfg[f"{plot_name}_line_style"],  # line style
            )
