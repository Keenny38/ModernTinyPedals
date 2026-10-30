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
Check for updates
"""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import IO, NamedTuple

from . import app_signal, realtime_state, version
from .async_request import get_response, set_header_get
from .const_app import APP_NAME, EXECUTABLE, FORK_REPO_NAME, FORMER_FORK_REPO_NAMES, LEGACY_EXECUTABLE
from .const_common import DATE_NA, VERSION_NA
from .const_file import ConfigType
from .i18n import current_language
from .release_manifest import (
    MANIFEST_SUFFIX,
    MAX_MANIFEST_SIZE,
    MAX_SIGNATURE_SIZE,
    SIGNATURE_SUFFIX,
    ManifestError,
    ReleaseManifest,
    verify_manifest,
)
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


# Former names of the official repository (lower case) -> current name: update_repository saved before a rename
RENAMED_REPOS = {name.lower(): FORK_REPO_NAME for name in FORMER_FORK_REPO_NAMES}
OFFICIAL_REPOS = {FORK_REPO_NAME.lower(), *RENAMED_REPOS}  # lower case, former names included


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


API_HOST = "api.github.com"
API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
MAX_RELEASE_SIZE = 4 * 1024 * 1024


class GitHubApiRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects inside GitHub API only

    Renamed repository: GitHub answers "301 Moved Permanently" to /repositories/<id>/...
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(f"https://{API_HOST}/"):
            return None  # refused: raises HTTPError
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Hosts of update requests (release API, release files & the hosts GitHub redirects them to, changelogs,
# changelog screenshots): every request and every redirect goes to one of them, over https only
ALLOWED_HOSTS = frozenset((
    API_HOST,
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "raw.githubusercontent.com",
))


def is_allowed_url(url: str) -> bool:
    """https address on a GitHub host of updates (ALLOWED_HOSTS), default port, no user name"""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:  # invalid port or address
        return False
    return (
        parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and port in (None, 443)
        and parts.username is None and parts.password is None
    )


class GitHubDownloadRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects to GitHub hosts of updates only (ALLOWED_HOSTS), over https

    Release files redirect from github.com to a GitHub storage host: never to another host, nor to http.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_url(newurl):
            logger.warning("UPDATES: redirect refused: %s", newurl)
            return None  # refused: raises HTTPError
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str, timeout: float):
    """Response of GET request to a GitHub host of updates, redirects to other hosts or http refused

    Raises:
        ValueError: url is not an https address of ALLOWED_HOSTS.
        OSError, http.client.HTTPException: request failed (redirect refused: HTTPError).
    """
    if not is_allowed_url(url):
        raise ValueError(f"not a GitHub https address: {url}")
    return urllib.request.build_opener(GitHubDownloadRedirect).open(url, timeout=timeout)


def fetch_api_following_redirects(uri_path: str, timeout: float) -> bytes:
    """Body of GitHub API GET request, redirects followed, empty if failed"""
    request = urllib.request.Request(
        f"https://{API_HOST}{uri_path}",
        headers={"User-Agent": f"{APP_NAME}/{version.__version__}", **API_HEADERS},
    )
    try:
        with urllib.request.build_opener(GitHubApiRedirect).open(request, timeout=timeout) as response:
            return response.read(MAX_RELEASE_SIZE)
    except (OSError, ValueError, http.client.HTTPException):
        return b""


async def request_latest_release(repo: str) -> bytes:
    """Latest release data from github Rest API

    Direct request first; if it gives nothing (offline, or repository renamed: raw request
    never follows redirects), again with redirects followed.
    """
    uri_path = f"/repos/{repo}/releases/latest"
    port = 443
    timeout = 5
    user_agent = f"User-Agent: {APP_NAME}/{version.__version__}"
    request_header = set_header_get(
        uri_path,
        API_HOST,
        user_agent,
        *(f"{name}: {value}" for name, value in API_HEADERS.items()),
    )
    data = await get_response(request_header, API_HOST, port, timeout, ssl=True)
    if not data:
        data = await asyncio.to_thread(fetch_api_following_redirects, uri_path, timeout)
    return data


class InstallerAsset(NamedTuple):
    """Windows installer attached to a release: setup ZIP (installer inside) or installer itself"""

    name: str
    url: str
    sha256: str  # expected hash of downloaded file
    repository: str = ""  # update repository it was found in (at check time), see verify_installer
    size: int = 0  # expected size of downloaded file (signed manifest), 0 if unknown
    installer_sha256: str = ""  # expected hash of installer inside setup ZIP (signed manifest), empty if unknown


# Release files: "<name>-<version>-setup.zip" (installer "<name>-<version>-windows-setup.exe" inside)
# and "<name>-<version>-source.zip". Releases before 0.20.0 attached the installer itself.
SETUP_ZIP_SUFFIX = "-setup.zip"
INSTALLER_SUFFIX = "-windows-setup.exe"
INSTALLER_SUFFIXES = (SETUP_ZIP_SUFFIX, INSTALLER_SUFFIX)
RELEASE_SHA256_HEADING = "### SHA256"  # checksum list appended to release notes by the release workflow
_sha256_line = re.compile(r"[-*]\s*`?([0-9a-fA-F]{64})\s+\*?([\w.+-]+)`?")


def release_notes_hashes(body: str) -> dict[str, str]:
    """Files & hashes of the SHA256 section of release notes (last one: appended by the release workflow)

    Only lines "- `<hash>  <file>`" of that section: a hash written in a commit title or the changelog
    is never taken for the one of a release file.
    """
    lines = body.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == RELEASE_SHA256_HEADING]
    if not starts:
        return {}
    hashes: dict[str, str] = {}
    for line in lines[starts[-1] + 1:]:
        if line.startswith("#"):  # next section
            break
        match = _sha256_line.fullmatch(line.strip())
        if match:
            hashes.setdefault(match.group(2), match.group(1).lower())
    return hashes


def release_hash(release: dict, name: str) -> str:
    """SHA-256 of release file of a custom update repository: asset digest given by GitHub, else the SHA256
    section of release notes (official releases: signed manifest only, see verified_release)"""
    for asset in release.get("assets", ()):
        if not isinstance(asset, dict):
            continue
        digest = str(asset.get("digest") or "")
        if asset.get("name") == name and digest.lower().startswith("sha256:"):
            with suppress(ValueError):
                return parse_sha256(digest[7:])
    return release_notes_hashes(str(release.get("body") or "")).get(name, "")


def release_assets(data: bytes) -> dict[str, str]:
    """Release files (name: download url) of github Rest API release response, raise ValueError if invalid"""
    try:
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        return {str(asset["name"]): str(asset["browser_download_url"]) for asset in release["assets"]}
    except (AttributeError, TypeError, IndexError, KeyError, ValueError) as error:
        raise ValueError(f"invalid release response: {error}") from error


def parse_installer(data: bytes, repository: str = "", manifest: ReleaseManifest | None = None) -> InstallerAsset | None:
    """Find Windows installer & its hash in github Rest API release response, None if no verifiable installer

    Args:
        repository: update repository the release comes from, kept with the installer.
        manifest: verified manifest of release (official repository): hashes & sizes taken from it only,
            installer not listed in it is not found. None: hash given by GitHub or release notes (custom repository).
    """
    try:
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        assets = release_assets(data)
    except (AttributeError, TypeError, IndexError, KeyError, ValueError):
        return None
    for suffix in INSTALLER_SUFFIXES:  # setup ZIP first
        for name, url in assets.items():
            if not name.endswith(suffix) or not is_allowed_url(url):
                continue
            if manifest is not None:
                listed = manifest.assets.get(name)
                if listed is None:
                    continue
                inner = None
                if suffix == SETUP_ZIP_SUFFIX:  # installer inside, also listed (published beside the ZIP)
                    inner = manifest.assets.get(f"{name[:-len(SETUP_ZIP_SUFFIX)]}{INSTALLER_SUFFIX}")
                return InstallerAsset(name, url, listed.sha256, repository, listed.size, inner.sha256 if inner else "")
            sha256 = release_hash(release, name)
            if sha256:
                return InstallerAsset(name, url, sha256, repository)
    return None


def fetch_release_file(url: str, limit: int, timeout: float = 10) -> bytes:
    """Small release file (manifest, signature), raise ValueError if larger than limit (or OSError, HTTPException)"""
    with open_url(url, timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"release file is too large: {url}")
    return data


def fetch_manifest(data: bytes, timeout: float = 10) -> ReleaseManifest:
    """Verified signed manifest of release (github Rest API response), raise ManifestError

    Files "<name>-<version>-manifest.json" & ".sig" of release (tools/sign_release.py), signature checked
    against the release public keys of the app (release_manifest.RELEASE_PUBLIC_KEYS).
    """
    try:
        assets = release_assets(data)
    except ValueError as error:
        raise ManifestError(str(error)) from error
    names = [name for name in assets if name.endswith(MANIFEST_SUFFIX)]
    if not names:
        raise ManifestError("release has no signed manifest")
    if len(names) > 1:
        raise ManifestError("release has several manifests")
    signature_url = assets.get(f"{names[0]}{SIGNATURE_SUFFIX}")
    if not signature_url:
        raise ManifestError("release manifest has no signature")
    try:
        manifest_data = fetch_release_file(assets[names[0]], MAX_MANIFEST_SIZE, timeout)
        signature = fetch_release_file(signature_url, MAX_SIGNATURE_SIZE, timeout)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise ManifestError(f"release manifest not downloaded: {error}") from error
    return verify_manifest(manifest_data, signature)


def check_manifest(manifest: ReleaseManifest, tag: str, checked_version: tuple[int, int, int],
                   current_version: tuple[int, int, int], version_tag: str = "") -> None:
    """Verified manifest is the one of this official release & newer than running app, raise ManifestError

    Args:
        version_tag: development tag of running app (version.DEVELOPMENT), see is_new_version.
    """
    if manifest.repository.lower() not in OFFICIAL_REPOS:  # former name: release signed before a rename
        raise ManifestError(f"release manifest is for another repository: {manifest.repository}")
    if manifest.tag != tag or manifest.version != tag_version(tag):
        raise ManifestError(f"release manifest is for another release: {manifest.tag} ({manifest.version})")
    manifest_version = parse_version_string(manifest.version)
    if manifest_version != checked_version:
        raise ManifestError(f"release manifest version {manifest.version} differs from release")
    if not is_new_version(manifest_version, current_version, version_tag):
        raise ManifestError(f"release manifest version {manifest.version} is not newer than running app")


def verified_release(data: bytes, repository: str, checked_version: tuple[int, int, int],
                     current_version: tuple[int, int, int], version_tag: str = "") -> InstallerAsset | None:
    """Installer of official release (hash & size from its verified signed manifest), raise ManifestError

    None: verified release without Windows installer.
    """
    manifest = fetch_manifest(data)
    check_manifest(manifest, parse_release_tag(data), checked_version, current_version, version_tag)
    return parse_installer(data, repository, manifest)


RELEASE_VISUALS_HEADING = "### Visuals"  # see tools/gen_release_notes.py
RELEASE_DETAILS_HEADING = "## Commits"  # technical part of release notes (commits by kind, checksums)


def parse_release_notes(data: bytes) -> str:
    """Release notes (Markdown body of GitHub release), empty if unavailable

    Visuals section (before / after images of overlays, after the commits) is kept: What's New shows it folded.
    """
    try:
        release = json.loads(data[data.index(b"{"):].decode("utf-8"))
        return str(release.get("body") or "").strip()
    except (AttributeError, TypeError, IndexError, ValueError):
        return ""


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
MAX_EARLIER_VERSIONS = 12  # versions between installed & latest shown by What's New (older ones: GitHub)
_changelog_date = re.compile(r"\((\d{4})-(\d{1,2})-(\d{1,2})\)")


class ChangelogEntry(NamedTuple):
    """Changelog section of a version"""

    version: str  # "0.26.0"
    date: tuple[int, int, int]  # release date (year, month, day), DATE_NA if not written
    body: str  # Markdown


def changelog_entries(text: str) -> list[ChangelogEntry]:
    """Changelog sections in file order ("## 0.26.0 (2026-10-19)"), text before first "## " heading left out"""
    sections: list[tuple[str, str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].split(" ")[0], line, []))
        elif sections:
            sections[-1][2].append(line)
    entries = []
    for name, heading, body in sections:
        match = _changelog_date.search(heading)
        date = (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else DATE_NA
        entries.append(ChangelogEntry(name, date, "\n".join(body).strip()))
    return entries


def changelog_sections(text: str) -> list[tuple[str, str]]:
    """Changelog sections (version, body) in file order, text before first "## " heading left out"""
    return [(entry.version, entry.body) for entry in changelog_entries(text)]


def entries_between(entries: list[ChangelogEntry], newer_than: tuple[int, int, int], up_to: tuple[int, int, int],
                    limit: int = MAX_EARLIER_VERSIONS) -> list[ChangelogEntry]:
    """Changelog sections of versions newer than newer_than and up to up_to (included), newest first, at most limit"""
    found = [entry for entry in entries if newer_than < parse_version_string(entry.version) <= up_to]
    found.sort(key=lambda entry: parse_version_string(entry.version), reverse=True)
    return found[:limit]


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


def tag_version(tag: str) -> str:
    """Version of release tag ("v0.26.0" -> "0.26.0")"""
    return tag.lstrip("v").split("-")[0]


def fetch_changelog(repo: str, tag: str, language: str, timeout: float = 5) -> str:
    """Changelog of language at release tag (CHANGELOG.<language>.md, CHANGELOG.md for English), empty if none"""
    if not tag or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return ""
    filename = localized_changelog_name(language)
    url = f"https://raw.githubusercontent.com/{repo}/{tag}/{filename}"
    try:
        with open_url(url, timeout) as response:
            return response.read(MAX_CHANGELOG_SIZE).decode("utf-8", "replace")
    except (OSError, ValueError, http.client.HTTPException) as error:  # not translated (404), offline, cut
        logger.info("UPDATES: no %s changelog: %s", language, error)
        return ""


def fetch_localized_summary(repo: str, tag: str, language: str, timeout: float = 5) -> str:
    """Translated changelog section of release (CHANGELOG.<language>.md at release tag), empty if none"""
    if localized_changelog_name(language) == CHANGELOG_FILE:
        return ""
    return changelog_section(fetch_changelog(repo, tag, language, timeout), tag_version(tag))


# Changelog screenshots: "![caption](https://raw.githubusercontent.com/<repo>/<ref>/docs/changes/<file>)" lines,
# shown by What's New from docs/changes next to the app (project, or screenshots of the version in a release
# build), else downloaded once into the changelog image folder
CHANGELOG_IMAGE_URL = re.compile(
    r"https://raw\.githubusercontent\.com/([\w.-]+/[\w.-]+)/[\w.-]+/docs/changes/(\w[\w.-]*\.(?:png|jpe?g|gif|webp))")
CHANGELOG_IMAGE_FOLDER = os.path.join("docs", "changes")
MAX_CHANGELOG_IMAGE_SIZE = 8 * 1024 * 1024
IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")


def changelog_image_name(url: str) -> str:
    """File name of changelog screenshot of app repository (update or fork), empty if not one"""
    match = CHANGELOG_IMAGE_URL.fullmatch(url)
    if match is None:
        return ""
    repos = {*OFFICIAL_REPOS, update_repository().lower()}  # former names: screenshots of earlier changelogs
    return match.group(2) if match.group(1).lower() in repos else ""


def is_image_data(data: bytes) -> bool:
    """PNG, JPEG, GIF or WebP file content"""
    return data.startswith(IMAGE_SIGNATURES) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def changelog_image_cache() -> str:
    """Folder of downloaded changelog screenshots"""
    from .userfile import app_path, set_default_data_path

    return app_path(set_default_data_path("changelogimage/"))


def changelog_image_file(url: str, timeout: float = 10) -> str:
    """Local file of changelog screenshot (docs/changes next to app, else downloaded once & kept)

    Raises:
        ValueError: not a changelog screenshot of app repository.
        OSError: not available (offline, not found, not an image, unable to save).
    """
    from .userfile import APP_ROOT, atomic_replace

    name = changelog_image_name(url)
    if not name:
        raise ValueError(f"not a changelog image: {url}")
    folder = changelog_image_cache()
    for path in (os.path.join(APP_ROOT, CHANGELOG_IMAGE_FOLDER, name), os.path.join(folder, name)):
        if os.path.isfile(path):
            return path
    try:
        with open_url(url, timeout) as response:
            data = response.read(MAX_CHANGELOG_IMAGE_SIZE + 1)
    except (ValueError, http.client.HTTPException) as error:
        raise OSError(f"changelog image not downloaded: {error}") from error
    if len(data) > MAX_CHANGELOG_IMAGE_SIZE or not is_image_data(data):
        raise OSError(f"changelog image too large or not an image: {url}")
    path = os.path.join(folder, name)
    os.makedirs(folder, exist_ok=True)
    atomic_replace(path, data, fsync=False)  # downloaded again if lost
    return path


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


APP_EXECUTABLE = EXECUTABLE  # installer/neopedal.iss AppExe
# Executable names of an installed app: legacy name until 0.23.0 (renamed by installer on update)
APP_EXECUTABLES = (EXECUTABLE, LEGACY_EXECUTABLE)
INSTALLER_APP_ID = "{6C3F5B8E-4A2D-4E1B-9C7A-1D2E3F4A5B6C}"  # installer/neopedal.iss AppId
# Start menu shortcut of app, written by installer at every install (installer/neopedal.iss Icons)
START_MENU_FOLDER = os.path.join("Microsoft", "Windows", "Start Menu", "Programs")
START_MENU_SHORTCUT = os.path.join(START_MENU_FOLDER, "NeoPedal", "NeoPedal.lnk")
# Installed as "Modern Tiny Pedals": updates keep the Start menu folder (Inno Setup UsePreviousGroup)
LEGACY_START_MENU_SHORTCUTS = (
    os.path.join(START_MENU_FOLDER, "Modern Tiny Pedals", "NeoPedal.lnk"),
    os.path.join(START_MENU_FOLDER, "Modern Tiny Pedals", "Modern Tiny Pedals.lnk"),
)


def is_install_folder(folder: str) -> bool:
    """Folder of app installed by installer: executable & uninstaller"""
    return (
        bool(folder)
        and os.path.isfile(os.path.join(folder, UNINSTALLER_NAME))
        and any(os.path.isfile(os.path.join(folder, name)) for name in APP_EXECUTABLES)
    )


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
        for shortcut in (START_MENU_SHORTCUT, *LEGACY_START_MENU_SHORTCUTS):
            target = shortcut_target(os.path.join(appdata, shortcut))
            if os.path.basename(target).lower() in APP_EXECUTABLES:
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


DOWNLOAD_FOLDER_PREFIX = "neopedal-update-"  # private temporary folder of a download


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
    or download is cancelled. Default folder: new private temporary folder (never a predictable
    name in shared temporary folder). Setup ZIP: hash checked again on the open ZIP file the installer
    is extracted from, ZIP then removed. Hash of the installer file (downloaded one, or extracted one,
    hashed while extracting and checked against the signed manifest when known) is remembered:
    run_installer checks it again through a handle that keeps the file unchanged until the installer runs.

    Args:
        progress: called with received & total bytes (0 if unknown) after each chunk, from download thread.
        cancelled: download stopped (raise DownloadCancelled) once set.
    """
    expected = parse_sha256(asset.sha256)
    own_folder = not folder
    if own_folder:
        folder = tempfile.mkdtemp(prefix=DOWNLOAD_FOLDER_PREFIX)
    path = os.path.join(folder, os.path.basename(asset.name))
    try:
        _download_verified(asset.url, path, expected, timeout, progress, cancelled, asset.size)
        if not path.lower().endswith(".zip"):
            remember_installer(path, expected)
            return path
        try:
            return extract_installer(path, folder, expected, asset.installer_sha256)
        finally:
            with suppress(OSError):
                os.remove(path)
    except BaseException:
        if own_folder:  # nothing kept in private folder after a failure
            shutil.rmtree(folder, ignore_errors=True)
        raise


def _download_verified(
    url: str,
    path: str,
    expected: str,
    timeout: float,
    progress: Callable[[int, int], object] | None,
    cancelled: threading.Event | None,
    size: int = 0,
) -> None:
    """Download to path through ".part" file, sha256 checked while downloading and again on final file

    Args:
        size: expected size (signed manifest), 0 if unknown.
    """
    part_path = f"{path}.part"
    digest = hashlib.sha256()
    replaced = False
    try:
        with open_url(url, timeout) as response, open(part_path, "wb") as file:
            total = content_length(response)
            limit = size or total or MAX_INSTALLER_SIZE
            received = 0
            while chunk := response.read(1 << 16):
                if cancelled is not None and cancelled.is_set():
                    raise DownloadCancelled("download cancelled")
                received += len(chunk)
                # Bounded: a wrong asset (endless or chunked answer) never fills the disk before its hash fails
                if received > limit:
                    raise ValueError("downloaded installer is larger than announced")
                digest.update(chunk)
                file.write(chunk)
                if progress is not None:
                    progress(received, total)
            if cancelled is not None and cancelled.is_set():
                raise DownloadCancelled("download cancelled")
        if digest.hexdigest() != expected:
            raise ValueError("downloaded installer does not match its sha256 hash")
        os.replace(part_path, path)
        replaced = True
        if not path.lower().endswith(".zip"):  # setup ZIP: checked while extracting
            with open(path, "rb") as file:
                verify_file_sha256(file, expected)
    except BaseException:  # partial or invalid download never left behind
        with suppress(OSError):
            os.remove(path if replaced else part_path)
        raise


def verify_file_sha256(file: IO[bytes], expected: str) -> None:
    """Check sha256 of open file from its start (raise ValueError), file left at its start"""
    file.seek(0)
    digest = hashlib.sha256()
    while chunk := file.read(1 << 20):
        digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("downloaded installer changed after its sha256 hash was verified")
    file.seek(0)


class InstallerChangedError(ValueError):
    """Installer file is not the one downloaded (hash differs or unknown), or its signer changed"""


# Installer files written by download_installer (normalized path: sha256), checked again by run_installer
_downloaded_installers: dict[str, str] = {}


def _installer_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def remember_installer(path: str, sha256: str) -> None:
    """Hash of installer file written by the updater, checked again before it runs"""
    _downloaded_installers[_installer_key(path)] = sha256


def downloaded_installer_hash(path: str) -> str:
    """Hash of installer file written by download_installer, empty if not one"""
    return _downloaded_installers.get(_installer_key(path), "")


def discard_installer(path: str) -> None:
    """Remove installer downloaded by download_installer (not run: declined or failed to start),
    never left in temporary folder (its private download folder removed too)"""
    if not path:
        return
    _downloaded_installers.pop(_installer_key(path), None)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        logger.warning("UPDATES: unable to remove downloaded installer: %s", error)
        return
    folder = os.path.dirname(path)
    if os.path.basename(folder).startswith(DOWNLOAD_FOLDER_PREFIX):
        with suppress(OSError):  # not empty: left as is
            os.rmdir(folder)


MAX_INSTALLER_SIZE = 1 << 30  # extracted installer size limit


def extract_installer(zip_path: str, folder: str, expected: str = "", expected_installer: str = "") -> str:
    """Extract the installer (only executable) of setup ZIP to folder, return its path (raise OSError or ValueError)

    Hash of extracted installer remembered for run_installer (see download_installer).

    Args:
        expected: sha256 of setup ZIP, checked on the open file installer is extracted from.
        expected_installer: sha256 of installer inside (signed manifest), checked while extracting, empty if unknown.
    """
    try:
        with open(zip_path, "rb") as zip_file:
            if expected:
                verify_file_sha256(zip_file, expected)
            path, sha256 = _extract_installer(zip_file, folder, expected_installer)
    except zipfile.BadZipFile as error:  # also CRC mismatch while reading
        raise ValueError(f"invalid setup archive: {error}") from error
    remember_installer(path, sha256)
    return path


def _extract_installer(zip_file: IO[bytes], folder: str, expected_installer: str = "") -> tuple[str, str]:
    """Extract the installer of open setup ZIP file to folder, return its path & sha256"""
    with zipfile.ZipFile(zip_file) as archive:
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
        digest = hashlib.sha256()
        try:
            with archive.open(info) as source, open(part_path, "wb") as target:
                while chunk := source.read(1 << 16):
                    digest.update(chunk)
                    target.write(chunk)
            if expected_installer and digest.hexdigest() != expected_installer:
                raise ValueError("installer in setup archive does not match the signed release manifest")
            os.replace(part_path, path)
        except BaseException:
            with suppress(OSError):
                os.remove(part_path)
            raise
    return path, digest.hexdigest()


# Authenticode (WinVerifyTrust) result
SIGNATURE_VALID = "valid"
SIGNATURE_UNSIGNED = "unsigned"
SIGNATURE_INVALID = "invalid"
SIGNATURE_UNKNOWN = "unknown"  # not checked (not Windows, check unavailable)
SIGNATURE_REVOCATION_UNKNOWN = "revocation unknown"  # valid, but certificate revocation could not be checked


class Signature(NamedTuple):
    """Authenticode signature of a file"""

    state: str  # SIGNATURE_*
    signer: str = ""  # subject name of signing certificate (valid signature), empty if unknown


def check_signature(path: str, revocation: bool = False, handle: int | None = None) -> Signature:
    """Authenticode signature of file: state (valid, unsigned, invalid, revocation unknown, or unknown) & signer

    Args:
        revocation: certificate revocation of the whole chain checked online (signer of a custom update
            repository), else nothing downloaded (cached revocation data only).
        handle: Windows handle of the open file, checked through it (never reopened by name).
    """
    if sys.platform != "win32":
        return Signature(SIGNATURE_UNKNOWN)
    try:
        return _win_verify_trust(path, revocation, handle)
    except (AttributeError, OSError, ValueError) as error:
        logger.error("UPDATES: unable to check installer signature: %s", error)
        return Signature(SIGNATURE_UNKNOWN)


def installer_signature(path: str) -> str:
    """Authenticode signature state of file: valid, unsigned, invalid, or unknown (no revocation download)"""
    return check_signature(path).state


# WinVerifyTrust results
TRUST_E_NOSIGNATURE = 0x800B0100
TRUST_E_SUBJECT_FORM_UNKNOWN = 0x800B0003
TRUST_E_PROVIDER_UNKNOWN = 0x800B0001
CERT_E_REVOKED = 0x800B010C
REVOCATION_UNKNOWN_RESULTS = (
    0x800B010E,  # CERT_E_REVOCATION_FAILURE
    0x80092013,  # CRYPT_E_REVOCATION_OFFLINE
    0x80092012,  # CRYPT_E_NO_REVOCATION_CHECK
)


def _win_verify_trust(path: str, revocation: bool = False, handle: int | None = None) -> Signature:
    """Check embedded Authenticode signature with WinVerifyTrust (no UI), signer name of valid signature"""
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
    file_info = WintrustFileInfo(ctypes.sizeof(WintrustFileInfo), os.path.abspath(path), handle, None)
    data = WintrustData()
    data.cbStruct = ctypes.sizeof(WintrustData)
    data.dwUIChoice = 2  # WTD_UI_NONE
    if revocation:
        data.fdwRevocationChecks = 1  # WTD_REVOKE_WHOLECHAIN
        data.dwProvFlags = 0x80  # WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT, revocation data downloaded
    else:
        data.fdwRevocationChecks = 0  # WTD_REVOKE_NONE
        data.dwProvFlags = 0x1000  # WTD_CACHE_ONLY_URL_RETRIEVAL
    data.dwUnionChoice = 1  # WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
    verify = wintrust.WinVerifyTrust
    verify.argtypes = (wintypes.HWND, ctypes.POINTER(GUID), ctypes.c_void_p)
    verify.restype = wintypes.LONG
    result = verify(None, ctypes.byref(action), ctypes.byref(data)) & 0xFFFFFFFF
    last_error = ctypes.get_last_error() & 0xFFFFFFFF
    signer = ""
    try:
        if result == 0:
            signer = _signer_name(wintrust, data.hWVTStateData)
    finally:
        data.dwStateAction = 2  # WTD_STATEACTION_CLOSE, free verify state
        verify(None, ctypes.byref(action), ctypes.byref(data))
    if result == 0:
        return Signature(SIGNATURE_VALID, signer)
    if result in REVOCATION_UNKNOWN_RESULTS:
        logger.error("UPDATES: installer certificate revocation not checked: 0x%08X", result)
        return Signature(SIGNATURE_REVOCATION_UNKNOWN)
    # No signature, unknown subject form or provider: unsigned, unless "no signature" comes
    # from another error (file not readable, broken signature), see WinVerifyTrust documentation
    no_signature = (TRUST_E_NOSIGNATURE, TRUST_E_SUBJECT_FORM_UNKNOWN, TRUST_E_PROVIDER_UNKNOWN)
    if result in no_signature and (result != TRUST_E_NOSIGNATURE or last_error in no_signature):
        return Signature(SIGNATURE_UNSIGNED)
    logger.error("UPDATES: installer signature check failed: 0x%08X", result)
    return Signature(SIGNATURE_INVALID)


def _signer_name(wintrust, state_data) -> str:
    """Subject name of signing certificate of verified file (WinVerifyTrust state), empty if unavailable"""
    if sys.platform != "win32":  # Windows API only (also skips type checking on other platforms)
        return ""
    import ctypes
    from ctypes import wintypes

    class ProviderSigner(ctypes.Structure):  # CRYPT_PROVIDER_SGNR, first fields
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("sftVerifyAsOf", wintypes.FILETIME),
            ("csCertChain", wintypes.DWORD),
            ("pasCertChain", ctypes.c_void_p),
        ]

    class ProviderCert(ctypes.Structure):  # CRYPT_PROVIDER_CERT, first fields
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pCert", ctypes.c_void_p),
        ]

    provider_data = wintrust.WTHelperProvDataFromStateData
    provider_data.argtypes = (wintypes.HANDLE,)
    provider_data.restype = ctypes.c_void_p
    provider_signer = wintrust.WTHelperGetProvSignerFromChain
    provider_signer.argtypes = (ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    provider_signer.restype = ctypes.POINTER(ProviderSigner)
    name_string = ctypes.WinDLL("crypt32").CertGetNameStringW
    name_string.argtypes = (
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD)
    name_string.restype = wintypes.DWORD
    provider = provider_data(state_data)
    if not provider:
        return ""
    signer = provider_signer(provider, 0, False, 0)
    if not signer or not signer.contents.csCertChain or not signer.contents.pasCertChain:
        return ""
    certificate = ctypes.cast(signer.contents.pasCertChain, ctypes.POINTER(ProviderCert)).contents.pCert
    if not certificate:
        return ""
    size = name_string(certificate, 4, 0, None, None, 0)  # CERT_NAME_SIMPLE_DISPLAY_TYPE, with null
    if size <= 1:
        return ""
    buffer = ctypes.create_unicode_buffer(size)
    name_string(certificate, 4, 0, None, buffer, size)
    return buffer.value


class UnsignedInstallerError(ValueError):
    """Installer of a custom update repository is not signed"""


class RevocationUnknownError(ValueError):
    """Certificate revocation of installer of a custom update repository could not be checked"""


def is_official_repository(repo: str) -> bool:
    """Repository is the official one (also its name before it was renamed)"""
    repo = repo.strip().strip("/").lower()
    return repo in OFFICIAL_REPOS


def verify_installer(path: str, repository: str | None = None, handle: int | None = None,
                     revocation: bool | None = None) -> str:
    """Refuse installer with a broken signature (raise ValueError), unsigned one is logged, signer name returned

    Official releases may be unsigned: installed only with a verified signed manifest (its sha256 checked),
    a signature present must still be valid. Installer of another update repository must be signed
    (raise UnsignedInstallerError), also if signature can not be checked, by a certificate not revoked
    (revocation checked online, raise RevocationUnknownError if revocation servers can not be reached).

    Args:
        repository: update repository the installer was downloaded from (found at check time),
            None for update repository currently set.
        handle: Windows handle of the open installer, checked through it.
        revocation: revocation checked online, None for custom repositories only. False: cached data only
            (installer whose revocation was checked online after download, hash checked again since).
    """
    if repository is None:
        repository = update_repository()
    official = is_official_repository(repository)
    if revocation is None:
        revocation = not official
    signature = check_signature(path, revocation=revocation, handle=handle)
    if signature.state == SIGNATURE_INVALID:
        raise ValueError("installer signature is not valid")
    if not official:
        if signature.state == SIGNATURE_REVOCATION_UNKNOWN:
            raise RevocationUnknownError("certificate revocation of installer could not be checked")
        if signature.state != SIGNATURE_VALID:
            raise UnsignedInstallerError(f"installer of a custom update repository is not signed ({signature.state})")
    elif signature.state == SIGNATURE_REVOCATION_UNKNOWN:  # official release: signed manifest verified
        logger.warning("UPDATES: installer certificate revocation not checked, signed manifest verified")
    if signature.state == SIGNATURE_UNSIGNED:
        logger.warning("UPDATES: installer is not signed, sha256 hash of signed manifest verified")
    else:
        logger.info("UPDATES: installer signature: %s %s", signature.state, signature.signer)
    return signature.signer


def installer_signer(path: str, repository: str | None = None) -> str:
    """Signer of downloaded installer of a custom update repository, shown before installing (download thread)

    Hash checked again and signature verified with online revocation check through an open handle
    (raise ValueError, see verify_installer), empty signer for official releases (not checked here).
    """
    if repository is None:
        repository = update_repository()
    if is_official_repository(repository):
        return ""
    with open_installer(path) as (file, handle):
        verify_file_sha256(file, _expected_installer_hash(path))
        return verify_installer(path, repository, handle, revocation=True)


def _expected_installer_hash(path: str) -> str:
    """Hash of installer written by download_installer, raise InstallerChangedError if not one"""
    expected = downloaded_installer_hash(path)
    if not expected:
        raise InstallerChangedError("installer was not downloaded by the updater")
    return expected


@contextmanager
def open_installer(path: str) -> Iterator[tuple[IO[bytes], int | None]]:
    """Installer open for reading: file & Windows handle (None on other systems)

    Windows: opened without write nor delete sharing, the file can not be changed, replaced, renamed
    or removed by another program while open; it can still be read & started (CreateProcess).
    """
    if sys.platform != "win32":
        with open(path, "rb") as file:
            yield file, None
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        wintypes.HANDLE)
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        os.path.abspath(path),
        0x80000000,  # GENERIC_READ
        0x00000001,  # FILE_SHARE_READ only: no FILE_SHARE_WRITE, no FILE_SHARE_DELETE
        None,  # not inherited by started processes
        3,  # OPEN_EXISTING
        0x80,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    if handle is None or handle == ctypes.c_void_p(-1).value:  # INVALID_HANDLE_VALUE
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error), path)
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        kernel32.CloseHandle(wintypes.HANDLE(handle))
        raise
    with os.fdopen(descriptor, "rb") as file:  # closes handle
        yield file, handle


def run_installer(path: str, folder: str | None = None, repository: str | None = None,
                  signer: str | None = None) -> None:
    """Start installer silently, it closes NeoPedal and starts it again when done

    Installer kept open without write or delete sharing from its last checks until its process started:
    sha256 checked again (hash of download_installer), signature checked, then started from that same file.

    Args:
        folder: install folder, None for install_folder() (empty: chosen by installer).
        repository: update repository the installer was downloaded from, None for current setting.
        signer: signer shown to user before installing (custom repository, see installer_signer),
            None if not shown. Signed by another one: refused.

    Raises:
        ValueError: installer signature is not valid (UnsignedInstallerError: unsigned installer
            of a custom update repository, InstallerChangedError: installer not the downloaded one).
        OSError: installer can not be started.
    """
    expected = _expected_installer_hash(path)
    with open_installer(path) as (file, handle):
        try:
            verify_file_sha256(file, expected)
        except ValueError as error:
            raise InstallerChangedError(str(error)) from error
        # Revocation of custom repository signer checked online after download (installer_signer), same content
        found = verify_installer(path, repository, handle, revocation=False if signer is not None else None)
        if signer is not None and found != signer:
            raise InstallerChangedError(f"installer signer changed: {found or 'unknown'}")
        if folder is None:
            folder = install_folder()
        args = [path, "/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS"]
        if folder:
            args.append(f"/DIR={os.path.normpath(folder)}")
            logger.info("UPDATES: installing into %s", folder)
        subprocess.Popen(args, close_fds=True)  # started while installer is held unchanged, closed after


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
        "_scheduled_checking",
        "_last_check_time",
        "_last_checked_version",
        "_last_checked_date",
        "_disabled",
        "_refused",
        "installer",
        "release_notes",
        "localized_notes",
        "earlier_entries",
        "_changelog_cache",
    )

    def __init__(self):
        self._is_checking = False
        self._update_available = False
        self._manual_checking = False
        self._scheduled_checking = False
        self._last_check_time: float | None = None  # time.monotonic of last check, None if none yet
        self._last_checked_version = VERSION_NA
        self._last_checked_date = DATE_NA
        self._disabled = False
        self._refused = ""  # why newer official release was refused (signed manifest not verified), empty if not
        self.installer: InstallerAsset | None = None
        self.release_notes = ""  # English (GitHub release notes)
        self.localized_notes: dict[str, str] = {}  # language code: translated notes
        # language code: changelog sections of versions between installed & latest (skipped updates), newest first
        self.earlier_entries: dict[str, list[ChangelogEntry]] = {}
        self._changelog_cache: dict[tuple[str, str, str], str] = {}  # (repo, tag, language): changelog, last tag only

    def is_manual(self) -> bool:
        """Is manual checking"""
        return self._manual_checking

    def is_scheduled(self) -> bool:
        """Is automatic checking while app runs (see check_due)"""
        return self._scheduled_checking

    def is_updates(self) -> bool:
        """Is updates available"""
        return self._update_available

    def is_refused(self) -> bool:
        """Newer official release found but refused: its signed manifest is missing or not valid (see message)"""
        return bool(self._refused)

    def is_skipped(self) -> bool:
        """Update available but version skipped by user: not shown, unless checked by hand"""
        return (
            self._update_available and not self._manual_checking
            and version_number(self._last_checked_version) == skipped_version()
        )

    def notes(self, language: str) -> str:
        """Release notes of latest release in language, English if not translated"""
        return self.localized_notes.get(language) or self.release_notes

    def earlier_notes(self, language: str) -> list[ChangelogEntry]:
        """Changelog sections of versions between installed & latest release (newest first), in language if
        translated, else English, empty if none (installed version is the previous release)"""
        return self.earlier_entries.get(language) or self.earlier_entries.get("en", [])

    def _changelog(self, repo: str, tag: str, language: str) -> str:
        """Changelog of language at release tag, fetched once per tag (checked again every few hours)"""
        key = (repo, tag, language)
        if key not in self._changelog_cache:
            if any(cached[:2] != key[:2] for cached in self._changelog_cache):
                self._changelog_cache.clear()  # newer release: older changelogs never used again
            self._changelog_cache[key] = fetch_changelog(repo, tag, language)
        return self._changelog_cache[key]

    def latest_version(self) -> tuple[int, int, int]:
        """Version of latest release (last check)"""
        return self._last_checked_version

    def latest_date(self) -> tuple[int, int, int]:
        """Release date of latest release (last check)"""
        return self._last_checked_date

    def check(self, manual: bool, scheduled: bool = False):
        """Run update check in separated thread

        Args:
            manual: asked by user, result shown even if no update.
            scheduled: automatic check while app runs (see check_due), never turns a running check automatic.
        """
        if scheduled and self._is_checking:
            return
        self._manual_checking = manual
        self._scheduled_checking = scheduled
        self._last_check_time = time.monotonic()
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

    def check_due(self, now: float | None = None) -> bool:
        """Automatic check while app runs, True if started

        Due once number_of_hours_between_update_checks passed since last check (startup, manual or
        automatic). Off with check_for_updates_on_startup off or 0 hours; not while driving (next call).
        """
        hours = cfg.application["number_of_hours_between_update_checks"]
        if not cfg.application["check_for_updates_on_startup"] or hours <= 0:
            return False
        if self._is_checking or realtime_state.active:
            return False
        if now is None:
            now = time.monotonic()
        if self._last_check_time is not None and now - self._last_check_time < hours * 3600:
            return False
        self.check(False, scheduled=True)
        return True

    def __checking(self, repo: str):
        """Fetch version info from github Rest API"""
        try:
            raw_bytes = asyncio.run(request_latest_release(repo))
            checked_version, checked_date = parse_release(raw_bytes)
            official = is_official_repository(repo)
            # Custom repository: hash given by GitHub (Authenticode signature required at install)
            installer = None if official else parse_installer(raw_bytes, repo)
            release_notes = parse_release_notes(raw_bytes)
            current_version = parse_version_string(version.__version__)
            update_available = is_new_version(checked_version, current_version, version.DEVELOPMENT)
            refused = ""
            if update_available and official:
                # Official release: offered only with its signed manifest (hash & size of installer from it)
                try:
                    installer = verified_release(raw_bytes, repo, checked_version, current_version, version.DEVELOPMENT)
                except ManifestError as error:
                    logger.error("UPDATES: release v%s refused, signed manifest not verified: %s",
                                 ".".join(map(str, checked_version)), error)
                    refused = str(error) or "signed manifest not verified"
                    update_available = False
                    installer = None
                    release_notes = ""
            localized_notes = {}
            earlier_entries = {}
            language = current_language()
            if update_available:
                # Changelog of release: notes in app language, sections of skipped versions in between
                tag = parse_release_tag(raw_bytes)
                text = self._changelog(repo, tag, language)
                if language != "en":
                    summary = changelog_section(text, tag_version(tag))
                    if summary:
                        localized_notes[language] = localize_release_notes(release_notes, summary)
                    if not text:  # not translated: skipped versions in English
                        text = self._changelog(repo, tag, "en")
                earlier = [entry for entry in entries_between(changelog_entries(text), current_version, checked_version)
                           if parse_version_string(entry.version) != checked_version]  # latest: release notes
                if earlier:
                    earlier_entries[language] = earlier
            # Save info, all at once (no partial state on error)
            self.installer = installer
            self.release_notes = release_notes
            self.localized_notes = localized_notes
            self.earlier_entries = earlier_entries
            self._update_available = update_available
            self._refused = refused
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
        if self._refused:
            return "Update Refused: v{}.{}.{} Has No Valid Signature".format(*self._last_checked_version)
        if not self._update_available:
            return "No Updates Available"
        return "New Updates: v{}.{}.{} ({}-{}-{})".format(
            *self._last_checked_version,
            *self._last_checked_date,
        )


update_checker = UpdateChecker()
