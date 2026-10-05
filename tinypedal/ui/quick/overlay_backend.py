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
Overlays page backend (qml/Overlays.qml): overlay list model, filters, previews & actions

Rows are filtered by a proxy model (search words, All / Active / Inactive, category), so the QML
grid animates rows in & out instead of being rebuilt. Previews are rendered one per event loop
tick, only for rows the page shows and only while the page is visible (never during a race with
the window hidden), then kept as PNG data URLs: a refresh re-renders them in the background and
the old picture stays shown until the new one is ready (unchanged picture: page not told).
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QBuffer,
    QByteArray,
    QIODevice,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage

from ... import app_signal
from ...const_file import ConfigType
from ...i18n import tr, trm
from ...i18n.options import module_label
from ...module_control import ModuleControl
from ...setting import cfg
from ..module_view import sort_key

logger = logging.getLogger(__name__)

ROOT = QModelIndex()  # list rows have no parent
PREVIEW_MAX = QSize(520, 360)  # bigger overlays (standings...) scaled down: card & tooltip sizes
FILTER_ALL = 0
FILTER_ACTIVE = 1
FILTER_INACTIVE = 2
PREVIEW_LOADING = 0
PREVIEW_READY = 1
PREVIEW_UNAVAILABLE = 2

# Widget categories: (name, widget name prefixes), first match wins, unmatched (plugins) are "Other"
WIDGET_CATEGORIES = (
    ("Timing", (
        "deltabest", "lap_time_history", "laps_and_position", "pit_stop_estimate", "race_plan", "relative", "rivals",
        "sectors", "session", "standings", "stint_history", "timing", "track_clock",
        "delta_graph", "gap_trend", "stint_timer",
    )),
    ("Tyres & Wheels", ("friction_circle", "slip_", "tyre_", "wheel_")),
    ("Brakes", ("brake_",)),
    ("Driver Inputs", ("onboard_setting", "pedal", "steering_", "trailing")),
    ("Engine & Energy", (
        "battery", "cruise", "drs", "electric_motor", "engine", "fuel", "gear", "instrument", "lift_and_coast",
        "push_to_pass", "rpm_led", "speedometer", "virtual_energy",
    )),
    ("Chassis", (
        "acceleration", "damage", "differential", "force", "rake_angle", "ride_height", "roll_angle",
        "suspension_", "weight_distribution",
    )),
    ("Track & Traffic", (
        "black_box", "chat", "elevation", "flag", "heading", "navigation", "pace_notes", "radar", "track_", "traffic",
        "weather",
        "pit_lane_helper", "race_notifications", "spotter",
    )),
)
CATEGORY_ALL = ""  # category filter off
CATEGORY_OTHER = "Other"
# Category color, readable on light & dark theme
CATEGORY_COLORS = {
    "Timing": "#4C8DFF",
    "Tyres & Wheels": "#A371F7",
    "Brakes": "#E5534B",
    "Driver Inputs": "#3FB950",
    "Engine & Energy": "#F0883E",
    "Chassis": "#22B8C8",
    "Track & Traffic": "#D4A72C",
    CATEGORY_OTHER: "#8B949E",
}
CATEGORY_ORDER = (*(category for category, _ in WIDGET_CATEGORIES), CATEGORY_OTHER)


def widget_category(name: str) -> str:
    """Category of widget, by name prefix"""
    for category, prefixes in WIDGET_CATEGORIES:
        if name.startswith(prefixes):
            return category
    return CATEGORY_OTHER


def search_words(text: str) -> tuple[str, ...]:
    """Search text words, case & accent folded: every word must match (any order)"""
    return tuple(sort_key(text).split())


class OverlayRow:
    """Overlay of list: name, texts & state"""

    __slots__ = ("name", "label", "category", "search", "enabled", "failed")

    def __init__(self, name: str, enabled: bool, failed: bool):
        self.name = name
        self.label = module_label(name)
        self.category = widget_category(name)
        # Matched by label, widget name (english words) & category, in any language
        self.search = sort_key(f"{self.label} {name.replace('_', ' ')} {tr(self.category)}")
        self.enabled = enabled
        self.failed = failed

    def matches(self, words: tuple[str, ...]) -> bool:
        return all(word in self.search for word in words)


class Preview(NamedTuple):
    """Rendered overlay picture: PNG data URL ("" if not available) & logical size"""

    url: str
    width: int
    height: int


class OverlayModel(QAbstractListModel):
    """Every overlay, sorted by label"""

    NameRole = Qt.ItemDataRole.UserRole + 1
    LabelRole = Qt.ItemDataRole.UserRole + 2
    CategoryRole = Qt.ItemDataRole.UserRole + 3
    CategoryLabelRole = Qt.ItemDataRole.UserRole + 4
    ColorRole = Qt.ItemDataRole.UserRole + 5
    EnabledRole = Qt.ItemDataRole.UserRole + 6
    FailedRole = Qt.ItemDataRole.UserRole + 7
    PreviewRole = Qt.ItemDataRole.UserRole + 8
    PreviewStateRole = Qt.ItemDataRole.UserRole + 9
    PreviewWidthRole = Qt.ItemDataRole.UserRole + 10
    PreviewHeightRole = Qt.ItemDataRole.UserRole + 11
    ROLE_NAMES = {
        NameRole: b"name",
        LabelRole: b"label",
        CategoryRole: b"category",
        CategoryLabelRole: b"categoryLabel",
        ColorRole: b"categoryColor",
        EnabledRole: b"active",  # "enabled" would disable QML delegate item
        FailedRole: b"failed",
        PreviewRole: b"preview",
        PreviewStateRole: b"previewState",
        PreviewWidthRole: b"previewWidth",
        PreviewHeightRole: b"previewHeight",
    }
    PREVIEW_ROLES = [PreviewRole, PreviewStateRole, PreviewWidthRole, PreviewHeightRole]

    def __init__(self, parent, previews: PreviewCache):
        super().__init__(parent)
        self.rows: list[OverlayRow] = []
        self.index_of: dict[str, int] = {}
        self.previews = previews

    def set_rows(self, rows: list[OverlayRow]):
        self.beginResetModel()
        self.rows = sorted(rows, key=lambda row: sort_key(row.label))
        self.index_of = {row.name: index for index, row in enumerate(self.rows)}
        self.endResetModel()

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name) for role, name in self.ROLE_NAMES.items()}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = ROOT) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role in (self.LabelRole, Qt.ItemDataRole.DisplayRole):
            return row.label
        if role == self.NameRole:
            return row.name
        if role == self.EnabledRole:
            return row.enabled
        if role == self.FailedRole:
            return row.failed
        if role == self.CategoryRole:
            return row.category
        if role == self.CategoryLabelRole:
            return tr(row.category)
        if role == self.ColorRole:
            return CATEGORY_COLORS[row.category]
        if role in self.PREVIEW_ROLES:
            return self.previews.role(row.name, role)
        return None

    def row_changed(self, name: str, roles: list[int]):
        row = self.index_of.get(name)
        if row is not None:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, roles)


class OverlayFilter(QSortFilterProxyModel):
    """Rows shown: matching search words, state & category filter"""

    def __init__(self, parent, model: OverlayModel):
        super().__init__(parent)
        self.words: tuple[str, ...] = ()
        self.state = FILTER_ALL
        self.category = CATEGORY_ALL
        self.setSourceModel(model)

    def source_rows(self) -> list[OverlayRow]:
        return self.sourceModel().rows  # type: ignore[attr-defined]

    def accepts(self, row: OverlayRow, use_state: bool = True, use_category: bool = True) -> bool:
        """Row passes filters (state or category filter left out to count rows of each choice)"""
        return (
            row.matches(self.words)
            and (not use_state or self.state == FILTER_ALL or (self.state == FILTER_ACTIVE) == row.enabled)
            and (not use_category or self.category in (CATEGORY_ALL, row.category))
        )

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        rows = self.source_rows()
        return 0 <= source_row < len(rows) and self.accepts(rows[source_row])

    def shown_names(self) -> list[str]:
        return [row.name for row in self.source_rows() if self.accepts(row)]


class PreviewCache:
    """Overlay pictures, rendered in background one per event loop tick while active"""

    def __init__(self, render: Callable[[str], QImage | None], on_ready: Callable[[str], None], parent=None):
        self._render = render
        self._on_ready = on_ready
        self._previews: dict[str, Preview] = {}
        self._stale: set[str] = set()
        self._queue: deque[str] = deque()
        self._queued: set[str] = set()
        self.active = False  # page visible: queue rendered
        self._timer = QTimer(parent)  # deleted with backend: never fires on a deleted model
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_next)

    def role(self, name: str, role: int):
        """Preview role value of overlay, render queued if missing or out of date"""
        preview = self._previews.get(name)
        if preview is None or name in self._stale:
            self.request(name)
        if role == OverlayModel.PreviewStateRole:
            if preview is None:
                return PREVIEW_LOADING
            return PREVIEW_READY if preview.url else PREVIEW_UNAVAILABLE
        if role == OverlayModel.PreviewRole:
            return "" if preview is None else preview.url
        if preview is None:
            return 0
        return preview.width if role == OverlayModel.PreviewWidthRole else preview.height

    def request(self, name: str):
        if name not in self._queued:
            self._queued.add(name)
            self._queue.append(name)
            self._wake()

    def invalidate(self, name: str = ""):
        """Overlay setting changed (all overlays if no name): rendered again when shown"""
        self._stale.update((name,) if name else self._previews)

    def set_active(self, active: bool):
        self.active = active
        if active:
            self._wake()
        else:
            self._timer.stop()

    def pending(self) -> int:
        return len(self._queue)

    def stop(self):
        self._timer.stop()
        self._queue.clear()
        self._queued.clear()

    def _wake(self):
        if self.active and self._queue and not self._timer.isActive():
            self._timer.start()

    def _render_next(self):
        if not self._queue or not self.active:
            self._timer.stop()
            return
        name = self._queue.popleft()
        self._queued.discard(name)
        self._stale.discard(name)
        self.render_now(name)
        if not self._queue:
            self._timer.stop()

    def render_now(self, name: str):
        """Render overlay picture, page told only if it changed"""
        image = self._render(name)
        if image is None:
            preview = Preview("", 0, 0)
        else:
            ratio = image.devicePixelRatio() or 1
            preview = Preview(image_url(image), round(image.width() / ratio), round(image.height() / ratio))
        if self._previews.get(name) == preview:
            return  # same picture: kept, no reload in page
        self._previews[name] = preview
        self._on_ready(name)


def image_url(image: QImage) -> str:
    """Picture as PNG data URL for QML Image (no image provider shared with the QML engine)"""
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")  # type: ignore[call-overload]  # device save refuses bytes format at run time
    buffer.close()
    return f"data:image/png;base64,{bytes(data.toBase64().data()).decode('ascii')}"


def render_preview(name: str) -> QImage | None:
    """Overlay picture with current setting, None if it cannot be drawn (plugins needing live data...)"""
    from ..widget_preview import render_widget

    try:
        pixmap = render_widget(cfg, name, dict(cfg.user.setting[name]))
    except Exception as error:  # never break the page
        logger.debug("Overlay preview error: %s: %s", name, error, exc_info=True)
        return None
    if pixmap.isNull():
        return None
    ratio = pixmap.devicePixelRatio() or 1
    limit = PREVIEW_MAX * ratio
    if pixmap.width() > limit.width() or pixmap.height() > limit.height():
        pixmap = pixmap.scaled(limit, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(ratio)
    return pixmap.toImage()


class OverlayBackend(QObject):
    """Overlays page state & actions

    Args:
        parent: page widget, parent of config dialogs & messages.
        module_control: widget control.
        open_config: open config dialog of overlay (name).
        confirm: ask a yes / no question (message), True if yes.
        show_log: show app log (start errors).
    """

    countsChanged = Signal()
    filterChanged = Signal()
    rowsChanged = Signal()
    viewChanged = Signal()

    def __init__(
        self,
        parent,
        module_control: ModuleControl,
        open_config: Callable[[str], None],
        confirm: Callable[[str], bool],
        show_log: Callable[[], None] = lambda: None,
    ):
        super().__init__(parent)
        from ... import safe_mode

        self._control = module_control
        self._open_config = open_config
        self._confirm = confirm
        self._show_log = show_log
        self._safe_mode = safe_mode.state.enabled
        self.previews = PreviewCache(render_preview, self._preview_ready, self)
        self.source = OverlayModel(self, self.previews)
        self.proxy = OverlayFilter(self, self.source)
        self.proxy.rowsInserted.connect(self.countsChanged)
        self.proxy.rowsRemoved.connect(self.countsChanged)
        self.proxy.modelReset.connect(self.countsChanged)
        self._search = ""
        self.source.set_rows([self._new_row(name) for name in module_control.names])

    # State
    def _failed(self, name: str, enabled: bool) -> bool:
        """Enabled overlay not running: failed to start (error in log), overlays are off in safe mode"""
        return enabled and not self._safe_mode and name not in self._control.active_modules

    def _new_row(self, name: str) -> OverlayRow:
        enabled = bool(cfg.user.setting[name]["enable"])
        return OverlayRow(name, enabled, self._failed(name, enabled))

    def _update_row(self, row: OverlayRow) -> bool:
        enabled = bool(cfg.user.setting[row.name]["enable"])
        failed = self._failed(row.name, enabled)
        if (enabled, failed) == (row.enabled, row.failed):
            return False
        row.enabled, row.failed = enabled, failed
        self.source.row_changed(row.name, [OverlayModel.EnabledRole, OverlayModel.FailedRole])
        return True

    def update_overlay(self, name: str):
        """Overlay state from setting, after toggle or config saved"""
        index = self.source.index_of.get(name)
        if index is not None and self._update_row(self.source.rows[index]):
            self.countsChanged.emit()

    @Slot()
    def refresh(self):
        """Setting or preset changed (also hotkey & tray toggles): states read again, previews out of date"""
        names = set(self._control.names)
        if names != set(self.source.index_of):  # plugin added or removed
            self.source.set_rows([self._new_row(name) for name in self._control.names])
            self.rowsChanged.emit()
        else:
            for row in self.source.rows:
                self._update_row(row)
        self.previews.invalidate()
        self._emit_previews()  # shown rows read preview again: rendered again in background
        self.countsChanged.emit()

    def set_active(self, active: bool):
        """Page shown or hidden: previews rendered only while shown"""
        self.previews.set_active(active)

    def _preview_ready(self, name: str):
        self.source.row_changed(name, OverlayModel.PREVIEW_ROLES)

    def _emit_previews(self):
        count = self.source.rowCount()
        if count:
            self.source.dataChanged.emit(self.source.index(0, 0), self.source.index(count - 1, 0),
                                         OverlayModel.PREVIEW_ROLES)

    def invalidate_preview(self, name: str):
        self.previews.invalidate(name)
        self.source.row_changed(name, OverlayModel.PREVIEW_ROLES)

    # Properties
    @Property(QObject, constant=True)
    def model(self) -> QObject:
        return self.proxy

    @Property(bool, constant=True)
    def safeMode(self) -> bool:
        return self._safe_mode

    @Property(int, notify=countsChanged)
    def totalCount(self) -> int:
        return len(self.source.rows)

    @Property(int, notify=countsChanged)
    def activeCount(self) -> int:
        return sum(row.enabled for row in self.source.rows)

    @Property(int, notify=countsChanged)
    def failedCount(self) -> int:
        return sum(row.failed for row in self.source.rows)

    @Property(int, notify=countsChanged)
    def shownCount(self) -> int:
        return self.proxy.rowCount()

    @Property(list, notify=countsChanged)
    def stateCounts(self) -> list[int]:
        """Rows of All, Active & Inactive choice (search & category filter applied)"""
        rows = [row for row in self.source.rows if self.proxy.accepts(row, use_state=False)]
        active = sum(row.enabled for row in rows)
        return [len(rows), active, len(rows) - active]

    @Property(list, notify=rowsChanged)
    def categories(self) -> list[dict]:
        """Category chips: all, then categories having overlays"""
        present = {row.category for row in self.source.rows}
        chips = [{"key": CATEGORY_ALL, "label": tr("All"), "color": ""}]
        chips.extend(
            {"key": category, "label": tr(category), "color": CATEGORY_COLORS[category]}
            for category in CATEGORY_ORDER if category in present
        )
        return chips

    @Property(dict, notify=countsChanged)
    def categoryCounts(self) -> dict[str, int]:
        """Rows of each category chip (search & state filter applied)"""
        counts = dict.fromkeys((CATEGORY_ALL, *CATEGORY_ORDER), 0)
        for row in self.source.rows:
            if self.proxy.accepts(row, use_category=False):
                counts[row.category] += 1
                counts[CATEGORY_ALL] += 1
        return counts

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(int, notify=filterChanged)
    def stateFilter(self) -> int:
        return self.proxy.state

    @Property(str, notify=filterChanged)
    def category(self) -> str:
        return self.proxy.category

    @Property(bool, notify=filterChanged)
    def filtered(self) -> bool:
        proxy = self.proxy
        return bool(proxy.words) or proxy.state != FILTER_ALL or proxy.category != CATEGORY_ALL

    @Property(bool, notify=viewChanged)
    def gridView(self) -> bool:
        return bool(cfg.application.get("show_overlay_previews", True))

    # Filters
    def _set_filter(self, **values):
        """Change filter values (words, state, category), shown rows updated (animated in page)"""
        proxy = self.proxy
        proxy.beginFilterChange()
        for name, value in values.items():
            setattr(proxy, name, value)
        proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        self.filterChanged.emit()
        self.countsChanged.emit()

    @Slot(str)
    def setSearch(self, text: str):
        words = search_words(text)
        self._search = text
        if words != self.proxy.words:
            self._set_filter(words=words)
        else:
            self.filterChanged.emit()

    @Slot(int)
    def setStateFilter(self, state: int):
        if state in (FILTER_ALL, FILTER_ACTIVE, FILTER_INACTIVE) and state != self.proxy.state:
            self._set_filter(state=state)

    @Slot(str)
    def setCategory(self, category: str):
        if category in (CATEGORY_ALL, *CATEGORY_ORDER) and category != self.proxy.category:
            self._set_filter(category=category)

    @Slot()
    def clearFilters(self):
        self._search = ""
        self._set_filter(words=(), state=FILTER_ALL, category=CATEGORY_ALL)

    @Slot(bool)
    def setGridView(self, grid: bool):
        if grid != self.gridView:
            cfg.application["show_overlay_previews"] = grid
            cfg.save(config_type=ConfigType.CONFIG)
            self.viewChanged.emit()

    # Actions
    @Slot(str)
    def toggle(self, name: str):
        if name in self.source.index_of:
            self._control.toggle(name)
            self.update_overlay(name)

    @Slot(str)
    def openConfig(self, name: str):
        if name in self.source.index_of:
            self._open_config(name)

    @Slot()
    def showLog(self):
        self._show_log()

    @Slot()
    def enableShown(self):
        self._set_shown(True)

    @Slot()
    def disableShown(self):
        self._set_shown(False)

    def _set_shown(self, enable: bool):
        """Enable or disable shown overlays (every overlay without filter), confirmed if set so"""
        names = [name for name in self.proxy.shown_names() if bool(cfg.user.setting[name]["enable"]) != enable]
        if not names:
            return
        word = "Enable" if enable else "Disable"
        everything = len(names) == len(self.source.rows) or not self.filtered
        if cfg.application["show_confirmation_for_batch_toggle"]:
            text = f"<b>{word}</b> all overlays?" if everything else f"<b>{word}</b> {len(names)} shown overlays?"
            if not self._confirm(trm(text)):
                return
        if everything:
            if enable:
                self._control.enable_all()
            else:
                self._control.disable_all()
        else:
            for name in names:
                self._control.toggle(name)
        app_signal.refresh.emit(True)  # other pages & menus follow, rows updated by refresh

    def close(self):
        self.previews.stop()
