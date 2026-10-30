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
Tools page backend (qml/shell/Tools.qml): pages left out of the navigation bar (Pages section, as the Tools menu),
listed tools by section with what each is for, whether it is in the navigation bar, live state of tools with an
on / off switch, search by name, description & former names
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from ...i18n import tr
from ...template.page_registry import page_spec
from ..module_view import sort_key


def page_entries(rail: set[str]) -> list[dict]:
    """Main window pages left out of the navigation bar (Pages section, as the Tools menu), Tools page apart"""
    from ..nav_rail import NAV_PAGES, page_name
    from ..tools_view import PAGE_PATH

    entries = []
    for index, (key, _, glyph, letter) in enumerate(NAV_PAGES):
        if key in rail or key == "tools":
            continue
        spec = page_spec(key)
        label = page_name(index)
        description = tr(spec.description) if spec is not None and spec.description else ""
        entries.append({
            "path": f"{PAGE_PATH}{key}",
            "name": key,
            "label": label,
            "glyph": glyph,
            "letter": letter or label[:1],
            "description": description,
            "inRail": False,
            "search": sort_key(" ".join((label, key, description))),
        })
    return entries


def tool_entries() -> list[tuple[str, list[dict]]]:
    """Pages left out of the navigation bar, then listed tools by section: (section title, [entry, ...]), texts in
    app language"""
    from ..nav_rail import current_rail_items, rail_text
    from ..tools_view import LISTED_TOOL_SECTIONS, TOOL_KEYWORDS

    rail = set(current_rail_items())
    pages = page_entries(rail)
    sections = [(tr("Pages"), pages)] if pages else []
    for title, tools in LISTED_TOOL_SECTIONS:
        entries = []
        for label, glyph, path in tools:
            spec = page_spec(path)
            description = tr(spec.description) if spec is not None and spec.description else ""
            short = spec.short_label if spec is not None else ""
            entries.append({
                "path": path,
                "name": path.rsplit(".", 1)[-1],
                "label": tr(label),
                "glyph": glyph,
                "letter": rail_text(short, label)[:1] if short else tr(label)[:1],
                "description": description,
                "inRail": path.split(".", 1)[0] in rail,
                "search": sort_key(" ".join((tr(label), label, description, TOOL_KEYWORDS.get(path, "")))),
            })
        sections.append((tr(title), entries))
    return sections


class ToolsBackend(QObject):
    """State of Tools page: sections of tools (filtered by search), live states"""

    sectionsChanged = Signal()
    statusesChanged = Signal()
    searchChanged = Signal()

    def __init__(self, parent: QObject | None, open_tool: Callable[[str], object]):
        super().__init__(parent)
        self._open_tool = open_tool
        self._all = tool_entries()
        self._search = ""
        self._sections: list[dict] = []
        self._shown = 0  # tools shown (every section)
        self._statuses: dict[str, str] = {}
        self._filter()

    def _filter(self):
        """Sections shown: tools matching every word of search (any order, case & accents ignored)"""
        words = sort_key(self._search).split()
        sections = []
        for title, tools in self._all:
            shown = [{key: value for key, value in tool.items() if key != "search"} for tool in tools
                     if all(word in tool["search"] for word in words)]
            if shown:
                sections.append({"title": title, "tools": shown})
        if sections != self._sections:
            self._sections = sections
            self._shown = sum(len(section["tools"]) for section in sections)
            self.sectionsChanged.emit()

    def refresh(self):
        """Rail entries or language changed: tool entries read again"""
        self._all = tool_entries()
        self._filter()

    def set_statuses(self, statuses: dict[str, str]):
        """Live states by dialog class name ("on", "off", "" closed), emitted only when changed"""
        if statuses != self._statuses:
            self._statuses = dict(statuses)
            self.statusesChanged.emit()

    @Property(list, notify=sectionsChanged)
    def sections(self) -> list[dict]:
        return self._sections

    @Property(int, notify=sectionsChanged)
    def shownCount(self) -> int:
        return self._shown

    @Property(dict, notify=statusesChanged)
    def statuses(self) -> dict[str, str]:
        return self._statuses

    @Property(str, notify=searchChanged)
    def search(self) -> str:
        return self._search

    @Slot(str)
    def setSearch(self, text: str):
        if text != self._search:
            self._search = text
            self.searchChanged.emit()
            self._filter()

    @Slot(str)
    def openTool(self, path: str):
        """Open tool once the click is done (its page is shown over this one)"""
        QTimer.singleShot(0, self, lambda: self._open_tool(path))
