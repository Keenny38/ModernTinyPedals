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
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from contextlib import suppress
from typing import NamedTuple

from . import app_signal, version
from .async_request import get_response, set_header_get
from .const_app import APP_NAME, FORK_REPO_NAME
from .const_common import DATE_NA, VERSION_NA
from .const_file import ConfigType
from .i18n import current_language
from .setting import cfg
from .version_check import is_new_version, parse_version_string

logger = logging.getLogger(__name__)


def version_number(version_tuple: tuple[int, int, int]) -> int:
    """Version as one number (major * 1000000 + minor * 1000 + patch), stored in config"""
    major, minor, patch = version_tuple
    return major * 1_000_000 + minor * 1000 + patch


def skipped_version() -> int:
    """Update version skipped by user (see version_number), 0 if none"""
    value = cfg.application.get("skipped_update_version", 0)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def skip_version(version_tuple: tuple[int, int, int]):
    """Update notice of version not shown again (a newer version is), saved in config"""
    cfg.application["skipped_update_version"] = version_number(version_tuple)
    cfg.save(config_type=ConfigType.CONFIG)
    logger.info("UPDATES: version %s skipped", ".".join(map(str, version_tuple)))


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
    """Windows installer attached to a release: setup ZIP (installer inside) or installer itself"""

    name: str
    url: str
    sha256: str  # expected hash of downloaded file
    repository: str = ""  # update repository it was found in (at check time), see verify_installer


# Release files: "<name>-<version>-setup.zip" (installer "<name>-<version>-windows-setup.exe" inside)
# and "<name>-<version>-source.zip". Releases before 0.20.0 attached the installer itself.
INSTALLER_SUFFIXES = ("-setup.zip", "-windows-setup.exe")
DOWNLOAD_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/")


def release_hash(release: dict, name: str) -> str:
    """SHA-256 of release file: asset digest given by GitHub, else the SHA256 list of release notes"""
    for asset in release.get("assets", ()):
        if not isinstance(asset, dict):
            continue
        digest = str(asset.get("digest") or "")
        if asset.get("name") == name and digest.lower().startswith("sha256:"):
            with suppress(ValueError):
                return parse_sha256(digest[7:])
    # Release notes lines "- `<hash>  <file>`" (tools/gen_release_notes.py & release workflow)
    match = re.search(rf"\b([0-9a-fA-F]{{64}})\s+\*?{re.escape(name)}\b", str(release.get("body") or ""))
    return match.group(1).lower() if match else ""


def parse_installer(data: bytes, repository: str = "") -> InstallerAsset | None:
    """Find Windows installer & its hash in github Rest API release response, None if no verifiable installer

    Args:
        repository: update repository the release comes from, kept with the installer.
    """
    try:
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        assets = {str(asset["name"]): str(asset["browser_download_url"]) for asset in release["assets"]}
    except (AttributeError, TypeError, IndexError, KeyError, ValueError):
        return None
    for suffix in INSTALLER_SUFFIXES:  # setup ZIP first
        for name, url in assets.items():
            if not name.endswith(suffix) or not url.startswith(DOWNLOAD_HOSTS):
                continue
            sha256 = release_hash(release, name)
            if sha256:
                return InstallerAsset(name, url, sha256, repository)
    return None


RELEASE_VISUALS_HEADING = "### Visuals"  # see tools/gen_release_notes.py
RELEASE_DETAILS_HEADING = "## Commits"  # technical part of release notes (commits by kind, checksums)


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


def parse_release_tag(data: bytes) -> str:
    """Tag name of release in github Rest API response, empty if invalid"""
    try:
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        tag = str(release["tag_name"])
    except (AttributeError, TypeError, IndexError, KeyError, ValueError):
        return ""
    return tag if re.fullmatch(r"[\w.+-]+", tag) else ""


# Changelog: CHANGELOG.md in English (also the GitHub release notes), translations in
# CHANGELOG.<language code>.md (CHANGELOG.fr.md), with the same "## X.Y.Z (date)" sections
CHANGELOG_FILE = "CHANGELOG.md"
MAX_CHANGELOG_SIZE = 4 * 1024 * 1024


def changelog_sections(text: str) -> list[tuple[str, str]]:
    """Changelog sections (version, body) in file order, text before first "## " heading left out"""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].split(" ")[0], []))
        elif sections:
            sections[-1][1].append(line)
    return [(name, "\n".join(body).strip()) for name, body in sections]


def changelog_section(text: str, version: str) -> str:
    """Body of version section in changelog, empty if none"""
    return next((body for name, body in changelog_sections(text) if name == version), "")


def localized_changelog_name(language: str, filename: str = CHANGELOG_FILE) -> str:
    """Changelog file of language (CHANGELOG.fr.md), English changelog for English or invalid code"""
    if language == "en" or not re.fullmatch(r"[a-z]{2,3}(_[A-Za-z]{2,4})?", language):
        return filename
    root, ext = os.path.splitext(filename)
    return f"{root}.{language}{ext}"


def localize_release_notes(notes: str, summary: str) -> str:
    """Release notes with changelog part replaced by translated changelog section

    Technical details (commits, checksums) are kept as they are. Notes without written
    changelog (commits only) get the translated section first.
    """
    summary = summary.strip()
    if not summary:
        return notes
    _, heading, details = notes.partition(RELEASE_DETAILS_HEADING)
    if heading:
        return f"{summary}\n\n{heading}{details}"
    if notes.lstrip().startswith("### "):  # commits by kind only
        return f"{summary}\n\n{RELEASE_DETAILS_HEADING}\n\n{notes.strip()}"
    return summary


def fetch_localized_summary(repo: str, tag: str, language: str, timeout: float = 5) -> str:
    """Translated changelog section of release (CHANGELOG.<language>.md at release tag), empty if none"""
    filename = localized_changelog_name(language)
    if filename == CHANGELOG_FILE or not tag or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return ""
    url = f"https://raw.githubusercontent.com/{repo}/{tag}/{filename}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            text = response.read(MAX_CHANGELOG_SIZE).decode("utf-8", "replace")
    except (OSError, ValueError) as error:  # not translated (404), offline
        logger.info("UPDATES: no %s release notes: %s", language, error)
        return ""
    version = tag.lstrip("v").split("-")[0]
    return changelog_section(text, version)


UNINSTALLER_NAME = "unins000.exe"  # left next to app executable by installer (Inno Setup)


def is_frozen_windows() -> bool:
    """Windows executable (installed or portable), not run from source"""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def is_installed_copy() -> bool:
    """Executable installed by installer (uninstaller next to it), not a portable ZIP copy"""
    return os.path.isfile(os.path.join(os.path.dirname(sys.executable), UNINSTALLER_NAME))


def can_auto_update() -> bool:
    """Installer update applies to Windows executable installed by installer, or run from source on Windows

    Run from source: installer updates the installed app (installed if none), like run by hand.
    Portable ZIP copy (published until 0.19) keeps presets & data in its own folder: installer
    would install another copy elsewhere, starting with default presets and no data.
    """
    if is_frozen_windows():
        return is_installed_copy()
    return sys.platform == "win32"


def is_portable_copy() -> bool:
    """Windows executable from portable ZIP: installer run by hand, into the folder of this copy"""
    return is_frozen_windows() and not is_installed_copy()


APP_EXECUTABLE = "tinypedal.exe"  # installer/tinypedal.iss AppExe
INSTALLER_APP_ID = "{6C3F5B8E-4A2D-4E1B-9C7A-1D2E3F4A5B6C}"  # installer/tinypedal.iss AppId
# Start menu shortcut of app, written by installer at every install (installer/tinypedal.iss Icons)
START_MENU_SHORTCUT = os.path.join(
    "Microsoft", "Windows", "Start Menu", "Programs", "Modern Tiny Pedals", "Modern Tiny Pedals.lnk")


def is_install_folder(folder: str) -> bool:
    """Folder of app installed by installer: executable & uninstaller"""
    return bool(folder) and all(
        os.path.isfile(os.path.join(folder, name)) for name in (APP_EXECUTABLE, UNINSTALLER_NAME))


def registry_install_folder() -> str:
    """Install folder recorded by installer in registry (current user), empty if none"""
    if sys.platform != "win32":  # Windows registry only (also skips type checking on other platforms)
        return ""
    import winreg

    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{INSTALLER_APP_ID}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "Inno Setup: App Path")
    except OSError:
        return ""
    return value if isinstance(value, str) else ""


def _link_string(data: bytes, offset: int, unicode: bool) -> str:
    """Null terminated string of shortcut data (UTF-16 or system code page)"""
    if offset <= 0 or offset >= len(data):
        raise ValueError("invalid shortcut string offset")
    if unicode:
        end = offset
        while data[end:end + 2] not in (b"\x00\x00", b""):
            end += 2
        return data[offset:end].decode("utf-16-le")
    end = data.find(b"\x00", offset)
    return data[offset:end if end >= 0 else len(data)].decode("mbcs" if sys.platform == "win32" else "latin-1")


def shortcut_target(path: str) -> str:
    """Local target file of Windows shortcut (.lnk, MS-SHLLINK format), empty if none or unreadable"""
    try:
        with open(path, "rb") as file:
            data = file.read(1 << 16)
        if len(data) < 76 or int.from_bytes(data[:4], "little") != 0x4C:
            return ""
        flags = int.from_bytes(data[20:24], "little")
        offset = 76  # after header
        if flags & 0x01:  # HasLinkTargetIDList: skipped
            offset += 2 + int.from_bytes(data[offset:offset + 2], "little")
        if not flags & 0x02:  # no HasLinkInfo
            return ""
        info = data[offset:offset + int.from_bytes(data[offset:offset + 4], "little")]
        if not int.from_bytes(info[8:12], "little") & 0x01:  # no VolumeIDAndLocalBasePath: not a local file
            return ""
        if int.from_bytes(info[4:8], "little") >= 0x24:  # header with Unicode paths
            base = _link_string(info, int.from_bytes(info[28:32], "little"), True)
            suffix_offset = int.from_bytes(info[32:36], "little")
            suffix = _link_string(info, suffix_offset, True) if suffix_offset else ""
        else:
            base = _link_string(info, int.from_bytes(info[16:20], "little"), False)
            suffix_offset = int.from_bytes(info[24:28], "little")
            suffix = _link_string(info, suffix_offset, False) if suffix_offset else ""
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    return base + suffix


def installed_app_folder() -> str:
    """Folder of the app installed by installer on this computer, empty if none found

    Registry first (folder reused by installer), then Start menu shortcut: registry seen by
    a packaged (MSIX) app and the programs it starts can be its own stale copy.
    """
    candidates = [registry_install_folder()]
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        target = shortcut_target(os.path.join(appdata, START_MENU_SHORTCUT))
        if os.path.basename(target).lower() == APP_EXECUTABLE:
            candidates.append(os.path.dirname(target))
    for folder in candidates:
        if is_install_folder(folder):
            return os.path.normpath(folder)
    return ""


def install_folder() -> str:
    """Folder updated by installer: this installed copy, else installed app found (run from source)

    Empty: installer picks it (previous install folder, or default folder for a first install).
    """
    if is_frozen_windows():
        return os.path.dirname(sys.executable) if is_installed_copy() else ""
    return installed_app_folder() if sys.platform == "win32" else ""


def parse_sha256(text: str) -> str:
    """Hash from sha256sum output ("<hash>  <name>", any whitespace)"""
    parts = text.split()
    value = parts[0].lower() if parts else ""
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid sha256 file")
    return value


class DownloadCancelled(Exception):
    """Download cancelled by user"""


def content_length(response) -> int:
    """Size announced by download response, 0 if unknown"""
    headers = getattr(response, "headers", None)
    try:
        return max(int(headers.get("Content-Length", 0)), 0) if headers is not None else 0
    except (TypeError, ValueError):
        return 0


def download_installer(
    asset: InstallerAsset,
    folder: str = "",
    timeout: float = 30,
    progress: Callable[[int, int], object] | None = None,
    cancelled: threading.Event | None = None,
) -> str:
    """Download installer, verify sha256, return installer path (raise OSError or ValueError)

    Data is downloaded to a ".part" file first, removed if download fails, hash mismatches
    or download is cancelled. Setup ZIP: installer is extracted next to it, ZIP removed.

    Args:
        progress: called with received & total bytes (0 if unknown) after each chunk, from download thread.
        cancelled: download stopped (raise DownloadCancelled) once set.
    """
    expected = parse_sha256(asset.sha256)
    folder = folder or tempfile.gettempdir()
    path = os.path.join(folder, os.path.basename(asset.name))
    part_path = f"{path}.part"
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(asset.url, timeout=timeout) as response, open(part_path, "wb") as file:
            total = content_length(response)
            received = 0
            while chunk := response.read(1 << 16):
                if cancelled is not None and cancelled.is_set():
                    raise DownloadCancelled("download cancelled")
                digest.update(chunk)
                file.write(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, total)
            if cancelled is not None and cancelled.is_set():
                raise DownloadCancelled("download cancelled")
        if digest.hexdigest() != expected:
            raise ValueError("downloaded installer does not match its sha256 hash")
        os.replace(part_path, path)
    except BaseException:  # partial or invalid download never left behind
        with suppress(OSError):
            os.remove(part_path)
        raise
    if not path.lower().endswith(".zip"):
        return path
    try:
        return extract_installer(path, folder)
    finally:
        with suppress(OSError):
            os.remove(path)


MAX_INSTALLER_SIZE = 1 << 30  # extracted installer size limit


def extract_installer(zip_path: str, folder: str) -> str:
    """Extract the installer (only executable) of setup ZIP to folder, return its path (raise OSError or ValueError)"""
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = [info for info in archive.infolist()
                       if not info.is_dir() and info.filename.lower().endswith(".exe")]
            if len(members) != 1:
                raise ValueError("setup archive does not contain one installer")
            info = members[0]
            if info.file_size > MAX_INSTALLER_SIZE:
                raise ValueError("installer in setup archive is too large")
            # File name only: never a path from the archive
            path = os.path.join(folder, os.path.basename(info.filename.replace("\\", "/")))
            part_path = f"{path}.part"
            try:
                with archive.open(info) as source, open(part_path, "wb") as target:
                    shutil.copyfileobj(source, target, 1 << 16)
                os.replace(part_path, path)
            except BaseException:
                with suppress(OSError):
                    os.remove(part_path)
                raise
    except zipfile.BadZipFile as error:  # also CRC mismatch while reading
        raise ValueError(f"invalid setup archive: {error}") from error
    return path


# Authenticode (WinVerifyTrust) result
SIGNATURE_VALID = "valid"
SIGNATURE_UNSIGNED = "unsigned"
SIGNATURE_INVALID = "invalid"
SIGNATURE_UNKNOWN = "unknown"  # not checked (not Windows, check unavailable)


def installer_signature(path: str) -> str:
    """Authenticode signature state of file: valid, unsigned, invalid, or unknown"""
    if sys.platform != "win32":
        return SIGNATURE_UNKNOWN
    try:
        return _win_verify_trust(path)
    except (AttributeError, OSError, ValueError) as error:
        logger.error("UPDATES: unable to check installer signature: %s", error)
        return SIGNATURE_UNKNOWN


def _win_verify_trust(path: str) -> str:
    """Check embedded Authenticode signature with WinVerifyTrust (no UI, no network)"""
    if sys.platform != "win32":  # Windows API only (also skips type checking on other platforms)
        raise OSError("WinVerifyTrust is only available on Windows")
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    class WintrustFileInfo(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pcwszFilePath", wintypes.LPCWSTR),
            ("hFile", wintypes.HANDLE),
            ("pgKnownSubject", ctypes.c_void_p),
        ]

    class WintrustData(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pPolicyCallbackData", ctypes.c_void_p),
            ("pSIPClientData", ctypes.c_void_p),
            ("dwUIChoice", wintypes.DWORD),
            ("fdwRevocationChecks", wintypes.DWORD),
            ("dwUnionChoice", wintypes.DWORD),
            ("pFile", ctypes.POINTER(WintrustFileInfo)),
            ("dwStateAction", wintypes.DWORD),
            ("hWVTStateData", wintypes.HANDLE),
            ("pwszURLReference", wintypes.LPCWSTR),
            ("dwProvFlags", wintypes.DWORD),
            ("dwUIContext", wintypes.DWORD),
            ("pSignatureSettings", ctypes.c_void_p),
        ]

    # WINTRUST_ACTION_GENERIC_VERIFY_V2 {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}
    action = GUID(0x00AAC56B, 0xCD44, 0x11D0, (wintypes.BYTE * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
    file_info = WintrustFileInfo(ctypes.sizeof(WintrustFileInfo), os.path.abspath(path), None, None)
    data = WintrustData()
    data.cbStruct = ctypes.sizeof(WintrustData)
    data.dwUIChoice = 2  # WTD_UI_NONE
    data.fdwRevocationChecks = 0  # WTD_REVOKE_NONE
    data.dwUnionChoice = 1  # WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    data.dwProvFlags = 0x1000  # WTD_CACHE_ONLY_URL_RETRIEVAL
    verify = ctypes.WinDLL("wintrust", use_last_error=True).WinVerifyTrust
    verify.argtypes = (wintypes.HWND, ctypes.POINTER(GUID), ctypes.c_void_p)
    verify.restype = wintypes.LONG
    result = verify(None, ctypes.byref(action), ctypes.byref(data)) & 0xFFFFFFFF
    last_error = ctypes.get_last_error() & 0xFFFFFFFF
    data.dwStateAction = 2  # WTD_STATEACTION_CLOSE, free verify state
    verify(None, ctypes.byref(action), ctypes.byref(data))
    if result == 0:
        return SIGNATURE_VALID
    # No signature, unknown subject form or provider: unsigned, unless "no signature" comes
    # from another error (file not readable, broken signature), see WinVerifyTrust documentation
    no_signature = (0x800B0100, 0x800B0003, 0x800B0001)
    if result in no_signature and (result != 0x800B0100 or last_error in no_signature):
        return SIGNATURE_UNSIGNED
    logger.error("UPDATES: installer signature check failed: 0x%08X", result)
    return SIGNATURE_INVALID


class UnsignedInstallerError(ValueError):
    """Installer of a custom update repository is not signed"""


def is_official_repository(repo: str) -> bool:
    """Repository is the official one (also its name before it was renamed)"""
    repo = repo.strip().strip("/").lower()
    return RENAMED_REPOS.get(repo, repo).lower() == FORK_REPO_NAME.lower()


def verify_installer(path: str, repository: str | None = None) -> None:
    """Refuse installer with a broken signature (raise ValueError), unsigned one is logged

    Official releases are unsigned (sha256 hash checked), installer of another
    update repository must be signed (raise UnsignedInstallerError).

    Args:
        repository: update repository the installer was downloaded from (found at check time),
            None for update repository currently set.
    """
    signature = installer_signature(path)
    if signature == SIGNATURE_INVALID:
        raise ValueError("installer signature is not valid")
    if repository is None:
        repository = update_repository()
    if signature == SIGNATURE_UNSIGNED and not is_official_repository(repository):
        raise UnsignedInstallerError("installer of a custom update repository is not signed")
    if signature == SIGNATURE_UNSIGNED:
        logger.warning("UPDATES: installer is not signed, sha256 hash verified only")
    else:
        logger.info("UPDATES: installer signature: %s", signature)


def run_installer(path: str, folder: str | None = None, repository: str | None = None) -> None:
    """Start installer silently, it closes TinyPedal and starts it again when done

    Args:
        folder: install folder, None for install_folder() (empty: chosen by installer).
        repository: update repository the installer was downloaded from, None for current setting.

    Raises:
        ValueError: installer signature is not valid (UnsignedInstallerError: unsigned installer
            of a custom update repository).
        OSError: installer can not be started.
    """
    verify_installer(path, repository)
    if folder is None:
        folder = install_folder()
    args = [path, "/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS"]
    if folder:
        args.append(f"/DIR={os.path.normpath(folder)}")
        logger.info("UPDATES: installing into %s", folder)
    subprocess.Popen(args, close_fds=True)


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
        "localized_notes",
    )

    def __init__(self):
        self._is_checking = False
        self._update_available = False
        self._manual_checking = False
        self._last_checked_version = VERSION_NA
        self._last_checked_date = DATE_NA
        self._disabled = False
        self.installer: InstallerAsset | None = None
        self.release_notes = ""  # English (GitHub release notes)
        self.localized_notes: dict[str, str] = {}  # language code: translated notes

    def is_manual(self) -> bool:
        """Is manual checking"""
        return self._manual_checking

    def is_updates(self) -> bool:
        """Is updates available"""
        return self._update_available

    def is_skipped(self) -> bool:
        """Update available but version skipped by user: not shown, unless checked by hand"""
        return (
            self._update_available and not self._manual_checking
            and version_number(self._last_checked_version) == skipped_version()
        )

    def notes(self, language: str) -> str:
        """Release notes of latest release in language, English if not translated"""
        return self.localized_notes.get(language) or self.release_notes

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

    def is_checking(self) -> bool:
        """Is checking (background thread running)"""
        return self._is_checking

    def __checking(self, repo: str):
        """Fetch version info from github Rest API"""
        try:
            raw_bytes = asyncio.run(request_latest_release(repo))
            checked_version, checked_date = parse_release(raw_bytes)
            self.installer = parse_installer(raw_bytes, repo)
            self.release_notes = parse_release_notes(raw_bytes)
            current_version = parse_version_string(version.__version__)
            self._update_available = is_new_version(checked_version, current_version, version.DEVELOPMENT)
            self.localized_notes = {}
            language = current_language()
            if self._update_available and language != "en":  # notes shown in app language
                summary = fetch_localized_summary(repo, parse_release_tag(raw_bytes), language)
                if summary:
                    self.localized_notes[language] = localize_release_notes(self.release_notes, summary)
            # Save info
            self._last_checked_version = checked_version
            self._last_checked_date = checked_date
        except Exception:  # unexpected error: never stuck checking (no check would run again)
            logger.exception("UPDATES: error while checking for updates")
        finally:
            self._is_checking = False
            # Send update signal
            app_signal.updates.emit(False)
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
