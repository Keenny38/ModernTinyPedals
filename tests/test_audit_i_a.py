"""Audit I lot A: driver ranks lookups by name & memo, serial only on real changes, rank history kept in memory &
trimmed, storage file not read again for online ranks, RaceControl sign in single flight"""

import json
import os
import threading
import time

import pytest

from neopedal.process import driver_ranks as dr
from neopedal.process import field_ranks as fr
from neopedal.process import raceos
from tests.test_driver_ranks import storage_text
from tests.test_home_view import home  # noqa: F401
from tests.test_online_ranks import AUTH, PLAYER, STEAM, FakeHttp, FakeOnline

NOON = time.mktime((2026, 10, 18, 12, 0, 0, 0, 0, -1))  # local noon: + a few minutes stays the same day


def counted(calls: list, function):
    """function adding its arguments to calls"""
    def call(*args):
        calls.append(args)
        return function(*args)
    return call


def ranks_of(name, driver=("Silver", 2, 40), steam_id=""):
    return dr.DriverRanks(name, steam_id, "", "", dr.Rank(*driver), None)


# --- B3: index by name & memo of rank_info lookups
def test_find_name_same_as_find_driver():
    drivers = [ranks_of("Keenny Hess"), ranks_of("keenny hess", ("Gold", 1, 0)), ranks_of("Flo"), ranks_of("")]
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()))
    watcher.drivers = drivers  # set without check: index made by first lookup
    for name in ("Keenny Hess", "KEENNY HESS ", " flo", "", "  ", "Nobody"):
        assert watcher.find_name(name) is dr.find_driver(drivers, name=name)
    assert watcher.find_name("keenny hess") is drivers[0]  # first one kept
    assert watcher.team_ranks("FLO") is drivers[2]
    watcher.drivers = [ranks_of("Other")]  # list replaced: index made again
    assert watcher.find_name("Flo") is None and watcher.find_name("other") is not None


@pytest.fixture
def lookups(monkeypatch):
    """rank_info lookups on fake ranks: drivers of watcher & field ranks set by test"""
    from neopedal import rank_info

    monkeypatch.setattr(rank_info.ranks, "poll", lambda: None)
    monkeypatch.setattr(rank_info.ranks, "drivers", [ranks_of("Keenny Hess")])
    monkeypatch.setattr(rank_info.field, "poll", lambda names: None)
    monkeypatch.setattr(rank_info.field, "_ranks", {"austin martin": ranks_of("Austin Martin", ("Bronze", 3, 0))})
    found: list[tuple] = []
    monkeypatch.setattr(rank_info.ranks, "find_name", counted(found, rank_info.ranks.find_name))
    return rank_info, found


def test_driver_ranks_memo_until_ranks_change(lookups, monkeypatch):
    rank_info, found = lookups
    assert rank_info.driver_ranks("Keenny Hess#12").driver.text == "Silver 2"
    assert rank_info.driver_ranks("Austin Martin#9566").driver.text == "Bronze 3"
    assert rank_info.driver_ranks("Nobody") is None
    for _ in range(3):  # each update: memo, nothing looked for again
        assert rank_info.driver_ranks("Keenny Hess#12").driver.text == "Silver 2"
        assert rank_info.driver_ranks("Nobody") is None
    assert found == [("Keenny Hess",), ("Austin Martin",), ("Nobody",)]
    # Player ranks changed (list replaced): looked for again
    monkeypatch.setattr(rank_info.ranks, "drivers", [ranks_of("Keenny Hess", ("Gold", 1, 0))])
    assert rank_info.driver_ranks("Keenny Hess#12").driver.text == "Gold 1"
    # Field ranks read (dict replaced, serial incremented)
    monkeypatch.setattr(rank_info.field, "_ranks", {"nobody": ranks_of("Nobody", ("Gold", 3, 0))})
    monkeypatch.setattr(rank_info.field, "serial", rank_info.field.serial + 1)
    assert rank_info.driver_ranks("Nobody").driver.text == "Gold 3"
    assert rank_info.driver_ranks("Austin Martin#9566") is None
    # Dict filled in place (size changed): seen too
    rank_info.field.known["austin martin"] = ranks_of("Austin Martin", ("Silver", 1, 0))
    assert rank_info.driver_ranks("Austin Martin#9566").driver.text == "Silver 1"
    # Serial alone incremented (values set without replacing the list): looked for again
    count = len(found)
    monkeypatch.setattr(rank_info.ranks, "serial", rank_info.ranks.serial + 1)
    rank_info.driver_ranks("Keenny Hess#12")
    assert len(found) == count + 1


def test_driver_ranks_memo_bounded(lookups, monkeypatch):
    rank_info, _found = lookups
    monkeypatch.setattr(rank_info, "MEMO_NAMES", 3)
    for name in ("a", "b", "c", "d"):
        rank_info.driver_ranks(name)
    assert len(rank_info._current_memo().ranks) <= 3
    assert rank_info.driver_ranks("Keenny Hess").driver.text == "Silver 2"


def test_field_level_memo(lookups, monkeypatch):
    rank_info, _found = lookups
    averages: list[tuple] = []
    monkeypatch.setattr(fr, "average_level", counted(averages, fr.average_level))
    names = ["Keenny Hess", "Austin Martin#9566", "Austin Martin", "Nobody"]
    level = rank_info.field_level(names)
    assert level.known == 2 and level.driver == fr.rank_of_level(
        (dr.Rank("Silver", 2, 40).level + dr.Rank("Bronze", 3, 0).level) / 2)
    assert rank_info.field_level(iter(names)) == level and len(averages) == 1  # same drivers: memo (any iterable)
    assert rank_info.field_level(names[:1]).known == 1 and len(averages) == 2  # other drivers
    monkeypatch.setattr(rank_info.field, "_ranks", {})  # field ranks dropped (option off)
    monkeypatch.setattr(rank_info.field, "serial", rank_info.field.serial + 1)
    assert rank_info.field_level(names).known == 1 and len(averages) == 3


def test_field_ranks_replaced_whole_with_serial():
    from tests.test_field_ranks import SESSION, make_field

    field, source, clock = make_field()
    known = field.known
    field.poll(SESSION)
    assert field.known is not known and field.serial == 1 and known == {}  # never changed in place
    known = field.known
    clock[0] += fr.CHECK_SECONDS
    field.poll(SESSION)  # nothing due: same dict
    assert field.known is known and field.serial == 1
    source.server = False  # left the server: dropped
    clock[0] += fr.CHECK_SECONDS
    field.poll(SESSION)
    assert field.known == {} and field.serial == 2 and len(known) == 4


def test_watcher_keeps_equal_drivers_list(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    watcher, clock, _wall, _history = online_watcher(tmp_path, online)
    watcher.check()
    drivers, serial = watcher.drivers, watcher.serial
    assert watcher._by_name[0] is drivers  # index made by check (worker), not by first lookup
    clock[0] = dr.ONLINE_SECONDS
    watcher.check()  # same ranks read again
    assert len(online.fetched) == 2 and watcher.drivers is drivers and watcher.serial == serial


# --- B7: serial on real changes only, history in memory & trimmed
def online_watcher(tmp_path, online, text=None, history_lines=()):
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(text if text is not None else json.dumps({"other": "x"}), encoding="utf-8")
    os.utime(path, (NOON - 3600, NOON - 3600))
    history = tmp_path / dr.HISTORY_FILE
    for entry in history_lines:
        dr.append_history(str(history), entry)
    clock, wall = [0.0], [NOON]
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), STEAM, ("Keenny Hess",)), lambda: str(history),
                             clock=lambda: clock[0], online=online, wall_clock=lambda: wall[0],
                             run_online=lambda work: work())
    return watcher, clock, wall, history


def test_online_read_with_same_ranks_changes_nothing(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    watcher, clock, wall, _history = online_watcher(tmp_path, online)
    watcher.check()
    assert watcher.online and watcher.serial == 1 and watcher.updated == NOON
    clock[0], wall[0] = dr.ONLINE_SECONDS, NOON + 300
    watcher.check()
    assert len(online.fetched) == 2 and watcher.serial == 1  # same ranks: pages not made again
    assert watcher.updated == NOON + 300  # time of read kept
    clock[0], wall[0] = 2 * dr.ONLINE_SECONDS, NOON + 86400  # next day: date shown changes
    watcher.check()
    assert watcher.serial == 2 and watcher.updated == NOON + 86400
    online.ranks = online.ranks._replace(driver=dr.Rank("Gold", 1, 30))
    clock[0], wall[0] = 3 * dr.ONLINE_SECONDS, NOON + 86400 + 300
    watcher.check()
    assert watcher.serial == 3 and watcher.player.driver.progress == 30


def test_history_of_kept_in_memory(tmp_path, monkeypatch):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    old = dr.HistoryEntry(NOON - 7200, dr.Rank("Silver", 3, 80), None, "", STEAM)
    other = dr.HistoryEntry(NOON - 7000, dr.Rank("Bronze", 1, 0), None, "", "76561190000000002")
    watcher, clock, wall, history = online_watcher(tmp_path, online, history_lines=(old, other))
    watcher.check()
    entries = watcher.history_of(STEAM)
    assert isinstance(entries, tuple) and [entry.driver for entry in entries] == [
        dr.Rank("Silver", 3, 80), dr.Rank("Gold", 1, 12)]
    assert len(watcher.history_of("")) == 3  # account unknown: every line, like account_history
    assert list(watcher.history_of("")) == dr.read_history(str(history))
    assert watcher.history_of("76561190000000009") == ()
    monkeypatch.setattr(dr, "read_history", lambda path: pytest.fail("history file read again"))
    online.ranks = online.ranks._replace(driver=dr.Rank("Gold", 1, 40))
    clock[0], wall[0] = dr.ONLINE_SECONDS, NOON + 300
    watcher.check()  # rank changed: line added, memory too
    assert [entry.driver.progress for entry in watcher.history_of(STEAM)] == [80, 12, 40]
    assert entries[-1].driver.progress == 12  # snapshot given before never changed
    assert watcher.last_entry(STEAM).driver.progress == 40
    assert [other.steam_id for other in watcher.others] == ["76561190000000002"]


def test_history_of_without_check_and_path_change(tmp_path):
    first, second = tmp_path / "a.history", tmp_path / "b.history"
    dr.append_history(str(first), dr.HistoryEntry(1, dr.Rank("Silver", 1, 0), None, "", STEAM))
    path = [str(first)]
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()), lambda: path[0])
    assert len(watcher.history_of(STEAM)) == 1  # read once when asked first
    path[0] = str(second)  # config folder changed: read again
    assert watcher.history_of(STEAM) == ()
    assert dr.RankWatcher(lambda: dr.Located("", "", ())).history_of(STEAM) == ()  # no history


def test_trim_history_keeps_last_entry_of_each_account():
    entries = [dr.HistoryEntry(index, dr.Rank("Silver", 1, index), None, "", steam)
               for index, steam in enumerate(["old", "", "a", "a", "b", "a", "a", "a"])]
    kept = dr.trim_history(entries, keep=3)
    assert [entry.time for entry in kept] == [0, 1, 4, 5, 6, 7]  # old, unknown & b kept, newest 3 of a
    assert dr.trim_history(entries, keep=10) == entries


def test_history_file_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "HISTORY_KEEP", 5)
    monkeypatch.setattr(dr, "HISTORY_SLACK", 2)
    history = tmp_path / dr.HISTORY_FILE
    dr.append_history(str(history), dr.HistoryEntry(1, dr.Rank("Gold", 1, 0), None, "", "other"))
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()), lambda: str(history))
    for progress in range(10):
        watcher.record(ranks_of("Keenny Hess", ("Silver", 1, progress)), 100 + progress, STEAM)
        lines = dr.read_history(str(history))
        assert list(watcher.history_of("")) == lines  # memory always same as file
        assert len(lines) <= 5 + 2 + 1
    lines = dr.read_history(str(history))
    assert lines[0].steam_id == "other"  # last line of an account never dropped
    assert lines[-1].driver == dr.Rank("Silver", 1, 9)
    assert not any(name.endswith(".tmp") for name in os.listdir(tmp_path))


def test_history_not_saved_kept_in_memory_for_adopted_account(tmp_path, monkeypatch):
    history = tmp_path / dr.HISTORY_FILE
    dr.append_history(str(history), dr.HistoryEntry(1, dr.Rank("Gold", 1, 0), None))  # line without account
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()), lambda: str(history))
    monkeypatch.setattr(dr, "append_history", lambda path, entry: False)  # read-only folder
    adopted = watcher.adopt_unknown_account(STEAM)
    assert adopted is not None and watcher.last_entry(STEAM) == adopted
    assert watcher.adopt_unknown_account("76561190000000002") is None  # never given to a second account
    watcher.record(ranks_of("x", ("Silver", 1, 0)), 2, STEAM)  # not saved: not in memory either
    assert watcher.last_entry(STEAM) == adopted


def test_history_concurrent_reader_sees_whole_snapshots(tmp_path):
    history = tmp_path / dr.HISTORY_FILE
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()), lambda: str(history))
    stop, bad = threading.Event(), []

    def read():
        while not stop.is_set():
            entries = watcher.history_of(STEAM)
            if [entry.time for entry in entries] != list(range(len(entries))):
                bad.append(entries)
            time.sleep(0)  # writer runs too

    reader = threading.Thread(target=read)
    reader.start()
    try:
        for index in range(60):
            watcher.record(ranks_of("x", ("Silver", 1, index % 100)), index, STEAM)
    finally:
        stop.set()
        reader.join(5)
    assert not bad and len(watcher.history_of(STEAM)) == 60


def test_home_driver_card_history_from_memory(home, monkeypatch):  # noqa: F811
    from neopedal import rank_info

    monkeypatch.setattr(rank_info.ranks, "poll", lambda: None)
    monkeypatch.setattr(rank_info.ranks, "_history", dr._History.of(rank_info.history_path(), [
        dr.HistoryEntry(1, dr.Rank("Silver", 1, 90), None, "", "1"),
        dr.HistoryEntry(2, dr.Rank("Bronze", 1, 0), None, "", "2")]))  # other account: left out
    monkeypatch.setattr(dr, "read_history", lambda path: pytest.fail("history file read by page"))
    monkeypatch.setattr(rank_info.ranks, "player", dr.DriverRanks(
        "Keenny Hess", "1", "", "", dr.Rank("Silver", 2, 40), None, ""))
    monkeypatch.setattr(rank_info.ranks, "serial", rank_info.ranks.serial + 1)
    home.refresh_driver()
    assert "+50%" in home.card_driver.label_value.text()  # 90% S1 -> 40% S2


# --- Architecture 6: storage file not read again while online ranks used
def test_storage_without_ranks_not_read_again_for_online_ranks(tmp_path, monkeypatch):
    reads: list[tuple] = []
    located: list[tuple] = []
    monkeypatch.setattr(dr, "read_raw", counted(reads, dr.read_raw))
    online = FakeOnline(raceos.player_ranks(PLAYER))
    watcher, clock, wall, _history = online_watcher(tmp_path, online)
    locate = watcher._locate
    watcher._locate = counted(located, locate)
    watcher.check()
    assert len(reads) == 1 and watcher.online and len(located) == 1
    clock[0], wall[0] = dr.ONLINE_SECONDS, NOON + 300
    watcher.check()  # online ranks read again, file unchanged: neither read nor game located again
    assert len(online.fetched) == 2 and len(reads) == 1 and len(located) == 1
    path = tmp_path / dr.STORAGE_FILE
    os.utime(path, (NOON + 400, NOON + 400))  # game wrote file (no ranks there): only a sign the game ran
    clock[0] += dr.CHECK_SECONDS
    watcher.check()
    assert len(reads) == 1 and len(located) == 2 and watcher.online  # account looked for again, file not read
    online.on = False  # online ranks dropped: file read again
    clock[0] += dr.CHECK_SECONDS
    watcher.check()
    assert len(reads) == 2 and not watcher.online


def test_storage_with_ranks_read_when_written(tmp_path, monkeypatch):
    reads: list[tuple] = []
    monkeypatch.setattr(dr, "read_raw", counted(reads, dr.read_raw))
    online = FakeOnline(raceos.player_ranks(PLAYER))
    watcher, clock, _wall, _history = online_watcher(tmp_path, online, storage_text())
    watcher.check()
    assert len(reads) == 1 and watcher.online
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    os.utime(path, (NOON + 400, NOON + 400))  # newer than online read: file ranks shown
    clock[0] += dr.CHECK_SECONDS
    watcher.check()
    assert len(reads) == 2 and not watcher.online and watcher.player.driver == dr.Rank("Silver", 2, 40)


# --- B11: RaceControl sign in single flight
class BlockingTicket:
    """Game ticket that waits until released while blocking is set"""

    def __init__(self):
        self.blocking = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.blocking:
            self.entered.set()
            assert self.release.wait(5)
        return "ticket"


def make_client():
    http = FakeHttp()
    ticket = BlockingTicket()
    clock = [2_000_000_000.0]
    client = raceos.RaceOSClient(ticket, http=http, clock=lambda: clock[0], wall_clock=lambda: 1_792_000_000.0)
    return client, http, ticket, clock


class WatchedEvent(threading.Event):
    """Event telling when a caller waits on it"""

    def __init__(self):
        super().__init__()
        self.waiting = threading.Event()

    def wait(self, timeout=None):
        self.waiting.set()
        return super().wait(timeout)


def watch_flight(client):
    """Sign in running: its event replaced by one telling when another caller waits for it"""
    event = client._flight.done = WatchedEvent()
    return event.waiting


def run_thread(work, results, name):
    thread = threading.Thread(target=lambda: results.__setitem__(name, work()), daemon=True)
    thread.start()
    return thread


def test_sign_in_single_flight():
    client, http, ticket, _clock = make_client()
    ticket.blocking = True
    http.answers["POST"].append((200, AUTH))
    results: dict = {}
    first = run_thread(lambda: client.sign_in(STEAM), results, "first")
    assert ticket.entered.wait(5)
    waiting = watch_flight(client)
    second = run_thread(lambda: client.sign_in(STEAM), results, "second")
    assert waiting.wait(5) and http.calls == []  # waits for the sign in running
    ticket.release.set()
    first.join(5)
    second.join(5)
    assert results["first"] is results["second"] is client._signed and results["first"].token == "token-1"
    assert ticket.calls == 1 and len(http.calls) == 1  # one ticket, one request
    assert client._flight is None


def test_forget_never_waits_for_sign_in_and_drops_it():
    client, http, ticket, _clock = make_client()
    ticket.blocking = True
    http.answers["POST"].extend([(200, AUTH), (200, AUTH)])
    results: dict = {}
    first = run_thread(lambda: client.sign_in(STEAM), results, "first")
    assert ticket.entered.wait(5)
    forgot = run_thread(client.forget, results, "forget")
    forgot.join(1)
    assert not forgot.is_alive()  # lock never held during requests
    token = run_thread(lambda: client.token(STEAM), results, "token")  # new sign in, not the dropped one
    ticket.release.set()
    first.join(5)
    token.join(5)
    assert results["first"] is None  # option turned off meanwhile: answer dropped
    assert results["token"] == "token-1" and client._signed is not None and len(http.calls) == 2


def test_account_switch_during_sign_in_drops_its_answer():
    client, http, ticket, _clock = make_client()
    ticket.blocking = True
    http.answers["POST"].extend([(404, None), (200, AUTH)])
    results: dict = {}
    first = run_thread(lambda: client.sign_in(STEAM), results, "first")
    assert ticket.entered.wait(5)
    ticket.blocking = False
    other = client.sign_in("76561190000000002")  # own sign in, never waits for the other account one
    assert other is None and client.no_account  # 404 of this account
    ticket.release.set()
    first.join(5)
    assert results["first"] is None and client._signed is None and client.no_account  # its answer dropped


def test_failed_sign_in_counted_once_for_waiting_callers():
    client, http, ticket, clock = make_client()
    ticket.blocking = True
    http.answers["POST"].append((500, None))
    results: dict = {}
    first = run_thread(lambda: client.fetch(STEAM), results, "first")
    assert ticket.entered.wait(5)
    waiting = watch_flight(client)
    second = run_thread(lambda: client.fetch(STEAM), results, "second")
    assert waiting.wait(5)
    ticket.release.set()
    first.join(5)
    second.join(5)
    assert results == {"first": None, "second": None} and len(http.calls) == 1
    assert client._retry_wait == 2 * raceos.RETRY_SECONDS  # doubled once
    assert client._retry_time == clock[0] + raceos.RETRY_SECONDS


def test_token_of_last_sign_in_while_another_runs():
    client, http, ticket, _clock = make_client()
    http.answers["POST"].extend([(200, AUTH), (200, {**AUTH, "accessToken": "token-2"})])
    assert client.fetch(STEAM) is not None
    ticket.blocking = True
    results: dict = {}
    reader = run_thread(lambda: client.fetch(STEAM), results, "fetch")
    assert ticket.entered.wait(5)
    assert client.token(STEAM) == "token-1"  # valid token given at once
    ticket.release.set()
    reader.join(5)
    assert client.token(STEAM) == "token-2"
