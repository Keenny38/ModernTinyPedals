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
OpenXR overlay bridge (Windows): app side of the OpenXR API layer (native/openxr_layer)

The layer (TinyPedalXrLayer.dll) is loaded by the OpenXR loader in every OpenXR game, on every runtime
(SteamVR, Meta / Air Link, Virtual Desktop, WMR, Pimax, Varjo...), once registered as an implicit API layer
for the current user (HKEY_CURRENT_USER, no admin rights). It draws the image this module writes to a named
shared memory, as a quad layer after the game's layers.

Registration is kept while `enable_vr_overlay` is on, also when the app is closed: the layer does nothing
(pure pass-through) without a recent app heartbeat, so a game started before the app shows the overlay as
soon as the app runs. Turning the option off removes the registration; the installer removes it on uninstall.

Shared memory layout: native/openxr_layer/include/tinypedal_vr_shared.h (kept in sync, see tests).
"""

from __future__ import annotations

import logging
import ntpath
import os
import struct
import sys
import time
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

# Shared memory protocol (tinypedal_vr_shared.h)
MAPPING_NAME = "TinyPedalVROverlay"
MAGIC = 0x52565054  # "TPVR"
VERSION = 1
HEADER_SIZE = 256
DATA_OFFSET = 4096
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAPPING_SIZE = DATA_OFFSET + MAX_IMAGE_BYTES
MAX_DIMENSION = 4096
APP_TIMEOUT_MS = 2000
LAYER_TIMEOUT_MS = 1000

FORMAT_RGBA8_STRAIGHT = 1
FORMAT_RGBA8_PREMULTIPLIED = 2
FLAG_VISIBLE = 0x1
FLAG_ATTACH_TO_HEADSET = 0x2

LAYER_IDLE = 0
LAYER_ACTIVE = 1
LAYER_UNSUPPORTED = 2
LAYER_FAILED = 3

GRAPHICS_API_NAMES = {0: "none", 1: "D3D11", 2: "D3D12", 3: "Vulkan", 4: "OpenGL", 5: "other"}

# Field offsets
OFFSET_MAGIC = 0  # magic, version, header_size, mapping_size: 4 x uint32
OFFSET_SEQUENCE = 16
OFFSET_APP_HEARTBEAT = 24
OFFSET_FRAME = 32  # "<6I4f3I": width, height, stride, pixel_format, flags, image_serial,
                   # 4 placement floats, data_offset, data_capacity, app_pid
OFFSET_LAYER = 128  # written by layer
LAYER_FORMAT = "<QIIIiQI"  # heartbeat, pid, state, graphics_api, last_result, frames_shown, version

# Layer files & registration
LAYER_NAME = "XR_APILAYER_TINYPEDAL_overlay"
LAYER_DLL = "TinyPedalXrLayer.dll"
LAYER_MANIFEST = "TinyPedalXrLayer.json"
LAYER_FOLDER = "openxr_layer"  # in bundled lib folder
REGISTRY_KEY = r"SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit"
DISABLE_ENVIRONMENT = "DISABLE_TINYPEDAL_XR_LAYER"

WINDOWS = sys.platform == "win32"


class Placement(NamedTuple):
    """Overlay placement in meters (same settings as the SteamVR overlay)"""

    width_meters: float
    distance_meters: float
    vertical_offset_meters: float
    horizontal_offset_meters: float
    attach_to_headset: bool


class LayerStatus(NamedTuple):
    """State written back by the layer of the last OpenXR game frame"""

    heartbeat_ms: int
    pid: int
    state: int
    graphics_api: int
    last_result: int
    frames_shown: int
    version: int

    def recent(self, now_ms: int) -> bool:
        """Layer wrote during the last second (an OpenXR game is rendering frames)"""
        return self.heartbeat_ms != 0 and abs(now_ms - self.heartbeat_ms) <= LAYER_TIMEOUT_MS

    def drawing(self, now_ms: int) -> bool:
        """An OpenXR game shows the overlay (supported graphics API, no error)"""
        return self.recent(now_ms) and self.state == LAYER_ACTIVE

    @property
    def graphics_name(self) -> str:
        return GRAPHICS_API_NAMES.get(self.graphics_api, "unknown")


def tick_ms() -> int:
    """Milliseconds since boot, same clock as the layer (GetTickCount64)"""
    if WINDOWS:
        import ctypes

        function = ctypes.windll.kernel32.GetTickCount64  # type: ignore[attr-defined]
        function.restype = ctypes.c_uint64
        return int(function())
    return int(time.monotonic() * 1000)


class SharedFrameWriter:
    """Write overlay frames for the OpenXR layer (seqlock: never a torn image)

    Args:
        buffer: writable buffer of MAPPING_SIZE bytes (tests), else named shared memory (Windows).
    """

    def __init__(self, buffer: Any = None):
        self._buffer = buffer
        self._mmap: Any = None
        self._serial = 0
        self._flags = 0
        self._placement = Placement(0.8, 1.0, -0.2, 0.0, False)
        self._size = (0, 0, 0)  # width, height, stride of last image

    @property
    def is_open(self) -> bool:
        return self._buffer is not None

    def open(self) -> bool:
        """Create (or open, layer may hold it) shared memory, write static header. False if unavailable."""
        if self._buffer is None:
            if not WINDOWS:
                return False
            import mmap

            try:
                self._mmap = mmap.mmap(-1, MAPPING_SIZE, tagname=MAPPING_NAME)  # type: ignore[call-arg, unused-ignore]
            except (OSError, ValueError) as error:
                logger.warning("VR overlay: OpenXR shared memory not created: %s", error)
                return False
            self._buffer = self._mmap
        buffer = self._buffer
        if len(buffer) < MAPPING_SIZE:
            self.close()
            return False
        # Kept from a previous app run (layer holds mapping): continue sequence & image serial
        sequence = struct.unpack_from("<Q", buffer, OFFSET_SEQUENCE)[0]
        if sequence & 1:
            sequence += 1  # app closed while writing
        self._serial = struct.unpack_from("<I", buffer, OFFSET_FRAME + 20)[0]
        struct.pack_into("<Q", buffer, OFFSET_SEQUENCE, sequence + 1)  # odd: header not complete
        struct.pack_into("<4I", buffer, OFFSET_MAGIC, MAGIC, VERSION, HEADER_SIZE, MAPPING_SIZE)
        struct.pack_into("<I", buffer, OFFSET_FRAME + 16, 0)  # flags: nothing shown yet
        struct.pack_into("<3I", buffer, OFFSET_FRAME + 40, DATA_OFFSET, MAX_IMAGE_BYTES, os.getpid())
        struct.pack_into("<Q", buffer, OFFSET_SEQUENCE, sequence + 2)
        self.heartbeat()
        return True

    def close(self):
        """Nothing shown any more (layer sees heartbeat 0 at once), shared memory released"""
        buffer = self._buffer
        if buffer is not None:
            try:
                self.__write(None, visible=False)
                struct.pack_into("<Q", buffer, OFFSET_APP_HEARTBEAT, 0)
            except (TypeError, ValueError, struct.error):  # mapping already closed
                pass
        if self._mmap is not None:
            try:
                self._mmap.close()
            except (OSError, ValueError, BufferError):
                logger.debug("VR overlay: shared memory close failed", exc_info=True)
        self._mmap = None
        self._buffer = None

    def heartbeat(self, now_ms: int | None = None):
        """App alive: written every update tick (layer stops drawing APP_TIMEOUT_MS after the last one)"""
        if self._buffer is not None:
            struct.pack_into("<Q", self._buffer, OFFSET_APP_HEARTBEAT, tick_ms() if now_ms is None else now_ms)

    def set_placement(self, placement: Placement):
        """New placement, written with next frame (or now if changed)"""
        if placement != self._placement:
            self._placement = placement
            if self._buffer is not None:
                self.__write(None, visible=bool(self._flags & FLAG_VISIBLE))

    def write_image(self, pixels: Any, width: int, height: int, stride: int):
        """Show new image: RGBA8 rows (straight alpha, sRGB colors), stride bytes per row

        Raises:
            ValueError: image too big for shared memory (caller scales it down first).
        """
        if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION and stride >= width * 4
                and stride * height <= MAX_IMAGE_BYTES):
            raise ValueError(f"VR overlay image too big for OpenXR layer: {width}x{height}")
        if self._buffer is not None:
            self.__write((pixels, width, height, stride), visible=True)

    def hide(self):
        """Nothing shown (all overlays hidden)"""
        if self._buffer is not None and self._flags & FLAG_VISIBLE:
            self.__write(None, visible=False)

    def layer_status(self) -> LayerStatus | None:
        """Last state written by the layer, None if shared memory not open"""
        if self._buffer is None:
            return None
        return LayerStatus(*struct.unpack_from(LAYER_FORMAT, self._buffer, OFFSET_LAYER))

    def __write(self, image: tuple | None, visible: bool):
        """Seqlock write: sequence odd, fields (& pixels), sequence even"""
        buffer = self._buffer
        sequence = struct.unpack_from("<Q", buffer, OFFSET_SEQUENCE)[0]
        if sequence & 1:
            sequence += 1
        struct.pack_into("<Q", buffer, OFFSET_SEQUENCE, sequence + 1)
        if image is not None:
            pixels, width, height, stride = image
            view = memoryview(pixels).cast("B")
            size = stride * height
            if len(view) < size:
                struct.pack_into("<Q", buffer, OFFSET_SEQUENCE, sequence + 2)
                raise ValueError("VR overlay image buffer smaller than its size")
            buffer[DATA_OFFSET:DATA_OFFSET + size] = view[:size]
            self._serial = (self._serial + 1) & 0xFFFFFFFF
            self._size = (width, height, stride)
        width, height, stride = self._size
        placement = self._placement
        self._flags = (FLAG_VISIBLE if visible and width else 0) | (
            FLAG_ATTACH_TO_HEADSET if placement.attach_to_headset else 0)
        struct.pack_into(
            "<6I4f", buffer, OFFSET_FRAME,
            width, height, stride, FORMAT_RGBA8_STRAIGHT, self._flags, self._serial,
            placement.width_meters, placement.distance_meters,
            placement.vertical_offset_meters, placement.horizontal_offset_meters,
        )
        struct.pack_into("<Q", buffer, OFFSET_SEQUENCE, sequence + 2)


# Layer files & registration


def find_layer_manifest() -> str | None:
    """Manifest of the OpenXR layer with its DLL next to it, None if not found

    Release (PyInstaller): lib/openxr_layer. From source: native/openxr_layer/build/bin (CMake build),
    or folder given by TINYPEDAL_XR_LAYER_DIR.
    """
    folders = []
    override = os.environ.get("TINYPEDAL_XR_LAYER_DIR")
    if override:
        folders.append(override)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        folders.append(os.path.join(bundle, LAYER_FOLDER))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    folders.append(os.path.join(root, "native", "openxr_layer", "build", "bin"))
    for folder in folders:
        manifest = os.path.join(folder, LAYER_MANIFEST)
        # Manifest without loadable DLL would make the OpenXR loader fail game startup: both required
        if os.path.isfile(manifest) and os.path.isfile(os.path.join(folder, LAYER_DLL)):
            return os.path.abspath(manifest)
    return None


def is_layer_entry(name: str) -> bool:
    """Registry value of a TinyPedal layer manifest (any install folder)"""
    return ntpath.basename(name).lower() == LAYER_MANIFEST.lower()


def _winreg(module: Any = None) -> Any:
    if module is not None:
        return module
    import winreg  # Windows only

    return winreg


def registered_layers(winreg_module: Any = None) -> dict[str, int]:
    """TinyPedal layer entries of current user: manifest path -> value (0 enabled)"""
    reg = _winreg(winreg_module)
    entries: dict[str, int] = {}
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, reg.KEY_READ)
    except OSError:
        return entries
    try:
        index = 0
        while True:
            try:
                name, value, _ = reg.EnumValue(key, index)
            except OSError:  # no more values
                break
            index += 1
            if is_layer_entry(name):
                entries[name] = value
    finally:
        reg.CloseKey(key)
    return entries


def register_layer(manifest: str, winreg_module: Any = None) -> bool:
    """Register layer for current user (enabled), removing TinyPedal entries of other folders

    Returns:
        True if registered (or already was).
    """
    reg = _winreg(winreg_module)
    manifest = os.path.abspath(manifest)
    existing = registered_layers(reg)
    try:
        key = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, reg.KEY_READ | reg.KEY_SET_VALUE)
    except OSError as error:
        logger.warning("VR overlay: OpenXR layer not registered: %s", error)
        return False
    try:
        for name in existing:
            if ntpath.normcase(name) != ntpath.normcase(manifest):
                reg.DeleteValue(key, name)  # app moved or other copy: one TinyPedal layer only
                logger.info("VR overlay: removed OpenXR layer registration %s", name)
        if existing.get(manifest) != 0:
            reg.SetValueEx(key, manifest, 0, reg.REG_DWORD, 0)
            logger.info("VR overlay: OpenXR layer registered %s", manifest)
    except OSError as error:
        logger.warning("VR overlay: OpenXR layer not registered: %s", error)
        return False
    finally:
        reg.CloseKey(key)
    return True


def unregister_layer(winreg_module: Any = None) -> int:
    """Remove every TinyPedal layer entry of current user, returns number removed"""
    reg = _winreg(winreg_module)
    existing = registered_layers(reg)
    if not existing:
        return 0
    removed = 0
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, reg.KEY_SET_VALUE)
    except OSError:
        return 0
    try:
        for name in existing:
            try:
                reg.DeleteValue(key, name)
                removed += 1
            except OSError:
                logger.debug("VR overlay: cannot remove %s", name, exc_info=True)
    finally:
        reg.CloseKey(key)
    if removed:
        logger.info("VR overlay: OpenXR layer unregistered")
    return removed
