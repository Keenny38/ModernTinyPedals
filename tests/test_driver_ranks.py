"""Driver Rank & Safety Rank read from the game menu storage file (coherent_local_storage.json)"""

import json

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


def storage_text():
    """Same layout as game file: stored items are JSON text inside a JSON object"""
    return json.dumps({"profile": json.dumps({"user": PROFILE}), "events": json.dumps(TEAM), "other": "x"})


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
