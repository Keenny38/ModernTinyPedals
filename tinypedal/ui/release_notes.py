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
What's new: release notes of an available update

Notes are the Markdown body of the GitHub release (tools/gen_release_notes.py): changelog
section of the version (themes with bullets) first, then "## Commits" (commits by kind) and
SHA256 checksums. The changelog part is shown in the app language when translated
(CHANGELOG.<code>.md, see update.localize_release_notes). Shown as a header (version, date,
installed version), one card per theme, and technical details (commits, checksums) folded
below. Also asks to install a new version (prompt mode).
"""

from __future__ import annotations

import html
import re
from typing import NamedTuple

from PySide6.QtCore import QDate, QLocale, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..const_app import VERSION
from ..i18n import current_language, tr
from ..update import RELEASE_DETAILS_HEADING, release_url
from ..version import __version__ as app_version
from ..version_check import parse_version_string
from ._common import BaseDialog, FocusRingButton, UIScaler
from .notification import download_progress_text

DETAILS_HEADING = RELEASE_DETAILS_HEADING  # technical part of notes starts here
COMMIT_KINDS = ("Added", "Fixed", "Changed")  # see tools/gen_release_notes.py
# Portable ZIP is no longer published: installer installed into the portable folder keeps its data
PORTABLE_UPDATE_NOTE = (
    "Portable copy (ZIP): download the setup ZIP from the releases page and install it into the folder of this copy, "
    "your presets and data are kept. Next updates then install from the app."
)
_bold = re.compile(r"\*\*(.+?)\*\*")
_code = re.compile(r"`([^`]+)`")
_link = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_image = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")  # Markdown image line


class NotesSection(NamedTuple):
    """Theme of release notes: title & items (bullets or paragraphs, Markdown)"""

    title: str
    items: list[str]


def inline_html(text: str) -> str:
    """Inline Markdown (bold, code, links) as rich text"""
    text = html.escape(text, quote=False)
    text = _link.sub(r'<a href="\2">\1</a>', text)
    text = _bold.sub(r"<b>\1</b>", text)
    return _code.sub(r"<code>\1</code>", text)


def parse_sections(markdown: str) -> list[NotesSection]:
    """Headings (## or ###) start a section, bullets & paragraphs are its items"""
    sections: list[NotesSection] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or _image.match(line):  # changelog screenshots are online only
            continue
        heading = re.match(r"^#{2,4}\s+(.*)$", line)
        if heading:
            sections.append(NotesSection(heading.group(1).strip(), []))
            continue
        if not sections:
            sections.append(NotesSection("", []))
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if bullet:
            sections[-1].items.append(bullet.group(1))
        elif sections[-1].items and raw_line.startswith((" ", "\t")):
            sections[-1].items[-1] += " " + line  # wrapped bullet
        else:
            sections[-1].items.append(line)
    return [section for section in sections if section.items]


def split_notes(notes: str) -> tuple[list[NotesSection], list[NotesSection]]:
    """(what's new themes, technical details: commits & checksums)"""
    summary, _, details = notes.partition(DETAILS_HEADING)
    if not details and summary.lstrip().startswith("### "):
        # No written changelog: notes are commits only, shown as themes
        return parse_sections(summary), []
    return parse_sections(summary), parse_sections(details)


def items_html(items: list[str]) -> str:
    """Bullets of a section as rich text list"""
    rows = "".join(f"<li style='margin-bottom:{UIScaler.pixel(5)}px'>{inline_html(item)}</li>" for item in items)
    return f"<ul style='margin-left:{UIScaler.pixel(-14)}px'>{rows}</ul>"


def format_release_date(date: tuple[int, int, int]) -> str:
    """Release date in current language (4 octobre 2026), empty if unknown"""
    qdate = QDate(*date)
    if not qdate.isValid() or date[0] < 2000:
        return ""
    return QLocale(current_language()).toString(qdate, "d MMMM yyyy")


def version_text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


class NotesCard(QFrame):
    """Card: theme title & its bullets"""

    def __init__(self, parent, section: NotesSection, monospace: bool = False):
        super().__init__(parent)
        self.setObjectName("notesCard")
        layout = QVBoxLayout(self)
        margin = UIScaler.pixel(12)
        layout.setContentsMargins(margin, UIScaler.pixel(10), margin, UIScaler.pixel(6))
        layout.setSpacing(UIScaler.pixel(4))
        if section.title:
            self.label_title = QLabel(inline_html(section.title))
            self.label_title.setObjectName("notesCardTitle")
            self.label_title.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(self.label_title)
        self.label_items = QLabel(items_html(section.items))
        self.label_items.setObjectName("notesMono" if monospace else "notesItems")
        self.label_items.setTextFormat(Qt.TextFormat.RichText)
        self.label_items.setWordWrap(True)
        self.label_items.setOpenExternalLinks(True)
        self.label_items.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(self.label_items)


class ReleaseNotesDialog(BaseDialog):
    """What's new of an available update, optionally asking to install it

    Install of installed Windows app: download progress shown with Cancel (page kept open),
    installer then runs (see UpdateInstaller). Skip This Version hides the update notice.
    """

    install_requested = Signal()
    skip_requested = Signal()

    def __init__(self, parent, notes: str, version: tuple[int, int, int], date: tuple[int, int, int],
                 can_install: bool = False, prompt: bool = False, download_url: str = "", portable: bool = False,
                 installer=None, can_skip: bool = False):
        """
        Args:
            installer: UpdateInstaller (download state & progress), shown while downloading.
            can_skip: update notice of this version can be skipped.
        """
        super().__init__(parent)
        self.prompt = prompt
        self.can_install = can_install  # installed Windows app: downloads & runs installer
        self.download_url = download_url  # else: download opened in browser (installer, or release page)
        self.portable = portable  # portable ZIP copy: updated by hand from release page
        self.installer = installer if can_install and not portable else None
        self.set_utility_title(tr("Update Available") if prompt else tr("Release Notes"))  # page title
        self.themes, self.details = split_notes(notes)

        # Header: version (newer than installed one or not), date, installed version
        title = QLabel(f"{tr('Version')} {version_text(version)}")
        title.setObjectName("notesTitle")
        newer = version > parse_version_string(app_version)  # development suffix left out
        chip = QLabel(tr("New Version") if newer else tr("Installed"))
        chip.setObjectName("notesChip")
        layout_title = QHBoxLayout()
        layout_title.addWidget(title)
        layout_title.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout_title.addStretch(1)
        released = format_release_date(date)
        detail = " · ".join(text for text in (
            f"{tr('Released')} {released}" if released else "",
            f"{tr('Installed version')} {VERSION}",
        ) if text)
        self.label_detail = QLabel(detail)
        self.label_detail.setEnabled(False)  # muted

        # Body: themes, then technical details folded
        body = QWidget()
        body.setObjectName("notesBody")
        layout_body = QVBoxLayout(body)
        layout_body.setContentsMargins(0, 0, UIScaler.pixel(4), 0)
        layout_body.setSpacing(UIScaler.pixel(10))
        for section in self.themes:
            layout_body.addWidget(NotesCard(body, section))
        if not self.themes:
            empty = QLabel(tr("No release notes for this version."))
            empty.setEnabled(False)
            layout_body.addWidget(empty)
        self.button_details = QPushButton()
        self.button_details.setObjectName("notesToggle")
        self.button_details.setCheckable(True)
        self.button_details.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button_details.toggled.connect(self.toggle_details)
        self.details_box = QWidget()
        layout_details = QVBoxLayout(self.details_box)
        layout_details.setContentsMargins(0, 0, 0, 0)
        layout_details.setSpacing(UIScaler.pixel(10))
        for section in self.details:
            if section.title in COMMIT_KINDS:  # commit kind headings of release notes, translated
                section = section._replace(title=tr(section.title))
            layout_details.addWidget(NotesCard(self.details_box, section, monospace=section.title == "SHA256"))
        layout_body.addWidget(self.button_details, alignment=Qt.AlignmentFlag.AlignLeft)
        layout_body.addWidget(self.details_box)
        layout_body.addStretch(1)
        self.button_details.setHidden(not self.details)
        self.toggle_details(False)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)

        # Actions
        button_github = QPushButton(tr("View On GitHub"))
        button_github.clicked.connect(lambda: QDesktopServices.openUrl(release_url()))
        self.button_skip = FocusRingButton(tr("Skip This Version"))
        self.button_skip.setToolTip(tr("Not shown again for this version, shown again for a newer one"))
        self.button_skip.clicked.connect(self.request_skip)
        self.button_skip.setVisible(can_skip and newer)
        self.button_close = QPushButton(tr("Later") if prompt else tr("Close"))
        self.button_close.clicked.connect(self.close)
        self.button_install = QPushButton(tr("Install Now") if prompt else tr("Download And Install"))
        self.button_install.setObjectName("notesPrimary")
        self.button_install.clicked.connect(self.request_install)
        self.button_install.setDefault(True)
        if portable:
            self.button_install.setText(tr("Open Releases Page"))
            self.button_install.setToolTip(tr(PORTABLE_UPDATE_NOTE))
        elif not can_install:
            self.button_install.setToolTip(tr("Opens the download in your browser, extract the ZIP and run the installer"))
        layout_buttons = QHBoxLayout()
        layout_buttons.addWidget(button_github)
        layout_buttons.addWidget(self.button_skip)
        layout_buttons.addStretch(1)
        layout_buttons.addWidget(self.button_close)
        layout_buttons.addWidget(self.button_install)

        # Download progress (installed app), with cancel
        self.download_box = QWidget(self)
        self.progress_bar = QProgressBar(self.download_box)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAccessibleName(tr("Download progress"))
        self.label_progress = QLabel(self.download_box)
        self.button_cancel = FocusRingButton(tr("Cancel Download"), self.download_box)
        self.button_cancel.clicked.connect(self.cancel_download)
        layout_download = QHBoxLayout(self.download_box)
        layout_download.setContentsMargins(0, 0, 0, 0)
        layout_download.addWidget(self.label_progress)
        layout_download.addWidget(self.progress_bar, stretch=1)
        layout_download.addWidget(self.button_cancel)
        self.download_box.setHidden(True)
        if self.installer is not None:
            self.installer.busy_changed.connect(self.download_state)
            self.installer.progress.connect(self.download_progress)

        # Header & actions stay, notes fill the rest of the window (scrolled when longer)
        layout_main = QVBoxLayout(self)
        margin = UIScaler.pixel(14)
        layout_main.setContentsMargins(margin, margin, margin, margin)
        layout_main.setSpacing(UIScaler.pixel(8))
        layout_main.addLayout(layout_title)
        layout_main.addWidget(self.label_detail)
        layout_main.addSpacing(UIScaler.pixel(4))
        layout_main.addWidget(scroll, stretch=1)
        if portable:  # installer would install another copy elsewhere, without presets & data
            note = QLabel(tr(PORTABLE_UPDATE_NOTE))
            note.setWordWrap(True)
            layout_main.addWidget(note)
        layout_main.addWidget(self.download_box)
        layout_main.addLayout(layout_buttons)
        self.resize(UIScaler.size(42), UIScaler.size(40))
        if self.installer is not None and self.installer.busy:  # page opened while downloading
            self.download_state(True)

    def showEvent(self, event):
        """Shown as page: page has its own Close button (Later kept when asking to install)"""
        super().showEvent(event)
        if self.in_app_page and not self.prompt:
            self.button_close.hide()

    def toggle_details(self, shown: bool):
        """Commits & checksums folded by default"""
        self.details_box.setVisible(shown)
        label = tr("Hide Technical Details") if shown else tr("Show Technical Details")
        self.button_details.setText(f"{label} ({tr('commits, SHA256')})")

    def request_install(self):
        """Installed Windows app: install asked (downloaded & run by caller), else download opened in browser

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
        self.download_box.setVisible(busy)
        self.button_install.setEnabled(not busy)
        self.button_skip.setEnabled(not busy)
        self.button_cancel.setEnabled(busy)
        if busy and self.installer is not None:
            self.download_progress(self.installer.received, self.installer.total)
            self.button_cancel.setFocus(Qt.FocusReason.OtherFocusReason)

    def download_progress(self, received: int, total: int):
        """Percent & size downloaded (busy bar while size is unknown)"""
        if total > 0:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(min(round(received * 1000 / total), 1000))
        else:
            self.progress_bar.setRange(0, 0)
        text = download_progress_text(received, total) if received else ""
        self.label_progress.setText(f"{tr('Downloading Update...')} {text}".strip())
        self.progress_bar.setAccessibleDescription(text)

    def cancel_download(self):
        """Stop download, partial file removed"""
        if self.installer is not None:
            self.button_cancel.setEnabled(False)
            self.installer.cancel()
