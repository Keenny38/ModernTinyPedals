"""Race calculator: where the car rejoins after a stop at the end of this lap (class rivals)"""

import pytest

from neopedal.race_live import Rival, pit_exit


def rival(place, name, progress, player=False):
    return Rival(place, name, int(progress), 0, 0, False, player, progress)


CARS = [
    rival(1, "Alice", 30.50),
    rival(2, "Me", 30.00, player=True),
    rival(3, "Bob", 29.80),  # 20 s behind at 100 s a lap
    rival(4, "Carl", 29.40),  # 60 s behind
    rival(5, "Dan", 28.90),
]


def test_pit_exit_place_and_gaps():
    place = pit_exit(CARS, 30.0, 100.0)  # back on track at 29.70
    assert place.place == 3 and place.passed == 1
    assert place.ahead[0] == "Bob" and place.ahead[1] == pytest.approx(10.0)
    assert place.behind[0] == "Carl" and place.behind[1] == pytest.approx(30.0)
    place = pit_exit(CARS, 150.0, 100.0)  # 28.50: last
    assert place.place == 5 and place.passed == 3 and place.behind is None
    assert place.ahead[0] == "Dan" and place.ahead[1] == pytest.approx(40.0)
    place = pit_exit(CARS, 5.0, 100.0)
    assert place.place == 2 and place.passed == 0 and place.ahead[0] == "Alice"


def test_pit_exit_unknown():
    assert pit_exit(CARS[:1], 30.0, 100.0) is None  # no player car
    assert pit_exit([CARS[1]], 30.0, 100.0) is None  # alone in class
    assert pit_exit(CARS, 30.0, 0.0) is None
    assert pit_exit(CARS, 0.0, 100.0) is None


def test_class_rivals_shows_exit():
    from neopedal.ui.quick import race_results

    table = race_results.class_rivals(CARS, 25, pit_exit(CARS, 30.0, 100.0))
    text = table["exit"]
    assert "back on track P3 in class" in text and "10.0 s behind Bob" in text
    assert "30.0 s ahead of Carl" in text and "1 car(s) pass you" in text
    assert race_results.class_rivals(CARS, 25)["exit"] == ""
    escaped = race_results.class_rivals(CARS, 25, pit_exit([*CARS[:2], rival(3, "<b>X", 29.9)], 30.0, 100.0))
    assert "&lt;b&gt;X" in escaped["exit"]


def test_rival_tracker_reads_progress(ui_env, monkeypatch):
    from neopedal.api_control import api
    from neopedal.race_live import RivalTracker

    read = api.read
    values = {
        (read.vehicle, "player_index"): 0, (read.vehicle, "total_vehicles"): 2,
        (read.vehicle, "same_class"): True, (read.vehicle, "slot_id"): 7, (read.vehicle, "number_pitstops"): 0,
        (read.lap, "completed_laps"): 12, (read.lap, "progress"): 0.25, (read.vehicle, "place"): 1,
        (read.vehicle, "driver_name"): "Me", (read.vehicle, "in_pits"): False,
    }
    for (group, name), value in values.items():
        monkeypatch.setattr(group, name, lambda *args, value=value, **kwargs: value, raising=False)
    rivals = RivalTracker().update(now=0.0)
    assert rivals[0].progress == pytest.approx(12.25)
