"""Vectorized vertex builders (ui/quick/lines.py) give the same bytes as the former per point loops"""

import math
import random
import struct
from array import array

import pytest
from PySide6.QtGui import QColor

from tinypedal.ui.quick import lines
from tinypedal.ui.quick.lines import (
    COLORED_VERTEX,
    LINE_STRIP,
    LINES,
    TRIANGLE_STRIP,
    TRIANGLES,
    Vertices,
    _normals,
)


# Former implementations (reference)
def old_step_strip(xs, ys):
    count = min(len(xs), len(ys))
    if count < 2:
        return lines.line_strip(xs, ys)
    data = array("f")
    previous = ys[0]
    for x, y in zip(xs[:count], ys[:count]):
        data.extend((x, previous, x, y))
        previous = y
    return Vertices(data, count * 2, LINE_STRIP)


def old_segments(points):
    data = array("f")
    for line in points:
        data.extend(line)
    return Vertices(data, len(points) * 2, LINES)


def old_colored_band(xs, ys, colors, half_width, alphas=None):
    count = min(len(xs), len(ys), len(colors))
    if count < 2:
        return Vertices(bytearray(), 0, TRIANGLE_STRIP, True)
    data = bytearray(COLORED_VERTEX.size * count * 2)
    offset = 0
    alphas = alphas if alphas is not None else [1.0] * count
    for x, y, (nx, ny), color, alpha in zip(xs, ys, _normals(xs[:count], ys[:count]), colors, alphas):
        opacity = min(max(alpha, 0.0), 1.0)
        rgba = (round(color.red() * opacity), round(color.green() * opacity), round(color.blue() * opacity),
                round(255 * opacity))
        COLORED_VERTEX.pack_into(data, offset, x + nx * half_width, y + ny * half_width, *rgba)
        COLORED_VERTEX.pack_into(data, offset + COLORED_VERTEX.size, x - nx * half_width, y - ny * half_width, *rgba)
        offset += COLORED_VERTEX.size * 2
    return Vertices(data, count * 2, TRIANGLE_STRIP, True)


def old_merge_strips(strips):
    data = array("f")
    for strip in strips:
        source = strip.data
        for index in range(0, strip.vertex_count * 2 - 4, 2):
            data.extend(source[index:index + 6])
    return Vertices(data, len(data) // 2, TRIANGLES)


def old_range_band(xs, lows, highs):
    count = min(len(xs), len(lows), len(highs))
    data = array("f")
    for x, low, high in zip(xs[:count], lows[:count], highs[:count]):
        data.extend((x, low, x, high))
    return Vertices(data, count * 2 if count > 1 else 0, TRIANGLE_STRIP)


def old_area(xs, ys, base):
    count = min(len(xs), len(ys))
    data = array("f")
    for x, y in zip(xs[:count], ys[:count]):
        data.extend((x, base, x, y))
    return Vertices(data, count * 2 if count > 1 else 0, TRIANGLE_STRIP)


def same(new: Vertices, old: Vertices):
    assert bytes(new.data) == bytes(old.data)
    assert new.vertex_count == old.vertex_count
    assert new.mode == old.mode
    assert new.colored == old.colored


def values(rng, count, special=False):
    result = [rng.uniform(-5000.0, 5000.0) for _ in range(count)]
    if special and count:
        result[rng.randrange(count)] = math.nan
        result[rng.randrange(count)] = math.inf
        result[rng.randrange(count)] = 1e39  # beyond float32: inf
        result[rng.randrange(count)] = 7  # int
    return result


SIZES = [(0, 0), (1, 1), (2, 2), (3, 3), (2, 5), (5, 2), (0, 3), (17, 17), (500, 499), (1000, 1000)]


@pytest.mark.parametrize("sizes", SIZES)
@pytest.mark.parametrize("special", [False, True])
def test_step_strip_same_bytes(sizes, special):
    rng = random.Random(sum(sizes) + special)
    xs, ys = values(rng, sizes[0], special), values(rng, sizes[1], special)
    same(lines.step_strip(xs, ys), old_step_strip(xs, ys))
    same(lines.step_strip(tuple(xs), array("d", ys)), old_step_strip(tuple(xs), array("d", ys)))


@pytest.mark.parametrize("count", [0, 1, 2, 3, 250])
def test_segments_same_bytes(count):
    rng = random.Random(count)
    points = [tuple(values(rng, 4, special=True)) for _ in range(count)]
    same(lines.segments(points), old_segments(points))


@pytest.mark.parametrize("sizes", SIZES)
@pytest.mark.parametrize("special", [False, True])
def test_range_band_and_area_same_bytes(sizes, special):
    rng = random.Random(sum(sizes) * 3 + special)
    xs, lows = values(rng, sizes[0], special), values(rng, sizes[1], special)
    highs = values(rng, max(sizes[1] - 1, 0), special)
    same(lines.range_band(xs, lows, highs), old_range_band(xs, lows, highs))
    same(lines.range_band(xs, lows, lows), old_range_band(xs, lows, lows))
    for base in (0.0, -12.5, math.nan, 3):
        same(lines.area(xs, lows, base), old_area(xs, lows, base))


def strip_of(rng, count):
    xs, ys = values(rng, count), values(rng, count)
    return lines.band(xs, ys, rng.uniform(0.1, 30.0))


@pytest.mark.parametrize("counts", [[], [0], [1], [2], [3], [2, 3, 0, 40], [300, 2, 7]])
def test_merge_strips_same_bytes(counts):
    rng = random.Random(len(counts) * 11 + sum(counts))
    strips = [strip_of(rng, count) for count in counts]
    same(lines.merge_strips(strips), old_merge_strips(strips))
    # Raw strips: odd vertex counts, short data (slices cut at its end), NaN
    raw = [Vertices(array("f", values(rng, 2 * vertices, True)), vertices, TRIANGLE_STRIP)
           for vertices in (1, 2, 3, 4, 5, 9)]
    raw.append(Vertices(array("f", values(rng, 7)), 6, TRIANGLE_STRIP))  # data shorter than vertices
    raw.append(Vertices(array("f", values(rng, 30)), 4, TRIANGLE_STRIP))  # data longer than vertices
    same(lines.merge_strips(raw), old_merge_strips(raw))


@pytest.mark.parametrize("sizes", [(0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3), (5, 4, 6), (6, 6, 2),
                                   (200, 200, 200), (100, 99, 101)])
@pytest.mark.parametrize("alpha_mode", ["none", "random", "short", "long", "out_of_range"])
def test_colored_band_same_bytes(sizes, alpha_mode):
    rng = random.Random(sum(sizes) * 7 + len(alpha_mode))
    xs, ys = values(rng, sizes[0]), values(rng, sizes[1])
    colors = [QColor(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(sizes[2])]
    count = min(sizes)
    alphas = {
        "none": None,
        "random": [rng.random() for _ in range(count)],
        "short": [rng.random() for _ in range(max(count - 2, 0))],
        "long": [rng.random() for _ in range(count + 5)],
        "out_of_range": [rng.uniform(-2.0, 3.0) for _ in range(count)],
    }[alpha_mode]
    half = rng.uniform(0.5, 20.0)
    same(lines.colored_band(xs, ys, colors, half, alphas), old_colored_band(xs, ys, colors, half, alphas))


def test_colored_band_nan_position_same_bytes():
    xs, ys = [0.0, 1.0, math.nan, 3.0], [0.0, math.inf, 2.0, 1.0]
    colors = [QColor("red")] * 4
    same(lines.colored_band(xs, ys, colors, 1.0), old_colored_band(xs, ys, colors, 1.0))


def test_colored_band_record_layout():
    """Interleaved record: x, y little endian floats then premultiplied rgba"""
    band = lines.colored_band([0.0, 10.0], [0.0, 0.0], [QColor(200, 100, 50)] * 2, 1.0, [0.5, 1.0])
    first = struct.unpack_from("<ff4B", band.data, 0)
    assert first[:2] == (0.0, 1.0)
    assert first[2:] == (100, 50, 25, 128)
