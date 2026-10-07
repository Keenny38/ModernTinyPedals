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

Compose all visible overlay widgets into one image (same layout as on desktop), then:
- OpenXR layer (Windows): image written to shared memory, drawn in every OpenXR game on any runtime
  (SteamVR, Meta / Air Link, Virtual Desktop, WMR, Pimax, Varjo...) by the app's own OpenXR API layer
  (native/openxr_layer, bundled in the release, see vr_shared.py). Nothing to install.
- SteamVR overlay: OpenVR games (rFactor 2, Le Mans Ultimate in SteamVR mode...). Requires the "openvr"
  package (bundled in the release, from source: pip install openvr); created once SteamVR runs (never
  starts SteamVR), hidden while the OpenXR layer draws the overlay (OpenXR game on SteamVR runtime).
  Both placed the same way: fixed in seated space or attached to headset.
- VR mirror window: one desktop window showing the composed image, for window capture overlays such as
  OpenKneeboard, OVR Toolkit, XSOverlay or Desktop+.
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

from . import app_signal, vr_shared
from .const_file import ConfigType
from .setting import cfg

logger = logging.getLogger(__name__)

MAX_PIXELS = 1024 * 1024  # setOverlayRaw data size limit, image is scaled down above this
MIRROR_TITLE = "Modern Tiny Pedals VR"  # window title to select in window capture apps
STEAMVR_PROCESSES = ("vrserver.exe", "vrserver")  # SteamVR server (Windows, Linux)
STEAMVR_RETRY_MS = 5000  # SteamVR started after app: overlay created within this delay


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
        # SteamVR (OpenVR)
        self._openvr = None
        self._overlay = None
        self._handle = None
        self._buffer = None
        self._checksum: int | None = None
        self._visible = False
        self._has_image = False  # last composed image not empty (SteamVR overlay shown unless hidden for OpenXR)
        self._steamvr_wanted = False  # openvr available, waiting for SteamVR or running
        self._steamvr_retry_at = 0  # tick (ms) of next SteamVR start attempt
        self._steamvr_error_shown = False
        self._hidden_for_openxr = False  # SteamVR overlay hidden: OpenXR layer draws in headset
        # OpenXR layer
        self._xr: vr_shared.SharedFrameWriter | None = None
        self._xr_checksum: int | None = None
        self._xr_drawing = False
        self._xr_state: tuple | None = None  # last layer state logged
        self._xr_frames: tuple[int, int] | None = None  # (pid, frames_shown) of layer at last tick
        self._xr_shown_at: int | None = None  # tick (ms) when layer frames_shown last grew
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
            manifest = vr_shared.find_layer_manifest()
            if manifest is None:
                logger.info("VR overlay: OpenXR layer not found (from source: build native/openxr_layer)")
                return False
            manifest = vr_shared.prepare_layer(manifest)  # release: copy outside lib, rewritten by updates
            if not vr_shared.register_layer(manifest):
                return False
            writer = vr_shared.SharedFrameWriter()
            if not writer.open():
                return False
            self._xr = writer
            self._xr_checksum = None
            self._xr_state = None
            self._xr_frames = self._xr_shown_at = None
            logger.info("ENABLED: VR overlay (OpenXR layer %s)", manifest)
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
        writer, self._xr = self._xr, None
        self._xr_checksum = None
        self._xr_drawing = False
        self._xr_frames = self._xr_shown_at = None
        if writer is not None:
            writer.close()
            logger.info("DISABLED: VR overlay (OpenXR layer)")

    def __update_openxr_status(self, now: int):
        """Layer state of OpenXR game: logged on change, SteamVR overlay hidden while layer draws"""
        status = self._xr.layer_status() if self._xr is not None else None
        frames = (status.pid, status.frames_shown) if status is not None else None
        last = self._xr_frames
        if frames is not None and last is not None and frames[0] == last[0] and frames[1] > last[1]:
            self._xr_shown_at = now
        self._xr_frames = frames
        # ACTIVE layer may still submit no quad (no layer slot left, image refused): SteamVR overlay kept
        drawing = (status is not None and status.drawing(now) and self._xr_shown_at is not None
                   and now - self._xr_shown_at <= vr_shared.LAYER_TIMEOUT_MS)
        state = (status.pid, status.state, status.graphics_api) if status is not None and status.recent(now) else None
        if state != self._xr_state:
            self._xr_state = state
            if status is not None and state is not None:
                if status.state == vr_shared.LAYER_ACTIVE:
                    logger.info("VR overlay: shown in OpenXR game (%s, process %s)", status.graphics_name, status.pid)
                elif status.state == vr_shared.LAYER_UNSUPPORTED:
                    logger.warning("VR overlay: OpenXR game uses %s, not supported by OpenXR layer "
                                   "(SteamVR overlay or mirror window still work)", status.graphics_name)
                else:
                    logger.warning("VR overlay: OpenXR layer stopped in game (XrResult %s)", status.last_result)
            elif self._xr_drawing:
                logger.info("VR overlay: OpenXR game closed")
        self._xr_drawing = drawing

    def __write_openxr(self, image: QImage | None, checksum: int | None):
        writer = self._xr
        if writer is None:
            return
        if image is None:
            writer.hide()
            self._xr_checksum = None
            return
        if checksum == self._xr_checksum:
            return
        image = fit_image(image, vr_shared.MAX_DIMENSION)
        if image.format() != QImage.Format.Format_RGBA8888:
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        view = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
        try:
            writer.write_image(view, image.width(), image.height(), image.bytesPerLine())
            self._xr_checksum = checksum
        except (ValueError, TypeError, BufferError) as error:
            logger.warning("VR overlay: OpenXR image not written: %s", error)

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
        self.__start_steamvr(setting, report)
        return True

    def __steamvr_unavailable(self, message: str, report: bool):
        self._steamvr_wanted = False
        if report:
            self.__fail(message)
        else:
            logger.info("VR overlay: SteamVR overlay unavailable (%s)", message)

    def __start_steamvr(self, setting: dict, report: bool = False):
        """Start SteamVR overlay if SteamVR is running (never starts SteamVR)"""
        self._steamvr_retry_at = vr_shared.tick_ms() + STEAMVR_RETRY_MS
        if not steamvr_running():
            if report and not self._steamvr_error_shown and self._xr is None:
                logger.info("VR overlay: waiting for SteamVR")
            return
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
        if self._steamvr_wanted and self._overlay is None and now >= self._steamvr_retry_at:
            self.__start_steamvr(cfg.user.config["vr_overlay"])
        overlay = self._overlay
        if overlay is not None:
            # OpenXR game drawn by the layer (also on SteamVR runtime): no second image from SteamVR overlay
            hide = self._xr_drawing
            if hide != self._hidden_for_openxr:
                self._hidden_for_openxr = hide
                try:
                    self.__steamvr_show(self._has_image and not hide)
                except Exception as error:
                    self.__steamvr_stopped(error)
                    overlay = None
                else:
                    logger.info("VR overlay: SteamVR overlay %s", "hidden (OpenXR layer draws it)" if hide else "shown")
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
        self.__write_openxr(image, checksum)
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
        self._has_image = False
        self.__release_steamvr()
        try:
            self.__close_openxr()
        except Exception:
            logger.debug("VR overlay: OpenXR close failed", exc_info=True)

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
