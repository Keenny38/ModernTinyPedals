"""Driver Rank & Safety Rank read online from RaceControl (raceos.gg), the way the game menu does"""

import json
import os

from neopedal.process import driver_ranks as dr
from neopedal.process import raceos

STEAM = "76561190000000001"
PLAYER = {
    "id": "45062fe7", "name": "Keenny Hess", "username": "keenny",
    "driverRank": {"elo": 1420, "rank": "Gold", "tier": 1, "progress": 12},
    "safetyRank": {"rating": 0, "rank": "Platinum", "tier": 2, "progress": 80},
    "platforms": [{"platform": "steam", "id": STEAM}],
    "profile": {"nationality": "FR", "badges": ["s397"]},
}
AUTH = {"accessToken": "token-1", "expiresAt": "2026-10-17T14:33:29Z", "player": PLAYER, "banned": False}


class FakeHttp:
    """RaceControl answers: queued (status, json data) per method"""

    def __init__(self):
        self.calls = []
        self.answers = {"POST": [], "GET": []}

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append((method, url, json.loads(body) if body else None, headers))
        queue = self.answers[method]
        status, data = queue.pop(0) if queue else (0, None)
        return status, json.dumps(data).encode() if data is not None else b""


def make_client(ticket="ticket-1", now=None):
    http = FakeHttp()
    clock = now or [2_000_000_000.0]
    tickets = []

    def get_ticket():
        tickets.append(1)
        return ticket

    client = raceos.RaceOSClient(get_ticket, http=http, clock=lambda: clock[0], user_agent="NeoPedal/test")
    return client, http, clock, tickets


def test_player_ranks_parse():
    ranks = raceos.player_ranks(PLAYER)
    assert ranks == dr.DriverRanks("Keenny Hess", STEAM, "45062fe7", "FR", dr.Rank("Gold", 1, 12),
                                   dr.Rank("Platinum", 2, 80), "")
    assert raceos.player_ranks({"name": "x"}) is None
    assert raceos.player_ranks(None) is None
    numeric = raceos.player_ranks({**PLAYER, "platforms": [{"platform": "steam", "id": 76561190000000001}]})
    assert numeric.steam_id == STEAM


def test_game_ticket():
    assert raceos.game_ticket(lambda route: (200, b'{"authSessionTicket": "abc"}')) == "abc"
    assert raceos.game_ticket(lambda route: (0, b"")) == ""
    assert raceos.game_ticket(lambda route: (200, b"null")) == ""
    routes = []
    raceos.game_ticket(lambda route: routes.append(route) or (0, b""))
    assert routes == [raceos.TICKET_ROUTE]


def test_signed_in_for_each_read():
    """Ranks of sign in answer are current (player route gives an old copy): new ticket & sign in each read"""
    client, http, _clock, tickets = make_client()
    http.answers["POST"].append((200, AUTH))
    ranks = client.fetch(STEAM)
    assert ranks.driver == dr.Rank("Gold", 1, 12) and len(tickets) == 1
    method, url, body, headers = http.calls[0]
    assert (method, url) == ("POST", raceos.AUTH_URL)
    assert body == {"token": "ticket-1", "game": "lmu", "platform": "steam"}
    assert "Game-Authorization" not in headers and headers["User-Agent"] == "NeoPedal/test"
    http.answers["POST"].append((200, {**AUTH, "player": {**PLAYER, "driverRank": {"rank": "Gold", "tier": 1,
                                                                                   "progress": 30.9}}}))
    assert client.fetch(STEAM).driver.progress == 30 and len(tickets) == 2
    assert [call[0] for call in http.calls] == ["POST", "POST"]


def test_offline_waits_like_failed_sign_in():
    client, http, _clock, tickets = make_client()
    assert client.fetch(STEAM) is None  # no answer (offline): waits like a failed sign in
    assert len(tickets) == 1 and len(http.calls) == 1


def test_game_not_running_no_request():
    client, http, _clock, tickets = make_client(ticket="")
    assert client.fetch(STEAM) is None and http.calls == []
    assert client.fetch(STEAM) is None and len(tickets) == 2  # asked again next time (no wait)


def test_failed_sign_in_waits_longer_each_time():
    client, http, clock, tickets = make_client()
    http.answers["POST"].append((500, None))
    assert client.fetch(STEAM) is None and len(http.calls) == 1
    clock[0] += raceos.RETRY_SECONDS - 1
    assert client.fetch(STEAM) is None and len(http.calls) == 1 and len(tickets) == 1  # waiting: no ticket asked
    clock[0] += 1
    http.answers["POST"].append((200, {"no": "token"}))
    assert client.fetch(STEAM) is None and len(http.calls) == 2
    clock[0] += raceos.RETRY_SECONDS
    assert client.fetch(STEAM) is None and len(http.calls) == 2  # wait doubled
    clock[0] += raceos.RETRY_SECONDS
    http.answers["POST"].append((200, AUTH))
    assert client.fetch(STEAM) is not None


def test_no_account():
    client, http, clock, _tickets = make_client()
    http.answers["POST"].append((404, None))
    assert client.fetch(STEAM) is None and client.no_account
    clock[0] += raceos.NO_ACCOUNT_SECONDS - 1
    assert client.fetch(STEAM) is None and len(http.calls) == 1


def test_account_switch_and_forget_clear_failures():
    client, http, _clock, _tickets = make_client()
    http.answers["POST"].extend([(500, None), (200, AUTH), (500, None), (200, AUTH)])
    assert client.fetch(STEAM) is None
    assert client.fetch(STEAM) is None and len(http.calls) == 1  # waiting after failure
    assert client.fetch("76561190000000002") is not None  # other Steam account: read at once
    assert client.fetch("76561190000000002") is None  # failed
    client.forget()  # option turned off & on: read at once
    assert client.fetch("76561190000000002") is not None and len(http.calls) == 4


def test_http_request_without_network(monkeypatch):
    import urllib.request

    def refused(*args, **kwargs):
        raise OSError("refused")

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    assert raceos.http_request("POST", raceos.AUTH_URL, b"{}", {}, 1) == (0, b"")


class FakeOnline:
    def __init__(self, ranks=None):
        self.on = True
        self.running = True
        self.ranks = ranks
        self.fetched = []
        self.forgotten = 0

    def enabled(self):
        return self.on

    def game_running(self):
        return self.running

    def fetch(self, account):
        self.fetched.append(account)
        return self.ranks

    def forget(self):
        self.forgotten += 1


def storage_text(progress=40):
    profile = {"steamId": STEAM, "name": "Keenny Hess", "badge": "sr-clean",
               "driverRank": {"rank": "Silver", "tier": 2, "progress": progress},
               "safetyRank": {"rank": "Platinum", "tier": 3, "progress": 50}}
    return json.dumps({"profile": json.dumps({"user": profile})})


def make_watcher(tmp_path, online, clock, text=None):
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(text if text is not None else json.dumps({"other": "x"}), encoding="utf-8")
    os.utime(path, (1_900_000_000, 1_900_000_000))
    results = tmp_path / "Results"
    results.mkdir()
    os.utime(results, (1_900_000_000, 1_900_000_000))
    history = tmp_path / dr.HISTORY_FILE
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), STEAM, ("Keenny Hess",), (), str(results)),
                             lambda: str(history), clock=lambda: clock[0], online=online,
                             wall_clock=lambda: 2_000_000_000.0, run_online=lambda work: work())
    return watcher, path, results, history


def test_watcher_prefers_online_ranks(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    clock = [0.0]
    watcher, _path, _results, history = make_watcher(tmp_path, online, clock, storage_text())
    watcher.check()
    assert online.fetched == [STEAM] and watcher.online and not watcher.remembered
    assert watcher.player.driver == dr.Rank("Gold", 1, 12) and watcher.updated == 2_000_000_000
    assert watcher.player.badge == "sr-clean"  # service gives none: badge of game file kept
    assert watcher.team_ranks("Keenny Hess").driver == dr.Rank("Gold", 1, 12)  # Broadcast Director cards
    assert len([d for d in watcher.drivers if d.name == "Keenny Hess"]) == 1
    last = dr.read_history(str(history))[-1]
    assert last.driver == dr.Rank("Gold", 1, 12) and last.steam_id == STEAM and last.time == 2_000_000_000
    # Not due again before ONLINE_SECONDS
    clock[0] = dr.ONLINE_SECONDS - 1
    watcher.check()
    assert len(online.fetched) == 1
    clock[0] = dr.ONLINE_SECONDS
    watcher.check()
    assert len(online.fetched) == 2 and watcher.serial == 1  # same ranks: values unchanged


def test_watcher_online_without_ranks_in_game_file(tmp_path):
    """Game file without ranks (current game): online ranks shown, not the remembered ones"""
    online = FakeOnline(raceos.player_ranks(PLAYER))
    watcher, _path, _results, history = make_watcher(tmp_path, online, [0.0])
    dr.append_history(str(history), dr.HistoryEntry(1_800_000_000, dr.Rank("Silver", 2, 40), None, "", STEAM))
    watcher.check()
    assert watcher.online and not watcher.remembered and watcher.player.driver.text == "Gold 1"


def test_watcher_reads_after_session_end(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    clock = [0.0]
    watcher, _path, results, _history = make_watcher(tmp_path, online, clock)
    watcher.check()
    assert len(online.fetched) == 1
    # Session ended: results file added (folder modified), read 30 s & 3 min later
    clock[0] = 100.0
    os.utime(results, (1_950_000_000, 1_950_000_000))
    watcher.check()
    assert len(online.fetched) == 1
    online.ranks = online.ranks._replace(driver=dr.Rank("Gold", 1, 20))
    online.running = False  # read after a session even if game closed meanwhile
    clock[0] = 100.0 + dr.ONLINE_RESULTS_DELAYS[0]
    watcher.check()
    assert len(online.fetched) == 2 and watcher.player.driver.progress == 20 and watcher.serial == 2
    clock[0] = 100.0 + dr.ONLINE_RESULTS_DELAYS[1]
    watcher.check()
    assert len(online.fetched) == 3


def test_watcher_tells_session_end(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    ended = []
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    results = tmp_path / "Results"
    results.mkdir()
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), STEAM, (), (), str(results)), clock=lambda: 0.0,
                             online=online, run_online=lambda work: work(), session_ended=lambda: ended.append(1))
    watcher.check()
    assert ended == []  # results folder first seen: no session end
    os.utime(results, (1_950_000_000, 1_950_000_000))
    watcher.check()
    assert ended == [1]
    online.on = False
    os.utime(results, (1_960_000_000, 1_960_000_000))
    watcher.check()
    assert ended == [1]  # online ranks off: not told


def test_watcher_periodic_read_only_while_game_runs(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    online.running = False
    clock = [0.0]
    watcher, _path, _results, _history = make_watcher(tmp_path, online, clock)
    watcher.check()
    assert online.fetched == [] and not watcher.online
    clock[0] = dr.ONLINE_GAME_SECONDS - 1
    online.running = True
    watcher.check()
    assert online.fetched == []
    clock[0] = dr.ONLINE_GAME_SECONDS  # game looked for again: started, ranks read
    watcher.check()
    assert online.fetched == [STEAM] and watcher.online


def test_watcher_failed_read_retried_later(tmp_path):
    online = FakeOnline(None)
    clock = [0.0]
    watcher, _path, _results, _history = make_watcher(tmp_path, online, clock)
    watcher.check()
    assert len(online.fetched) == 1 and not watcher.online
    clock[0] = dr.ONLINE_RETRY_SECONDS - 1
    watcher.check()
    assert len(online.fetched) == 1
    clock[0] = dr.ONLINE_RETRY_SECONDS
    online.ranks = raceos.player_ranks(PLAYER)
    watcher.check()
    assert len(online.fetched) == 2 and watcher.online


def test_watcher_option_turned_off(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    clock = [0.0]
    watcher, _path, _results, _history = make_watcher(tmp_path, online, clock, storage_text())
    watcher.check()
    assert watcher.online
    online.on = False
    watcher.check()
    assert not watcher.online and watcher.player.driver == dr.Rank("Silver", 2, 40) and online.forgotten == 1
    watcher.check()
    assert online.forgotten == 1
    online.on = True  # turned on again: read at once
    watcher.check()
    assert watcher.online and len(online.fetched) == 2


def test_watcher_never_reads_online_when_off(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    online.on = False
    watcher, _path, _results, _history = make_watcher(tmp_path, online, [0.0], storage_text())
    watcher.check()
    assert online.fetched == [] and online.forgotten == 0 and not watcher.online


def test_watcher_ignores_read_ended_after_turned_off(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    pending = []
    clock = [0.0]
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), STEAM, ()), clock=lambda: clock[0], online=online,
                             run_online=pending.append)
    watcher.check()
    assert len(pending) == 1 and not watcher.online
    watcher.check()  # read still running: not started twice
    assert len(pending) == 1
    online.on = False
    watcher.check()
    pending.pop()()  # read ends after option turned off: ignored
    online.on = True
    clock[0] = 1.0
    watcher.check()
    assert len(pending) == 1  # new read started (turned on again), old result never applied
    assert not watcher.online


def test_watcher_drops_online_ranks_of_other_account(tmp_path):
    online = FakeOnline(raceos.player_ranks(PLAYER))
    account = {"id": STEAM}
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), account["id"], ()), clock=lambda: 0.0, online=online,
                             active_account=lambda: account["id"], run_online=lambda work: work())
    watcher.check()
    assert watcher.online
    account["id"] = "76561190000000002"
    online.ranks = None  # other account not signed in
    watcher.check()
    assert not watcher.online and watcher.player is None and online.fetched[-1] == "76561190000000002"
