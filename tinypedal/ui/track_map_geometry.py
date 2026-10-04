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
Track map geometry at a position: curve section, osculating circle, curve & length grades, slope

Map nodes: coordinates (x, y) & distances (distance, elevation) of track map file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from .. import calculation as calc


class CurveInfo(NamedTuple):
    """Curve & slope of track section starting at a node"""

    section: list[tuple[float, float]]  # node coordinates
    center: tuple[float, float]  # osculating circle center
    radius: float
    angle: float  # degrees
    yaw: float  # radians, driving direction at node
    direction: int  # -1 left, 1 right, 0 straight
    length: float  # meters
    height_delta: float  # meters
    slope_percent: float  # fraction
    slope_angle: float  # degrees


def section_indices(total_nodes: int, section_nodes: int, seek_index: int) -> list[int]:
    """Node indices of section starting at seek index (wraps around lap end)"""
    count = int(min(section_nodes, total_nodes - 2))
    return [(seek_index + offset) % total_nodes for offset in range(max(count, 0))]


def section_length(
    map_length: float, total_nodes: int, section_nodes: int, seek_index: int, raw_dists: Sequence) -> float:
    """Length of section from selected nodes"""
    max_nodes = int(min(section_nodes, total_nodes - 2))
    end_index = seek_index + max_nodes
    if end_index >= total_nodes:
        return map_length - raw_dists[seek_index][0] + raw_dists[end_index - total_nodes][0]
    return raw_dists[end_index][0] - raw_dists[seek_index][0]


def section_height_delta(total_nodes: int, section_nodes: int, seek_index: int, raw_dists: Sequence) -> float:
    """Height delta of section from selected nodes"""
    max_nodes = int(min(section_nodes, total_nodes - 2))
    end_index = seek_index + max_nodes
    if end_index >= total_nodes:
        end_index -= total_nodes
    return raw_dists[end_index][1] - raw_dists[seek_index][1]


def curve_description(arc_radius: float, turn_direct: int, curve_grade: Sequence) -> str:
    """Curve description: "Right 3", "Left Hairpin", "Straight" """
    if arc_radius >= curve_grade[-1][0]:
        return curve_grade[-1][1]
    direct_desc = "Right" if turn_direct > 0 else "Left"
    curve_desc = calc.select_grade(curve_grade, arc_radius)
    return f"{direct_desc} {curve_desc}"


def node_at(raw_dists: Sequence, distance: float) -> int:
    """Node index at track distance"""
    return calc.binary_search_higher_column(raw_dists, distance, 0, len(raw_dists) - 1)


def curve_at(raw_coords: Sequence, raw_dists: Sequence, map_length: float, section_nodes: int,
             seek_index: int) -> CurveInfo:
    """Curve of section starting at node: circle through first, middle & last section nodes"""
    total = len(raw_coords)
    section = [tuple(raw_coords[index]) for index in section_indices(total, section_nodes, seek_index)]
    point_one, point_sec = section[0], section[1]
    point_mid, point_end = section[len(section) // 2], section[-1]
    center = calc.tri_coords_circle_center(*point_one, *point_mid, *point_end)
    radius = calc.distance(point_one, center)
    angle = calc.quad_coords_angle(center, point_one, point_mid, point_end)
    yaw = calc.oriyaw(point_sec[1] - point_one[1], point_sec[0] - point_one[0])
    direction = calc.turning_direction(yaw, *point_one, *point_end)
    length = section_length(map_length, total, section_nodes, seek_index, raw_dists)
    height = section_height_delta(total, section_nodes, seek_index, raw_dists)
    return CurveInfo(
        section,  # type: ignore[arg-type]
        center, radius, angle, yaw, direction, length, height,
        calc.slope_percent(height, length), calc.slope_angle(height, length),
    )


def config_grades(config: dict[str, Any]) -> dict[str, list[tuple[float, str]]]:
    """Curve, length & slope grades of track map viewer config, sorted"""
    curves = [
        (config["curve_grade_hairpin"], "Hairpin"),
        *[(config[f"curve_grade_{index}"], str(index)) for index in range(1, 9) if config[f"curve_grade_{index}"] >= 0],
        (config["curve_grade_straight"], "Straight"),
    ]
    lengths = [
        (config["length_grade_short"], "Short"),
        (config["length_grade_normal"], "Normal"),
        (config["length_grade_long"], "Long"),
        (config["length_grade_very_long"], "Very Long"),
        (config["length_grade_extra_long"], "Extra Long"),
        (config["length_grade_extremely_long"], "Extremely Long"),
    ]
    slopes = [
        (config["slope_grade_flat"], "Flat"),
        (config["slope_grade_gentle"], "Gentle"),
        (config["slope_grade_moderate"], "Moderate"),
        (config["slope_grade_steep"], "Steep"),
        (config["slope_grade_extreme"], "Extreme"),
        (config["slope_grade_cliff"], "Cliff"),
    ]
    return {"curve": sorted(curves), "length": sorted(lengths), "slope": sorted(slopes)}
