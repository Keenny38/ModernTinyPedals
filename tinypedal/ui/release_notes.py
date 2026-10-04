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
SHA256 checksums. Shown as a header (version, date, installed version), one card per theme,
and technical details (commits, checksums) folded below. Also asks to install a new version
(prompt mode).
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
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..const_app import VERSION
from ..i18n import current_language, tr
from ..update import release_url
from ..version import __version__ as app_version
from ..version_check import parse_version_string
from ._common import BaseDialog, UIScaler

DETAILS_HEADING = "## Commits"  # technical part of notes starts here
COMMIT_KINDS = ("Added", "Fixed", "Changed")  # see tools/gen_release_notes.py
_bold = re.compile(r"\*\*(.+?)\*\*")
_code = re.compile(r"`([^`]+)`")
_link = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


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
        if not line:
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
    """What's new of an available update, optionally asking to install it"""

    install_requested = Signal()

    def __init__(self, parent, notes: str, version: tuple[int, int, int], date: tuple[int, int, int],
                 can_install: bool = False, prompt: bool = False, download_url: str = ""):
        super().__init__(parent)
        self.prompt = prompt
        self.can_install = can_install  # installed Windows app: downloads & runs installer
        self.download_url = download_url  # else: download opened in browser (installer, or release page)
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
        self.button_close = QPushButton(tr("Later") if prompt else tr("Close"))
        self.button_close.clicked.connect(self.close)
        self.button_install = QPushButton(tr("Install Now") if prompt else tr("Download And Install"))
        self.button_install.setObjectName("notesPrimary")
        self.button_install.clicked.connect(self.request_install)
        self.button_install.setDefault(True)
        if not can_install:
            self.button_install.setToolTip(tr("Opens the download in your browser, run it to install"))
        layout_buttons = QHBoxLayout()
        layout_buttons.addWidget(button_github)
        layout_buttons.addStretch(1)
        layout_buttons.addWidget(self.button_close)
        layout_buttons.addWidget(self.button_install)

        # Header & actions stay, notes fill the rest of the window (scrolled when longer)
        layout_main = QVBoxLayout(self)
        margin = UIScaler.pixel(14)
        layout_main.setContentsMargins(margin, margin, margin, margin)
        layout_main.setSpacing(UIScaler.pixel(8))
        layout_main.addLayout(layout_title)
        layout_main.addWidget(self.label_detail)
        layout_main.addSpacing(UIScaler.pixel(4))
        layout_main.addWidget(scroll, stretch=1)
        layout_main.addLayout(layout_buttons)
        self.resize(UIScaler.size(42), UIScaler.size(40))

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
        """Installed Windows app: install asked (downloaded & run by caller), else download opened in browser"""
        if self.can_install:
            self.install_requested.emit()
        else:
            QDesktopServices.openUrl(QUrl(self.download_url or release_url()))
        self.close()
