"""Classic & modern designs: options shown on the Overlay Options page for a design are the ones it reads

For each overlay & design, option names are looked up in the code of the design (its widget module and
the widget & template modules it imports, plus data modules reading overlay options): an option shown for
a design but never named by its code does nothing there (was: modern only columns ordered on classic page).
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from neopedal.setting import cfg
from neopedal.template.setting_widget import WIDGET_DEFAULT
from neopedal.template.widget.modern import CLASSIC_LAYOUT_OPTION, MODERN_DESIGN_OPTIONS
from neopedal.widget._modern import COMMON_OPTIONS, design_option_keys, modern_module

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "neopedal"
FOLLOWED = ("neopedal.widget", "neopedal.template.widget")  # imports followed from a design module
DATA_MODULES = tuple(sorted((PACKAGE / "module").rglob("*.py")))  # read options of overlays too (relative)
DESIGNS = [(name, False) for name in WIDGET_DEFAULT] + [(name, True) for name in MODERN_DESIGN_OPTIONS]


@cache
def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def module_file(module: str) -> Path | None:
    base = ROOT.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.exists():
            return path
    return None


def imported_modules(path: Path) -> list[str]:
    package = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
    modules = []
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            modules.append(module)
            modules.extend(f"{module}.{alias.name}" for alias in node.names)  # submodules imported by name
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


@cache
def design_files(path: Path) -> frozenset[Path]:
    """Module & the widget/template modules it imports (transitive)"""
    seen = {path}
    todo = [path]
    while todo:
        for module in imported_modules(todo.pop()):
            if not module.startswith(FOLLOWED):
                continue
            found = module_file(module)
            if found is not None and found not in seen:
                seen.add(found)
                todo.append(found)
    return frozenset(seen)


@cache
def references(files: frozenset[Path]) -> tuple[frozenset[str], tuple[re.Pattern, ...]]:
    """String literals, and patterns of names built at run time (f-strings with a fixed part, prefixes)"""
    literals: set[str] = set()
    patterns: list[re.Pattern] = []
    for path in files:
        for node in ast.walk(parsed(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
            elif isinstance(node, ast.JoinedStr):
                if sum(len(value.value) for value in node.values if isinstance(value, ast.Constant)) >= 5:
                    patterns.append(re.compile("^" + "".join(
                        re.escape(value.value) if isinstance(value, ast.Constant) else r"\w+"
                        for value in node.values) + "$"))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "startswith" and node.args and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str) and len(node.args[0].value) >= 5):
                patterns.append(re.compile("^" + re.escape(node.args[0].value)))
    return frozenset(literals), tuple(patterns)


def shown_options(name: str, modern: bool) -> list[str]:
    """Options the page shows for the design"""
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    values = dict(cfg.user.setting[name], **{CLASSIC_LAYOUT_OPTION: not modern})
    design = SimpleNamespace(user=SimpleNamespace(config=cfg.user.config, setting={name: values}))
    return design_option_keys(design, name, list(WIDGET_DEFAULT[name]))


@pytest.mark.parametrize(("name", "modern"), DESIGNS,
                         ids=[f"{name}-{'modern' if modern else 'classic'}" for name, modern in DESIGNS])
def test_shown_options_read_by_design(ui_env, name, modern):
    module = PACKAGE / "widget" / ("_modern" if modern else "") / f"{name}.py"
    if not module.exists():
        pytest.skip("plugin overlay")
    files = design_files(module) | design_files(PACKAGE / "widget" / "_base.py") | frozenset(DATA_MODULES)
    literals, patterns = references(files)
    unread = [key for key in shown_options(name, modern) if key not in COMMON_OPTIONS
              and key not in literals and not any(pattern.match(key) for pattern in patterns)]
    assert not unread, f"shown for {'modern' if modern else 'classic'} design, never read by it: {unread}"


@pytest.mark.parametrize("name", sorted(MODERN_DESIGN_OPTIONS))
def test_modern_options_exist(name):
    """Options listed by modern design (shown on its page) are options of the overlay"""
    missing = [key for key in modern_module(name).Realtime.options if key not in WIDGET_DEFAULT[name]]
    assert not missing, f"modern {name} lists unknown options: {missing}"


@pytest.mark.parametrize("name", sorted(MODERN_DESIGN_OPTIONS))
def test_modern_only_options_listed_by_modern_design(name):
    """Modern only options (hidden on classic page) are shown on modern page (else shown by none)"""
    shown = set(modern_module(name).Realtime.options)
    missing = [key for key in MODERN_DESIGN_OPTIONS[name] if key not in shown]
    assert not missing, f"modern only options of {name} shown by neither design: {missing}"
