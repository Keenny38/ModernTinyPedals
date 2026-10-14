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
Penalties of each driver from the game results stream (Le Mans Ultimate), without Qt

The game writes every penalty in its results stream (shared memory, then results file), one line each:

    <Penalty Driver="Name" ID="54" Penalty="Stop/Go" Time="10" Laps="0" Reason="Speeding In Pitlane" et="25.5">
        Name received Stop/Go penalty, 10s, 0laps for Speeding In Pitlane. Result: penalties=1, 1st=Stop/Go,10s
    <Penalty et="957.9">Name served 1st Drive Thru penalty, result: penalties=0, 1st=Drive Thru,10s
    <Penalty et="600.2">Name finished before serving penalty, added 35 seconds to totalET
    <Penalty Driver="Name" ID="8" Penalty="Disqualify" et="986.5">Disqualify

"Result: penalties=N, 1st=Kind,Ts" tells penalties still to serve after the line and the first one of them.
"""

from __future__ import annotations

import html
import re
from typing import NamedTuple

ATTRIBUTE = re.compile(rb'(\w+)="([^"]*)"')
RESULT = re.compile(rb"[Rr]esult: penalties=(\d+)(?:, 1st=([^,<]+),(\d+)s)?")
ADDED = re.compile(rb"added (\d+) seconds")
NAME_END = (b" received ", b" served ", b" finished before serving")
DISQUALIFY = "Disqualify"


class Penalty(NamedTuple):
    """Penalties of a driver: to serve (count, first one's kind & time in seconds), seconds added to race time
    (not served before finish), disqualified"""

    pending: int = 0
    kind: str = ""  # "Drive Thru", "Stop/Go"...
    seconds: int = 0
    added: int = 0
    disqualified: bool = False


NO_PENALTY = Penalty()


def _text(value: bytes) -> str:
    return html.unescape(value.decode("utf-8", "replace")).strip()


def parse_line(line: bytes) -> tuple[bytes, Penalty | None, int, bool] | None:
    """Driver name (bytes as shared memory, entities decoded), penalties to serve after line (None if line
    does not tell), seconds added, disqualified; None if not a penalty line or driver unknown"""
    if not line.startswith(b"<Penalty"):
        return None
    head, _, rest = line.partition(b">")
    text = rest.partition(b"<")[0]
    attributes = dict(ATTRIBUTE.findall(head))
    driver = attributes.get(b"Driver", b"")
    if not driver:
        ends = [index for index in (text.find(end) for end in NAME_END) if index > 0]
        if not ends:
            return None
        driver = text[:min(ends)].strip()
    driver = html.unescape(driver.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")
    disqualified = attributes.get(b"Penalty", b"") == DISQUALIFY.encode()
    result = RESULT.search(text)
    state = None
    if result is not None:
        count = int(result.group(1))
        kind = _text(result.group(2)) if result.group(2) and count else ""
        if kind == "None":
            kind = ""
        seconds = int(result.group(3)) if result.group(3) and count else 0
        state = Penalty(count, kind, seconds)
    added = ADDED.search(text)
    return driver, state, int(added.group(1)) if added else 0, disqualified


def apply_line(current: Penalty, state: Penalty | None, added: int, disqualified: bool) -> Penalty:
    """Penalties of driver after a stream line (see parse_line)"""
    if state is not None:
        current = current._replace(pending=state.pending, kind=state.kind, seconds=state.seconds)
    if added:
        current = current._replace(pending=0, kind="", seconds=0, added=current.added + added)
    if disqualified:
        current = current._replace(disqualified=True)
    return current


def kind_code(kind: str) -> str:
    """Two letter code of penalty kind: DT (drive through), SG (stop & go), TP (time added), else initials"""
    key = kind.casefold().replace(" ", "").replace("-", "")
    if key.startswith("drive"):
        return "DT"
    if key.startswith("stop"):
        return "SG"
    if key.startswith("time"):
        return "TP"
    words = [word for word in re.split(r"[\s/&-]+", kind) if word]
    return "".join(word[0] for word in words[:2]).upper() or "PN"


def short_label(penalty: Penalty, count: int = 0) -> str:
    """Two letter label (classic design): DQ, first penalty to serve (DT, SG), else "" """
    if penalty.disqualified:
        return "DQ"
    if penalty.pending or count:
        return kind_code(penalty.kind) if penalty.kind else "PN"
    return ""


def count_text(count: int, penalty: Penalty) -> str:
    """Pit stops column of classic design (2 letters): penalty (DQ, DT, SG...) if any, else pit stops (count
    negative: penalties to serve as game counts them)"""
    return short_label(penalty, -count if count < 0 else 0) or f"{count}"


def label(penalty: Penalty, count: int = 0) -> str:
    """Penalty label (modern design): DQ, first penalty to serve with stop time (DT, SG10), number to serve when
    several (SG x2), seconds added at finish (+35s), else "" (count: penalties to serve as game counts them)"""
    if penalty.disqualified:
        return "DQ"
    pending = max(penalty.pending, count)
    if pending:
        if not penalty.kind:
            return "PEN" if pending == 1 else f"PEN\u00d7{pending}"
        code = kind_code(penalty.kind)
        if pending > 1:
            return f"{code}\u00d7{pending}"
        if code == "TP":  # time added to race time
            return f"+{penalty.seconds}s"
        return f"{code}{penalty.seconds}" if code == "SG" and penalty.seconds else code
    if penalty.added:
        return f"+{penalty.added}s"
    return ""
