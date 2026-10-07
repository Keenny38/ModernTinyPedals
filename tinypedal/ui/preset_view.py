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
Presets page: loaded preset & auto load, presets with tags & content, actions & details

Qt Quick page (qml/Presets.qml), state & actions in quick/preset_backend.py. This page hosts the
QML view and runs actions needing dialogs: preset packages, share codes, delete with undo, and the
Transfer, Restore Backup, Trash & Compare pages. The QML page is created when first shown.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from contextlib import nullcontext

import shiboken6
from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QVBoxLayout, QWidget

from .. import app_signal
from ..const_file import ConfigType, FileExt
from ..i18n import tr, trm
from ..i18n.options import module_label
from ..module_control import mctrl, wctrl
from ..setting import cfg
from ..userfile.preset_package import export_preset_package, import_preset_package
from ..userfile.preset_share import SHARE_PREFIX, decode_preset, encode_preset, save_preset_data, summarize_preset
from ..userfile.preset_trash import TrashEntry, purge_trash
from ..validator import is_allowed_filename, load_json_strict
from ._common import TextInputDialog, translate_filter
from .file_drop import unique_preset_name
from .preset_compare import PresetCompare
from .preset_management import (
    PresetTransfer,
    PresetTrash,
    RestoreBackup,
    restore_trashed_preset,
    trash_keep_days,
    trash_preset,
    update_preset_references,
)
from .quick.preset_backend import PresetBackend
from .toast import show_toast


class PresetList(QWidget):
    """Presets page"""

    def __init__(self, parent):
        super().__init__(parent)
        self.backend = PresetBackend(self, self)
        self.view: QQuickWidget | None = None  # see ensure_view
        self._creating = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Undo last delete (Ctrl+Z on this page, or undo button of toast)
        self.last_trashed: TrashEntry | None = None
        self.shortcut_undo = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.undo_delete)
        self.shortcut_undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut_undo.setEnabled(False)
        # Presets deleted long ago removed from trash, once app is running
        QTimer.singleShot(3000, self, lambda: purge_trash(cfg.path.settings, trash_keep_days()))

    def ensure_view(self) -> QQuickWidget | None:
        """QML page, created on first use"""
        if self.view is None and not self._creating:
            from .quick import create_quick_view

            self._creating = True  # page shown again while QML loads: one page only
            try:
                view = create_quick_view(self, "Presets.qml", {"backend": self.backend}, samples=0)
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
        self.backend.set_active(True)
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.set_active(False)  # preset files read again only once shown
        super().hideEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        if self.view is not None:  # QML gone before the backend it binds to
            view, self.view = self.view, None
            view.setSource(QUrl())
            view.deleteLater()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Presets, loaded preset or tags changed (read when page is shown)"""
        self.backend.refresh()

    # Messages
    def confirm_operation(self, title: str = "Confirm", message: str = "") -> bool:
        """Confirm operation"""
        confirm = QMessageBox.question(
            self, tr(title), trm(message),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        )
        return confirm == QMessageBox.StandardButton.Yes

    def warn(self, text: str):
        QMessageBox.warning(self, tr("Error"), text)

    def toast(self, text: str):
        show_toast(self, text)

    # Pages
    def open_page(self, name: str, preset_filename: str = ""):
        """Transfer, Restore Backup, Trash, or Compare (preset with loaded preset) page"""
        if name == "compare":
            PresetCompare(self, preset_a=cfg.filename.setting, preset_b=preset_filename).show()
        elif name == "transfer":
            PresetTransfer(self).open()
        elif name == "restore":
            RestoreBackup(self).open()
        elif name == "trash":
            PresetTrash(self).open()
        elif name == "folder":
            folder = os.path.abspath(cfg.path.settings)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
                QMessageBox.warning(self, tr("Error"), trm(f"Cannot open folder:<br><b>{folder}</b>"))

    # Load & auto load
    def load_preset(self, name: str):
        """Load preset by name (without extension)"""
        self.backend.load(f"{name}{FileExt.JSON}")

    @staticmethod
    def toggle_autoload(checked: bool):
        """Toggle auto load preset"""
        cfg.application["enable_auto_load_preset"] = checked
        cfg.save(config_type=ConfigType.CONFIG)

    # Packages & share codes
    def export_package(self, preset_filename: str):
        """Export preset, style presets and notes to single zip file"""
        include_notes = QMessageBox.question(
            self, tr("Export Package"),
            tr("Include track notes & pace notes in package?"),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
        zip_filename, _ = QFileDialog.getSaveFileName(
            self,
            dir=os.path.join(os.path.expanduser("~"), f"{preset_filename[:-5]}.zip"),
            filter=translate_filter("Modern Tiny Pedals preset package (*.zip)"),
        )
        if not zip_filename:
            return
        notes_paths = {"tracknotes": cfg.path.track_notes, "pacenotes": cfg.path.pace_notes} if include_notes else None
        try:
            count = export_preset_package(zip_filename, cfg.path.settings, preset_filename, notes_paths=notes_paths)
        except OSError as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to export package:<br>{error}"))
            return
        show_toast(self, trm(f"Exported <b>{count}</b> file(s) to:<br>{zip_filename}"))

    def import_package(self):
        """Import preset package"""
        zip_filename, _ = QFileDialog.getOpenFileName(
            self, dir=os.path.expanduser("~"), filter=translate_filter("Modern Tiny Pedals preset package (*.zip)"),
        )
        if zip_filename:
            self.import_package_file(zip_filename)

    def import_package_file(self, zip_filename: str):
        """Import preset package file"""
        overwrite_styles = QMessageBox.question(
            self, tr("Import Package"),
            tr("Also import style presets (brakes, brands, classes, compounds, heatmap, tracks)?<br><br>"
            "This will <b>overwrite</b> your existing style presets."),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
        # Styles: saving paused across import (no save written over imported styles), then reloaded
        # in memory (also styles imported before an error), so later style saves keep imported ones
        try:
            with cfg.styles_replaced() if overwrite_styles else nullcontext():
                result = import_preset_package(
                    zip_filename,
                    cfg.path.settings,
                    overwrite_styles=overwrite_styles,
                    notes_paths={"tracknotes": cfg.path.track_notes, "pacenotes": cfg.path.pace_notes},
                )
        except (ValueError, OSError, zipfile.BadZipFile) as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to import package:<br>{error}"))
            return
        self.refresh()
        lines = [f"Presets: <b>{', '.join(name[:-5] for name in result.presets) or tr('none')}</b>"]
        if result.styles:
            lines.append(f"Style presets: {', '.join(result.styles)} (reload preset to apply)")
        if result.notes:
            lines.append(f"Notes: {result.notes} file(s)")
        if result.skipped:
            lines.append(f"Skipped: {len(result.skipped)} file(s) (existing or not allowed)")
        QMessageBox.information(self, tr("Import Package"), trm("<br>".join(lines)))

    def copy_share_code(self, preset_filename: str):
        """Copy preset as share code to clipboard"""
        try:
            with open(f"{cfg.path.settings}{preset_filename}", encoding="utf-8") as file:
                code = encode_preset(json.load(file))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to read preset:<br>{error}"))
            return
        QApplication.clipboard().setText(code)
        show_toast(self, trm(f"Share code of <b>{preset_filename[:-5]}</b> copied ({len(code)} characters)"))

    def import_share_code(self):
        """Import preset from share code, with preview: code, then new preset name"""
        clipboard = QApplication.clipboard().text().strip()
        TextInputDialog(
            self, tr("Import Share Code"), tr("Paste preset share code:"), self.share_code_entered,
            text=clipboard if clipboard.startswith(SHARE_PREFIX) else "", multiline=True,
        ).open()

    def share_code_entered(self, code: str) -> bool:
        """Share code entered: ask new preset name with preview, False keeps code input open"""
        if not code.strip():
            return False
        try:
            preset = decode_preset(code)
            load_json_strict(json.dumps(preset))  # NaN & Infinity are not valid option values
        except (ValueError, RecursionError) as error:  # RecursionError: data nested too deep
            QMessageBox.warning(self, tr("Error"), trm(f"Invalid share code:<br>{error}"))
            return False
        summary = summarize_preset(preset, wctrl.names, mctrl.names)
        widgets = ", ".join(module_label(name) for name in summary.widgets) or tr("None")
        modules = ", ".join(module_label(name) for name in summary.modules) or tr("None")
        TextInputDialog(
            self, tr("Import Share Code"),
            trm(f"<b>{len(summary.widgets)}</b> widgets: {widgets}<br><br>"
                f"<b>{len(summary.modules)}</b> modules: {modules}<br><br>New preset name:"),
            lambda name: self.save_shared_preset(preset, name), text=tr("Shared preset"),
        ).open()
        return True

    def save_shared_preset(self, preset: dict, name: str) -> bool:
        """Save imported preset, False keeps name input open (invalid name)"""
        name = re.sub(r'[\\/:*?"<>|]', "", name).strip()  # characters not allowed in file name
        if not name or not is_allowed_filename(name):
            QMessageBox.warning(self, tr("Error"), tr("Invalid preset name."))
            return False
        filename = unique_preset_name(cfg.path.settings, f"{name}{FileExt.JSON}")
        if not save_preset_data(cfg.path.settings, filename, preset):
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to save preset {filename}"))
            return False
        self.refresh()
        show_toast(self, trm(f"Preset imported: <b>{filename[:-5]}</b>"))
        return True

    # Delete & undo
    def delete_preset(self, preset_filename: str) -> bool:
        """Move preset file & layout profiles to trash, clear primary preset references (shortcuts,
        tracks, classes), undo shown for a few seconds (also Ctrl+Z, or from trash later)"""
        if not os.path.exists(f"{cfg.path.settings}{preset_filename}"):  # already gone
            update_preset_references(preset_filename[:-len(FileExt.JSON)], "")
            return True
        try:
            entry = trash_preset(preset_filename)
        except OSError as error:  # locked file (cloud sync, antivirus), permission
            QMessageBox.warning(self, tr("Delete Preset"), trm(f"Unable to delete preset:<br>{error}"))
            return False
        self.last_trashed = entry
        self.shortcut_undo.setEnabled(True)
        self.backend.deleted(True)
        show_toast(
            self, trm(f"Preset <b>{entry.name}</b> moved to trash"),
            action_text=tr("Undo (Ctrl+Z)"), action=lambda: self.undo_delete(entry))
        return True

    def undo_delete(self, entry: TrashEntry | None = None) -> bool:
        """Restore preset deleted last (or entry), with its primary preset references"""
        entry = entry or self.last_trashed
        if entry is None or not shiboken6.isValid(self):
            return False
        if entry is self.last_trashed:
            self.last_trashed = None
            self.shortcut_undo.setEnabled(False)
            self.backend.deleted(False)
        if not os.path.isdir(entry.folder):  # restored or removed from trash meanwhile
            return False
        try:
            filename = restore_trashed_preset(entry)
        except OSError as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to restore preset:<br>{error}"))
            return False
        self.refresh()
        app_signal.refresh.emit(True)
        show_toast(self, trm(f"Preset restored: <b>{filename[:-len(FileExt.JSON)]}</b>"))
        return True
