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
Stream overlays page (ui/qml/StreamOverlays.qml): stream overlay server switch & settings, addresses of browser
sources (layout, race results with its options, each overlay) to copy into OBS Studio, Streamlabs, XSplit, vMix...,
and where each overlay is shown (screen & stream, stream only, screen only)

Sources watched now are shown live (asked again every second while page is shown).
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication

from ... import app_signal
from ...const_file import ConfigType
from ...i18n import tr
from ...i18n.options import module_label
from ...setting import cfg
from ...stream_overlay import LAYOUT, STREAM_VISIBILITY, canvas_screen, stream_visibility, streamoverlay
from ...template.setting_widget import WIDGET_FILENAME
from ...userfile import atomic_write
from .models import DictListModel

SETTINGS_FILE = "stream_overlays.json"  # page settings (race results source options), user config folder
REFRESH_MS = 1000
FRAME_RATES = (15, 30, 60)
RESULTS_CLASSES = ("all", "cycle")
RESULTS_SESSIONS = ("race", "qualifying", "any")
RESULTS_ROWS = (10, 15, 20, 25)
RESULTS_CYCLES = (6, 10, 15, 20)
OVERLAY_ROLES = ("key", "label", "visibility", "sizeText", "live", "shown")
TIMES = chr(0xD7)  # multiplication sign


def settings_path() -> str:
    return os.path.join(cfg.path.config, SETTINGS_FILE)


def load_page_settings() -> dict[str, Any]:
    try:
        with open(settings_path(), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_page_settings(data: dict[str, Any]):
    with atomic_write(settings_path()) as file:
        json.dump(data, file, indent=1, ensure_ascii=False)


def overlay_windows() -> dict[str, Any]:
    """Overlay windows by widget name"""
    windows = {}
    for widget in QApplication.topLevelWidgets():
        name = getattr(widget, "widget_name", None)
        if isinstance(name, str) and getattr(widget, "wcfg", None) is not None:
            windows[name] = widget
    return windows


def size_text(width: int, height: int) -> str:
    return f"{width} {TIMES} {height}" if width > 0 and height > 0 else ""


def window_size_text(widget) -> str:
    """Overlay size in screen pixels (browser source size)"""
    if widget is None:
        return ""
    screen = widget.screen()
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    return size_text(round(widget.width() * ratio), round(widget.height() * ratio))


def overlay_rows(watched: set[str]) -> list[dict[str, Any]]:
    """Enabled overlays: label, where shown, size, watched now"""
    windows = overlay_windows()
    rows = []
    for name in WIDGET_FILENAME:
        wcfg = cfg.user.setting.get(name)
        if not isinstance(wcfg, dict) or not wcfg.get("enable"):
            continue
        widget = windows.get(name)
        visibility = stream_visibility(wcfg)
        rows.append({
            "key": name,
            "label": module_label(name),
            "visibility": STREAM_VISIBILITY.index(visibility),
            "sizeText": window_size_text(widget),
            "live": name in watched and visibility != "Screen Only",
            "shown": widget is not None and widget.isVisible(),
        })
    rows.sort(key=lambda row: str(row["label"]).casefold())
    return rows


def choice(value: Any, choices: tuple, default: Any) -> Any:
    return value if value in choices else default


class StreamOverlaysBackend(QObject):
    """Stream overlays page state & actions"""

    serverChanged = Signal()  # switch, settings, addresses, status
    overlaysChanged = Signal()
    resultsChanged = Signal()  # race results source options
    noticeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        settings = load_page_settings()
        self.results_class = choice(settings.get("results_class"), RESULTS_CLASSES, "all")
        self.results_session = choice(settings.get("results_session"), RESULTS_SESSIONS, "race")
        self.results_rows = choice(settings.get("results_rows"), RESULTS_ROWS, 15)
        self.results_cycle = choice(settings.get("results_cycle"), RESULTS_CYCLES, 10)
        self.notice = ""
        self.notice_count = 0
        self.watched: set[str] = set()
        self._model = DictListModel(OVERLAY_ROLES, self)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        app_signal.refresh.connect(self.refresh_overlays)

    # Page
    def page_shown(self):
        self.refresh()
        self._timer.start()

    def page_hidden(self):
        self._timer.stop()

    def release(self):
        self.page_hidden()
        with suppress(RuntimeError, TypeError):  # already disconnected
            app_signal.refresh.disconnect(self.refresh_overlays)

    def save_settings(self):
        save_page_settings({
            "results_class": self.results_class, "results_session": self.results_session,
            "results_rows": self.results_rows, "results_cycle": self.results_cycle,
        })

    @Slot()
    def refresh(self):
        """Live sources & sizes (every second while shown)"""
        self.watched = streamoverlay.watched()
        self.refresh_overlays()
        self.serverChanged.emit()

    def refresh_overlays(self, *_args):
        self._model.sync(overlay_rows(self.watched))
        self.overlaysChanged.emit()

    def notify(self, text: str):
        self.notice = text
        self.notice_count += 1
        self.noticeChanged.emit()

    # Server
    @staticmethod
    def setting() -> dict:
        return cfg.user.config["stream_overlay"]

    def apply_setting(self, key: str, value: Any):
        """Change server setting, saved, server started again with it"""
        setting = self.setting()
        if setting.get(key) == value:
            return
        setting[key] = value
        cfg.save(config_type=ConfigType.CONFIG)
        streamoverlay.enable()
        self.refresh()

    @Property(bool, notify=serverChanged)
    def enabled(self) -> bool:
        return bool(self.setting()["enable_stream_overlay"])

    @Property(bool, notify=serverChanged)
    def running(self) -> bool:
        return streamoverlay.running

    @Property(int, notify=serverChanged)
    def watchingCount(self) -> int:
        """Sources shown now (layout & overlays)"""
        return len(self.watched)

    @Property(bool, notify=serverChanged)
    def lanAccess(self) -> bool:
        return bool(self.setting()["enable_lan_access"])

    @Property(int, notify=serverChanged)
    def port(self) -> int:
        return streamoverlay.port()

    @Property(int, notify=serverChanged)
    def frameRateIndex(self) -> int:
        rate = int(self.setting()["frame_rate"])
        return min(range(len(FRAME_RATES)), key=lambda index: abs(FRAME_RATES[index] - rate))

    @Property(str, notify=serverChanged)
    def statusText(self) -> str:
        if not self.enabled:
            return tr("Server off")
        if not self.running:
            return tr("Port %1 unavailable").replace("%1", str(self.port))
        if self.watched:
            return tr("On air: %1 sources shown").replace("%1", str(len(self.watched)))
        return tr("Ready")

    @Property(str, notify=serverChanged)
    def lanText(self) -> str:
        """Addresses for another computer (LAN access)"""
        return "  ".join(streamoverlay.base_urls()[1:]) if self.lanAccess else ""

    @Slot(bool)
    def setEnabled(self, enabled: bool):
        self.apply_setting("enable_stream_overlay", enabled)
        if enabled and not streamoverlay.running:
            self.notify(tr("Port %1 unavailable").replace("%1", str(self.port)))

    @Slot(bool)
    def setLanAccess(self, enabled: bool):
        self.apply_setting("enable_lan_access", enabled)

    @Slot(int)
    def setPort(self, port: int):
        if 1024 <= port <= 65535:
            self.apply_setting("stream_overlay_port", port)

    @Slot(int)
    def setFrameRate(self, index: int):
        if 0 <= index < len(FRAME_RATES):
            self.apply_setting("frame_rate", FRAME_RATES[index])

    @Slot()
    def newToken(self):
        """New access token: addresses copied before stop working"""
        streamoverlay.new_access_token()
        self.refresh()
        self.notify(tr("New access token: copy the addresses again into your streaming software."))

    # Addresses
    @Property(str, notify=serverChanged)
    def layoutUrl(self) -> str:
        return streamoverlay.url(f"/{LAYOUT}")

    @Property(str, notify=serverChanged)
    def indexUrl(self) -> str:
        return streamoverlay.url("/")

    @Property(str, notify=serverChanged)
    def screenText(self) -> str:
        """Layout canvas size: screen holding most overlays"""
        screen = canvas_screen(list(overlay_windows().values()))
        if screen is None:
            return ""
        ratio = screen.devicePixelRatio()
        return size_text(round(screen.geometry().width() * ratio), round(screen.geometry().height() * ratio))

    @Property(bool, notify=serverChanged)
    def layoutLive(self) -> bool:
        return LAYOUT in self.watched

    @Property(str, notify=resultsChanged)
    def resultsUrl(self) -> str:
        query = f"class={self.results_class}&rows={self.results_rows}&cycle={self.results_cycle}"
        if self.results_session != "race":
            query += f"&session={self.results_session}"
        return streamoverlay.url("/results", query)

    @Slot(str, result=str)
    def overlayUrl(self, name: str) -> str:
        return streamoverlay.url(f"/overlay/{name}")

    @Slot(str)
    def copy(self, text: str):
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None and text:
            clipboard.setText(text)
            self.notify(tr("Address copied: paste it as URL of a Browser source."))

    @Slot(str)
    def openInBrowser(self, url: str):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # Race results source options
    @Property(int, notify=resultsChanged)
    def resultsClassIndex(self) -> int:
        return RESULTS_CLASSES.index(self.results_class)

    @Property(int, notify=resultsChanged)
    def resultsSessionIndex(self) -> int:
        return RESULTS_SESSIONS.index(self.results_session)

    @Property(int, notify=resultsChanged)
    def resultsRowsIndex(self) -> int:
        return RESULTS_ROWS.index(self.results_rows)

    @Property(int, notify=resultsChanged)
    def resultsCycleIndex(self) -> int:
        return RESULTS_CYCLES.index(self.results_cycle)

    @Property(list, constant=True)
    def resultsRowsChoices(self) -> list:
        return [str(rows) for rows in RESULTS_ROWS]

    @Property(list, constant=True)
    def resultsCycleChoices(self) -> list:
        return [f"{seconds} s" for seconds in RESULTS_CYCLES]

    def set_results(self, name: str, value: Any):
        if getattr(self, name) != value:
            setattr(self, name, value)
            self.save_settings()
            self.resultsChanged.emit()

    @Slot(int)
    def setResultsClass(self, index: int):
        if 0 <= index < len(RESULTS_CLASSES):
            self.set_results("results_class", RESULTS_CLASSES[index])

    @Slot(int)
    def setResultsSession(self, index: int):
        if 0 <= index < len(RESULTS_SESSIONS):
            self.set_results("results_session", RESULTS_SESSIONS[index])

    @Slot(int)
    def setResultsRows(self, index: int):
        if 0 <= index < len(RESULTS_ROWS):
            self.set_results("results_rows", RESULTS_ROWS[index])

    @Slot(int)
    def setResultsCycle(self, index: int):
        if 0 <= index < len(RESULTS_CYCLES):
            self.set_results("results_cycle", RESULTS_CYCLES[index])

    # Overlays
    @Property(QObject, constant=True)
    def overlayModel(self) -> QObject:
        return self._model

    @Property(int, notify=overlaysChanged)
    def overlayCount(self) -> int:
        return len(self._model.rows)

    @Slot(str, int)
    def setVisibility(self, name: str, index: int):
        """Where overlay is shown (saved to preset), overlay started again with it"""
        wcfg = cfg.user.setting.get(name)
        if not isinstance(wcfg, dict) or not 0 <= index < len(STREAM_VISIBILITY):
            return
        if wcfg.get("stream_visibility") == STREAM_VISIBILITY[index]:
            return
        wcfg["stream_visibility"] = STREAM_VISIBILITY[index]
        cfg.save()
        if wcfg.get("enable"):
            from ...widget._base import reload_widget

            reload_widget(name)  # refreshes rows (app refresh signal)
        else:
            self.refresh_overlays()

    @Property(str, notify=noticeChanged)
    def noticeText(self) -> str:
        return self.notice

    @Property(int, notify=noticeChanged)
    def noticeCount(self) -> int:
        return self.notice_count
