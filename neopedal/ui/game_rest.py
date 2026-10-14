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
Game Rest API requests moved to the core module neopedal.game_rest (used by core & pages)

This name is the same module object (sys.modules alias): older imports & patches of neopedal.ui.game_rest act
on neopedal.game_rest.
"""

import sys

from .. import game_rest as _game_rest
from ..game_rest import *  # names seen by type checkers

sys.modules[__name__] = _game_rest
