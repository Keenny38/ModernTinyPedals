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
Release build self test: run.py --self-test [REPORT_FILE] (tinypedal.exe --self-test report.txt)

Checks what a frozen build can miss, without game, settings window or overlays:
data files next to executable, modules imported by name (widgets, modern designs, tools),
bundled QML modules (every page compiled) and worker processes (lap viewer jobs).
Exit code 0 if every check passed. Report is written to REPORT_FILE as well,
since the windowed executable has no console.
"""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Callable
from glob import glob

WORKER_TIMEOUT = 120  # seconds, first spawn of a frozen worker unpacks nothing but can be slow on CI


def check_data_files() -> str:
    """Files loaded by relative path from executable folder"""
    from .const_file import FontFile

    required = ("LICENSE.txt", "images/icon.png", "docs/licenses", "CHANGELOG.md", "CHANGELOG.fr.md")  # notes of What's New
    missing = [path for path in required if not os.path.exists(path)]
    if not glob(f"{FontFile.FOLDER}*.ttf"):
        missing.append(f"{FontFile.FOLDER}*.ttf")
    if missing:
        raise FileNotFoundError(", ".join(missing))
    return "data files found"


def check_modules() -> str:
    """Widgets, modern designs, data modules & tool pages, all imported by name at runtime"""
    from importlib import import_module

    from . import module, widget
    from .template.widget.modern import MODERN_DESIGNS
    from .ui.tools_view import TOOL_SECTIONS
    from .widget._modern import modern_module

    count = len(widget.__all__) + len(module.__all__)
    for name in sorted(MODERN_DESIGNS):
        modern_module(name)
        count += 1
    for _, tools in TOOL_SECTIONS:
        for _, _, dialog_path in tools:
            module_name, class_name = dialog_path.split(".")
            getattr(import_module(f"tinypedal.ui.{module_name}"), class_name)
            count += 1
    return f"{count} modules imported"


def check_qml_pages() -> str:
    """Compile every QML page: fails if a QML module is missing from the build"""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from .ui.quick import QML_FOLDER, register_types

    register_types()
    engine = QQmlEngine()
    engine.addImportPath(QML_FOLDER)
    files = sorted(glob(os.path.join(QML_FOLDER, "*.qml")))
    if not files:
        raise FileNotFoundError(QML_FOLDER)
    errors: list[str] = []
    for file in files:
        component = QQmlComponent(engine, QUrl.fromLocalFile(file))
        if component.isError():
            errors.extend(error.toString() for error in component.errors())
    if errors:
        raise RuntimeError("\n".join(errors))
    return f"{len(files)} QML pages compiled"


def check_worker_process() -> str:
    """Spawn worker process, as lap viewer jobs do (needs multiprocessing & freeze_support)"""
    import concurrent.futures
    import multiprocessing

    with concurrent.futures.ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
        worker_pid = pool.submit(os.getpid).result(timeout=WORKER_TIMEOUT)
    if worker_pid == os.getpid():
        raise RuntimeError("job ran in main process")
    return "worker process answered"


CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("Data files", check_data_files),
    ("Modules", check_modules),
    ("QML pages", check_qml_pages),
    ("Worker process", check_worker_process),
)


def run_self_test(report_file: str = "") -> int:
    """Run all checks, return exit code (0 passed, 1 failed)"""
    from PySide6.QtWidgets import QApplication

    from .version import __version__

    app = QApplication.instance() or QApplication(sys.argv[:1])  # UI modules read font metrics at import
    lines = [f"Modern Tiny Pedals {__version__} self test", f"Python {sys.version.split()[0]}", ""]
    failed = 0
    for title, check in CHECKS:
        try:
            lines.append(f"PASS {title}: {check()}")
        except Exception:  # every check reported, whatever failed
            failed += 1
            lines.append(f"FAIL {title}:\n{traceback.format_exc()}")
    lines.append("")
    lines.append(f"{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    report = "\n".join(lines) + "\n"
    if sys.stdout is not None:  # no console in windowed executable
        sys.stdout.write(report)
    if report_file:
        with open(report_file, "w", encoding="utf-8") as file:
            file.write(report)
    del app
    return 1 if failed else 0
