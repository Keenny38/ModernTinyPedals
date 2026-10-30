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
Share overlay settings as file: export settings of overlays you pick, import them into loaded preset

Package format: see userfile.overlay_package. Imported values are pending edits of the Overlay Options
page (undo, saved with Apply), like any edit made there.
"""

from __future__ import annotations

import html
import logging
import os
import zipfile
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..const_app import APP_NAME, VERSION
from ..i18n import tr, trm
from ..i18n.options import module_label
from ..module_control import wctrl
from ..setting import cfg
from ..userfile.overlay_package import (
    POSITION_KEYS,
    changed_options,
    export_overlay_package,
    overlay_values,
    package_filename,
    package_format,
    read_overlay_package,
)
from ..userfile.preset_package import PACKAGE_FORMATS as PRESET_PACKAGE_FORMATS
from ..version import SETTING_VERSION
from ._common import UIScaler, translate_filter
from .module_view import sort_key
from .toast import show_toast

logger = logging.getLogger(__name__)

FILE_FILTER = "NeoPedal overlay settings (*.zip)"


class OverlayPickDialog(QDialog):
    """Overlays to export or import, ticked in a list, with quick selections & optional "keep positions"

    Args:
        items: (overlay name, shown text) in shown order.
        checked: overlays ticked when opened.
        selections: (button text, overlays ticked by button).
        keep_positions: "Keep my positions" box shown with this state, not shown if None.
        ok_text: text of OK button.
    """

    def __init__(
        self, parent, title: str, text: str, items: list[tuple[str, str]], checked: Collection[str],
        selections: Collection[tuple[str, Collection[str]]] = (), keep_positions: bool | None = None,
        ok_text: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        self.list = QListWidget(self)
        for name, item_text in items:
            item = QListWidgetItem(item_text, self.list)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked)
        self.list.itemChanged.connect(self.update_ok)
        layout_select = QHBoxLayout()
        for button_text, names in selections:
            button = QPushButton(button_text, self)
            button.clicked.connect(lambda _=False, names=frozenset(names): self.check_only(names))
            layout_select.addWidget(button)
        layout_select.addStretch(1)
        self.keep_box: QCheckBox | None = None
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        if ok_text:
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        if selections:
            layout.addLayout(layout_select)
        layout.addWidget(self.list, stretch=1)
        if keep_positions is not None:
            self.keep_box = QCheckBox(tr("Keep my positions"), self)
            self.keep_box.setToolTip(tr("Overlays stay where you placed them, else they move to the positions of the file"))
            self.keep_box.setChecked(keep_positions)
            layout.addWidget(self.keep_box)
        layout.addWidget(self.buttons)
        self.setMinimumSize(UIScaler.size(26), UIScaler.size(24))
        self.update_ok()

    def check_only(self, names: Collection[str]):
        """Overlays of names ticked, others unticked"""
        for row in range(self.list.count()):
            item = self.list.item(row)
            checked = item.data(Qt.ItemDataRole.UserRole) in names
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def checked_names(self) -> list[str]:
        """Ticked overlays, in shown order"""
        items = (self.list.item(row) for row in range(self.list.count()))
        return [item.data(Qt.ItemDataRole.UserRole) for item in items
                if item.checkState() == Qt.CheckState.Checked]

    def keep_positions(self) -> bool:
        return self.keep_box is None or self.keep_box.isChecked()

    def update_ok(self, *_):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.checked_names()))


def available_names() -> list[str]:
    """Overlays of this version in loaded preset, sorted by shown name"""
    names = [name for name in wctrl.names if name in cfg.user.setting and name in cfg.default.setting]
    return sorted(names, key=lambda name: sort_key(module_label(name)))


def screen_rect() -> tuple[int, int, int, int]:
    """Primary screen geometry (positions are shared relative to it)"""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 0, 0, 1920, 1080
    rect = screen.geometry()
    return rect.x(), rect.y(), max(1, rect.width()), max(1, rect.height())


def pick_dialog(*args, **kwargs) -> OverlayPickDialog:
    """Overlay checklist (tests replace it)"""
    return OverlayPickDialog(*args, **kwargs)


def save_filename(parent, default_name: str) -> str:
    """Package file chosen in file dialog ("" if cancelled), ".zip" added if missing"""
    zip_filename, _ = QFileDialog.getSaveFileName(
        parent, tr("Export Overlay Settings"),
        dir=os.path.join(os.path.expanduser("~"), default_name),
        filter=translate_filter(FILE_FILTER),
    )
    if zip_filename and not zip_filename.lower().endswith(".zip"):
        zip_filename += ".zip"
    return zip_filename


def open_filename(parent) -> str:
    """Package file chosen in file dialog, "" if cancelled"""
    return QFileDialog.getOpenFileName(
        parent, tr("Import Overlay Settings"), dir=os.path.expanduser("~"), filter=translate_filter(FILE_FILTER),
    )[0]


# Export


def export_overlay_settings(
    parent, checked: Collection[str] = (), values: Callable[[str], Mapping[str, Any]] | None = None,
) -> int:
    """Pick overlays (checked ones ticked, else enabled ones), then save their settings as package file

    Args:
        checked: overlays ticked when dialog opens.
        values: options of overlay as shown (Overlay Options page: pending edits), saved ones if None.

    Returns:
        Number of overlays exported.
    """
    names = available_names()
    if not names:
        return 0
    read = values or (lambda name: cfg.user.setting[name])
    changed = {name: len(changed_options(read(name), cfg.default.setting[name])) for name in names}
    active = {name for name in names if cfg.user.setting[name].get("enable")}
    items = [
        (name, module_label(name) + (f"  ·  {trm(f'{changed[name]} option(s) changed')}" if changed[name] else ""))
        for name in names
    ]
    dialog = pick_dialog(
        parent, tr("Export Overlay Settings"),
        tr("Overlays to share: options changed from default and position are saved in the file."),
        items, set(checked) & set(names) or active,
        selections=[
            (tr("All"), names), (tr("None"), ()), (tr("Active"), active),
            (tr("With changes"), [name for name in names if changed[name]]),
        ],
        ok_text=tr("Export…"),
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0
    picked = dialog.checked_names()
    if not picked:
        return 0
    zip_filename = save_filename(parent, package_filename([module_label(name) for name in picked]))
    if not zip_filename:
        return 0
    try:
        count = export_overlay_package(
            zip_filename, {name: read(name) for name in picked}, cfg.default.setting,
            VERSION, SETTING_VERSION, screen_rect())
    except OSError as error:
        alert(parent, tr("Error"), trm(f"Unable to export overlay settings:<br>{html.escape(str(error))}"))
        return 0
    show_toast(parent, trm(f"Exported <b>{count}</b> overlay(s) to:<br>{html.escape(zip_filename)}"))
    return count


def alert(parent, title: str, text: str):
    """Error in the page showing it (dialog bridge), else a message box"""
    from .quick import dialogs

    dialogs.alert(parent, title, text, "warning")  # as the former message box (QMessageBox.warning)


# Import


def import_overlay_settings(parent, page=None) -> bool:
    """Pick package file, then import it (see import_overlay_file)"""
    if refuse_locked(parent):
        return False
    zip_filename = open_filename(parent)
    return bool(zip_filename) and import_overlay_file(parent, zip_filename, page)


def refuse_locked(parent) -> bool:
    """Loaded preset is locked: told, True"""
    if cfg.filename.setting not in cfg.user.filelock:
        return False
    alert(parent, tr("Error"), trm("Changes to locked preset will not be saved."))
    return True


def import_overlay_file(parent, zip_filename: str, page=None) -> bool:
    """Show what the package holds, let overlays be unticked & positions kept, then set its values as
    pending edits of Overlay Options page (page if set, else opened), saved with Apply

    Returns:
        True if values were set.
    """
    if refuse_locked(parent):
        return False
    if package_format(zip_filename) in PRESET_PACKAGE_FORMATS:
        alert(parent, tr("Error"), tr("This is a preset package: import it on the Presets page."))
        return False
    names = available_names()
    try:
        package = read_overlay_package(zip_filename, {name: cfg.default.setting[name] for name in names})
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        alert(parent, tr("Error"), trm(
            f"Unable to import overlay settings:<br>{html.escape(tr(str(error)))}"))
        return False
    if not package.overlays:
        alert(parent, tr("Error"), tr("No overlay of this file is available in this version."))
        return False
    lines = [html.escape(os.path.basename(zip_filename))]
    if package.app_version:
        lines.append(trm(f"Made with {APP_NAME} {html.escape(package.app_version)}"))
    preset_name = html.escape(cfg.filename.setting.removesuffix(".json"))
    lines.append(trm(f"Values are set in Overlay Options of preset <b>{preset_name}</b>, saved with Apply"))
    if package.unknown:
        lines.append(trm(f"Not available in this version: {html.escape(', '.join(package.unknown))}"))
    if package.skipped:
        lines.append(trm(f"{package.skipped} option(s) left out:") + report_html(package.left_out))
    shown = [name for name in names if name in package.overlays]
    items = []
    for name in shown:
        count = sum(key not in POSITION_KEYS for key in package.overlays[name])
        items.append((name, f"{module_label(name)}  ·  {trm(f'{count} option(s)')}"))
    dialog = pick_dialog(
        parent, tr("Import Overlay Settings"), "<br>".join(lines), items, shown,
        selections=[(tr("All"), shown), (tr("None"), ())], keep_positions=True, ok_text=tr("Import"),
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    picked = dialog.checked_names()
    if not picked:
        return False
    target = screen_rect()
    values = {
        name: overlay_values(
            package.overlays[name], cfg.user.setting[name], cfg.default.setting[name],
            dialog.keep_positions(), package.screen, target)
        for name in picked
    }
    if page is None:
        from .overlay_options import open_overlay_options

        page = open_overlay_options(parent, picked[0])
        if page is None:
            return False
    changed, report = page.backend.import_values(values)
    text = trm(f"{len(picked)} overlay(s) imported: {changed} option(s) changed, saved with Apply")
    if report:
        text += "<br>" + trm(f"{len(report)} value(s) skipped or corrected:") + report_html(report)
        logger.info("IMPORT OVERLAYS: %s", "; ".join(report))
    page.backend.notify_host(text)
    return True


REPORT_LINES = 10  # lines of an import report shown, the others counted


def report_line(line: str) -> str:
    """Report line with why a value is invalid translated (English line kept in log)"""
    head, marker, reason = line.partition("skipped: ")
    return f"{head}{marker}{tr(reason[:-1])})" if marker and reason.endswith(")") else line


def report_html(lines: Sequence[str]) -> str:
    """Options left out or corrected by an import, one per line (translated reasons), the first ones only"""
    shown = "".join(f"<br>• {html.escape(trm(report_line(line)))}" for line in lines[:REPORT_LINES])
    more = len(lines) - REPORT_LINES
    return shown + (f"<br>{trm(f'… and {more} more')}" if more > 0 else "")
