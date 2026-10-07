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
  Shows the whole canvas composed into one image. Both placed the same way: fixed in seated space or
  attached to headset.
- VR mirror window: one desktop window showing the composed image, for window capture overlays such as
  OpenKneeboard, OVR Toolkit, XSOverlay or Desktop+.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import threading
import zlib
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QWidget

from . import app_signal, vr_shared
from .const_file import ConfigType
from .setting import cfg

logger = logging.getLogger(__name__)

MAX_PIXELS = 1024 * 1024  # setOverlayRaw data size limit, image is scaled down above this
MIRROR_TITLE = "Modern Tiny Pedals VR"  # window title to select in window capture apps
STEAMVR_PROCESSES = ("vrserver.exe", "vrserver")  # SteamVR server (Windows, Linux)
STEAMVR_RETRY_MS = 5000  # SteamVR started after app: overlay created within this delay
OPENXR_MIN_INTERVAL_MS = 66  # OpenXR layer image written at most ~15 times per second (copied in game frame)
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
        self.pixmap = QPixmap()
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

    def set_image(self, image: QImage | None):
        """Show image, empty (background only) if None"""
        self.pixmap = QPixmap.fromImage(image) if image is not None else QPixmap()
        if not self.pixmap.isNull() and self.size() != self.pixmap.size():
            self.resize(self.pixmap.size())
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.background)
        if not self.pixmap.isNull():
            painter.drawPixmap(0, 0, self.pixmap)

    def closeEvent(self, event):
        """Closing window turns mirror off until next reload, so window is not shown again unexpectedly"""
        self._save_timer.stop()
        self.save_position()
        cfg.user.config["vr_overlay"]["enable_vr_mirror_window"] = False
        cfg.save(config_type=ConfigType.CONFIG)
        self.on_closed()
        super().closeEvent(event)


def window_image(widget: QWidget) -> QImage | None:
    """Overlay window as last painted: backing store copy (no repaint) once window painted (paint serial
    counted, see widget._base.PaintCounter), else rendered again (grab)"""
    if getattr(widget, "paint_serial", None) is not None:
        store = widget.backingStore()
        device = store.paintDevice() if store is not None else None
        if isinstance(device, QImage) and not device.isNull():
            ratio = device.devicePixelRatio()
            width, height = round(widget.width() * ratio), round(widget.height() * ratio)
            if 0 < width <= device.width() and 0 < height <= device.height():
                return device.copy(0, 0, width, height)
    pixmap = widget.grab()
    return pixmap.toImage() if not pixmap.isNull() else None


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


def compose_widgets(widgets: list) -> QImage | None:
    """Compose visible overlay widgets into one RGBA image, keeping desktop layout"""
    visible = [widget for widget in widgets if widget.isVisible() and widget.width() > 0]
    if not visible:
        return None
    bounds = QRect()
    for widget in visible:
        bounds = bounds.united(widget.frameGeometry())
    image = compose_group(visible, bounds.topLeft(), (bounds.width(), bounds.height()))
    pixels = image.width() * image.height()
    if pixels > MAX_PIXELS:
        scale = (MAX_PIXELS / pixels) ** 0.5
        image = image.scaled(
            max(int(image.width() * scale), 1),
            max(int(image.height() * scale), 1),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image


def _row_span(image: QImage) -> tuple[int, int] | None:
    """First & last row of 8 bit image with a non zero byte, None if all zero"""
    bits = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
    stride, width, height = image.bytesPerLine(), image.width(), image.height()
    zero = bytes(width)
    first = 0
    while first < height and bits[first * stride:first * stride + width] == zero:
        first += 1
    if first == height:
        return None
    last = height - 1
    while bits[last * stride:last * stride + width] == zero:
        last -= 1
    return first, last


def content_rect(image: QImage) -> QRect:
    """Bounding rect of visible (not fully transparent) pixels, empty if none"""
    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    rows = _row_span(alpha)
    if rows is None:
        return QRect()
    top, bottom = rows
    band = alpha.copy(0, top, alpha.width(), bottom - top + 1)
    columns = _row_span(band.transformed(QTransform().rotate(90)))  # rows of rotated image: columns
    if columns is None:
        return QRect()
    left, right = columns
    return QRect(left, top, right - left + 1, bottom - top + 1)


class TileFrame(NamedTuple):
    """Visible parts of the canvas for the OpenXR layer: atlas image (RGBA8888) & its tiles"""

    atlas: QImage
    tiles: tuple[vr_shared.Tile, ...]
    canvas: tuple[int, int]  # width, height (same scale as atlas)
    checksum: int


def compose_group(widgets: list, origin: QPoint, size: tuple[int, int]) -> QImage:
    """Widgets (stacking order kept) composed into a transparent image of size, origin at its top left"""
    image = QImage(size[0], size[1], QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    for widget in widgets:
        window = window_image(widget)
        if window is not None:
            painter.setOpacity(widget.windowOpacity())
            painter.drawImage(widget.frameGeometry().topLeft() - origin, window)
    painter.end()
    return image


def compose_tiles(widgets: list, max_tiles: int = OPENXR_MAX_TILES, gap: int = OPENXR_TILE_GAP) -> TileFrame | None:
    """Visible overlay widgets as tiles of the canvas (bounding box of all widgets, desktop layout):
    one tile per group of nearby widgets, cropped to its visible pixels, packed in an atlas.
    Scaled down (canvas too) when the atlas is bigger than the shared memory allows.

    Returns:
        None if nothing visible.
    """
    visible = [widget for widget in widgets if widget.isVisible() and widget.width() > 0]
    if not visible:
        return None
    geometries = [widget.frameGeometry() for widget in visible]
    bounds = QRect()
    for geometry in geometries:
        bounds = bounds.united(geometry)
    rects = [(rect.x() - bounds.x(), rect.y() - bounds.y(), rect.width(), rect.height()) for rect in geometries]
    parts: list[tuple[QImage, int, int]] = []  # image, canvas x & y
    for group in vr_shared.cluster_rects(rects, gap, min(max_tiles, vr_shared.MAX_TILES)):
        box = rects[group[0]]
        for index in group[1:]:
            box = vr_shared.union_rect(box, rects[index])
        image = compose_group([visible[index] for index in group],
                              bounds.topLeft() + QPoint(box[0], box[1]), (box[2], box[3]))
        rect = content_rect(image)
        if rect.isEmpty():
            continue
        if rect != image.rect():  # transparent margins not sent
            image = image.copy(rect)
        parts.append((image, box[0] + rect.x(), box[1] + rect.y()))
    if not parts:
        return None
    # Scale: atlas within shared memory (MAX_PIXELS) & largest image, canvas within layer limit
    area = sum(image.width() * image.height() for image, _, _ in parts)
    scale = min(1.0, math.sqrt(MAX_PIXELS / area), vr_shared.MAX_CANVAS / max(bounds.width(), bounds.height()))
    while True:
        sizes = [(max(round(image.width() * scale), 1), max(round(image.height() * scale), 1)) for image, _, _ in parts]
        packed = vr_shared.pack_atlas(sizes)
        if packed is not None and packed[1] * packed[2] * 4 <= vr_shared.MAX_IMAGE_BYTES:
            break
        scale *= 0.9  # rows waste space: smaller until it fits (1 pixel tiles always do)
    positions, atlas_width, atlas_height = packed
    canvas = (min(max(round(bounds.width() * scale), 1), vr_shared.MAX_CANVAS),
              min(max(round(bounds.height() * scale), 1), vr_shared.MAX_CANVAS))
    atlas = QImage(atlas_width, atlas_height, QImage.Format.Format_RGBA8888)
    atlas.fill(Qt.GlobalColor.transparent)  # padding between tiles transparent
    painter = QPainter(atlas)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    tiles = []
    for (image, x, y), (width, height), (atlas_x, atlas_y) in zip(parts, sizes, positions):
        if (width, height) != (image.width(), image.height()):
            image = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(atlas_x, atlas_y, image)
        canvas_x = min(round(x * scale), canvas[0] - width)  # rounding never moves a tile off canvas
        canvas_y = min(round(y * scale), canvas[1] - height)
        tiles.append(vr_shared.Tile(atlas_x, atlas_y, width, height, max(canvas_x, 0), max(canvas_y, 0)))
    painter.end()
    layout = repr((tiles, canvas)).encode()
    checksum = zlib.crc32(memoryview(atlas.constBits())[:atlas.sizeInBytes()], zlib.crc32(layout))  # type: ignore[arg-type]
    return TileFrame(atlas, tuple(tiles), canvas, checksum)


class ImageFrame(NamedTuple):
    """Raw RGBA frame for SteamVR"""

    buffer: ctypes.Array
    width: int
    height: int
    checksum: int


def image_checksum(image: QImage) -> int:
    """Checksum of image pixels & size (change detection, no copy)"""
    view = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
    return zlib.crc32(view, image.width() << 16 | image.height())


def image_frame(image: QImage, checksum: int | None = None) -> ImageFrame:
    """Copy image pixels once into ctypes buffer, with checksum for change detection"""
    view = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
    buffer = (ctypes.c_ubyte * len(view)).from_buffer_copy(view)
    if checksum is None:
        checksum = image_checksum(image)
    return ImageFrame(buffer, image.width(), image.height(), checksum)


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


def steamvr_running() -> bool:
    """SteamVR server process running (openvr.init would start SteamVR otherwise)"""
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


def placement_from(setting: dict) -> vr_shared.Placement:
    """Overlay placement from "vr_overlay" setting"""
    return vr_shared.Placement(
        max(float(setting["overlay_width_meters"]), 0.05),
        float(setting["distance_meters"]),
        float(setting["vertical_offset_meters"]),
        float(setting["horizontal_offset_meters"]),
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
        self._overlay = None
        self._handle = None
        self._buffer = None
        self._checksum: int | None = None
        self._visible = False
        self._has_image = False  # last composed image not empty (SteamVR overlay shown unless hidden for OpenXR)
        self._steamvr_wanted = False  # openvr available, waiting for SteamVR or running
        self._steamvr_retry_at = 0  # tick (ms) of next SteamVR process check
        self._steamvr_check: SteamVRCheck | None = None  # process check running in background
        self._steamvr_report = False  # first check after enable: report problems as error
        self._steamvr_error_shown = False
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
        self._compose_key: tuple | None = None  # overlay windows state of last composed image

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
            self._mirror_checksum = None  # image sent again
            if self._mirror.isHidden():
                self._mirror.show()
        if setting["enable_vr_overlay"]:
            openxr = self.__enable_openxr(setting)
            self.__enable_steamvr(setting, report=not openxr)
        else:
            self.__close_openxr()
            self._steamvr_wanted = False
            self.__release_steamvr()
            if vr_shared.WINDOWS:
                self.__unregister_openxr()
        if self.running and not self._timer.isActive():
            self._timer.start(max(int(setting["update_interval"]), 20))

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
            writer.write_tiles(view, atlas.width(), atlas.height(), atlas.bytesPerLine(), frame.tiles, frame.canvas)
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
        if self._handle is not None:
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
        if self._steamvr_check is None and now >= self._steamvr_retry_at and not self._xr_drawing:
            self._steamvr_retry_at = now + STEAMVR_RETRY_MS
            self._steamvr_check = SteamVRCheck()
        check = self._steamvr_check
        if check is None or not check.done():
            return
        self._steamvr_check = None
        report, self._steamvr_report = self._steamvr_report, False
        if check.running:
            self.__start_steamvr(cfg.user.config["vr_overlay"], report)
        elif report and not self._steamvr_error_shown and self._xr is None:
            logger.info("VR overlay: waiting for SteamVR")

    def __start_steamvr(self, setting: dict, report: bool = False):
        """Start SteamVR overlay (SteamVR running)"""
        self._steamvr_retry_at = vr_shared.tick_ms() + STEAMVR_RETRY_MS
        import openvr

        try:
            openvr.init(openvr.VRApplication_Overlay)
            self._openvr = openvr
            self._overlay = openvr.IVROverlay()
            self._handle = self._overlay.createOverlay("tinypedal.overlay", "Modern Tiny Pedals")
            self._overlay.setOverlayWidthInMeters(self._handle, max(float(setting["overlay_width_meters"]), 0.05))
            self.__set_transform(openvr, self._overlay, setting)
            self._overlay.showOverlay(self._handle)
            self._visible = True
            self._hidden_for_openxr = False
        except Exception as error:  # SteamVR closing, or openvr error: tried again later
            logger.debug("VR overlay: SteamVR init failed", exc_info=True)
            if not self._steamvr_error_shown:
                self._steamvr_error_shown = True
                if report and self._xr is None:
                    self.__fail(f"VR overlay unavailable: {error}")
                else:
                    logger.warning("VR overlay: SteamVR overlay not started: %s", error)
            self.__release_steamvr()
            return
        self._compose_key = None  # image sent on next update
        self._checksum = None
        logger.info("ENABLED: VR overlay (SteamVR)")

    def __set_transform(self, openvr, overlay, setting: dict):
        """Set overlay position"""
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
            overlay.setOverlayTransformTrackedDeviceRelative(
                self._handle, openvr.k_unTrackedDeviceIndex_Hmd, matrix)
        else:
            overlay.setOverlayTransformAbsolute(self._handle, openvr.TrackingUniverseSeated, matrix)

    def __release_steamvr(self):
        """Destroy SteamVR overlay & shut openvr down (SteamVR may be closed already)"""
        if self._overlay is not None and self._handle is not None:
            try:
                self._overlay.destroyOverlay(self._handle)
            except Exception:  # SteamVR already closed
                logger.debug("VR overlay: destroy failed", exc_info=True)
        if self._openvr is not None:
            try:
                self._openvr.shutdown()
            except Exception:
                logger.debug("VR overlay: shutdown failed", exc_info=True)
        was_running = self._handle is not None
        self._openvr = self._overlay = self._handle = self._buffer = None
        self._checksum = None
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
        if self._xr_dirty:  # tiles held back by write rate limit
            self.__write_openxr(widgets, now)
        key = compose_key(widgets)
        if key is not None and key == self._compose_key:
            return  # no overlay window painted, moved, shown or hidden since last update
        self._compose_key = key
        self.__write_openxr(widgets, now)
        if overlay is not None and self._hidden_for_openxr:
            overlay = None  # hidden for OpenXR: no image sent (~4 MB), sent again once shown
            self._checksum = None
        if self._mirror is None and overlay is None:
            return  # OpenXR layer only: whole canvas image not needed
        image = compose_widgets(widgets)
        checksum = image_checksum(image) if image is not None else None
        if self._mirror is not None:
            if checksum != self._mirror_checksum:
                self._mirror_checksum = checksum
                self._mirror.set_image(image)
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
                frame = image_frame(image, checksum)
                self._checksum = frame.checksum
                self._buffer = frame.buffer  # keep reference until next frame
                overlay.setOverlayRaw(self._handle, frame.buffer, frame.width, frame.height, 4)
            self.__steamvr_show(not self._hidden_for_openxr)
        except Exception as error:  # SteamVR closed, or openvr error
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
        self._mirror_checksum = None
        if mirror is not None:
            mirror.hide()
            mirror.deleteLater()
            logger.info("DISABLED: VR mirror window")
        if not self.running:
            self._timer.stop()

    def disable(self, close_mirror: bool = False):
        """Stop VR overlay & mirror window updates

        OpenXR layer stays registered (inactive without app heartbeat), shared memory released: layer stops
        drawing at once.

        Args:
            close_mirror: close mirror window too, else kept open (reload: enable() uses it again,
                window capture apps keep following it), closed when turned off in setting.
        """
        if close_mirror:
            self.disable_mirror()
        self._timer.stop()
        self._compose_key = None
        self._steamvr_wanted = False
        self._steamvr_check = None  # background check result ignored
        self._has_image = False
        self.__release_steamvr()
        try:
            self.__close_openxr()
        except Exception:
            logger.debug("VR overlay: OpenXR close failed", exc_info=True)

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
