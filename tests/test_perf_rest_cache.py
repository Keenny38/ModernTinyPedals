"""Shared game Rest API cache: one request per route at a time, answers reused for a short time, stale ones
dropped; game requests of pages parsed in background, slow page callbacks reported; connector answers shared"""

import asyncio
import logging
import threading
import time

import pytest

from neopedal import game_rest_cache, perf_monitor
from neopedal.game_rest_cache import NO_ANSWER, GameRestCache

ADDRESS = ("localhost", 6397)


class FakeGame:
    """Game answers by route, requests counted"""

    def __init__(self, answers: dict | None = None):
        self.answers = dict(answers or {})
        self.asked: list[str] = []
        self.release = threading.Event()
        self.release.set()

    def fetch(self, address, route, timeout):
        self.asked.append(route)
        assert self.release.wait(5)
        body = self.answers.get(route)
        return (0, b"") if body is None else (200, body)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def game():
    return FakeGame({"/rest/a": b'{"x": 1}', "/rest/b": b"[1, 2]"})


def test_answer_reused_until_max_age(game):
    clock = Clock()
    cache = GameRestCache(game.fetch, clock)
    first = cache.answer("/rest/a", 1.0, ADDRESS)
    assert first.ok and first.body == b'{"x": 1}' and game.asked == ["/rest/a"]
    clock.now += 0.5
    assert cache.answer("/rest/a", 1.0, ADDRESS) is first and len(game.asked) == 1
    assert cache.fresh("/rest/a", 1.0, ADDRESS) is first
    assert cache.fresh("/rest/a", 0.2, ADDRESS) is None  # too old for this reader, never asks
    clock.now += 1.0
    assert cache.answer("/rest/a", 1.0, ADDRESS) is not first and len(game.asked) == 2
    # Other address: other answers (rF2 connector, game of another computer)
    cache.answer("/rest/a", 1.0, ("192.168.1.20", 6397))
    assert len(game.asked) == 3
    # Game not running: no answer kept as well (other readers do not wait for a connection each)
    missing = cache.answer("/rest/none", 1.0, ADDRESS)
    assert missing.status == 0 and not missing.ok
    assert cache.answer("/rest/none", 1.0, ADDRESS) is missing
    cache.forget("/rest/a")
    cache.answer("/rest/a", 1.0, ADDRESS)
    assert game.asked.count("/rest/a") == 4
    assert cache.requests == len(game.asked)


def test_single_request_for_concurrent_callers(game):
    cache = GameRestCache(game.fetch)
    game.release.clear()
    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.answer("/rest/a", 1.0, ADDRESS)))
               for _ in range(6)]
    for thread in threads:
        thread.start()
    end = time.monotonic() + 5
    while not game.asked and time.monotonic() < end:
        time.sleep(0.01)
    time.sleep(0.05)  # others waiting for the request in progress
    game.release.set()
    for thread in threads:
        thread.join(5)
    assert game.asked == ["/rest/a"] and len(results) == 6
    assert all(result is results[0] for result in results)


def test_waiter_gets_kept_answer_when_request_hangs(game):
    cache = GameRestCache(game.fetch, timeout=0.05)
    old = cache.store("/rest/a", 200, b"old", ADDRESS)
    game.release.clear()
    asking = threading.Thread(target=lambda: cache.answer("/rest/a", 0.0, ADDRESS))
    asking.start()
    end = time.monotonic() + 5
    while not game.asked and time.monotonic() < end:
        time.sleep(0.01)
    assert cache.answer("/rest/a", 0.0, ADDRESS) is old  # waited a bounded time, never stuck
    game.release.set()
    asking.join(5)


def test_stale_answers_dropped(game):
    clock = Clock()
    cache = GameRestCache(game.fetch, clock)
    cache.answer("/rest/a", 1.0, ADDRESS)
    cache.store("/rest/b", 200, b"[3]", ADDRESS)
    clock.now += game_rest_cache.STALE_AGE - 1
    cache.answer("/rest/c", 1.0, ADDRESS)  # cache used: old answers checked
    assert cache.fresh("/rest/a", 1e9, ADDRESS) is not None  # not stale yet
    clock.now += game_rest_cache.PRUNE_EVERY  # checked at most every PRUNE_EVERY seconds
    cache.answer("/rest/c", 1.0, ADDRESS)
    assert cache.fresh("/rest/a", 1e9, ADDRESS) is None and cache.fresh("/rest/b", 1e9, ADDRESS) is None
    assert cache.fresh("/rest/c", 1e9, ADDRESS) is not None  # asked lately: kept
    clock.now += game_rest_cache.STALE_AGE + 1
    cache.prune()  # periodic call: nothing kept once nobody asks
    assert not cache._routes


def test_json_new_object_each_call(game):
    cache = GameRestCache(game.fetch)
    first = cache.json("/rest/a", 1.0, ADDRESS)
    first["x"] = 5
    assert cache.json("/rest/a", 1.0, ADDRESS) == {"x": 1} and len(game.asked) == 1
    assert cache.json("/rest/none", 1.0, ADDRESS) is None


def test_access_disabled_asks_nothing(game, monkeypatch):
    cache = GameRestCache(game.fetch)
    monkeypatch.setattr(game_rest_cache, "lmu_address", lambda: None)
    assert cache.answer("/rest/a") is NO_ANSWER and cache.json("/rest/a") is None
    assert cache.fresh("/rest/a") is None
    assert not game.asked


def test_fetch_error_is_no_answer():
    def broken(address, route, timeout):
        raise RuntimeError("broken")

    cache = GameRestCache(broken)
    assert cache.answer("/rest/a", 1.0, ADDRESS).status == 0


# Pages
def wait_requests(*requests, timeout=5.0):
    from PySide6.QtCore import QCoreApplication

    end = time.monotonic() + timeout
    while any(request.busy for request in requests) and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert not any(request.busy for request in requests)


def test_request_game_shares_answers(game, monkeypatch):
    from neopedal.ui import game_rest

    monkeypatch.setattr(game_rest, "game_address", lambda: ADDRESS)
    monkeypatch.setattr(game_rest_cache.rest_cache, "fetch", game.fetch)
    game_rest_cache.rest_cache.forget()
    try:
        assert game_rest.request_game("/rest/a") == {"x": 1}
        assert game_rest.request_game("/rest/a") == {"x": 1} and game.asked == ["/rest/a"]
        game_rest_cache.rest_cache.store("/rest/b", 200, b"[3]", ADDRESS)  # read by connector
        assert game_rest.request_game("/rest/b") == [3] and game.asked == ["/rest/a"]
        assert game_rest.request_game("/rest/b", max_age=0.0) == [1, 2] and game.asked[-1] == "/rest/b"
        monkeypatch.setattr(game_rest, "game_address", lambda: None)
        assert game_rest.request_game("/rest/a") is None
    finally:
        game_rest_cache.rest_cache.forget()


def test_game_request_parsed_in_background(monkeypatch):
    from PySide6.QtCore import QObject

    from neopedal.ui import game_rest

    monkeypatch.setattr(game_rest, "request_game", {"/a": [3, 1, 2]}.get)
    parent = QObject()
    threads = []

    def parse(answers):
        threads.append(threading.current_thread())
        return tuple(sorted(answers[0]))

    received: list = []
    request = game_rest.GameRequest(parent, ("/a",), received.append, parse=parse)
    assert request.start()
    wait_requests(request)
    assert received == [(1, 2, 3)] and threads[0] is not threading.main_thread()
    assert request.start(lambda: [[5, 4]])  # own work parsed as well
    wait_requests(request)
    assert received[-1] == (4, 5)
    # Without parse: as before
    plain: list = []
    request = game_rest.GameRequest(parent, ("/a",), plain.append)
    request.start()
    wait_requests(request)
    assert plain == [[[3, 1, 2]]]


def test_game_request_parse_held_weakly(monkeypatch):
    import gc
    import weakref

    from PySide6.QtCore import QObject

    from neopedal.ui import game_rest

    class Page:
        def received(self, value):
            pass

        def parse(self, value):
            return value

    page = Page()
    parent = QObject()
    request = game_rest.GameRequest(parent, (), page.received, parse=page.parse)
    alive = weakref.ref(page)
    del page
    gc.collect()
    assert alive() is None
    assert request.start(lambda: 1)  # page gone: nothing parsed, nothing called
    wait_requests(request)


def test_slow_callback_reported(monkeypatch, caplog):
    from PySide6.QtCore import QObject

    from neopedal.ui import game_rest

    clock = iter([0.0, 0.040, 1.0, 1.040, 2.0, 2.001])
    monkeypatch.setattr(perf_monitor, "perf_counter", lambda: next(clock))
    perf_monitor._slow_calls.clear()
    recorded = []
    monkeypatch.setattr(perf_monitor.PerfMonitor, "enabled", True)
    monkeypatch.setattr(perf_monitor.PerfMonitor, "record", classmethod(
        lambda cls, name, event, seconds: recorded.append((name, event, round(seconds, 3)))))

    class Page(QObject):
        def received(self, value):
            pass

    page = Page()
    request = game_rest.GameRequest(page, (), page.received)
    with caplog.at_level(logging.DEBUG, logger="neopedal.perf_monitor"):
        request._done(1)
        request._done(2)
        request._done(3)
    slow = [record for record in caplog.records if "slow callback" in record.getMessage()]
    assert [record.levelno for record in slow] == [logging.WARNING, logging.DEBUG]  # once a minute, then debug
    assert "Page.received" in slow[0].getMessage() and "40 ms" in slow[0].getMessage()
    assert [(name, event.rsplit(".", 2)[-2:], seconds) for name, event, seconds in recorded] == [
        ("game_request", ["Page", "received"], 0.04), ("game_request", ["Page", "received"], 0.04),
        ("game_request", ["Page", "received"], 0.001)]


def test_timed_call_returns_and_raises():
    assert perf_monitor.timed_call("x", "y", lambda a, b: a + b, 1, 2) == 3
    with pytest.raises(ZeroDivisionError):
        perf_monitor.timed_call("x", "y", lambda: 1 / 0)


# Connector
class FakeConnection:
    def __init__(self, body: bytes):
        self.body = body
        self.gets = 0

    async def get(self, request):
        self.gets += 1
        return self.body


def connector_with(data):
    from neopedal.adapter.restapi_connector import ResOutput, RestAPIConnector, RestAPITask

    task = RestAPITask("/rest/test", (ResOutput("value", 0, lambda value, default: value, ("v",)),), "", True, 0.2)
    connector = RestAPIConnector((task,), data)
    connector.setConnection({"restapi_update_interval": 100, "url_host": "localhost", "url_port": 6397,
                             "enable_restapi_access": True})
    return connector, task


def test_connector_answers_shared(monkeypatch):
    from types import SimpleNamespace

    from neopedal.adapter import restapi_connector

    cache = GameRestCache(lambda *args: (_ for _ in ()).throw(AssertionError("never asked")))
    monkeypatch.setattr(restapi_connector, "rest_cache", cache)
    data = SimpleNamespace(value=0)
    connector, task = connector_with(data)
    connection = FakeConnection(b'{"v": 7}')
    asyncio.run(connector.output_resource(connection, b"", task.path, task.outputs, -1))
    assert data.value == 7 and connection.gets == 1
    assert cache.fresh(task.path, 1.0, ADDRESS).body == b'{"v": 7}'  # pages read it without asking
    # Answer read by a page moments ago: used instead of asking again
    cache.store(task.path, 200, b'{"v": 8}', ADDRESS)
    asyncio.run(connector.output_resource(connection, b"", task.path, task.outputs, -1, 0.1))
    assert data.value == 8 and connection.gets == 1
    # Not shared (age 0): asked
    asyncio.run(connector.output_resource(connection, b"", task.path, task.outputs, -1))
    assert data.value == 7 and connection.gets == 2
    # Error status (empty body) never shared
    cache.forget()
    asyncio.run(connector.output_resource(FakeConnection(b""), b"", task.path, task.outputs, -1))
    assert cache.fresh(task.path, 1.0, ADDRESS) is None
    # First answer (until available) shared too
    assert asyncio.run(connector.update_once(connection, b"", task.path, task.outputs))
    assert cache.fresh(task.path, 1.0, ADDRESS).body == b'{"v": 7}'
