"""UI thread budget of the Broadcast Director: one game answer of a 60 cars race handled within a frame budget

Each answer (once a second) makes the car list, timing table, car sheet, laps, commentator tab & graphics state on
the UI thread. Timed: received_state with everything shown (page, timing table, sheet, lap history, graphics source
watched). Budget kept generous (slow CI machines).
"""

import time
from functools import partial

from neopedal.process.game_info import Contact
from neopedal.ui.quick import director_game as dgame
from tests.test_broadcast_director import TRACK, car, director_page, race_answers  # noqa: F401

UI_BUDGET = 0.05  # seconds an answer may hold the UI thread
CARS = 60
CLASSES = ("Hyper", "LMP2", "GT3")


def field(now: float) -> list:
    """60 cars of three classes spread along the lap, some close (battles), some in the pits, laps & sectors done"""
    cars = []
    for slot in range(1, CARS + 1):
        lap = 100.0 + slot * 0.1
        cars.append(car(
            slot, slot, laps=20 - slot // 20, distance=(TRACK - slot * 63.0 + now * 50.0) % TRACK,
            car_class=CLASSES[slot % 3], best=lap, last=lap + 0.4, best_sector1=lap * 0.3, best_sector2=lap * 0.65,
            last_sector1=lap * 0.3 + 0.1, last_sector2=lap * 0.65 + 0.2, pitstops=slot % 3, in_pit=slot % 17 == 0,
            penalties=1 if slot % 13 == 0 else 0, grid=CARS + 1 - slot, energy=0.5,
        ))
    return cars


def answer(page, now: float, contacts=()) -> dict:
    """Game state as the state request makes it (background thread), handed to received_state"""
    page.game.answers = race_answers(now, *field(now), focus=5, contacts=contacts)
    return dgame.ask_state(page.game.connection(), forecast=False, trackmap=False)


def timed(call) -> float:
    start = time.perf_counter()
    call()
    return time.perf_counter() - start


def test_director_answer_of_60_cars_within_budget(director_page, monkeypatch):  # noqa: F811
    from neopedal.stream_director import director_feed

    page, backend = director_page, director_page.backend
    published: list[dict] = []
    monkeypatch.setattr(director_feed, "publish", published.append)
    monkeypatch.setattr(director_feed, "watched", lambda: True)  # graphics source open
    monkeypatch.setattr(backend.game, "schedule", lambda: None)  # no next request: answers handed by the test
    backend.received_state(answer(page, 100.0))
    backend.timing.setTimingOpen(True)
    backend.selectCar(7)
    backend.showLaps(7)
    backend.setCommentaryTab(3)  # pit stops
    contacts = [Contact(100.0 + index * 0.4, f"Driver {index + 1}", f"Driver {index + 2}") for index in range(8)]
    times = []
    for second in range(1, 9):
        state = answer(page, 100.0 + second, contacts[:second])
        times.append(timed(partial(backend.received_state, state)))
    assert backend.carRows.rowCount() == CARS and backend.timing.timingRows.rowCount() == CARS
    assert backend.sheet["driver"] == "Driver 7" and len(published) >= 9 and backend.events
    assert sorted(times)[len(times) // 2] < UI_BUDGET, times  # median: one slow pass of a busy machine allowed
    assert max(times) < UI_BUDGET * 4, times
