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
Check for updates
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from typing import NamedTuple

from . import app_signal, version
from .async_request import get_response, set_header_get
from .const_app import APP_NAME, FORK_REPO_NAME
from .const_common import DATE_NA, VERSION_NA
from .setting import cfg
from .version_check import is_new_version, parse_version_string

logger = logging.getLogger(__name__)


RENAMED_REPOS = {"keenny38/overlays": FORK_REPO_NAME}


def update_repository() -> str:
    """Get update repository ("owner/name"), empty if update checking is disabled"""
    repo = str(cfg.application["update_repository"]).strip().strip("/")
    if repo.lower() in RENAMED_REPOS:  # saved before the repository was renamed
        repo = RENAMED_REPOS[repo.lower()]
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return repo
    return ""


def release_url() -> str:
    """Get release page url of update repository"""
    return f"https://github.com/{update_repository() or FORK_REPO_NAME}/releases"


def request_latest_release(repo: str):
    """Setup request for latest release data from github Rest API"""
    uri_path = f"/repos/{repo}/releases/latest"
    host = "api.github.com"
    port = 443
    timeout = 5
    user_agent = f"User-Agent: {APP_NAME}/{version.__version__}"
    request_header = set_header_get(
        uri_path,
        host,
        user_agent,
        "Accept: application/vnd.github+json",
        "X-GitHub-Api-Version: 2022-11-28",
    )
    return get_response(request_header, host, port, timeout, ssl=True)


class InstallerAsset(NamedTuple):
    """Windows installer attached to a release"""

    name: str
    url: str
    sha256_url: str


INSTALLER_SUFFIX = "-windows-setup.exe"
DOWNLOAD_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/")


def parse_installer(data: bytes) -> InstallerAsset | None:
    """Find Windows installer & its sha256 file in github Rest API release response"""
    try:
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        assets = {str(asset["name"]): str(asset["browser_download_url"]) for asset in release["assets"]}
    except (AttributeError, TypeError, IndexError, KeyError, ValueError):
        return None
    for name, url in assets.items():
        sha256_url = assets.get(f"{name}.sha256", "")
        if name.endswith(INSTALLER_SUFFIX) and sha256_url and url.startswith(DOWNLOAD_HOSTS):
            return InstallerAsset(name, url, sha256_url)
    return None


RELEASE_VISUALS_HEADING = "### Visuals"  # see tools/gen_release_notes.py


def parse_release_notes(data: bytes) -> str:
    """Release notes (Markdown body of GitHub release), empty if unavailable

    Visuals section (before / after images of overlays) is left out: images are online only.
    """
    try:
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        body = str(release.get("body") or "")
    except (AttributeError, TypeError, IndexError, ValueError):
        return ""
    return body.split(RELEASE_VISUALS_HEADING, 1)[0].strip()


def can_auto_update() -> bool:
    """Installer update only applies to installed Windows executable"""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def parse_sha256(text: str) -> str:
    """Hash from sha256sum output ("<hash>  <name>")"""
    value = text.strip().split(" ")[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid sha256 file")
    return value


def download_installer(asset: InstallerAsset, folder: str = "", timeout: float = 30) -> str:
    """Download installer, verify sha256, return file path (raise OSError or ValueError)"""
    with urllib.request.urlopen(asset.sha256_url, timeout=timeout) as response:
        expected = parse_sha256(response.read(1024).decode("utf-8", "replace"))
    path = os.path.join(folder or tempfile.gettempdir(), os.path.basename(asset.name))
    digest = hashlib.sha256()
    with urllib.request.urlopen(asset.url, timeout=timeout) as response, open(path, "wb") as file:
        while chunk := response.read(1 << 16):
            digest.update(chunk)
            file.write(chunk)
    if digest.hexdigest() != expected:
        os.remove(path)
        raise ValueError("downloaded installer does not match its sha256 hash")
    return path


def run_installer(path: str) -> None:
    """Start installer silently, it closes TinyPedal and starts it again when done"""
    subprocess.Popen([path, "/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS"], close_fds=True)


def parse_release(data: bytes) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Parse release version & date from github Rest API response"""
    try:
        # Response contains http header, json body starts from first "{"
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        tag = str(release["tag_name"]).lstrip("v").split("-")[0]
        ver_split = tag.split(".")
        date_split = str(release["published_at"]).split("T")[0].split("-")
        return (
            (int(ver_split[0]), int(ver_split[1]), int(ver_split[2])),
            (int(date_split[0]), int(date_split[1]), int(date_split[2])),
        )
    except (AttributeError, TypeError, IndexError, KeyError, ValueError):
        logger.error("UPDATES: error while fetching latest release info")
    return VERSION_NA, DATE_NA


class UpdateChecker:
    """Check for updates"""

    __slots__ = (
        "_is_checking",
        "_update_available",
        "_manual_checking",
        "_last_checked_version",
        "_last_checked_date",
        "_disabled",
        "installer",
        "release_notes",
    )

    def __init__(self):
        self._is_checking = False
        self._update_available = False
        self._manual_checking = False
        self._last_checked_version = VERSION_NA
        self._last_checked_date = DATE_NA
        self._disabled = False
        self.installer: InstallerAsset | None = None
        self.release_notes = ""

    def is_manual(self) -> bool:
        """Is manual checking"""
        return self._manual_checking

    def is_updates(self) -> bool:
        """Is updates available"""
        return self._update_available

    def latest_version(self) -> tuple[int, int, int]:
        """Version of latest release (last check)"""
        return self._last_checked_version

    def latest_date(self) -> tuple[int, int, int]:
        """Release date of latest release (last check)"""
        return self._last_checked_date

    def check(self, manual: bool):
        """Run update check in separated thread"""
        self._manual_checking = manual
        repo = update_repository()
        self._disabled = not repo
        if self._disabled:  # no repository set, skip checking
            self._update_available = False
            if manual:
                app_signal.updates.emit(False)
            logger.info("UPDATES: %s", self.message())
            return
        if not self._is_checking:
            self._is_checking = True
            app_signal.updates.emit(True)
            threading.Thread(target=self.__checking, args=(repo,), daemon=True).start()

    def __checking(self, repo: str):
        """Fetch version info from github Rest API"""
        raw_bytes = asyncio.run(request_latest_release(repo))
        checked_version, checked_date = parse_release(raw_bytes)
        self.installer = parse_installer(raw_bytes)
        self.release_notes = parse_release_notes(raw_bytes)
        current_version = parse_version_string(version.__version__)
        self._update_available = is_new_version(checked_version, current_version, version.DEVELOPMENT)
        # Save info
        self._last_checked_version = checked_version
        self._last_checked_date = checked_date
        # Send update signal
        app_signal.updates.emit(False)
        self._is_checking = False
        # Output log
        logger.info("UPDATES: %s", self.message())

    def message(self) -> str:
        """Get message"""
        if self._disabled:
            return "Update Checking Disabled (Set Update Repository)"
        if self._last_checked_version == VERSION_NA:
            return "Unable To Find Updates"
        if not self._update_available:
            return "No Updates Available"
        return "New Updates: v{}.{}.{} ({}-{}-{})".format(
            *self._last_checked_version,
            *self._last_checked_date,
        )


update_checker = UpdateChecker()
