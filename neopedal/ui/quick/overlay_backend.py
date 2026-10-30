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
Overlays page backend (qml/Overlays.qml): overlay list model, filters, sort, previews & actions

Rows are filtered & sorted by a proxy model (search words, All / Active / Inactive, category or
Favorites / Recently Edited chip; by name, enabled first or category), so the QML grid animates rows
in & out instead of being rebuilt. Previews are rendered in background (a few ms of each event loop
tick, rows on screen first), only for rows the page shows and only while the page is visible (never
during a race with the window hidden), then served to QML by preview_provider (image:// URL, serial
changed only when the picture changes). A refresh renders again only previews whose inputs changed
(overlay options, global config & settings, style files, language, pixel ratio, game logos), checked
only while the page is shown; the old picture stays shown until the new one is ready (unchanged
picture: page not told). Pictures are shared by inputs with other pages (widget_preview).

A hovered card plays its overlay on a moving simulated session (LiveRunner), one at a time. The
screen view shows running overlays at their place on the screens (overlay_screen), movable there by mouse
(snapped to other overlays & screens) or keyboard, saved & undoable like moves in game, never while overlays
are locked; a screenshot of the game can be shown under them (in memory only).
Favorites & recently edited overlays are kept in config.json (application section), not in presets.
Enabling or disabling the shown overlays is done at once, with Undo in the page toast.
"""

from __future__ import annotations

import logging
import weakref
from collections import deque
from collections.abc import Callable, Collection, Iterable, Mapping
from functools import partial
from time import perf_counter
from typing import Any, NamedTuple

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QBuffer,
    QByteArray,
    QIODevice,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication, QImage, QImageReader

from ... import app_signal
from ...const_file import ConfigType, FileExt
from ...i18n import tr, trm
from ...i18n.options import module_label
from ...module_control import ModuleControl
from ...setting import cfg
from ...template.widget.descriptions import OVERLAY_DESCRIPTIONS
from ...template.widget.registry import CATEGORY_COLORS as REGISTRY_COLORS
from ...template.widget.registry import OTHER as CATEGORY_OTHER
from ...template.widget.registry import category_of
from ..module_view import sort_key
from .overlay_screen import bounds_of, clamped_position, overlapping, rect_value, screen_for_image, snap_position
from .page_backend import PageBackend
from .preview_provider import STORE

logger = logging.getLogger(__name__)

ROOT = QModelIndex()  # list rows have no parent
PREVIEW_MAX = QSize(520, 360)  # bigger overlays (standings...) scaled down: card & tooltip sizes
FILTER_ALL = 0
FILTER_ACTIVE = 1
FILTER_INACTIVE = 2
PREVIEW_LOADING = 0
PREVIEW_READY = 1
PREVIEW_UNAVAILABLE = 2
RENDER_BUDGET = 0.008  # seconds of previews rendered per event loop tick (at least one)
UNDO_DEPTH = 30  # page changes undone one after another with Ctrl+Z (switches, batch switches, moves)
_WIDGET_CATEGORY = category_of()  # category of built-in widgets

# Widget categories: (name, widget names) in chips order, unknown widgets (plugins) are "Other",
# see template.widget.registry.OVERLAYS
WIDGET_CATEGORIES = tuple(
    (category, tuple(name for name, of in _WIDGET_CATEGORY.items() if of == category))
    for category in REGISTRY_COLORS if category != CATEGORY_OTHER
)
CATEGORY_ALL = ""  # category filter off
# Chips of marked overlays, filtering like categories (keys never category names)
CATEGORY_FAVORITES = "#favorites"
CATEGORY_RECENT = "#recent"
# Category color, readable on light & dark theme
CATEGORY_COLORS = dict(REGISTRY_COLORS)
CATEGORY_ORDER = (*(category for category, _ in WIDGET_CATEGORIES), CATEGORY_OTHER)
CATEGORY_RANK = {category: rank for rank, category in enumerate(CATEGORY_ORDER)}
CATEGORY_KEYS = (CATEGORY_ALL, CATEGORY_FAVORITES, CATEGORY_RECENT, *CATEGORY_ORDER)

# Sort of rows
SORT_NAME = 0
SORT_ACTIVE = 1  # enabled first
SORT_CATEGORY = 2
SORT_MODES = (SORT_NAME, SORT_ACTIVE, SORT_CATEGORY)

# Views
VIEW_CARDS = 0
VIEW_LIST = 1
VIEW_SCREEN = 2

# Overlay names kept in config.json (application section), comma separated
FAVORITES_KEY = "favorite_overlays"
RECENT_KEY = "recent_overlays"
RECENT_MAX = 8  # recently edited overlays kept
PRESETS_SHOWN = 15  # presets in header menu (most recent first)

# Animated preview of hovered card
LIVE_FRAME_MS = 66  # about 15 pictures per second
LIVE_SLOW_SECONDS = 0.03  # picture drawn slower than this: fewer pictures per second (twice its time)
SCREEN_POLL_MS = 1000  # screen view: overlays moved in game (dragged) followed
# Screenshot under the screen view: kept at most this wide (the view shows a screen a few hundred pixels wide; a
# 4K capture would hold 33 MB in the store), files decoded within this memory (see QImageReader.allocationLimit)
BACKGROUND_MAX_WIDTH = 1920
BACKGROUND_ALLOCATION_MB = 128


def widget_category(name: str) -> str:
    """Category of widget"""
    return _WIDGET_CATEGORY.get(name, CATEGORY_OTHER)


def overlay_description(name: str) -> str:
    """What overlay shows (current language), "" if unknown (plugins)"""
    text = OVERLAY_DESCRIPTIONS.get(name, "")
    return tr(text) if text else ""


def search_words(text: str) -> tuple[str, ...]:
    """Search text words, case & accent folded: every word must match (any order)"""
    return tuple(sort_key(text).split())


def name_list(key: str) -> list[str]:
    """Overlay names of application option (comma separated), in order, without duplicates"""
    value = cfg.application.get(key, "")
    if not isinstance(value, str):
        return []
    return list(dict.fromkeys(name.strip() for name in value.split(",") if name.strip()))


def save_name_list(key: str, names: Iterable[str]) -> bool:
    """Store overlay names in application option, True if changed (config saved)"""
    value = ",".join(names)
    if cfg.application.get(key) == value:
        return False
    cfg.application[key] = value
    cfg.save(config_type=ConfigType.CONFIG)
    return True


def note_edited(names: Iterable[str]) -> bool:
    """Overlays whose options were saved (Overlay Options page): first of Recently Edited chip (last edited
    first, RECENT_MAX kept), True if changed"""
    edited = [name for name in names if name]
    if not edited:
        return False
    recent = list(dict.fromkeys([*reversed(edited), *name_list(RECENT_KEY)]))[:RECENT_MAX]
    return save_name_list(RECENT_KEY, recent)


def visibility_badges(setting: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """When overlay shows, if not always: (kind, value) per limit, kind "context" (session or pit state),
    "stream" (stream only) or "screen" (screen only)"""
    badges = []
    context = setting.get("visibility_context", "Always")
    if isinstance(context, str) and context != "Always":
        badges.append(("context", context))
    stream = setting.get("stream_visibility", "Screen & Stream")
    if stream == "Stream Only":
        badges.append(("stream", stream))
    elif stream == "Screen Only":
        badges.append(("screen", stream))
    return tuple(badges)


BADGE_TIPS = {
    "context": "Shown only in some sessions, on track or in pits (Visibility Context option)",
    "stream": "Shown only on stream (browser sources), hidden on screen",
    "screen": "Shown only on screen, never on stream",
}


def badge_values(badges: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    """Badges for QML: kind, text & tip (current language)"""
    return [{"kind": kind, "text": tr(value), "tip": tr(BADGE_TIPS[kind])} for kind, value in badges]


class OverlayRow:
    """Overlay of list: name, texts & state"""

    __slots__ = ("name", "label", "category", "description", "search", "enabled", "failed", "favorite", "badges")

    def __init__(self, name: str, enabled: bool, failed: bool, favorite: bool = False,
                 badges: tuple[tuple[str, str], ...] = ()):
        self.name = name
        self.label = module_label(name)
        self.category = widget_category(name)
        self.description = overlay_description(name)
        # Matched by label, widget name (english words) & category, in any language
        self.search = sort_key(f"{self.label} {name.replace('_', ' ')} {tr(self.category)}")
        self.enabled = enabled
        self.failed = failed
        self.favorite = favorite
        self.badges = badges

    def matches(self, words: tuple[str, ...]) -> bool:
        return all(word in self.search for word in words)


class Preview(NamedTuple):
    """Rendered overlay picture: image provider URL ("" if not available) & logical size"""

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
    DescriptionRole = Qt.ItemDataRole.UserRole + 12
    FavoriteRole = Qt.ItemDataRole.UserRole + 13
    BadgesRole = Qt.ItemDataRole.UserRole + 14
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
        DescriptionRole: b"description",
        FavoriteRole: b"favorite",
        BadgesRole: b"badges",
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
        if role == self.DescriptionRole:
            return row.description
        if role == self.FavoriteRole:
            return row.favorite
        if role == self.BadgesRole:
            return badge_values(row.badges)
        if role in self.PREVIEW_ROLES:
            return self.previews.role(row.name, role)
        return None

    def row_changed(self, name: str, roles: list[int]):
        row = self.index_of.get(name)
        if row is not None:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, roles)


class OverlayFilter(QSortFilterProxyModel):
    """Rows shown: matching search words, state & category (or favorites / recent) filter, sorted by sort mode

    Sorted only when asked (resort): a switched overlay never jumps away from under the pointer.
    """

    def __init__(self, parent, model: OverlayModel):
        super().__init__(parent)
        self.words: tuple[str, ...] = ()
        self.state = FILTER_ALL
        self.category = CATEGORY_ALL
        self.sort_mode = SORT_NAME
        self.recent: dict[str, int] = {}  # recently edited overlay: rank (0 newest)
        self.setDynamicSortFilter(False)
        self.setSourceModel(model)
        self.sort(0)

    def source_rows(self) -> list[OverlayRow]:
        return self.sourceModel().rows  # type: ignore[attr-defined]

    def accepts(self, row: OverlayRow, use_state: bool = True, use_category: bool = True) -> bool:
        """Row passes filters (state or category filter left out to count rows of each choice)"""
        return (
            row.matches(self.words)
            and (not use_state or self.state == FILTER_ALL or (self.state == FILTER_ACTIVE) == row.enabled)
            and (not use_category or self.in_category(row, self.category))
        )

    def in_category(self, row: OverlayRow, category: str) -> bool:
        if category == CATEGORY_ALL:
            return True
        if category == CATEGORY_FAVORITES:
            return row.favorite
        if category == CATEGORY_RECENT:
            return row.name in self.recent
        return row.category == category

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        rows = self.source_rows()
        return 0 <= source_row < len(rows) and self.accepts(rows[source_row])

    def sort_key(self, index: int) -> tuple:
        """Sort key of source row (source rows are sorted by label: row index breaks ties)"""
        row = self.source_rows()[index]
        if self.category == CATEGORY_RECENT:  # last edited first
            return self.recent.get(row.name, RECENT_MAX), index
        if self.sort_mode == SORT_ACTIVE:
            return not row.enabled, index
        if self.sort_mode == SORT_CATEGORY:
            return CATEGORY_RANK.get(row.category, len(CATEGORY_RANK)), index
        return (index,)

    def lessThan(self, source_left: QModelIndex | QPersistentModelIndex,
                 source_right: QModelIndex | QPersistentModelIndex) -> bool:
        return self.sort_key(source_left.row()) < self.sort_key(source_right.row())

    def resort(self):
        """Rows placed again by sort mode (states changed since last sort)"""
        self.invalidate()  # sorted again by sort(0) column kept

    def shown_names(self) -> list[str]:
        """Shown overlays in shown order"""
        return [self.data(self.index(row, 0), OverlayModel.NameRole) for row in range(self.rowCount())]


class PreviewCache:
    """Overlay pictures, rendered in background while active (time budget per event loop tick, rows on screen
    first)

    Args:
        render: picture of overlay, None if not available.
        on_ready: called with overlay name when its picture changed.
        signature: inputs of the picture of overlay (any comparable value): invalidate() then marks only pictures
            whose inputs changed. Without it every picture is out of date after invalidate().
    """

    def __init__(
        self,
        render: Callable[[str], QImage | None],
        on_ready: Callable[[str], None],
        parent=None,
        signature: Callable[[str], object] | None = None,
    ):
        self._render = render
        self._on_ready = on_ready
        self._signature = signature
        self._previews: dict[str, Preview] = {}
        self._signatures: dict[str, object] = {}  # inputs of drawn pictures
        self._stale: set[str] = set()
        self._queue: deque[str] = deque()
        self._queued: set[str] = set()
        self._visible: frozenset[str] = frozenset()  # rows on screen: rendered first
        self.active = False  # page visible: queue rendered
        self._timer = QTimer(parent)  # deleted with backend: never fires on a deleted model
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_next)
        self._prefix = STORE.new_prefix("overlays")  # pictures served to QML by preview_provider
        weakref.finalize(self, STORE.release, self._prefix)

    @property
    def prefix(self) -> str:
        """Key prefix of pictures in STORE (released with the cache)"""
        return self._prefix

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
        """Overlay setting changed (all overlays if no name, only those whose inputs changed when signed):
        rendered again when shown"""
        if name:
            self._stale.add(name)
        elif self._signature is None:
            self._stale.update(self._previews)
        else:
            signature = self._signature
            self._stale.update(
                drawn for drawn in self._previews if self._signatures.get(drawn) != signature(drawn))

    def is_stale(self, name: str) -> bool:
        return name in self._stale

    def set_visible(self, names: Collection[str]):
        """Rows on screen: their pictures rendered first"""
        self._visible = frozenset(names)

    def redraw(self, names: list[str]):
        """Render again pictures of names already drawn & out of date (shown rows), in background"""
        for name in names:
            if name in self._stale and name in self._previews:
                self.request(name)

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

    def _take(self) -> str:
        """Next overlay to render: first queued row on screen, else first queued"""
        if self._visible:
            for position, name in enumerate(self._queue):
                if name in self._visible:
                    del self._queue[position]
                    return name
        return self._queue.popleft()

    def _render_next(self):
        """Render queued pictures for a few ms (at least one), rest on next ticks: page stays responsive"""
        deadline = perf_counter() + RENDER_BUDGET
        while self._queue and self.active:
            name = self._take()
            self._queued.discard(name)
            self._stale.discard(name)
            self.render_now(name)
            if perf_counter() >= deadline:
                break
        if not self._queue or not self.active:
            self._timer.stop()

    def render_now(self, name: str):
        """Render overlay picture, page told only if it changed"""
        if self._signature is not None:
            self._signatures[name] = self._signature(name)
        image = self._render(name)
        key = f"{self._prefix}{name}"
        if image is None:
            preview = Preview("", 0, 0)
            STORE.discard(key)
        else:
            ratio = image.devicePixelRatio() or 1
            # Same picture: same URL (serial kept)
            preview = Preview(STORE.put(key, image), round(image.width() / ratio), round(image.height() / ratio))
        if self._previews.get(name) == preview:
            return  # same picture: kept, no reload in page
        self._previews[name] = preview
        self._on_ready(name)


class LiveRunner:
    """Animated preview of one overlay at a time: pictures drawn by timer into STORE (key), url told by on_frame

    Args:
        make: animated picture source of overlay (widget_preview.live_preview), None if not animated.
        on_frame: called with picture URL ("" once stopped).
        key: STORE key of pictures.
        parent: timer parent (deleted with it).
    """

    def __init__(self, make: Callable[[str], Any], on_frame: Callable[[str], None], key: str, parent=None):
        self._make = make
        self._on_frame = on_frame
        self._key = key
        self._live: Any = None
        self._started = 0.0
        self._url = ""
        self.name = ""
        self.still: set[str] = set()  # overlays not animated (sample, error): never built again
        self._timer = QTimer(parent)
        self._timer.setInterval(LIVE_FRAME_MS)
        self._timer.timeout.connect(self._next)

    def start(self, name: str):
        """Play overlay (first picture on next timer tick: hover answered at once)"""
        if name == self.name or name in self.still:
            return
        self.stop()
        self.name = name
        self._timer.setInterval(LIVE_FRAME_MS)
        self._timer.start()

    def restart(self, name: str):
        """Play overlay from a new source (options, zoom or race situation changed): last picture kept shown until
        the first new one, an overlay not animated before tried again"""
        self.still.discard(name)
        if name != self.name:
            self.start(name)
            return
        if self._live is not None:
            self._live.close()
            self._live = None
        self._timer.setInterval(LIVE_FRAME_MS)
        if not self._timer.isActive():
            self._timer.start()

    @property
    def playing(self) -> bool:
        """An overlay is played (pictures drawn by timer)"""
        return bool(self.name)

    def stop(self, name: str = ""):
        """Stop playing (only if playing name, when given)"""
        if not self.name or (name and name != self.name):
            return
        self._timer.stop()
        if self._live is not None:
            self._live.close()
            self._live = None
        self.name = ""
        STORE.discard(self._key)
        if self._url:
            self._url = ""
            self._on_frame("")

    def _next(self):
        name = self.name
        try:
            if self._live is None:
                self._live = self._make(name)
                self._started = perf_counter()
                if self._live is None:
                    self.still.add(name)
                    self.stop()
                    self._on_frame("")  # told even without picture shown: page knows it is not animated
                    return
            drawing = perf_counter()
            image = self._live.frame(drawing - self._started)
            cost = perf_counter() - drawing
        except Exception as error:  # never break the page: still picture kept
            logger.debug("Live preview error: %s: %s", name, error, exc_info=True)
            image = None
        if image is None:
            self.still.add(name)
            self.stop()
            self._on_frame("")  # told even without picture shown: page knows it is not animated
            return
        if cost > LIVE_SLOW_SECONDS:  # big overlay: fewer pictures, page stays responsive
            self._timer.setInterval(max(LIVE_FRAME_MS, round(cost * 2000)))
        url = STORE.put(self._key, image)
        if url != self._url:
            self._url = url
            self._on_frame(url)

    def forget_still(self):
        """Options changed: overlays not animated before tried again"""
        self.still.clear()


def image_url(image: QImage) -> str:
    """Picture as PNG data URL (pages without the overlaypreview image provider, HTML)"""
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")  # type: ignore[call-overload]  # device save refuses bytes format at run time
    buffer.close()
    return f"data:image/png;base64,{bytes(data.toBase64().data()).decode('ascii')}"


def render_preview(name: str) -> QImage | None:
    """Overlay picture with current setting, None if it cannot be drawn (plugins needing live data...); same
    inputs as a picture drawn before (any page): that picture"""
    from ..widget_preview import render_image

    try:
        return render_image(cfg, name, cfg.user.setting[name], max_size=PREVIEW_MAX)
    except Exception as error:  # never break the page
        logger.debug("Overlay preview error: %s: %s", name, error, exc_info=True)
        return None


def make_live_preview(name: str) -> Any:
    """Animated picture source of overlay with current setting, None if not animated"""
    from ..widget_preview import live_preview

    setting = cfg.user.setting.get(name)
    if not isinstance(setting, dict):
        return None
    return live_preview(cfg, name, setting, PREVIEW_MAX)


def preview_signature(name: str) -> object:
    """Inputs of overlay picture (see widget_preview.preview_key): shared inputs read once per setting refresh"""
    from ..widget_preview import preview_key

    setting = cfg.user.setting.get(name)
    if not isinstance(setting, dict):
        return None
    return preview_key(cfg, name, setting, max_size=PREVIEW_MAX)


def screen_rects() -> list[tuple[str, QRect, bool]]:
    """Screens of desktop: name, geometry & primary"""
    primary = QGuiApplication.primaryScreen()
    return [(screen.name(), screen.geometry(), screen is primary) for screen in QGuiApplication.screens()]


def screen_scales() -> list[tuple[QRect, float]]:
    """Screens of desktop: geometry & device pixel ratio (size of a screenshot taken on it)"""
    return [(screen.geometry(), screen.devicePixelRatio()) for screen in QGuiApplication.screens()]


def positions_locked() -> bool:
    """Overlays locked (Lock Overlays): never moved, also not from the screen view (as in game)"""
    return bool(cfg.overlay["fixed_position"])


def shrink_background(image: QImage, max_width: int = BACKGROUND_MAX_WIDTH) -> QImage:
    """Screenshot scaled down to max_width (same ratio) if wider, else as is (any thread)"""
    if image.isNull() or image.width() <= max_width:
        return image
    scaled = image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(1)
    return scaled


def read_background(filename: str, max_width: int = BACKGROUND_MAX_WIDTH) -> tuple[QSize, QImage]:
    """Screenshot file decoded at most max_width wide (worker thread: a 4K PNG takes 100 ms or more), with its
    pixel size on screen (tells the screen it was taken on); image null if unreadable or too big"""
    reader = QImageReader(filename)
    reader.setAllocationLimit(BACKGROUND_ALLOCATION_MB)
    size = reader.size()  # from the file header, before decoding (invalid for formats without one)
    if size.isValid() and size.width() > max_width:
        # Decoded straight to the shown size when the format allows (JPEG), else scaled by the reader
        reader.setScaledSize(QSize(max_width, max(1, round(size.height() * max_width / size.width()))))
    image = reader.read()
    if image.isNull():
        return size, image
    if not size.isValid():
        size = image.size()
    return size, shrink_background(image, max_width)


class OverlayBackend(PageBackend):
    """Overlays page state & actions

    Args:
        parent: page widget, parent of config dialogs & messages.
        module_control: widget control.
        open_config: open config dialog of overlay (name).
        confirm: ask a yes / no question (message), True if yes.
        show_log: show app log (start errors).
        export_settings: export settings of overlays (names ticked first) as package file.
        import_settings: import overlay settings package file.
        open_presets: show Presets page.
        capture_screen: picture of the screen of this name (app window hidden meanwhile), None if not taken.
        pick_screenshot: picture file chosen by the user, "" if cancelled.
        ask: ask a question in the page (text, action button text, on_result(chosen)), else confirm answers.

    Messages (moves, batch switch, test on screen) show in the page toast (show_toast), Undo in it; signals
    overlayMoved, bulkToggled & notice tell them too. Every reversible change of the page (switch, batch switch,
    move) goes on one undo history: Ctrl+Z (undo(), page shortcut) undoes the last one, Undo of a toast its own.
    """

    countsChanged = Signal()  # rows, enabled, failed, shown & shown enabled
    filterCountsChanged = Signal()  # rows of each filter choice (state & category chips)
    filterChanged = Signal()
    rowsChanged = Signal()
    viewChanged = Signal()
    presetChanged = Signal()
    liveChanged = Signal()
    screenChanged = Signal()
    lockChanged = Signal()  # overlays locked or unlocked (screen view: moves allowed or not)
    backgroundChanged = Signal()  # screenshot under the screen view
    overlayMoved = Signal(str)  # label of overlay moved from screen view (undo offered)
    bulkToggled = Signal(str)  # shown overlays enabled or disabled: message (undo offered)
    notice = Signal(str)  # short message for the page toast
    undoChanged = Signal()  # page undo history changed (Ctrl+Z enabled or not)

    def __init__(
        self,
        parent,
        module_control: ModuleControl,
        open_config: Callable[[str], None],
        confirm: Callable[[str], bool],
        show_log: Callable[[], None] = lambda: None,
        export_settings: Callable[[list[str]], object] = lambda names: None,
        import_settings: Callable[[], object] = lambda: None,
        open_presets: Callable[[], object] = lambda: None,
        capture_screen: Callable[[str], QImage | None] = lambda name: None,
        pick_screenshot: Callable[[], str] = lambda: "",
        ask: Callable[[str, str, Callable[[bool], object]], object] | None = None,
    ):
        super().__init__(parent, "Overlays")
        from ... import safe_mode

        self._control = module_control
        self._open_config = open_config
        self._confirm = confirm
        self._show_log = show_log
        self._export_settings = export_settings
        self._import_settings = import_settings
        self._open_presets = open_presets
        self._capture_screen = capture_screen
        self._pick_screenshot = pick_screenshot
        self._ask = ask
        self._safe_mode = safe_mode.state.enabled
        self._positions_locked = positions_locked()
        self._background: dict[str, Any] = {}  # screenshot under the screen view: url & desktop rect
        # Page undo history (Ctrl+Z, toasts): (kind, overlay name or "", undo action), last change last
        self._undo: list[tuple[str, str, Callable[[], object]]] = []
        self._inputs_changed = False  # setting refreshed while hidden: previews checked once shown
        self._shown_once = False  # page shown at least once: a refresh while hidden waits for the next show
        self._refresh_pending = (False, False)  # states & marks changed by refreshes not yet shown (see refresh)
        self.previews = PreviewCache(render_preview, self._preview_ready, self, self.preview_signature)
        self.live = LiveRunner(make_live_preview, self._live_frame, f"{self.previews.prefix}#live", self)
        self._live_url = ""
        self.source = OverlayModel(self, self.previews)
        self.proxy = OverlayFilter(self, self.source)
        self.proxy.rowsInserted.connect(self._count_shown)
        self.proxy.rowsRemoved.connect(self._count_shown)
        self.proxy.modelReset.connect(self._count_shown)
        self._search = ""
        self._view = self._saved_view()  # view shown, see refresh
        self._counts = (0, 0)  # enabled & failed rows, see _recount
        self._totals = (0, 0, 0, 0, 0)  # rows, enabled, failed, shown & shown enabled (count properties)
        self._state_counts = [0, 0, 0]  # rows of All, Active & Inactive choice
        self._category_counts: dict[str, int] = dict.fromkeys(CATEGORY_KEYS, 0)  # rows of each chip
        self._favorites: set[str] = set(name_list(FAVORITES_KEY))
        self._preset = (cfg.filename.setting, cfg.filename.setting in cfg.user.filelock)
        self._screen: dict[str, Any] = {}
        self._screen_names: frozenset[str] = frozenset()  # overlays in screen view
        self._screen_timer = self.page_timer(self._poll_screen, SCREEN_POLL_MS)
        self._screen_soon = self.page_timer(self._update_screen, 50, single_shot=True)  # previews of several rows
        sort_mode = cfg.application.get("overlays_sort_order", SORT_NAME)
        self.proxy.sort_mode = sort_mode if sort_mode in SORT_MODES else SORT_NAME
        self.proxy.recent = {name: rank for rank, name in enumerate(name_list(RECENT_KEY))}
        self.source.set_rows([self._new_row(name) for name in module_control.names])
        self.proxy.resort()
        self._recount()
        self._update_counts()

    # State
    def _failed(self, name: str, enabled: bool) -> bool:
        """Enabled overlay not running: failed to start (error in log), overlays are off in safe mode"""
        return enabled and not self._safe_mode and name not in self._control.active_modules

    def _new_row(self, name: str) -> OverlayRow:
        setting = cfg.user.setting[name]
        enabled = bool(setting["enable"])
        return OverlayRow(name, enabled, self._failed(name, enabled), name in self._favorites, visibility_badges(setting))

    def _update_row(self, row: OverlayRow) -> bool:
        """Row state read again from setting, True if enabled or failed state changed (counts)"""
        setting = cfg.user.setting[row.name]
        enabled = bool(setting["enable"])
        failed = self._failed(row.name, enabled)
        favorite = row.name in self._favorites
        badges = visibility_badges(setting)
        roles = []
        if (enabled, failed) != (row.enabled, row.failed):
            row.enabled, row.failed = enabled, failed
            roles += [OverlayModel.EnabledRole, OverlayModel.FailedRole]
        if favorite != row.favorite:
            row.favorite = favorite
            roles.append(OverlayModel.FavoriteRole)
        if badges != row.badges:
            row.badges = badges
            roles.append(OverlayModel.BadgesRole)
        if roles:
            self.source.row_changed(row.name, roles)
        return OverlayModel.EnabledRole in roles

    def _recount(self):
        """Enabled & failed rows counted once per change (count properties read often by page)"""
        rows = self.source.rows
        self._counts = (sum(row.enabled for row in rows), sum(row.failed for row in rows))

    def _update_counts(self):
        """Rows of each filter choice & shown rows counted again (state, marks or filters changed), page told only of
        counts that changed"""
        proxy = self.proxy
        rows = [row for row in self.source.rows if proxy.accepts(row, use_state=False)]
        active = sum(row.enabled for row in rows)
        state_counts = [len(rows), active, len(rows) - active]
        category_counts = dict.fromkeys(CATEGORY_KEYS, 0)
        for row in self.source.rows:
            if proxy.accepts(row, use_category=False):
                category_counts[row.category] += 1
                category_counts[CATEGORY_ALL] += 1
                category_counts[CATEGORY_FAVORITES] += row.favorite
                category_counts[CATEGORY_RECENT] += row.name in proxy.recent
        if state_counts != self._state_counts or category_counts != self._category_counts:
            self._state_counts, self._category_counts = state_counts, category_counts
            self.filterCountsChanged.emit()
        self._count_shown()

    def _count_shown(self):
        """Count properties worked out (rows shown or their state changed), countsChanged sent if one changed"""
        proxy = self.proxy
        shown = proxy.rowCount()
        shown_active = sum(bool(proxy.data(proxy.index(row, 0), OverlayModel.EnabledRole)) for row in range(shown))
        totals = (len(self.source.rows), *self._counts, shown, shown_active)
        if totals != self._totals:
            self._totals = totals
            self.countsChanged.emit()

    def update_overlay(self, name: str):
        """Overlay state from setting, after toggle or config saved"""
        index = self.source.index_of.get(name)
        if index is not None and self._update_row(self.source.rows[index]):
            self._states_changed(True, False)
            self._screen_changed()

    def _states_changed(self, enabled: bool, marks: bool):
        """Rows changed state (enabled, favorite or recent): counted again, filtered again if a filter uses it
        (rows are never filtered nor sorted again by themselves: a switched card stays under the pointer)"""
        if enabled:
            self._recount()
        proxy = self.proxy
        if (enabled and proxy.state != FILTER_ALL) or (marks and proxy.category in (CATEGORY_FAVORITES, CATEGORY_RECENT)):
            self._set_filter()
        elif enabled or marks:
            self._update_counts()

    def preview_signature(self, name: str) -> object:
        """Inputs of overlay picture: shared inputs (read again after refresh), overlay options & style"""
        return preview_signature(name)

    @Slot()
    def refresh(self):
        """Setting or preset changed (also hotkey & tray toggles): states read again, previews whose inputs
        changed rendered again (inputs read only while page is shown: never while racing)

        Rows follow the setting at once (a toggled overlay is right whenever the page is read); the rest (counts,
        filters & chips, view, preset, lock, screen layout, previews) only serves the shown page: while the page is
        hidden (racing, window in the tray) it is done once, when the page is shown again.
        """
        from ..widget_preview import inputs_changed

        names = set(self._control.names)
        changed = False
        self._favorites = set(name_list(FAVORITES_KEY))
        recent = {name: rank for rank, name in enumerate(name_list(RECENT_KEY))}
        marks_changed = recent != self.proxy.recent
        self.proxy.recent = recent
        if names != set(self.source.index_of):  # plugin added or removed
            self.source.set_rows([self._new_row(name) for name in self._control.names])
            self.rowsChanged.emit()
            changed = True
        else:
            for row in self.source.rows:
                favorite = row.favorite
                changed = self._update_row(row) or changed
                marks_changed = marks_changed or favorite != row.favorite
        inputs_changed()
        self._inputs_changed = True
        pending_changed, pending_marks = self._refresh_pending
        self._refresh_pending = (pending_changed or changed, pending_marks or marks_changed)
        # A page never shown yet has no shown state to protect: counts & chips follow at once
        if self._shown_once and self.defer_while_hidden(self._refresh_page):
            return
        self._refresh_page()

    def _refresh_page(self):
        """Part of refresh serving the shown page (see refresh), several refreshes while hidden: once"""
        changed, marks_changed = self._refresh_pending
        self._refresh_pending = (False, False)
        self.live.forget_still()
        self.live.stop()  # options may have changed: started again by hover
        if self.previews.active and self._inputs_changed:  # not checked by set_active already
            self._check_previews()
        self._states_changed(changed, marks_changed)
        if marks_changed:
            self.rowsChanged.emit()  # chips (recent chip shown once something edited)
        view = self._saved_view()
        if view != self._view:  # cards or list set on Config page
            self._view = view
            self.viewChanged.emit()
        preset = (cfg.filename.setting, cfg.filename.setting in cfg.user.filelock)
        if preset != self._preset:
            self._preset = preset
            self.presetChanged.emit()
        self._read_lock()
        self._screen_changed()

    def _read_lock(self):
        """Overlays locked or unlocked (tray, hotkey, Home page): page told only if changed"""
        locked = positions_locked()
        if locked != self._positions_locked:
            self._positions_locked = locked
            self.lockChanged.emit()

    def _check_previews(self):
        """Previews whose inputs changed marked out of date, those of shown rows rendered again in background
        (page told per row only if picture changed)"""
        self._inputs_changed = False
        self.previews.invalidate()
        self.previews.redraw(self.proxy.shown_names())

    def set_active(self, active: bool):
        """Page shown or hidden: previews checked & rendered only while shown"""
        from ..widget_preview import set_showing

        self._shown_once = self._shown_once or active
        set_showing(self, active)
        self.previews.set_active(active)
        if active and self._inputs_changed:
            self._check_previews()
        if active:
            self._screen_changed()
        else:
            self.live.stop()
            self._screen_timer.stop()

    def _preview_ready(self, name: str):
        self.source.row_changed(name, OverlayModel.PREVIEW_ROLES)
        if self._view == VIEW_SCREEN and name in self._screen_names:
            self._screen_soon.start()  # several pictures ready in a row: layout sent once

    @Slot(int, int)
    def setVisibleRows(self, first: int, last: int):
        """Rows on screen (page rows, first to last): their previews rendered first"""
        proxy = self.proxy
        last = min(last, proxy.rowCount() - 1)
        self.previews.set_visible([
            proxy.data(proxy.index(row, 0), OverlayModel.NameRole) for row in range(max(first, 0), last + 1)])

    # Properties
    @Property(QObject, constant=True)
    def model(self) -> QObject:
        return self.proxy

    @Property(bool, constant=True)
    def safeMode(self) -> bool:
        return self._safe_mode

    @Property(int, notify=countsChanged)
    def totalCount(self) -> int:
        return self._totals[0]

    @Property(int, notify=countsChanged)
    def activeCount(self) -> int:
        return self._totals[1]

    @Property(int, notify=countsChanged)
    def failedCount(self) -> int:
        return self._totals[2]

    @Property(int, notify=countsChanged)
    def shownCount(self) -> int:
        return self._totals[3]

    @Property(list, notify=filterCountsChanged)
    def stateCounts(self) -> list[int]:
        """Rows of All, Active & Inactive choice (search & category filter applied)"""
        return self._state_counts

    @Property(list, notify=rowsChanged)
    def categories(self) -> list[dict]:
        """Chips: all, favorites, recently edited (once something edited), then categories having overlays"""
        present = {row.category for row in self.source.rows}
        chips = [
            {"key": CATEGORY_ALL, "label": tr("All"), "color": "", "glyph": ""},
            {"key": CATEGORY_FAVORITES, "label": tr("Favorites"), "color": "", "glyph": ""},  # star
        ]
        if self.proxy.recent:
            chips.append({"key": CATEGORY_RECENT, "label": tr("Recently Edited"), "color": "", "glyph": ""})
        chips.extend(
            {"key": category, "label": tr(category), "color": CATEGORY_COLORS[category], "glyph": ""}
            for category in CATEGORY_ORDER if category in present
        )
        return chips

    @Property(dict, notify=filterCountsChanged)
    def categoryCounts(self) -> dict[str, int]:
        """Rows of each chip (search & state filter applied)"""
        return self._category_counts

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

    @Property(int, notify=filterChanged)
    def sortMode(self) -> int:
        return self.proxy.sort_mode

    @Property(bool, notify=viewChanged)
    def gridView(self) -> bool:
        return self._view == VIEW_CARDS

    @Property(int, notify=viewChanged)
    def viewMode(self) -> int:
        return self._view

    @Property(str, notify=presetChanged)
    def presetName(self) -> str:
        filename = self._preset[0]
        return filename[:-len(FileExt.JSON)] if filename.endswith(FileExt.JSON) else filename

    @Property(bool, notify=presetChanged)
    def presetLocked(self) -> bool:
        return self._preset[1]

    @Property(str, notify=liveChanged)
    def liveName(self) -> str:
        return self.live.name if self._live_url else ""

    @Property(str, notify=liveChanged)
    def liveUrl(self) -> str:
        return self._live_url

    @Property(dict, notify=screenChanged)
    def screenLayout(self) -> dict:
        return self._screen

    @Property(bool, notify=lockChanged)
    def positionsLocked(self) -> bool:
        return self._positions_locked

    @Property(dict, notify=backgroundChanged)
    def background(self) -> dict:
        """Screenshot under the screen view: url & desktop rect (x, y, w, h), empty if none"""
        return self._background

    @Property(int, notify=countsChanged)
    def shownActiveCount(self) -> int:
        """Shown overlays enabled (Disable button count; Enable button: the others)"""
        return self._totals[4]

    # Filters
    def _set_filter(self, **values):
        """Change filter values (words, state, category), shown rows updated (animated in page)"""
        proxy = self.proxy
        resort = values.get("category", proxy.category) != proxy.category and CATEGORY_RECENT in (
            values["category"], proxy.category)
        proxy.beginFilterChange()
        for name, value in values.items():
            setattr(proxy, name, value)
        proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        if resort:  # recent chip: last edited first
            proxy.resort()
        self.filterChanged.emit()
        self._update_counts()
        self._screen_changed()

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
        if category in CATEGORY_KEYS and category != self.proxy.category:
            self._set_filter(category=category)

    @Slot()
    def clearFilters(self):
        self._search = ""
        self._set_filter(words=(), state=FILTER_ALL, category=CATEGORY_ALL)

    @Slot(int)
    def setSortMode(self, mode: int):
        """Sort rows by name, enabled first or category (kept in config.json)"""
        if mode not in SORT_MODES:
            return
        if mode != self.proxy.sort_mode:
            self.proxy.sort_mode = mode
            if cfg.application.get("overlays_sort_order") != mode:
                cfg.application["overlays_sort_order"] = mode
                cfg.save(config_type=ConfigType.CONFIG)
            self.filterChanged.emit()
        self.proxy.resort()  # same mode chosen again: states changed since placed again

    @staticmethod
    def _saved_view() -> int:
        if cfg.application.get("show_overlay_screen_view", False):
            return VIEW_SCREEN
        return VIEW_CARDS if cfg.application.get("show_overlay_previews", True) else VIEW_LIST

    @Slot(bool)
    def setGridView(self, grid: bool):
        self.setViewMode(VIEW_CARDS if grid else VIEW_LIST)

    @Slot(int)
    def setViewMode(self, mode: int):
        """Cards, list or screen view (kept in config.json)"""
        if mode not in (VIEW_CARDS, VIEW_LIST, VIEW_SCREEN) or mode == self._view:
            return
        application = cfg.application
        application["show_overlay_screen_view"] = mode == VIEW_SCREEN
        if mode != VIEW_SCREEN:
            application["show_overlay_previews"] = mode == VIEW_CARDS
        cfg.save(config_type=ConfigType.CONFIG)
        self._view = mode
        if mode != VIEW_CARDS:
            self.live.stop()
        self.viewChanged.emit()
        self._screen_changed()

    # Undo history of the page
    def _push_undo(self, kind: str, name: str, action: Callable[[], object], merge: bool = False
                   ) -> Callable[[], object]:
        """Reversible change put on the page undo history (merge: same change as the last one, kept as one step:
        arrow key presses in a row), returns the Undo of its toast (that change only, once)"""
        entry = (kind, name, action)
        if merge and self._undo and self._undo[-1][:2] == (kind, name):
            entry = self._undo[-1]
        else:
            self._undo.append(entry)
            del self._undo[:-UNDO_DEPTH]
            self.undoChanged.emit()
        return lambda: self._run_undo(entry)

    def _run_undo(self, entry: tuple[str, str, Callable[[], object]]):
        """Change of a toast undone, once (undone by Ctrl+Z already: nothing)"""
        if any(item is entry for item in self._undo):
            self._undo = [item for item in self._undo if item is not entry]
            self.undoChanged.emit()
            entry[2]()

    @Property(bool, notify=undoChanged)
    def canUndo(self) -> bool:
        return bool(self._undo)

    @Slot()
    def undo(self):
        """Ctrl+Z: last change of the page undone (switch, batch switch, move)"""
        if self._undo:
            self._run_undo(self._undo[-1])

    # Actions
    @Slot(str)
    def toggle(self, name: str):
        """Overlay switched on or off, undone by Ctrl+Z (no toast: the switch shows it)"""
        if name in self.source.index_of:
            self._control.toggle(name)
            self.update_overlay(name)
            self._push_undo("toggle", name, lambda: self.toggle_back(name))

    def toggle_back(self, name: str):
        if name in self.source.index_of:
            self._control.toggle(name)
            self.update_overlay(name)

    @Slot(str)
    def toggleFavorite(self, name: str):
        """Mark overlay as favorite or not (kept in config.json, every preset)"""
        index = self.source.index_of.get(name)
        if index is None:
            return
        self._favorites ^= {name}
        save_name_list(FAVORITES_KEY, [row.name for row in self.source.rows if row.name in self._favorites])
        self._update_row(self.source.rows[index])
        self._states_changed(False, True)

    @Slot(str)
    def openConfig(self, name: str):
        if name in self.source.index_of:
            self.live.stop()
            self._open_config(name)

    @Slot()
    def showLog(self):
        self._show_log()

    @Slot(str)
    def exportSettings(self, name: str):
        """Settings of overlays saved as package file: this overlay ticked first, else enabled ones"""
        self._export_settings([name] if name in self.source.index_of else [])

    @Slot()
    def importSettings(self):
        self._import_settings()

    @Slot()
    def enableShown(self):
        self._set_shown(True)

    @Slot()
    def disableShown(self):
        self._set_shown(False)

    def _set_shown(self, enable: bool):
        """Enable or disable shown overlays (every overlay without filter) at once, Undo offered by the page"""
        names = [name for name in self.proxy.shown_names() if bool(cfg.user.setting[name]["enable"]) != enable]
        if not names:
            return
        if len(names) == len(self.source.rows) or not self.filtered:
            if enable:
                self._control.enable_all()
            else:
                self._control.disable_all()
        else:
            self._control.set_enabled(names, enable)  # saved & on demand modules updated once
        state = "enabled" if enable else "disabled"
        text = trm(f"1 overlay {state}" if len(names) == 1 else f"{len(names)} overlays {state}")
        self.bulkToggled.emit(text)
        self._toast(text, self._push_undo("bulk", "", lambda: self.switch_back(names, enable)))
        app_signal.refresh.emit(True)  # other pages & menus follow, rows updated by refresh

    @Slot()
    def undoBulk(self):
        """Overlays switched by the last Enable / Disable put back as they were (once)"""
        entry = next((item for item in reversed(self._undo) if item[0] == "bulk"), None)
        if entry is not None:
            self._run_undo(entry)

    def switch_back(self, names: list[str], enable: bool):
        """Overlays switched by an Enable / Disable put back as they were"""
        self._control.set_enabled([name for name in names if name in self.source.index_of], not enable)
        app_signal.refresh.emit(True)

    @Slot()
    def testOnScreen(self):
        """Running overlays show a simulated race for a few seconds (saved values), again: stopped"""
        from ..overlay_test import TEST_SECONDS, overlay_test

        test = overlay_test()
        if test.running:
            test.stop()
            return
        shown = test.start()
        if shown:
            self._notify(trm(f"{shown} overlay(s) on screen show this situation for {TEST_SECONDS} s (saved values)"))
        else:
            self._notify(tr("No overlay on screen now: enable overlays, unlock them or start the game"))

    def _toast(self, text: str, undo: Callable[[], object] | None = None):
        """Message in the page toast (Undo button if undo is set), nothing without a page (tests)"""
        from PySide6.QtWidgets import QWidget

        from ..toast import show_toast

        page = self.parent()
        if isinstance(page, QWidget):
            show_toast(page, text, action_text=tr("Undo") if undo is not None else "", action=undo)

    def _notify(self, text: str):
        self.notice.emit(text)
        self._toast(text)

    # Presets
    @Slot(result=list)
    def presetChoices(self) -> list[dict]:
        """Presets of header menu, most recently changed first (read when the menu opens)"""
        loaded = self.presetName
        try:
            names = cfg.preset_files()[:PRESETS_SHOWN]
        except OSError:  # presets folder gone: nothing to list
            names = []
        return [{"name": name, "loaded": name == loaded} for name in names]

    @Slot(str)
    def loadPreset(self, name: str):
        """Load preset (whole app reloaded)"""
        if name and name != self.presetName and name in cfg.preset_files():
            cfg.set_next_to_load(f"{name}{FileExt.JSON}")
            app_signal.reload.emit(True)

    @Slot()
    def openPresets(self):
        self._open_presets()

    # Animated preview
    @Slot(str)
    def startLive(self, name: str):
        """Play overlay of hovered card on a moving simulated session (page shown, cards view)"""
        if self.page_visible and self._view == VIEW_CARDS and name in self.source.index_of:
            self.live.start(name)

    @Slot(str)
    def stopLive(self, name: str):
        self.live.stop(name)

    def _live_frame(self, url: str):
        if url != self._live_url:
            self._live_url = url
            self.liveChanged.emit()

    # Screen view
    def _screen_changed(self):
        """Screen view: layout made again (page shown only), followed while shown"""
        if self._view != VIEW_SCREEN or not self.page_visible:
            self._screen_timer.stop()
            return
        self._update_screen()
        if not self._screen_timer.isActive():
            self._screen_timer.start()

    def _poll_screen(self):
        """Overlays dragged in game or screens changed while screen view shown"""
        if self._view != VIEW_SCREEN or not self.page_visible:
            self._screen_timer.stop()
            return
        self._update_screen()

    def overlay_rects(self) -> dict[str, QRect]:
        """Running overlays shown by the filters (search & category, state left out): desktop geometry"""
        rows = self.source.rows
        rects = {}
        for name, widget in self._control.active_modules.items():
            index = self.source.index_of.get(name)
            geometry = getattr(widget, "geometry", None)
            if index is None or not callable(geometry) or not self.proxy.accepts(rows[index], use_state=False):
                continue
            rect = geometry()
            if isinstance(rect, QRect) and rect.isValid():
                rects[name] = QRect(rect)
        return rects

    def _update_screen(self):
        """Screens & running overlays at their place, page told only if changed"""
        self._read_lock()
        screens = screen_rects()
        bounds = bounds_of(rect for _, rect, _ in screens)
        rects = self.overlay_rects()
        overlaps = overlapping(rects)
        rows = self.source.rows
        overlays = []
        for name, rect in sorted(rects.items(), key=lambda item: item[1].width() * item[1].height(), reverse=True):
            row = rows[self.source.index_of[name]]
            overlays.append({
                "name": name,
                "label": row.label,
                "color": CATEGORY_COLORS[row.category],
                "preview": self.previews.role(name, OverlayModel.PreviewRole),
                "overlap": name in overlaps,
                **rect_value(rect),
            })  # biggest first: smaller ones drawn over them
        enabled_off = sum(
            1 for row in rows if row.enabled and row.name not in rects and self.proxy.accepts(row, use_state=False)
            and row.name not in self._control.active_modules)
        layout = {
            "bounds": rect_value(bounds),
            "screens": [{"name": name, "primary": primary, **rect_value(rect)} for name, rect, primary in screens],
            "overlays": overlays,
            "overlaps": len(overlaps),
            "notRunning": enabled_off,
        }
        self._screen_names = frozenset(rects)
        if layout != self._screen:
            self._screen = layout
            self.screenChanged.emit()

    def _movable(self, name: str) -> tuple[Callable[..., object], QRect] | None:
        """Move function & geometry of running overlay, None if it cannot be moved (not running, overlays locked)"""
        self._read_lock()
        if self._positions_locked:
            return None
        widget = self._control.active_modules.get(name)
        move = getattr(widget, "move_overlay", None)
        geometry = getattr(widget, "geometry", None)
        if not callable(move) or not callable(geometry):
            return None
        rect = geometry()
        return (move, QRect(rect)) if isinstance(rect, QRect) else None

    def _place(self, name: str, x: int, y: int, merge: bool):
        """Move running overlay to desktop position (kept inside screens), saved & undoable"""
        movable = self._movable(name)
        if movable is None:
            self._update_screen()
            return
        move, rect = movable
        pos = clamped_position(rect, x, y, bounds_of(rect for _, rect, _ in screen_rects()))
        if pos != rect.topLeft():
            if merge:
                move(pos, "Move", merge=True)  # presses in a row: one undo step, layout stored once they stop
            else:
                move(pos, "Move")
            label = module_label(name)
            self.overlayMoved.emit(label)
            self._toast(trm(f"Overlay moved, not saved (locked preset): {label}") if self.presetLocked
                        else trm(f"Overlay moved: {label}"), self._push_undo("move", name, self.undoMove, merge))
        self._update_screen()

    @Slot(str, int, int)
    def moveOverlay(self, name: str, x: int, y: int):
        """Move running overlay to desktop position (dragged), saved & undoable (edit mode history)"""
        self._place(name, x, y, merge=False)

    @Slot(str, int, int)
    def nudgeOverlay(self, name: str, dx: int, dy: int):
        """Move running overlay by dx, dy pixels (arrow keys), saved & undoable"""
        movable = self._movable(name)
        if movable is None:
            self._update_screen()
            return
        rect = movable[1]
        self._place(name, rect.x() + dx, rect.y() + dy, merge=True)

    @Slot(str, int, int, int, bool, result="QVariantMap")
    def snapOverlay(self, name: str, x: int, y: int, distance: int, snap: bool) -> dict:
        """Place of overlay dragged to x, y (desktop): kept on the screens, snapped to the edges & centers of other
        overlays & screens within distance pixels (snap), with the alignment lines to draw (linesX, linesY)"""
        from ...widget._layout_guide import alignment_lines

        widget = self._control.active_modules.get(name)
        geometry = getattr(widget, "geometry", None)
        if not callable(geometry):
            return {"x": x, "y": y, "linesX": [], "linesY": []}
        screens = [rect for _, rect, _ in screen_rects()]
        bounds = bounds_of(screens)
        target = QRect(geometry())
        target.moveTopLeft(clamped_position(target, x, y, bounds))
        others = []
        for other, other_widget in self._control.active_modules.items():
            other_geometry = getattr(other_widget, "geometry", None)
            if other != name and callable(other_geometry):
                rect = other_geometry()
                if isinstance(rect, QRect) and rect.isValid():
                    others.append(QRect(rect))
        if snap:
            snapped = snap_position(target, others, screens, distance)
            target.moveTopLeft(clamped_position(target, snapped.x(), snapped.y(), bounds))
        lines_x: set[int] = set()
        lines_y: set[int] = set()
        for screen in screens:
            screen_x, screen_y = alignment_lines(target, others, screen)
            lines_x |= screen_x
            lines_y |= screen_y
        return {"x": target.x(), "y": target.y(), "linesX": sorted(lines_x), "linesY": sorted(lines_y)}

    @Slot(result="QVariantMap")
    def snapSettings(self) -> dict:
        """Snapping of the screen view, as in game edit mode (application options): magnetic (Ctrl inverts it),
        distance in desktop pixels, alignment guides shown"""
        options = cfg.application
        return {
            "magnetic": bool(options.get("enable_magnetic_snap", True)),
            "distance": max(int(options.get("snap_gap", 0)), int(options.get("snap_distance", 0))),
            "guides": bool(options.get("show_layout_guides", True)),
        }

    @Slot(bool)
    def setMagneticSnap(self, magnetic: bool):
        """Snap switch of the screen view: the edit mode option (Snap button of the in-game toolbar too)"""
        from ...widget._edit_mode import toggle_application_option

        if bool(cfg.application.get("enable_magnetic_snap", True)) != magnetic:
            toggle_application_option("enable_magnetic_snap")

    @Slot()
    def undoMove(self):
        """Undo last overlay change (edit mode history: moved from screen view or in game)"""
        from ...widget._edit_mode import edit_mode

        edit_mode().undo()
        self._update_screen()

    @Slot()
    def unlockPositions(self):
        """Unlock overlays (as Unlock Overlay of the Home page & tray menu): movable again, here & in game"""
        if positions_locked():
            self.ctx.octrl.toggle.lock()
            app_signal.refresh.emit(True)  # Home page, tray menu & notification bar follow
        self._read_lock()

    @Slot()
    def unlockPreset(self):
        """Unlock loaded preset (moves saved again), confirmed"""
        filename = cfg.filename.setting
        if filename not in cfg.user.filelock:
            return
        text = trm(f"Unlock <b>{filename}</b> preset?")
        if self._ask is None:
            if self._confirm(text):
                self._unlock_preset(filename)
            return
        page = weakref.ref(self)

        def answered(chosen: bool):
            backend = page()
            if chosen and backend is not None:
                backend._unlock_preset(filename)

        self._ask(text, tr("Unlock Preset"), answered)

    @staticmethod
    def _unlock_preset(filename: str):
        if filename not in cfg.user.filelock or cfg.filename.setting != filename:
            return  # unlocked or another preset loaded meanwhile
        cfg.user.filelock.pop(filename, None)
        cfg.save(config_type=ConfigType.FILELOCK)
        app_signal.refresh.emit(True)  # preset state read again by every page (this one too)

    # Screenshot under the screen view
    def _set_background(self, image: QImage | None, rect: QRect):
        if image is None or image.isNull() or not rect.isValid():
            return
        url = STORE.put(f"{self.previews.prefix}#background", image)
        self._background = {"url": url, **rect_value(rect)}
        self.backgroundChanged.emit()

    @Slot(str)
    def captureBackground(self, screen: str):
        """Picture of a screen (the game running there) shown under the overlays of that screen; a capture wider
        than the stored size (4K screen) is scaled down in background, only the small picture is kept"""
        rect = next((rect for name, rect, _ in screen_rects() if name == screen), None)
        if rect is None:
            return
        image = self._capture_screen(screen)
        if image is None or image.isNull():
            return
        if image.width() <= BACKGROUND_MAX_WIDTH:
            self._set_background(image, rect)
            return
        rect = QRect(rect)
        self.jobs.run("scale screenshot", lambda: (shrink_background(image), rect), self._background_scaled,
                      key="background")

    def _background_scaled(self, result: tuple[QImage, QRect]):
        self._set_background(*result)

    @Slot()
    def loadBackground(self):
        """Screenshot file shown under the overlays of the screen it was taken on (else the main screen): decoded
        & scaled down in background (UI never waits for a big PNG), only the small picture is kept"""
        filename = self._pick_screenshot()
        if not filename:
            return
        self.jobs.run("read screenshot", partial(read_background, filename), self._background_read, key="background")

    def _background_read(self, result: tuple[QSize, QImage]):
        size, image = result
        if image.isNull():
            self._notify(tr("Unable to load image."))
            return
        screens = screen_rects()
        primary = next((rect for _, rect, main in screens if main), screens[0][1] if screens else QRect())
        self._set_background(image, screen_for_image(size, screen_scales(), primary))

    @Slot()
    def clearBackground(self):
        if self._background:
            STORE.discard(f"{self.previews.prefix}#background")
            self._background = {}
            self.backgroundChanged.emit()

    def close(self):
        """Page closed (older name of release)"""
        self.release()

    def release_resources(self):
        from ..widget_preview import set_showing

        self.live.stop()
        self.previews.stop()
        set_showing(self, False)
