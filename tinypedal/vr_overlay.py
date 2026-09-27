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
Native VR overlay (SteamVR / OpenVR), experimental

Compose all visible overlay widgets into one image (same layout as on desktop),
and show it as SteamVR overlay, fixed in seated space or attached to headset.
Requires optional "openvr" package (pip install openvr) and running SteamVR.
"""

from __future__ import annotations

import ctypes
import logging
import zlib
from typing import NamedTuple

from PySide6.QtCore import QObject, QRect, Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from . import app_signal
from .setting import cfg

logger = logging.getLogger(__name__)

MAX_PIXELS = 1024 * 1024  # setOverlayRaw data size limit, image is scaled down above this


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
        painter.setOpacity(widget.windowOpacity())
        painter.drawPixmap(widget.frameGeometry().topLeft() - bounds.topLeft(), widget.grab())
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


def image_frame(image: QImage) -> ImageFrame:
    """Copy image pixels once into ctypes buffer, with checksum for change detection"""
    view = memoryview(image.constBits())[:image.sizeInBytes()]
    buffer = (ctypes.c_ubyte * len(view)).from_buffer_copy(view)
    return ImageFrame(buffer, image.width(), image.height(), zlib.crc32(buffer))


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

    @property
    def running(self) -> bool:
        return self._handle is not None

    def enable(self):
        """Start VR overlay if enabled in setting"""
        setting = cfg.user.config["vr_overlay"]
        if not setting["enable_vr_overlay"] or self.running:
            return
        try:
            import openvr  # optional dependency
        except ImportError:
            self.__fail("VR overlay requires \"openvr\" package (pip install openvr).")
            return
        try:
            openvr.init(openvr.VRApplication_Overlay)
            self._openvr = openvr
            self._overlay = openvr.IVROverlay()
            self._handle = self._overlay.createOverlay("tinypedal.overlay", "TinyPedal")
            self._overlay.setOverlayWidthInMeters(self._handle, max(float(setting["overlay_width_meters"]), 0.05))
            self.__set_transform(openvr, self._overlay, setting)
            self._overlay.showOverlay(self._handle)
            self._visible = True
        except Exception as error:  # SteamVR not running, or openvr error
            self.__fail(f"VR overlay unavailable: {error}")
            self.disable()
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
        """Send composed widgets image to SteamVR, only if changed"""
        overlay = self._overlay
        if overlay is None:  # timer tick queued after disable()
            return
        widgets = [widget for widget in QApplication.topLevelWidgets() if hasattr(widget, "widget_name")]
        image = compose_widgets(widgets)
        try:
            if image is None:  # all widgets hidden (auto hide, out of session), hide VR overlay too
                if self._visible:
                    overlay.hideOverlay(self._handle)
                    self._visible = False
                    self._checksum = None
                return
            frame = image_frame(image)
            if frame.checksum != self._checksum:  # skip unchanged image
                self._checksum = frame.checksum
                self._buffer = frame.buffer  # keep reference until next frame
                overlay.setOverlayRaw(self._handle, frame.buffer, frame.width, frame.height, 4)
            if not self._visible:
                overlay.showOverlay(self._handle)
                self._visible = True
        except Exception as error:
            self.__fail(f"VR overlay stopped: {error}")
            self.disable()

    def disable(self):
        """Stop VR overlay"""
        self._timer.stop()
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
