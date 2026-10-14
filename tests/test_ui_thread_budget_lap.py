"""UI thread budget of lap viewer playback: per frame backend work of 4 long laps with several chart panels, map
(trails on) & simple view shown stays well under a frame (playbackStep: positions every frame, full cursor state
about 30 times a second). Budgets generous for slow CI machines (a fast machine is several times under them)."""

import time

from tests.test_ui_thread_budget import long_laps  # noqa: F401  (fixture)

FRAMES = 120
LIGHT_BUDGET = 0.004  # seconds per playback frame moving cars only (average)
FULL_BUDGET = 0.025  # seconds per playback frame with full cursor state (average)


def average(call, count: int) -> float:
    start = time.perf_counter()
    for index in range(count):
        call(index)
    return (time.perf_counter() - start) / count


def test_playback_frames_within_budget(long_laps):  # noqa: F811
    page = long_laps
    for column in ("rpm", "gear", "steering", "brake", "throttle"):
        page.setChannelVisible(column, True)
    page.wait_jobs()
    page.setMapShown(True)
    page.setSimpleView(True)
    page.wait_jobs()
    assert page.dashboard.layout  # items of simple view (read by QML when shown)
    assert len(page.data.laps) == 4 and len(page.panels) >= 5
    lap_time = page.referenceLapTime
    assert lap_time > 0
    step = lap_time / 2 / FRAMES  # half a lap, frame by frame
    light = average(lambda index: page.playbackStep(10.0 + index * step, False), FRAMES)
    full = average(lambda index: page.playbackStep(10.0 + index * step * 4 + step / 2, True), FRAMES // 4)
    state = page.playbackStep(lap_time / 3, True)["state"]
    assert state["values"] and state["dashboard"] and state["inputs"]
    assert (len(page.playbackStep(lap_time / 3, False)["mapXY"]) == 12) is bool(page._map)  # 4 laps on map
    assert light < LIGHT_BUDGET, f"light frame {light * 1000:.2f} ms"
    assert full < FULL_BUDGET, f"full frame {full * 1000:.2f} ms"
    page.setSideTab(1)  # G circle shown: its positions too
    page.wait_jobs()
    light_g = average(lambda index: page.playbackStep(10.0 + index * step, False), FRAMES)
    assert page.playbackStep(lap_time / 3, False)["gXY"]
    assert light_g < LIGHT_BUDGET, f"light frame with G circle {light_g * 1000:.2f} ms"
    print(f"light {light * 1000:.2f} ms, full {full * 1000:.2f} ms, light with G {light_g * 1000:.2f} ms")


def test_cursor_state_same_position_cached(long_laps):  # noqa: F811
    page = long_laps
    page.setSimpleView(True)
    page.wait_jobs()
    x = page.data.max_x() / 2
    state = page.cursorState(x)
    start = time.perf_counter()
    for _ in range(100):
        assert page.cursorState(x) is state
    assert (time.perf_counter() - start) / 100 < 0.0005  # same position & page state: nothing worked out
