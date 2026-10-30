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
What's New page backend (qml/home/ReleaseNotes.qml): release notes as rows of one list

Rows: version headers (several versions: skipped updates, versions since the last one run), "### group"
headings, cards ("#### theme": bullets with sub-bullets, screenshots, overlay actions) and folds (before /
after visuals, technical details: commits & checksums). Search filters cards (folds opened), the contents
chips jump to a version or group, the version menu shows any version of the local changelog (offline).
Option keys written in notes (`show_apex_speed`) open their option; overlays named by a card title can be
turned on (Try) or opened in Overlay Options. Screenshots are loaded on a worker thread when their card is
built (list delegates near the view: visible ones first), one at a time; their size is read first (file
header) so the card keeps its height, and QML decodes them at shown width only.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, NamedTuple

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QImageReader, QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from ... import app_signal
from ...const_common import DATE_NA
from ...const_file import ConfigType
from ...i18n import current_language, tr, trm
from ...i18n.options import format_module_name, module_label
from ...setting import cfg
from ...update import changelog_image_file, release_url
from ...version import __version__ as app_version
from ...version_check import parse_version_string
from ..module_view import sort_key
from ..release_notes import (
    COMMIT_KINDS,
    VISUALS_GROUP,
    NotesItem,
    Release,
    format_release_date,
    inline_html,
    notes_image,
    plain_text,
    split_notes,
    version_text,
)
from . import open_web_link
from .models import DictListModel
from .page_backend import PageBackend

if TYPE_CHECKING:
    from ..option_finder import OptionEntry

logger = logging.getLogger(__name__)

ROLES = ("key", "kind", "title", "subtitle", "items", "overlays", "expanded", "count")
KIND_VERSION = "version"
KIND_GROUP = "group"
KIND_CARD = "card"
KIND_FOLD = "fold"
FOLD_VISUALS = "visuals"
FOLD_DETAILS = "details"
DEFAULT_VIEW = ""  # version menu: notes the page was opened with
MAX_OVERLAY_ACTIONS = 2  # overlays named by a card title with Try / Options buttons
MIN_LABEL_LENGTH = 3  # shorter overlay names never matched in titles
IMAGE_ALLOCATION_LIMIT = 128  # MB, decoded screenshot


class Card(NamedTuple):
    """Card of a release, built once (rows of searches & folds reuse its row)"""

    key: str
    group: str  # shown group heading
    fold: str  # "" (themes), FOLD_VISUALS or FOLD_DETAILS
    search: str  # case & accent folded text
    row: dict


def image_size(url: str) -> tuple[str, int, int]:
    """Worker thread: local file of changelog screenshot (downloaded if needed) & its size (file header only,
    decoded by QML at shown size)"""
    path = changelog_image_file(url)
    reader = QImageReader(path)
    reader.setAllocationLimit(IMAGE_ALLOCATION_LIMIT)
    size = reader.size()
    if not size.isValid() or size.isEmpty() or not reader.canRead():
        raise OSError(f"changelog image not readable: {reader.errorString()}")
    return path, size.width(), size.height()


def overlay_labels() -> list[tuple[re.Pattern, str]]:
    """(name pattern, overlay) of every overlay, longest names first (Relative Finish Order before Relative):
    displayed name in app language & English name, whole words, case & accents ignored"""
    from ...module_control import wctrl

    labels: dict[str, str] = {}
    for name in wctrl.names:
        for label in (module_label(name), format_module_name(name)):
            folded = sort_key(label).strip()
            if len(folded) >= MIN_LABEL_LENGTH:
                labels.setdefault(folded, name)
    return [(re.compile(rf"(?<!\w){re.escape(label)}(?!\w)"), name)
            for label, name in sorted(labels.items(), key=lambda pair: -len(pair[0]))]


def overlays_named(title: str, labels: list[tuple[re.Pattern, str]]) -> list[str]:
    """Overlays named by a card title, in title order, at most MAX_OVERLAY_ACTIONS"""
    text = sort_key(title)
    found: list[tuple[int, str]] = []
    for pattern, name in labels:
        match = pattern.search(text)
        if match is None or any(name == other for _, other in found):
            continue
        found.append((match.start(), name))
        text = f"{text[:match.start()]}{' ' * (match.end() - match.start())}{text[match.end():]}"  # no sub-name
    return [name for _, name in sorted(found)][:MAX_OVERLAY_ACTIONS]


class ReleaseNotesBackend(PageBackend):
    """What's New page: rows, search, contents, version menu, screenshots, install state

    Args:
        releases: notes shown at start, newest first (several: versions since the installed or last run one).
        newer: first release is newer than the running version (update).
        prompt: asking to install (Install Now, Later).
        installable: install button shown (update notes, not notes of running version).
        can_install: app downloads & runs the installer (else download opened in browser).
        portable: portable copy (updated by hand from the releases page).
        can_skip: update notice can be skipped (shown for a newer version only).
        since: version run before an update (notes since then), empty if none.
    """

    rowsChanged = Signal()
    headerChanged = Signal()
    searchChanged = Signal()
    imagesChanged = Signal()
    overlaysChanged = Signal()
    installChanged = Signal()
    settingChanged = Signal()
    installClicked = Signal()
    skipClicked = Signal()
    cancelClicked = Signal()
    closeClicked = Signal()
    overlayTried = Signal(str, str)  # overlay turned on by Try: name & message (Undo offered)

    def __init__(self, parent: QObject, releases: list[Release], newer: bool = False, prompt: bool = False,
                 installable: bool = False, can_install: bool = False, portable: bool = False,
                 can_skip: bool = False, since: str = ""):
        super().__init__(parent, "Release notes")
        self._default = releases
        self._releases = releases
        self._newer = newer
        self._prompt = prompt
        self._installable = installable
        self._can_install = can_install
        self._portable = portable
        self._can_skip = can_skip and newer
        self._since = since
        self._view = DEFAULT_VIEW
        self._history: list[Release] | None = None  # local changelog, read when the version menu needs it
        self._versions: list[dict] | None = None
        self._option_keys: frozenset[str] | None = None
        self._labels: list[tuple[re.Pattern, str]] | None = None
        self._cards: list[list[Card]] = []
        self._expanded: set[str] = set()
        self._words: tuple[str, ...] = ()
        self._search = ""
        self._found = 0
        self._toc: list[dict] = []
        self._images: dict[str, dict] = {}  # url: status (loading, ready, failed), source, width, height
        self._image_queue: list[str] = []  # waiting screenshots, in request order (near the view first)
        self._image_loading = ""
        self._image_list: list[dict] = []  # screenshots of shown rows (viewer navigation)
        self._enabled_overlays: list[str] = []
        self._tried: list[str] = []  # overlays turned on by Try, last last (Ctrl+Z, Undo of the toast)
        self._undo_shortcut: QShortcut | None = None
        if isinstance(parent, QWidget):  # Ctrl+Z on this page undoes the last Try, as the Undo of its toast
            self._undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), parent, self.undoLastTry)
            self._undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._undo_shortcut.setEnabled(False)
        self._close_visible = True
        self._downloading = False
        self._cancelling = False
        self._progress = -1.0
        self._progress_text = ""
        self.model = DictListModel(ROLES, self)
        self._build_cards()
        self._refresh_rows(reset=True)
        self._refresh_overlays()
        self._detail = self._detail_text()

    def first_version(self) -> tuple[int, int, int] | None:
        """Version of the notes opened with (newest), None if none"""
        return self._default[0].version if self._default else None

    # Content -----------------------------------------------------------------------------------------------

    def _option_key_set(self) -> frozenset[str]:
        """Keys of every option of preset & application (code spans of notes that name one become option links),
        read from the settings (the option search index costs 100+ ms to build, read on click only)"""
        if self._option_keys is None:
            keys: set[str] = set()
            for settings in (cfg.user.setting, cfg.user.config):
                for options in settings.values():
                    if isinstance(options, dict):
                        keys.update(options)
            self._option_keys = frozenset(keys)
        return self._option_keys

    def _overlay_labels(self) -> list[tuple[re.Pattern, str]]:
        if self._labels is None:
            self._labels = overlay_labels()
        return self._labels

    def _build_cards(self):
        """Cards of shown releases (rows built once, search text folded once)"""
        keys = self._option_key_set()
        labels = self._overlay_labels()
        self._cards = []
        for index, release in enumerate(self._releases):
            themes, details = split_notes(release.notes)
            cards = []
            for number, section in enumerate((*themes, *details)):
                fold = "" if number < len(themes) else FOLD_VISUALS if section.group == VISUALS_GROUP else FOLD_DETAILS
                group = tr(section.group) if fold == FOLD_DETAILS and section.group in COMMIT_KINDS else section.group
                if fold == FOLD_VISUALS:
                    group = ""  # fold title says it
                    items = [item for item in section.items if notes_image(item.text) is not None]
                else:
                    items = section.items
                if not items:
                    continue
                key = f"{index}:{number}"
                row = {
                    "key": key, "kind": KIND_CARD, "title": inline_html(section.title, keys), "subtitle": "",
                    "items": [self._item(item, keys) for item in items],
                    "overlays": overlays_named(section.title, labels) if section.title and not fold else [],
                    "expanded": False, "count": 0,
                }
                search = sort_key(" ".join((group, plain_text(section.title), *(plain_text(item.text) for item in items))))
                cards.append(Card(key, group, fold, search, row))
            self._cards.append(cards)

    @staticmethod
    def _item(item: NotesItem, keys: frozenset[str]) -> dict:
        image = notes_image(item.text)
        if image is not None:
            return {"html": "", "level": 0, "bullet": False, "image": image[1], "caption": image[0]}
        return {"html": inline_html(item.text, keys), "level": item.level, "bullet": item.bullet, "image": "",
                "caption": ""}

    def _refresh_rows(self, reset: bool = False):
        """Rows of shown releases: search & open folds applied (synced in place: scroll position kept)"""
        rows: list[dict] = []
        toc: list[dict] = []
        several = len(self._releases) > 1
        words = self._words
        found = 0
        for index, release in enumerate(self._releases):
            cards = [card for card in self._cards[index] if all(word in card.search for word in words)]
            found += len(cards)
            if not cards and (words or several):
                continue
            if several:
                key = f"{index}:version"
                toc.append({"key": key, "label": version_text(release.version)})
                rows.append({
                    "key": key, "kind": KIND_VERSION, "title": f"{tr('Version')} {version_text(release.version)}",
                    "subtitle": format_release_date(release.date), "items": [], "overlays": [], "expanded": False,
                    "count": len(cards),
                })
            for fold in ("", FOLD_VISUALS, FOLD_DETAILS):
                fold_cards = [card for card in cards if card.fold == fold]
                if not fold_cards:
                    continue
                if fold:
                    key = f"{index}:{fold}"
                    expanded = bool(words) or key in self._expanded
                    count = (sum(len(card.row["items"]) for card in fold_cards) if fold == FOLD_VISUALS
                             else len(fold_cards))
                    rows.append({
                        "key": key, "kind": KIND_FOLD,
                        "title": tr("Before / After") if fold == FOLD_VISUALS else tr("Technical Details"),
                        "subtitle": "" if fold == FOLD_VISUALS else tr("commits, SHA256"),
                        "items": [], "overlays": [], "expanded": expanded, "count": count,
                    })
                    if not expanded:
                        continue
                group = ""
                for card in fold_cards:
                    if card.group and card.group != group:
                        key = f"{card.key}:group"
                        rows.append({"key": key, "kind": KIND_GROUP, "title": inline_html(card.group), "subtitle": "",
                                     "items": [], "overlays": [], "expanded": False, "count": 0})
                        if not several and not fold:
                            toc.append({"key": key, "label": plain_text(card.group)})
                    group = card.group
                    rows.append(card.row)
        if reset:
            self.model.reset(rows)
        else:
            self.model.sync(rows, reset_if_mostly_new=True)
        self._found = found
        self._toc = toc if len(toc) > 1 else []
        self._image_list = [{"url": item["image"], "caption": item["caption"]} for row in rows
                            for item in row["items"] if item["image"]]
        self.rowsChanged.emit()
        self.searchChanged.emit()

    def _refresh_overlays(self):
        enabled = [name for name, options in cfg.user.setting.items()
                   if isinstance(options, dict) and options.get("enable") and name in self._named_overlays()]
        if enabled != self._enabled_overlays:
            self._enabled_overlays = enabled
            self.overlaysChanged.emit()

    def _named_overlays(self) -> set[str]:
        return {name for cards in self._cards for card in cards for name in card.row["overlays"]}

    def page_shown(self):
        self._refresh_overlays()  # turned on or off elsewhere meanwhile

    # Header ------------------------------------------------------------------------------------------------

    def _first(self) -> Release | None:
        return self._releases[0] if self._releases else None

    @Property(str, notify=headerChanged)
    def title(self) -> str:
        first = self._first()
        return f"{tr('Version')} {version_text(first.version)}" if first is not None else tr("What's New")

    @Property(str, notify=headerChanged)
    def chip(self) -> str:
        """New Version, Installed (running version), empty for an older version of the history"""
        first = self._first()
        if first is None:
            return ""
        running = parse_version_string(app_version)
        if self._view == DEFAULT_VIEW and self._newer:
            return tr("New Version")
        return tr("Installed") if first.version == running else ""

    @Property(bool, notify=headerChanged)
    def chipNew(self) -> bool:
        return self._view == DEFAULT_VIEW and self._newer

    @Property(str, notify=headerChanged)
    def detail(self) -> str:
        """Release date, version installed or updated from, versions shown"""
        return self._detail

    def _detail_text(self) -> str:
        first = self._first()
        if first is None:
            return ""
        released = format_release_date(first.date) if first.date != DATE_NA else ""
        parts = [f"{tr('Released')} {released}" if released else ""]
        if self._view == DEFAULT_VIEW:
            if self._since:
                parts.append(f"{tr('Updated from')} {self._since}")
            elif self._installable:
                from ..home_view import base_version

                parts.append(f"{tr('Installed version')} {base_version()}")
            if len(self._releases) > 1:
                parts.append(f"{len(self._releases)} versions")  # same word in French
        return " · ".join(part for part in parts if part)

    @Property(QObject, constant=True)
    def notes(self) -> QObject:
        """Rows: version headers, group headings, cards & folds"""
        return self.model

    # Search & contents -------------------------------------------------------------------------------------

    @Property(str, notify=searchChanged)
    def searchText(self) -> str:
        return self._search

    @Property(int, notify=searchChanged)
    def foundCount(self) -> int:
        return self._found

    @Property(bool, notify=searchChanged)
    def searching(self) -> bool:
        return bool(self._words)

    @Slot(str)
    def setSearch(self, text: str):
        words = tuple(sort_key(text).split())
        self._search = text
        if words != self._words:
            self._words = words
            self._refresh_rows()
        else:
            self.searchChanged.emit()

    @Property(list, notify=rowsChanged)
    def contents(self) -> list:
        """Contents chips: versions (several shown), else groups ("New", "Fixes"...), empty if one entry"""
        return self._toc

    @Slot(str, result=int)
    def rowOf(self, key: str) -> int:
        return self.model.index_of(key)

    @Slot(str)
    def toggleFold(self, key: str):
        """Open or close visuals / technical details"""
        if key in self._expanded:
            self._expanded.discard(key)
        else:
            self._expanded.add(key)
        self._refresh_rows()

    # Version menu (local changelog) ------------------------------------------------------------------------

    def _local_history(self) -> list[Release]:
        if self._history is None:
            from ..home_view import local_changelog

            self._history = [Release(parse_version_string(entry.version), entry.date, entry.body)
                             for entry in local_changelog(current_language())
                             if parse_version_string(entry.version) != (0, 0, 0)]
        return self._history

    @Property(list, constant=True)
    def versions(self) -> list:
        """Version menu: notes opened with first, then every version of the local changelog"""
        if self._versions is None:  # read once, when the menu is built
            self._versions = self._version_choices()
        return self._versions

    def _version_choices(self) -> list[dict]:
        first = self._default[0] if self._default else None
        if first is None:
            label = tr("What's New")
        elif len(self._default) > 1:
            label = f"{version_text(self._default[-1].version)} → {version_text(first.version)}"
        else:
            label = version_text(first.version)
        choices = [{"key": DEFAULT_VIEW, "label": label}]
        shown = {release.version for release in self._default} if len(self._default) == 1 else set()
        for release in self._local_history():
            if release.version not in shown:
                date = format_release_date(release.date)
                text = version_text(release.version)
                choices.append({"key": text, "label": f"{text} · {date}" if date else text})
        return choices

    @Property(str, notify=headerChanged)
    def view(self) -> str:
        return self._view

    @Slot(str)
    def showVersion(self, key: str):
        """Notes opened with (DEFAULT_VIEW), or one version of the local changelog"""
        if key == self._view:
            return
        if key == DEFAULT_VIEW:
            releases = self._default
        else:
            releases = [release for release in self._local_history() if version_text(release.version) == key][:1]
            if not releases:
                return
        self._view = key
        self._releases = releases
        self._expanded.clear()
        self._build_cards()
        self._refresh_rows(reset=True)
        self._refresh_overlays()
        self._detail = self._detail_text()
        self.headerChanged.emit()

    # Links: options, overlays, web -------------------------------------------------------------------------

    @Slot(str, str)
    def openLink(self, link: str, overlays: str = ""):
        """option:<key> opens the option (overlay of the card first, Find Option when several have it),
        web links open in browser

        Args:
            overlays: overlays named by the card, comma separated (preferred owner of an option key).
        """
        if link.startswith("option:"):
            self.open_option(link[7:], [name for name in overlays.split(",") if name])
        else:
            open_web_link(link, ("https", "http"))

    def host_window(self) -> QWidget | None:
        """Window pages open from (options, Find Option): main window when shown as page, else the one that opened
        it. Read when used: the update button that opened the page is rebuilt by a language change"""
        dialog = self.parent()
        if not isinstance(dialog, QWidget):
            return None
        window = dialog.window()
        opener = dialog.parentWidget()
        return opener.window() if window is dialog and opener is not None else window

    def option_entries(self, key: str) -> list[OptionEntry]:
        from ..option_finder import cached_index

        return [entry for entry in cached_index() if entry.key == key]

    def open_option(self, key: str, overlays: list[str]):
        from ..option_finder import OptionFinder, open_option

        entries = self.option_entries(key)
        preferred = [entry for entry in entries if entry.section in overlays]
        if preferred or len(entries) == 1:
            open_option(self.host_window(), (preferred or entries)[0])
            return
        finder = OptionFinder(self.host_window())  # every overlay or module having it
        if hasattr(finder, "shown_dialog"):  # else already open as a window: DialogSingletonError
            finder.show()
            set_search = getattr(finder.shown_dialog(), "set_search", None)
            if callable(set_search):
                set_search(key)

    @Slot(str, result=str)
    def optionTip(self, link: str) -> str:
        """Tooltip of an option link"""
        if not link.startswith("option:"):
            return link
        from ...i18n.options import option_label

        return f"{option_label(link[7:])} · {tr('Open option')}"

    @Property(list, notify=overlaysChanged)
    def enabledOverlays(self) -> list:
        return self._enabled_overlays

    @Slot(str, result=str)
    def overlayLabel(self, name: str) -> str:
        return module_label(name)

    @Slot(str)
    def tryOverlay(self, name: str):
        """Turn on overlay named by a card (saved in loaded preset), Undo offered by the page toast & Ctrl+Z"""
        from ...module_control import wctrl

        if name in wctrl.names and wctrl.set_enabled([name], True):
            logger.info("UPDATES: %s turned on from what's new", name)
            text = trm(f"Overlay turned on: {module_label(name)}")
            self.overlayTried.emit(name, text)
            self._tried = [*(tried for tried in self._tried if tried != name), name]
            self.tried_changed()
            page = self.parent()
            if isinstance(page, QWidget):
                from ..toast import show_toast

                show_toast(page, text, action_text=tr("Undo"), action=lambda: self.undo_tried(name))
            app_signal.refresh.emit(True)  # Overlays page, menus & tray follow
        self._refresh_overlays()

    @Slot()
    def undoLastTry(self):
        """Ctrl+Z: last overlay turned on by Try turned off again (then the one before)"""
        if self._tried:
            self.undo_tried(self._tried[-1])

    def undo_tried(self, name: str):
        """Undo of a toast: overlay turned on by that Try turned off again, once"""
        if name in self._tried:
            self.undoTry(name)

    def tried_changed(self):
        if self._undo_shortcut is not None:
            self._undo_shortcut.setEnabled(bool(self._tried))

    @Slot(str)
    def undoTry(self, name: str):
        """Overlay turned on by Try turned off again"""
        from ...module_control import wctrl

        if name in self._tried:
            self._tried.remove(name)
            self.tried_changed()

        if name in wctrl.names and wctrl.set_enabled([name], False):
            logger.info("UPDATES: %s turned off again from what's new", name)
            app_signal.refresh.emit(True)
        self._refresh_overlays()

    @Slot(str)
    def overlayOptions(self, name: str):
        from ..overlay_options import open_overlay_options

        open_overlay_options(self.host_window(), name)

    # Screenshots -------------------------------------------------------------------------------------------

    @Property(dict, notify=imagesChanged)
    def images(self) -> dict:
        """url: status ("loading", "ready", "failed"), source (local file url), width & height (pixels)"""
        return self._images

    @Property(list, notify=rowsChanged)
    def imageList(self) -> list:
        """Screenshots of shown rows in order: url & caption (viewer)"""
        return self._image_list

    @Slot(str)
    def requestImage(self, url: str):
        """Screenshot delegate built: loaded in request order (delegates near the view first)"""
        if url in self._images or url in self._image_queue or url == self._image_loading:
            return
        self._image_queue.append(url)
        self._load_next_image()

    @Slot(str)
    def dropImage(self, url: str):
        """Screenshot delegate gone (scrolled far away) before its turn: not loaded for now"""
        if url in self._image_queue:
            self._image_queue.remove(url)

    def _load_next_image(self):
        if self._image_loading or not self._image_queue or self.page_released:
            return
        url = self._image_loading = self._image_queue.pop(0)
        self._set_image(url, {"status": "loading"})
        self.jobs.run("Changelog image", lambda: image_size(url), self._image_loaded, self._image_failed)

    def _set_image(self, url: str, state: dict):
        self._images = {**self._images, url: state}
        self.imagesChanged.emit()

    def _image_loaded(self, result: tuple[str, int, int]):
        path, width, height = result
        url, self._image_loading = self._image_loading, ""
        self._set_image(url, {"status": "ready", "source": QUrl.fromLocalFile(path).toString(),
                              "width": width, "height": height})
        self._load_next_image()

    def _image_failed(self, error: BaseException):
        logger.info("UPDATES: changelog image not shown: %s", error)
        url, self._image_loading = self._image_loading, ""
        self._set_image(url, {"status": "failed"})
        self._load_next_image()

    @Slot(str)
    def openImage(self, url: str):
        """Screenshot in default image viewer (local file once loaded), else online"""
        state = self._images.get(url, {})
        if state.get("status") == "ready":
            QDesktopServices.openUrl(QUrl(state["source"]))  # local file of the cache
        else:
            open_web_link(url)  # address of release notes text: https only

    # Install, download, actions ----------------------------------------------------------------------------

    @Property(bool, notify=installChanged)
    def installVisible(self) -> bool:
        return self._installable

    @Property(str, constant=True)
    def installText(self) -> str:
        if self._portable:
            return tr("Open Releases Page")
        return tr("Install Now") if self._prompt else tr("Download And Install")

    @Property(str, constant=True)
    def installTip(self) -> str:
        from ..release_notes import PORTABLE_UPDATE_NOTE

        if self._portable:
            return tr(PORTABLE_UPDATE_NOTE)
        if not self._can_install:
            return tr("Opens the download in your browser, extract the ZIP and run the installer")
        return ""

    @Property(str, constant=True)
    def portableNote(self) -> str:
        """Installer would install another copy elsewhere, without presets & data"""
        from ..release_notes import PORTABLE_UPDATE_NOTE

        return tr(PORTABLE_UPDATE_NOTE) if self._portable and self._installable else ""

    @Property(bool, constant=True)
    def skipVisible(self) -> bool:
        return self._can_skip and self._installable

    @Property(str, constant=True)
    def closeText(self) -> str:
        return tr("Later") if self._prompt else tr("Close")

    @Property(bool, notify=installChanged)
    def closeVisible(self) -> bool:
        return self._close_visible

    def set_close_visible(self, visible: bool):
        if visible != self._close_visible:
            self._close_visible = visible
            self.installChanged.emit()

    @Property(bool, notify=installChanged)
    def downloading(self) -> bool:
        return self._downloading

    @Property(bool, notify=installChanged)
    def cancelling(self) -> bool:
        return self._cancelling

    @Property(float, notify=installChanged)
    def progress(self) -> float:
        """Downloaded part 0 - 1, -1 while size is unknown"""
        return self._progress

    @Property(str, notify=installChanged)
    def progressText(self) -> str:
        return self._progress_text

    def set_downloading(self, busy: bool):
        self._downloading = busy
        self._cancelling = False
        if not busy:
            self._progress, self._progress_text = -1.0, ""
        self.installChanged.emit()

    def set_cancelling(self):
        self._cancelling = True
        self.installChanged.emit()

    def set_progress(self, value: float, text: str):
        if (value, text) != (self._progress, self._progress_text):
            self._progress, self._progress_text = value, text
            self.installChanged.emit()

    @Slot()
    def install(self):
        self.installClicked.emit()

    @Slot()
    def skip(self):
        self.skipClicked.emit()

    @Slot()
    def cancelDownload(self):
        self.cancelClicked.emit()

    @Slot()
    def close(self):
        self.closeClicked.emit()

    @Slot()
    def openGitHub(self):
        QDesktopServices.openUrl(QUrl(release_url()))

    @Property(bool, notify=settingChanged)
    def showAfterUpdate(self) -> bool:
        return bool(cfg.application["show_release_notes_after_update"])

    @Slot(bool)
    def setShowAfterUpdate(self, shown: bool):
        """What's new shown at first start after each update (show_release_notes_after_update)"""
        if shown != self.showAfterUpdate:
            cfg.application["show_release_notes_after_update"] = shown
            cfg.save(0, config_type=ConfigType.CONFIG)
            self.settingChanged.emit()
