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
What's new: release notes of an available update, of the running version, or of the versions since the
last one run (shown once after an update)

Notes are the Markdown body of the GitHub release (tools/gen_release_notes.py): changelog section of the
version first ("### New" groups of "#### theme" cards, bullets with sub-bullets), then "## Commits"
(commits by kind), before / after Visuals and SHA256 checksums. The changelog part is shown in the app
language when translated (CHANGELOG.<code>.md, see update.localize_release_notes); sections of versions
skipped since the installed one follow (update.UpdateChecker.earlier_notes). Qt Quick page
(qml/home/ReleaseNotes.qml), state & actions in quick/release_backend.py; this dialog hosts it and runs
install, download & skip. Also asks to install a new version (prompt mode).
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, NamedTuple

from PySide6.QtCore import QDate, QLocale, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QVBoxLayout

from ..const_app import APP_NAME
from ..const_file import ConfigType
from ..i18n import current_language, tr
from ..setting import cfg
from ..update import (
    RELEASE_DETAILS_HEADING,
    RELEASE_VISUALS_HEADING,
    ChangelogEntry,
    changelog_image_name,
    entries_between,
    release_url,
)
from ..version import __version__ as app_version
from ..version_check import parse_version_string
from ._common import BaseDialog, UIScaler, find_dialog_host, page_host
from .notification import download_progress_text

if TYPE_CHECKING:
    from PySide6.QtQuickWidgets import QQuickWidget

logger = logging.getLogger(__name__)

DETAILS_HEADING = RELEASE_DETAILS_HEADING  # technical part of notes starts here
COMMIT_KINDS = ("Added", "Fixed", "Changed")  # see tools/gen_release_notes.py
VISUALS_GROUP = RELEASE_VISUALS_HEADING.removeprefix("### ")  # before / after images (tools/gen_release_notes.py)
MAX_LEVEL = 2  # deepest sub-bullet level shown
# Portable ZIP is no longer published: installer installed into the portable folder keeps its data
PORTABLE_UPDATE_NOTE = (
    "Portable copy (ZIP): download the setup ZIP from the releases page and install it into the folder of this copy, "
    "your presets and data are kept. Next updates then install from the app."
)
_bold = re.compile(r"\*\*(.+?)\*\*")
_code = re.compile(r"`([^`]+)`")
_link = re.compile(r"\[([^\]]+)\]\((https?://[^)\s\"]+)\)")
_image = re.compile(r"^!\[([^\]]*)\]\(([^)]*)\)$")  # Markdown image line
_heading = re.compile(r"^(#{2,4})\s+(.*)$")
_bullet = re.compile(r"^[-*+]\s+(.*)$")
_markup = re.compile(r"\*\*|`")


class NotesItem(NamedTuple):
    """Bullet, paragraph or changelog screenshot of a card"""

    text: str  # Markdown (image line for a screenshot)
    level: int = 0  # 0 bullet or paragraph, 1 & 2 sub-bullets
    bullet: bool = True


class NotesSection(NamedTuple):
    """Card of release notes: "#### theme" (or bullets right under a "### group"), its items in notes order"""

    title: str
    items: list[NotesItem]
    group: str = ""  # "### heading" the card belongs to ("New", "Fixes"...), empty before the first one


def inline_html(text: str, option_keys: Collection[str] = ()) -> str:
    """Inline Markdown (bold, code, links) as rich text, code spans naming an option as option:<key> links"""
    text = html.escape(text, quote=False)
    text = _link.sub(r'<a href="\2">\1</a>', text)
    text = _bold.sub(r"<b>\1</b>", text)

    def code(match: re.Match) -> str:
        value = match.group(1)
        if value in option_keys:
            return f'<a href="option:{value}"><code>{value}</code></a>'
        return f"<code>{value}</code>"

    return _code.sub(code, text)


def plain_text(text: str) -> str:
    """Markdown text without markup (search)"""
    return _markup.sub("", _link.sub(r"\1", text))


def notes_image(item: str) -> tuple[str, str] | None:
    """(caption, url) of changelog screenshot item, None if item is not one"""
    match = _image.match(item)
    if match is None or not changelog_image_name(match.group(2)):
        return None
    return match.group(1), match.group(2)


def _indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def parse_sections(markdown: str) -> list[NotesSection]:
    """Cards of notes: "### group" headings group "#### theme" cards (bullets right under a group: card without
    title); bullets keep their level (indented "- " is a sub-bullet), wrapped lines join their bullet, changelog
    screenshots are items of their own. Other images (not a changelog screenshot of app repository) are left out.
    """
    sections: list[NotesSection] = []
    group = ""
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        image = _image.match(line)
        if image and notes_image(line) is None:
            continue
        heading = _heading.match(line)
        if heading:
            title = heading.group(2).strip()
            if len(heading.group(1)) == 4:
                sections.append(NotesSection(title, [], group))
            else:
                group = title
                sections.append(NotesSection("", [], group))
            continue
        if not sections:
            sections.append(NotesSection("", [], group))
        items = sections[-1].items
        if image:  # own item, never part of a wrapped bullet
            items.append(NotesItem(line, 0, False))
            continue
        indent = _indent(raw_line)
        bullet = _bullet.match(line)
        if bullet:
            items.append(NotesItem(bullet.group(1), min(indent // 2, MAX_LEVEL), True))
        elif items and indent and _image.match(items[-1].text) is None:
            items[-1] = items[-1]._replace(text=f"{items[-1].text} {line}")  # wrapped bullet
        else:
            items.append(NotesItem(line, 0, False))
    return [section for section in sections if section.items]


def split_notes(notes: str) -> tuple[list[NotesSection], list[NotesSection]]:
    """(what's new themes, technical details: commits, visuals & checksums)"""
    summary, _, details = notes.partition(DETAILS_HEADING)
    if not details and summary.lstrip().startswith("### "):
        # No written changelog: notes are commits only, shown as themes
        return parse_sections(summary), []
    return parse_sections(summary), parse_sections(details)


def format_release_date(date: tuple[int, int, int]) -> str:
    """Release date in current language (4 octobre 2026), empty if unknown"""
    qdate = QDate(*date)
    if not qdate.isValid() or date[0] < 2000:
        return ""
    return QLocale(current_language()).toString(qdate, "d MMMM yyyy")


def version_text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


class Release(NamedTuple):
    """Notes of one version shown by the page"""

    version: tuple[int, int, int]
    date: tuple[int, int, int]  # DATE_NA if unknown
    notes: str  # Markdown: changelog section, then technical details for a GitHub release


class ReleaseNotesDialog(BaseDialog):
    """What's new of an available update (optionally asking to install it), or of the running version

    Install of installed Windows app: download progress shown with Cancel (page kept open),
    installer then runs (see UpdateInstaller). Skip This Version hides the update notice.
    """

    install_requested = Signal()
    skip_requested = Signal()

    def __init__(self, parent, notes: str, version: tuple[int, int, int], date: tuple[int, int, int],
                 can_install: bool = False, prompt: bool = False, download_url: str = "", portable: bool = False,
                 installer=None, can_skip: bool = False, earlier: Sequence[ChangelogEntry] = (),
                 current: bool = False, since: str = ""):
        """
        Args:
            installer: UpdateInstaller (download state & progress), shown while downloading.
            can_skip: update notice of this version can be skipped.
            earlier: changelog sections of versions between installed (or since) & this one, newest first.
            current: notes of running version: nothing to install.
            since: version run before an update (notes of the versions since then), empty if none.
        """
        from .quick import create_quick_view
        from .quick.release_backend import ReleaseNotesBackend

        super().__init__(parent)
        self.prompt = prompt
        self.can_install = can_install and not current  # installed Windows app: downloads & runs installer
        self.download_url = download_url  # else: download opened in browser (installer, or release page)
        self.portable = portable  # portable ZIP copy: updated by hand from release page
        self.installer = installer if self.can_install and not portable else None
        self.set_utility_title(tr("Update Available") if prompt else tr("What's New"))  # page title
        releases = [Release(version, date, notes)]
        releases.extend(Release(parse_version_string(entry.version), entry.date, entry.body) for entry in earlier)
        self.backend = ReleaseNotesBackend(
            self, releases, newer=not current and version > parse_version_string(app_version), prompt=prompt,
            installable=not current, can_install=self.can_install, portable=portable, can_skip=can_skip,
            since=since)
        # Actions that close the page run once QML handled the click (page deleted inside onClicked: Qt abort)
        queued = Qt.ConnectionType.QueuedConnection
        self.backend.installClicked.connect(self.request_install, queued)
        self.backend.skipClicked.connect(self.request_skip, queued)
        self.backend.closeClicked.connect(self.close, queued)
        self.backend.cancelClicked.connect(self.cancel_download)
        self.view: QQuickWidget = create_quick_view(self, "ReleaseNotes.qml", {"backend": self.backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        self.setMinimumSize(UIScaler.size(30), UIScaler.size(24))
        self.resize(UIScaler.size(42), UIScaler.size(40))
        if self.installer is not None:
            self.installer.busy_changed.connect(self.download_state)
            self.installer.progress.connect(self.download_progress)
            if self.installer.busy:  # page opened while downloading
                self.download_state(True)

    def shows_version(self, version: tuple[int, int, int]) -> bool:
        """Notes opened for this version (page already open shown again instead of a new one)"""
        return self.backend.first_version() == tuple(version)

    def showEvent(self, event):
        """Shown as page: page has its own Close button (Later kept when asking to install)"""
        self.backend.set_close_visible(not self.in_app_page or self.prompt)
        self.backend.page_shown()
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.release_page()
        super().closeEvent(event)

    def request_install(self):
        """Installed Windows app or run from source on Windows: install asked (downloaded & run by caller),
        else download opened in browser

        Portable copy: release page opened (new ZIP), never the installer. Page stays open
        while downloading (progress & cancel), when installer progress is known.
        """
        if self.can_install and not self.portable:
            self.install_requested.emit()
            if self.installer is not None:  # also when notify button was rebuilt (language change)
                self.installer.download(auto_install=True)
                return
        elif self.portable:
            QDesktopServices.openUrl(QUrl(release_url()))
        else:
            QDesktopServices.openUrl(QUrl(self.download_url or release_url()))
        self.close()

    def request_skip(self):
        """Skip this version: update notice hidden (until a newer version), page closed"""
        self.skip_requested.emit()
        self.close()

    def download_state(self, busy: bool):
        """Downloading: progress & cancel shown, install & skip disabled"""
        self.backend.set_downloading(busy)
        if busy and self.installer is not None:
            self.download_progress(self.installer.received, self.installer.total)

    def download_progress(self, received: int, total: int):
        """Percent & size downloaded (busy bar while size is unknown)"""
        text = download_progress_text(received, total) if received else ""
        self.backend.set_progress(min(received / total, 1.0) if total > 0 else -1.0,
                                  f"{tr('Downloading Update…')} {text}".strip())

    def cancel_download(self):
        """Stop download, partial file removed"""
        if self.installer is not None:
            self.backend.set_cancelling()
            self.installer.cancel()


def open_notes_page(parent, title: str, version: tuple[int, int, int]) -> ReleaseNotesDialog | None:
    """What's New page of this title & version already open in app: shown again & returned (no second page
    built, changelog read & cards made, to be thrown away), None if none"""
    host = page_host(parent, ReleaseNotesDialog)
    page = host.find_dialog_page(ReleaseNotesDialog.__name__, f"{title} - {APP_NAME}") if host is not None else None
    if page is None or not isinstance(page.dialog, ReleaseNotesDialog) or not page.dialog.shows_version(version):
        return None
    host.show_page_widget(page)
    return page.dialog


def running_version_dialog(parent) -> ReleaseNotesDialog:
    """What's new in running version (local changelog in app language, works offline): the open page if any"""
    from .home_view import base_version, local_changelog

    version = base_version()
    shown = open_notes_page(parent, tr("What's New"), parse_version_string(version))
    if shown is not None:
        return shown
    entries = local_changelog(current_language())
    entry = next((entry for entry in entries if entry.version == version), entries[0] if entries else None)
    if entry is None:
        return ReleaseNotesDialog(parent, "", parse_version_string(version), (0, 0, 0), current=True)
    return ReleaseNotesDialog(parent, entry.body, parse_version_string(entry.version), entry.date, current=True)


def remember_version_run() -> str:
    """Version run before this start ("" if none recorded), newest version run kept (an older copy started
    in between, source checkout & installed app, never shows the same notes again)"""
    from .home_view import base_version

    previous = str(cfg.application["last_run_version"])
    current = base_version()
    if parse_version_string(current) > parse_version_string(previous):
        cfg.application["last_run_version"] = current
        cfg.save(0, config_type=ConfigType.CONFIG)
    return previous


def notes_after_update(previous: str, language: str = "en") -> tuple[ChangelogEntry, list[ChangelogEntry]] | None:
    """Changelog sections of versions run for the first time: (running version, versions between), None if the
    running version is not newer than previous one, none recorded (first start of this feature or of the app),
    or not in the changelog"""
    from .home_view import base_version, local_changelog

    if not previous:
        return None
    current = parse_version_string(base_version())
    entries = entries_between(local_changelog(language), parse_version_string(previous), current)
    if not entries or parse_version_string(entries[0].version) != current:
        return None
    return entries[0], entries[1:]


def show_notes_after_update(window, previous: str) -> ReleaseNotesDialog | None:
    """First start after an update: what's new since previous version run, as page (waits inside app while
    window is hidden in tray), unless show_release_notes_after_update is off"""
    if not cfg.application["show_release_notes_after_update"]:
        return None
    found = notes_after_update(previous, current_language())
    if found is None:
        return None
    entry, earlier = found
    dialog = ReleaseNotesDialog(window, entry.body, parse_version_string(entry.version), entry.date,
                                earlier=earlier, current=True, since=previous)
    logger.info("UPDATES: what's new since %s shown", previous)
    if window.isVisible() and not window.isMinimized():
        dialog.open()
        return dialog
    host = find_dialog_host(window)
    if host is None or not host.show_dialog_page(dialog, bring_to_front=False):
        dialog.deleteLater()  # no page to wait in
        return None
    return dialog
