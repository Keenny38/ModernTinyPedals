"""Startup cost ratchet: modules imported before the main window opens (python -X importtime)

Imports of app start (main, loader, main window) are measured in a new interpreter. Pages, overlays and
services load when first used: one imported at startup by mistake fails here, as does a large growth of
startup imports or of their import time. Lower the ratchets when startup gets lighter.
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STARTUP_IMPORTS = "import neopedal.main; from neopedal import loader; from neopedal.ui.app import AppWindow"
# App modules imported at startup (140 on 2026-10-20): ratchet, a few more allowed before failing
MAX_APP_MODULES = 150
# Import time of app modules at startup, best of runs (about 0.2 s on a desktop, 2026-10-20): fails only on
# a large regression, as test computers can be slow or busy
MAX_APP_IMPORT_SECONDS = 1.5
RUNS = 3
# Loaded when first used, never at startup: tool & analysis pages, overlays, services, QML & charts
NOT_AT_STARTUP = (
    "neopedal.ui.quick",
    "neopedal.ui.lap_viewer",
    "neopedal.ui.driver_stats_viewer",
    "neopedal.ui.race_calculator",
    "neopedal.ui.broadcast_director",
    "neopedal.web_dashboard",
    "neopedal.stream_overlay",
    "neopedal.stream_director",
    "neopedal.command_server",
    "neopedal.bug_report",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtCharts",
    "PySide6.QtMultimedia",
    "PySide6.QtNetwork",
    "numpy",
)
# Overlays: package & shared parts only (each overlay imported once enabled)
OVERLAY_PARTS = ("neopedal.widget", "neopedal.widget._modern", "neopedal.widget._style")
IMPORT_LINE = re.compile(r"import time:\s+(\d+) \|\s+\d+ \|\s*(\S+)")


def startup_imports() -> dict[str, float]:
    """Module name: own import time (seconds) of app start, in a new interpreter"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", STARTUP_IMPORTS],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=True,
    )
    modules = {}
    for line in result.stderr.splitlines():
        match = IMPORT_LINE.match(line)
        if match:
            modules[match[2]] = int(match[1]) / 1_000_000
    assert "neopedal.ui.app" in modules, result.stderr[-2000:]
    return modules


def app_import_seconds(modules: dict[str, float]) -> float:
    """Own import time of app modules, version excepted (runs git describe from a source checkout only)"""
    return sum(seconds for name, seconds in modules.items()
               if name.startswith("neopedal") and name != "neopedal.version")


def test_startup_imports_stay_light():
    runs = [startup_imports() for _ in range(RUNS)]
    modules = runs[0]
    lazy = [name for name in modules if any(name == prefix or name.startswith(f"{prefix}.") for prefix in NOT_AT_STARTUP)]
    assert not lazy, f"imported at startup, should load when first used: {sorted(lazy)}"
    overlays = [name for name in modules if name.startswith("neopedal.widget") and name not in OVERLAY_PARTS]
    assert not overlays, f"overlays imported at startup: {sorted(overlays)}"
    app_modules = [name for name in modules if name.split(".")[0] == "neopedal"]
    assert len(app_modules) <= MAX_APP_MODULES, (
        f"{len(app_modules)} app modules imported at startup (ratchet {MAX_APP_MODULES})")
    seconds = min(app_import_seconds(run) for run in runs)
    assert seconds <= MAX_APP_IMPORT_SECONDS, f"app modules took {seconds:.2f} s to import at startup"
