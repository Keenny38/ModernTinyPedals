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
Protocol version 2: only the visible parts of the overlay canvas (desktop layout of all widgets) are sent,
as tiles packed in an atlas image; the layer shows each tile as its own quad, where it is on the canvas.
A layer of another version (game started before an app update) draws nothing and reports the mismatch.
"""

from __future__ import annotations

import hashlib
import logging
import ntpath
import os
import shutil
import struct
import sys
import tempfile
import time
from collections.abc import Sequence
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

# Shared memory protocol (tinypedal_vr_shared.h)
MAPPING_NAME = "TinyPedalVROverlay"
MAGIC = 0x52565054  # "TPVR"
VERSION = 2
HEADER_SIZE = 256
DATA_OFFSET = 4096
TILE_OFFSET = 256
TILE_SIZE = 32
MAX_TILES = 16
MAX_CANVAS = 16384
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
LAYER_VERSION_MISMATCH = 4

GRAPHICS_API_NAMES = {0: "none", 1: "D3D11", 2: "D3D12", 3: "Vulkan", 4: "OpenGL", 5: "other"}

# Field offsets
OFFSET_MAGIC = 0  # magic, version, header_size, mapping_size: 4 x uint32
OFFSET_SEQUENCE = 16
OFFSET_APP_HEARTBEAT = 24
OFFSET_FRAME = 32  # "<6I4f3I": atlas width, height, stride, pixel_format, flags, image_serial,
                   # 4 canvas placement floats, data_offset, data_capacity, app_pid
OFFSET_CANVAS = 84  # "<3I": canvas_width, canvas_height, tile_count
OFFSET_LAYER = 128  # written by layer
TILE_FORMAT = "<6I8x"  # atlas_x, atlas_y, width, height, canvas_x, canvas_y
LAYER_FORMAT = "<QIIIiQI"  # heartbeat, pid, state, graphics_api, last_result, frames_shown, version

# Layer files & registration
LAYER_NAME = "XR_APILAYER_TINYPEDAL_overlay"
LAYER_DLL = "TinyPedalXrLayer.dll"
LAYER_MANIFEST = "TinyPedalXrLayer.json"
LAYER_FOLDER = "openxr_layer_bundle"  # in bundled lib folder: copied to LAYER_INSTALL_FOLDER, never loaded there
LAYER_INSTALL_FOLDER = "openxr_layer"  # next to executable: one subfolder per layer build, loaded by games
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


class Tile(NamedTuple):
    """Part of the canvas: width x height pixels at (atlas_x, atlas_y) of the atlas, shown 1:1 at
    (canvas_x, canvas_y) of the canvas"""

    atlas_x: int
    atlas_y: int
    width: int
    height: int
    canvas_x: int
    canvas_y: int


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
    def version_mismatch(self) -> bool:
        """Layer in game speaks another protocol version (game started before app update): draws nothing"""
        return self.state == LAYER_VERSION_MISMATCH or (self.version not in (0, VERSION))

    @property
    def graphics_name(self) -> str:
        return GRAPHICS_API_NAMES.get(self.graphics_api, "unknown")


def cropped_placement(placement: Placement, crop: tuple[int, int, int, int] | None,
                      width: int, height: int) -> Placement:
    """Placement of width x height part at (x, y) of a canvas placed by placement (same scale & position)

    Args:
        crop: (x, y, canvas_width, canvas_height), None if image is the whole canvas.
    """
    if crop is None or crop[2] <= 0 or crop[3] <= 0:
        return placement
    x, y, canvas_width, canvas_height = crop
    scale = placement.width_meters / canvas_width  # meters per pixel
    return placement._replace(
        width_meters=width * scale,
        horizontal_offset_meters=placement.horizontal_offset_meters + (x + (width - canvas_width) / 2) * scale,
        vertical_offset_meters=placement.vertical_offset_meters - (y + (height - canvas_height) / 2) * scale,
    )


def tile_placement(placement: Placement, canvas: tuple[int, int], tile: Tile) -> Placement:
    """Placement of a tile: same position & scale as on the canvas placed by placement (layer's quad_placement)"""
    return cropped_placement(placement, (tile.canvas_x, tile.canvas_y, canvas[0], canvas[1]), tile.width, tile.height)


def pack_atlas(sizes: Sequence[tuple[int, int]], max_width: int = MAX_DIMENSION, max_height: int = MAX_DIMENSION,
               padding: int = 1) -> tuple[list[tuple[int, int]], int, int] | None:
    """Positions of (width, height) rectangles in rows (tallest first), padding pixels apart, so bilinear
    filtering of one tile never reads another one

    Returns:
        (positions in sizes order, atlas width, atlas height), None if they do not fit in max size.
    """
    positions: list[tuple[int, int]] = [(0, 0)] * len(sizes)
    x = y = row_height = width = 0
    for index in sorted(range(len(sizes)), key=lambda item: -sizes[item][1]):
        item_width, item_height = sizes[index]
        if item_width > max_width:
            return None
        if x and x + item_width > max_width:
            y += row_height + padding
            x = row_height = 0
        positions[index] = (x, y)
        width = max(width, x + item_width)
        row_height = max(row_height, item_height)
        x += item_width + padding
    height = y + row_height
    if height > max_height:
        return None
    return positions, width, height


Rect = tuple[int, int, int, int]  # x, y, width, height


def union_rect(first: Rect, second: Rect) -> Rect:
    left, top = min(first[0], second[0]), min(first[1], second[1])
    right = max(first[0] + first[2], second[0] + second[2])
    bottom = max(first[1] + first[3], second[1] + second[3])
    return left, top, right - left, bottom - top


def _near(first: Rect, second: Rect, gap: int) -> bool:
    """Rectangles overlap, or are less than gap pixels apart"""
    return (first[0] < second[0] + second[2] + gap and second[0] < first[0] + first[2] + gap
            and first[1] < second[1] + second[3] + gap and second[1] < first[1] + first[3] + gap)


def cluster_rects(rects: Sequence[Rect], gap: int, max_count: int) -> list[list[int]]:
    """Group rectangles (widgets) into at most max_count tiles: rectangles less than gap pixels apart share a
    tile, tile bounding boxes never overlap, then closest tiles merged (smallest added area) while too many

    Returns:
        Groups of rectangle indexes (increasing, so widgets keep their stacking order), ordered by first index.
    """
    groups = [([index], rect) for index, rect in enumerate(rects)]

    def merge(first: int, second: int):
        indexes = sorted(groups[first][0] + groups[second][0])
        groups[first] = (indexes, union_rect(groups[first][1], groups[second][1]))
        del groups[second]

    def merge_near(distance: int):
        merged = True
        while merged:
            merged = False
            for first in range(len(groups)):
                for second in range(first + 1, len(groups)):
                    if _near(groups[first][1], groups[second][1], distance):
                        merge(first, second)
                        merged = True
                        break
                if merged:
                    break

    merge_near(gap)
    while len(groups) > max(max_count, 1):
        best = None
        for first in range(len(groups)):
            for second in range(first + 1, len(groups)):
                union = union_rect(groups[first][1], groups[second][1])
                growth = union[2] * union[3] - sum(group[1][2] * group[1][3] for group in (groups[first], groups[second]))
                if best is None or growth < best[0]:
                    best = (growth, first, second)
        assert best is not None
        merge(best[1], best[2])
        merge_near(0)  # merged box may cover another tile
    return sorted((group[0] for group in groups), key=lambda indexes: indexes[0])


def tick_ms() -> int:
    """Milliseconds since boot, same clock as the layer (GetTickCount64)"""
    if WINDOWS:
        import ctypes

        function = ctypes.windll.kernel32.GetTickCount64  # type: ignore[attr-defined]
        function.restype = ctypes.c_uint64
        return int(function())
    return int(time.monotonic() * 1000)


# Mapping security: current user, SYSTEM & administrators, writable by medium integrity processes (games not
# run as administrator when the app is)
MAPPING_SDDL = "D:(A;;GA;;;{user})(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;ME)"
PAGE_READWRITE = 0x04


def _current_user_sid() -> str:
    """String SID of the process user (Windows)"""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser: size needed
        buffer = ctypes.create_string_buffer(max(size.value, 1))
        if not advapi32.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER.User.Sid
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        try:
            return str(text.value)
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.CloseHandle(token)


def create_mapping(name: str, size: int) -> int | None:
    """Handle of named shared memory of size bytes, created for the current user at medium integrity
    (MAPPING_SDDL), or opened if it exists (kept by a layer since a previous app run). None if not created.
    Windows only; closed with close_handle."""
    import ctypes
    from ctypes import wintypes

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    kernel32.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                            wintypes.DWORD, wintypes.LPCWSTR]
    kernel32.CreateFileMappingW.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    sddl = MAPPING_SDDL.format(user=_current_user_sid())
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        logger.debug("VR overlay: security descriptor %s refused (error %s)", sddl, ctypes.get_last_error())  # type: ignore[attr-defined]
        return None
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        handle = kernel32.CreateFileMappingW(wintypes.HANDLE(-1), ctypes.byref(attributes), PAGE_READWRITE,
                                             0, size, name)
        if not handle:
            logger.debug("VR overlay: CreateFileMappingW failed (error %s)", ctypes.get_last_error())  # type: ignore[attr-defined]
            return None
        return int(handle)
    finally:
        kernel32.LocalFree(descriptor)


def close_handle(handle: int):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle(handle)


def is_elevated() -> bool:
    """App runs as administrator (Windows)"""
    if not WINDOWS:
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


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
        self._size = (0, 0, 0)  # width, height, stride of last atlas
        self._tiles: tuple[Tile, ...] = ()  # tiles of last atlas
        self._canvas = (0, 0)  # canvas width & height of last atlas
        self.warning: str | None = None  # problem to report to the user (set by open)

    @property
    def is_open(self) -> bool:
        return self._buffer is not None

    def open(self) -> bool:
        """Create (or open, layer may hold it) shared memory, write static header. False if unavailable."""
        if self._buffer is None:
            if not WINDOWS:
                return False
            import mmap

            # Created with an explicit DACL first (app run as administrator, game not: default DACL of an
            # elevated process would deny the game), then mapped by name (opens the existing mapping)
            handle = None
            try:
                handle = create_mapping(MAPPING_NAME, MAPPING_SIZE)
            except Exception:  # ctypes / Windows API error: default security (works unless elevated)
                logger.debug("VR overlay: shared memory with explicit security not created", exc_info=True)
            if handle is None and is_elevated():
                self.warning = ("VR overlay: app runs as administrator, OpenXR games not run as administrator "
                                "may not show the overlay: run the app without administrator rights")
                logger.warning(self.warning)
            try:
                self._mmap = mmap.mmap(-1, MAPPING_SIZE, tagname=MAPPING_NAME)  # type: ignore[call-arg, unused-ignore]
            except (OSError, ValueError) as error:
                logger.warning("VR overlay: OpenXR shared memory not created: %s", error)
                return False
            finally:
                if handle is not None:
                    close_handle(handle)  # mapping kept by the mmap handle
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
        """App alive: written every update tick & every 500 ms (layer stops drawing APP_TIMEOUT_MS after the last one)"""
        if self._buffer is not None:
            struct.pack_into("<Q", self._buffer, OFFSET_APP_HEARTBEAT, tick_ms() if now_ms is None else now_ms)

    def set_placement(self, placement: Placement):
        """New placement, written with next frame (or now if changed)"""
        if placement != self._placement:
            self._placement = placement
            if self._buffer is not None:
                self.__write(None, visible=bool(self._flags & FLAG_VISIBLE))

    def write_image(self, pixels: Any, width: int, height: int, stride: int,
                    crop: tuple[int, int, int, int] | None = None):
        """Show new image (one tile): RGBA8 rows (straight alpha, sRGB colors), stride bytes per row

        Args:
            crop: image is the (x, y) part of a canvas_width x canvas_height canvas (transparent around):
                (x, y, canvas_width, canvas_height), shown where it is on the canvas. None: whole canvas.

        Raises:
            ValueError: image too big for shared memory (caller scales it down first), or crop outside canvas.
        """
        x, y, canvas_width, canvas_height = crop if crop is not None else (0, 0, width, height)
        self.write_tiles(pixels, width, height, stride, [Tile(0, 0, width, height, x, y)], (canvas_width, canvas_height))

    def write_tiles(self, pixels: Any, width: int, height: int, stride: int, tiles: Sequence[Tile],
                    canvas: tuple[int, int]):
        """Show new atlas: RGBA8 rows (straight alpha, sRGB colors), stride bytes per row, of which tiles
        are shown on a canvas_width x canvas_height canvas (placed in VR by placement)

        Raises:
            ValueError: atlas too big for shared memory (caller scales it down first), tiles outside atlas or
                canvas, or too many tiles.
        """
        if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION and stride >= width * 4
                and stride * height <= MAX_IMAGE_BYTES):
            raise ValueError(f"VR overlay image too big for OpenXR layer: {width}x{height}")
        canvas_width, canvas_height = canvas
        if not (0 < canvas_width <= MAX_CANVAS and 0 < canvas_height <= MAX_CANVAS):
            raise ValueError(f"VR overlay canvas too big for OpenXR layer: {canvas_width}x{canvas_height}")
        if not 0 < len(tiles) <= MAX_TILES:
            raise ValueError(f"VR overlay: {len(tiles)} tiles for OpenXR layer (1 to {MAX_TILES})")
        for tile in tiles:
            if (min(tile) < 0 or tile.width < 1 or tile.height < 1
                    or tile.atlas_x + tile.width > width or tile.atlas_y + tile.height > height
                    or tile.canvas_x + tile.width > canvas_width or tile.canvas_y + tile.height > canvas_height):
                raise ValueError(f"VR overlay tile outside atlas or canvas: {tile}")
        if self._buffer is not None:
            self.__write((pixels, width, height, stride, tuple(Tile(*tile) for tile in tiles), canvas), visible=True)

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
            pixels, width, height, stride, tiles, canvas = image
            view = memoryview(pixels).cast("B")
            size = stride * height
            if len(view) < size:
                struct.pack_into("<Q", buffer, OFFSET_SEQUENCE, sequence + 2)
                raise ValueError("VR overlay image buffer smaller than its size")
            buffer[DATA_OFFSET:DATA_OFFSET + size] = view[:size]
            self._serial = (self._serial + 1) & 0xFFFFFFFF
            self._size = (width, height, stride)
            self._tiles = tiles
            self._canvas = canvas
        width, height, stride = self._size
        placement = self._placement  # of the whole canvas: each tile placed by the layer (tile_placement)
        self._flags = (FLAG_VISIBLE if visible and width and self._tiles else 0) | (
            FLAG_ATTACH_TO_HEADSET if placement.attach_to_headset else 0)
        struct.pack_into(
            "<6I4f", buffer, OFFSET_FRAME,
            width, height, stride, FORMAT_RGBA8_STRAIGHT, self._flags, self._serial,
            placement.width_meters, placement.distance_meters,
            placement.vertical_offset_meters, placement.horizontal_offset_meters,
        )
        struct.pack_into("<3I", buffer, OFFSET_CANVAS, *self._canvas, len(self._tiles))
        for index, tile in enumerate(self._tiles):
            struct.pack_into(TILE_FORMAT, buffer, TILE_OFFSET + index * TILE_SIZE, *tile)
        struct.pack_into("<Q", buffer, OFFSET_SEQUENCE, sequence + 2)


# Layer files & registration


def find_layer_manifest() -> str | None:
    """Manifest of the OpenXR layer with its DLL next to it, None if not found

    Release (PyInstaller): lib/openxr_layer_bundle (registered from its copy, see install_layer). From source: native/openxr_layer/build/bin (CMake build),
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


def layer_install_root() -> str | None:
    """Folder of the layer copies loaded by games: next to executable in release, None from source"""
    if not getattr(sys, "frozen", False):
        return None
    return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), LAYER_INSTALL_FOLDER)


def install_layer(manifest: str, root: str) -> str:
    """Copy layer files to their own subfolder of root, named after their content, returns its manifest

    OpenXR games keep the layer DLL loaded, even with the app closed. Loaded from the bundled lib folder,
    which each update deletes & rewrites, it would make the installer close the game or fail. A copy is
    never written again once complete: a new layer build goes to a new folder, older ones removed once
    no game uses them (see remove_old_layers).
    """
    source = os.path.dirname(os.path.abspath(manifest))
    digest = hashlib.sha256()
    for name in (LAYER_DLL, LAYER_MANIFEST):
        with open(os.path.join(source, name), "rb") as file:
            digest.update(file.read())
    folder = os.path.join(root, digest.hexdigest()[:16])
    installed = os.path.join(folder, LAYER_MANIFEST)
    if os.path.isfile(installed) and os.path.isfile(os.path.join(folder, LAYER_DLL)):
        return installed
    os.makedirs(root, exist_ok=True)
    if os.path.isdir(folder):
        shutil.rmtree(folder)  # incomplete copy (raises if its DLL is loaded: registered from bundle)
    temp = tempfile.mkdtemp(prefix=".tmp-", dir=root)
    try:
        for name in (LAYER_DLL, LAYER_MANIFEST):
            shutil.copyfile(os.path.join(source, name), os.path.join(temp, name))
        os.rename(temp, folder)  # complete folder or none
    except OSError:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return installed


def remove_old_layers(root: str, keep: str) -> int:
    """Remove layer copies of root other than folder keep, returns number removed

    Copy still loaded by a running game: its DLL cannot be deleted, folder kept until a later start.
    """
    removed = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or os.path.normcase(os.path.abspath(folder)) == os.path.normcase(
                os.path.abspath(keep)):
            continue
        try:
            dll = os.path.join(folder, LAYER_DLL)
            if os.path.lexists(dll):
                os.remove(dll)  # first: fails while loaded, manifest kept with its DLL
            shutil.rmtree(folder)
            removed += 1
        except OSError:
            logger.debug("VR overlay: OpenXR layer copy %s in use, kept", folder, exc_info=True)
    return removed


def prepare_layer(manifest: str, root: str | None = None) -> str:
    """Manifest to register: copy of bundled layer outside lib folder in release (root default),
    manifest unchanged from source or when copy fails. Older copies removed once the new one is
    registered (remove_old_copies)."""
    if root is None:
        root = layer_install_root()
        if root is None:
            return manifest
    try:
        return install_layer(manifest, root)
    except OSError as error:
        logger.warning("VR overlay: OpenXR layer not copied to %s, registered from %s: %s", root, manifest, error)
        return manifest


def short_path(path: str) -> str | None:
    """8.3 short form of an existing path (Windows), None if unavailable"""
    if not WINDOWS:
        return None
    import ctypes

    function = ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
    size = function(path, None, 0)
    if not size:
        return None
    buffer = ctypes.create_unicode_buffer(size)
    if not function(path, buffer, size):
        return None
    return str(buffer.value)


def ascii_layer_roots() -> list[str]:
    """Folders for a layer copy when its path is not ASCII: ASCII folders users can write without admin
    rights (ProgramData, Public, system drive root), one subfolder per Windows user (removing older copies
    never touches another user's registered copy)"""
    user = hashlib.sha256(os.path.normcase(os.path.expanduser("~")).encode("utf-8")).hexdigest()[:12]
    roots = []
    for base in (os.environ.get("PROGRAMDATA"), os.environ.get("PUBLIC"), os.environ.get("SYSTEMDRIVE", "C:") + "\\"):
        if base and base.isascii():
            roots.append(os.path.join(base, "ModernTinyPedals", LAYER_INSTALL_FOLDER, user))
    return roots


def loadable_manifest(manifest: str, roots: Sequence[str] | None = None) -> str | None:
    """Manifest path the OpenXR loader can open: it reads the registry & manifest with narrow (ANSI)
    APIs, a non-ASCII path (C:\\Users\\Jérôme\\...) is silently ignored. Short (8.3) folder path, else layer
    copied to an ASCII folder (roots, default ascii_layer_roots).

    Returns:
        ASCII manifest path, None if impossible.
    """
    manifest = os.path.abspath(manifest)
    if manifest.isascii():
        return manifest
    folder = short_path(os.path.dirname(manifest))  # file name kept: registry entry found by its name
    if folder is not None and folder.isascii():
        return os.path.join(folder, LAYER_MANIFEST)
    for root in ascii_layer_roots() if roots is None else roots:
        if not root.isascii():
            continue
        try:
            installed = install_layer(manifest, root)  # fails without write permission: next folder
        except OSError as error:
            logger.debug("VR overlay: OpenXR layer not copied to %s: %s", root, error)
            continue
        logger.info("VR overlay: OpenXR layer path not ASCII, copied to %s", installed)
        return installed
    return None


def remove_old_copies(*manifests: str, roots: Sequence[str] | None = None) -> int:
    """Once registered: other layer copies of the folders (roots, default install & ASCII roots) holding
    manifests removed, returns number removed"""
    if roots is None:
        install_root = layer_install_root()
        roots = [*([install_root] if install_root else []), *ascii_layer_roots()]
    known = {os.path.normcase(os.path.abspath(root)) for root in roots}
    removed = 0
    for manifest in manifests:
        folder = os.path.dirname(os.path.abspath(manifest))
        root = os.path.dirname(folder)
        if os.path.normcase(root) in known:
            removed += remove_old_layers(root, folder)
    return removed


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
    """Register layer for current user (enabled), removing TinyPedal entries of other folders.
    Disabled by the user (value not 0, OpenXR layer tools): kept disabled.

    Returns:
        True if registered (or already was).
    """
    reg = _winreg(winreg_module)
    manifest = os.path.abspath(manifest)
    existing = registered_layers(reg)
    disabled = next((value for value in existing.values() if value != 0), 0)
    try:
        key = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, reg.KEY_READ | reg.KEY_SET_VALUE)
    except OSError as error:
        logger.warning("VR overlay: OpenXR layer not registered: %s", error)
        return False
    try:
        if existing.get(manifest) != disabled:
            reg.SetValueEx(key, manifest, 0, reg.REG_DWORD, disabled)  # new entry first: never none
            logger.info("VR overlay: OpenXR layer registered %s", manifest)
        for name in existing:
            if ntpath.normcase(name) != ntpath.normcase(manifest):
                reg.DeleteValue(key, name)  # app moved or other copy: one TinyPedal layer only
                logger.info("VR overlay: removed OpenXR layer registration %s", name)
        if disabled:
            logger.warning("VR overlay: OpenXR layer disabled by user (registry value %s), kept disabled: "
                           "enable it again in your OpenXR layer tool to show the overlay in OpenXR games",
                           disabled)
    except OSError as error:
        logger.warning("VR overlay: OpenXR layer not registered: %s", error)
        return False
    finally:
        reg.CloseKey(key)
    return True


def remove_missing_layers(winreg_module: Any = None) -> int:
    """Remove enabled TinyPedal entries whose manifest or DLL is missing (app moved or uninstalled by hand,
    copy deleted): the OpenXR loader would fail xrCreateInstance in every OpenXR game. Returns number removed."""
    reg = _winreg(winreg_module)
    missing = [name for name, value in registered_layers(reg).items() if value == 0 and not (
        os.path.isfile(name) and os.path.isfile(os.path.join(os.path.dirname(name), LAYER_DLL)))]
    if not missing:
        return 0
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, reg.KEY_SET_VALUE)
    except OSError:
        return 0
    removed = 0
    try:
        for name in missing:
            try:
                reg.DeleteValue(key, name)
                removed += 1
                logger.info("VR overlay: removed OpenXR layer registration of missing files %s", name)
            except OSError:
                logger.debug("VR overlay: cannot remove %s", name, exc_info=True)
    finally:
        reg.CloseKey(key)
    return removed


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
