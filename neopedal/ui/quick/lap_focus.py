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
Lap viewer page opened on given laps (Home page session debrief): reference & compared lap of a track folder,
then a corner of the reference lap shown in the Corners tab with charts zoomed on it

Laps load in background: the corner is picked once the reference lap is shown with its corners found (lap viewer
tells each chart rebuild), within FOCUS_TIMEOUT_MS.

Guided analysis ("Analyze My Last Lap"): best lap against newest lap, then the Corners tab and charts zoomed on the
corner where the newest lap loses most time (LostCornerFocus, same wait).
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from PySide6.QtCore import QObject, QTimer

from ...i18n import tr
from .lap_actions import path_key

FOCUS_TIMEOUT_MS = 30_000  # laps not shown by then (huge files, other laps picked meanwhile): corner left alone
CORNERS_TAB = 2  # side tab of lap viewer: map, G circle, corners...


def corner_at(rows: list, apex: float) -> int:
    """Corner row covering a lap distance (corner table rows), else the one with the nearest apex, -1 if none"""
    for index, row in enumerate(rows):
        if row.corner.start <= apex <= row.corner.end:
            return index
    if not rows:
        return -1
    return min(range(len(rows)), key=lambda index: abs(rows[index].corner.apex - apex))


class CornerFocus(QObject):
    """Waits for the reference lap to be shown with its corners, then selects the corner around apex (once)"""

    def __init__(self, backend: Any, reference: str, apex: float):
        super().__init__(backend)
        self._backend = backend
        self._reference = path_key(reference)
        self._apex = apex
        self._done = False
        backend.chartChanged.connect(self.check)
        QTimer.singleShot(FOCUS_TIMEOUT_MS, self, self.stop)

    def check(self):
        backend = self._backend
        if self._done:
            return
        if path_key(backend.reference_key or "-") != self._reference:
            return
        if not any(path_key(lap.key) == self._reference for lap in backend.data.laps):
            return
        rows = backend.corner_rows()
        if not rows:
            return
        index = corner_at(rows, self._apex)
        backend.setSideTab(CORNERS_TAB)
        backend.setSelectedCorner(index)
        backend.cornerTable.request_focus(index)
        self.stop()

    def stop(self):
        if self._done:
            return
        self._done = True
        with suppress(RuntimeError, TypeError):  # already disconnected
            self._backend.chartChanged.disconnect(self.check)
        self.deleteLater()


class LostCornerFocus(QObject):
    """Guided analysis: waits for best & last laps to be shown with their corners, then opens the Corners tab on the
    corner where the last lap loses most time (once); tells the page when there is none"""

    def __init__(self, backend: Any, reference: str, compared: str):
        super().__init__(backend)
        self._backend = backend
        self._reference = path_key(reference)
        self._compared = path_key(compared)
        self._done = False
        backend.chartChanged.connect(self.check)
        QTimer.singleShot(FOCUS_TIMEOUT_MS, self, self.stop)

    def check(self):
        backend = self._backend
        if self._done or path_key(backend.reference_key or "-") != self._reference:
            return
        if {path_key(lap.key) for lap in backend.data.laps} != {self._reference, self._compared}:
            return  # other laps still shown (charts of best & last lap being built)
        lost = backend.cornerTable.lost_corners()
        backend.setSideTab(CORNERS_TAB)
        if lost:
            backend.setSelectedCorner(lost[0])
            backend.lostCornersShown.emit()  # charts zoomed on worst corner, steps through the others
        else:
            backend.set_status(tr("No corner where the last lap loses time against the best lap"))
        self.stop()

    def stop(self):
        if self._done:
            return
        self._done = True
        with suppress(RuntimeError, TypeError):  # already disconnected
            self._backend.chartChanged.disconnect(self.check)
        self.deleteLater()


def analyze_last_lap(backend: Any, best: str, last: str) -> LostCornerFocus | None:
    """Best lap against last lap (compare preset already applied by the page), then the corner where the last lap
    loses most time; None if the last lap is the best one (nothing to compare)"""
    if not best or not last or path_key(best) == path_key(last):
        return None
    focus = LostCornerFocus(backend, best, last)
    QTimer.singleShot(0, focus, focus.check)  # laps already read: charts may be built at once
    return focus


def show_laps(backend: Any, reference: str, compared: str = "", apex: float = -1.0) -> bool:
    """Lap viewer backend shows reference & compared laps of a track folder, then the corner around apex (lap
    distance of reference lap, -1: none) in its Corners tab; False if reference lap is not in a track folder"""
    focus = CornerFocus(backend, reference, apex) if apex >= 0 else None
    if not backend.show_track_laps(reference, compared):
        if focus is not None:
            focus.stop()
        return False
    if focus is not None:
        QTimer.singleShot(0, focus, focus.check)  # laps shown at once (already read): charts may be built
    elif compared:
        backend.setSideTab(CORNERS_TAB)
    return True
