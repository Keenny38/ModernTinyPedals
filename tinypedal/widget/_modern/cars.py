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
Modern overlay design: cars on maps & radar

Car colors by race status (player, leader, lapped, in pit, yellow flag), shared by track map,
navigation & radar, so a car reads the same in every view.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainterPath

from .theme import Theme


class CarColors(NamedTuple):
    """Car fill by race status"""

    player: QColor
    leader: QColor
    same_lap: QColor
    laps_ahead: QColor  # car one lap or more ahead of player
    laps_behind: QColor  # car one lap or more behind player
    in_pit: QColor
    yellow: QColor  # slow or stopped car under local yellow


def car_colors(theme: Theme) -> CarColors:
    """Car colors of theme"""
    return CarColors(
        player=theme.accent,
        leader=theme.positive,
        same_lap=theme.text,
        laps_ahead=theme.lap_ahead,
        laps_behind=theme.blue,
        in_pit=theme.text_faint,
        yellow=theme.caution,
    )


def status_color(colors: CarColors, veh_info) -> QColor:
    """Car color by race status (yellow flag first, then pit, player, leader, laps)"""
    if veh_info.isYellow and not veh_info.inPit:
        return colors.yellow
    if veh_info.inPit and not veh_info.isPlayer:
        return colors.in_pit
    if veh_info.isPlayer:
        return colors.player
    if veh_info.positionOverall == 1:
        return colors.leader
    if veh_info.isLapped > 0:
        return colors.laps_ahead
    if veh_info.isLapped < 0:
        return colors.laps_behind
    return colors.same_lap


def chevron(size: float) -> QPainterPath:
    """Arrow head of car seen from above, pointing up, centered on origin"""
    path = QPainterPath()
    path.moveTo(QPointF(0, -size * 0.6))
    path.lineTo(QPointF(size * 0.48, size * 0.42))
    path.quadTo(QPointF(size * 0.5, size * 0.5), QPointF(size * 0.4, size * 0.47))
    path.lineTo(QPointF(0, size * 0.24))
    path.lineTo(QPointF(-size * 0.4, size * 0.47))
    path.quadTo(QPointF(-size * 0.5, size * 0.5), QPointF(-size * 0.48, size * 0.42))
    path.closeSubpath()
    return path
