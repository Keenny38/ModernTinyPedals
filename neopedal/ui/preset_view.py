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
Presets page: loaded preset & auto load, presets with tags & content, actions & details

Qt Quick page (qml/Presets.qml), state & actions in quick/preset_backend.py. This page hosts the
QML view and runs actions needing file dialogs: preset packages, delete with undo. Compare, Transfer,
Restore Backup & Recently Deleted are panels of the QML page. The QML page is created when first shown.
"""

from __future__ import annotations

import html
import os
import zipfile
from contextlib import nullcontext
from functools import partial

import shiboken6
from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from .. import app_signal
from ..const_file import ConfigType, FileExt
from ..i18n import tr, trm
from ..setting import cfg
from ..userfile.preset_package import export_preset_package, import_preset_package
from ..userfile.preset_trash import TrashEntry, purge_trash
from ._common import confirm_action, translate_filter
from .preset_management import (
    after_saving,
    restore_trashed_preset,
    trash_keep_days,
    trash_preset,
    update_preset_references,
)
from .quick import dialogs
from .quick.preset_backend import PRESET_FILES, PRESET_FILES_WAIT, TRY_AGAIN, PresetBackend
from .quick.preset_tools_backend import TRASH
from .toast import show_toast


def purge_old_trash() -> None:
    """Presets deleted long ago removed from trash (startup), skipped if the trash page reads or restores
    meanwhile: its own read purges as well"""
    if not TRASH.acquire(blocking=False):
        return
    try:
        purge_trash(cfg.path.settings, trash_keep_days())
    finally:
        TRASH.release()


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
        QTimer.singleShot(3000, self, purge_old_trash)

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
        """Presets, loaded preset or tags changed (read when page is shown)"""
        self.backend.refresh()

    # Messages
    def confirm_operation(self, title: str = "Confirm", message: str = "", action_text: str = "") -> bool:
        """Confirm operation: Cancel, then the action button (see _common.confirm_action)"""
        return confirm_action(self, tr(title), trm(message), action_text or tr(title))

    def ask(self, title: str, message: str, on_result):
        """Confirmation over the page (QML dialog of its TpDialogHost), answer by callback: title translated,
        message English (translated here)"""
        dialogs.confirm(self, title, trm(message), title, on_result)

    def warn(self, text: str):
        dialogs.alert(self, tr("Error"), text, "warning")

    def toast(self, text: str):
        """Short notice in the toast of the page"""
        self.backend.show_toast(text)

    def page_toast(self, text: str, error: bool = False, undo: bool = False):
        """Toast of the page (TpDialogHost), Undo of the last delete"""
        show_toast(self, text, level="error" if error else "",
                   action_text=tr("Undo") if undo else "", action=self.backend.undoDelete if undo else None)

    # Folder (other tools are panels of the page)
    def open_page(self, name: str):
        """Presets folder in file manager"""
        if name == "folder":
            folder = os.path.abspath(cfg.path.settings)
            if not os.path.isdir(folder) or not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):  # never a file
                dialogs.alert(self, tr("Error"), trm(f"Cannot open folder:<br><b>{html.escape(folder)}</b>"), "warning")

    # Load & auto load
    def load_preset(self, name: str):
        """Load preset by name (without extension)"""
        self.backend.load(f"{name}{FileExt.JSON}")

    @staticmethod
    def toggle_autoload(checked: bool):
        """Toggle auto load preset"""
        cfg.application["enable_auto_load_preset"] = checked
        cfg.save(config_type=ConfigType.CONFIG)

    # Packages
    def export_package(self, preset_filename: str):
        """Export preset, style presets and notes to single zip file"""
        include_notes = confirm_action(
            self, tr("Export Package"), tr("Include track notes & pace notes in package?"),
            tr("Include Notes"), cancel_text=tr("Without Notes"))
        zip_filename, _ = QFileDialog.getSaveFileName(
            self,
            dir=os.path.join(os.path.expanduser("~"), f"{preset_filename[:-5]}.zip"),
            filter=translate_filter("NeoPedal preset package (*.zip)"),
        )
        if not zip_filename:
            return
        notes_paths = {"tracknotes": cfg.path.track_notes, "pacenotes": cfg.path.pace_notes} if include_notes else None
        try:
            count = export_preset_package(zip_filename, cfg.path.settings, preset_filename, notes_paths=notes_paths)
        except OSError as error:
            dialogs.alert(self, tr("Error"), trm(f"Unable to export package:<br>{html.escape(str(error))}"), "warning")
            return
        self.toast(trm(f"Exported <b>{count}</b> file(s) to:<br>{html.escape(zip_filename)}"))

    def import_package(self):
        """Import preset package"""
        zip_filename, _ = QFileDialog.getOpenFileName(
            self, dir=os.path.expanduser("~"), filter=translate_filter("NeoPedal preset package (*.zip)"),
        )
        if zip_filename:
            self.import_package_file(zip_filename)

    def import_package_file(self, zip_filename: str):
        """Import preset package file"""
        from ..userfile.overlay_package import is_overlay_package

        if is_overlay_package(zip_filename):  # overlay settings: imported into loaded preset
            from .overlay_share import import_overlay_file

            import_overlay_file(self, zip_filename)
            return
        overwrite_styles = confirm_action(
            self, tr("Import Package"),
            tr("Also import style presets (brakes, brands, classes, compounds, heatmap, tracks)?<br><br>"
            "This will <b>overwrite</b> your existing style presets."),
            tr("Import Style Presets"), cancel_text=tr("Keep My Style Presets"), danger=True)
        if overwrite_styles:  # a running save finished first, waited off the UI thread (audit PERF-018)
            after_saving(self.backend, partial(self._import_package_now, zip_filename, True))
        else:
            self._import_package_now(zip_filename, False)

    def _import_package_now(self, zip_filename: str, overwrite_styles: bool):
        # Styles: saving paused across import (no save written over imported styles), then reloaded
        # in memory (also styles imported before an error), so later style saves keep imported ones
        try:
            with cfg.styles_replaced() if overwrite_styles else nullcontext():
                result = import_preset_package(
                    zip_filename,
                    cfg.path.settings,
                    overwrite_styles=overwrite_styles,
                    notes_paths={"tracknotes": cfg.path.track_notes, "pacenotes": cfg.path.pace_notes},
                    receiver=cfg.user.setting,  # local file & game connection options: yours kept
                )
        except (ValueError, OSError, zipfile.BadZipFile) as error:
            self.refresh()  # presets imported before error
            dialogs.alert(self, tr("Error"), trm(f"Unable to import package:<br>{html.escape(str(error))}"), "warning")
            return
        self.refresh()
        lines = [f"Presets: <b>{html.escape(', '.join(name[:-5] for name in result.presets)) or tr('none')}</b>"]
        if result.styles:
            lines.append(f"Style presets: {html.escape(', '.join(result.styles))} (reload preset to apply)")
        if result.notes:
            lines.append(f"Notes: {result.notes} file(s)")
        if result.skipped:
            lines.append(f"Skipped: {len(result.skipped)} file(s) (existing or not allowed)")
        if result.kept:
            lines.append(f"Kept yours: {len(result.kept)} local file & game connection option(s)")
        dialogs.alert(self, tr("Import Package"), trm("<br>".join(lines)), "info")

    # Delete & undo
    def delete_preset(self, preset_filename: str) -> bool:
        """Move preset file & layout profiles to trash, clear primary preset references (shortcuts,
        tracks, classes), undo shown for a few seconds (also Ctrl+Z, or from trash later)"""
        if not os.path.exists(f"{cfg.path.settings}{preset_filename}"):  # already gone
            update_preset_references(preset_filename[:-len(FileExt.JSON)], "")
            return True
        # Not being read by the page meanwhile; a slow read (disk, antivirus) never blocks the GUI for long
        if not PRESET_FILES.acquire(timeout=PRESET_FILES_WAIT):
            show_toast(self, tr(TRY_AGAIN), level="error")
            return False
        try:
            with TRASH:  # never during a purge or restore of the trash page
                entry = trash_preset(preset_filename)
        except OSError as error:  # locked file (cloud sync, antivirus), permission
            dialogs.alert(
                self, tr("Delete Preset"), trm(f"Unable to delete preset:<br>{html.escape(str(error))}"), "warning")
            return False
        finally:
            PRESET_FILES.release()
        self.last_trashed = entry
        self.shortcut_undo.setEnabled(True)
        self.backend.deleted(True)
        self.backend.show_toast(trm(f"Preset <b>{html.escape(entry.name)}</b> moved to trash"), undo=True)
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
            dialogs.alert(self, tr("Error"), trm(f"Unable to restore preset:<br>{html.escape(str(error))}"), "warning")
            return False
        self.refresh()
        app_signal.refresh.emit(True)
        self.toast(trm(f"Preset restored: <b>{html.escape(filename[:-len(FileExt.JSON)])}</b>"))
        return True
