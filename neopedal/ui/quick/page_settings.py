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
Page settings kept between sessions: one JSON file per page in the user config folder

A page changes its settings often (number arrows held, filters clicked): PageSettings.save() writes them once
changes pause (UI thread timer), flush() writes them at once (page closing; app quitting: every page). Reading the
file of a page first writes changes of its open pages.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import weakref
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QTimer
from shiboken6 import isValid

from ...setting import cfg
from ...userfile import atomic_write

logger = logging.getLogger(__name__)

SAVE_DELAY_MS = 500  # settings written once changes pause

_unsaved: weakref.WeakSet[PageSettings] = weakref.WeakSet()  # page settings changed, not written yet
_quit_hooked: weakref.ReferenceType | None = None  # app whose quit writes every page settings


def settings_path(name: str) -> str:
    return os.path.join(cfg.path.config, name)


def load_settings(name: str) -> dict[str, Any]:
    """Settings of file name ({} if missing or invalid), changes of open pages written first"""
    flush_all(name)
    try:
        with open(settings_path(name), encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(name: str, data: dict[str, Any]):
    """Settings written at once (errors logged)"""
    with atomic_write(settings_path(name)) as file:
        file.write(json.dumps(data, indent=1, ensure_ascii=False))


def flush_all(name: str | None = None):
    """Settings changed of every page (of file name only if given) written now"""
    for settings in list(_unsaved):
        if not isValid(settings):  # page deleted without closing: changes lost
            _unsaved.discard(settings)
        elif name is None or settings.name == name:
            settings.flush()


def _hook_quit():
    """App quitting with pages open: their changed settings written (hooked once per app)"""
    global _quit_hooked
    app = QCoreApplication.instance()
    if app is None or (_quit_hooked is not None and _quit_hooked() is app):
        return
    app.aboutToQuit.connect(flush_all)
    _quit_hooked = weakref.ref(app)


class PageSettings(QObject):
    """Settings file of a page: read, written once changes pause (UI thread)

    Args:
        name: file name in the user config folder.
        delay_ms: changes written this long after the last one.
        parent: page backend (timer stops with it).
        collect: settings written when save() is given none, read when written (held weakly when a bound method:
            the page is never kept alive by its settings).
    """

    def __init__(self, name: str, delay_ms: int, parent: QObject,
                 collect: Callable[[], dict[str, Any]] | None = None):
        super().__init__(parent)
        self.name = name
        self._collect: Callable[[], Callable[[], dict[str, Any]] | None] = (
            weakref.WeakMethod(collect) if inspect.ismethod(collect) else lambda: collect)
        self._data: dict[str, Any] | None = None  # settings given to save(), written once changes pause
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.flush)
        _hook_quit()

    @property
    def pending(self) -> bool:
        """Changes not written yet"""
        return self._dirty

    def load(self) -> dict[str, Any]:
        return load_settings(self.name)

    def save(self, data: dict[str, Any] | None = None):
        """Settings (data as given now, else collected when written) written once changes pause (number arrows
        held: one write)"""
        self._data = data
        self._dirty = True
        _unsaved.add(self)
        self._timer.start()

    def save_now(self, data: dict[str, Any] | None = None):
        """Settings written at once (read by other parts of the app from the file)"""
        self._data = data
        self._dirty = True
        self.flush()

    def flush(self):
        """Settings changed written now (changes paused, page closing, app quitting)"""
        self._timer.stop()
        _unsaved.discard(self)
        if not self._dirty:
            return
        self._dirty = False
        data, self._data = self._data, None
        if data is None:
            collect = self._collect()
            if collect is None:  # page gone
                return
            data = collect()
        try:
            write_settings(self.name, data)
        except OSError as error:
            logger.warning("Page settings %s not saved: %s", self.name, error)
