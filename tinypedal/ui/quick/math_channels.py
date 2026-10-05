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
Math channels of lap viewer: channels derived from recorded ones by an expression (no Qt)

Expression over channel names: + - * / ( ), abs(x), min(a, b...), max(a, b...), d(x) (change per second),
numbers & constants (pi, g, deg). Python's own parser builds the syntax tree, then nodes are evaluated one by
one from a whitelist: never eval. Anything else (attribute, subscript, other call, comparison, power...) is
refused. Values are evaluated over every sample of a lap (lists), single numbers where nothing varies.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

MATH_PREFIX = "math:"  # channel column of a math channel: "math:<name>" (lap_viewer.MATH_PREFIX, module without Qt)
MAX_EXPRESSION = 300  # characters of an expression
MAX_NODES = 120  # syntax tree nodes (deep nesting refused before evaluation)
MAX_NAME = 40  # characters of a math channel name
MAX_CHANNELS = 24  # math channels kept in viewer settings
CONSTANTS = {"pi": math.pi, "g": 9.80665, "deg": 180.0 / math.pi}
FUNCTIONS = ("abs", "min", "max", "d")
YAW_RATE = "yaw_rate"  # computed input: car heading change (radians per second), from recorded yaw
PRESETS = (  # name, expression, unit
    # Steering lock 20° at the wheels & wheelbase 2.7 m: edit them to match your car.
    # Positive: more steering than yaw rate needs (understeer), negative: oversteer
    ("Understeer Angle", "abs(steering) * 20 - abs(yaw_rate) * 2.7 / max(speed_kph / 3.6, 5) * deg", "°"),
    ("Brake Release Rate", "max(-d(brake), 0) * 100", "%/s"),
    ("Throttle Application Rate", "max(d(throttle), 0) * 100", "%/s"),
)
_name_pattern = re.compile(rf"^[^\x00-\x1f|:\\]{{1,{MAX_NAME}}}$")

Value = float | list[float]  # value of an expression part: same at every sample, or one per sample


class MathChannel(NamedTuple):
    """Math channel of viewer settings"""

    name: str
    expression: str
    unit: str = ""

    @property
    def column(self) -> str:
        return f"{MATH_PREFIX}{self.name}"


class MathError(ValueError):
    """Expression refused: message tells why (English, translated by page)"""


def parse_expression(expression: str) -> ast.Expression:
    """Syntax tree of expression, only whitelisted nodes, raises MathError"""
    text = expression.strip()
    if not text:
        raise MathError("Empty expression")
    if len(text) > MAX_EXPRESSION:
        raise MathError("Expression too long")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        raise MathError("Syntax error") from error
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise MathError("Expression too long")
    for node in nodes:
        check_node(node)
    return tree


def check_node(node: ast.AST):
    """Refuse any node outside the whitelist"""
    if isinstance(node, (ast.Expression, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)):
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            raise MathError("Not allowed: only + - * /")
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd)):
            raise MathError("Not allowed: only + - * /")
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise MathError("Not allowed: only numbers")
        return
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
            raise MathError("Not allowed: only abs, min, max & d functions")
        count = len(node.args)
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            raise MathError("Not allowed: only abs, min, max & d functions")
        if node.func.id in ("abs", "d") and count != 1:
            raise MathError(f"{node.func.id}() takes one value")
        if node.func.id in ("min", "max") and count < 1:
            raise MathError(f"{node.func.id}() takes one value or more")
        return
    raise MathError("Not allowed: only channels, numbers, + - * / abs min max d")


def input_names(tree: ast.Expression) -> list[str]:
    """Channel names used by expression (functions & constants left out), in expression order"""
    names: list[str] = []
    calls = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in calls and node.id not in CONSTANTS and node.id not in names:
            names.append(node.id)
    return names


def name_error(name: str, taken: Sequence[str]) -> str:
    """Why math channel name is refused, "" if fine (taken: names of other math channels)"""
    if not name.strip() or name != name.strip():
        return "Name needed"
    if not _name_pattern.match(name):
        return "Name too long or with | : \\ characters"
    if name.lower() in (other.lower() for other in taken):
        return "Name already used"
    return ""


def expression_error(expression: str, known: Callable[[str], bool] | None = None) -> str:
    """Why expression is refused, "" if fine (known: whether a channel name exists, None: not checked)"""
    try:
        tree = parse_expression(expression)
    except MathError as error:
        return str(error)
    if known is not None:
        unknown = [name for name in input_names(tree) if not known(name)]
        if unknown:
            return f"Unknown channel: {unknown[0]}"
    return ""


def derivative(values: Sequence[float], times: Sequence[float]) -> list[float]:
    """Change per second at each sample (centered), one-sided at lap start & end"""
    count = min(len(values), len(times))
    result = [0.0] * count
    for index in range(count):
        before, after = max(index - 1, 0), min(index + 1, count - 1)
        span = times[after] - times[before]
        if span > 0:
            result[index] = (values[after] - values[before]) / span
    return result


def unwrapped(angles: Sequence[float]) -> list[float]:
    """Angles (radians) without jumps of a full turn (heading crossing ±pi)"""
    result: list[float] = []
    offset = 0.0
    previous = None
    for angle in angles:
        if previous is not None:
            step = angle - previous
            if step > math.pi:
                offset -= math.tau
            elif step < -math.pi:
                offset += math.tau
        result.append(angle + offset)
        previous = angle
    return result


class Evaluator:
    """Expression over samples of one lap: inputs by name (same sample count), lap time of each sample"""

    def __init__(self, inputs: dict[str, Sequence[float]], times: Sequence[float], count: int):
        self.inputs = inputs
        self.times = times
        self.count = count

    def run(self, tree: ast.Expression) -> list[float]:
        """Value at each sample, infinite values (huge numbers) as 0: line stays drawable"""
        value = self.value(tree.body)
        values = value if isinstance(value, list) else [value] * self.count
        return [item if math.isfinite(item) else 0.0 for item in values]

    def value(self, node: ast.AST) -> Value:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):  # only numbers (see check_node)
                return float(node.value)
            raise MathError("Not allowed: only numbers")
        if isinstance(node, ast.Name):
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            values = self.inputs.get(node.id)
            if values is None:
                raise MathError(f"Unknown channel: {node.id}")
            return [float(value) for value in values]
        if isinstance(node, ast.UnaryOp):
            operand = self.value(node.operand)
            if isinstance(node.op, ast.USub):
                return [-value for value in operand] if isinstance(operand, list) else -operand
            return operand
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.value(node.left), self.value(node.right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self.call(node.func.id, [self.value(arg) for arg in node.args])
        raise MathError("Not allowed: only channels, numbers, + - * / abs min max d")

    @staticmethod
    def operate(op: ast.operator, first: float, second: float) -> float:
        if isinstance(op, ast.Add):
            return first + second
        if isinstance(op, ast.Sub):
            return first - second
        if isinstance(op, ast.Mult):
            return first * second
        return first / second if second else 0.0  # division by zero: 0 (line stays drawable)

    def binary(self, op: ast.operator, left: Value, right: Value) -> Value:
        if isinstance(left, list) and isinstance(right, list):
            return [self.operate(op, first, second) for first, second in zip(left, right)]
        if isinstance(left, list):
            return [self.operate(op, first, right) for first in left]  # type: ignore[arg-type]
        if isinstance(right, list):
            return [self.operate(op, left, second) for second in right]
        return self.operate(op, left, right)

    def call(self, name: str, args: list[Value]) -> Value:
        if name == "abs":
            value = args[0]
            return [abs(item) for item in value] if isinstance(value, list) else abs(value)
        if name == "d":
            value = args[0]
            return derivative(value, self.times) if isinstance(value, list) else 0.0
        pick = min if name == "min" else max
        if len(args) == 1:  # lowest or highest value over lap
            value = args[0]
            return pick(value, default=0.0) if isinstance(value, list) else value
        lists = [arg for arg in args if isinstance(arg, list)]
        numbers = [arg for arg in args if not isinstance(arg, list)]
        if not lists:
            return pick(numbers)  # type: ignore[type-var]
        return [pick(*items, *numbers) for items in zip(*lists)]


def evaluate(expression: str, inputs: dict[str, Sequence[float]], times: Sequence[float], count: int) -> list[float]:
    """Values of expression at each of count samples, raises MathError"""
    return Evaluator(inputs, times, count).run(parse_expression(expression))


def parse_channels(saved) -> list[MathChannel]:
    """Math channels of viewer settings, invalid entries left out"""
    if not isinstance(saved, list):
        return []
    channels: list[MathChannel] = []
    for item in saved[:MAX_CHANNELS]:
        if not isinstance(item, dict):
            continue
        name, expression, unit = item.get("name"), item.get("expression"), item.get("unit", "")
        if not isinstance(name, str) or not isinstance(expression, str) or not isinstance(unit, str):
            continue
        if name_error(name, [channel.name for channel in channels]) or expression_error(expression):
            continue
        channels.append(MathChannel(name, expression.strip(), unit[:12]))
    return channels


def saved_channels(channels: Sequence[MathChannel]) -> list[dict]:
    """Math channels as saved in viewer settings"""
    return [{"name": channel.name, "expression": channel.expression, "unit": channel.unit} for channel in channels]
