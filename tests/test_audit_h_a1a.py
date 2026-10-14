"""Audit h, lot a1a: game requests (callback errors, delivery after page close, shared workers),
pages released on Esc, Director & Race Calculator kept while main window hidden"""

from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject

from neopedal.setting import cfg


def pump(seconds: float = 0.0):
    end = time.monotonic() + seconds
    while True:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if time.monotonic() >= end:
            return
        time.sleep(0.005)


def wait_until(condition, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return True


# --- Fix 1: callback raising: logged, on_failed called (owner polls again)
def test_callback_error_calls_on_failed(ui_env, caplog):
    from neopedal.ui import game_rest

    parent = QObject()
    failures: list = []
    received: list = []

    def callback(value):
        received.append(value)
        if value == "boom":
            raise ValueError("broken answer")

    request = game_rest.GameRequest(parent, (), callback, lambda: failures.append(request.busy))
    with caplog.at_level(logging.ERROR, logger=game_rest.logger.name):
        assert request.start(lambda: "boom")
        assert wait_until(lambda: failures)
    assert received == ["boom"] and failures == [False]  # not busy any more: owner's schedule re-arms its poll
    assert any("failed" in record.getMessage() and record.exc_info for record in caplog.records)
    assert request.start(lambda: "ok")
    assert wait_until(lambda: not request.busy)
    assert received[-1] == "ok" and len(failures) == 1
    parent.deleteLater()
    pump()


def test_callback_error_without_on_failed_logged(ui_env, caplog):
    from neopedal.ui import game_rest

    parent = QObject()

    def callback(value):
        raise RuntimeError("broken")

    request = game_rest.GameRequest(parent, (), callback)
    with caplog.at_level(logging.ERROR, logger=game_rest.logger.name):
        request.start(lambda: 1)
        assert wait_until(lambda: not request.busy)
    assert any(record.exc_info for record in caplog.records)
    assert request.start(lambda: 2)  # next request can start
    assert wait_until(lambda: not request.busy)
    parent.deleteLater()
    pump()


def test_on_failed_error_logged_not_raised(ui_env, caplog):
    from neopedal.ui import game_rest

    parent = QObject()

    def broken_failed():
        raise RuntimeError("schedule broken")

    request = game_rest.GameRequest(parent, (), lambda value: None, broken_failed)
    with caplog.at_level(logging.ERROR, logger=game_rest.logger.name):
        request.start(lambda: 1 / 0)
        assert wait_until(lambda: not request.busy)
    messages = [record.getMessage() for record in caplog.records]
    assert any("request failed" in text for text in messages) and len(caplog.records) >= 2
    parent.deleteLater()
    pump()


def test_director_poll_rearmed_after_callback_error(ui_env, monkeypatch):
    """Director re-arms its state poll on the last line of received_state: on_failed (schedule) re-arms it"""
    from neopedal.ui import game_rest

    class Page(QObject):
        def __init__(self):
            super().__init__()
            self.scheduled = 0
            self.request_state = game_rest.GameRequest(self, (), self.received_state, self.schedule)

        def schedule(self):
            if not self.request_state.busy:
                self.scheduled += 1

        def received_state(self, state):
            state["missing"]  # unexpected answer
            self.schedule()

    page = Page()
    page.request_state.start(dict)
    assert wait_until(lambda: page.scheduled == 1)
    page.deleteLater()
    pump()


# --- Fix 2: result handed over on the UI thread, dropped once the request is deleted (page closed)
def test_result_dropped_after_request_deleted(ui_env):
    from neopedal.ui import game_rest

    parent = QObject()
    received: list = []
    release = threading.Event()
    started = threading.Event()

    def work():
        started.set()
        release.wait(5)
        return "late"

    request = game_rest.GameRequest(parent, (), received.append)
    request.start(work)
    assert started.wait(5)
    parent.deleteLater()
    pump()  # request deleted while its job runs
    release.set()
    pump(0.2)
    assert received == []


def test_requests_share_workers(ui_env):
    """No thread kept per request: many requests run on the shared game request workers"""
    from neopedal.ui import game_rest

    parent = QObject()
    received: list = []
    requests = [game_rest.GameRequest(parent, (), received.append) for _ in range(12)]
    for request in requests:
        request.start(lambda: threading.current_thread().name)
    assert wait_until(lambda: len(received) == 12)
    assert len(set(received)) <= game_rest.GAME_WORKERS
    assert all(name.startswith(game_rest.WORKER_LABEL) for name in received)
    parent.deleteLater()
    pump()


def test_worker_never_holds_request(ui_env):
    """Default work (resources) does not reference the request: nothing of the page freed on a worker"""
    from neopedal.ui import game_rest

    parent = QObject()
    request = game_rest.GameRequest(parent, ("/a",), lambda value: None)
    request.start()
    assert wait_until(lambda: not request.busy)
    parent.deleteLater()
    pump()


# --- Fix 3: Esc (reject) & close release the backend once
def _count_release(monkeypatch, backend_type) -> list:
    calls: list = []
    original = backend_type.release

    def release(self, *args, **kwargs):
        calls.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(backend_type, "release", release)
    return calls


def _race_calculator(monkeypatch):
    from neopedal.module_info import minfo
    from neopedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    monkeypatch.setattr(race_calculator.RaceCalculator, "warn", lambda self, text: None)
    return race_calculator.RaceCalculator(None)


def _page_factories():
    def results(monkeypatch):
        from neopedal.ui.race_results_viewer import RaceResultsViewer

        return RaceResultsViewer(None)

    def stream(monkeypatch):
        from neopedal.ui.stream_overlay_view import StreamOverlaysView

        return StreamOverlaysView(None)

    def track_map(monkeypatch):
        from neopedal.ui.track_map_viewer import TrackMapViewer

        return TrackMapViewer(None)

    def director(monkeypatch):
        from neopedal.ui.broadcast_director import BroadcastDirector

        return BroadcastDirector(None)

    return {"results": results, "stream": stream, "track_map": track_map, "director": director,
            "race_calculator": _race_calculator}


@pytest.mark.parametrize("name", list(_page_factories()))
@pytest.mark.parametrize("how", ["esc", "close"])
def test_page_backend_released_once(ui_env, monkeypatch, name, how):
    page = _page_factories()[name](monkeypatch)
    calls = _count_release(monkeypatch, type(page.backend))
    view = page.ensure_view() if hasattr(page, "ensure_view") else page.view
    page.show()
    pump()
    if how == "esc":
        page.reject()  # Esc: QDialog.done() deletes without closeEvent (Qt >= 6.3)
    else:
        assert page.close()
    assert len(calls) == 1
    assert view.source().isEmpty()  # QML unloaded with the backend
    page.close()  # closed again (deleted later): never released twice
    pump()
    assert len(calls) == 1


@pytest.mark.parametrize("how", ["esc", "close"])
def test_option_finder_view_unloaded(ui_env, how):
    from neopedal.ui.option_finder import OptionFinder

    page = OptionFinder(None)
    view = page.view
    page.show()
    pump()
    if how == "esc":
        page.reject()
    else:
        assert page.close()
    assert view.source().isEmpty()
    pump()


def test_default_free_page_ignores_other_views(ui_env):
    """free_page default: only a Qt Quick view is unloaded, backend without release left alone"""
    from PySide6.QtWidgets import QTableWidget

    from neopedal.ui._common import BaseDialog

    class Page(BaseDialog):
        EMBED_IN_APP = False

        def __init__(self):
            super().__init__(None)
            self.view = QTableWidget(self)
            self.backend = SimpleNamespace()

    page = Page()
    page.show()
    page.reject()
    pump()


# --- Fix 4: Director & Race Calculator pages kept while window hidden (option)
class _Dialog:
    KEEP_WHEN_HIDDEN = False

    def keep_when_hidden(self):
        return self.KEEP_WHEN_HIDDEN


class _Director(_Dialog):
    KEEP_WHEN_HIDDEN = True


class _DirectorOff(_Director):
    def keep_when_hidden(self):
        return False


def _tab_view(*dialogs):
    pages = [SimpleNamespace(dialog=dialog(), restored=True, has_unsaved_changes=lambda: False)
             for dialog in dialogs]
    closed: list = []

    def close_all_pages():
        closed.append(True)
        return True

    return SimpleNamespace(
        dialog_pages=lambda: pages, open_page_paths=lambda: [f"x.{index}" for index in range(len(pages))],
        track_pages=True, close_all_pages=close_all_pages, _releasing_pages=False, _deferred_pages=None,
        closed=closed)


def test_live_pages_kept_while_hidden(ui_env, monkeypatch):
    from neopedal.ui.app import TabView

    monkeypatch.setitem(cfg.application, "keep_director_and_calculator_running_while_hidden", True)
    view = _tab_view(_Dialog, _Director)
    assert not TabView.release_tool_pages(view) and not view.closed
    view = _tab_view(_Dialog)
    assert TabView.release_tool_pages(view) and view.closed  # other restored pages still released
    view = _tab_view(_Dialog, _DirectorOff)
    assert TabView.release_tool_pages(view) and view.closed  # director turned off: released too
    monkeypatch.setitem(cfg.application, "keep_director_and_calculator_running_while_hidden", False)
    view = _tab_view(_Dialog, _Director)
    assert TabView.release_tool_pages(view) and view.closed and view._deferred_pages == ["x.0", "x.1"]


def test_live_pages_flagged():
    from neopedal.ui._common import BaseDialog
    from neopedal.ui.broadcast_director import BroadcastDirector
    from neopedal.ui.race_calculator import RaceCalculator

    assert BroadcastDirector.KEEP_WHEN_HIDDEN and RaceCalculator.KEEP_WHEN_HIDDEN
    assert not BaseDialog.KEEP_WHEN_HIDDEN


def test_keep_option_default_and_listed():
    import re

    from neopedal import regex_pattern as rxp
    from neopedal.i18n.options import load_data
    from neopedal.template.setting_global import GLOBAL_DEFAULT
    from neopedal.ui.quick.settings_backend import CATEGORIES

    key = "keep_director_and_calculator_running_while_hidden"
    assert GLOBAL_DEFAULT["application"][key] is True
    assert re.search(rxp.CFG_BOOL, key)
    assert any(key in keys for category in CATEGORIES for _, keys in category.groups)
    assert "Régie de course" in load_data("fr_options.json")[key]
