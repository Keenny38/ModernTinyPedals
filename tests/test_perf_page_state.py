"""Qt Quick page performance: page state (timers stop while hidden), JavaScript i18n.tr, MSAA per page"""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from tinypedal.setting import cfg


def process_events(seconds: float = 0.0):
    end = time.monotonic() + seconds
    while True:
        QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.005)


def delete_now(widget):
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def qml_warnings(monkeypatch):
    """QML warnings (binding & type errors) of pages created in the test

    From QQmlEngine.warnings, not a Python Qt message handler: the QML loader thread logging while
    the main thread loads a page (interpreter lock held) would deadlock.
    """
    from PySide6.QtQuickWidgets import QQuickWidget

    warnings: list[str] = []
    set_source = QQuickWidget.setSource

    def watched_source(view, url):
        engine = view.engine()
        engine.setOutputWarningsToStandardError(False)
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        set_source(view, url)

    monkeypatch.setattr(QQuickWidget, "setSource", watched_source)
    return warnings


# --- Page state
def test_page_state_follows_show_hide_and_minimize():
    from tinypedal.ui.quick import PageState

    window = QWidget()
    stack = QStackedWidget(window)
    other = QWidget()
    page = QWidget()
    stack.addWidget(other)
    stack.addWidget(page)
    state = PageState(page)
    changes = []
    state.activeChanged.connect(lambda: changes.append(state.active))
    try:
        assert not state.active  # not shown yet
        stack.setCurrentWidget(page)
        window.show()
        process_events()
        assert state.active
        stack.setCurrentWidget(other)  # stacked page in background
        process_events()
        assert not state.active
        stack.setCurrentWidget(page)
        process_events()
        assert state.active
        window.showMinimized()
        process_events(0.05)
        assert not state.active
        window.showNormal()
        process_events(0.05)
        assert state.active
        window.hide()  # tray
        process_events()
        assert not state.active
        assert changes == [True, False, True, False, True, False]
    finally:
        window.close()
        delete_now(window)


def test_page_state_follows_moved_page():
    from tinypedal.ui.quick import PageState

    first, second = QWidget(), QWidget()
    page = QWidget(first)
    state = PageState(page)
    try:
        first.show()
        second.show()
        process_events()
        assert state.active
        page.setParent(second)  # page moved to another window (tab view rebuilt): hidden until shown
        process_events()
        assert not state.active
        page.show()
        process_events()
        assert state.active
        second.showMinimized()  # new window watched
        process_events(0.05)
        assert not state.active
        first.showMinimized()
        second.showNormal()
        process_events(0.05)
        assert state.active
    finally:
        delete_now(first)
        delete_now(second)


# --- i18n.tr in JavaScript
@pytest.fixture
def french():
    from tinypedal import i18n

    i18n.set_language("Français")
    yield i18n
    i18n.set_language("English")


def js_translations(texts: list, method: str = "tr") -> list:
    from tinypedal.ui.quick import Translator, translator_copy

    engine = QQmlEngine()
    translator = Translator()
    copy = translator_copy(engine, translator)
    assert copy is not translator  # JavaScript object made
    engine.rootContext().setContextProperty("i18n", copy)
    component = QQmlComponent(engine)
    component.setData(
        f"import QtQuick\nQtObject {{ required property var texts; "
        f"readonly property var out: texts.map(function(t) {{ return i18n.{method}(t) }}) }}".encode(),
        QUrl("test_tr.qml"))
    obj = component.createWithInitialProperties({"texts": texts})
    assert obj is not None, component.errorString()
    result = obj.property("out")
    result = result.toVariant() if hasattr(result, "toVariant") else result
    obj.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return list(result)


def test_js_tr_matches_python_tr(french):
    from tinypedal.i18n.fr import TRANSLATION

    texts = [*TRANSLATION, "Not a translated text", "", "toString", "constructor", "__proto__"]
    assert js_translations(texts) == [french.tr(text) for text in texts]
    assert js_translations(["Clean only"]) == ["Tours propres"]


def test_js_tr_english_and_numbers():
    assert js_translations(["Clean only", 3, "Lap"]) == ["Clean only", "3", "Lap"]


def test_js_trm_uses_python_rules(french):
    texts = ["Lap 3", "No rule for this text"]
    assert js_translations(texts, "trm") == [french.trm(text) for text in texts]


# --- Pages: MSAA only with GPU drawn lines, no QML warning
def test_pages_without_gpu_lines_have_no_msaa(ui_env):
    from tinypedal.ui.driver_stats_viewer import DriverStatsViewer
    from tinypedal.ui.race_results_viewer import RaceResultsViewer

    for viewer_class in (DriverStatsViewer, RaceResultsViewer):
        viewer = viewer_class(None)
        try:
            assert viewer.view.format().samples() <= 0, viewer_class.__name__
        finally:
            viewer.close()
            delete_now(viewer)


def test_track_map_play_stops_while_hidden(ui_env, qml_warnings):
    from tests.test_track_map_viewer import write_map
    from tinypedal.ui.track_map_viewer import TrackMapViewer

    write_map(cfg.path.track_map)
    viewer = TrackMapViewer(None, cfg.path.track_map, "Ring")
    try:
        viewer.resize(900, 700)
        viewer.show()
        process_events(0.1)
        root, backend = viewer.view.rootObject(), viewer.backend
        state = viewer.view.rootContext().contextProperty("pageState")
        assert state.active and backend.loaded
        backend.setPosition(10.0)
        root.setProperty("playing", True)
        process_events(0.3)
        assert backend.position > 10.0  # moves every frame
        viewer.hide()
        process_events(0.05)
        assert not state.active
        position = backend.position
        process_events(0.3)
        assert backend.position == position  # no frame step while hidden
        viewer.show()
        process_events(0.3)
        assert backend.position != position
        root.setProperty("playing", False)
        process_events(0.05)
        shown = list(qml_warnings)  # page closing logs its own warnings (backend freed first), not tested here
    finally:
        viewer.close()
        delete_now(viewer)
    assert not [text for text in shown if ".qml" in text], shown


PAGES = (
    ("driver_stats_viewer", "DriverStatsViewer"),
    ("race_results_viewer", "RaceResultsViewer"),
    ("race_calculator", "RaceCalculator"),
    ("stream_overlay_view", "StreamOverlaysView"),
    ("spectate_view", "SpectateList"),
    ("overlay_view", "OverlayView"),
    ("game_replays", "GameReplays"),
)


@pytest.mark.parametrize(("module_name", "class_name"), PAGES)
def test_pages_shown_hidden_without_qml_warning(ui_env, monkeypatch, qml_warnings, module_name, class_name):
    """Pages reading pageState load, hide & show again without QML warning"""
    from importlib import import_module

    from tests.test_game_info import FakeGame
    from tinypedal.ui import game_rest
    from tinypedal.ui._common import BaseDialog

    monkeypatch.setattr(BaseDialog, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(game_rest, "GameConnection", FakeGame().connection)  # no real game request
    window = QWidget()
    try:
        page = getattr(import_module(f"tinypedal.ui.{module_name}"), class_name)(window)
        page.resize(1100, 750)
        window.resize(1100, 750)
        window.show()
        page.show()
        process_events(0.3)
        state = page.findChildren(QObject)  # page state of the QML view
        state = [item for item in state if type(item).__name__ == "PageState"]
        assert state and state[0].active
        page.hide()
        process_events(0.1)
        assert not state[0].active
        page.show()
        process_events(0.2)
        assert state[0].active
        shown = list(qml_warnings)
    finally:
        window.close()
        delete_now(window)
    assert not [text for text in shown if ".qml" in text], shown
