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
Settings page: every global option (config.json) by category, and the settings of the loaded preset
(units, global font override, pace notes, API options, module options), in one page

Qt Quick page (qml/Settings.qml), state & actions in quick/settings_backend.py. Replaces the config
pages of Application, Compatibility, Notification, Overlay Style, Remote Control, Web Dashboard,
VR Overlay & User Path (Config menu entries open their category), of units, API options, global font
and module options (Modules page gear opens the module category).
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable
from contextlib import suppress
from functools import partial

from PySide6.QtCore import QMetaObject, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from .. import app_signal, loader
from ..i18n import current_language, tr, trm
from ._common import BaseDialog, UIScaler, page_host, run_after_saving
from .settings_host import SettingsHostMixin
from .toast import show_toast

TITLE = "Settings"
HELP_CACHE_DELAY_MS = 5_000  # last option page closed this long: option help texts freed (see release_help_texts)

# What reads each config.json section once saved, see apply_saved_sections. Any other section (user_path,
# compatibility, api, telemetry...) is read by the API, the modules or the overlays when they start: the whole
# app reloads for it, as before.
REFRESH_SECTIONS = frozenset(("notification", "application"))  # read live by the window, its pages & menus
OVERLAY_SECTIONS = frozenset(("overlay_style",))  # read by each overlay when started: overlays restarted
SWITCH_SECTIONS = {  # read by their server or VR layer when (re)started, see settings_backend.apply_switch
    "remote_control": "servers", "web_dashboard": "servers", "stream_overlay": "stream", "vr_overlay": "vr",
}
RELOAD_OPTIONS = frozenset((  # options of a refreshed section read by overlays & modules when they start
    "application/minimum_update_interval",
    "application/enable_layout_per_screen_setup",
))


def apply_saved_sections(sections: Iterable[str], options: Iterable[str] = ()) -> Callable[[], object]:
    """What applies config.json sections just saved (to run once saving is finished, see run_after_saving)

    The window, its pages & menus are refreshed for the sections they read live (notification, application),
    overlays are restarted for their style, a server or the VR layer is restarted for its section; the whole
    app reloads (API, modules, overlays & servers) for any other section, or for an option that overlays &
    modules read when they start (RELOAD_OPTIONS). Options are "section/key" ids (Settings page, Find Option).
    """
    saved = set(sections)
    known = REFRESH_SECTIONS | OVERLAY_SECTIONS | set(SWITCH_SECTIONS)
    if not saved <= known or any(option in RELOAD_OPTIONS for option in options):
        from .menu import menu_reload_preset

        return menu_reload_preset
    switches = sorted({SWITCH_SECTIONS[section] for section in saved if section in SWITCH_SECTIONS})
    restart_overlays = bool(saved & OVERLAY_SECTIONS)

    def apply():
        if switches:
            from .quick.settings_backend import apply_switch

            for kind in switches:
                apply_switch(kind)
        if restart_overlays:
            from ..module_control import wctrl

            wctrl.reload()
        app_signal.refresh.emit(True)  # pages, menus & notices read the saved settings

    return apply


def release_help_texts():
    """An option page closed: option help texts (several MB of parsed JSON) freed once no option page is open
    anymore, after a delay (page often opened again right away), see i18n.options.hold_help_cache"""
    from ..i18n.options import clear_help_cache, help_cache_held, release_help_cache

    if release_help_cache():
        QTimer.singleShot(HELP_CACHE_DELAY_MS, lambda: None if help_cache_held() else clear_help_cache())


def open_app_settings(parent, section: str = "", key: str = "") -> AppSettings:
    """Open settings page (shown again if open) at category of config section or of a section of the
    loaded preset ("units", "font", "api", "pace_notes_playback", a module...), option flashed if set"""
    host = page_host(parent, AppSettings)
    page = host.find_dialog_page(AppSettings.__name__) if host is not None else None
    if page is not None and isinstance(page.dialog, AppSettings):  # already open: shown, no copy built
        host.show_page_widget(page)
        shown: BaseDialog = page.dialog
    else:
        dialog = AppSettings(parent)
        dialog.open()
        shown = dialog.shown_dialog()  # same page already open: shown instead, this copy deleted
    if isinstance(shown, AppSettings):
        if key:
            shown.backend.focus_option(section, key)
        elif section:
            shown.backend.open_section(section)
    return shown  # type: ignore[return-value]


class AppSettings(SettingsHostMixin, BaseDialog):
    """Settings page (global options of config.json, settings of the loaded preset)"""

    OWNS_TITLE = True  # category title in the page (no page header title above it)

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.settings_backend import SettingsBackend

        super().__init__(parent)
        self.set_utility_title(tr(TITLE))
        # Layout follows page width (categories as a choice list when narrow): window never grown for it
        self.setMinimumSize(UIScaler.size(32), UIScaler.size(24))
        from ..i18n.options import hold_help_cache

        hold_help_cache()  # option help texts kept while this page is open, see release_help_texts
        self._help_held = True
        self.backend = SettingsBackend(self, self)
        self.backend.stateChanged.connect(self.refresh_modified)
        self._language = current_language()
        self._stale = False  # changed while hidden, see refresh
        self.view: QQuickWidget = create_quick_view(self, "Settings.qml", {"backend": self.backend}, samples=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        # Text fields keep their own undo while focused (shortcut override)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.backend.undo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self, self.backend.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.backend.redo)
        app_signal.refresh.connect(self.refresh)

    # Page state
    def is_modified(self) -> bool:
        return self.backend.is_modified()

    def save_action(self):
        """Ctrl+S: Apply, page kept open"""
        return self.apply_edits

    def apply_edits(self) -> bool:
        """Field being edited committed first (Ctrl+S keeps focus in it), then Apply"""
        root = self.view.rootObject() if self.view is not None else None
        if root is not None:
            QMetaObject.invokeMethod(root, "commitEdits")
        return self.backend.apply()

    def refresh(self, *_):
        """Settings saved elsewhere, or app language changed: page updated now if shown, else once shown
        (navigation bar page kept open behind other pages)"""
        if self.view is None:
            return
        if not self.isVisible():
            self._stale = True
            return
        self.refresh_now()

    def refresh_now(self):
        """Values & status cards read again, page rebuilt in new app language"""
        self._stale = False
        if self.view is None:
            return
        if current_language() != self._language:
            self.retranslate()
        self.backend.refresh()

    def showEvent(self, event):
        if self._stale:
            self.refresh_now()
        super().showEvent(event)

    def retranslate(self):
        """QML texts & page title in new app language, pending edits kept"""
        self._language = current_language()
        self.set_utility_title(tr(TITLE))
        from .app import DialogPage

        page = self.parentWidget()
        while page is not None and not isinstance(page, DialogPage):
            page = page.parentWidget()
        if isinstance(page, DialogPage):  # in-app page title
            page.title = tr(TITLE)
            page.show_modified()
        from .quick import reload_in_language

        reload_in_language(self.view)

    def closeEvent(self, event):
        if self.is_modified():
            confirm = QMessageBox.question(
                self, tr("Confirm"), tr("<b>Save changes before continuing?</b>"),
                buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if confirm == QMessageBox.StandardButton.Cancel or (
                    confirm == QMessageBox.StandardButton.Save and not self.apply_edits()):
                event.ignore()
                return
        event.accept()
        with suppress(RuntimeError, TypeError):  # closed twice
            app_signal.refresh.disconnect(self.refresh)
        view, self.view = self.view, None  # type: ignore[assignment]
        if view is not None:  # closed twice (nested event loop while asking to save)
            view.setSource(QUrl())  # QML gone before the backend it binds to
        if self._help_held:  # option help texts freed once no option page is open (closed twice: once)
            self._help_held = False
            release_help_texts()

    def reject(self):
        """Esc: close, asking to save pending changes"""
        self.close()

    # Settings host: dialogs & applying
    def confirm(self, text: str) -> bool:
        return self.confirm_operation(title="Confirm", message=text)

    def applied(self, sections: set[str], restart: list[str]):
        """Settings saved: what reads them is refreshed or restarted (see apply_saved_sections), options read
        at startup offer a restart"""
        options = list(self.backend.applied_options)  # saved option ids: some need the whole app reloaded
        if restart:
            from .quick.dialogs import confirm

            confirm(self, tr("Restart NeoPedal"),
                    trm(f"<b>{html.escape(', '.join(restart))}</b>: restart NeoPedal now to apply?"),
                    tr("Restart NeoPedal"), partial(self.restart_or_reload, sections, options))
            return
        self.restart_or_reload(sections, options, False)

    def restart_or_reload(self, sections: set[str], options: list[str], restart: bool):
        """Restart chosen (options read at startup), else saved settings applied: the window refreshed, overlays,
        a server or the whole app restarted, by what reads the saved sections (see apply_saved_sections)"""
        import shiboken6

        if not shiboken6.isValid(self):  # page closed while asked (question cancelled): settings applied anyway
            run_after_saving(apply_saved_sections(sections, options))
            return
        if restart:
            window = self.window()
            restart_app = getattr(window, "restart_app", None) if window is not self else None
            run_after_saving(restart_app if callable(restart_app) else loader.restart)
            return
        show_toast(self, tr("Settings saved"))
        run_after_saving(apply_saved_sections(sections, options))
