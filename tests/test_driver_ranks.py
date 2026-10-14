"""Driver Rank & Safety Rank read from the game menu storage file (coherent_local_storage.json)"""

import json
import os

from neopedal.process import driver_ranks as dr

PROFILE = {
    "id": "45062fe7", "steamId": "76561190000000001", "name": "Keenny Hess", "username": "Keenny Hess",
    "driverRank": {"elo": 0, "rank": "Silver", "tier": 2, "progress": 40},
    "safetyRank": {"rank": "Platinum", "tier": 3, "rating": 0, "progress": 50, "contactImpactsPerLapRatio": 0},
}
TEAM = {"teams": [{"name": "Team", "drivers": [
    {"state": "accepted", "driverId": "cba24a06", "name": "Flo Veninski", "nationality": "FR",
     "driverRank": {"elo": 0, "rank": "Silver", "tier": 2, "progress": 30},
     "safetyRank": {"rank": "Gold", "tier": 3, "rating": 0, "progress": 10}},
]}], "driverRank": None, "split": None}


def storage_text(profile=None):
    """Same layout as game file: stored items are JSON text inside a JSON object"""
    return json.dumps({"profile": json.dumps({"user": profile or PROFILE}), "events": json.dumps(TEAM), "other": "x"})


def test_parse_storage():
    drivers = dr.parse_storage(storage_text())
    player = dr.find_driver(drivers, steam_id="76561190000000001")
    assert player is not None and player.name == "Keenny Hess"
    assert player.driver == dr.Rank("Silver", 2, 40) and player.safety == dr.Rank("Platinum", 3, 50)
    assert player.driver.text == "Silver 2" and player.driver.short == "S2"
    mate = dr.find_driver(drivers, name="flo veninski")
    assert mate is not None and mate.nationality == "FR" and mate.safety.text == "Gold 3"
    assert dr.find_driver(drivers, name="Nobody") is None
    assert len(drivers) == 2  # node with "driverRank": null skipped


def test_rank_level_order():
    assert dr.Rank("Silver", 2, 40).level < dr.Rank("Silver", 2, 41).level < dr.Rank("Silver", 3, 0).level
    assert dr.Rank("Silver", 3, 100).level <= dr.Rank("Gold", 1, 0).level
    assert dr.Rank("Unknown", 1, 0).level == -1


def test_invalid_or_missing_file(tmp_path):
    assert dr.parse_storage("{broken") == []
    assert dr.parse_storage(json.dumps({"a": "{not json Rank"})) == []
    assert dr.read_storage(str(tmp_path / "missing.json")) == []
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    assert len(dr.read_storage(str(path))) == 2


def test_watcher_reads_when_changed_and_keeps_history(tmp_path):
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    history = tmp_path / dr.HISTORY_FILE
    located = []
    watcher = dr.RankWatcher(lambda: located.append(1) or dr.Located(str(path), "76561190000000001", ()),
                             lambda: str(history))
    watcher.check()
    assert watcher.player is not None and watcher.player.driver.text == "Silver 2" and watcher.serial == 1
    assert len(watcher.drivers) == 2 and watcher.team_ranks("Flo Veninski") is not None
    watcher.check()  # file unchanged: not read again, located once (cached)
    assert watcher.serial == 1 and len(located) == 1
    assert [entry.driver for entry in dr.read_history(str(history))] == [dr.Rank("Silver", 2, 40)]
    # Rank changed in game menu: read again, history gets a line
    profile = {**PROFILE, "driverRank": {**PROFILE["driverRank"], "progress": 55}}
    path.write_text(storage_text(profile), encoding="utf-8")
    os.utime(path, (2_000_000_000, 2_000_000_000))
    watcher.check()
    assert watcher.player.driver.progress == 55 and watcher.serial == 2
    assert [entry.driver.progress for entry in dr.read_history(str(history))] == [40, 55]
    assert dr.rank_change(dr.Rank("Silver", 2, 40), dr.Rank("Silver", 2, 55)) == 15


def test_watcher_without_game(tmp_path):
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()))
    watcher.check()
    assert watcher.player is None and watcher.drivers == [] and watcher.serial == 0


def test_player_badge_found_in_event_registration(tmp_path, monkeypatch):
    """Profile entry has no badge: badge of same driver elsewhere in file (registration profile, team list)"""
    from neopedal.setting import cfg
    from neopedal.ui.quick.stats_backend import badge_card
    from neopedal.userfile import badge_icons

    driver = {"steamId": "76561190000000001", "name": "Keenny Hess", "profile": {"nationality": "FR", "badge": "sr-saint"},
              "driverRank": {"rank": "Silver", "tier": 2, "progress": 40}}
    events = {"state": {"registeredOnlineEvents": [{"event": {"registrations": [{"driver": driver}]}}]}}
    text = json.dumps({"profile": json.dumps({"user": PROFILE}), "events": json.dumps(events)})
    drivers = dr.parse_storage(text)
    player = dr.player_entry(drivers, dr.Located("", "76561190000000001", ()))
    assert player is not None and player.badge == "sr-saint"
    assert dr.player_entry(dr.parse_storage(storage_text()), dr.Located("", "76561190000000001", ())).badge == ""
    monkeypatch.setattr(cfg.path, "game_image", str(tmp_path))
    requested = []
    monkeypatch.setattr(badge_icons.icons, "request", requested.append)
    card = badge_card(player)
    assert card["name"] == "Trusted Racer" and card["icon"] == "" and requested == ["sr-saint"]
    icon = tmp_path / badge_icons.ICON_FOLDER / "sr-saint.svg"
    icon.parent.mkdir()
    icon.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    assert badge_card(player)["icon"].endswith("sr-saint.svg")
    assert badge_card(player._replace(badge="sr-future"))["name"] == "sr-future"  # unknown badge: as given
    assert badge_card(player._replace(badge="")) == {} and badge_card(None) == {}


def test_badge_icons_download(monkeypatch, tmp_path):
    from neopedal.setting import cfg
    from neopedal.userfile import badge_icons

    monkeypatch.setattr(cfg.path, "game_image", str(tmp_path))
    urls = []
    answers = {"sr-clean": b"<svg xmlns='http://www.w3.org/2000/svg'/>", "sr-saint": b""}
    monkeypatch.setattr(badge_icons, "download", lambda url: urls.append(url) or answers[url.split("/")[-1][:-4]])
    icons = badge_icons.BadgeIcons()
    assert icons.icon_file("../evil") == "" and icons.file("not-a-badge") == ""
    assert icons.fetch("sr-clean") and icons.version == 1
    assert urls == ["https://rf2-ui-images-prod.s3.eu-west-1.amazonaws.com/badges/sr-clean.svg"]
    assert icons.file("SR-CLEAN") == str(tmp_path / "badge" / "sr-clean.svg")
    assert not icons.fetch("sr-saint")  # empty answer: not saved
    icons.request("sr-saint")
    assert "sr-saint" not in icons._queued  # failed lately: not asked again yet


def test_watcher_keeps_last_ranks_when_game_cache_emptied(tmp_path):
    """Game rewrote its menu cache without ranks: last ranks of history shown (with their date), badge too"""
    path = tmp_path / dr.STORAGE_FILE
    profile = {**PROFILE, "badge": "sr-clean"}
    path.write_text(storage_text(profile), encoding="utf-8")
    os.utime(path, (1_900_000_000, 1_900_000_000))
    history = tmp_path / dr.HISTORY_FILE
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), "76561190000000001", ("Keenny Hess",)), lambda: str(history))
    watcher.check()
    assert not watcher.remembered and watcher.player.badge == "sr-clean"
    assert dr.read_history(str(history))[-1].badge == "sr-clean"
    # Cache emptied by game: no driver in file any more
    path.write_text(json.dumps({"other": json.dumps({"seen": True})}), encoding="utf-8")
    os.utime(path, (1_950_000_000, 1_950_000_000))
    watcher.check()
    assert watcher.remembered and watcher.serial == 2
    assert watcher.player == dr.DriverRanks("Keenny Hess", "76561190000000001", "", "", dr.Rank("Silver", 2, 40),
                                            dr.Rank("Platinum", 3, 50), "sr-clean")
    assert watcher.updated == 1_900_000_000  # time ranks were seen, not file time
    assert len(dr.read_history(str(history))) == 1  # remembered ranks never added again
    # Ranks back in game file
    path.write_text(storage_text(profile), encoding="utf-8")
    os.utime(path, (2_000_000_000, 2_000_000_000))
    watcher.check()
    assert not watcher.remembered and watcher.updated == 2_000_000_000 and watcher.serial == 3


def test_watcher_no_history_no_remembered_ranks(tmp_path):
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), "", ()), lambda: str(tmp_path / dr.HISTORY_FILE))
    watcher.check()
    assert watcher.player is None and not watcher.remembered


def test_history_badge_line_read_by_older_format(tmp_path):
    path = tmp_path / dr.HISTORY_FILE
    path.write_text('{"time": 1, "driver": ["Silver", 2, 40], "safety": null}\n', encoding="utf-8")
    assert dr.read_history(str(path))[0].badge == ""
    assert dr.append_history(str(path), dr.HistoryEntry(2.0, None, None, "sr-saint"))
    assert [entry.badge for entry in dr.read_history(str(path))] == ["", "sr-saint"]


def test_history_kept_per_steam_account(tmp_path):
    """Two game accounts on one computer: ranks of one never shown, nor compared, as ranks of the other"""
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    os.utime(path, (1_900_000_000, 1_900_000_000))
    history = tmp_path / dr.HISTORY_FILE
    history.write_text('{"time": 1, "driver": ["Gold", 1, 0], "safety": null}\n', encoding="utf-8")  # older line
    located = {"steam": "76561190000000001"}
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), located["steam"], ("Keenny Hess",)), lambda: str(history))
    watcher.check()
    entries = dr.read_history(str(history))
    assert entries[-1].steam_id == "76561190000000001" and entries[-1].driver == dr.Rank("Silver", 2, 40)
    # Other account signed in, game cache emptied: no ranks (not those of the first account, nor the older line)
    located["steam"] = "76561190000000002"
    path.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    os.utime(path, (1_950_000_000, 1_950_000_000))
    watcher.check()
    assert watcher.player is None and not watcher.remembered
    # First account again: its last ranks remembered
    located["steam"] = "76561190000000001"
    os.utime(path, (1_960_000_000, 1_960_000_000))
    watcher.check()
    assert watcher.remembered and watcher.player.driver == dr.Rank("Silver", 2, 40)
    assert [entry.driver for entry in dr.account_history(dr.read_history(str(history)), "76561190000000001")] == [
        dr.Rank("Silver", 2, 40)]
    assert len(dr.account_history(dr.read_history(str(history)), "")) == 2  # account unknown: every line


def test_recent_steam_users_order(tmp_path):
    from neopedal.process import player_profile as pp

    config = tmp_path / "config"
    config.mkdir()
    (config / "loginusers.vdf").write_text('''"users"
{
    "76561190000000001" { "AccountName" "a" "Timestamp" "100" }
    "76561190000000002" { "AccountName" "b" "Timestamp" "200" }
    "76561190000000003" { "AccountName" "c" "Timestamp" "50" }
}''', encoding="utf-8")
    assert pp.recent_steam_users(str(tmp_path), active="") == [
        "76561190000000002", "76561190000000001", "76561190000000003"]  # last signed in first
    assert pp.recent_steam_users(str(tmp_path), active="76561190000000003")[0] == "76561190000000003"  # running Steam
    assert pp.recent_steam_users(str(tmp_path), active="76561199999999999")[0] == "76561190000000002"  # not listed
    assert pp.recent_steam_users("") == []


def test_other_accounts_and_live_account_switch(tmp_path):
    """Other game accounts of this computer: their last ranks (Steam order, names & pictures); Steam account
    switched: ranks of the account now in use read at once"""
    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    history = tmp_path / dr.HISTORY_FILE
    dr.append_history(str(history), dr.HistoryEntry(5.0, dr.Rank("Gold", 1, 65), dr.Rank("Silver", 3, 20),
                                                    "sr-saint", "76561190000000002"))
    dr.append_history(str(history), dr.HistoryEntry(6.0, dr.Rank("Bronze", 2, 10), None, "", "76561190000000009"))
    accounts = (("76561190000000001", "Main", "main.png"), ("76561190000000002", "Second", ""))
    active = {"id": "76561190000000001"}
    located = []

    def locate():
        located.append(1)
        first = next(account for account in accounts if account[0] == active["id"])
        return dr.Located(str(path), active["id"], ("Keenny Hess",), (first, *(a for a in accounts if a != first)))

    watcher = dr.RankWatcher(locate, lambda: str(history), active_account=lambda: active["id"])
    watcher.check()
    assert watcher.player.driver == dr.Rank("Silver", 2, 40)
    assert [(other.steam_id, other.name) for other in watcher.others] == [
        ("76561190000000002", "Second"), ("76561190000000009", "")]  # Steam accounts first, then history only
    assert watcher.others[0].ranks.badge == "sr-saint" and watcher.others[0].time == 5.0
    # Second account signed in to Steam, game file unchanged (its ranks not written yet): last ranks of second
    active["id"] = "76561190000000002"
    serial = watcher.serial
    watcher.check()
    assert len(located) == 2 and watcher.serial > serial
    assert watcher.player is not None and watcher.remembered and watcher.player.driver == dr.Rank("Gold", 1, 65)
    assert [other.steam_id for other in watcher.others] == ["76561190000000001", "76561190000000009"]
    assert watcher.others[0].ranks.driver == dr.Rank("Silver", 2, 40)  # first account recorded when read
    watcher.check()  # same account: nothing located again
    assert len(located) == 2


def test_steam_accounts_names_and_pictures(tmp_path):
    from neopedal.process import player_profile as pp

    (tmp_path / "config" / "avatarcache").mkdir(parents=True)
    (tmp_path / "config" / "avatarcache" / "76561190000000002.png").write_bytes(b"png")
    (tmp_path / "config" / "loginusers.vdf").write_text('''"users"
{
    "76561190000000001" { "AccountName" "a" "PersonaName" "Main" "Timestamp" "100" }
    "76561190000000002" { "AccountName" "b" "PersonaName" "Second" "Timestamp" "50" }
}''', encoding="utf-8")
    accounts = pp.steam_accounts(str(tmp_path), active="76561190000000002")
    assert [(account.steam_id, account.name) for account in accounts] == [
        ("76561190000000002", "Second"), ("76561190000000001", "Main")]
    assert accounts[0].avatar.endswith("76561190000000002.png") and accounts[1].avatar == ""
