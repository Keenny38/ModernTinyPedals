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
Home page: state at a glance (game & session, checks, overlay, preset, last session & its debrief, driver)
& quick access

Qt Quick page (qml/home/Home.qml), state & actions in quick/home_backend.py. The QML page is created when first
shown, game & files are read only while it is shown. Quick access entries & release notes helpers are here (rail
& settings use them without the page).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, NamedTuple

from PySide6.QtCore import QUrl, Slot
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..api_control import api
from ..const_app import VERSION
from ..i18n import tr
from ..setting import cfg
from ..userfile.driver_history import SessionRecord, last_record
from .nav_rail import RailEditor
from .ordered_picker import PickerEntry

if TYPE_CHECKING:
    from ..update import ChangelogEntry

CHANGELOG_FILE = "CHANGELOG.md"  # next to app (release build) or project root (source)
# Quick access actions (besides tools & pages): key: (label, glyph, letter)
QUICK_ACTIONS = {
    "command_palette": ("Command Palette", "\ue721", "C"),  # search
    "bug_report": ("Create Bug Report", "\uebe8", "B"),  # bug
    "check_updates": ("Check for Updates", "\ue895", "U"),  # sync
}
QUICK_SHORTCUTS = {"command_palette": "Ctrl+K"}  # shown after label


class QuickEntry(NamedTuple):
    """Quick access entry: tool, page or action"""

    key: str
    label: str  # untranslated
    glyph: str
    letter: str  # drawn without icon font
    kind: str  # "tool", "page" or "action"
    target: str = ""  # tool dialog path, page key


def quick_access_entries() -> dict[str, QuickEntry]:
    """Every possible quick access entry by key: tools, then pages (but home), then actions"""
    from .nav_rail import rail_entries

    tools, pages = {}, {}
    for key, entry in rail_entries().items():
        if entry.page >= 0:
            if key != "home":
                pages[key] = QuickEntry(key, entry.tooltip, entry.glyph, entry.letter, "page", key)
        else:
            tools[key] = QuickEntry(key, entry.tooltip, entry.glyph, entry.letter, "tool", entry.dialog)
    actions = {key: QuickEntry(key, label, glyph, letter, "action") for key, (label, glyph, letter) in QUICK_ACTIONS.items()}
    return {**tools, **pages, **actions}


def parse_quick_items(text: str) -> list[str]:
    """Known & unique entry keys of quick access setting text, in order"""
    from .tools_view import RENAMED_TOOL_KEYS

    known = quick_access_entries()
    keys: list[str] = []
    for key in (text or "").split(","):
        key = RENAMED_TOOL_KEYS.get(key.strip(), key.strip())  # merged tools: new tool
        if key in known and key not in keys:
            keys.append(key)
    return keys


def default_quick_items() -> list[str]:
    from ..template.setting_global import GLOBAL_DEFAULT

    application: dict = GLOBAL_DEFAULT["application"]  # type: ignore[assignment]
    return parse_quick_items(str(application["home_quick_access"]))


def current_quick_items() -> list[str]:
    """Quick access entry keys from setting (may be empty: user removed every entry)"""
    text = cfg.application.get("home_quick_access")
    return default_quick_items() if text is None else parse_quick_items(str(text))


class QuickAccessEditor(RailEditor):
    """Choose & order home page quick access entries"""

    TITLE = "Customize Quick Access"
    HELP = (
        "Buttons of home page: drag entries to reorder, or use the arrows. "
        "Add tools, pages or actions from the list on the right."
    )

    def picker_entries(self) -> dict[str, PickerEntry]:
        kinds = {
            "tool": (tr("Tools"), tr("Tool")), "page": (tr("Pages"), tr("Page")), "action": (tr("Actions"), tr("Action")),
        }
        return {
            key: PickerEntry(key, tr(entry.label), entry.glyph, entry.letter, kinds[entry.kind][0],
                             tag=kinds[entry.kind][1])
            for key, entry in quick_access_entries().items()
        }

    def badge_text(self, row: int) -> str:
        return str(row + 1)

    def current_items(self) -> list[str]:
        return current_quick_items()

    def default_items(self) -> list[str]:
        return default_quick_items()

    def save_items(self, keys: list[str]):
        cfg.application["home_quick_access"] = ",".join(keys)  # empty: no quick access button


def base_version(version: str = VERSION) -> str:
    """Version without development suffix: 0.19.1+3.g8a0f9f3 -> 0.19.1"""
    return version.split("+")[0].split("-")[0]


def read_changelog_entries(filename: str) -> list[ChangelogEntry]:
    """Changelog sections with release dates, empty if no changelog"""
    from ..update import changelog_entries

    try:
        with open(filename, encoding="utf-8") as file:
            return changelog_entries(file.read())
    except (OSError, UnicodeDecodeError):
        return []


_changelog_cache: dict[tuple[str, str], tuple[tuple, list[ChangelogEntry]]] = {}  # (language, file): (times, entries)


def _file_times(*filenames: str) -> tuple:
    """Modification time & size of each file, 0 when missing (cache key: files read again once changed)"""
    times = []
    for filename in filenames:
        try:
            found = os.stat(filename)
            times.append((found.st_mtime_ns, found.st_size))
        except OSError:
            times.append((0, 0))
    return tuple(times)


def local_changelog(language: str = "en", filename: str = CHANGELOG_FILE) -> list[ChangelogEntry]:
    """Changelog next to app, newest version first: section in language (CHANGELOG.<code>.md) when written,
    else English (works offline, every version: release notes history)

    Read once per language while the files are unchanged (What's New reads it twice when opened, the start of
    the app once more): a copy of the cached list is returned.
    """
    from ..update import localized_changelog_name
    from ..version_check import parse_version_string

    translated = localized_changelog_name(language, filename) if language != "en" else ""
    times = _file_times(filename, translated) if translated else _file_times(filename)
    cached = _changelog_cache.get((language, filename))
    if cached is not None and cached[0] == times:
        return list(cached[1])
    sections = {entry.version: entry for entry in read_changelog_entries(filename)}
    if translated:
        sections.update((entry.version, entry) for entry in read_changelog_entries(translated))
    entries = sorted(sections.values(), key=lambda entry: parse_version_string(entry.version), reverse=True)
    _changelog_cache[(language, filename)] = (times, entries)
    return list(entries)


def read_changelog(filename: str) -> list[tuple[str, str]]:
    """Changelog sections (version, body), empty if no changelog"""
    from ..update import changelog_sections

    try:
        with open(filename, encoding="utf-8") as file:
            return changelog_sections(file.read())
    except (OSError, UnicodeDecodeError):
        return []


def current_release_notes(filename: str = CHANGELOG_FILE, version: str = VERSION, language: str = "en") -> str:
    """Changelog section of running version in language (CHANGELOG.<code>.md), empty if no changelog

    Section of running version in language, else in English (not translated yet), else
    newest section (development version).
    """
    from ..update import localized_changelog_name

    translated = read_changelog(localized_changelog_name(language, filename)) if language != "en" else []
    english = read_changelog(filename)
    base = base_version(version)
    for sections in (translated, english):
        body = next((body for name, body in sections if name == base), None)
        if body is not None:
            return body
    return (translated or english or [("", "")])[0][1]


def api_state_text() -> tuple[str, bool]:
    """API state text & whether game is running"""
    if cfg.api["enable_active_state_override"]:
        state = "overriding"
    else:
        state = api.read.state.version()
    return state, bool(state) and state not in ("not running", "0.0")


def last_session() -> SessionRecord | None:
    """Last driven session (driver stats history, end of file read), None if none"""
    try:
        return last_record(cfg.path.config)
    except OSError:
        return None


class HomeView(QWidget):
    """Home page

    Args:
        parent: page area.
        window: main window (tools, dialogs & command palette opened from it).
        select_page: shows a main window page by navigation key.
    """

    def __init__(self, parent, window, select_page):
        super().__init__(parent)
        from .quick.home_backend import HomeBackend

        self.backend = HomeBackend(self, window, select_page)
        self.view: QQuickWidget | None = None  # see ensure_view
        self._creating = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def ensure_view(self) -> QQuickWidget | None:
        """QML page, created on first use"""
        if self.view is None and not self._creating:
            from .quick import create_quick_view

            self._creating = True  # page shown again while QML loads: one page only
            try:
                view = create_quick_view(self, "Home.qml", {"backend": self.backend}, samples=0)
            finally:
                self._creating = False
            view.setAcceptDrops(False)  # preset & plugin files dropped go to main window
            self._layout.addWidget(view)
            view.show()  # child added to a shown page is not shown by itself
            self.setFocusProxy(view)
            self.view = view
        return self.view

    def showEvent(self, event):
        self.ensure_view()
        self.backend.page_shown()
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.page_hidden()  # nothing read while another page (or the race) is shown
        super().hideEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.release_page()

    def release_page(self):
        """Page closed or released (see LazyPage.release): QML gone before the backend it binds to, then the
        backend's jobs, timers & deferred work stopped"""
        if self.view is not None:
            view, self.view = self.view, None
            view.setSource(QUrl())
            view.deleteLater()
        self.backend.release()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Setting, preset or language changed: cards made again (once shown if hidden)"""
        self.backend.refresh()
