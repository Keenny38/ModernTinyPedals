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
Overlay Options page backend (qml/OverlayOptions.qml): options of every overlay, in one page

Overlays listed on the left (by category, with unsaved edits & search matches), options of the
selected one in sections (see overlay_sections): on/off option leading a section is its header
switch, options of an item that is off are dimmed. Only options of the overlay design in use are
shown (modern design or classic layout, following an unsaved design switch too).

Edits of any overlay stay pending (undo & redo) until applied: Apply saves the loaded preset once and
restarts only the edited overlays. Invalid values are marked at once and block Apply.

Tools: search in the selected overlay or in every overlay, "Modified" filter (options changed from
default), a value applied to every overlay having the option, display order list, reset of an option,
a section or an overlay, live preview with unsaved values. Black box keeps its declared sections,
simple mode, color themes and display profile (options set by profile are locked, see OptionUI).
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, NamedTuple, Protocol

from PySide6.QtCore import Property, QObject, QPoint, QTimer, Signal, Slot

from ...i18n import tr, trm
from ...i18n.options import module_label, option_help_specific, option_label
from ...module_control import ModuleControl
from ...setting import cfg
from ...template.widget import WIDGET_OPTION_UI
from ...template.widget.black_box_ui import OptionUI, theme_color
from ...widget._style import OVERLAY_SCALE_RANGE
from ..module_view import sort_key
from ..widget_preview import set_showing
from .models import DictListModel
from .option_kinds import (
    KIND_BOOL,
    KIND_CHOICE,
    KIND_COLOR,
    KIND_FONT,
    KIND_IMAGE,
    KIND_INTEGER,
    KIND_PATH,
    KIND_TEXT,
    NUMBER_KINDS,
    OptionKind,
    check_value,
    choice_label,
    choice_values,
    decimals,
    display_text,
    display_value,
    number_range,
    number_text,
    option_kind,
    parse_number,
    parse_path,
)
from .overlay_backend import CATEGORY_COLORS, CATEGORY_ORDER, widget_category
from .overlay_sections import (
    GENERAL_KEYS,
    ITEM_PREFIX,
    SECTION_ORDER,
    Section,
    auto_sections,
    declared_sections,
    listed_sections,
    order_keys,
    section_dependencies,
)
from .page_backend import PageBackend
from .preview_provider import STORE

logger = logging.getLogger(__name__)

ROW_ROLES = (
    "key", "overlay", "option", "row", "label", "help", "kind", "title", "first", "last",
    "toggle", "toggleChecked", "collapsed", "count", "changedCount", "customizedCount",
    "checked", "choices", "choiceIndex", "text", "number", "decimals", "step", "minimum", "maximum",
    "color", "modified", "changed", "error", "defaultText", "dimmed", "locked", "note", "hint", "shared",
    "table", "orders",
)
NAV_ROLES = (
    "key", "label", "category", "categoryLabel", "color", "enabled", "changed", "errors", "matches", "customized",
)
ROW_OPTION = "option"
ROW_HEADER = "header"
ROW_ORDER = "order"
# Options holding an ordered list of names (text, names separated by commas), edited as an order list:
# option key -> (help text, names offered besides those listed)
LIST_OPTIONS = {
    "class_order": (
        "Classes in multi-class split mode, top first: drag them, or use the arrows. "
        "Classes found in no list come after, fastest first.",
        lambda: list(cfg.user.classes),
    ),
}
MAX_ROWS = 400  # options shown at once (search in every overlay): more asks for a narrower search
PREVIEW_DELAY_MS = 250  # preview rendered once edits pause
PREVIEW_SCALE_MAX = 3.0  # zoomed preview drawn up to this size (sharp), scaled up above
PREVIEW_SCALE_STEP = 0.25  # zoom rounded up to a step: not drawn again for every few pixels
KEEP_HIDDEN_BYTES = 1 << 20  # bigger picture (zoomed) released while page is hidden
INFO_DELAY_MS = 100  # header of selected overlay (customized count) told once edits pause
WARM_INTERVAL_MS = 0  # options of other overlays read one per event loop tick
# Options always different from default (moved, switched on): not counted as customized
NOT_CUSTOMIZED = frozenset(("enable", "position_x", "position_y"))
PREVIEW_OFF = 0
PREVIEW_LOADING = 1
PREVIEW_READY = 2
PREVIEW_UNAVAILABLE = 3
PREVIEW_INVALID = 4
_MISSING = object()


class OverlayOptionsHost(Protocol):
    """Page hosting the backend: dialogs, notices & restarting saved overlays"""

    def confirm(self, text: str) -> bool: ...
    def pick_color(self, color: str) -> str: ...
    def pick_folder(self, folder: str) -> str: ...
    def pick_image(self, filename: str) -> str: ...
    def edit_table(self, text: str) -> str | None: ...
    def notify(self, text: str) -> None: ...
    def applied(self, names: list[str]) -> None: ...
    def export_overlays(self, names: list[str]) -> None: ...
    def import_overlays(self) -> None: ...


class OverlayLayout(NamedTuple):
    """Options shown for an overlay, in sections"""

    keys: tuple[str, ...]  # shown options, page order
    sections: tuple[Section, ...]
    section_of: Mapping[str, Section]
    dependencies: Mapping[str, str]  # option: on/off option it is used with
    option_ui: OptionUI | None


def option_id(name: str, key: str) -> str:
    return f"{name}/{key}"


def split_id(value: str) -> tuple[str, str]:
    name, _, key = value.partition("/")
    return name, key


def section_id(name: str, section: str) -> str:
    return f"{name}#{section}"


def section_title(section: Section) -> str:
    """Translated title: fixed & declared sections by tr, items by their option label"""
    if section.key.startswith(ITEM_PREFIX):
        return option_label(section.title)
    return tr(section.title)


def default_keys(name: str) -> list[str]:
    """Options of overlay in template order (options of loaded preset only)"""
    saved = cfg.user.setting.get(name, {})
    keys = [key for key in cfg.default.setting.get(name, {}) if key in saved]
    keys.extend(key for key in saved if key not in cfg.default.setting.get(name, {}))
    return keys


def build_layout(name: str, values: Mapping[str, Any]) -> OverlayLayout:
    """Shown options & sections of overlay, for design given by values (unsaved design switch)"""
    from ...widget._modern import design_option_keys, uses_modern_design

    keys = default_keys(name)
    design_config = SimpleNamespace(user=SimpleNamespace(config=cfg.user.config, setting={name: values}))
    try:
        keys = design_option_keys(design_config, name, keys)
    except Exception as error:  # broken modern module: every option shown
        logger.debug("Overlay options: design of %s: %s", name, error, exc_info=True)
    option_ui = WIDGET_OPTION_UI.get(name)
    if option_ui is not None and option_ui.modern_only and not uses_modern_design(design_config, name):
        option_ui = None  # classic layout: automatic sections
    if option_ui is not None and option_ui.hidden:
        keys = [key for key in keys if key not in option_ui.hidden]
    if option_ui is not None and option_ui.layout:
        sections = listed_sections(keys, option_ui.layout, option_ui.order_title, option_ui.order_toggles.values())
        dependencies: Mapping[str, str] = option_ui.dependencies
    elif option_ui is not None:
        sections = declared_sections(keys, option_ui.sections)
        dependencies = option_ui.dependencies
    else:
        sections = auto_sections(keys, values)
        dependencies = section_dependencies(sections)
    ordered = tuple(key for section in sections for key in section.keys)
    section_of = {key: section for section in sections for key in section.keys}
    return OverlayLayout(ordered, tuple(sections), section_of, dependencies, option_ui)


class OverlayOptionsBackend(PageBackend):
    """Overlay Options page state & actions

    Args:
        parent: page dialog.
        host: dialogs, notices & what to do once options are saved.
        control: overlay control (names, running state).
    """

    overlayChanged = Signal()
    infoChanged = Signal()  # overlayInfo: with overlayChanged, and once edits pause
    namesChanged = Signal()  # overlay list (choice list of narrow page): names or language changed
    stateChanged = Signal()  # pending edits, errors, undo & redo
    filterChanged = Signal()
    highlightChanged = Signal()
    previewChanged = Signal()

    def __init__(self, parent, host: OverlayOptionsHost, control: ModuleControl):
        super().__init__(parent, "Overlay options")
        self._host = host
        self._control = control
        self._preview_key = STORE.new_prefix("options") + "preview"
        weakref.finalize(self, STORE.release, self._preview_key)
        self.rows = DictListModel(ROW_ROLES, self)
        self.nav = DictListModel(NAV_ROLES, self)
        self._names: list[str] = [name for name in control.names if name in cfg.user.setting]
        self._overlay = self._names[0] if self._names else ""
        self._layouts: dict[str, OverlayLayout] = {}
        self._sorted_names: list[str] = []
        self._row_overrides: dict[str, Mapping[str, bool]] = {}  # overlay: profile overrides its rows were built with
        self._kinds: dict[str, OptionKind] = {}  # option key: kind (same for every overlay)
        self._search_texts: dict[str, str] = {}
        self._pending: dict[str, Any] = {}  # option id: valid value not saved yet
        self._invalid: dict[str, tuple[str, str]] = {}  # option id: (typed text, English reason)
        self._undo: list[tuple[dict, dict]] = []
        self._redo: list[tuple[dict, dict]] = []
        self._step_depth = 0
        self._step_before: tuple[dict, dict] | None = None
        self._preset = ""  # preset loaded when first edit was made, see apply
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._scope_all = False
        self._modified_only = False
        self._advanced = False
        self._collapsed: dict[str, set[str]] = {}
        self._nav_words: tuple[str, ...] = ()
        self._nav_filter = ""
        self._active_only = False
        self._match_count = 0
        self._truncated = 0
        self._highlight = ""
        self._shared: dict[str, int] = {}  # option key: overlays having it
        self._helped: set[str] = set()  # descriptions shown once in results of every overlay
        self._active = False
        self._preview_enabled = True
        self._preview_visible = True  # preview panel shown by page (not on narrow page, search of every overlay)
        self._preview_state = PREVIEW_OFF
        self._preview_url = ""
        self._preview_size = (0, 0)
        self._preview_scale = 1.0  # size of picture shown, relative to overlay size
        self._preview_zoom = 1.0  # size asked by page (zoomed preview), see setPreviewScale
        self._preview_signature: object = None  # inputs of picture shown (see render_preview)
        self._preview_bytes = 0  # size of picture in store
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self.render_preview)
        self._warm_queue: list[str] = []
        self._warm_timer = QTimer(self)
        self._warm_timer.setInterval(WARM_INTERVAL_MS)
        self._warm_timer.timeout.connect(self._warm_next)
        self._info_timer = QTimer(self)
        self._info_timer.setSingleShot(True)
        self._info_timer.setInterval(INFO_DELAY_MS)
        self._info_timer.timeout.connect(self.infoChanged)
        self.overlayChanged.connect(self.infoChanged)
        self._sort_names()
        self._count_shared()
        self.update_all()
        self._warm_queue = [name for name in self._names if name != self._overlay]

    # Values
    @staticmethod
    def saved(name: str, key: str) -> Any:
        return cfg.user.setting[name][key]

    @staticmethod
    def default(name: str, key: str) -> Any:
        return cfg.default.setting.get(name, {}).get(key)

    def value(self, name: str, key: str) -> Any:
        """Edited value (pending), else saved"""
        return self._pending.get(option_id(name, key), self.saved(name, key))

    def values(self, name: str) -> dict:
        """Overlay setting with pending edits (invalid ones keep saved value)"""
        values = dict(cfg.user.setting[name])
        prefix = f"{name}/"
        for oid, value in self._pending.items():
            if oid.startswith(prefix):
                values[oid[len(prefix):]] = value
        return values

    def kind(self, key: str) -> OptionKind:
        kind = self._kinds.get(key)
        if kind is None:
            kind = self._kinds[key] = option_kind(key)
        return kind

    def is_customized(self, name: str, key: str) -> bool:
        """Changed from default (pending value counted), see NOT_CUSTOMIZED"""
        if key in NOT_CUSTOMIZED:
            return False
        default = self.default(name, key)
        return default is not None and self.value(name, key) != default

    def is_changed(self, name: str, key: str) -> bool:
        oid = option_id(name, key)
        return oid in self._pending or oid in self._invalid

    # Layouts
    def layout(self, name: str) -> OverlayLayout:
        layout = self._layouts.get(name)
        if layout is None:
            layout = self._layouts[name] = build_layout(name, self.values(name))
        return layout

    def _design_changed(self, name: str):
        """Design switch edited: shown options follow"""
        self._layouts.pop(name, None)

    def _warm_next(self):
        """Options of one more overlay read (nav counts), one per tick: page opens at once"""
        while self._warm_queue:
            name = self._warm_queue.pop(0)
            if name in self._layouts or name not in cfg.user.setting:
                continue
            self.layout(name)
            self._update_nav_row(name)  # customized count of this overlay only
            return
        self._warm_timer.stop()

    def _count_shared(self):
        counts: dict[str, int] = {}
        for name in self._names:
            for key in cfg.user.setting[name]:
                counts[key] = counts.get(key, 0) + 1
        self._shared = counts

    # Search
    def search_text(self, name: str, key: str) -> str:
        oid = option_id(name, key)
        text = self._search_texts.get(oid)
        if text is None:
            section = self.layout(name).section_of.get(key)
            title = section_title(section) if section is not None else ""
            text = self._search_texts[oid] = sort_key(
                f"{option_label(key)} {key.replace('_', ' ')} {key} {title} {module_label(name)}")
        return text

    def matches(self, name: str, key: str) -> bool:
        if self._modified_only and not self.is_customized(name, key) and not self.is_changed(name, key):
            return False
        if self._words:
            text = self.search_text(name, key)
            return all(word in text for word in self._words)
        return True

    def shown_in_mode(self, layout: OverlayLayout, key: str) -> bool:
        """Simple mode (overlays with many options): on/off & choice options (main ones if listed, see
        OptionUI.simple_switches), and the common ones"""
        ui = layout.option_ui
        if ui is None or not ui.simple_mode or self._advanced or self.filtering:
            return True
        if key in ui.basic or key in GENERAL_KEYS:
            return True
        if self.kind(key).kind not in (KIND_BOOL, KIND_CHOICE):
            return False
        return ui.simple_switches is None or key in ui.simple_switches

    # Rows
    def update_all(self):
        self.update_rows()
        self.update_nav()

    def update_rows(self):
        """Rows of shown options, synced in place (editors keep focus & typed text)"""
        rows: list[dict] = []
        self._match_count = 0
        self._truncated = 0
        self._helped = set()
        self._row_overrides = {}
        if self.filtering and self._scope_all:
            for name in self._names:
                self._overlay_rows(name, rows, with_name=True)
        elif self._overlay:
            self._overlay_rows(self._overlay, rows, with_name=False)
        for number, row in enumerate(rows):
            row["last"] = number == len(rows) - 1 or rows[number + 1]["row"] == ROW_HEADER
        # Mostly other rows (overlay, search or filter changed): new list at once, else changed rows only
        # (editors keep focus & typed text, section folded without moving the list)
        self.rows.sync(rows, reset_if_mostly_new=True)

    def _overlay_rows(self, name: str, rows: list[dict], with_name: bool):
        layout = self.layout(name)
        values = self.values(name)
        overrides = self._overrides(layout, values)
        fixed = self._fixed(layout, values, overrides)
        self._row_overrides[name] = overrides
        collapsed = self._collapsed.get(name, set()) if not self.filtering else set()
        for section in layout.sections:
            shown = [key for key in section.keys
                     if key != section.toggle and self.shown_in_mode(layout, key) and self.matches(name, key)]
            toggle_match = bool(section.toggle) and self.matches(name, section.toggle)
            if section.key == SECTION_ORDER:
                if not shown:
                    continue
                if self._match_count >= MAX_ROWS:
                    self._truncated += len(shown)
                    continue
                self._match_count += len(shown)
                rows.append(self._header_row(name, section, overrides, fixed, len(order_keys(section)), False,
                                             with_name))
                rows.append(self._order_row(name, section))
                continue
            if not shown and not toggle_match:
                continue
            if self._match_count >= MAX_ROWS:
                self._truncated += len(shown) + toggle_match
                continue
            self._match_count += len(shown) + toggle_match
            is_collapsed = section.key in collapsed
            rows.append(self._header_row(name, section, overrides, fixed, len(shown), is_collapsed, with_name))
            if is_collapsed:
                continue
            for key in shown:
                row = self._option_row(name, key, layout, values, overrides, fixed)
                if with_name:
                    if row["help"] in self._helped:
                        row["help"] = ""
                    else:
                        self._helped.add(row["help"])
                rows.append(row)

    def _header_row(self, name: str, section: Section, overrides: Mapping[str, bool], fixed: Collection[str],
                    count: int, collapsed: bool, with_name: bool) -> dict:
        title = section_title(section)
        if with_name:
            title = f"{module_label(name)}  {chr(0x203A)}  {title}"
        toggle = section.toggle
        row = self._blank_row(section_id(name, section.key), name, ROW_HEADER)
        row.update(
            title=title,
            label=option_label(toggle) if toggle else "",
            first=True,
            toggle=option_id(name, toggle) if toggle else "",
            toggleChecked=bool(overrides.get(toggle, self.value(name, toggle))) if toggle else False,
            collapsed=collapsed,
            count=count,
            changedCount=sum(self.is_changed(name, key) for key in section.keys),
            customizedCount=sum(self.is_customized(name, key) for key in section.keys),
            changed=bool(toggle) and self.is_changed(name, toggle),
            error=self._error_text(option_id(name, toggle)) if toggle else "",
            modified=bool(toggle) and self.is_customized(name, toggle),
            locked=bool(toggle) and toggle in fixed,
        )
        return row

    def _order_row(self, name: str, section: Section) -> dict:
        row = self._blank_row(section_id(name, section.key) + "/list", name, ROW_ORDER)
        ui = self.layout(name).option_ui
        toggles = {key: toggle for key, toggle in (ui.order_toggles if ui is not None else {}).items()
                   if toggle in section.keys}
        labels = ui.order_labels if ui is not None else {}
        orders = []
        for key in self._ordered(name, section):
            toggle = toggles.get(key, "")
            orders.append({
                "key": key,
                "label": tr(labels[key]) if key in labels else option_label(key.removeprefix("display_order_")),
                "changed": self.is_changed(name, key) or (bool(toggle) and self.is_changed(name, toggle)),
                "toggle": option_id(name, toggle) if toggle else "",
                "checked": bool(self.value(name, toggle)) if toggle else True,
            })
        row.update(
            kind=ROW_ORDER,
            help=tr("Columns from left to right: switch them on or off, drag them or use the arrows.")
            if toggles else "",
            orders=orders,
            modified=any(self.is_customized(name, key) for key in order_keys(section)),
            changed=any(self.is_changed(name, key) for key in section.keys),
        )
        return row

    def _ordered(self, name: str, section: Section) -> list[str]:
        """Items of display order list as shown by overlay: design order while no display order was
        changed (modern design), else by display order value (same value: design or template order)"""
        keys = list(order_keys(section))
        ui = self.layout(name).option_ui
        if ui is not None and ui.design_order:
            rank = {key: index for index, key in enumerate(ui.design_order)}
            keys.sort(key=lambda key: rank.get(key, len(rank)))
            if all(self.value(name, key) == self.default(name, key) for key in keys):
                return keys
        return sorted(keys, key=lambda key: self._order_value(name, key))  # stable: same value keeps order

    def _order_value(self, name: str, key: str) -> float:
        value = self.value(name, key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    @staticmethod
    def _blank_row(key: str, name: str, row_type: str) -> dict:
        return {
            "key": key, "overlay": name, "option": "", "row": row_type, "label": "", "help": "", "kind": "",
            "title": "", "first": False, "last": False, "toggle": "", "toggleChecked": False, "collapsed": False,
            "count": 0, "changedCount": 0, "customizedCount": 0, "checked": False, "choices": [],
            "choiceIndex": -1, "text": "", "number": 0.0, "decimals": 0, "step": 1.0, "minimum": 0.0,
            "maximum": 0.0, "color": "", "modified": False, "changed": False, "error": "", "defaultText": "",
            "dimmed": False, "locked": False, "note": "", "hint": "", "shared": 0, "table": False, "orders": [],
        }

    def _error_text(self, oid: str) -> str:
        invalid = self._invalid.get(oid)
        return trm(tr(invalid[1])) if invalid else ""

    def list_items(self, name: str, key: str, value: Any = None) -> list[str]:
        """Names of list option in order: those of value (current value if None), then names offered not listed"""
        from ...module.module_relative import class_key

        if value is None:
            value = self.value(name, key)
        items: list[str] = []
        seen: set[str] = set()
        offered = LIST_OPTIONS[key][1]() if key in LIST_OPTIONS else []
        for item in [*str(value).split(","), *offered]:
            item = item.strip()
            if item and class_key(item) not in seen:
                seen.add(class_key(item))
                items.append(item)
        return items

    def _list_row(self, name: str, key: str) -> dict:
        """Order list row of a list option (see LIST_OPTIONS)"""
        oid = option_id(name, key)
        items = self.list_items(name, key)
        saved = self.list_items(name, key, self.saved(name, key))
        default = self.default(name, key)
        row = self._blank_row(oid, name, ROW_ORDER)
        row.update(
            option=key,
            kind=ROW_ORDER,
            label=option_label(key),
            help=tr(LIST_OPTIONS[key][0]),
            orders=[{
                "key": item, "label": item, "changed": index >= len(saved) or saved[index] != item,
                "toggle": "", "checked": True,
            } for index, item in enumerate(items)],
            modified=default is not None and items != self.list_items(name, key, default),
            changed=self.is_changed(name, key),
        )
        return row

    def _option_row(self, name: str, key: str, layout: OverlayLayout, values: Mapping[str, Any],
                    overrides: Mapping[str, bool], fixed: Collection[str]) -> dict:
        if key in LIST_OPTIONS:
            return self._list_row(name, key)
        oid = option_id(name, key)
        kind = self.kind(key)
        value = self.value(name, key)
        default = self.default(name, key)
        invalid = self._invalid.get(oid)
        row = self._blank_row(oid, name, ROW_OPTION)
        locked = key in fixed  # only set by profile: editable, profile switched to Custom (see _release)
        row.update(
            option=key,
            label=option_label(key),
            help=option_help_specific(name, key),
            kind=kind.kind,
            checked=bool(value) if kind.kind == KIND_BOOL else False,
            text=invalid[0] if invalid else "" if kind.kind == KIND_BOOL else display_value(kind, value),
            color=value if kind.kind == KIND_COLOR and not invalid and isinstance(value, str) else "",
            modified=default is not None and value != default,
            changed=oid in self._pending or oid in self._invalid,
            error=self._error_text(oid),
            defaultText=display_text(kind, default) if default is not None else "",
            locked=locked,
            shared=max(self._shared.get(key, 1) - 1, 0) if key not in NOT_CUSTOMIZED else 0,
            table=kind.kind == KIND_TEXT and "by_compound" in key,
        )
        if key in overrides:
            state = tr("on") if overrides[key] else tr("off")
            ui = layout.option_ui
            source = ui.override_source if ui is not None else ""
            row["note"] = f"{tr('Set by')} {option_label(source)}: {tr(str(values.get(source, '')))} ({state})"
            if not locked:
                row["note"] += f"  ·  {tr('Changing it switches to')} {tr('Custom')}"
            row["checked"] = bool(overrides[key]) if kind.kind == KIND_BOOL else row["checked"]
        else:
            control = self._off_control(layout, values, overrides, key)
            if control:
                row["dimmed"] = True
                row["note"] = f"{tr('Used only while on:')} {option_label(control)}"
        if kind.kind in (KIND_CHOICE, KIND_FONT):
            choices = list(choice_values(kind))
            if value not in choices:
                choices.insert(0, value)  # removed theme, uninstalled font: kept until changed
            row["choices"] = [choice_label(kind, choice) for choice in choices]
            row["choiceIndex"] = choices.index(value)
        elif kind.kind in NUMBER_KINDS and isinstance(value, (int, float)) and not isinstance(value, bool):
            places = decimals(value, default) if kind.kind != KIND_INTEGER else 0
            minimum, maximum = number_range(key)
            row.update(number=float(value), decimals=places, step=10 ** -places if places else 1.0,
                       minimum=float(minimum), maximum=float(maximum), hint=unit_hint_text(key, value))
        return row

    @staticmethod
    def _overrides(layout: OverlayLayout, values: Mapping[str, Any]) -> Mapping[str, bool]:
        ui = layout.option_ui
        if ui is None or ui.overrides is None:
            return {}
        try:
            return ui.overrides(values)
        except (KeyError, TypeError, ValueError):  # invalid value pending
            return {}

    @staticmethod
    def _fixed(layout: OverlayLayout, values: Mapping[str, Any], overrides: Mapping[str, bool]) -> Collection[str]:
        """Overridden options still overridden once override source released (auto compact mode): locked"""
        ui = layout.option_ui
        if not overrides or ui is None or ui.release is None or ui.overrides is None:
            return overrides.keys()
        try:
            release = ui.release(values)
            return ui.overrides({**values, **release}).keys() if release else overrides.keys()
        except (KeyError, TypeError, ValueError):  # invalid value pending
            return overrides.keys()

    @staticmethod
    def _off_control(layout: OverlayLayout, values: Mapping[str, Any], overrides: Mapping[str, bool],
                     key: str) -> str:
        """On/off option up the chain of option that is off, "" if every one is on"""
        control = layout.dependencies.get(key)
        seen = set()
        while control and control not in seen:
            seen.add(control)
            if not bool(overrides.get(control, values.get(control, True))):
                return control
            control = layout.dependencies.get(control)
        return ""

    def update_nav(self):
        """Overlay list: filtered by name & state, counts of unsaved edits & search matches"""
        self._info_timer.stop()
        self.infoChanged.emit()  # customized count of selected overlay
        changed: dict[str, int] = {}
        errors: dict[str, int] = {}
        for oid in self._pending.keys() | self._invalid.keys():
            name = split_id(oid)[0]
            changed[name] = changed.get(name, 0) + 1
        for oid in self._invalid:
            name = split_id(oid)[0]
            errors[name] = errors.get(name, 0) + 1
        rows = []
        for name in self._names:
            enabled = bool(cfg.user.setting[name]["enable"])
            if name != self._overlay and not self._nav_shown(name, enabled):
                continue
            category = widget_category(name)
            layout = self._layouts.get(name)
            matches = 0
            if self.filtering and self._scope_all:
                layout = self.layout(name)
                matches = sum(self.matches(name, key) for key in layout.keys)
            rows.append({
                "key": name,
                "label": module_label(name),
                "category": category,
                "categoryLabel": tr(category),
                "color": CATEGORY_COLORS[category],
                "enabled": enabled,
                "changed": changed.get(name, 0),
                "errors": errors.get(name, 0),
                "matches": matches,
                "customized": -1 if layout is None else sum(self.is_customized(name, key) for key in layout.keys),
            })
        order = {category: index for index, category in enumerate(CATEGORY_ORDER)}
        rows.sort(key=lambda row: (order.get(str(row["category"]), len(order)), sort_key(str(row["label"]))))
        self.nav.sync(rows)

    def _nav_shown(self, name: str, enabled: bool) -> bool:
        if self._active_only and not enabled:
            return False
        if self._nav_words:
            text = sort_key(f"{module_label(name)} {name.replace('_', ' ')} {tr(widget_category(name))}")
            return all(word in text for word in self._nav_words)
        return True

    def _update_nav_row(self, name: str):
        """Counts of one overlay in overlay list (unsaved edits, errors, customized options)"""
        number = self.nav.index_of(name)
        if number < 0:
            return
        prefix = f"{name}/"
        layout = self._layouts.get(name)
        self.nav.update_row(number, {
            "changed": sum(oid.startswith(prefix) for oid in self._pending.keys() | self._invalid.keys()),
            "errors": sum(oid.startswith(prefix) for oid in self._invalid),
            "customized": -1 if layout is None else sum(self.is_customized(name, key) for key in layout.keys),
        })

    def _update_edited(self, oid: str) -> bool:
        """Rows of one edited option updated alone (its row, its section header, its overlay in list),
        False if more rows follow it (on/off option others depend on, display profile, design switch,
        display order, "Modified" filter): every row updated then"""
        name, key = split_id(oid)
        if self._modified_only or key == "enable_classic_layout" or name not in self._names:
            return False
        layout = self.layout(name)
        section = layout.section_of.get(key)
        if section is None or section.key == SECTION_ORDER or key == section.toggle:
            return False
        if key in layout.dependencies.values():
            return False
        ui = layout.option_ui
        if ui is not None and (key == ui.override_source or key in ui.order_toggles.values()):
            return False
        values = self.values(name)
        overrides = self._overrides(layout, values)
        if overrides != self._row_overrides.get(name, overrides):
            return False
        number = self.rows.index_of(oid)
        if number >= 0:
            shown = self.rows.rows[number]
            row = self._option_row(name, key, layout, values, overrides, self._fixed(layout, values, overrides))
            row["help"] = shown["help"]  # shown once in results of every overlay
            row["last"] = shown["last"]
            self.rows.update_row(number, row)
        number = self.rows.index_of(section_id(name, section.key))
        if number >= 0:
            self.rows.update_row(number, {
                "changedCount": sum(self.is_changed(name, other) for other in section.keys),
                "customizedCount": sum(self.is_customized(name, other) for other in section.keys),
            })
        self._update_nav_row(name)
        self._info_timer.start()  # customized count of header, once edits pause
        return True

    def changed(self, edited: set[str] | None = None):
        """Pending edits changed: rows, counts, page marker & preview

        Args:
            edited: option ids whose pending value changed (one: its rows updated alone), None if unknown.
        """
        if edited is None or len(edited) > 1 or (edited and not self._update_edited(next(iter(edited)))):
            self.update_all()
        self.stateChanged.emit()
        self.schedule_preview()

    # Properties
    @Property(QObject, constant=True)
    def options(self) -> QObject:
        return self.rows

    @Property(QObject, constant=True)
    def overlays(self) -> QObject:
        return self.nav

    @Property(str, notify=overlayChanged)
    def overlay(self) -> str:
        return self._overlay

    @Property(dict, notify=infoChanged)
    def overlayInfo(self) -> dict:
        """Header of selected overlay: name, category, state, design, tools it has"""
        name = self._overlay
        if not name:
            return {"name": "", "label": "", "category": "", "color": "", "enabled": False, "design": "",
                    "optionCount": 0, "customized": 0, "simpleMode": False, "themes": [], "preset": "",
                    "profile": "", "profileOption": "", "userProfiles": [], "previewParts": False}
        from ...template.widget.modern import MODERN_DESIGNS
        from ...widget._modern import uses_modern_design

        layout = self.layout(name)
        category = widget_category(name)
        design = ""
        if name in MODERN_DESIGNS:
            design_config = SimpleNamespace(user=SimpleNamespace(config=cfg.user.config,
                                                                 setting={name: self.values(name)}))
            design = tr("Modern design") if uses_modern_design(design_config, name) else tr("Classic layout")
        ui = layout.option_ui
        # Option setting others (display profile) away from default: named in header, options it sets are
        # shown with its value
        profile = profile_option = ""
        if ui is not None and ui.override_source and ui.override_source in cfg.user.setting[name]:
            value = self.value(name, ui.override_source)
            if value != self.default(name, ui.override_source):
                profile = f"{option_label(ui.override_source)}: {tr(str(value))}"
                profile_option = option_id(name, ui.override_source)
        return {
            "name": name,
            "label": module_label(name),
            "category": tr(category),
            "color": CATEGORY_COLORS[category],
            "enabled": bool(cfg.user.setting[name]["enable"]),
            "design": design,
            "optionCount": len(layout.keys),
            "customized": sum(self.is_customized(name, key) for key in layout.keys),
            "simpleMode": ui is not None and ui.simple_mode,
            "themes": [{"name": theme, "label": tr(theme)} for theme in ui.color_themes] if ui is not None else [],
            "preset": cfg.filename.setting.removesuffix(".json"),
            "profile": profile,
            "profileOption": profile_option,
            "userProfiles": [{"name": profile_name, "label": tr(profile_name)}
                             for profile_name in (ui.user_profiles if ui is not None else {})],
            "previewParts": ui is not None and bool(ui.part_options),
        }

    @Property(int, notify=stateChanged)
    def pendingCount(self) -> int:
        return len(self._pending.keys() | self._invalid.keys())

    @Property(int, notify=stateChanged)
    def pendingOverlays(self) -> int:
        return len({split_id(oid)[0] for oid in self._pending.keys() | self._invalid.keys()})

    @Property(int, notify=stateChanged)
    def errorCount(self) -> int:
        return len(self._invalid)

    @Property(str, notify=stateChanged)
    def firstError(self) -> str:
        oid = self.first_error_id()
        if not oid:
            return ""
        name, key = split_id(oid)
        return f"{module_label(name)} {chr(0x203A)} {option_label(key)}: {trm(tr(self._invalid[oid][1]))}"

    def first_error_id(self) -> str:
        for name in self._names:
            for key in default_keys(name):
                if option_id(name, key) in self._invalid:
                    return option_id(name, key)
        return next(iter(self._invalid), "")

    @Property(bool, notify=stateChanged)
    def canUndo(self) -> bool:
        return bool(self._undo)

    @Property(bool, notify=stateChanged)
    def canRedo(self) -> bool:
        return bool(self._redo)

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(bool, notify=filterChanged)
    def searching(self) -> bool:
        return bool(self._words)

    @Property(bool, notify=filterChanged)
    def filtering(self) -> bool:
        """Search or "Modified" filter on (QML & Python attribute)"""
        return bool(self._words) or self._modified_only

    @Property(bool, notify=filterChanged)
    def scopeAll(self) -> bool:
        return self._scope_all

    @Property(bool, notify=filterChanged)
    def modifiedOnly(self) -> bool:
        return self._modified_only

    @Property(bool, notify=filterChanged)
    def advanced(self) -> bool:
        return self._advanced

    @Property(int, notify=stateChanged)
    def matchCount(self) -> int:
        return self._match_count

    @Property(int, notify=stateChanged)
    def truncatedCount(self) -> int:
        return self._truncated

    @Property(str, notify=filterChanged)
    def navFilter(self) -> str:
        return self._nav_filter

    @Property(bool, notify=filterChanged)
    def activeOnly(self) -> bool:
        return self._active_only

    @Property(str, notify=highlightChanged)
    def highlightKey(self) -> str:
        """Row to scroll to & flash (opened at an option)"""
        return self._highlight

    @Property(bool, notify=previewChanged)
    def previewEnabled(self) -> bool:
        return self._preview_enabled

    @Property(int, notify=previewChanged)
    def previewState(self) -> int:
        return self._preview_state

    @Property(str, notify=previewChanged)
    def previewUrl(self) -> str:
        return self._preview_url

    @Property(int, notify=previewChanged)
    def previewWidth(self) -> int:
        return self._preview_size[0]

    @Property(int, notify=previewChanged)
    def previewHeight(self) -> int:
        return self._preview_size[1]

    @Property(float, notify=previewChanged)
    def previewScale(self) -> float:
        """Size of picture (previewWidth & previewHeight) relative to overlay size"""
        return self._preview_scale

    # Navigation & filters
    @Slot(str)
    def showOption(self, oid: str):
        """Scroll to option & flash it (header profile pill)"""
        self.focus_option(*split_id(oid))

    @Slot(str)
    def selectOverlay(self, name: str):
        if name not in self._names:
            return
        if self.filtering and self._scope_all:  # leave search of every overlay for the overlay
            self._scope_all = False
            self.filterChanged.emit()
        if name != self._overlay:
            self._overlay = name
            self._preview_signature = None
            self._preview_url = ""
            self._preview_state = PREVIEW_LOADING if self._preview_enabled else PREVIEW_OFF
            self.previewChanged.emit()
        self.update_all()
        self.overlayChanged.emit()
        self.stateChanged.emit()
        self.schedule_preview(now=True)

    @Slot(int)
    def stepOverlay(self, offset: int):
        """Previous or next overlay of list (keyboard)"""
        names = [row["key"] for row in self.nav.rows]
        if not names:
            return
        index = names.index(self._overlay) if self._overlay in names else -1
        self.selectOverlay(names[max(0, min(len(names) - 1, index + offset))])

    @Slot(str)
    def setSearch(self, text: str):
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self.update_all()
            self.stateChanged.emit()
        self.filterChanged.emit()

    @Slot(bool)
    def setScopeAll(self, scope_all: bool):
        if scope_all != self._scope_all:
            self._scope_all = scope_all
            self.update_all()
            self.filterChanged.emit()
            self.stateChanged.emit()

    @Slot(bool)
    def setModifiedOnly(self, modified_only: bool):
        if modified_only != self._modified_only:
            self._modified_only = modified_only
            self.update_all()
            self.filterChanged.emit()
            self.stateChanged.emit()

    @Slot(bool)
    def setAdvanced(self, advanced: bool):
        if advanced != self._advanced:
            self._advanced = advanced
            self.update_rows()
            self.filterChanged.emit()
            self.stateChanged.emit()

    @Slot(str)
    def setNavFilter(self, text: str):
        self._nav_filter = text
        words = tuple(sort_key(text).split())
        if words != self._nav_words:
            self._nav_words = words
            self.update_nav()
        self.filterChanged.emit()

    @Slot(bool)
    def setActiveOnly(self, active_only: bool):
        if active_only != self._active_only:
            self._active_only = active_only
            self.update_nav()
            self.filterChanged.emit()

    @Slot(str)
    def toggleSection(self, sid: str):
        """Collapse or expand section (row key of its header)"""
        name, _, section = sid.partition("#")
        collapsed = self._collapsed.setdefault(name, set())
        if section in collapsed:
            collapsed.discard(section)
        else:
            collapsed.add(section)
        self.update_rows()

    @Slot(bool)
    def setAllCollapsed(self, collapse: bool):
        name = self._overlay
        if not name:
            return
        if collapse:
            self._collapsed[name] = {section.key for section in self.layout(name).sections}
        else:
            self._collapsed.pop(name, None)
        self.update_rows()

    def focus_option(self, name: str, key: str = ""):
        """Show overlay & flash option (opened from option search or an overlay)"""
        if name not in self._names:
            return
        if self.filtering:
            self._search, self._words, self._modified_only = "", (), False
            self.filterChanged.emit()
        self.selectOverlay(name)
        if not key or key not in cfg.user.setting[name]:
            return
        layout = self.layout(name)
        section = layout.section_of.get(key)
        if section is None:
            return
        if not self.shown_in_mode(layout, key) and not self._advanced:
            self._advanced = True
            self.filterChanged.emit()
        self._collapsed.get(name, set()).discard(section.key)
        self.update_rows()
        target = section_id(name, section.key) if key == section.toggle else option_id(name, key)
        if section.key == SECTION_ORDER:
            target = section_id(name, section.key) + "/list"
        self._highlight = ""
        self.highlightChanged.emit()  # same option again: flashed again
        self._highlight = target
        self.highlightChanged.emit()

    @Slot()
    def clearHighlight(self):
        self._highlight = ""

    @Slot(str, result=int)
    def navIndex(self, name: str) -> int:
        """Index of overlay in overlay list, -1 if filtered out"""
        return self.nav.index_of(name)

    @Slot(str, result=int)
    def rowIndex(self, key: str) -> int:
        """Index of row (option id or section header key), -1 if not shown"""
        return self.rows.index_of(key)

    def sorted_names(self) -> list[str]:
        """Every overlay, in list order: by category, then label"""
        return list(self._sorted_names)

    def _sort_names(self):
        order = {category: index for index, category in enumerate(CATEGORY_ORDER)}
        self._sorted_names = sorted(self._names, key=lambda name: (
            order.get(widget_category(name), len(order)), sort_key(module_label(name))))

    @Property(list, notify=namesChanged)
    def overlayKeys(self) -> list[str]:
        """Choice list of narrow page"""
        return list(self._sorted_names)

    @Property(list, notify=namesChanged)
    def overlayLabels(self) -> list[str]:
        return [module_label(name) for name in self._sorted_names]

    @Slot(str)
    def copyText(self, text: str):
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    # Edits
    def _snapshot(self) -> tuple[dict, dict]:
        return dict(self._pending), dict(self._invalid)

    @contextmanager
    def _step(self) -> Iterator[None]:
        """Edits made inside are one undo step, page updated once"""
        if self._step_depth == 0:
            self._step_before = self._snapshot()
        self._step_depth += 1
        try:
            yield
        finally:
            self._step_depth -= 1
            if self._step_depth == 0:
                before, self._step_before = self._step_before, None
                after = self._snapshot()
                if before is not None and after != before:
                    self._undo.append(before)
                    del self._undo[:-100]
                    self._redo.clear()
                    if not self._preset:
                        self._preset = cfg.filename.setting
                self.changed(edited_ids(before, after) if before is not None else None)

    def _set(self, oid: str, value: Any = None, text: str | None = None):
        """Set pending value (dropped if same as saved), invalid typed text marked"""
        name, key = split_id(oid)
        if name not in cfg.user.setting or key not in cfg.user.setting[name]:
            return
        kind = self.kind(key)
        reason = check_value(key, kind, value) if text is None else text_reason(key, kind, text)
        if text is not None and not reason:
            value = text_value(kind, text)
        if reason:
            self._invalid[oid] = (text if text is not None else str(value), reason)
            self._pending.pop(oid, None)
        else:
            self._invalid.pop(oid, None)
            if value == self.saved(name, key):
                self._pending.pop(oid, None)
            else:
                self._pending[oid] = value
        if key == "enable_classic_layout":
            self._design_changed(name)

    def _release(self, oid: str):
        """Option set by override source (display profile) edited: override source released first (its
        values kept, profile Custom), unless option stays overridden (auto compact mode)"""
        name, key = split_id(oid)
        if name not in self._names:
            return
        layout = self.layout(name)
        ui = layout.option_ui
        if ui is None or ui.release is None:
            return
        values = self.values(name)
        overrides = self._overrides(layout, values)
        if key not in overrides or key in self._fixed(layout, values, overrides):
            return
        for other, value in ui.release(values).items():
            if other != key and other in values:
                self._set(option_id(name, other), value)

    @Slot(str, bool)
    def setBool(self, oid: str, value: bool):
        with self._step():
            self._release(oid)
            self._set(oid, bool(value))

    @Slot(str, int)
    def setChoice(self, oid: str, index: int):
        name, key = split_id(oid)
        if name not in cfg.user.setting or key not in cfg.user.setting[name]:
            return
        choices = list(choice_values(self.kind(key)))
        current = self.value(name, key)
        if current not in choices:
            choices.insert(0, current)
        if 0 <= index < len(choices):
            with self._step():
                self._release(oid)
                self._set(oid, choices[index])

    @Slot(str, str)
    def setText(self, oid: str, text: str):
        with self._step():
            self._release(oid)
            self._set(oid, text=text)

    @Slot(str, float)
    def setNumber(self, oid: str, number: float):
        _, key = split_id(oid)
        value: int | float = number
        if self.kind(key).kind == KIND_INTEGER or float(number).is_integer():
            value = round(number)
        with self._step():
            self._release(oid)
            self._set(oid, value)

    @Slot(str)
    def resetOption(self, oid: str):
        """Option back to default (pending until applied)"""
        name, key = split_id(oid)
        default = self.default(name, key)
        if default is not None:
            with self._step():
                self._release(oid)
                self._set(oid, default)

    def _reset_keys(self, name: str, keys) -> int:
        """Options back to default ("enable" kept), count of options changed"""
        count = 0
        for key in keys:
            default = self.default(name, key)
            if key == "enable" or default is None:
                continue
            oid = option_id(name, key)
            if self.value(name, key) != default or oid in self._invalid:
                count += 1
            self._set(oid, default)
        return count

    @Slot(str)
    def resetSection(self, sid: str):
        """Options of a section back to default (row key of its header), after confirmation"""
        name, _, section_key = sid.partition("#")
        if name not in self._names:
            return
        section = next((section for section in self.layout(name).sections if section.key == section_key), None)
        if section is None:
            return
        text = (f"Reset <b>{section_title(section)}</b> options to default?<br><br>"
                "Changes are only saved after clicking Apply or Save Button.")
        if not self._host.confirm(trm(text)):
            return
        with self._step():
            self._reset_keys(name, section.keys)

    @Slot()
    def resetOverlay(self):
        """Every option of selected overlay back to default ("enable" kept), after confirmation"""
        name = self._overlay
        if not name:
            return
        text = (f"Reset all <b>{module_label(name)}</b> options to default?<br><br>"
                "Changes are only saved after clicking Apply or Save Button.")
        if not self._host.confirm(trm(text)):
            return
        with self._step():
            self._reset_keys(name, default_keys(name))

    def notify_host(self, text: str):
        self._host.notify(text)

    @Slot(str)
    def applyToAll(self, oid: str):
        """Value of option set to every other overlay having it (pending)"""
        name, key = split_id(oid)
        if name not in self._names or oid in self._invalid or key in NOT_CUSTOMIZED:
            return
        value = self.value(name, key)
        names = [other for other in self._names if other != name and key in cfg.user.setting[other]]
        with self._step():
            for other in names:
                self._set(option_id(other, key), value)
        self._host.notify(trm(
            f"{option_label(key)}: {display_text(self.kind(key), value)} set to {len(names)} overlay(s), "
            "saved with Apply"))

    @Slot()
    def exportOverlays(self):
        """Settings of overlays (shown values, selected overlay ticked) saved as package file"""
        self._host.export_overlays([self._overlay] if self._overlay else [])

    @Slot()
    def importOverlays(self):
        """Overlay settings package file picked, its values set as pending edits"""
        self._host.import_overlays()

    def import_values(self, overlays: Mapping[str, Mapping[str, Any]]) -> tuple[int, int]:
        """Imported overlay values set as pending edits (one undo step, saved with Apply), invalid values
        skipped (saved value kept), first overlay shown

        Returns:
            Number of options changed & of values skipped.
        """
        changed = skipped = 0
        names = [name for name in overlays if name in self._names]
        with self._step():
            for name in names:
                for key, value in overlays[name].items():
                    if key not in cfg.user.setting[name]:
                        skipped += 1
                        continue
                    kind = self.kind(key)
                    if check_value(key, kind, value) or (
                            kind.kind == KIND_CHOICE and value not in choice_values(kind)):
                        skipped += 1
                        continue
                    if kind.kind == KIND_INTEGER and isinstance(value, float):
                        value = round(value)
                    if value != self.value(name, key):
                        changed += 1
                    self._set(option_id(name, key), value)
        if names:
            self.selectOverlay(names[0])
        return changed, skipped

    @Slot(float, float)
    def previewClicked(self, x: float, y: float):
        """Preview clicked at (x, y), fractions of picture size: options of the part drawn there shown"""
        key = self.preview_part_option(x, y)
        if key:
            self.focus_option(self._overlay, key)

    def preview_part_option(self, x: float, y: float) -> str:
        """Option of the smallest part of the picture at (x, y) (fractions of picture size), "" if none"""
        from ..widget_preview import widget_part_rects

        name = self._overlay
        ui = self.layout(name).option_ui if name else None
        if ui is None or not ui.part_options or not (0 <= x <= 1 and 0 <= y <= 1):
            return ""
        try:
            found = widget_part_rects(cfg, name, self.values(name))
        except Exception as error:  # broken preview: click does nothing
            logger.debug("Overlay options: preview parts of %s: %s", name, error, exc_info=True)
            return ""
        if found is None:
            return ""
        size, rects = found
        point = QPoint(round(x * size.width()), round(y * size.height()))
        hits = [(rect.width() * rect.height(), part) for part, rect in rects.items()
                if part in ui.part_options and rect.contains(point)]
        if not hits:
            return ""
        key = ui.part_options[min(hits)[1]]
        return key if key in cfg.user.setting[name] else ""

    @Slot(str)
    def saveUserProfile(self, profile_name: str):
        """Shown on/off options (profile values included) saved as user profile, profile selected (pending)"""
        name = self._overlay
        ui = self.layout(name).option_ui if name else None
        if ui is None or ui.profile_text is None or profile_name not in ui.user_profiles:
            return
        values = self.values(name)
        shown = {**values, **self._overrides(self.layout(name), values)}
        with self._step():
            self._set(option_id(name, ui.user_profiles[profile_name]), ui.profile_text(shown))
            self._set(option_id(name, ui.override_source), profile_name)
        self._host.notify(trm(f"Display saved as {tr(profile_name)}, saved with Apply"))

    @Slot(str)
    def applyColorTheme(self, theme_name: str):
        """Every color of selected overlay set to theme colors (from each option default color)"""
        name = self._overlay
        ui = self.layout(name).option_ui if name else None
        if ui is None or theme_name not in ui.color_themes:
            return
        theme = ui.color_themes[theme_name]
        with self._step():
            for key in default_keys(name):
                default = self.default(name, key)
                if self.kind(key).kind == KIND_COLOR and isinstance(default, str):
                    self._set(option_id(name, key), theme_color(default, theme))

    @Slot(str, str, int)
    def moveOrder(self, name: str, key: str, offset: int):
        """Move item of display order list up (-1) or down (+1)"""
        section = self._order_section(name)
        if section is None or key not in order_keys(section):
            return
        keys = self._ordered(name, section)
        index = keys.index(key)
        target = max(0, min(len(keys) - 1, index + offset))
        if target == index:
            return
        keys.insert(target, keys.pop(index))
        self._set_orders(name, keys)

    @Slot(str, str, int)
    def placeOrder(self, name: str, key: str, position: int):
        """Item of display order list moved to position (dragged)"""
        section = self._order_section(name)
        if section is None or key not in order_keys(section):
            return
        keys = self._ordered(name, section)
        keys.remove(key)
        keys.insert(max(0, min(len(keys), position)), key)
        self._set_orders(name, keys)

    @Slot(str, str, str, int)
    def moveListItem(self, name: str, key: str, item: str, offset: int):
        """Move name of list option up (-1) or down (+1)"""
        items = self.list_items(name, key) if key in LIST_OPTIONS and name in self._names else []
        if item not in items:
            return
        index = items.index(item)
        target = max(0, min(len(items) - 1, index + offset))
        if target != index:
            items.insert(target, items.pop(index))
            with self._step():
                self._set(option_id(name, key), ", ".join(items))

    @Slot(str, str, str, int)
    def placeListItem(self, name: str, key: str, item: str, position: int):
        """Name of list option moved to position (dragged)"""
        items = self.list_items(name, key) if key in LIST_OPTIONS and name in self._names else []
        if item not in items:
            return
        items.remove(item)
        items.insert(max(0, min(len(items), position)), item)
        with self._step():
            self._set(option_id(name, key), ", ".join(items))

    @Slot(str, str)
    def resetList(self, name: str, key: str):
        """List option back to default order"""
        if key in LIST_OPTIONS and name in self._names:
            with self._step():
                self._reset_keys(name, (key,))

    @Slot(str)
    def resetOrder(self, name: str):
        section = self._order_section(name)
        if section is not None:
            with self._step():
                self._reset_keys(name, order_keys(section))

    def _order_section(self, name: str) -> Section | None:
        if name not in self._names:
            return None
        return next((section for section in self.layout(name).sections if section.key == SECTION_ORDER), None)

    def _set_orders(self, name: str, keys: list[str]):
        with self._step():
            for position, key in enumerate(keys, 1):
                self._set(option_id(name, key), position)

    @Slot()
    def undo(self):
        if self._undo:
            self._redo.append(self._snapshot())
            self._pending, self._invalid = self._undo.pop()
            self._layouts.clear()
            self.changed()

    @Slot()
    def redo(self):
        if self._redo:
            self._undo.append(self._snapshot())
            self._pending, self._invalid = self._redo.pop()
            self._layouts.clear()
            self.changed()

    @Slot()
    def discard(self):
        """Drop every pending edit"""
        if self._pending or self._invalid:
            with self._step():
                designs = {split_id(oid)[0] for oid in self._pending if oid.endswith("/enable_classic_layout")}
                self._pending.clear()
                self._invalid.clear()
                for name in designs:
                    self._design_changed(name)

    def is_modified(self) -> bool:
        return bool(self._pending or self._invalid)

    def preset_changed(self) -> bool:
        """Another preset was loaded since first unsaved edit"""
        return bool(self._preset) and self._preset != cfg.filename.setting

    @Slot(result=bool)
    def apply(self) -> bool:
        """Save pending edits into loaded preset & restart edited overlays, False if nothing saved

        Invalid values are shown instead. Edits made before another preset was loaded are saved
        into it only once confirmed.
        """
        for oid, value in list(self._pending.items()):
            if self.kind(split_id(oid)[1]).kind == KIND_PATH:
                path = parse_path(str(value))
                if path is None:
                    self._invalid[oid] = (str(self._pending.pop(oid)), "Folder cannot be used")
                else:
                    self._pending[oid] = path
        if self._invalid:
            self.changed()
            self.show_first_error()
            return False
        if not self._pending:
            return True
        if self.preset_changed():
            preset_name = cfg.filename.setting.removesuffix(".json")
            text = (f"Preset <b>{preset_name}</b> was loaded since this page was opened."
                    f"<br><br>Save changed options to <b>{preset_name}</b>?")
            if not self._host.confirm(trm(text)):
                return False
        names: list[str] = []
        for oid, value in self._pending.items():
            name, key = split_id(oid)
            if name in cfg.user.setting and key in cfg.user.setting[name]:
                cfg.user.setting[name][key] = value
                if name not in names:
                    names.append(name)
        self._pending.clear()
        self._undo.clear()
        self._redo.clear()
        self._preset = ""
        self._layouts.clear()
        cfg.save(0)
        self.changed()
        self._host.applied(names)
        return True

    @Slot()
    def showFirstError(self):
        """Show overlay & option of first invalid value"""
        oid = self.first_error_id()
        if oid:
            self.focus_option(*split_id(oid))

    def show_first_error(self):
        self.showFirstError()

    @Slot()
    def refresh(self):
        """Preset loaded or options saved elsewhere (overlay moved, toggled): saved values shown again"""
        names = [name for name in self._control.names if name in cfg.user.setting]
        if names != self._names:
            self._names = names
            if self._overlay not in names:
                self._overlay = names[0] if names else ""
        for oid in list(self._pending):
            name, key = split_id(oid)
            if name not in cfg.user.setting or key not in cfg.user.setting[name]:
                self._pending.pop(oid)
            elif self._pending[oid] == self.saved(name, key):
                self._pending.pop(oid)  # same value saved meanwhile
        self._invalid = {oid: value for oid, value in self._invalid.items()
                         if split_id(oid)[0] in cfg.user.setting}
        if not self._pending and not self._invalid:
            self._preset = ""
        self._layouts.clear()
        self._search_texts.clear()
        self._count_shared()
        self._sort_names()  # names or language changed
        self.namesChanged.emit()
        self.update_all()
        self.overlayChanged.emit()
        self.stateChanged.emit()
        self.schedule_preview(now=True)
        self._warm_queue = [name for name in self._names if name != self._overlay]
        if self._active:
            self._warm_timer.start()

    # Dialogs
    @Slot(str)
    def pickColor(self, oid: str):
        name, key = split_id(oid)
        if name not in self._names:
            return
        color = self._host.pick_color(str(self.value(name, key)))
        if color:
            with self._step():
                self._set(oid, color)

    @Slot(str)
    def browse(self, oid: str):
        """Choose folder (path option) or image file"""
        name, key = split_id(oid)
        if name not in self._names:
            return
        kind = self.kind(key).kind
        current = str(self.value(name, key))
        if kind == KIND_PATH:
            from ...userfile import set_relative_path

            folder = self._host.pick_folder(current)
            if folder:
                self.setText(oid, set_relative_path(folder))
        elif kind == KIND_IMAGE:
            filename = self._host.pick_image(current)
            if filename:
                self.setText(oid, filename)

    @Slot(str)
    def editTable(self, oid: str):
        """Tyre targets per compound edited as a table"""
        name, key = split_id(oid)
        if name not in self._names:
            return
        invalid = self._invalid.get(oid)
        text = self._host.edit_table(invalid[0] if invalid else str(self.value(name, key)))
        if text is not None:
            self.setText(oid, text)

    # Preview
    def set_active(self, active: bool):
        """Page shown or hidden: nothing rendered or read while hidden (racing)"""
        self._active = active
        if active:
            self.schedule_preview(now=True)
            if self._warm_queue:
                self._warm_timer.start()
        else:
            self._preview_timer.stop()
            self._warm_timer.stop()
            self.drop_big_preview()
        set_showing(self, active)

    def drop_big_preview(self):
        """Hidden: zoomed picture (MBs) released, drawn again once shown (same inputs: picture reused if still
        kept), small one kept shown"""
        if self._preview_bytes <= KEEP_HIDDEN_BYTES:
            return
        STORE.discard(self._preview_key)
        self._preview_bytes = 0
        self._preview_signature = None
        self._preview_url = ""
        self._preview_state = PREVIEW_LOADING if self._preview_enabled else PREVIEW_OFF
        self.previewChanged.emit()

    @Slot(bool)
    def setPreviewEnabled(self, enabled: bool):
        if enabled == self._preview_enabled:
            return
        self._preview_enabled = enabled
        self._preview_signature = None
        if not enabled:
            self._preview_timer.stop()
            self._preview_state = PREVIEW_OFF
            self._preview_url = ""
        self.previewChanged.emit()
        self.schedule_preview(now=True)

    @Slot(float)
    def setPreviewScale(self, zoom: float):
        """Preview shown zoomed: overlay drawn at that size (sharp text & lines, as global overlay
        scale does), rounded up to a step, up to PREVIEW_SCALE_MAX"""
        drawn = self._preview_zoom
        # Picture scaled a little by page: kept (fit zoom moves with size of picture drawn)
        if drawn - 2 * PREVIEW_SCALE_STEP <= zoom <= drawn + 0.05 or preview_zoom(zoom) == drawn:
            return
        self._preview_zoom = preview_zoom(zoom)  # drawn again at new size
        self.schedule_preview(now=True)

    @Slot(bool)
    def setPreviewVisible(self, visible: bool):
        """Preview panel shown or hidden by page: nothing drawn while hidden, drawn once when shown again"""
        if visible == self._preview_visible:
            return
        self._preview_visible = visible
        if visible:
            self.schedule_preview(now=True)
        else:
            self._preview_timer.stop()

    def schedule_preview(self, now: bool = False):
        if not self._preview_enabled or not self._preview_visible or not self._active or not self._overlay:
            return
        if now:
            self._preview_timer.start(0)
        else:
            self._preview_timer.start(PREVIEW_DELAY_MS)

    def render_preview(self):
        """Selected overlay drawn with unsaved values (kept as is while a value is invalid)"""
        name = self._overlay
        if not name or not self._preview_enabled:
            return
        if any(oid.startswith(f"{name}/") for oid in self._invalid):
            if self._preview_state != PREVIEW_INVALID:
                self._preview_state = PREVIEW_INVALID
                self.previewChanged.emit()
            return
        values = self.values(name)
        zoom = self._preview_zoom
        # Same values, overlay style, zoom & shared inputs (page shown again, edit undone): picture kept
        signature = preview_signature(name, values, zoom)
        if signature == self._preview_signature and self._preview_state in (PREVIEW_READY, PREVIEW_UNAVAILABLE):
            return
        self._preview_signature = signature
        image = render_overlay(name, values, zoom)
        if image is None:
            self._preview_state = PREVIEW_UNAVAILABLE
            self._preview_url = ""
            self._preview_size = (0, 0)
            self._preview_bytes = 0
            STORE.discard(self._preview_key)
        else:
            ratio = image.devicePixelRatio() or 1
            self._preview_state = PREVIEW_READY
            self._preview_url = STORE.put(self._preview_key, image)
            self._preview_bytes = image.sizeInBytes()
            self._preview_size = (round(image.width() / ratio), round(image.height() / ratio))
            self._preview_scale = drawn_scale(cfg.user.config["overlay_style"].get("overlay_scale", 1.0), zoom)
        self.previewChanged.emit()

    def close(self):
        """Page closed (older name of release)"""
        self.release()

    def release_resources(self):
        self._preview_timer.stop()
        self._warm_timer.stop()
        self._info_timer.stop()
        STORE.discard(self._preview_key)
        set_showing(self, False)


def edited_ids(before: tuple[dict, dict], after: tuple[dict, dict]) -> set[str]:
    """Option ids whose pending value or invalid text changed between two snapshots"""
    edited: set[str] = set()
    for old, new in zip(before, after):
        edited.update(oid for oid in old.keys() | new.keys() if old.get(oid, _MISSING) != new.get(oid, _MISSING))
    return edited


def preview_zoom(zoom: float) -> float:
    """Size an overlay preview is drawn at for a zoom: rounded up to a step, 1 to PREVIEW_SCALE_MAX"""
    if not zoom > 1:  # also nan
        return 1.0
    steps = -(-zoom // PREVIEW_SCALE_STEP)  # ceil
    return min(steps * PREVIEW_SCALE_STEP, PREVIEW_SCALE_MAX)


def drawn_scale(overlay_scale: float, zoom: float) -> float:
    """Size of an overlay drawn zoomed, relative to its size: global overlay scale times zoom is
    limited to the range of overlay scale"""
    low, high = OVERLAY_SCALE_RANGE
    base = min(max(overlay_scale, low), high)
    return min(max(overlay_scale * zoom, low), high) / base


def render_overlay(name: str, values: dict, zoom: float = 1.0):
    """Overlay picture with values (QImage) drawn at zoom, None if it cannot be drawn; same inputs as a picture
    drawn before (any page): that picture"""
    from ..widget_preview import render_image

    try:
        return render_image(cfg, name, values, zoom)
    except Exception as error:  # never break the page
        logger.debug("Overlay options preview error: %s: %s", name, error, exc_info=True)
        return None


def preview_signature(name: str, values: dict, zoom: float) -> object:
    """Inputs of overlay picture (see widget_preview.preview_key)"""
    from ..widget_preview import preview_key

    try:
        return preview_key(cfg, name, values, zoom)
    except Exception:  # never break the page: drawn again
        logger.debug("Overlay options preview inputs error: %s", name, exc_info=True)
        return object()


def text_reason(key: str, kind: OptionKind, text: str) -> str:
    """Why typed text is invalid (English), "" if valid"""
    if kind.kind in NUMBER_KINDS:
        value = parse_number(kind, text)
        return "Number required" if value is None else check_value(key, kind, value)
    return check_value(key, kind, text)


def text_value(kind: OptionKind, text: str) -> Any:
    """Value of valid typed text"""
    if kind.kind in NUMBER_KINDS:
        return parse_number(kind, text)
    if kind.kind == KIND_COLOR:
        return text.strip().upper()
    return text


def unit_hint_text(key: str, value: Any) -> str:
    """Value in user's display unit ("= 32.5 psi"), "" if option carries no unit or is shown in it"""
    from .._option import unit_hint

    try:
        hint = unit_hint(key, number_text(value), cfg.units)
    except (AttributeError, KeyError, TypeError, ValueError):
        return ""
    return f"= {hint}" if hint else ""

