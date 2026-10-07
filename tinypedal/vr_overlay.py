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
VR overlay, experimental

Compose all visible overlay widgets into one image (same layout as on desktop), then:
- SteamVR overlay: fixed in seated space or attached to headset. Requires optional "openvr"
  package (pip install openvr) and running SteamVR.
- VR mirror window: one desktop window showing the composed image, for OpenXR games on any
  runtime (Meta, Virtual Desktop, WMR...) through a window capture overlay such as OpenKneeboard
  (an OpenXR API layer), OVR Toolkit, XSOverlay or Desktop+.
"""

from __future__ import annotations

import ctypes
import logging
import zlib
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import app_signal
from .const_file import ConfigType
from .setting import cfg

logger = logging.getLogger(__name__)

MAX_PIXELS = 1024 * 1024  # setOverlayRaw data size limit, image is scaled down above this
MIRROR_TITLE = "Modern Tiny Pedals VR"  # window title to select in window capture apps


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
    image = QImage(bounds.width(), bounds.height(), QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    for widget in visible:
        window = window_image(widget)
        if window is not None:
            painter.setOpacity(widget.windowOpacity())
            painter.drawImage(widget.frameGeometry().topLeft() - bounds.topLeft(), window)
    painter.end()
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


class VROverlay(QObject):
    """SteamVR overlay control, runs in main (GUI) thread"""

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_overlay)
        self._openvr = None
        self._overlay = None
        self._handle = None
        self._buffer = None
        self._checksum: int | None = None
        self._visible = False
        self._mirror: MirrorWindow | None = None
        self._mirror_checksum: int | None = None
        self._compose_key: tuple | None = None  # overlay windows state of last composed image

    @property
    def running(self) -> bool:
        return self._handle is not None or self._mirror is not None

    def enable(self):
        """Start SteamVR overlay and/or VR mirror window if enabled in setting

        Mirror window kept from before reload is used again (window capture apps keep it).
        """
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
        if self._mirror is not None and not self._timer.isActive():
            self._timer.start(max(int(setting["update_interval"]), 20))
        if not setting["enable_vr_overlay"] or self._handle is not None:
            return
        try:
            import openvr  # optional dependency
        except ImportError:
            self.__fail("VR overlay requires \"openvr\" package (pip install openvr).")
            return
        except Exception as error:  # package found, native library (libopenvr_api) missing or not loadable
            logger.debug("VR overlay: openvr import failed", exc_info=True)
            self.__fail(f"VR overlay unavailable, OpenVR library not loaded: {error}")
            return
        try:
            openvr.init(openvr.VRApplication_Overlay)
            self._openvr = openvr
            self._overlay = openvr.IVROverlay()
            self._handle = self._overlay.createOverlay("tinypedal.overlay", "Modern Tiny Pedals")
            self._overlay.setOverlayWidthInMeters(self._handle, max(float(setting["overlay_width_meters"]), 0.05))
            self.__set_transform(openvr, self._overlay, setting)
            self._overlay.showOverlay(self._handle)
            self._visible = True
        except Exception as error:  # SteamVR not running, or openvr error
            logger.debug("VR overlay: init failed", exc_info=True)
            self.__fail(f"VR overlay unavailable: {error}")
            self.__disable_vr()
            return
        self._timer.start(max(int(setting["update_interval"]), 20))
        logger.info("ENABLED: VR overlay")

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

    def update_overlay(self):
        """Send composed widgets image to SteamVR & mirror window, only if changed"""
        overlay = self._overlay
        if overlay is None and self._mirror is None:  # timer tick queued after disable()
            return
        widgets = [widget for widget in QApplication.topLevelWidgets() if hasattr(widget, "widget_name")]
        key = compose_key(widgets)
        if key is not None and key == self._compose_key:
            return  # no overlay window painted, moved, shown or hidden since last update
        self._compose_key = key
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
                if self._visible:
                    overlay.hideOverlay(self._handle)
                    self._visible = False
                    self._checksum = None
                return
            if checksum != self._checksum:  # skip unchanged image
                frame = image_frame(image, checksum)
                self._checksum = frame.checksum
                self._buffer = frame.buffer  # keep reference until next frame
                overlay.setOverlayRaw(self._handle, frame.buffer, frame.width, frame.height, 4)
            if not self._visible:
                overlay.showOverlay(self._handle)
                self._visible = True
        except Exception as error:  # SteamVR closed, or openvr error
            logger.debug("VR overlay: update failed", exc_info=True)
            self.__fail(f"VR overlay stopped: {error}")
            self.__disable_vr()

    def __disable_vr(self):
        """SteamVR failed or closed: stop VR overlay only, mirror window (sharing timer) kept updating"""
        self.disable()
        if self._mirror is not None:
            self._timer.start()  # same interval as before stopped

    def disable_mirror(self):
        """Close VR mirror window"""
        mirror, self._mirror = self._mirror, None
        self._mirror_checksum = None
        if mirror is not None:
            mirror.hide()
            mirror.deleteLater()
            logger.info("DISABLED: VR mirror window")
        if self._overlay is None:
            self._timer.stop()

    def disable(self, close_mirror: bool = False):
        """Stop VR overlay & mirror window updates

        Args:
            close_mirror: close mirror window too, else kept open (reload: enable() uses it again,
                window capture apps keep following it), closed when turned off in setting.
        """
        if close_mirror:
            self.disable_mirror()
        self._timer.stop()
        self._compose_key = None
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
        if was_running:
            logger.info("DISABLED: VR overlay")

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
