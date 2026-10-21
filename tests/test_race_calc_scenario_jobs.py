"""Race calculator scenarios on a worker thread: newest plan's scenarios handed over, UI thread not held"""

import time

from PySide6.QtCore import QCoreApplication

from tests.test_race_calculator import host, page, set_race  # noqa: F401 (host, page: fixtures)


def wait_jobs(backend, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while backend.jobs.running and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    return not backend.jobs.running


def test_scenarios_on_worker_thread(page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_backend

    backend = page.backend
    monkeypatch.setattr(race_backend, "SCENARIO_JOBS", True)
    shown = []
    backend.scenariosChanged.connect(lambda: shown.append(dict(backend.scenarios)))
    set_race(backend, laps=40, tank=45, fuel=3.0)  # 2 stops
    assert wait_jobs(backend)
    assert "laps per stint" in backend.scenarios["oneLess"]
    shown.clear()
    for laps in (41, 42, 60):  # quick changes: only the newest plan's scenarios shown
        backend.setInput("input_race_laps", laps)
    assert wait_jobs(backend)
    assert shown and len(backend.strategy.stops) == 3
    comparison = backend.scenarios["comparison"]
    assert comparison and any("3" in str(row) for row in comparison.get("rows", []))
    details = {row["key"]: row for row in backend.details["rows"]}
    assert details["one_less_stint"]["fuel"] not in ("", None)


def test_scenario_results_pure():
    """Worker thread function: same texts as the plan's scenarios"""
    from neopedal.fuel_strategy import StrategyInput, plan
    from neopedal.ui.quick.race_backend import scenario_results

    setup = StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, sc_lap=10, sc_laps=3)
    scenarios = scenario_results(plan(setup), setup, setup, 0, True, False, "L")
    assert "Without safety car" in scenarios["safetyCar"] and scenarios["rain"] == ""
    assert scenarios["comparison"]
