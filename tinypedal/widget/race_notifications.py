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
Race notifications Widget

Short messages that fade out after a few seconds: position gained or lost (overall & in class),
new penalty, fastest lap in class, blue flag, full course yellow start & end, lap invalidated.
Nothing drawn while there is no message (unless overlay unlocked).
"""

from __future__ import annotations

from itertools import islice
from time import monotonic
from typing import Any, NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from .. import calculation as calc
from ..api_control import api
from ..const_common import MAX_SECONDS
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ._base import Overlay
from ._race_aids import LEFT, ClassicCells, HiddenPreview, finite, option_colors

# Message kinds (color)
GAIN = 0
LOSS = 1
WARNING = 2
INFO = 3
BEST = 4
KIND_OPTIONS = ("highlight_color_gain", "highlight_color_loss", "highlight_color_warning", "highlight_color_info",
                "highlight_color_best")
SETTLE_TIME = 1.0  # seconds a new position must hold before notified (no back & forth at line)
FADE_TIME = 0.6  # seconds of fade out at end of display
FADE_STEPS = 8  # opacity steps of fade (widget redrawn only on step change)
# Message titles (English, translated when shown), for widget width
TITLES = ("Position", "Class position", "Penalty", "Fastest lap", "Blue flag", "Full course yellow",
          "Green flag", "Lap invalidated")
PREVIEW_TITLE = "Race notifications"


class Message(NamedTuple):
    """Notification"""

    title: str  # English, translated when shown
    detail: str = ""
    kind: int = INFO


class Settled:
    """Value that must hold a while before taken as changed"""

    def __init__(self, delay: float):
        self.delay = delay
        self.value: Any = None
        self.candidate: Any = None
        self.since = 0.0

    def reset(self):
        self.value = None
        self.candidate = None

    def update(self, value: Any, now: float) -> tuple[Any, Any] | None:
        """(old, new) value once a different value held for delay, else None"""
        if self.value is None:
            self.value = value
            return None
        if value == self.value:
            self.candidate = None
            return None
        if value != self.candidate:
            self.candidate = value
            self.since = now
            return None
        if now - self.since < self.delay:
            return None
        old = self.value
        self.value = value
        self.candidate = None
        return old, value


class RaceEvents:
    """Race state changes of player, as messages (first reading of a session never notifies)"""

    def __init__(self, enabled: dict[str, bool]):
        self.enabled = enabled
        self.session: Any = None
        self.position = Settled(SETTLE_TIME)
        self.class_position = Settled(SETTLE_TIME)
        self.penalties = -1
        self.class_best = MAX_SECONDS
        self.blue_flag = True  # rising edge only, no message for flag already shown
        self.yellow_state = -1
        self.invalidated = True

    def reset(self):
        self.position.reset()
        self.class_position.reset()
        self.penalties = -1
        self.class_best = MAX_SECONDS
        self.blue_flag = True
        self.yellow_state = -1
        self.invalidated = True

    def poll(self, now: float) -> list[Message]:
        """New messages since last poll"""
        session = api.read.session.identifier()[0]
        if session != self.session:
            self.session = session
            self.reset()
        in_race = api.read.session.in_race() and not api.read.session.pre_race()
        messages: list[Message] = []
        self.poll_positions(now, in_race, messages)
        penalties = api.read.vehicle.number_penalties()
        if self.enabled["show_penalty"] and penalties > self.penalties >= 0:
            messages.append(Message("Penalty", f"x{penalties}" if penalties > 1 else "", LOSS))
        self.penalties = penalties
        if in_race:
            self.poll_class_best(messages)
        blue = api.read.session.blue_flag()
        if self.enabled["show_blue_flag"] and blue and not self.blue_flag:
            messages.append(Message("Blue flag", minfo.vehicles.nearestBlueClass, INFO))
        self.blue_flag = blue
        yellow = api.read.session.yellow_flag_state()
        if self.enabled["show_full_course_yellow"] and in_race and self.yellow_state >= 0:
            if yellow > 0 >= self.yellow_state:
                messages.append(Message("Full course yellow", "", WARNING))
            elif yellow == 0 < self.yellow_state:
                messages.append(Message("Green flag", "", GAIN))
        self.yellow_state = yellow
        invalidated = api.read.lap.invalidated()
        if self.enabled["show_lap_invalidated"] and invalidated and not self.invalidated:
            messages.append(Message("Lap invalidated", "", WARNING))
        self.invalidated = invalidated
        return messages

    def poll_positions(self, now: float, in_race: bool, messages: list[Message]):
        """Overall & class position changes (race only)"""
        vehicles = minfo.vehicles
        index = vehicles.playerIndex
        if not in_race or not 0 <= index < min(vehicles.totalVehicles, len(vehicles.dataSet)):
            self.position.reset()
            self.class_position.reset()
            return
        player = vehicles.dataSet[index]
        for settled, place, option, title in (
            (self.position, player.positionOverall, "show_position_change", "Position"),
            (self.class_position, player.positionInClass, "show_position_change_in_class", "Class position"),
        ):
            if place <= 0:
                continue
            change = settled.update(place, now)
            if change is not None and self.enabled[option]:
                old, new = change
                if new < old:
                    messages.append(Message(title, f"P{new} ▲{old - new}", GAIN))
                else:
                    messages.append(Message(title, f"P{new} ▼{new - old}", LOSS))

    def poll_class_best(self, messages: list[Message]):
        """New fastest lap in player class"""
        vehicles = minfo.vehicles
        index = vehicles.playerIndex
        cars = vehicles.dataSet
        if not 0 <= index < len(cars):
            return
        player_class = cars[index].vehicleClass
        best = MAX_SECONDS
        best_car = None
        for car in islice(cars, vehicles.totalVehicles):
            laptime = car.bestLapTime
            if car.vehicleClass == player_class and finite(laptime) and 0 < laptime < best:
                best = laptime
                best_car = car
        if best_car is None:
            return
        if best < self.class_best - 0.0005 and self.class_best < MAX_SECONDS and self.enabled["show_class_fastest_lap"]:
            messages.append(Message("Fastest lap", f"{best_car.driverName} {calc.sec2laptime(best)}", BEST))
        self.class_best = best


class Toast(NamedTuple):
    """Shown message"""

    message: Message
    start: float


class NotificationsMixin:
    """Message queue & fading, for classic & modern widget"""

    wcfg: Any

    def setup_notifications(self):
        """Options, queue"""
        wcfg = self.wcfg
        self.duration = min(max(float(wcfg["display_duration"]), 1.0), 60.0)
        self.max_toasts = min(max(int(wcfg["number_of_notifications"]), 1), 8)
        self.newest_first = wcfg["layout"] == 0
        self.events = RaceEvents({
            key: bool(wcfg[key]) for key in (
                "show_position_change", "show_position_change_in_class", "show_penalty", "show_class_fastest_lap",
                "show_blue_flag", "show_full_course_yellow", "show_lap_invalidated",
            )
        })
        self.toasts: list[Toast] = []
        self.clock = monotonic

    def add_messages(self, messages: list[Message], now: float):
        """Queue new messages, same message shown again only once shown one expires"""
        for message in messages:
            if any(toast.message == message for toast in self.toasts):
                continue
            self.toasts.append(Toast(message, now))
        del self.toasts[:-self.max_toasts]  # oldest dropped first

    def read_notifications(self) -> tuple:
        """Shown messages, newest first: ((message, opacity step), ...)"""
        now = self.clock()
        self.add_messages(self.events.poll(now), now)
        self.toasts = [toast for toast in self.toasts if now - toast.start < self.duration]
        shown = []
        for toast in reversed(self.toasts):
            left = self.duration - (now - toast.start)
            step = FADE_STEPS if left >= FADE_TIME else max(round(left / FADE_TIME * FADE_STEPS), 1)
            shown.append((toast.message, step))
        return tuple(shown)

    def slot_order(self, shown: tuple) -> tuple:
        """Messages in slot order (top to bottom)"""
        if self.newest_first:
            return shown
        return tuple(reversed(shown))

    def first_slot(self, count: int) -> int:
        """Slot of first message: newest at top fills from top, newest at bottom from bottom"""
        if self.newest_first:
            return 0
        return max(self.max_toasts - count, 0)


class Realtime(HiddenPreview, NotificationsMixin, ClassicCells, Overlay):
    """Draw widget"""

    update_while_hidden = True  # race state followed while hidden (no stale message when shown)

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()
        self.setup_notifications()

        # Config variable
        wcfg = self.wcfg
        gap = 2
        self.toast_h = round(font_m.height * 1.4)
        self.stripe = max(round(font_m.width * 0.5), 3)
        title_chars = max(len(tr(title)) for title in (*TITLES, PREVIEW_TITLE))
        self.title_w = self.text_cell_width(title_chars)
        self.detail_w = self.text_cell_width(20)
        width = self.stripe + self.title_w + self.detail_w
        self.rects = tuple(
            QRectF(0, (self.toast_h + gap) * index, width, self.toast_h) for index in range(self.max_toasts)
        )
        self.colors = option_colors(wcfg, "font_color_notification", "background_color_notification", *KIND_OPTIONS)
        self.kind_colors = tuple(self.colors[key] for key in KIND_OPTIONS)
        self.preview = ((Message(PREVIEW_TITLE), FADE_STEPS),)

        # Config canvas
        self.resize(round(width), (self.toast_h + gap) * self.max_toasts - gap)
        self.state: tuple = ()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_notifications()
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        shown = self.state or (self.preview if self.previewing() else ())
        if not shown:
            return
        painter = QPainter(self)
        colors = self.colors
        metrics = self.fontMetrics()
        rects = self.rects[self.first_slot(len(shown)):]
        for rect, (message, step) in zip(rects, self.slot_order(shown)):
            painter.setOpacity(step / FADE_STEPS)
            painter.fillRect(rect, colors["background_color_notification"])
            painter.fillRect(QRectF(rect.left(), rect.top(), self.stripe, rect.height()), self.kind_colors[message.kind])
            title = QRectF(rect.left() + self.stripe, rect.top(), self.title_w, rect.height())
            self.draw_cell(painter, title, tr(message.title), self.kind_colors[message.kind], None, LEFT)
            if message.detail:
                detail = QRectF(title.right(), rect.top(), self.detail_w, rect.height())
                text = metrics.elidedText(message.detail, Qt.TextElideMode.ElideRight,
                                          round(self.detail_w - self.cell_padding() * 2))
                self.draw_cell(painter, detail, text, colors["font_color_notification"], None, LEFT)
        painter.setOpacity(1.0)
