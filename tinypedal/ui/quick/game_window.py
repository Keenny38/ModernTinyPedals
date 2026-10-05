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
Game window of LMU (Windows): middle click posted to it, as the player does in game

The web UI of the game hides & shows its panels (top bar, standings, replay bar) and HUD on a middle click
in its watch & replay screens; its Rest API has no command for it. The click is posted to the game window
only (found by game executable name): mouse cursor & window focus are left as they are.
"""

from __future__ import annotations

import sys
import time

GAME_EXECUTABLE = "le mans ultimate"  # in executable path of game process
WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON = 0x0207, 0x0208, 0x0010
CLICK_SECONDS = 0.06  # button held: game reads mouse buttons once per frame, a shorter click is missed
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_path(pid: int) -> str:
    """Executable path of process, "" if unknown"""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def find_game_window() -> tuple[int, int, int]:
    """Largest visible window of game process: handle, client width & height, (0, 0, 0) if none"""
    if sys.platform != "win32":
        return 0, 0, 0
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if GAME_EXECUTABLE in process_path(pid.value).lower():
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                found.append((int(hwnd), rect.right, rect.bottom))
        return True

    user32.EnumWindows(visit, 0)
    return max(found, key=lambda window: window[1] * window[2], default=(0, 0, 0))


def middle_click(window: tuple[int, int, int]) -> bool:
    """Middle click posted to center of window (handle, width, height), button held a frame or more
    (blocks CLICK_SECONDS: call from a background thread)"""
    hwnd, width, height = window
    if not hwnd or sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    position = (max(height, 2) // 2 << 16) | (max(width, 2) // 2)
    pressed = user32.PostMessageW(hwnd, WM_MBUTTONDOWN, MK_MBUTTON, position)
    time.sleep(CLICK_SECONDS)
    released = user32.PostMessageW(hwnd, WM_MBUTTONUP, 0, position)
    return bool(pressed and released)


def middle_click_game() -> bool:
    """Middle click posted to center of game window, False if game window not found"""
    return middle_click(find_game_window())
