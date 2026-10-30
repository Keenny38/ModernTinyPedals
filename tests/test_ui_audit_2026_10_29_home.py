"""UI/UX audit 2026-10-29, Home page (H1 to H4): one status banner (verdict, its action, other checks, version,
update told once), large game card in a session (place, lap, time left, actions at hand), one overlays card without
share bars, last session & debrief merged (details on demand), card places kept while read in background"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF

from neopedal import i18n
from neopedal.ui import home_view
from neopedal.ui.home_checks import CheckState, home_checks, home_status
from neopedal.ui.quick import home_backend, qml_path
from neopedal.userfile.driver_history import SessionRecord
from tests.test_audit_g_qml_pages import item_named, items_of, pump
from tests.test_home_view import item_texts
from tests.test_perf_page_state import qml_warnings  # noqa: F401


@pytest.fixture
def home(ui_env, monkeypatch):
    """Home page alone (pages opened from it recorded), shown wide: three columns of cards"""
    # Game window of this machine never looked for (a running Le Mans Ultimate would change the checks)
    monkeypatch.setattr(home_backend, "find_game_window", lambda: False)
    opened: list[str] = []
    page = home_view.HomeView(None, None, opened.append)
    page.opened = opened
    page.resize(1500, 1000)
    page.show()
    QCoreApplication.processEvents()
    yield page
    page.close()
    page.deleteLater()
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def state(**values) -> CheckState:
    base = {"game": "Le Mans Ultimate", "running": True, "game_window": False, "override": False, "spectate": False,
            "overlays": 5, "recorder": True, "update": ""}
    return CheckState(**{**base, **values})


def keys(rows) -> list[str]:
    return [row["key"] for row in rows]


def on_track(monkeypatch, remaining=1500.0, finish=0, laps=0):
    from neopedal.api_control import api

    read = api.read
    monkeypatch.setattr(read.state, "version", lambda: "1.4200")
    monkeypatch.setattr(read.state, "active", lambda: True)
    monkeypatch.setattr(read.session, "track_name", lambda: "Spa")
    monkeypatch.setattr(read.session, "session_type", lambda: 4)
    monkeypatch.setattr(read.session, "finish_type", lambda as_lap=None: finish)
    monkeypatch.setattr(read.session, "remaining", lambda: remaining)
    monkeypatch.setattr(read.lap, "maximum", lambda: laps)
    monkeypatch.setattr(read.vehicle, "place", lambda index=None: 3)
    monkeypatch.setattr(read.vehicle, "total_vehicles", lambda: 20)
    monkeypatch.setattr(read.lap, "completed_laps", lambda index=None: 4)


# --- H1: banner verdict
def test_status_verdict_and_other_checks():
    status = home_status(home_checks(state(running=False, update="1.2.3", recorder=False, overlays=0)), {})
    assert status["key"] == "game" and status["title"] == "Game not running" and status["action"] == "api"
    assert keys(status["rows"]) == ["overlays", "recorder"]  # game not running once, update left to the button
    status = home_status(home_checks(state(update="1.2.3")), {})
    assert status["key"] == "ready" and status["level"] == "success" and status["rows"] == []
    status = home_status(home_checks(state(overlays=0)), {})
    assert status["key"] == "overlays" and status["actionText"] == "Open Overlays"  # action follows the verdict
    session = {"track": "Spa", "session": "Race", "position": "P3", "vehicle": "Ferrari 499P"}
    status = home_status(home_checks(state(spectate=True)), session)
    assert status["title"] == "In session · Spa · Race · P3" and status["level"] == "live"
    assert status["text"] == "Ferrari 499P" and keys(status["rows"]) == ["spectate"]  # no "ready" row on track


def test_banner_on_page_without_warnings(qml_warnings, home, monkeypatch):  # noqa: F811
    from neopedal.api_control import api

    monkeypatch.setattr(api.read.state, "version", lambda: "not running")
    backend = home.backend
    backend.refresh_live()
    QCoreApplication.processEvents()
    root = home.view.rootObject()
    assert item_named(root, "statusTitle").property("text") == "Game not running"
    assert item_named(root, "statusAction").property("text") == "API Options"
    texts = item_texts(home.view)
    assert "Not running" not in texts  # game card does not tell it again
    assert "Version" in item_named(root, "versionText").property("text")
    assert not qml_warnings, qml_warnings


# --- H2: large game card on track
def test_game_card_large_in_session(qml_warnings, home, monkeypatch):  # noqa: F811
    on_track(monkeypatch, remaining=3725.0)
    backend = home.backend
    backend.refresh_live()
    pump(0.2)  # layout polished
    game = backend.game
    assert (game["position"], game["total"], game["lap"], game["timeLeft"]) == ("P3", "/20", "Lap 5", "1:02:05")
    root = home.view.rootObject()
    card = item_named(root, "gameCard")
    columns = root.property("columns")
    assert columns > 1 and card.width() > item_named(root, "overlaysCard").width() * 1.5  # whole row
    assert {"P3", "/20", "Lap 5", "1:02:05", "Time left", "Live Calculator", "Broadcast Director"} <= item_texts(home.view)
    on_track(monkeypatch, remaining=0.0, finish=1, laps=30)  # lap race: lap of laps, no time left
    backend.refresh_live()
    assert backend.game["lap"] == "Lap 5/30" and backend.game["timeLeft"] == ""
    assert not qml_warnings, qml_warnings


def test_context_actions_open_pages(home, monkeypatch):
    tabs, opened = [], []

    class Calculator:
        class backend:
            @staticmethod
            def setTab(index):
                tabs.append(index)

    monkeypatch.setattr(home.backend, "open_tool", lambda path: opened.append(path) or Calculator())
    home.backend.openLiveCalculator()
    home.backend.openDirector()
    from neopedal.ui.quick.race_base import TABS

    assert opened == ["race_calculator.RaceCalculator", "broadcast_director.BroadcastDirector"]
    assert tabs == [TABS.index("live")]


def test_game_published_only_on_change(home, monkeypatch):
    on_track(monkeypatch)
    backend = home.backend
    backend.refresh_live()
    told = []
    for signal in (backend.gameChanged, backend.statusChanged, backend.checksChanged, backend.overlayChanged):
        signal.connect(lambda: told.append(1))
    backend.refresh_live()  # nothing changed: page not told
    assert told == []


# --- H3: one overlays card, last session & debrief merged
def test_one_overlays_card_without_share_bars():
    with open(qml_path("Home.qml"), encoding="utf-8") as file:
        text = file.read()
    assert "CountLine" not in text and 'title: i18n.tr("Overlay")' not in text
    assert text.count('onOpened: backend.openPage("widget")') == 1  # one card opens the overlays page
    assert 'title: i18n.tr("Checks")' not in text  # checks in the banner


def test_debrief_details_on_demand(qml_warnings, home):  # noqa: F811
    backend = home.backend
    backend.publish("lastSession", {"track": "Spa", "vehicle": "Oreca 07", "session": "Race"}, backend.lastSessionChanged)
    backend.publish("debrief", {"best": "1:30.000", "figures": ["3 laps"], "personal": "", "personalText": "",
                                "tips": [{"index": 0, "label": "T1", "loss": "0.20 s", "cause": "Brakes", "apex": 10.0}],
                                "against": "vs your personal best lap", "canOpen": True}, backend.debriefChanged)
    backend.set_loading("debrief", False)
    QCoreApplication.processEvents()
    texts = item_texts(home.view)
    assert {"Last Session", "Session Debrief", "Best 1:30.000", "Open Telemetry", "Show Details"} <= texts
    assert "T1" not in texts
    root = home.view.rootObject()
    root.setProperty("debriefOpen", True)
    QCoreApplication.processEvents()
    assert {"T1", "Brakes", "Hide Details"} <= item_texts(home.view)
    assert not qml_warnings, qml_warnings


# --- H4: places kept while read in background
def test_card_places_kept_while_reading(qml_warnings, home, monkeypatch):  # noqa: F811
    backend = home.backend
    root = home.view.rootObject()
    # Driver card: place kept (spinner) until profile & results are read, then shown or freed
    backend.publish("driver", {}, backend.driverChanged)
    backend.set_loading("driver", True)
    QCoreApplication.processEvents()
    assert item_named(root, "driverCard").isVisible() and item_named(root, "driverLoading").isVisible()
    backend._driver_key = ("forced",)
    backend.driver_data_read(None)
    QCoreApplication.processEvents()
    assert backend.loading["driver"] is False
    if backend.driver == {}:  # nothing known on this computer: place freed
        assert not item_named(root, "driverCard").isVisible()
    # Debrief: spinner in the last session card while its laps are read
    started = []
    monkeypatch.setattr(backend.jobs, "run", lambda *args, **kwargs: started.append(args))
    record = SessionRecord(time=1759660000, track="Spa", vehicle="Oreca 07", session=2, best=123.456)
    monkeypatch.setattr(home_view, "last_session", lambda: record)
    backend._record_read = False
    backend._debrief_key = None
    backend.publish("debrief", {}, backend.debriefChanged)
    backend.refresh_last_session()
    QCoreApplication.processEvents()
    assert started and backend.loading["debrief"] is True
    assert item_named(root, "lastSessionCard").isVisible() and item_named(root, "debriefLoading").isVisible()
    backend.debrief_failed(OSError("laps gone"))  # unreadable: spinner gone, no debrief
    QCoreApplication.processEvents()
    assert backend.loading["debrief"] is False and backend.debrief == {}
    assert not item_named(root, "debriefLoading").isVisible()
    assert not qml_warnings, qml_warnings


def test_clock_text():
    assert home_backend.clock_text(3725.4) == "1:02:05" and home_backend.clock_text(65) == "1:05"
    assert home_backend.clock_text(-3) == "0:00"


# --- French: buttons stay inside the page on narrow & wide pages
@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


@pytest.mark.parametrize("width", [520, 900, 1300])
def test_page_fits_in_french(french, home, monkeypatch, width):
    on_track(monkeypatch)
    home.backend.refresh_live()
    home.resize(width, 900)
    pump(0.3)
    root = home.view.rootObject()
    cards = {"statusBanner", "gameCard", "overlaysCard", "lastSessionCard", "driverCard"}

    def in_cards(item) -> bool:
        while item is not None and item is not root:
            if item.objectName() in cards:
                return True
            item = item.parentItem()
        return False

    buttons = [item for item in items_of(root) if item.isVisible() and "TpButton" in item.metaObject().className()
               and in_cards(item)]  # quick access: fixed columns, long names elided (tooltip)
    assert len(buttons) >= 5
    for button in buttons:
        right = button.mapToItem(root, QPointF(button.width(), 0)).x()
        assert right <= root.width() + 0.5, (button.property("text"), right, root.width())
        assert button.width() >= button.implicitWidth() - 0.5, button.property("text")  # text never cut


# --- This week (shared with Driver Stats, stats_analysis.weekly_progress)
def test_week_card_texts():
    assert home_backend.week_card([]) == {}
    items = [{"kind": "summary", "sessions": 3, "laps": 42, "seconds": 3900.0, "meters": 0.0, "tracks": 2, "vehicles": 2},
             {"kind": "record", "track": "Spa", "vehicle": "GT3", "best": 120.0, "previous": 121.0, "gain": 1.0, "time": 1.0},
             {"kind": "goal_reached", "track": "Spa", "vehicle": "GT3", "goal": 121.0, "best": 120.0, "time": 1.0},
             {"kind": "record", "track": "Monza", "vehicle": "GT3", "best": 110.0, "previous": 0.0, "gain": 0.0, "time": 2.0}]
    card = home_backend.week_card(items)
    assert card["summary"] == "3 sessions · 1 h 05 min · 42 laps"
    assert [(row["kind"], row["text"]) for row in card["highlights"]] == [
        ("goal_reached", "1 goal reached"), ("record", "2 new personal bests")]


def test_week_card_from_history_read_with_debrief(qml_warnings, home, monkeypatch):  # noqa: F811
    import time

    from neopedal.ui import home_debrief

    now = time.time()
    records = [SessionRecord(time=now - 86400 * 30, track="Spa", vehicle="Oreca 07", best=125.0, valid=10),
               SessionRecord(time=now - 3600, track="Spa", vehicle="Oreca 07", best=123.0, valid=12, seconds=1800.0)]
    reads = []
    monkeypatch.setattr(home_debrief, "load_history", lambda path: reads.append(path) or list(records))
    monkeypatch.setattr(home_view, "last_session", lambda: records[-1])
    backend = home.backend
    root = home.view.rootObject()
    backend._record_read = False
    backend._debrief_key = backend._records = backend._week_key = None
    backend.set_loading("week", True)
    backend.publish("week", {}, backend.weekChanged)
    started = []
    real_run = backend.jobs.run
    monkeypatch.setattr(backend.jobs, "run", lambda *args, **kwargs: started.append(args[0]) or real_run(*args, **kwargs))
    backend.refresh_slow()
    QCoreApplication.processEvents()
    assert item_named(root, "weekCard").isVisible()  # place kept while the history is read
    end = time.monotonic() + 10
    while backend.loading["week"] and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert len(reads) == 1  # one disk pass: debrief & week from the same records
    week = backend.week
    assert week["summary"] == "1 session · 30 min · 12 laps"
    assert [row["kind"] for row in week["highlights"]] == ["record"]
    pump(0.1)
    assert {"This Week", "1 session · 30 min · 12 laps", "1 new personal best"} <= item_texts(home.view)
    assert not item_named(root, "weekLoading").isVisible()
    told = []
    backend.weekChanged.connect(lambda: told.append(1))
    started.clear()
    backend.refresh_week()  # nothing changed: no job, page not told
    assert started == [] and told == []
    # Nothing driven in the last days: no card, no place kept
    backend._records = [records[0]]
    backend.refresh_week()
    end = time.monotonic() + 10
    while backend.week and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    pump(0.1)
    assert backend.week == {} and not item_named(root, "weekCard").isVisible()
    assert not qml_warnings, qml_warnings
