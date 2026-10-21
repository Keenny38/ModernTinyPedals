"""Home page session debrief card: read in background from history, recorded laps, stats & goals"""

import json
import os
import time

from PySide6.QtCore import QCoreApplication

from neopedal.setting import cfg
from neopedal.ui import home_debrief, home_view
from neopedal.userfile.driver_history import SessionRecord
from tests.test_home_view import home  # noqa: F401  (fixture)
from tests.test_session_debrief import START, record, save


def wait_until(condition, timeout: float = 10.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "debrief not read"
        QCoreApplication.processEvents()
        time.sleep(0.005)


def write_stats(best: float):
    with open(os.path.join(cfg.path.config, "driver.stats"), "w", encoding="utf-8") as file:
        json.dump({"Track": {"GT3 - Brand": {"pb": best}}}, file)


def set_goal(monkeypatch, laptime: float):
    """Lap time goal of test track & vehicle, as driver stats page saves it"""
    from neopedal.ui.quick.stats_common import CONFIG_NAME

    monkeypatch.setitem(cfg.user.config, CONFIG_NAME, {"goals": {"Track|GT3 - Brand": laptime}})


def test_debrief_card_with_laps_tips_and_reached_goal(home, monkeypatch):  # noqa: F811
    folder = cfg.path.telemetry.rstrip("/")
    save(folder, 5, 89.5, START - 86400, brake=0.47)  # older personal best lap
    save(folder, 1, 91.0, START + 100, sectors=[30.2, 30.6, 30.2])
    save(folder, 2, 90.0, START + 200, sectors=[30.0, 30.4, 29.6])
    save(folder, 3, 90.5, START + 300, sectors=[29.9, 30.7, 29.9])
    write_stats(89.5)
    set_goal(monkeypatch, 89.9)
    monkeypatch.setattr(home_view, "last_session", lambda: record())
    backend = home.backend
    backend._record_read = False
    backend.refresh_last_session()
    wait_until(lambda: backend.debrief != {})
    card = backend.debrief
    assert card["best"] == "1:30.000" and card["personal"] == "slower" and "vs personal best" in card["personalText"]
    assert card["figures"][0] == "3 laps" and card["figures"][1].startswith("Pace 1:30.500")
    assert "Theoretical 1:29.900" in card["figures"]
    assert card["against"] == "vs your personal best lap" and card["canOpen"]
    assert card["tips"] and "Brakes" in card["tips"][0]["cause"] and card["tips"][0]["apex"] > 0
    assert card["goal"]["state"] == "reached" and card["goal"]["goal"] == "1:29.900"  # personal best 1:29.500
    assert home_debrief.debrief_laps(backend._debrief_data)[1]  # telemetry opens both laps compared
    QCoreApplication.processEvents()
    from tests.test_home_view import item_texts

    assert {"Session Debrief", "Best 1:30.000", "Open Telemetry"} <= item_texts(home.view)


def test_debrief_card_hidden_without_laps_or_best(home, monkeypatch):  # noqa: F811
    monkeypatch.setattr(home_view, "last_session", lambda: record(best=0.0, valid=0, invalid=0))
    backend = home.backend
    shown = []
    real = backend.debrief_read
    monkeypatch.setattr(backend, "debrief_read", lambda data: (shown.append(data), real(data)))
    backend._debrief_key = None
    backend._record_read = False
    backend.refresh_last_session()
    wait_until(lambda: shown)
    assert backend.debrief == {}
    monkeypatch.setattr(home_view, "last_session", lambda: None)
    backend.refresh_last_session()
    assert backend.debrief == {} and backend.lastSession == {}


def test_goal_progress_from_first_best_of_history():
    history = [SessionRecord(time=1.0, track="Track", vehicle="GT3 - Brand", best=92.0),
               SessionRecord(time=2.0, track="Other", vehicle="GT3 - Brand", best=80.0)]
    progress = home_debrief.goal_progress(90.0, 91.0, record(), history)
    assert progress.ratio == 0.5 and progress.gap == 1.0 and not progress.reached
    assert home_debrief.goal_text(progress) == "Goal 1:30.000: 1.000 s to find (50%)"
    card = home_debrief.goal_card(progress)
    assert (card["state"], card["gap"], card["ratio"], card["percent"]) == ("gap", "1.000 s to find", 0.5, "50%")
    assert home_debrief.goal_progress(90.0, 90.0004, record(), history).reached  # as shown (milliseconds)
    assert home_debrief.goal_text(home_debrief.goal_progress(90.0, 0.0, record(), [])) == "Goal 1:30.000"


def test_stats_goal_read_from_driver_stats_setting(ui_env, monkeypatch):
    set_goal(monkeypatch, 89.9)
    assert home_debrief.stats_goal("Track", "GT3 - Brand") == 89.9
    assert home_debrief.stats_goal("Track", "Other") == 0.0
    set_goal(monkeypatch, "junk")
    assert home_debrief.stats_goal("Track", "GT3 - Brand") == 0.0


def test_debrief_text_in_french(ui_env):
    from neopedal import i18n
    from neopedal.userfile.session_debrief import CornerTip, build_debrief

    i18n.set_language("Français")
    try:
        debrief = build_debrief(record(best=90.0), [record(end=START - 1000, best=89.5)], "")
        data = home_debrief.DebriefData(debrief, [CornerTip("V5", 0.12, (("brake_early", 6.0),), 512.0)], None)
        card = home_debrief.debrief_card(data)
    finally:
        i18n.set_language("English")
    assert card["best"] == "1:30.000" and card["personalText"] == "+0,500 s par rapport au record"
    assert card["tips"] == [{"index": 0, "label": "V5", "loss": "+0,12 s", "cause": "Freine 6 m plus tôt",
                             "apex": 512.0}]
    assert card["against"] == "tour type par rapport à votre meilleur tour de la session"
