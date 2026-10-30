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
Host of a Settings page backend (quick/settings_backend.py): dialogs & applying of saved settings, shared by the
Settings page (app_settings) and the Pace Notes page (pace_notes_view). No Qt Quick import: the Pace Notes page
module is imported when the main window is built.
"""

from __future__ import annotations

import html
import os
import sys
from contextlib import suppress
from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QColorDialog, QFileDialog

from .. import app_signal
from ..const_file import FileFilter
from ..i18n import tr, trm
from ._common import run_after_saving, translate_filter
from .toast import show_toast


class SettingsHostMixin:
    """Dialogs & applying of a page hosting a SettingsBackend (Settings page, Pace Notes page)"""

    def pick_color(self, color: str) -> str:
        from ._option import ColorEdit

        dialog = QColorDialog(self)  # type: ignore[call-overload]
        for index, old_color in enumerate(ColorEdit.HISTORY):
            dialog.setCustomColor(index, QColor(old_color))
        picked = dialog.getColor(
            initial=QColor(color), parent=self, options=QColorDialog.ColorDialogOption.ShowAlphaChannel)  # type: ignore[arg-type]
        if not picked.isValid():
            return ""
        if ColorEdit.HISTORY[0] != picked:
            ColorEdit.HISTORY.appendleft(picked)
        name_format = QColor.NameFormat.HexRgb if picked.alpha() == 255 else QColor.NameFormat.HexArgb
        return picked.name(name_format).upper()

    def pick_folder(self, folder: str) -> str:
        return QFileDialog.getExistingDirectory(self, dir=folder)  # type: ignore[arg-type]

    def pick_image(self, filename: str) -> str:
        return QFileDialog.getOpenFileName(self, dir=filename, filter=translate_filter(FileFilter.PNG))[0]  # type: ignore[arg-type]

    def pick_file(self, filename: str, filter_name: str) -> str:
        """File of a file option (pace notes file), filter: FileFilter attribute name"""
        file_filter = getattr(FileFilter, filter_name, "")
        return QFileDialog.getOpenFileName(
            self, dir=filename, filter=translate_filter(file_filter) if file_filter else "")[0]  # type: ignore[arg-type]

    def open_folder(self, folder: str):
        """Folder in file manager, created if missing"""
        with suppress(OSError):
            os.makedirs(folder, exist_ok=True)
        if os.path.isdir(folder):
            if sys.platform == "win32":  # platform check also read by type checker
                try:
                    os.startfile(folder)
                    return
                except OSError:  # no associated application, access denied: try Qt below
                    pass
            if QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
                return
        from .quick.dialogs import alert  # Qt Quick package imported once a page is shown

        alert(self, tr("Error"), trm(f"Cannot open folder:<br><b>{html.escape(folder)}</b>"), "warning")  # type: ignore[arg-type]

    def ask(self, text: str, action_text: str, on_result):
        """Confirmation over the page (QML dialog of its TpDialogHost), answer by callback (translated texts)"""
        from .quick.dialogs import confirm

        confirm(self, tr("Confirm"), text, action_text, on_result)  # type: ignore[arg-type]

    def toast(self, text: str):
        show_toast(self, text)  # type: ignore[arg-type]

    def applied_preset(self, sections: set[str], config_sections: set[str], font_sections: int, undo):
        """Settings of the loaded preset saved: the parts reading them restarted (none if the whole app
        reloads for config.json settings saved at the same time), Undo offered for a global font override

        Args:
            config_sections: config.json sections saved at the same time (see applied).
            font_sections: overlays & modules whose font changed (global font override), 0 if none.
            undo: puts the fonts back, False if another preset was loaded meanwhile.
        """
        from ..module_control import mctrl
        from .menu import menu_reload_only, menu_restart_api

        reloaded = bool(config_sections - {"notification"})  # see applied
        if font_sections:
            show_toast(self, trm(f"Font changed in {font_sections} overlay(s)"),  # type: ignore[arg-type]
                       action_text=tr("Undo"), action=lambda: self.undo_font(undo))
        elif not config_sections:
            show_toast(self, tr("Settings saved"))  # type: ignore[arg-type]
        if any(section.startswith("api_") for section in sections):
            run_after_saving(menu_restart_api)
        others = {section for section in sections if not section.startswith("api_")}
        if reloaded or not (others or font_sections):
            return
        modules = others & set(mctrl.names)
        if font_sections or others - modules - {"pace_notes_playback"}:
            run_after_saving(menu_reload_only)  # overlays read units & fonts when started
            return
        if "pace_notes_playback" in others:
            app_signal.refresh.emit(True)  # pace notes player follows its settings
            modules.add("module_notes")  # notes file read again
        for name in sorted(modules):
            run_after_saving(partial(mctrl.reload, name))
        run_after_saving(partial(app_signal.refresh.emit, True))  # module cards & other pages read again

    def undo_font(self, undo) -> None:
        """Toast Undo of a global font override"""
        from .menu import menu_reload_only

        if undo():
            run_after_saving(menu_reload_only)
            show_toast(self, tr("Font change undone"))  # type: ignore[arg-type]
        else:
            show_toast(self, tr("Another preset was loaded: font change not undone"), level="error")  # type: ignore[arg-type]

    def test_sound(self, values: dict) -> str:
        """Pace notes: a sound of the sound folder played, "" if played else why not (translated)"""
        from .pace_notes_view import play_test_sound

        return play_test_sound(self, values)  # type: ignore[arg-type]

    def open_link(self, name: str):
        """Section of the loaded preset shown (former links of the Settings page)"""
        backend = getattr(self, "backend", None)
        if backend is not None:
            backend.open_section(name)
