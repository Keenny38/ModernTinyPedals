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
Stream overlays page (ui/qml/StreamOverlays.qml): stream overlay server switch & settings, addresses of browser
sources (layout, race results with its options, each overlay) to copy into OBS Studio, Streamlabs, XSplit, vMix...,
and where each overlay is shown (screen & stream, stream only, screen only)

Sources watched now are shown live (asked again every second while page is shown).
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication

from ... import app_signal, realtime_state, safe_mode
from ...const_file import ConfigType
from ...i18n import tr
from ...i18n.options import module_label
from ...setting import cfg
from ...stream_overlay import (
    LAYOUT,
    STREAM_VISIBILITY,
    canvas_screen,
    layout_section,
    stream_layout,
    stream_visibility,
    streamoverlay,
)
from ...template.setting_widget import WIDGET_FILENAME
from . import page_settings
from .models import DictListModel
from .page_backend import PageBackend

SETTINGS_FILE = "stream_overlays.json"  # page settings (race results source options), user config folder
REFRESH_MS = 1000
FRAME_RATES = (15, 30, 60)
RESULTS_CLASSES = ("all", "cycle")
RESULTS_SESSIONS = ("race", "qualifying", "any")
RESULTS_ROWS = (10, 15, 20, 25)
RESULTS_CYCLES = (6, 10, 15, 20)
LAYOUT_FORMATS = ("16:9", "screen")  # layout canvas: centre of screen in 16:9 (1920 x 1080 source), or whole screen
OVERLAY_ROLES = ("key", "label", "visibility", "sizeText", "live", "shown")
TIMES = chr(0xD7)  # multiplication sign


def load_page_settings() -> dict[str, Any]:
    """Page settings (changes of an open page written first)"""
    return page_settings.load_settings(SETTINGS_FILE)


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


def crop_size(width: int, height: int, aspect: tuple[int, int]) -> tuple[int, int]:
    """Size of centre part of a screen in aspect ratio (whole screen if same ratio), same as layout page"""
    if width <= 0 or height <= 0:
        return width, height
    ratio = aspect[0] / aspect[1]
    if width / height > ratio:
        return round(height * ratio), height
    return width, round(width / ratio)


def hidden_reason(rows: list[dict[str, Any]], spectating: bool) -> str:
    """Why no overlay is shown on stream now, empty if one is (or none enabled for stream)"""
    streamed = [row for row in rows if row["visibility"] != 2]
    if not streamed or any(row["shown"] for row in streamed):
        return ""
    if realtime_state.hidden and not realtime_state.shown:
        if spectating:
            return tr("No overlay shown now: Auto Hide hides them outside sessions. They show while you drive, "
                      "and while you spectate or watch a replay with a source on air.")
        return tr("No overlay shown now: Auto Hide hides them while you are not driving. Turn on "
                  "\"Show overlays while spectating\" to stream a session you watch.")
    return tr("No overlay shown now: hidden by their visibility options or a hotkey.")


class StreamOverlaysBackend(PageBackend):
    """Stream overlays page state & actions"""

    serverChanged = Signal()  # switch, settings, addresses, status
    overlaysChanged = Signal()
    resultsChanged = Signal()  # race results source options
    noticeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, "Stream overlays")
        settings = load_page_settings()
        self.page_file = page_settings.PageSettings(SETTINGS_FILE, page_settings.SAVE_DELAY_MS, self)
        self.results_class = choice(settings.get("results_class"), RESULTS_CLASSES, "all")
        self.results_session = choice(settings.get("results_session"), RESULTS_SESSIONS, "race")
        self.results_rows = choice(settings.get("results_rows"), RESULTS_ROWS, 15)
        self.results_cycle = choice(settings.get("results_cycle"), RESULTS_CYCLES, 10)
        self.layout_format = choice(settings.get("layout_format"), LAYOUT_FORMATS, LAYOUT_FORMATS[0])
        self.notice = ""
        self.notice_count = 0
        self.watched: set[str] = set()
        self._server_state: tuple = ()
        self._model = DictListModel(OVERLAY_ROLES, self)
        self._timer = self.page_timer(self.refresh, REFRESH_MS)
        app_signal.refresh.connect(self.refresh_overlays)

    # Page
    def page_shown(self):
        self.refresh(force=True)
        self._timer.start()

    def page_hidden(self):
        self._timer.stop()

    def release_resources(self):
        self.page_hidden()
        self.page_file.flush()
        with suppress(RuntimeError, TypeError):  # already disconnected
            app_signal.refresh.disconnect(self.refresh_overlays)

    def save_settings(self):
        """Settings written once changes pause"""
        self.page_file.save(self.page_settings())

    def page_settings(self) -> dict[str, Any]:
        return {
            "results_class": self.results_class, "results_session": self.results_session,
            "results_rows": self.results_rows, "results_cycle": self.results_cycle,
            "layout_format": self.layout_format,
        }

    @Slot()
    def refresh(self, force: bool = False):
        """Live sources & sizes (every second while shown), server state signaled only when changed"""
        self.watched = streamoverlay.watched()
        self.refresh_overlays()
        state = self.server_state()
        if force or state != self._server_state:
            self._server_state = state
            self.serverChanged.emit()

    def server_state(self) -> tuple:
        """Everything server properties depend on"""
        setting = self.setting()
        return (
            bool(setting["enable_stream_overlay"]), streamoverlay.running, frozenset(self.watched),
            bool(setting["enable_lan_access"]), streamoverlay.port(), setting["frame_rate"],
            streamoverlay.access_token(), self.lanText, self.screenText, self.layoutSizeText,
            self.spectating, self.hiddenText, stream_layout.version,
        )

    def refresh_overlays(self, *_args):
        """Overlay rows synced in place (every second while shown), page told only when something changed"""
        if self._model.sync(overlay_rows(self.watched)):
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
        self.refresh(force=True)

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

    @Property(bool, notify=serverChanged)
    def spectating(self) -> bool:
        """Overlays shown & updated while spectating or watching a replay, a source on air"""
        return bool(self.setting().get("show_overlays_while_spectating", True))

    @Property(str, notify=serverChanged)
    def hiddenText(self) -> str:
        """Why sources are empty now (no overlay shown), empty if not"""
        if not self.running:
            return ""
        return hidden_reason(self._model.rows, bool(self.setting().get("show_overlays_while_spectating", True)))

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
            if safe_mode.state.enabled and not streamoverlay.port_unavailable:  # never started in safe mode
                return tr("Off in safe mode")
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

    @Slot(bool)
    def setSpectating(self, enabled: bool):
        self.apply_setting("show_overlays_while_spectating", enabled)

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
        self.refresh(force=True)
        self.notify(tr("New access token: copy the addresses again into your streaming software."))

    # Addresses
    @Property(str, notify=serverChanged)
    def layoutUrl(self) -> str:
        return streamoverlay.url(f"/{LAYOUT}", "crop=16:9" if self.layout_format == "16:9" else "")

    @Property(str, notify=serverChanged)
    def indexUrl(self) -> str:
        return streamoverlay.url("/")

    @staticmethod
    def screen_size() -> tuple[int, int]:
        """Screen of layout canvas (holding most overlays), screen pixels"""
        screen = canvas_screen(list(overlay_windows().values()))
        if screen is None:
            return 0, 0
        ratio = screen.devicePixelRatio()
        return round(screen.geometry().width() * ratio), round(screen.geometry().height() * ratio)

    @Property(str, notify=serverChanged)
    def screenText(self) -> str:
        """Layout canvas size: screen holding most overlays"""
        return size_text(*self.screen_size())

    @Property(str, notify=serverChanged)
    def layoutSizeText(self) -> str:
        """Layout source detail: browser source size & part of screen shown"""
        width, height = self.screen_size()
        if self.layout_format == "screen":
            return tr("Browser source size") + ": " + size_text(width, height)
        text = tr("Browser source size") + ": " + size_text(1920, 1080)
        crop = crop_size(width, height, (16, 9))
        if crop != (width, height) and width > 0:
            text += "  (" + tr("centre %1 of the screen %2").replace("%1", size_text(*crop)).replace(
                "%2", size_text(width, height)) + ")"
        return text

    @Property(bool, notify=serverChanged)
    def layoutPlaced(self) -> bool:
        """Overlays placed by the layout editor on this layout format"""
        return bool(stream_layout.get(layout_section(self.crop())))

    def crop(self) -> str:
        return "16:9" if self.layout_format == "16:9" else ""

    @Slot()
    def editLayout(self):
        """Layout editor in the browser (overlays shown now dragged to their place on the layout)"""
        query = f"crop={self.crop()}&edit=1" if self.crop() else "edit=1"
        self.openInBrowser(streamoverlay.url(f"/{LAYOUT}", query))

    @Slot()
    def resetLayout(self):
        stream_layout.set(layout_section(self.crop()), {})
        streamoverlay.store.bump()
        self.refresh(force=True)
        self.notify(tr("Overlays back to their place on screen"))

    @Property(int, notify=serverChanged)
    def layoutFormatIndex(self) -> int:
        return LAYOUT_FORMATS.index(self.layout_format)

    @Slot(int)
    def setLayoutFormat(self, index: int):
        if 0 <= index < len(LAYOUT_FORMATS) and LAYOUT_FORMATS[index] != self.layout_format:
            self.layout_format = LAYOUT_FORMATS[index]
            self.save_settings()
            self.refresh(force=True)

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
