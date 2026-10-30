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
Notification center (qml/shell/NotificationCenter.qml): messages of the app with level, time & actions (view log,
create bug report, what's new...), notices shown in the status band; messages marked read once it closes
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import Property, QDate, QLocale, QObject, QPoint, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from ...i18n import current_language
from ..notification import notification_store, run_notification_action
from .models import DictListModel
from .shell_popup import ShellBackend, ShellPopup, popup_size

KIND = "notifications"
# Roles of the messages model ("id" is a QML keyword: entryId)
MESSAGE_ROLES = ("entryId", "text", "severity", "count", "time", "read", "actions")


def time_text(moment) -> str:
    """Time of a message: hour today, else date & hour, in app language"""
    locale = QLocale(current_language())
    if moment.date() == QDate.currentDate():
        return locale.toString(moment.time(), QLocale.FormatType.ShortFormat)
    return locale.toString(moment, QLocale.FormatType.ShortFormat)


class NotificationBackend(ShellBackend):
    """Messages & shown notices for QML, actions run on the main window (popup closed first)

    Messages are a model synced in place (a new message is inserted at the top, a read mark changes one row: the
    history list never rebuilds its delegates); the shown notices (a few) have their own signal.
    """

    entriesChanged = Signal()  # messages (entries, entryCount, unreadCount)
    activeChanged = Signal()  # notices shown in the status band

    def __init__(self, window: QWidget):
        super().__init__()
        self._window = window
        self.model = DictListModel(MESSAGE_ROLES, self)
        self._entries: list[dict] = []
        self._active: list[dict] = []
        self._unread = 0
        store = notification_store()
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        store = notification_store()
        entries = [{
            "id": entry["id"], "text": entry["text"], "severity": entry["severity"], "count": entry["count"],
            "time": time_text(entry["time"]), "read": entry["read"], "actions": entry["actions"],
        } for entry in store.entries()]
        active = [{"text": text, "key": key} for text, key in store.active()]
        unread = store.unread_count()
        if (entries, unread) != (self._entries, self._unread):
            self._entries, self._unread = entries, unread
            self.model.sync([{"entryId": entry["id"], **{name: entry[name] for name in MESSAGE_ROLES[1:]}}
                             for entry in entries], key="entryId")
            self.entriesChanged.emit()
        if active != self._active:
            self._active = active
            self.activeChanged.emit()

    @Property(QObject, constant=True)
    def messages(self) -> QObject:
        """Messages model, newest first (QML list)"""
        return self.model

    @Property(list, notify=entriesChanged)
    def entries(self) -> list[dict]:
        """Messages as dicts (Python callers & tests; the QML list reads the model)"""
        return self._entries

    @Property(int, notify=entriesChanged)
    def entryCount(self) -> int:
        return len(self._entries)

    @Property(list, notify=activeChanged)
    def active(self) -> list[dict]:
        return self._active

    @Property(int, notify=entriesChanged)
    def unreadCount(self) -> int:
        return self._unread

    @Slot(str)
    def runAction(self, key: str):
        """Action of a message or notice: popup closed, then run on the main window"""
        self.closeRequested.emit()
        window = self._window
        QTimer.singleShot(0, window, lambda: run_notification_action(window, key))

    @Slot(int)
    def remove(self, entry_id: int):
        notification_store().remove(entry_id)

    @Slot()
    def clearAll(self):
        notification_store().clear()

    @Slot()
    def close(self):
        self.closeRequested.emit()

    def popup_closed(self):
        """Messages seen: marked read (bell badge cleared)"""
        with contextlib.suppress(RuntimeError, TypeError):  # closed twice: already disconnected
            notification_store().changed.disconnect(self.refresh)
        notification_store().mark_all_read()


class NotificationCenter(ShellPopup):
    """Notification center popup"""

    @classmethod
    def open_at(cls, window: QWidget, anchor: QWidget | None = None) -> NotificationCenter | None:
        """Open next to anchor (bell of the rail), or over the window; clicking the bell again closes it"""
        shown = cls.shown(KIND)
        if shown is not None:
            shown.close()
            return None
        if cls.just_closed(KIND):
            return None
        size = popup_size(window, 26, 30)
        popup = cls(window, KIND, "NotificationCenter.qml", NotificationBackend(window), size)
        if anchor is not None:  # opening upward, right of the bell
            corner = anchor.mapToGlobal(anchor.rect().bottomRight())
            position = QPoint(corner.x() + 4, corner.y() - size.height())
        else:
            frame = window.geometry()
            position = frame.topRight() - popup.rect().topRight()
        popup.popup(position)
        return popup
