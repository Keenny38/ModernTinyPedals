"""
PyInstaller hook for optional "openvr" package (SteamVR overlay, see tinypedal/vr_overlay.py)

openvr loads its native library (libopenvr_api_64.dll...) with ctypes from a computed path, which
PyInstaller cannot detect: without this hook the library is left out of the build and
"import openvr" fails with OSError, so the VR overlay never shows in the headset.
Only the library of this platform & Python bitness is kept (package ships all of them), placed in
the "openvr" package folder where openvr looks for it.
"""

import platform
import struct

from PyInstaller.utils.hooks import collect_dynamic_libs


def library_pattern(system: str, bits: int) -> str:
    """openvr library file name used on platform (same choice as openvr/__init__.py)"""
    if system == "Darwin":
        return "libopenvr_api_32.dylib"  # universal library
    if system == "Windows":
        return f"libopenvr_api_{bits}.dll"
    return f"libopenvr_api_{bits}.so"


binaries = collect_dynamic_libs(
    "openvr", search_patterns=[library_pattern(platform.system(), struct.calcsize("P") * 8)])
