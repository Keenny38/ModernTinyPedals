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
VR overlay

Visible overlay widgets keep their desktop layout (the canvas: bounding box of all widgets) in VR:
- OpenXR layer (Windows): only the visible parts of the canvas, one tile per group of nearby widgets, packed
  in an atlas written to shared memory, drawn as one quad per tile in every OpenXR game on any runtime
  (SteamVR, Meta / Air Link, Virtual Desktop, WMR, Pimax, Varjo...) by the app's own OpenXR API layer
  (native/openxr_layer, bundled in the release, see vr_shared.py). Nothing to install. Widgets spread over
  the screen cost no bandwidth nor GPU copy for the empty space between them.
- SteamVR overlay: OpenVR games (rFactor 2, Le Mans Ultimate in SteamVR mode...). Requires the "openvr"
  package (bundled in the release, from source: pip install openvr); created once SteamVR runs (never
  starts SteamVR), hidden while the OpenXR layer draws the overlay (OpenXR game on SteamVR runtime).
  Shows the whole canvas composed into one image (sent at most ~15 times per second, only when changed). Both
  placed the same way: fixed in seated space or attached to headset.
Updates slowed (1 s) while overlays are paused (not driving) & some still visible, stopped when none is (OpenXR layer
heartbeat kept); back to the update interval when overlays resume, show, hide or are edited.
- VR mirror window: one desktop window showing the composed image, for window capture overlays such as
  OpenKneeboard, OVR Toolkit, XSOverlay or Desktop+.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import threading
import weakref
import zlib
from array import array
from collections.abc import Callable
from contextlib import suppress
from typing import NamedTuple

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from . import app_signal, overlay_signal, realtime_state, vr_shared
from .const_file import ConfigType
from .setting import cfg

logger = logging.getLogger(__name__)

MAX_PIXELS = 1024 * 1024  # setOverlayRaw data size limit, image is scaled down above this
MIRROR_TITLE = "NeoPedal VR"  # window title to select in window capture apps
STEAMVR_PROCESSES = ("vrserver.exe", "vrserver")  # SteamVR server (Windows, Linux)
STEAMVR_RETRY_MS = 5000  # SteamVR started after app: overlay created within this delay
STEAMVR_IDLE_RETRY_MS = 60000  # same while overlays are paused (not driving): checked again at once on resume
STEAMVR_MIN_INTERVAL_MS = 66  # SteamVR overlay image (whole canvas) sent at most ~15 times per second
OPENXR_MIN_INTERVAL_MS = 66  # OpenXR layer image written at most ~15 times per second (copied in game frame)
PAUSED_GRACE_MS = 1000  # overlays paused: updates kept this long (last paint, fade out), then slowed or stopped
PAUSED_INTERVAL_MS = 1000  # overlays paused, some still visible or SteamVR connected (quit events): update interval
OPENXR_MAX_TILES = 8  # tiles (quad layers) at most, room left for the game's layers (runtimes allow 16 or more)
OPENXR_TILE_GAP = 32  # widgets closer than this (pixels) share a tile
HEARTBEAT_INTERVAL_MS = 500  # app heartbeat for the OpenXR layer, whatever the update interval (layer timeout 2 s)
# Layer of a game that drew the overlay, tiles shown again (auto hide) or session restarted: SteamVR overlay kept
# hidden at most this long while its frames resume (no ~50 ms double image), shown if the layer draws nothing
OPENXR_RESUME_GRACE_MS = 3000


class XrLayerProcess:
    """Layer status of one OpenXR game process: several games may run the layer, each writing the single
    status block of the shared memory in turn (app sees one of them per tick)"""

    __slots__ = ("status", "shown_at", "wait_from", "drew_before_hide", "logged")

    def __init__(self, status: vr_shared.LayerStatus):
        self.status = status
        self.shown_at: int | None = None  # tick (ms) when frames_shown last grew
        self.wait_from: int | None = None  # tick (ms) from which frames are expected again (grace window)
        self.drew_before_hide = False  # drew the overlay when tiles were last hidden
        self.logged: tuple | None = None  # (state, graphics API) last logged, None once closed

    def update(self, status: vr_shared.LayerStatus, now: int):
        """New status of this process: frames growth recorded (lower count: new session or mixed read of two
        writers, new base only)"""
        if status.frames_shown > self.status.frames_shown and status.heartbeat_ms != 0:
            self.shown_at = now
            self.wait_from = None
        self.status = status

    def drew_recently(self, now: int, within: int) -> bool:
        return self.shown_at is not None and 0 <= now - self.shown_at <= within

    def drawing(self, now: int, tiles_visible: bool) -> bool:
        """Layer shows the overlay: frames shown within LAYER_TIMEOUT_MS, or drew before tiles were hidden
        (nothing to draw) and frames resuming within OPENXR_RESUME_GRACE_MS. ACTIVE layer may still submit
        no quad (no layer slot left, image refused): not drawing then."""
        if not self.status.drawing(now):
            return False
        if self.drew_recently(now, vr_shared.LAYER_TIMEOUT_MS):
            return True
        if not tiles_visible:
            return self.drew_before_hide
        return self.wait_from is not None and 0 <= now - self.wait_from <= OPENXR_RESUME_GRACE_MS


class MirrorWindow(QWidget):
    """Desktop window showing composed overlay image, captured by VR window overlay apps

    Kept while overlays reload (capture apps follow this window), position remembered.
    """

    def __init__(self, background: str, on_closed: Callable[[], None]):
        super().__init__(None, Qt.WindowType.Window)
        self.on_closed = on_closed
        self.setWindowTitle(MIRROR_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.background = QColor("#000000")
        self.set_background(background)
        self.image: QImage | None = None  # composed image, drawn as is (updated in place by its composer)
        self.resize(640, 360)
        self.restore_position()
        # Position saved once moving stops
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self.save_position)

    def set_background(self, background: str):
        """Background color, black if invalid"""
        self.background = QColor(background) if QColor.isValidColorName(background) else QColor("#000000")
        self.update()

    def restore_position(self):
        """Position of last time, if still on a screen"""
        setting = cfg.user.config["vr_overlay"]
        try:
            position = QPoint(int(setting["mirror_position_x"]), int(setting["mirror_position_y"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        if QGuiApplication.screenAt(position) is not None:  # never set (default), or screen gone
            self.move(position)

    def save_position(self):
        """Remember window position (global config)"""
        if not self.isVisible() or self.isMinimized():
            return
        setting = cfg.user.config["vr_overlay"]
        position = self.pos()
        if (setting.get("mirror_position_x"), setting.get("mirror_position_y")) != (position.x(), position.y()):
            setting["mirror_position_x"] = position.x()
            setting["mirror_position_y"] = position.y()
            cfg.save(config_type=ConfigType.CONFIG)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible():
            self._save_timer.start()

    def set_image(self, image: QImage | None, dirty: QRegion | None = None):
        """Show image (kept & drawn in paint events, no pixmap copy), empty (background only) if None.

        Args:
            dirty: part of the same image changed since last call (only that part painted again), None: whole.
        """
        partial = image is self.image
        self.image = image
        if image is not None and not image.isNull() and self.size() != image.size():
            self.resize(image.size())
            partial = False
        if partial and dirty is not None:
            self.update(dirty)
        else:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = event.rect()
        painter.fillRect(rect, self.background)
        image = self.image
        if image is not None:
            part = rect.intersected(image.rect())
            if not part.isEmpty():
                painter.drawImage(part.topLeft(), image, part)

    def closeEvent(self, event):
        """Closing window turns mirror off until next reload, so window is not shown again unexpectedly"""
        self._save_timer.stop()
        self.save_position()
        cfg.user.config["vr_overlay"]["enable_vr_mirror_window"] = False
        cfg.save(config_type=ConfigType.CONFIG)
        self.on_closed()
        super().closeEvent(event)


def window_source(widget: QWidget) -> tuple[QImage, QRect] | None:
    """Overlay window as last painted: image & its part showing the window (device pixels). Backing store itself
    (no copy, no repaint) once window painted (paint serial counted, see widget._base.PaintCounter), else window
    rendered again (grab). Backing store only valid until the window paints again: drawn at once."""
    if getattr(widget, "paint_serial", None) is not None:
        store = widget.backingStore()
        device = store.paintDevice() if store is not None else None
        if isinstance(device, QImage) and not device.isNull():
            ratio = device.devicePixelRatio()
            width, height = round(widget.width() * ratio), round(widget.height() * ratio)
            if 0 < width <= device.width() and 0 < height <= device.height():
                return device, QRect(0, 0, width, height)
    pixmap = widget.grab()
    if pixmap.isNull():
        return None
    image = pixmap.toImage()
    return image, image.rect()


def draw_window(painter: QPainter, widget: QWidget, target: QRect):
    """Window as last painted drawn into target rect (painter coordinates), with window opacity. Scaled to target
    size first when it differs (pixels averaged as QImage.scaled: even thin lines & text, unlike bilinear)."""
    source = window_source(widget)
    if source is None:
        return
    image, rect = source
    if rect.size() != target.size():
        if rect != image.rect():  # window part of the backing store (top left), read in place
            image = QImage(image.constBits(), rect.width(), rect.height(), image.bytesPerLine(), image.format())
        image = image.scaled(target.width(), target.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        rect = image.rect()
    painter.setOpacity(widget.windowOpacity())
    painter.drawImage(target, image, rect)


def compose_key(widgets: list) -> tuple | None:
    """State of overlay windows (paint serial, opacity): composed image unchanged while same,
    None if a window is not counted (always composed again)"""
    key = []
    for widget in widgets:
        serial = getattr(widget, "paint_serial", None)
        if serial is None:
            return None
        key.append((id(widget), serial, widget.windowOpacity()))
    return tuple(key)


def canvas_size(width: int, height: int) -> tuple[int, int]:
    """Size of the composed image of a canvas: scaled down to MAX_PIXELS keeping aspect (as QImage.scaled)"""
    pixels = width * height
    if pixels <= MAX_PIXELS:
        return width, height
    scale = (MAX_PIXELS / pixels) ** 0.5
    size = QSize(width, height).scaled(
        max(int(width * scale), 1), max(int(height * scale), 1), Qt.AspectRatioMode.KeepAspectRatio)
    return max(size.width(), 1), max(size.height(), 1)


class RowChecksum:
    """Checksum of an image's pixels kept per band of rows: only bands drawn since the last value read again
    (change detection of an image updated in place, same value for same pixels & size)"""

    BAND_ROWS = 16

    def __init__(self):
        self._bands: list[int] = []  # crc32 of each band of rows
        self._shape: tuple[int, int, int] | None = None  # width, height & bytes per line of the image read
        self._stale: set[int] = set()  # bands drawn since

    def reset(self):
        """Whole image read next time"""
        self._shape = None

    def drawn(self, top: int, bottom: int):
        """Rows top to bottom (excluded) drawn"""
        self._stale.update(range(max(top, 0) // self.BAND_ROWS, -(-bottom // self.BAND_ROWS)))

    def value(self, image: QImage, seed: int) -> int:
        rows, height, stride = self.BAND_ROWS, image.height(), image.bytesPerLine()
        count = -(-height // rows)
        shape = (image.width(), height, stride)
        if shape != self._shape:
            self._shape, self._bands, self._stale = shape, [0] * count, set(range(count))
        if self._stale:
            view = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
            for band in self._stale:
                if band < count:
                    self._bands[band] = zlib.crc32(view[band * rows * stride:min(band * rows + rows, height) * stride])
            self._stale = set()
        return zlib.crc32(array("I", self._bands).tobytes(), seed)


class CanvasComposer:
    """Visible overlay windows (desktop layout) composed straight at the size sent (canvas_size) into one RGBA
    image kept between updates: only windows painted since last time drawn again, whole image when windows,
    their place, size or opacity change. Checksum read only where drawn (RowChecksum)."""

    def __init__(self):
        self.image: QImage | None = None
        self.dirty: QRegion | None = None  # part of image drawn by last compose, None if unchanged
        self.version = 0  # counts images drawn (each compose drawing something, each reset)
        self._layout: tuple | None = None  # canvas & windows drawn in image
        self._serials: list[int | None] = []  # paint serial of each window when drawn
        self._checksum = RowChecksum()

    def reset(self):
        """Image released, next one drawn whole"""
        self.image = self._layout = self.dirty = None
        self._serials = []
        self._checksum.reset()
        self.version += 1

    def checksum(self) -> int | None:
        """Checksum of image pixels & size (None if no image), only rows drawn since last call read"""
        image = self.image
        if image is None:
            return None
        return self._checksum.value(image, image.width() << 16 | image.height())

    def compose(self, widgets: list) -> QImage | None:
        """Image of visible widgets (updated in place, valid until next call), None if nothing visible.
        Part drawn in dirty."""
        visible = [widget for widget in widgets if widget.isVisible() and widget.width() > 0]
        if not visible:
            self.reset()
            return None
        geometries = [widget.frameGeometry() for widget in visible]
        bounds = QRect()
        for geometry in geometries:
            bounds = bounds.united(geometry)
        width, height = canvas_size(bounds.width(), bounds.height())
        layout = (bounds.getRect(), width, height, tuple(  # weak: new window never taken for a closed one
            (weakref.ref(widget), geometry.topLeft(), widget.size(), widget.windowOpacity())
            for widget, geometry in zip(visible, geometries)))
        serials = [getattr(widget, "paint_serial", None) for widget in visible]
        image = self.image
        clip = None
        if image is not None and layout == self._layout:
            clip = QRegion()
            for index, (serial, last) in enumerate(zip(serials, self._serials)):
                if serial is None or serial != last:  # painted since (or not counted)
                    target = self.target(geometries[index], visible[index], bounds, image)
                    clip += target
                    self._checksum.drawn(target.top(), target.bottom() + 1)
            if clip.isEmpty():
                self.dirty = None
                return image
        elif image is None or (image.width(), image.height()) != (width, height):
            image = self.image = QImage(width, height, QImage.Format.Format_RGBA8888)
        self._layout, self._serials = layout, serials
        self.version += 1
        if clip is None:
            image.fill(Qt.GlobalColor.transparent)
            self.dirty = QRegion(image.rect())
            self._checksum.drawn(0, image.height())
        else:  # its rows marked drawn above
            self.dirty = clip.intersected(image.rect())
        painter = QPainter(image)
        if clip is not None:  # changed windows' rects cleared, all windows there drawn again in order
            painter.setClipRegion(clip)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(clip.boundingRect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for widget, geometry in zip(visible, geometries):
            target = self.target(geometry, widget, bounds, image)
            if clip is None or clip.intersects(target):
                draw_window(painter, widget, target)
        painter.end()
        return image

    @staticmethod
    def target(geometry: QRect, widget: QWidget, bounds: QRect, image: QImage) -> QRect:
        """Rect of a window in the image (canvas scaled to image size), edges rounded to pixels"""
        scale_x, scale_y = image.width() / bounds.width(), image.height() / bounds.height()
        x, y = geometry.x() - bounds.x(), geometry.y() - bounds.y()
        left, top = round(x * scale_x), round(y * scale_y)
        return QRect(left, top, max(round((x + widget.width()) * scale_x) - left, 1),
                     max(round((y + widget.height()) * scale_y) - top, 1))


_composer = CanvasComposer()  # SteamVR overlay & mirror window image (one VR overlay control per app)


def compose_widgets(widgets: list) -> QImage | None:
    """Compose visible overlay widgets into one RGBA image, keeping desktop layout, scaled down to MAX_PIXELS.
    Same image updated in place by the next call (copy it to keep it)."""
    return _composer.compose(widgets)


def _alpha_rows(image: QImage) -> tuple[bytes, int]:
    """Alpha bytes of image, row after row (no padding), & row width"""
    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    width, stride = alpha.width(), alpha.bytesPerLine()
    bits = memoryview(alpha.constBits())[:alpha.sizeInBytes()]  # type: ignore[arg-type]
    if stride == width:
        return bits.tobytes(), width
    return b"".join(bits[row * stride:row * stride + width] for row in range(alpha.height())), width


def content_rect(image: QImage) -> QRect:
    """Bounding rect of visible (not fully transparent) pixels, empty if none (rows & columns found by stripping
    zero alpha bytes, no rotated copy)"""
    alpha, width = _alpha_rows(image)
    first = len(alpha) - len(alpha.lstrip(b"\0"))
    if width == 0 or first == len(alpha):
        return QRect()
    last = len(alpha.rstrip(b"\0")) - 1
    top, bottom = first // width, last // width
    left, right = width, -1
    for row in range(top, bottom + 1):
        line = alpha[row * width:(row + 1) * width]
        start = width - len(line.lstrip(b"\0"))
        if start == width:
            continue
        left = min(left, start)
        right = max(right, len(line.rstrip(b"\0")) - 1)
        if left == 0 and right == width - 1:
            break
    return QRect(left, top, right - left + 1, bottom - top + 1)


class TileFrame(NamedTuple):
    """Visible parts of the canvas for the OpenXR layer: atlas image (RGBA8888) & its tiles"""

    atlas: QImage
    tiles: tuple[vr_shared.Tile, ...]
    canvas: tuple[int, int]  # width, height (same scale as atlas)
    checksum: int
    dirty: tuple[int, int, int, int] | None = None  # atlas rect drawn since the previous frame, None: whole


def compose_group(widgets: list, origin: QPoint, size: tuple[int, int]) -> QImage:
    """Widgets (stacking order kept) composed into a transparent image of size, origin at its top left"""
    image = QImage(size[0], size[1], QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    for widget in widgets:
        draw_window(painter, widget, QRect(widget.frameGeometry().topLeft() - origin, widget.size()))
    painter.end()
    return image


def image_part(image: QImage, rect: QRect) -> QImage:
    """Part of an image read in place (no copy), valid while image kept & unchanged"""
    if rect == image.rect():
        return image
    view = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
    offset = rect.y() * image.bytesPerLine() + rect.x() * image.depth() // 8
    return QImage(view[offset:], rect.width(), rect.height(), image.bytesPerLine(), image.format())


class TileGroup:
    """Image of one group of nearby widgets (one tile), kept between updates. Visible part found per band of
    rows, only bands drawn since read again."""

    __slots__ = ("key", "image", "serials", "bands", "rect", "version")

    BAND_ROWS = 16

    def __init__(self, key: tuple, image: QImage, serials: list[int | None]):
        self.key = key  # image size, windows drawn (place in image, opacity)
        self.image = image
        self.serials = serials  # paint serial of each window when drawn
        self.bands: list[tuple[int, int, int, int] | None] = []  # visible part of each band (left, top, right, bottom)
        self.rect = QRect()  # visible part (content_rect)
        self.version = 0  # counts redraws
        self.drawn(0, image.height())

    def drawn(self, top: int, bottom: int):
        """Rows top to bottom (excluded) drawn: visible part of their bands found again"""
        image, rows = self.image, self.BAND_ROWS
        height = image.height() if not image.isNull() else 0
        count = -(-height // rows)
        if len(self.bands) != count:
            self.bands = [None] * count
        for band in range(max(top, 0) // rows, min(-(-bottom // rows), count)):
            band_top = band * rows
            rect = content_rect(image_part(image, QRect(0, band_top, image.width(), min(rows, height - band_top))))
            self.bands[band] = None if rect.isEmpty() else (
                rect.left(), band_top + rect.top(), rect.right(), band_top + rect.bottom())
        boxes = [box for box in self.bands if box is not None]
        if not boxes:
            self.rect = QRect()
            return
        left, right = min(box[0] for box in boxes), max(box[2] for box in boxes)
        self.rect = QRect(left, boxes[0][1], right - left + 1, boxes[-1][3] - boxes[0][1] + 1)


class TileComposer:
    """Visible overlay widgets as tiles of the canvas for the OpenXR layer, kept between updates (as
    CanvasComposer): groups computed again only when windows move or resize, each group image only drawn again
    where its windows painted since, atlas kept while packed the same with only changed tiles drawn in it,
    checksum read only where drawn"""

    def __init__(self):
        self._clusters: tuple[tuple, list[list[int]]] | None = None  # groups (cluster_rects) & their input
        self._groups: list[TileGroup] = []
        self._atlas: QImage | None = None
        self._drawn: list[tuple] = []  # what each atlas tile shows: place & size, group, its version & part
        self._checksum = RowChecksum()
        self._frame: TileFrame | None = None

    def reset(self):
        """Images released, next ones drawn whole"""
        self._clusters = self._atlas = self._frame = None
        self._groups = []
        self._drawn = []
        self._checksum.reset()

    def compose(self, widgets: list, max_tiles: int, gap: int) -> TileFrame | None:
        """Tiles of visible widgets (atlas updated in place, valid until next call), None if nothing visible"""
        visible = [widget for widget in widgets if widget.isVisible() and widget.width() > 0]
        if not visible:
            self.reset()
            return None
        geometries = [widget.frameGeometry() for widget in visible]
        bounds = QRect()
        for geometry in geometries:
            bounds = bounds.united(geometry)
        rects = tuple((rect.x() - bounds.x(), rect.y() - bounds.y(), rect.width(), rect.height())
                      for rect in geometries)
        cluster_key = (rects, gap, min(max_tiles, vr_shared.MAX_TILES))
        if self._clusters is None or self._clusters[0] != cluster_key:
            self._clusters = cluster_key, vr_shared.cluster_rects(rects, gap, cluster_key[2])
        groups = []
        parts: list[tuple[TileGroup, int, int]] = []  # group, canvas x & y of its visible part
        for members in self._clusters[1]:
            box = rects[members[0]]
            for index in members[1:]:
                box = vr_shared.union_rect(box, rects[index])
            group = self.__group([visible[index] for index in members], [geometries[index] for index in members],
                                 bounds.topLeft() + QPoint(box[0], box[1]), (box[2], box[3]))
            groups.append(group)
            if not group.rect.isEmpty():  # transparent margins not sent
                parts.append((group, box[0] + group.rect.x(), box[1] + group.rect.y()))
        self._groups = groups
        if not parts:
            return None
        # Scale: atlas within shared memory (MAX_PIXELS) & largest image, canvas within layer limit
        area = sum(group.rect.width() * group.rect.height() for group, _, _ in parts)
        scale = min(1.0, math.sqrt(MAX_PIXELS / area), vr_shared.MAX_CANVAS / max(bounds.width(), bounds.height()))
        while True:
            sizes = [(max(round(group.rect.width() * scale), 1), max(round(group.rect.height() * scale), 1))
                     for group, _, _ in parts]
            packed = vr_shared.pack_atlas(sizes)
            if packed is not None and packed[1] * packed[2] * 4 <= vr_shared.MAX_IMAGE_BYTES:
                break
            scale *= 0.9  # rows waste space: smaller until it fits (1 pixel tiles always do)
        positions, atlas_width, atlas_height = packed
        canvas = (min(max(round(bounds.width() * scale), 1), vr_shared.MAX_CANVAS),
                  min(max(round(bounds.height() * scale), 1), vr_shared.MAX_CANVAS))
        tiles = []
        drawn = []
        for (group, x, y), (width, height), (atlas_x, atlas_y) in zip(parts, sizes, positions):
            canvas_x = min(round(x * scale), canvas[0] - width)  # rounding never moves a tile off canvas
            canvas_y = min(round(y * scale), canvas[1] - height)
            tiles.append(vr_shared.Tile(atlas_x, atlas_y, width, height, max(canvas_x, 0), max(canvas_y, 0)))
            drawn.append((atlas_x, atlas_y, width, height, group, group.version, group.rect.getRect()))
        atlas = self._atlas
        dirty: vr_shared.Rect | None
        if (atlas is None or (atlas.width(), atlas.height()) != (atlas_width, atlas_height)
                or [item[:4] for item in drawn] != [item[:4] for item in self._drawn]):
            if atlas is None or (atlas.width(), atlas.height()) != (atlas_width, atlas_height):
                atlas = self._atlas = QImage(atlas_width, atlas_height, QImage.Format.Format_RGBA8888)
            atlas.fill(Qt.GlobalColor.transparent)  # padding between tiles transparent
            self._checksum.drawn(0, atlas_height)
            changed = list(range(len(drawn)))
            dirty = None
        else:  # same places: tiles drawn again where their group changed (drawn whole, source mode)
            changed = [index for index, (new, old) in enumerate(zip(drawn, self._drawn)) if new != old]
            dirty = (0, 0, 0, 0)  # atlas rect of changed tiles (empty: tiles moved on canvas only)
            for index in changed:
                tile_x, tile_y, tile_width, tile_height = drawn[index][:4]
                part = (tile_x, tile_y, tile_width, tile_height)
                dirty = part if dirty[2] == 0 else vr_shared.union_rect(dirty, part)
        self._drawn = drawn
        frame = self._frame
        if not changed and frame is not None and frame.tiles == tuple(tiles) and frame.canvas == canvas:
            return frame
        if changed:
            painter = QPainter(atlas)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            for index in changed:
                atlas_x, atlas_y, width, height, group, _, _ = drawn[index]
                image, rect = group.image, group.rect
                if (width, height) != (rect.width(), rect.height()):  # visible part scaled (read in place)
                    painter.drawImage(atlas_x, atlas_y, image_part(image, rect).scaled(
                        width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
                else:  # visible part drawn from group image (no copy)
                    painter.drawImage(QPoint(atlas_x, atlas_y), image, rect)
                self._checksum.drawn(atlas_y, atlas_y + height)
            painter.end()
        layout = repr((tiles, canvas)).encode()
        frame = self._frame = TileFrame(atlas, tuple(tiles), canvas, self._checksum.value(atlas, zlib.crc32(layout)),
                                        dirty)
        return frame

    def __group(self, widgets: list, geometries: list[QRect], origin: QPoint, size: tuple[int, int]) -> TileGroup:
        """Image of a group, drawn again where its windows painted since (whole if windows changed)"""
        targets = [QRect(geometry.topLeft() - origin, widget.size()) for widget, geometry in zip(widgets, geometries)]
        key = (size, tuple((weakref.ref(widget), target.getRect(), widget.windowOpacity())  # weak: as CanvasComposer
                           for widget, target in zip(widgets, targets)))
        serials = [getattr(widget, "paint_serial", None) for widget in widgets]
        group = next((group for group in self._groups if group.key == key), None)
        if group is None:
            return TileGroup(key, compose_group(widgets, origin, size), serials)
        clip = QRegion()
        for target, serial, last in zip(targets, serials, group.serials):
            if serial is None or serial != last:  # painted since (or not counted)
                clip += target
        group.serials = serials
        if clip.isEmpty():
            return group
        painter = QPainter(group.image)  # changed windows' rects cleared, all windows there drawn again in order
        painter.setClipRegion(clip)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(clip.boundingRect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for widget, target in zip(widgets, targets):
            if clip.intersects(target):
                draw_window(painter, widget, target)
        painter.end()
        bounds = clip.boundingRect()
        group.drawn(bounds.top(), bounds.bottom() + 1)
        group.version += 1
        return group


_tile_composer = TileComposer()  # OpenXR layer tiles


def compose_tiles(widgets: list, max_tiles: int = OPENXR_MAX_TILES, gap: int = OPENXR_TILE_GAP) -> TileFrame | None:
    """Visible overlay widgets as tiles of the canvas (bounding box of all widgets, desktop layout):
    one tile per group of nearby widgets, cropped to its visible pixels, packed in an atlas.
    Scaled down (canvas too) when the atlas is bigger than the shared memory allows.
    Same atlas updated in place by the next call (TileComposer).

    Returns:
        None if nothing visible.
    """
    return _tile_composer.compose(widgets, max_tiles, gap)


class ImageFrame(NamedTuple):
    """Raw RGBA frame for SteamVR: buffer over the image pixels (valid while image kept & unchanged)"""

    buffer: ctypes.Array
    width: int
    height: int
    checksum: int
    image: QImage | None = None


def image_checksum(image: QImage) -> int:
    """Checksum of image pixels & size (change detection, no copy)"""
    view = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
    return zlib.crc32(view, image.width() << 16 | image.height())


def image_frame(image: QImage, checksum: int | None = None) -> ImageFrame:
    """ctypes buffer over image pixels (no copy, image detached first if shared), with checksum for change
    detection. Same bytes & size (sizeInBytes) as the copy made before."""
    if checksum is None:
        checksum = image_checksum(image)
    size = image.sizeInBytes()
    buffer = (ctypes.c_ubyte * size).from_buffer(memoryview(image.bits()))  # type: ignore[arg-type]
    return ImageFrame(buffer, image.width(), image.height(), checksum, image)


def overlay_transform(distance: float, vertical: float, horizontal: float) -> list[list[float]]:
    """3x4 transform matrix (rows), overlay facing viewer at given offset (meters)"""
    return [
        [1.0, 0.0, 0.0, horizontal],
        [0.0, 1.0, 0.0, vertical],
        [0.0, 0.0, 1.0, -distance],
    ]


def fit_image(image: QImage, max_dimension: int) -> QImage:
    """Image scaled down (keeping aspect) when wider or taller than max_dimension"""
    if image.width() <= max_dimension and image.height() <= max_dimension:
        return image
    return image.scaled(
        min(image.width(), max_dimension), min(image.height(), max_dimension),
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def process_names_windows() -> set[str] | None:
    """Lower case executable names of all processes from one Toolhelp snapshot (Windows: a few ms, no handle
    opened per process as psutil does), None if unavailable"""
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return None
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        names = set()
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            names.add(entry.szExeFile.lower())
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return names
    finally:
        kernel32.CloseHandle(snapshot)


def steamvr_running() -> bool:
    """SteamVR server process running (openvr.init would start SteamVR otherwise)"""
    try:
        names = process_names_windows()
        if names is not None:
            return any(name in names for name in STEAMVR_PROCESSES)
    except Exception:  # ctypes error: psutil below
        logger.debug("VR overlay: process snapshot failed", exc_info=True)
    try:
        import psutil

        for process in psutil.process_iter(["name"]):
            name = (process.info.get("name") or "").lower()
            if name in STEAMVR_PROCESSES:
                return True
    except Exception:  # psutil error: assume not running (retried later)
        logger.debug("VR overlay: SteamVR process check failed", exc_info=True)
    return False


class SteamVRCheck:
    """steamvr_running() in a background thread (process scan takes tens of ms), result read on a later tick"""

    def __init__(self):
        self.running = False
        self._thread = threading.Thread(target=self.__run, daemon=True, name="SteamVR check")
        self._thread.start()

    def __run(self):
        self.running = steamvr_running()

    def done(self) -> bool:
        return not self._thread.is_alive()


STEAMVR_START_WAIT_S = 0.02  # GUI waits this at most for a SteamVR start (quick start adopted at once, else later)


def place_overlay(openvr, overlay, handle, setting: dict) -> None:
    """Set SteamVR overlay position from "vr_overlay" setting"""
    matrix = openvr.HmdMatrix34_t()
    rows = overlay_transform(
        float(setting["distance_meters"]),
        float(setting["vertical_offset_meters"]),
        float(setting["horizontal_offset_meters"]),
    )
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            matrix.m[row_index][column_index] = value
    if setting["enable_attach_to_headset"]:
        overlay.setOverlayTransformTrackedDeviceRelative(handle, openvr.k_unTrackedDeviceIndex_Hmd, matrix)
    else:
        overlay.setOverlayTransformAbsolute(handle, openvr.TrackingUniverseSeated, matrix)


def release_openvr(openvr, overlay, handle) -> None:
    """Destroy SteamVR overlay & shut openvr down (SteamVR may be closed already)"""
    if overlay is not None and handle is not None:
        try:
            overlay.destroyOverlay(handle)
        except Exception:  # SteamVR already closed
            logger.debug("VR overlay: destroy failed", exc_info=True)
    if openvr is not None:
        try:
            openvr.shutdown()
        except Exception:
            logger.debug("VR overlay: shutdown failed", exc_info=True)


class SteamVRStart:
    """openvr.init() & overlay creation in a background thread: IPC with vrserver, hundreds of ms (up to its
    timeout while SteamVR closes), never on the GUI thread. Result (openvr module, system, overlay, handle, shown)
    adopted by the GUI thread with take(), released by the thread itself if dropped (disable) before."""

    def __init__(self, setting: dict):
        self._setting = dict(setting)
        self.error: Exception | None = None
        self._result: tuple | None = None
        self._dropped = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self.__run, daemon=True, name="SteamVR start")
        self._thread.start()

    def __run(self):
        import openvr

        overlay = handle = started = None
        try:
            system = openvr.init(openvr.VRApplication_Overlay)
            started = openvr  # shut down on a later failure (never after a failed init)
            overlay = openvr.IVROverlay()
            handle = overlay.createOverlay("neopedal.overlay", "NeoPedal")
            overlay.setOverlayWidthInMeters(handle, max(float(self._setting["overlay_width_meters"]), 0.05))
            place_overlay(openvr, overlay, handle, self._setting)
            overlay.showOverlay(handle)
        except Exception as error:  # SteamVR closing, or openvr error: tried again later
            logger.debug("VR overlay: SteamVR init failed", exc_info=True)
            self.error = error
            release_openvr(started, overlay, handle)
            return
        with self._lock:
            if self._dropped:  # disabled meanwhile: nothing to adopt
                release_openvr(openvr, overlay, handle)
                return
            self._result = (openvr, system, overlay, handle)

    def done(self) -> bool:
        return not self._thread.is_alive()

    def wait(self, timeout: float) -> bool:
        """Wait for the start up to timeout seconds, True if done"""
        self._thread.join(timeout)
        return self.done()

    def take(self) -> tuple | None:
        """Result (once), None if failed (see error) or dropped"""
        with self._lock:
            result, self._result = self._result, None
        return result

    def drop(self):
        """Result never adopted: released now or by the thread once made"""
        with self._lock:
            self._dropped = True
            result, self._result = self._result, None
        if result is not None:
            release_openvr(result[0], result[2], result[3])


PLACEMENT_LIMIT = 100.0  # meters: largest width, distance & offsets the OpenXR layer draws (shared_frame.cpp)


def placement_meters(value: float, default: float, minimum: float = -PLACEMENT_LIMIT) -> float:
    """Placement value within what the OpenXR layer draws (else every frame refused, nothing shown)"""
    number = float(value)
    if not math.isfinite(number):
        number = default
    return min(max(number, minimum), PLACEMENT_LIMIT)


def placement_from(setting: dict) -> vr_shared.Placement:
    """Overlay placement from "vr_overlay" setting"""
    return vr_shared.Placement(
        placement_meters(setting["overlay_width_meters"], 0.8, 0.05),
        placement_meters(setting["distance_meters"], 1.0),
        placement_meters(setting["vertical_offset_meters"], -0.2),
        placement_meters(setting["horizontal_offset_meters"], 0.0),
        bool(setting["enable_attach_to_headset"]),
    )


class VROverlay(QObject):
    """VR overlay control (OpenXR layer, SteamVR overlay, mirror window), runs in main (GUI) thread"""

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_overlay)
        self._heartbeat_timer = QTimer(self)  # app alive for the OpenXR layer (update interval may be longer)
        self._heartbeat_timer.setInterval(HEARTBEAT_INTERVAL_MS)
        self._heartbeat_timer.timeout.connect(self.__heartbeat)
        # SteamVR (OpenVR)
        self._openvr = None
        self._system = None  # openvr IVRSystem: SteamVR events (quit)
        self._overlay = None
        self._handle = None
        self._buffer = None  # pixels sent last (ctypes buffer over _buffer_image), kept until next frame
        self._buffer_image: QImage | None = None
        self._checksum: int | None = None
        self._sent_at: int | None = None  # tick (ms) of last image sent to SteamVR (STEAMVR_MIN_INTERVAL_MS)
        self._steamvr_dirty = False  # newer image held back by the SteamVR rate limit (sent on a later tick)
        self._interval = 50  # update interval (ms) while overlays are shown
        self._paused_since: int | None = None  # tick (ms) overlays were seen paused (not shown, not editing)
        self._visible = False
        self._has_image = False  # last composed image not empty (SteamVR overlay shown unless hidden for OpenXR)
        self._steamvr_wanted = False  # openvr available, waiting for SteamVR or running
        self._steamvr_retry_at = 0  # tick (ms) of next SteamVR process check
        self._steamvr_check: SteamVRCheck | None = None  # process check running in background
        self._steamvr_start: SteamVRStart | None = None  # openvr init & overlay creation running in background
        self._steamvr_start_report = False  # report a failure of that start as error
        self._steamvr_report = False  # first check after enable: report problems as error
        self._steamvr_error_shown = False
        self._steamvr_quitting = False  # SteamVR asked to quit: never connected again until its process is gone
        self._hidden_for_openxr = False  # SteamVR overlay hidden: OpenXR layer draws in headset
        # OpenXR layer
        self._xr: vr_shared.SharedFrameWriter | None = None
        self._xr_checksum: int | None = None
        self._xr_dirty = False  # widgets changed since last tiles written (waiting for next write slot)
        self._xr_written_at: int | None = None  # tick (ms) of last image written
        self._xr_drawing = False
        self._xr_layers: dict[int, XrLayerProcess] = {}  # OpenXR game processes running the layer, by pid
        self._xr_tiles_visible = False  # tiles written & shown (not hidden) for the layer
        self._xr_layer_present = False  # layer heartbeat recent (OpenXR game running): tiles written
        self._xr_mismatch_reported: set[int] = set()  # game processes running a layer of another version
        self._xr_errors_shown: set[str] = set()  # layer setup problems reported once
        # Mirror window
        self._mirror: MirrorWindow | None = None
        self._mirror_checksum: int | None = None
        self._mirror_version: int | None = None  # composer version of the mirror's image (partial repaint)
        self._compose_key: tuple | None = None  # overlay windows state of last composed image
        # Overlays paused (not driving, game closed): updates slowed or stopped, back to normal on these
        for signal in (overlay_signal.paused, overlay_signal.hidden, overlay_signal.locked, overlay_signal.editing):
            signal.connect(self.__wake)
        overlay_signal.context.connect(self.__wake)

    @property
    def running(self) -> bool:
        return (self._handle is not None or self._mirror is not None or self._xr is not None
                or self._steamvr_wanted)

    @property
    def openxr_active(self) -> bool:
        """OpenXR layer available (shared memory written)"""
        return self._xr is not None

    def enable(self):
        """Start VR overlay (OpenXR layer & SteamVR) and/or VR mirror window if enabled in setting

        Mirror window kept from before reload is used again (window capture apps keep it).
        Never raises: problems are logged & reported (app_signal.error).
        """
        try:
            self.__enable()
        except Exception as error:  # never stop app loading
            logger.exception("VR overlay: enable failed")
            self.__fail(f"VR overlay unavailable: {error}")

    def __enable(self):
        setting = cfg.user.config["vr_overlay"]
        self._compose_key = None  # composed again on next update
        background = str(setting.get("mirror_background_color", "#000000"))
        if not setting.get("enable_vr_mirror_window", False):
            self.disable_mirror()  # turned off in setting
        elif self._mirror is None:
            self._mirror = MirrorWindow(background, self.disable_mirror)
            self._mirror.show()
            logger.info("ENABLED: VR mirror window")
        else:
            self._mirror.set_background(background)
            self._mirror_checksum = self._mirror_version = None  # image sent again
            if self._mirror.isHidden():
                self._mirror.show()
        if setting["enable_vr_overlay"]:
            # OpenXR layer: experimental, off by default (loaded by every OpenXR game, LMU too via OpenComposite)
            openxr = bool(setting.get("enable_openxr_layer", False)) and self.__enable_openxr(setting)
            if not openxr:
                self.__close_openxr()
                if vr_shared.WINDOWS:
                    self.__unregister_openxr()
            self.__enable_steamvr(setting, report=not openxr)
        else:
            self.__close_openxr()
            self._steamvr_wanted = False
            self.__drop_steamvr_start()
            self.__release_steamvr()
            if vr_shared.WINDOWS:
                self.__unregister_openxr()
        self._interval = max(int(setting["update_interval"]), 20)
        self._paused_since = None
        if self.running and (not self._timer.isActive() or self._timer.interval() != self._interval):
            self._timer.start(self._interval)

    def __wake(self, _state: bool = False):
        """Overlays resumed, shown, hidden, unlocked or edited: normal update interval again (slowed or stopped
        later by update_overlay if overlays stay paused), SteamVR checked again at once if waited for"""
        self._paused_since = None
        if self._steamvr_wanted and self._overlay is None and realtime_state.shown:
            self._steamvr_retry_at = 0
        if self.running and (not self._timer.isActive() or self._timer.interval() != self._interval):
            self._timer.start(self._interval)

    def __pace(self, now: int, widgets: list):
        """Overlays paused (not shown, not editing) for PAUSED_GRACE_MS: updated every PAUSED_INTERVAL_MS while a
        widget is visible or SteamVR connected (quit events must be answered), else timer stopped (after this
        update) until __wake. OpenXR layer heartbeat kept by its own timer."""
        if realtime_state.shown or realtime_state.editing:
            self._paused_since = None
            if self._timer.isActive() and self._timer.interval() != self._interval:
                self._timer.setInterval(self._interval)
            return
        if self._paused_since is None or now < self._paused_since:
            self._paused_since = now
            return
        if now - self._paused_since < PAUSED_GRACE_MS:
            return
        if self._system is None and not any(widget.isVisible() and widget.width() > 0 for widget in widgets):
            self._timer.stop()
        elif self._timer.isActive() and self._timer.interval() != PAUSED_INTERVAL_MS:
            self._timer.setInterval(PAUSED_INTERVAL_MS)

    # OpenXR layer

    def __enable_openxr(self, setting: dict) -> bool:
        """Register OpenXR layer & open shared memory (Windows), True if available"""
        if not vr_shared.WINDOWS:
            return False
        if self._xr is None:
            try:  # entries of missing files make the OpenXR loader fail every OpenXR game: removed first
                vr_shared.remove_missing_layers()
            except Exception:
                logger.debug("VR overlay: OpenXR layer registry cleanup failed", exc_info=True)
            manifest = vr_shared.find_layer_manifest()
            if manifest is None:
                logger.info("VR overlay: OpenXR layer not found (from source: build native/openxr_layer)")
                return False
            installed = vr_shared.prepare_layer(manifest)  # release: copy outside lib, rewritten by updates
            loadable = vr_shared.loadable_manifest(installed)  # ASCII path (OpenXR loader reads ANSI paths)
            if loadable is None:
                self.__report_once(f"VR overlay: OpenXR layer not usable from a folder with non-ASCII characters "
                                   f"({os.path.dirname(installed)}), no ASCII folder writable for a copy: "
                                   f"install the app in a folder with ASCII characters only")
                return False
            if not vr_shared.register_layer(loadable):
                return False
            vr_shared.remove_old_copies(installed, loadable)  # after registering: never an entry without DLL
            writer = vr_shared.SharedFrameWriter()
            if not writer.open():
                return False
            if writer.warning:
                self.__report_once(writer.warning)
            self._xr = writer
            self._xr_checksum = self._xr_written_at = None
            self._xr_dirty = False
            self._xr_layers.clear()
            self._xr_tiles_visible = False
            self._xr_layer_present = False
            self._heartbeat_timer.start()
            logger.info("ENABLED: VR overlay (OpenXR layer %s)", loadable)
        self._xr.set_placement(placement_from(setting))
        return True

    @staticmethod
    def __unregister_openxr():
        """Option turned off: layer no longer loaded by OpenXR games"""
        try:
            vr_shared.unregister_layer()
        except Exception:
            logger.debug("VR overlay: OpenXR layer unregister failed", exc_info=True)

    def __close_openxr(self):
        self._heartbeat_timer.stop()
        writer, self._xr = self._xr, None
        self._xr_layer_present = False
        self._xr_checksum = self._xr_written_at = None
        self._xr_dirty = False
        self._xr_drawing = False
        self._xr_layers.clear()
        self._xr_tiles_visible = False
        _tile_composer.reset()  # tile images released
        if writer is not None:
            writer.close()
            logger.info("DISABLED: VR overlay (OpenXR layer)")

    def __heartbeat(self):
        """App alive for the layer every HEARTBEAT_INTERVAL_MS; OpenXR game started: tiles written now"""
        writer = self._xr
        if writer is None:
            self._heartbeat_timer.stop()
            return
        now = vr_shared.tick_ms()
        writer.heartbeat(now)
        status = writer.layer_status()
        if status is not None and status.recent(now) and not self._xr_layer_present:
            self.update_overlay()

    def __read_layer_status(self) -> vr_shared.LayerStatus | None:
        """Layer status, None if not open or being written (read twice: two games may write it in turn)"""
        if self._xr is None:
            return None
        status = self._xr.layer_status()
        return status if status is not None and status == self._xr.layer_status() else None

    def __update_openxr_status(self, now: int):
        """Layer state of OpenXR games (one or several processes): logged on change of each process, SteamVR
        overlay hidden while a layer draws. Tiles written only while a layer runs (an OpenXR game): written at
        once when one appears, hidden when all go (nothing outdated shown by the next game)."""
        layers = self._xr_layers
        status = self.__read_layer_status()
        if status is not None and status.pid != 0:
            layer = layers.get(status.pid)
            if layer is None:
                if status.recent(now):
                    layers[status.pid] = layer = XrLayerProcess(status)
            else:
                layer.update(status, now)
            if layer is not None:
                self.__log_layer_state(layer, now)
        for pid, layer in list(layers.items()):
            if not layer.status.recent(now):
                if layer.logged is not None:
                    layer.logged = None
                    logger.info("VR overlay: OpenXR game closed (process %s)", pid)
                # Kept a while: session restarted by the same game, frames expected again (grace window)
                if not layer.drew_recently(now, OPENXR_RESUME_GRACE_MS):
                    del layers[pid]
        present = any(layer.status.recent(now) for layer in layers.values())
        if present != self._xr_layer_present:
            self._xr_layer_present = present
            if present:
                self._xr_dirty = True  # written on this tick, rate limit ignored
                self._xr_written_at = None
            else:
                self.__hide_tiles(now)
        self._xr_drawing = any(layer.drawing(now, self._xr_tiles_visible) for layer in layers.values())

    def __log_layer_state(self, layer: XrLayerProcess, now: int):
        """State of a game process logged when it changes (several games: each logged once per change)"""
        status = layer.status
        state = (status.state, status.graphics_api) if status.recent(now) else None
        if state is None or state == layer.logged:
            return
        layer.logged = state
        if status.state == vr_shared.LAYER_ACTIVE:
            logger.info("VR overlay: shown in OpenXR game (%s, process %s)", status.graphics_name, status.pid)
        elif status.state == vr_shared.LAYER_UNSUPPORTED:
            logger.warning("VR overlay: OpenXR game uses %s, not supported by OpenXR layer "
                           "(SteamVR overlay or mirror window still work)", status.graphics_name)
        elif status.version_mismatch:
            logger.warning("VR overlay: OpenXR game (process %s) runs the layer of another app version "
                           "(protocol %s, app %s), nothing drawn: restart the game "
                           "(SteamVR overlay or mirror window still work)",
                           status.pid, status.version, vr_shared.VERSION)
            if status.pid not in self._xr_mismatch_reported:
                self._xr_mismatch_reported.add(status.pid)
                app_signal.error.emit("VR overlay: restart the VR game to show the overlay in it "
                                      "(game started before the app was updated)")
        else:
            logger.warning("VR overlay: OpenXR layer stopped in game (XrResult %s)", status.last_result)

    def __hide_tiles(self, now: int):
        """Nothing for the layer to draw: games that drew it keep their state until tiles are shown again"""
        if self._xr is not None:
            self._xr.hide()
        self._xr_checksum = None
        if self._xr_tiles_visible:
            self._xr_tiles_visible = False
            for layer in self._xr_layers.values():
                layer.drew_before_hide = layer.drew_recently(now, OPENXR_RESUME_GRACE_MS)

    def __tiles_shown(self, now: int):
        """Tiles shown again (auto hide, game session restarted): SteamVR overlay kept hidden while the games
        that drew them resume (OPENXR_RESUME_GRACE_MS at most)"""
        if self._xr_tiles_visible:
            return
        self._xr_tiles_visible = True
        for layer in self._xr_layers.values():
            if layer.drew_before_hide:
                layer.wait_from = now
            layer.drew_before_hide = False
        self._xr_drawing = any(layer.drawing(now, True) for layer in self._xr_layers.values())

    def __write_openxr(self, widgets: list, now: int):
        """Tiles for OpenXR layer: copied by the layer in the game's frame, so written at most every
        OPENXR_MIN_INTERVAL_MS (composed from the newest widget state once the interval passed), only when
        changed. Hidden at once when no widget is visible."""
        writer = self._xr
        if writer is None:
            self._xr_dirty = False
            return
        if not any(widget.isVisible() and widget.width() > 0 for widget in widgets):
            self._xr_dirty = False
            self.__hide_tiles(now)
            return
        if not self._xr_layer_present:  # no OpenXR game: nothing composed (written once a layer appears)
            self._xr_dirty = False
            return
        if self._xr_written_at is not None and 0 <= now - self._xr_written_at < OPENXR_MIN_INTERVAL_MS:
            self._xr_dirty = True  # written on a later tick
            return
        self._xr_dirty = False
        frame = compose_tiles(widgets)
        if frame is None:  # nothing visible
            self.__hide_tiles(now)
            return
        if frame.checksum == self._xr_checksum:
            return
        self._xr_written_at = now
        self._xr_checksum = frame.checksum
        atlas = frame.atlas
        view = memoryview(atlas.constBits())[:atlas.sizeInBytes()]  # type: ignore[arg-type]
        try:
            writer.write_tiles(view, atlas.width(), atlas.height(), atlas.bytesPerLine(), frame.tiles, frame.canvas,
                               frame.dirty)
        except (ValueError, TypeError, BufferError) as error:
            self._xr_checksum = None
            logger.warning("VR overlay: OpenXR image not written: %s", error)
        else:
            self.__tiles_shown(now)

    # SteamVR (OpenVR)

    def __enable_steamvr(self, setting: dict, report: bool) -> bool:
        """SteamVR overlay wanted: started now if SteamVR runs, else once it runs (checked every few seconds)

        Args:
            report: report openvr unavailable as error (no OpenXR layer either).

        Returns:
            True if openvr available.
        """
        if self._handle is not None or self._steamvr_start is not None:  # running, or starting in background
            return True
        try:
            import openvr  # optional dependency  # noqa: F401
        except ImportError:
            self.__steamvr_unavailable("VR overlay requires \"openvr\" package (pip install openvr).", report)
            return False
        except Exception as error:  # package found, native library (libopenvr_api) missing or not loadable
            logger.debug("VR overlay: openvr import failed", exc_info=True)
            self.__steamvr_unavailable(f"VR overlay unavailable, OpenVR library not loaded: {error}", report)
            return False
        self._steamvr_wanted = True
        self._steamvr_error_shown = False
        self._steamvr_retry_at = 0
        self._steamvr_report = report
        self.__poll_steamvr(vr_shared.tick_ms())
        return True

    def __steamvr_unavailable(self, message: str, report: bool):
        self._steamvr_wanted = False
        if report:
            self.__fail(message)
        else:
            logger.info("VR overlay: SteamVR overlay unavailable (%s)", message)

    def __poll_steamvr(self, now: int):
        """SteamVR process checked in background every STEAMVR_RETRY_MS (not while the OpenXR layer draws:
        SteamVR overlay would stay hidden), SteamVR overlay started once SteamVR runs (never starts SteamVR)"""
        if self._steamvr_start is not None:  # start running: adopted once done (update_overlay), no new check
            self.__adopt_steamvr()
            return
        if self._steamvr_check is None and now >= self._steamvr_retry_at and not self._xr_drawing:
            # Overlays paused (not driving): checked rarely, at once when they resume (__wake)
            self._steamvr_retry_at = now + (STEAMVR_RETRY_MS if realtime_state.shown else STEAMVR_IDLE_RETRY_MS)
            self._steamvr_check = SteamVRCheck()
        check = self._steamvr_check
        if check is None or not check.done():
            return
        self._steamvr_check = None
        report, self._steamvr_report = self._steamvr_report, False
        if self._steamvr_quitting:  # SteamVR still closing (vrserver alive): connecting would keep it open
            if not check.running:
                self._steamvr_quitting = False
                logger.info("VR overlay: SteamVR closed, waiting for SteamVR")
            return
        if check.running:
            self.__start_steamvr(cfg.user.config["vr_overlay"], report)
        elif report and not self._steamvr_error_shown and self._xr is None:
            logger.info("VR overlay: waiting for SteamVR")

    def __start_steamvr(self, setting: dict, report: bool = False):
        """Start SteamVR overlay (SteamVR running): openvr init & overlay creation in a background thread
        (SteamVRStart), adopted at once if quick, else on a later update_overlay tick (GUI never held)"""
        self._steamvr_retry_at = vr_shared.tick_ms() + STEAMVR_RETRY_MS
        self._steamvr_start_report = report
        self._steamvr_start = SteamVRStart(setting)
        if self._steamvr_start.wait(STEAMVR_START_WAIT_S):
            self.__adopt_steamvr()

    def __adopt_steamvr(self):
        """SteamVR start done: overlay taken over (GUI thread), or failure reported & tried again later"""
        start = self._steamvr_start
        if start is None or not start.done():
            return
        self._steamvr_start = None
        report, self._steamvr_start_report = self._steamvr_start_report, False
        result = start.take()
        if result is None:
            error = start.error or RuntimeError("SteamVR start dropped")
            if not self._steamvr_error_shown:
                self._steamvr_error_shown = True
                if report and self._xr is None:
                    self.__fail(f"VR overlay unavailable: {error}")
                else:
                    logger.warning("VR overlay: SteamVR overlay not started: %s", error)
            self.__release_steamvr()
            return
        self._openvr, self._system, self._overlay, self._handle = result
        self._visible = True
        self._hidden_for_openxr = False
        self._compose_key = None  # image sent on next update
        self._checksum = None
        logger.info("ENABLED: VR overlay (SteamVR)")

    def __drop_steamvr_start(self):
        """SteamVR start running in background never adopted (disabled meanwhile)"""
        start, self._steamvr_start = self._steamvr_start, None
        if start is not None:
            start.drop()

    def __release_steamvr(self):
        """Destroy SteamVR overlay & shut openvr down (SteamVR may be closed already)"""
        release_openvr(self._openvr, self._overlay, self._handle)
        was_running = self._handle is not None
        self._openvr = self._system = self._overlay = self._handle = self._buffer = self._buffer_image = None
        self._checksum = self._sent_at = None
        self._steamvr_dirty = False
        self._visible = False
        self._hidden_for_openxr = False
        if was_running:
            logger.info("DISABLED: VR overlay (SteamVR)")

    def __steamvr_show(self, show: bool):
        overlay = self._overlay
        if overlay is None or show == self._visible:
            return
        if show:
            overlay.showOverlay(self._handle)
        else:
            overlay.hideOverlay(self._handle)
        self._visible = show

    # Update

    def update_overlay(self):
        """Send composed widgets image to OpenXR layer, SteamVR & mirror window, only if changed"""
        if not self.running:  # timer tick queued after disable()
            return
        now = vr_shared.tick_ms()
        if self._xr is not None:
            self._xr.heartbeat(now)
            self.__update_openxr_status(now)
        if self._system is not None:
            self.__steamvr_events()
        if self._steamvr_wanted and self._overlay is None:
            self.__poll_steamvr(now)
        overlay = self._overlay
        if overlay is not None:
            # OpenXR game drawn by the layer (also on SteamVR runtime): no second image from SteamVR overlay
            hide = self._xr_drawing
            if hide != self._hidden_for_openxr:
                self._hidden_for_openxr = hide
                if hide:
                    try:
                        self.__steamvr_show(False)
                    except Exception as error:
                        self.__steamvr_stopped(error)
                        overlay = None
                    else:
                        logger.info("VR overlay: SteamVR overlay hidden (OpenXR layer draws it)")
                else:  # image not sent while hidden: composed & sent now, then shown
                    self._compose_key = None
                    self._checksum = None
                    logger.info("VR overlay: SteamVR overlay shown")
        widgets = [widget for widget in QApplication.topLevelWidgets() if hasattr(widget, "widget_name")]
        self.__pace(now, widgets)
        xr_checked = self._xr_dirty
        if xr_checked:  # tiles held back by write rate limit
            self.__write_openxr(widgets, now)
        key = compose_key(widgets)
        unchanged = key is not None and key == self._compose_key
        if unchanged and not self._steamvr_dirty:
            return  # no overlay window painted, moved, shown or hidden since last update
        self._compose_key = key
        self._steamvr_dirty = False
        if not xr_checked and not unchanged:  # already composed from current widgets on this tick (or held back)
            self.__write_openxr(widgets, now)
        if overlay is not None and self._hidden_for_openxr:
            overlay = None  # hidden for OpenXR: no image sent (~4 MB), sent again once shown
            self._checksum = None
        if self._mirror is None and overlay is None:
            return  # OpenXR layer only: whole canvas image not needed
        image = compose_widgets(widgets)
        composer = _composer if image is not None and image is _composer.image else None
        if composer is not None:  # only rows drawn since last time read
            checksum = composer.checksum()
        else:
            checksum = image_checksum(image) if image is not None else None
        mirror = self._mirror
        if mirror is not None:
            if checksum != self._mirror_checksum or mirror.image is not image:
                self._mirror_checksum = checksum
                # Only the part drawn since the mirror's last image painted again (else whole window)
                partial = composer is not None and self._mirror_version == composer.version - 1
                mirror.set_image(image, composer.dirty if partial and composer is not None else None)
            self._mirror_version = composer.version if composer is not None else None
        if overlay is None:
            return
        try:
            if image is None:  # all widgets hidden (auto hide, out of session), hide VR overlay too
                self._has_image = False
                self.__steamvr_show(False)
                self._checksum = None
                return
            self._has_image = True
            if checksum != self._checksum:  # skip unchanged image
                if self._sent_at is not None and 0 <= now - self._sent_at < STEAMVR_MIN_INTERVAL_MS:
                    self._steamvr_dirty = True  # whole canvas sent at most ~15 times per second: on a later tick
                else:
                    frame = image_frame(image, checksum)
                    self._checksum = frame.checksum
                    self._buffer, self._buffer_image = frame.buffer, frame.image  # keep reference until next frame
                    overlay.setOverlayRaw(self._handle, frame.buffer, frame.width, frame.height, 4)
                    self._sent_at = now
            # Shown once an image was sent (image held back after hiding: old one never shown meanwhile)
            self.__steamvr_show(not self._hidden_for_openxr and self._checksum is not None)
        except Exception as error:  # SteamVR closed, or openvr error
            self.__steamvr_stopped(error)

    def __steamvr_events(self):
        """SteamVR events: quit asked (SteamVR closed from headset or desktop) acknowledged & overlay released at
        once, else SteamVR waits for the app (grey screen in headset) & games cannot start it again"""
        openvr, system = self._openvr, self._system
        if openvr is None or system is None:
            return
        try:
            event = openvr.VREvent_t()
            while system.pollNextEvent(event):
                if event.eventType == openvr.VREvent_Quit:
                    with suppress(Exception):
                        system.acknowledgeQuit_Exiting()
                    logger.info("VR overlay: SteamVR quitting, overlay released")
                    self._steamvr_quitting = True
                    self.__release_steamvr()
                    self._steamvr_retry_at = vr_shared.tick_ms() + STEAMVR_RETRY_MS
                    return
        except Exception as error:
            self.__steamvr_stopped(error)

    def __steamvr_stopped(self, error: Exception):
        """SteamVR closed or failed: overlay released, started again once SteamVR runs again.
        OpenXR layer & mirror window (sharing timer) kept updating."""
        logger.debug("VR overlay: update failed", exc_info=True)
        logger.warning("VR overlay: SteamVR overlay stopped: %s", error)
        self.__release_steamvr()
        self._steamvr_retry_at = vr_shared.tick_ms() + STEAMVR_RETRY_MS
        if not self.running:
            self._timer.stop()

    def disable_mirror(self):
        """Close VR mirror window"""
        mirror, self._mirror = self._mirror, None
        self._mirror_checksum = self._mirror_version = None
        if mirror is not None:
            mirror.hide()
            mirror.deleteLater()
            logger.info("DISABLED: VR mirror window")
        if not self.running:
            self._timer.stop()

    def disable(self, close_mirror: bool = False):
        """Stop VR overlay & mirror window updates

        OpenXR layer unregistered (games started after are never given it, registered again by enable()),
        shared memory released: layer stops drawing at once.

        Args:
            close_mirror: close mirror window too, else kept open (reload: enable() uses it again,
                window capture apps keep following it), closed when turned off in setting.
        """
        if close_mirror:
            self.disable_mirror()
        self._timer.stop()
        self._compose_key = self._paused_since = None
        self._steamvr_wanted = False
        self._steamvr_check = None  # background check result ignored
        self.__drop_steamvr_start()
        self._has_image = False
        self.__release_steamvr()
        _composer.reset()  # canvas image released
        try:
            self.__close_openxr()
        except Exception:
            logger.debug("VR overlay: OpenXR close failed", exc_info=True)
        if vr_shared.WINDOWS:
            self.__unregister_openxr()

    def __report_once(self, message: str):
        """Problem reported to the user once (enable runs again on each reload), logged each time"""
        if message in self._xr_errors_shown:
            logger.warning(message)
            return
        self._xr_errors_shown.add(message)
        self.__fail(message)

    @staticmethod
    def __fail(message: str):
        logger.error("VR OVERLAY: %s", message)
        app_signal.error.emit(message)


_vroverlay: VROverlay | None = None


def vroverlay() -> VROverlay:
    """Shared VR overlay control (created after QApplication)"""
    global _vroverlay
    if _vroverlay is None:
        _vroverlay = VROverlay()
    return _vroverlay
