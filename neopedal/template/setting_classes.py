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
Default classes template
"""

from types import MappingProxyType

# Primary preset by session of a class: loaded before the class preset ("preset", every session)
SESSION_PRESET_KEYS = MappingProxyType({
    "practice": "preset_practice",
    "qualify": "preset_qualify",
    "race": "preset_race",
})
CLASS_PRESET_KEYS = ("preset", *SESSION_PRESET_KEYS.values())

CLASSINFO_DEFAULT = MappingProxyType({
    "alias": "???",
    "color": "#0044AA",
    "preset": "",
    "preset_practice": "",
    "preset_qualify": "",
    "preset_race": "",
})


def session_name(session_type: int) -> str:
    """Session of primary class presets ("practice", "qualify", "race") of game session type, "" if unknown

    Test day counts as practice, warmup as race (race setup & strategy overlays).
    """
    if session_type in (0, 1):
        return "practice"
    if session_type == 2:
        return "qualify"
    if session_type in (3, 4):
        return "race"
    return ""

# Endurance class colors (WEC): Hypercar red, GT3 green, GTE orange
CLASS_COLORS = MappingProxyType({
    "Hyper": "#E21E19",
    "Hypercar": "#E21E19",
    "LMGT3": "#009639",
    "GT3": "#009639",
    "GTE": "#F08C00",
})
# Default class colors before setting version 2.51.6: replaced once by CLASS_COLORS if never changed
FORMER_DEFAULT_COLORS = MappingProxyType({
    "Hyper": "#FF4400",
    "Hypercar": "#FF4400",
    "GTE": "#00CC44",
    "GT3": "#229900",
})

CLASSES_DEFAULT = {
    "Hyper": {
        "alias": "HY",
        "color": CLASS_COLORS["Hypercar"],
        "preset": "",
    },
    "Hypercar": {
        "alias": "HY",
        "color": CLASS_COLORS["Hypercar"],
        "preset": "",
    },
    "LMP1": {
        "alias": "LMP1",
        "color": "#FF00AA",
        "preset": "",
    },
    "LMP2": {
        "alias": "LMP2",
        "color": "#0088FF",
        "preset": "",
    },
    "LMP2_ELMS": {
        "alias": "LMP2+",
        "color": "#0044AA",
        "preset": "",
    },
    "LMP3": {
        "alias": "LMP3",
        "color": "#880088",
        "preset": "",
    },
    "GTE": {
        "alias": "GTE",
        "color": CLASS_COLORS["GTE"],
        "preset": "",
    },
    "GT3": {
        "alias": "GT3",
        "color": CLASS_COLORS["GT3"],
        "preset": "",
    },
    "LMGT3": {
        "alias": "GT3",
        "color": CLASS_COLORS["LMGT3"],
        "preset": "",
    },
    "DPi": {
        "alias": "DPi",
        "color": "#0044AA",
        "preset": "",
    },
    "FR3.5_2014": {
        "alias": "FR35",
        "color": "#4488AA",
        "preset": "",
    },
    "Formula Pro": {
        "alias": "FPro",
        "color": "#FF3300",
        "preset": "",
    },
}
for _info in CLASSES_DEFAULT.values():
    _info.update((key, "") for key in SESSION_PRESET_KEYS.values())
