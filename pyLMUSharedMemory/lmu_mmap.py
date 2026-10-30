"""
LMU Memory Map Control

Inherit Python mapping of LMU Shared Memory Interface
"""

from __future__ import annotations

import ctypes
import gc
import logging
import mmap
import platform
from collections.abc import Callable
from typing import Any

try:
    from . import lmu_data
    from .lmu_data import LMUConstants
except ImportError:  # standalone, not package
    import lmu_data
    from lmu_data import LMUConstants

PLATFORM = platform.system()
MAX_VEHICLES = LMUConstants.MAX_MAPPED_VEHICLES
INVALID_INDEX = -1


def get_root_logger_name():
    """Get root logger name"""
    for logger_name in logging.root.manager.loggerDict:
        return logger_name
    return __name__


logger = logging.getLogger(get_root_logger_name())


def no_update() -> None:
    """Update placeholder while mmap is not created (None: unknown whether data changed)"""


def close_mmap(mmap_buffer: mmap.mmap, name: str) -> bool:
    """Close mmap, once more after a garbage collection if a ctypes view of it is only kept alive by a
    reference cycle (direct access), returns True if closed"""
    for collected in (False, True):
        try:
            mmap_buffer.close()
            logger.info("sharedmemory: CLOSED: %s", name)
            return True
        except BufferError:  # exported buffer (struct from_buffer) still referenced
            if not collected:
                gc.collect()
    logger.error("sharedmemory: buffer error while closing %s", name)
    return False


def platform_mmap(name: str, size: int) -> mmap.mmap:
    """Platform memory mapping"""
    if PLATFORM == "Windows":
        return windows_mmap(name, size)
    return linux_mmap(name, size)


def windows_mmap(name: str, size: int) -> mmap.mmap:
    """Windows mmap"""
    return mmap.mmap(-1, size, name)


def linux_mmap(name: str, size: int) -> mmap.mmap:
    """Linux mmap - read data from '/dev/shm/filename' if available"""
    file = open("/dev/shm/" + name, "a+b")
    if file.tell() == 0:
        file.write(b"\0" * size)
        file.flush()
    return mmap.mmap(file.fileno(), size)


class MMapControl:
    """Memory map control"""

    __slots__ = (
        "_mmap_name",
        "_mmap_buffer",
        "_struct",
        "_buffer",
        "_realtime",
        "_heads",
        "update",
        "data",
    )

    def __init__(self, mmap_name: str, data_struct: type[Any]) -> None:
        """Initialize memory map setting

        Args:
            mmap_name: mmap filename.
            data_struct: ctypes data structure, ex. lmu_data.SharedMemoryEvent.
        """
        self._mmap_name = mmap_name
        self._mmap_buffer = None
        self._struct = data_struct
        self._buffer = bytearray()
        self._realtime = None
        # Copy access: (live scoring info, copied scoring info, live first telemetry, copied first telemetry)
        self._heads: tuple | None = None
        # Returns True if data copy updated, False if not (no new data), None if unknown (direct access)
        self.update: Callable[[], bool | None] = no_update
        self.data: Any = None

    def __del__(self):
        logger.info("sharedmemory: GC: MMap %s", self._mmap_name)

    def create(self, access_mode: int = 0) -> None:
        """Create mmap instance & initial accessible copy

        Args:
            access_mode: 0 = copy access, 1 = direct access.
        """
        self._mmap_buffer = platform_mmap(
            name=self._mmap_name,
            size=ctypes.sizeof(self._struct),
        )

        if access_mode:
            self.data = self._struct.from_buffer(self._mmap_buffer)
            self.update = self.__buffer_share
        else:
            self._buffer[:] = self._mmap_buffer
            self._realtime = self._struct.from_buffer(self._mmap_buffer)
            self.data = self._struct.from_buffer(self._buffer)
            self._heads = None  # made by first update
            self.update = self.__buffer_copy

        mode = "Direct" if access_mode else "Copy"
        logger.info("sharedmemory: ACTIVE: %s (%s Access)", self._mmap_name, mode)

    def close(self) -> None:
        """Close memory mapping

        Create a final accessible mmap data copy before closing mmap instance.
        """
        self.data = self._struct.from_buffer_copy(self._mmap_buffer)
        self._realtime = None
        self._heads = None
        close_mmap(self._mmap_buffer, self._mmap_name)
        self.update = no_update  # unassign update method (for proper garbage collection)

    def __buffer_share(self) -> None:
        """Share buffer access, may result data desync (data always live, None: unknown whether changed)"""

    def __buffer_copy(self) -> bool:
        """Copy buffer access, helps avoid data desync

        Returns:
            True if data copy updated, False if not copied or same data (copy unchanged).
        """
        # Check if game updating data
        if (
            self._realtime.generic.events.SME_UPDATE_SCORING
            or self._realtime.generic.events.SME_UPDATE_TELEMETRY
        ) and (
            self._realtime.scoring.scoringInfo.mNumVehicles
            == self._realtime.telemetry.activeVehicles
        ) and self.__changed():
            self._buffer[:] = self._mmap_buffer
            return True
        return False

    def __changed(self) -> bool:
        """Whether shared memory differs from data copy

        Sample times of scoring & first telemetry entry are compared first: while the game runs they change
        nearly every tick, so the full compare (whole structure, same cost as the copy) only runs on same
        times (paused game, menus), where it mostly finds equal data and saves the copy.
        """
        heads = self._heads
        if heads is None:  # wrappers of live & copied structures, made once (ctypes allocates one per access)
            heads = self._heads = (
                self._realtime.scoring.scoringInfo, self.data.scoring.scoringInfo,
                self._realtime.telemetry.telemInfo[0], self.data.telemetry.telemInfo[0],
            )
        live_scor, copy_scor, live_tele, copy_tele = heads
        return (
            live_scor.mCurrentET != copy_scor.mCurrentET
            or live_tele.mElapsedTime != copy_tele.mElapsedTime
            or self._buffer != self._mmap_buffer
        )


def test_api():
    """API test run"""
    # Add logger
    test_handler = logging.StreamHandler()
    logger.setLevel(logging.INFO)
    logger.addHandler(test_handler)

    # Test run
    SEPARATOR = "=" * 50
    print("Test API - Direct Access")
    info = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)
    info.create(1)
    info.update()

    print(SEPARATOR)
    print("Test API - Close")
    info.close()

    print(SEPARATOR)
    print("Test API - Copy Access")
    info.create(0)
    info.update()

    print(SEPARATOR)
    print("Test API - Read")
    version = info.data.generic.gameVersion
    track = info.data.scoring.scoringInfo.mTrackName.decode()
    vehicle = info.data.telemetry.telemInfo[0].mVehicleName.decode()
    total = info.data.scoring.scoringInfo.mNumVehicles
    print(f"version: {version if version else 'not running'}")
    print(f"track name: {track if version else 'not running'}")
    print(f"vehicle name: {vehicle if version else 'not running'}")
    print(f"total cars: {total if version else 'not running'}")

    print(SEPARATOR)
    info.close()


if __name__ == "__main__":
    test_api()
