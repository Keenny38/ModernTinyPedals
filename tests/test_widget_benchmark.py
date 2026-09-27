"""Widget performance benchmark (update + paint time), using app PerfMonitor

Run with: pytest -m benchmark
Each widget runs FRAMES update/paint cycles on changing telemetry (shared memory structs,
no game needed). Test fails if a widget frame is slower than FRAME_BUDGET_MS on average,
report is saved to "tests/_render/benchmark.json" (CI artifact) to compare runs.

Compare with previous report (fails if a widget got SLOWDOWN_FACTOR times slower):
    TINYPEDAL_BENCHMARK_BASELINE=old_benchmark.json pytest -m benchmark
"""

import json
import math
import os
import pkgutil
from importlib import import_module

import pytest
from PySide6.QtCore import QTimerEvent

from tests.test_readers import lmu_api
from tinypedal.perf_monitor import PerfMonitor
from tinypedal.setting import cfg
from tinypedal.userfile.json_setting import copy_setting

pytestmark = pytest.mark.benchmark

FRAMES = 40
# Generous budget: widgets update every 20-50 ms and share GUI thread with all other widgets
FRAME_BUDGET_MS = float(os.environ.get("TINYPEDAL_FRAME_BUDGET_MS", "15"))
SLOWDOWN_FACTOR = 3.0
SLOWDOWN_MIN_MS = 0.5  # ignore tiny absolute differences (timer noise)
BASELINE_FILE = os.environ.get("TINYPEDAL_BENCHMARK_BASELINE", "")
OUTPUT = os.path.join(os.path.dirname(__file__), "_render", "benchmark.json")
WIDGET_NAMES = sorted(
    module.name
    for module in pkgutil.iter_modules(import_module("tinypedal.widget").__path__)
    if not module.name.startswith("_")
)
RESULTS: dict[str, dict[str, float]] = {}


def load_baseline() -> dict[str, dict[str, float]]:
    if not BASELINE_FILE:
        return {}
    with open(BASELINE_FILE, encoding="utf-8") as file:
        return json.load(file)["widgets"]


BASELINE = load_baseline()


@pytest.fixture(scope="module")
def live_api():
    """Default settings, API reader on in-memory shared memory data"""
    from tinypedal.api_control import api
    from tinypedal.main import load_bundled_fonts

    load_bundled_fonts()
    cfg.default.set_default()
    backup = {name: getattr(cfg.user, name, None) for name in cfg.user.__slots__}
    for name in cfg.user.__slots__:
        setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)))
    sim, data = lmu_api()
    old_api, old_read = api._api, api.read
    api._api, api.read = sim, sim.reader()
    yield data
    api._api, api.read = old_api, old_read
    for name, value in backup.items():
        if value is not None:
            setattr(cfg.user, name, value)
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump({"frame_budget_ms": FRAME_BUDGET_MS, "frames": FRAMES, "widgets": RESULTS}, file, indent=2)


def drive(data, frame: int):
    """Change telemetry every frame so widgets redraw"""
    tele = data.telemetry.telemInfo[0]
    phase = frame / FRAMES
    tele.mLocalVel.z = -60 * (1 + math.sin(phase * 6.28))
    tele.mEngineRPM = 4000 + 3000 * abs(math.sin(phase * 12.56))
    tele.mGear = 1 + frame % 6
    tele.mUnfilteredThrottle = abs(math.sin(phase * 3.14))
    tele.mUnfilteredBrake = abs(math.cos(phase * 3.14))
    tele.mFuel = 50 - frame * 0.1
    for index in range(4):
        wheel = tele.mWheels[index]
        wheel.mBrakeTemp = 573.15 + frame * 2 + index
        for layer in range(3):
            wheel.mTemperature[layer] = 353.15 + frame * 0.5 + layer
        wheel.mWear = 1 - frame * 0.001


@pytest.mark.parametrize("name", WIDGET_NAMES)
def test_widget_frame_time(live_api, name):
    widget = import_module(f"tinypedal.widget.{name}").Realtime(cfg, name)
    widget.adjustSize()
    event = QTimerEvent(0)
    PerfMonitor.set_enabled(True)
    PerfMonitor.reset()
    try:
        for frame in range(FRAMES):
            drive(live_api, frame)
            widget.timerEvent(event)
            widget.grab()  # paint
    finally:
        PerfMonitor.set_enabled(False)
        widget.deleteLater()
    stats = {(item.name, item.event): item for item in PerfMonitor.stats()}
    update = stats.get((name, "update"))
    paint_total = sum(item.total for (owner, event_name), item in stats.items() if owner == name and event_name == "paint")
    update_avg = update.average if update else 0.0
    frame_avg = update_avg + paint_total / FRAMES
    RESULTS[name] = {
        "frame_avg_ms": round(frame_avg, 3),
        "update_avg_ms": round(update_avg, 3),
        "update_max_ms": round(update.maximum, 3) if update else 0.0,
        "paint_avg_ms": round(paint_total / FRAMES, 3),
    }
    assert frame_avg < FRAME_BUDGET_MS, f"{name}: {frame_avg:.2f} ms per frame (budget {FRAME_BUDGET_MS} ms)"
    if name in BASELINE:
        before = BASELINE[name]["frame_avg_ms"]
        assert frame_avg < max(before * SLOWDOWN_FACTOR, before + SLOWDOWN_MIN_MS), (
            f"{name}: {frame_avg:.2f} ms per frame, was {before:.2f} ms")
