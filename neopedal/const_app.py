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
Constants
"""

import platform

from . import version_check


# System info
class PLATFORM:
    SYSTEM: str = platform.system()
    WINDOWS: bool = (SYSTEM == "Windows")

# App version
VERSION = version_check.neopedal()

# App info
APP_NAME = "NeoPedal"  # displayed name
APP_ID = "NeoPedal"  # build folder & executable (neopedal.exe)
EXECUTABLE = f"{APP_ID.lower()}.exe"  # Windows executable
# Name of versions until 0.23.0 (executable, plugins API, option keys, remote control header, VR layer):
# only read, for compatibility with older installs, plugins, presets & tools
LEGACY_NAME = "TinyPedal"
LEGACY_PACKAGE = LEGACY_NAME.lower()  # plugins import app modules by this package name
LEGACY_EXECUTABLE = f"{LEGACY_PACKAGE}.exe"
# Fork name of versions until 0.23.0: VR layer copy folder (removed), file formats (still read)
LEGACY_FORK_NAME = "ModernTinyPedals"
LEGACY_FORMAT_PREFIX = "modern-tiny-pedals"
FORMAT_PREFIX = APP_ID.lower()  # format of language packs, race plans & exported histories
CONFIG_ID = "NeoPedal"  # user config & data folders
DESKTOP_FILE_NAME = "NeoPedal"  # Linux desktop entry (NeoPedal.desktop)
RESTART_ENVIRONMENT = "NEOPEDAL_RESTART"  # set by restart, skips single instance check
REPO_NAME = "TinyPedal/TinyPedal"  # upstream project (wiki, credits)
FORK_REPO_NAME = "Keenny38/NeoPedal"  # this fork (releases, updates)
# Names of this fork repository before it was renamed (GitHub redirects them): still official
FORMER_FORK_REPO_NAMES = ("Keenny38/ModernTinyPedals", "Keenny38/overlays")
COPYRIGHT = "Copyright (C) 2022-2026 TinyPedal developers"
# Modified version notice (GPL v3 section 5a), upstream copyright above is kept
MODIFICATION_NOTICE = (
    "NeoPedal is a modified version of TinyPedal. "
    "Modifications copyright (C) 2026 Steven Vezzu and contributors."
)
DESCRIPTION = "Free and Open Source telemetry overlay application for racing simulation."
LICENSE = "Licensed under the GNU General Public License v3.0 or later."

# URL
URL_WEBSITE = f"https://github.com/{REPO_NAME}"  # upstream project (credits)
URL_FORK = f"https://github.com/{FORK_REPO_NAME}"  # this modified version
URL_USER_GUIDE = f"{URL_FORK}/wiki"  # wiki of this version (docs/wiki), not the upstream one
URL_FAQ = f"{URL_FORK}/wiki/Troubleshooting"
URL_RELEASE = f"https://github.com/{FORK_REPO_NAME}/releases"
