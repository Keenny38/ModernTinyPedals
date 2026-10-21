"""Overlays page additions: grouped switch, state counts, sort, favorites, recently edited, descriptions,
visibility badges, loaded preset, animated preview & screen view"""

import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage

from neopedal import app_signal
from neopedal.const_file import ConfigType
from neopedal.module_control import ModuleControl
from neopedal.setting import cfg
from neopedal.template.widget.descriptions import OVERLAY_DESCRIPTIONS
from neopedal.template.widget.registry import OVERLAYS
from neopedal.ui.quick import overlay_backend
from neopedal.ui.quick.overlay_backend import (
    CATEGORY_FAVORITES,
    CATEGORY_RECENT,
    FAVORITES_KEY,
    FILTER_ACTIVE,
    RECENT_KEY,
    RECENT_MAX,
    SORT_ACTIVE,
    SORT_CATEGORY,
    SORT_NAME,
    VIEW_CARDS,
    VIEW_LIST,
    VIEW_SCREEN,
    LiveRunner,
    OverlayBackend,
    OverlayModel,
    name_list,
    note_edited,
    visibility_badges,
)
from neopedal.ui.quick.overlay_screen import bounds_of, clamped_position, overlapping, rect_value

NAMES = ("brake_temperature", "brake_wear", "speedometer", "fuel", "relative")


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def solid(color: str, width: int = 40, height: int = 20) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


class FakeWidget:
    """Running overlay: geometry & move (saved, undoable in the real one)"""

    def __init__(self, rect: QRect):
        self.rect = QRect(rect)
        self.moves: list[tuple[QPoint, str]] = []

    def geometry(self) -> QRect:
        return QRect(self.rect)

    def move_overlay(self, pos: QPoint, action: str):
        self.moves.append((QPoint(pos), action))
        self.rect.moveTopLeft(pos)


class FakeControl:
    """Widget control: enabled overlays running (as fake widgets with a place) unless failing"""

    type_id = "widget"

    def __init__(self, names, rects=None):
        self._names = dict.fromkeys(names)
        self.widgets = {name: FakeWidget((rects or {}).get(name, QRect(10, 10, 100, 50))) for name in names}
        self.failing: set[str] = set()
        self.grouped: list[tuple[list[str], bool]] = []

    @property
    def names(self):
        return self._names.keys()

    @property
    def active_modules(self):
        return {name: self.widgets[name] for name in self._names
                if cfg.user.setting[name]["enable"] and name not in self.failing}

    def toggle(self, name):
        cfg.user.setting[name]["enable"] = not cfg.user.setting[name]["enable"]

    def set_enabled(self, names, enable):
        changed = [name for name in names if bool(cfg.user.setting[name]["enable"]) != enable]
        self.grouped.append((changed, enable))
        for name in changed:
            cfg.user.setting[name]["enable"] = enable
        return changed

    def enable_all(self):
        for name in self._names:
            cfg.user.setting[name]["enable"] = True

    def disable_all(self):
        for name in self._names:
            cfg.user.setting[name]["enable"] = False


@pytest.fixture
def page(ui_env, monkeypatch):
    """Backend over 5 overlays (speedometer & brake temperature on), solid previews, still overlays (no
    animation built), one 1920x1080 screen"""
    for name in NAMES:
        cfg.user.setting[name]["enable"] = name in ("brake_temperature", "speedometer")
    monkeypatch.setattr(overlay_backend, "render_preview", lambda name: solid("#336699"))
    monkeypatch.setattr(overlay_backend, "make_live_preview", lambda name: None)
    monkeypatch.setattr(overlay_backend, "screen_rects", lambda: [("Main", QRect(0, 0, 1920, 1080), True)])
    control = FakeControl(NAMES)
    backend = OverlayBackend(None, control, lambda name: None, lambda text: True)
    backend.test_control = control  # type: ignore[attr-defined]
    backend.test_saved = ui_env  # type: ignore[attr-defined]
    yield backend
    backend.close()
    backend.deleteLater()
    flush()


def shown(backend) -> list[str]:
    return backend.proxy.shown_names()


# --- Grouped switch of shown overlays
def test_set_enabled_starts_and_closes_once(ui_env, monkeypatch):
    log = []

    class Module:
        def __init__(self, config, name):
            self.name = name
            self.closed = False

        def start(self):
            log.append(("start", self.name))

        def stop(self, discard=False):
            log.append(("stop", self.name))
            self.closed = True

    names = ["module_force", "module_fuel", "module_hybrid"]
    target = SimpleNamespace(__all__=names, **{name: SimpleNamespace(Realtime=Module) for name in names})
    control = ModuleControl(target, ConfigType.MODULE)
    for name in names:
        monkeypatch.setitem(cfg.user.setting[name], "enable", name == "module_hybrid")
    told = []
    control.add_listener(lambda: told.append(1))
    ui_env.clear()
    assert control.set_enabled(["module_force", "module_fuel", "unknown", "module_hybrid"], True) == [
        "module_force", "module_fuel"]  # unknown & already enabled skipped
    assert log == [("start", "module_force"), ("start", "module_fuel")]
    assert told == [1] and ui_env == ["setting"]  # listeners told & setting saved once
    assert control.set_enabled(["module_force"], True) == [] and told == [1]  # nothing changed: nothing told
    assert control.set_enabled(names, False) == names
    assert set(log[2:]) == {("stop", "module_force"), ("stop", "module_fuel")} and not control.active_modules
    assert told == [1, 1] and not any(cfg.user.setting[name]["enable"] for name in names)


def test_enable_shown_grouped(page):
    page.setSearch("brake")
    page.enableShown()
    assert page.test_control.grouped == [(["brake_wear"], True)]


# --- State counts
def test_state_counts_shown_on_segments(page):
    assert page.stateCounts == [5, 2, 3]
    page.setSearch("brake")
    assert page.stateCounts == [2, 1, 1]


# --- Sort
def test_sort_modes_saved_and_placed_again_only_when_asked(page):
    labels = [page.proxy.data(page.proxy.index(row, 0), OverlayModel.LabelRole) for row in range(5)]
    assert labels == sorted(labels, key=str.casefold)  # by name
    page.setSortMode(SORT_ACTIVE)
    assert shown(page)[:2] == ["brake_temperature", "speedometer"]  # enabled first, by name
    assert cfg.application["overlays_sort_order"] == SORT_ACTIVE and page.sortMode == SORT_ACTIVE
    page.toggle("fuel")  # switched overlay stays under the pointer
    assert shown(page)[:2] == ["brake_temperature", "speedometer"] and "fuel" in shown(page)[2:]
    page.setSortMode(SORT_ACTIVE)  # same sort chosen again: placed again
    assert set(shown(page)[:3]) == {"brake_temperature", "speedometer", "fuel"}
    page.setSortMode(SORT_CATEGORY)
    categories = [page.proxy.data(page.proxy.index(row, 0), OverlayModel.CategoryRole) for row in range(5)]
    order = list(overlay_backend.CATEGORY_ORDER)
    assert [order.index(category) for category in categories] == sorted(order.index(category) for category in categories)
    page.setSortMode(99)  # unknown mode ignored
    assert page.sortMode == SORT_CATEGORY
    again = OverlayBackend(None, page.test_control, lambda name: None, lambda text: True)  # kept in config
    assert again.sortMode == SORT_CATEGORY
    again.close()
    again.deleteLater()
    page.setSortMode(SORT_NAME)


def test_switched_overlay_leaves_state_filter(page):
    page.setStateFilter(FILTER_ACTIVE)
    page.toggle("speedometer")
    assert shown(page) == ["brake_temperature"] and page.activeCount == 1


# --- Favorites & recently edited
def test_favorites_marked_kept_in_config_and_filtered(page):
    told = []
    page.countsChanged.connect(lambda: told.append(1))
    page.toggleFavorite("fuel")
    page.toggleFavorite("relative")
    page.toggleFavorite("nothing")  # unknown overlay ignored
    assert name_list(FAVORITES_KEY) == ["fuel", "relative"] and told
    index = page.source.index(page.source.index_of["fuel"], 0)
    assert index.data(OverlayModel.FavoriteRole) is True
    assert page.categoryCounts[CATEGORY_FAVORITES] == 2
    page.setCategory(CATEGORY_FAVORITES)
    assert shown(page) == ["fuel", "relative"] and page.filtered
    page.toggleFavorite("fuel")  # unmarked: leaves the chip at once
    assert shown(page) == ["relative"] and name_list(FAVORITES_KEY) == ["relative"]
    cfg.application[FAVORITES_KEY] = "relative,fuel"  # changed elsewhere (config imported)
    page.refresh()
    assert shown(page) == ["fuel", "relative"]


def test_note_edited_last_first_and_capped(ui_env):
    cfg.application[RECENT_KEY] = ""
    assert note_edited(["fuel", "relative"])
    assert name_list(RECENT_KEY) == ["relative", "fuel"]  # last edited first
    assert note_edited(["fuel"]) and name_list(RECENT_KEY) == ["fuel", "relative"]
    assert not note_edited(["fuel"])  # same order: not saved again
    assert not note_edited([])
    note_edited([f"overlay_{index}" for index in range(20)])
    assert len(name_list(RECENT_KEY)) == RECENT_MAX and name_list(RECENT_KEY)[0] == "overlay_19"
    cfg.application[RECENT_KEY] = 5  # wrong type in file: empty list
    assert name_list(RECENT_KEY) == []


def test_recent_chip_last_edited_first(page):
    assert CATEGORY_RECENT not in [chip["key"] for chip in page.categories]  # nothing edited yet
    note_edited(["speedometer", "brake_wear"])
    page.refresh()
    assert CATEGORY_RECENT in [chip["key"] for chip in page.categories]
    page.setCategory(CATEGORY_RECENT)
    assert shown(page) == ["brake_wear", "speedometer"]  # last edited first, whatever the sort
    assert page.categoryCounts[CATEGORY_RECENT] == 2
    page.setCategory("")
    assert len(shown(page)) == 5


def test_overlay_options_saved_marks_recent(ui_env, monkeypatch):
    from neopedal.ui import overlay_options

    monkeypatch.setattr(overlay_options, "show_toast", lambda *args: None)
    monkeypatch.setattr(overlay_options, "run_after_saving", lambda callback: None)
    cfg.application[RECENT_KEY] = ""
    host = SimpleNamespace(module_control=None)
    overlay_options.OverlayOptions.applied(host, ["fuel", "relative"])  # type: ignore[arg-type]
    assert name_list(RECENT_KEY) == ["relative", "fuel"]


# --- Descriptions & badges
def test_every_overlay_described_in_english_and_french():
    from neopedal.i18n.fr import TRANSLATION

    assert set(OVERLAY_DESCRIPTIONS) == {spec.name for spec in OVERLAYS}
    for name, text in OVERLAY_DESCRIPTIONS.items():
        assert text.endswith(".") and len(text) <= 100, name
        assert TRANSLATION.get(text), name
    assert len(set(OVERLAY_DESCRIPTIONS.values())) == len(OVERLAY_DESCRIPTIONS)


def test_description_role_translated(page):
    from neopedal import i18n

    index = page.source.index(page.source.index_of["fuel"], 0)
    assert index.data(OverlayModel.DescriptionRole) == OVERLAY_DESCRIPTIONS["fuel"]
    assert overlay_backend.overlay_description("plugin_xyz") == ""
    i18n.set_language("Français")
    try:
        assert overlay_backend.overlay_description("fuel").startswith("Carburant restant")
    finally:
        i18n.set_language("English")


def test_visibility_badges(page):
    assert visibility_badges({}) == ()
    assert visibility_badges({"visibility_context": "Race", "stream_visibility": "Stream Only"}) == (
        ("context", "Race"), ("stream", "Stream Only"))
    assert visibility_badges({"stream_visibility": "Screen Only"}) == (("screen", "Screen Only"),)
    cfg.user.setting["fuel"]["visibility_context"] = "In Pits"
    page.refresh()
    index = page.source.index(page.source.index_of["fuel"], 0)
    badges = index.data(OverlayModel.BadgesRole)
    assert [badge["kind"] for badge in badges] == ["context"] and badges[0]["text"] == "In Pits" and badges[0]["tip"]
    cfg.user.setting["fuel"]["visibility_context"] = "Always"


# --- Loaded preset
def test_loaded_preset_menu_and_load(page, monkeypatch):
    folder = cfg.path.settings
    for name in ("default", "Endurance", "Sprint"):
        with open(f"{folder}{name}.json", "w", encoding="utf-8") as file:
            file.write("{}")
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    page.refresh()
    assert page.presetName == "default" and not page.presetLocked
    choices = page.presetChoices()
    assert {choice["name"] for choice in choices} == {"default", "Endurance", "Sprint"}
    assert [choice["name"] for choice in choices if choice["loaded"]] == ["default"]
    reloads = []
    app_signal.reload.connect(reloads.append)
    try:
        page.loadPreset("missing")  # not a preset file: nothing loaded
        page.loadPreset("default")  # already loaded
        assert not reloads
        page.loadPreset("Sprint")
        assert reloads == [True] and cfg._setting_to_load == "Sprint.json"
    finally:
        app_signal.reload.disconnect(reloads.append)
        cfg.set_next_to_load("")
    told = []
    page.presetChanged.connect(lambda: told.append(1))
    monkeypatch.setattr(cfg.filename, "setting", "Sprint.json")
    page.refresh()
    assert told == [1] and page.presetName == "Sprint"


# --- Animated preview
def test_live_runner_plays_one_overlay_at_a_time(monkeypatch):
    built = []

    class Live:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def frame(self, seconds):
            return solid("#ff0000" if seconds < 0.5 else "#00ff00")

        def close(self):
            self.closed = True

    def make(name):
        built.append(name)
        return None if name == "still" else Live(name)

    urls = []
    runner = LiveRunner(make, urls.append, "test-live/key")
    runner.start("fuel")
    runner._next()
    assert built == ["fuel"] and urls and urls[0].startswith("image://") and runner.name == "fuel"
    runner._next()  # same picture: page not told again
    assert len(urls) == 1
    live = runner._live
    runner.start("relative")  # another card hovered: first one stopped
    assert live.closed and urls[-1] == "" and runner.name == "relative"
    runner.stop("fuel")  # not playing: nothing
    assert runner.name == "relative"
    runner.stop()
    runner.start("still")
    runner._next()  # not animated: remembered, never built again
    assert "still" in runner.still and runner.name == ""
    runner.start("still")
    assert runner.name == "" and built.count("still") == 1
    runner.forget_still()
    assert not runner.still
    runner.stop()


def test_live_runner_slow_pictures_fewer_per_second():
    class Slow:
        def frame(self, seconds):
            time.sleep(0.05)
            return solid("#ffffff")

        def close(self):
            pass

    runner = LiveRunner(lambda name: Slow(), lambda url: None, "test-live/slow")
    runner.start("x")
    runner._next()
    assert runner._timer.interval() >= 100
    runner.stop()


def test_live_runner_error_keeps_still_picture():
    class Broken:
        def frame(self, seconds):
            raise RuntimeError("boom")

        def close(self):
            pass

    urls = []
    runner = LiveRunner(lambda name: Broken(), urls.append, "test-live/broken")
    runner.start("x")
    runner._next()
    assert runner.name == "" and "x" in runner.still and urls == [""]  # page told: not animated


def test_live_only_while_page_shown_in_cards(page, monkeypatch):
    started = []
    monkeypatch.setattr(page.live, "start", started.append)
    page.startLive("fuel")  # page hidden
    page.set_active(True)
    page.startLive("fuel")
    page.startLive("unknown")
    page.setViewMode(VIEW_LIST)
    page.startLive("fuel")  # list: tooltips, no animation
    assert started == ["fuel"]
    page.setViewMode(VIEW_CARDS)
    page.set_active(False)


def test_real_overlay_animated_on_moving_session(ui_env):
    from neopedal import demo_data
    from neopedal.ui.widget_preview import live_preview

    still = demo_data.demo_session(cfg.user.setting["standings"])
    throttle = still.data.telemetry.telemInfo[demo_data.PLAYER].mUnfilteredThrottle
    live = live_preview(cfg, "pedal", cfg.user.setting["pedal"], QSize(520, 360))
    assert live is not None
    try:
        first = live.frame(0.0)
        braking = live.frame(demo_data.MOTION_PERIOD * 0.3)  # hard braking
        assert first is not None and braking is not None and first != braking
        assert live.session is not still  # own session: still pictures never move
        assert still.data.telemetry.telemInfo[demo_data.PLAYER].mUnfilteredThrottle == throttle
    finally:
        live.close()
    assert live_preview(cfg, "chat", cfg.user.setting["chat"], QSize(520, 360)) is None  # sample only
    assert live_preview(cfg, "standings", cfg.user.setting["standings"], QSize(520, 360)) is None  # sample race
    flush()


def test_set_motion_loops_a_corner(ui_env):
    from neopedal import demo_data

    session = demo_data.DemoSession(cfg.user.setting["standings"])
    tele = session.data.telemetry.telemInfo[demo_data.PLAYER]
    speeds, gears = [], []
    for step in range(60):
        demo_data.set_motion(session, step * demo_data.MOTION_PERIOD / 60)
        speeds.append(-tele.mLocalVel.z)
        gears.append(tele.mGear)
        assert 0 <= tele.mUnfilteredThrottle <= 1 and 0 <= tele.mUnfilteredBrake <= 1
        assert tele.mEngineRPM < tele.mEngineMaxRPM
    assert min(speeds) < 30 < 60 < max(speeds) and min(gears) >= 2 and max(gears) == 6
    demo_data.set_motion(session, demo_data.MOTION_PERIOD * 3)  # looped
    assert -tele.mLocalVel.z == pytest.approx(speeds[0])
    assert tele.mElapsedTime == pytest.approx(demo_data.ELAPSED + demo_data.MOTION_PERIOD * 3)  # clock runs on


# --- Screen view
def test_screen_geometry_helpers():
    assert rect_value(QRect(1, 2, 3, 4)) == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert bounds_of([QRect(0, 0, 1920, 1080), QRect(1920, -200, 1080, 1920)]) == QRect(0, -200, 3000, 1920)
    assert bounds_of([]) == QRect(0, 0, 1920, 1080)
    rects = {"a": QRect(0, 0, 100, 100), "b": QRect(50, 50, 100, 100), "c": QRect(100, 40, 50, 50),
             "d": QRect(500, 500, 10, 10)}
    assert overlapping(rects) == {"a", "b", "c"}  # c touches a only at an edge, but covers b
    assert overlapping({"a": QRect(0, 0, 10, 10), "b": QRect(10, 0, 10, 10)}) == set()  # side by side
    bounds = QRect(0, 0, 1920, 1080)
    assert clamped_position(QRect(0, 0, 200, 100), 1900, -50, bounds) == QPoint(1720, 0)
    assert clamped_position(QRect(0, 0, 3000, 100), 50, 50, bounds) == QPoint(0, 50)


def test_screen_view_layout_move_and_undo(page, monkeypatch):
    control = page.test_control
    control.widgets["speedometer"].rect = QRect(100, 100, 200, 100)
    control.widgets["brake_temperature"].rect = QRect(150, 150, 200, 100)  # covers speedometer
    told = []
    page.screenChanged.connect(lambda: told.append(1))
    page.set_active(True)
    assert not page.screenLayout  # cards: no layout made
    page.setViewMode(VIEW_SCREEN)
    assert cfg.application["show_overlay_screen_view"] and page.viewMode == VIEW_SCREEN and told
    layout = page.screenLayout
    assert layout["bounds"] == {"x": 0, "y": 0, "w": 1920, "h": 1080}
    assert layout["screens"] == [{"name": "Main", "primary": True, "x": 0, "y": 0, "w": 1920, "h": 1080}]
    assert {item["name"] for item in layout["overlays"]} == {"speedometer", "brake_temperature"}  # running only
    assert layout["overlaps"] == 2 and all(item["overlap"] for item in layout["overlays"])
    assert page._screen_timer.isActive()  # followed while shown
    page.setSearch("speed")  # filters apply
    assert [item["name"] for item in page.screenLayout["overlays"]] == ["speedometer"]
    assert page.screenLayout["overlaps"] == 0
    page.setSearch("")
    moved = []
    page.overlayMoved.connect(moved.append)
    page.moveOverlay("speedometer", 1900, 1000)  # kept on screen
    assert control.widgets["speedometer"].moves == [(QPoint(1720, 980), "Move")] and moved == ["Speedometer"]
    assert page.screenLayout["overlaps"] == 0
    page.moveOverlay("speedometer", 1720, 980)  # same place: nothing
    page.moveOverlay("fuel", 0, 0)  # not running: nothing
    assert len(control.widgets["speedometer"].moves) == 1 and moved == ["Speedometer"]
    undone = []
    from neopedal.widget import _edit_mode

    monkeypatch.setattr(_edit_mode.edit_mode(), "undo", lambda: undone.append(1) or True)
    page.undoMove()
    assert undone == [1]
    control.failing.add("speedometer")
    page._poll_screen()
    assert page.screenLayout["notRunning"] == 1
    page.set_active(False)
    assert not page._screen_timer.isActive()  # hidden: never followed
    page.setViewMode(VIEW_CARDS)
    assert not cfg.application["show_overlay_screen_view"] and cfg.application["show_overlay_previews"]


def test_view_modes_from_config(page):
    cfg.application["show_overlay_screen_view"] = True
    page.refresh()
    assert page.viewMode == VIEW_SCREEN and not page.gridView
    cfg.application["show_overlay_screen_view"] = False
    cfg.application["show_overlay_previews"] = False
    page.refresh()
    assert page.viewMode == VIEW_LIST
    page.setGridView(True)
    assert page.viewMode == VIEW_CARDS and cfg.application["show_overlay_previews"]


# --- Page
@pytest.fixture
def view(page, monkeypatch):
    from neopedal.ui.overlay_view import OverlayView

    widget = OverlayView(None, page.test_control)
    widget.resize(1000, 700)
    yield widget
    widget.close()
    widget.deleteLater()
    flush()


def item_texts(quick) -> set[str]:
    texts = set()
    stack = [quick.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def settle(count: int = 20):
    for _ in range(count):
        QCoreApplication.processEvents()


def test_qml_page_with_favorites_counts_badges_and_screen_view(view, monkeypatch):
    monkeypatch.setattr(overlay_backend, "render_preview", lambda name: solid("#336699"))
    monkeypatch.setattr(overlay_backend, "screen_rects", lambda: [("Main", QRect(0, 0, 1920, 1080), True)])
    cfg.user.setting["fuel"]["stream_visibility"] = "Stream Only"
    view.backend.refresh()
    view.backend.toggleFavorite("fuel")
    view.show()
    settle()
    assert not view.view.errors(), [error.toString() for error in view.view.errors()]
    texts = item_texts(view.view)
    assert "Favorites" in texts and "Stream Only" in texts
    assert any(text.startswith("Active") and text.endswith("2") for text in texts)  # state counts
    view.backend.setViewMode(VIEW_SCREEN)
    settle()
    assert not view.view.errors()
    assert "Layout Editor" in item_texts(view.view)
    view.backend.setViewMode(VIEW_LIST)
    settle()
    texts = item_texts(view.view)
    assert any(OVERLAY_DESCRIPTIONS["fuel"] in text for text in texts)  # category & description
    view.backend.setViewMode(VIEW_CARDS)
    cfg.user.setting["fuel"]["stream_visibility"] = "Screen & Stream"


def test_qml_page_french(page):
    from neopedal import i18n
    from neopedal.ui.overlay_view import OverlayView

    i18n.set_language("Français")
    try:
        widget = OverlayView(None, page.test_control)
        widget.show()
        settle(10)
        texts = item_texts(widget.view)
        assert "Favoris" in texts and "Favorites" not in texts
        assert i18n.trm("3 overlays overlap") == "3 overlays se chevauchent"
        assert i18n.trm("Overlay moved: Carburant") == "Overlay déplacé : Carburant"
        assert i18n.trm("2 enabled overlays not running") == "2 overlays activés non démarrés"
        widget.close()
        widget.deleteLater()
        flush()
    finally:
        i18n.set_language("English")


def test_hidden_options_not_in_config_page():
    from neopedal.template.setting_global import GLOBAL_DEFAULT
    from neopedal.ui.config import HIDDEN_OPTIONS

    for key in ("show_overlay_screen_view", "overlays_sort_order", "favorite_overlays", "recent_overlays"):
        assert key in GLOBAL_DEFAULT["application"] and key in HIDDEN_OPTIONS["application"]


# --- Played previews: whole lap of motion, Overlay Options preview
def test_set_motion_moves_wheels_around_simulated_values(ui_env):
    from neopedal import demo_data

    session = demo_data.DemoSession(cfg.user.setting["standings"])
    wheel = session.data.telemetry.telemInfo[demo_data.PLAYER].mWheels[0]
    still = (wheel.mBrakeTemp, wheel.mTireLoad, wheel.mRideHeight)
    seen = {"brake": [], "load": [], "pressure": []}
    for step in range(30):
        demo_data.set_motion(session, step * demo_data.MOTION_PERIOD / 30)
        seen["brake"].append(wheel.mBrakeTemp)
        seen["load"].append(wheel.mTireLoad)
        seen["pressure"].append(wheel.mBrakePressure)
    assert max(seen["brake"]) - min(seen["brake"]) > 100  # heats while braking, cools after
    assert min(seen["brake"]) >= still[0] and max(seen["load"]) > still[1] > min(seen["load"])
    assert max(seen["pressure"]) > 0.8 and min(seen["pressure"]) == 0
    demo_data.set_motion(session, 0.0)  # first picture just before braking: something moves at once
    first = (wheel.mBrakePressure, session.data.telemetry.telemInfo[demo_data.PLAYER].mUnfilteredThrottle)
    demo_data.set_motion(session, 0.5)
    assert (wheel.mBrakePressure, session.data.telemetry.telemInfo[demo_data.PLAYER].mUnfilteredThrottle) != first
    pits = demo_data.DemoSession(cfg.user.setting["standings"], "pits")
    tele = pits.data.telemetry.telemInfo[demo_data.PLAYER]
    demo_data.set_motion(pits, 1.0)
    assert tele.mSpeedLimiterActive and -tele.mLocalVel.z == pytest.approx(16.6)  # rolls at the limiter


class OptionsHost:
    """Overlay Options page host: questions answered yes, nothing else needed here"""

    def confirm(self, text):
        return True

    def notify(self, text):
        pass

    def applied(self, names):
        pass


class OptionsControl:
    def __init__(self):
        from neopedal.template.setting_widget import WIDGET_DEFAULT

        self.names = list(WIDGET_DEFAULT)

    def reload(self, name):
        pass


@pytest.fixture
def options(ui_env):
    from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend

    backend = OverlayOptionsBackend(None, OptionsHost(), OptionsControl())
    yield backend
    backend.close()
    backend.deleteLater()
    flush()


def test_options_preview_played_and_restarted_on_edits(options, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(overlay_backend, "perf_counter", lambda: clock[0])
    options.setPreviewPlaying(True)
    options.selectOverlay("pedal")
    options.set_active(True)
    options.render_preview()
    assert options.live.name == "pedal" and options.previewAnimated
    options.live._next()
    first = options.liveUrl
    assert first.startswith("image://overlaypreview/")
    clock[0] += 2.0  # braking
    options.live._next()
    assert options.liveUrl not in ("", first)
    options.setNumber("pedal/bar_length", cfg.user.setting["pedal"]["bar_length"] + 20)
    options.render_preview()  # new values: played again from a new source, last picture kept meanwhile
    assert options.live._live is None and options.liveUrl != "" and options.live.name == "pedal"
    options.live._next()
    options.setPreviewScenario(2)  # in pits
    options.render_preview()
    assert options.live._live is None
    options.setPreviewPlaying(False)
    assert options.live.name == "" and options.liveUrl == "" and not options.previewPlaying
    options.setPreviewPlaying(True)
    options.selectOverlay("relative")  # driver list: sample race drawn once, not played
    options.render_preview()
    options.live._next()
    assert not options.previewAnimated and options.liveUrl == ""
    options.selectOverlay("pedal")
    options.render_preview()
    assert options.live.name == "pedal"
    options.set_active(False)  # hidden: never played
    assert options.live.name == ""
    flush()


def test_card_hover_kept_over_its_buttons():
    """Hover of a card is a passive handler: pointer over name, star, settings or switch keeps the overlay played"""
    from neopedal.ui.quick import qml_path

    with open(qml_path("OverlayCard.qml"), encoding="utf-8") as file:
        text = file.read()
    assert "readonly property bool hovered: cardHover.hovered" in text and "HoverHandler { id: cardHover }" in text
