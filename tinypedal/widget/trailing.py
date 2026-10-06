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
Trailing Widget
"""

from typing import Any

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QPainter, QPen, QPixmap

from ..api_control import api
from ..module_info import minfo
from ._base import Overlay
from ._painter import fill_pixmap

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


class TrailingMixin:
    """Input sampling & time scale, for classic & modern widget"""

    wcfg: Any
    cfg: Any

    def setup_trailing(self):
        """Shown plots, plot step per update (pixels), update interval of time scale"""
        time_scale = max(self.wcfg["time_scale"], 0.01)
        if time_scale == 1:
            time_factor = self.wcfg["update_interval"] / 20
        else:
            time_factor = 1
            self._update_interval = max(
                self.wcfg["update_interval"] / time_scale,
                self.cfg.application["minimum_update_interval"],
            )
        self.display_scale = max(int(time_factor * self.wcfg["display_scale"]), 1)
        self.max_slip_angle = max(self.wcfg["maximum_slip_angle_difference"], 1) * 2
        self.max_paused_frames = max(self.wcfg["maximum_paused_frames"], 0)
        self.plot_names = tuple(name for name in PLOT_NAMES if self.wcfg[f"show_{name}"])
        self.max_speed = 0.0
        # Last data
        self.last_lap_etime = -1.0
        self.update_plot = 0

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


class Realtime(TrailingMixin, Overlay):
    """Draw widget"""

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

        # Config canvas
        self.resize(self.area_width, self.area_height)
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
        """Update when vehicle on track"""
        if self.plot_paused():
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
        painter.setViewport(self.rect_viewport)
        painter.drawPixmap(0, 0, self.pixmap_background)
        painter.drawPixmap(0, 0, self.pixmap_plot)

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
