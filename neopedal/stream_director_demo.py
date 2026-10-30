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
Broadcast graphics sample state (layout editor: every graphic shown with sample data) & texts of the graphics
page in app language (see stream_director)
"""

from __future__ import annotations

from typing import Any


def demo_state() -> dict[str, Any]:
    """Sample state showing every graphic (layout editor), texts in app language"""
    from .i18n import tr

    colors = ("#E21E19", "#0088FF", "#009639")
    classes = ("Hypercar", "LMP2", "LMGT3")
    names = ("A. Martin", "L. Hartmann", "K. Sato", "M. Rossi", "J. Novak", "E. Dubois", "T. Becker", "S. Lindqvist",
             "R. Costa", "P. Walsh", "N. Ivanova", "D. Okafor")
    tower = []
    for index, name in enumerate(names):
        cls = index // 4
        tower.append({
            "pos": index + 1, "classPos": index % 4 + 1, "cls": classes[cls], "color": colors[cls],
            "number": str(7 + index * 3), "name": name, "gap": f"+{0.4 + index * 1.7:.1f}" if index else "",
            "gapClass": f"+{0.4 + index % 4 * 1.3:.1f}" if index % 4 else "",
            "gapLeader": f"+{index * 4.1:.1f}" if index else "",
            "gapClassLeader": f"+{index % 4 * 3.2:.1f}" if index % 4 else "", "close": index == 2,
            "pit": index == 9, "air": index == 2, "change": (1, 0, 2, -1, 0, 0, -2, 1, 0, 0, 0, 0)[index],
            "lap": "1:35.418" if index == 4 else "", "lapId": 1, "lapTone": "fastest" if index == 4 else "",
            "tyres": ["M"] if index % 3 else ["S", "M"], "pen": 1 if index == 7 else 0,
            "fastest": index in (1, 4, 9), "stops": 2 if index % 2 else 1,
        })
    car = {"number": "13", "name": "Kenji Sato", "team": "Vortex Racing", "cls": "Hypercar", "color": colors[0],
           "classPos": 3, "logo": "", "picture": "",
           "stats": [[tr("Best"), "1:34.902"], [tr("Last"), "1:35.211"], [tr("Laps"), "42"], [tr("Places"), "+2"], ["DR", "S2"], ["SR", "P3"], [tr("Badge"), tr("Trusted Racer")]],
           "story": tr("Battle for P%1").replace("%1", "2"), "storyTone": "accent"}
    side = {"number": "10", "name": "L. Hartmann", "team": "Apex Motorsport"}
    other = {"number": "13", "name": "K. Sato", "team": "Vortex Racing"}
    train = [{"number": str(7 + index * 3), "name": names[index], "classPos": index + 1,
              "gap": "" if index == 0 else f"+{0.3 + index * 0.2:.1f}", "air": index == 2, "color": colors[0]}
             for index in range(5)]
    grid = [{"pos": index + 1, "number": tower[index]["number"], "name": names[index], "team": "Vortex Racing",
             "cls": tower[index]["cls"], "color": tower[index]["color"], "time": f"1:3{3 + index // 4}.{412 + index * 37}",
             "picture": ""} for index in range(8)]
    rows = [{"pos": row["pos"], "classPos": row["classPos"], "cls": row["cls"], "color": row["color"],
             "number": row["number"], "name": row["name"], "team": "Vortex Racing", "laps": 42 - index // 4,
             "gap": row["gap"] or tr("Leader"), "best": f"1:3{4 + index // 4}.{100 + index * 41}", "pits": 2,
             "status": tr("Retired") if index == 11 else ""} for index, row in enumerate(tower)]
    champ = [{"pos": index + 1, "name": names[index], "team": "Vortex Racing", "cls": "Hypercar", "color": colors[0],
              "points": 120 - index * 14, "medal": index + 1 if index < 3 else 0} for index in range(8)]
    return {
        "live": True, "demo": True, "cut": 1, "tower": tower, "onAir": car, "events": [],
        "graphics": {"tower": True, "towerMode": "all", "towerRows": 12, "towerCycle": 10, "card": True,
                     "cardSeconds": 0, "cardPicture": False, "battle": True, "train": True, "banners": True,
                     "bannerSeconds": 6, "replay": True, "clock": True, "hidden": False, "pitRadar": True,
                     "onboard": True, "onboardStyle": "dash", "quali": True, "map": True, "towerLaps": True,
                     "towerTyres": True, "towerPenalties": True, "towerFastest": True, "towerStops": True,
                     "towerGap": "interval", "towerGroup": False, "opacity": 92, "pageSeconds": 10,
                     "resultsRows": 10, "gridSeconds": 8, "replayGraphics": True, "mapRotation": 0, "mapDots": 100,
                     "accent": "#e5383b", "logo": True, "sponsors": True, "sponsorSeconds": 8},
        "battle": {"title": f"{tr('Battle for P%1').replace('%1', '2')} · Hypercar", "color": colors[0],
                   "gap": "0.4 s", "trend": tr("%1/lap").replace("%1", "-0.1 s"), "trendClass": "closing",
                   "ahead": side, "behind": other},
        "train": {"title": f"{tr('Battle for P%1').replace('%1', '1')} · Hypercar", "color": colors[0], "cars": train},
        "replay": True, "replayInfo": None,
        "clock": {"text": "2:41:07", "label": tr("Remaining")}, "flag": "",
        "weather": [tr("Air %1").replace("%1", "24°C"), tr("Track %1").replace("%1", "33°C")],
        "pitRadar": {"title": tr("Pit Lane"), "count": tr("%1 cars approaching").replace("%1", "1"),
                     "rows": [{"number": "22", "name": "J. Novak", "color": colors[1], "distance": "38 m",
                               "alongside": False, "ahead": True},
                              {"number": "31", "name": "T. Becker", "color": colors[2], "distance": "",
                               "alongside": True, "ahead": False}]},
        "onboard": {"number": "13", "name": "K. Sato", "color": colors[0], "cls": "Hypercar", "rpmMax": 9000,
                    "ahead": "#10 +0.4"},
        "quali": {"number": "13", "name": "K. Sato", "color": colors[0], "position": "P3", "lapStart": 0.0,
                  "now": 61.4, "running": True, "best": "1:34.902", "target": "1:34.511", "targetLabel": tr("Pole"),
                  "delta": "-0.124", "deltaTone": "gain", "status": tr("Improving"),
                  "sectors": [{"text": "31.204", "tone": "fastest"}, {"text": "30.019", "tone": "gain"},
                              {"text": "-", "tone": ""}]},
        "map": {"track": "", "yellow": -1, "cars": {}, "sectors": [0.3, 0.65], "yellowSectors": [False, True, False]},
        "grid": {"title": tr("Starting Grid"), "cars": grid},
        "event": {"track": "Circuit de la Sarthe", "logo": "", "session": tr("Race"),
                  "conditions": [tr("Air %1").replace("%1", "24°C"), tr("Track %1").replace("%1", "33°C")],
                  "forecast": [{"label": tr("Start"), "sky": "Clear", "temperature": "24°C", "rain": "0%", "wet": False},
                               {"label": "50%", "sky": "Light clouds", "temperature": "26°C", "rain": "10%",
                                "wet": False},
                               {"label": tr("Finish"), "sky": "Rain", "temperature": "21°C", "rain": "60%",
                                "wet": True}],
                  "schedule": [[tr("Session length"), "6:00:00"], [tr("Remaining"), "2:41:07"]]},
        "results": {"title": tr("Classification"), "subtitle": tr("Lap %1").replace("%1", "42"), "rows": rows},
        "champ": {"title": "Endurance Cup", "subtitle": "Hypercar", "rows": champ},
        "message": {"id": 1, "title": tr("Race control"), "text": tr("Red flag: restart in 10 minutes")},
        "countdown": {"label": tr("Race starts in"), "endsAt": 0, "seconds": 299},
        "brand": {"name": "Endurance Cup · Round 3", "logo": "", "sponsors": [],
                  "names": ["Sponsor A", "Sponsor B", "Sponsor C"]},
        "labels": demo_labels(),
    }


def demo_labels() -> dict[str, Any]:
    from .i18n import tr

    return labels(tr)


def labels(tr) -> dict[str, Any]:
    """Texts of the graphics page in app language"""
    from .i18n import tr_overlay

    return {
        "overall": tr("Overall"), "pit": tr("Pit").upper(), "replay": tr("Replay").upper(),
        "garage": tr_overlay("GAR"), "dnf": tr_overlay("DNF"), "dq": tr_overlay("DQ"),  # tower status, as overlays
        "alongside": tr("Alongside").upper(), "pen": tr("PEN"), "laps": tr("Laps"), "gap": tr("Gap"),
        "best": tr("Best"), "pits": tr("Pit Stops"), "points": tr("Points"), "lap": tr("Lap"), "gear": tr("Gear"),
        "throttle": tr("Throttle"), "brake": tr("Brake"), "energy": tr("Energy"), "fastestTag": tr("FL"),
        "save": tr("Save"), "reset": tr("Reset"), "resetAll": tr("Reset All"), "saved": tr("Layout saved"),
        "undo": tr("Undo"), "preset": tr("Layout"),
        "editHint": tr("Drag a graphic to move it, mouse wheel to resize it, double click: back to its place.") + "  "
        + tr("Arrows: move by one pixel, Ctrl+Z: undo, H: hide these bars"),
        "notSaved": tr("Layout not saved"), "neutral": "N", "reverse": "R",
        "presets": {"": tr("Default"), "pre": tr("Pre-race"), "race": tr("Race"), "post": tr("Post-race")},
        "names": {
            "tower": tr("Standings tower"), "card": tr("Driver Card"), "battle": tr("Battle"),
            "train": tr("Battle train"), "banners": tr("Banners"), "pitradar": tr("Pit radar"), "replay": tr("Replay"),
            "clock": tr("Session clock & weather"), "onboard": tr("Onboard"), "quali": tr("Qualifying"),
            "map": tr("Track Map"), "grid": tr("Starting Grid"), "event": tr("Event card"),
            "results": tr("Classification"), "champ": tr("Championship"), "message": tr("Message"),
            "countdown": tr("Countdown"), "logo": tr("League logo"), "sponsors": tr("Sponsors"),
        },
    }
