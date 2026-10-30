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
Page hosting a table editor (qml/editors/TableEditor.qml, backend: quick/table_editor.py)

Undo history (snapshots of the backend rows, Ctrl+Z / Ctrl+Y), unsaved changes marker, Ctrl+S (save), save or
discard asked on close, warnings & color / file dialogs of the backend. QML view made when first shown.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import QSize, QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFileDialog, QVBoxLayout

from ...i18n import tr, trm
from .._common import BaseEditor, UIScaler
from . import last_folder
from .table_editor import TableEditorBackend


class TableEditorPage(BaseEditor):
    """Table editor page: BACKEND class edits the table, TITLE names the page"""

    BACKEND: ClassVar[type[TableEditorBackend]] = TableEditorBackend
    TITLE = "Table Editor"
    MIN_WIDTH = 30  # em: search, Add & Save stay whole, other actions into the toolbar menu, table scrolls sideways

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr(self.TITLE))
        self.view: QQuickWidget | None = None  # see ensure_view
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.backend = self.BACKEND(self, self)
        self.enable_undo(self.backend.capture_state, self.backend.restore_state)
        self.setMinimumSize(self.page_minimum_size())
        self.resize(UIScaler.size(60), UIScaler.size(40))
        self.set_unmodified()

    def page_minimum_size(self) -> QSize:
        """Page area minimum while shown in app window (QML pages do not scroll)"""
        return QSize(UIScaler.size(self.MIN_WIDTH), UIScaler.size(22))

    def ensure_view(self) -> QQuickWidget:
        """QML page, made when first shown (backend works without it)"""
        if self.view is None:
            from . import create_quick_view

            view = create_quick_view(self, "TableEditor.qml", {"backend": self.backend})
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
        self.backend.page_hidden()
        super().hideEvent(event)

    # Undo history & unsaved changes told to backend (buttons of page)
    def sync_history(self):
        if hasattr(self, "backend"):
            self.backend.set_history(self.is_modified(), bool(self._undo_stack), bool(self._redo_stack))

    def set_modified(self):
        super().set_modified()
        self.sync_history()

    def set_unmodified(self):
        super().set_unmodified()
        self.sync_history()

    def record_change(self):
        super().record_change()
        self.sync_history()

    def reset_undo(self):
        super().reset_undo()
        self.sync_history()

    def undo(self):
        super().undo()
        self.sync_history()

    def redo(self):
        super().redo()
        self.sync_history()

    # Save (Ctrl+S, asked on close): one save, page stays open
    def applying(self):
        self.backend.save()

    def saving(self):
        self.backend.save()

    def free_page(self):
        if self.view is not None:  # QML gone before the backend it binds to
            view, self.view = self.view, None
            view.setSource(QUrl())
            view.deleteLater()
        self.backend.release()

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():  # Esc closes too (BaseEditor.reject), page released once
            self.release_page()

    # Backend dialogs & toasts: in the page (TpDialogHost), else widget dialogs
    def warn(self, text: str):
        """Change refused (duplicate name, invalid color, import failed): warning level, the table is kept"""
        from .dialogs import alert

        alert(self, tr("Error"), trm(text), "warning")

    def ask(self, title: str, text: str, action_text: str, on_result: Callable[[bool], object]):
        from .dialogs import confirm

        confirm(self, title, text, action_text, on_result)

    def toast(self, text: str, error: bool = False, undo: bool = False):
        from ..toast import show_toast

        show_toast(self, text, action_text=tr("Undo") if undo else "", action=self.undo if undo else None,
                   level="error" if error else "")

    def pick_color(self, color: str) -> str:
        from ..overlay_options import pick_color

        return pick_color(self, color)

    def open_file(self, file_filter: str) -> str:
        """File picked to import rows, started in the last folder of table imports"""
        filename = QFileDialog.getOpenFileName(self, dir=last_folder.start_folder("table_import"), filter=file_filter)[0]
        last_folder.remember("table_import", filename)
        return filename
