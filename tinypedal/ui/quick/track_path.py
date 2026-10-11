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
Track path of a map: distance along the track of a map position, position of a distance

Cars of the Game Replays map are placed on the track at their reported position, then moved along the track
(not in a straight line) between game answers.
"""

from __future__ import annotations

from bisect import bisect_right
from math import hypot

SEARCH_SPAN = 120  # segments searched around last segment of a car before searching the whole path


class TrackPath:
    """Polyline of track (map coordinates), closed if start & end join"""

    __slots__ = ("xs", "ys", "s", "length", "closed")

    def __init__(self, xs: list[float], ys: list[float], closed: bool):
        self.xs = list(xs)
        self.ys = list(ys)
        self.closed = closed
        distances = [0.0]
        for index in range(1, len(self.xs)):
            distances.append(distances[-1] + hypot(self.xs[index] - self.xs[index - 1],
                                                   self.ys[index] - self.ys[index - 1]))
        self.s = distances
        closing = hypot(self.xs[0] - self.xs[-1], self.ys[0] - self.ys[-1]) if closed and self.xs else 0.0
        self.length = distances[-1] + closing

    @property
    def segments(self) -> int:
        return len(self.xs) if self.closed else len(self.xs) - 1

    def _segment(self, index: int) -> tuple[float, float, float, float, float]:
        """Start point, end point & start distance of segment"""
        end = (index + 1) % len(self.xs)
        return self.xs[index], self.ys[index], self.xs[end], self.ys[end], self.s[index]

    def project(self, x: float, y: float, hint: int = -1) -> tuple[float, float, int]:
        """Nearest point of path: (distance along path, distance to path, segment), around hint segment first"""
        count = self.segments
        if count <= 0:
            return 0.0, float("inf"), -1
        if 0 <= hint < count:
            span = min(SEARCH_SPAN, count)
            candidates = range(hint - span // 2, hint - span // 2 + span)
            found = self._nearest(x, y, (index % count for index in candidates))
            if found[1] < 25.0:  # close to track near last place: kept
                return found
        return self._nearest(x, y, range(count))

    def _nearest(self, x: float, y: float, indexes) -> tuple[float, float, int]:
        best = (0.0, float("inf"), -1)
        for index in indexes:
            x1, y1, x2, y2, start = self._segment(index)
            dx, dy = x2 - x1, y2 - y1
            seg2 = dx * dx + dy * dy
            ratio = 0.0 if seg2 <= 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / seg2))
            px, py = x1 + dx * ratio, y1 + dy * ratio
            gap = hypot(x - px, y - py)
            if gap < best[1]:
                best = (start + ratio * seg2 ** 0.5, gap, index)
        return best

    def delta(self, start: float, end: float) -> float:
        """Distance from start to end along path, shortest way round on a closed path (signed)"""
        diff = end - start
        if self.closed and self.length > 0:
            diff = (diff + self.length / 2) % self.length - self.length / 2
        return diff

    def point(self, distance: float) -> tuple[float, float]:
        """Map position of distance along path (wrapped on a closed path, clamped otherwise)"""
        if self.closed and self.length > 0:
            distance %= self.length
        else:
            distance = max(0.0, min(distance, self.s[-1]))
        index = min(max(bisect_right(self.s, distance) - 1, 0), self.segments - 1 if self.segments > 0 else 0)
        x1, y1, x2, y2, start = self._segment(index)
        span = (self.s[index + 1] if index + 1 < len(self.s) else self.length) - start
        ratio = 0.0 if span <= 0 else (distance - start) / span
        return x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio
