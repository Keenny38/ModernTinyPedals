"""Driver card of Home page: ranks (change, badge, remembered date), profile, race record of results files"""

from neopedal.process import driver_ranks as dr
from neopedal.process import results_index as ri
from neopedal.process.player_profile import PlayerProfile
from neopedal.ui.home_driver import DriverData, driver_card

PLAYER = dr.DriverRanks("Keenny Hess", "76561190000000001", "", "FR", dr.Rank("Silver", 2, 55),
                        dr.Rank("Platinum", 3, 50), "sr-clean")
PROFILE = PlayerProfile("Keenny Hess", "", "FR", "Team NP", "38", "")
RECORD = ri.RaceRecord(races=4, wins=1, podiums=2, average_finish=3.5, clean=3, contacts=2)


def test_nothing_known_hides_card():
    assert driver_card(None, False, 0.0, [], None) is None
    assert driver_card(None, False, 0.0, [], DriverData(None, ri.RaceRecord(0, 0, 0, 0.0, 0, 0), "")) is None


def test_full_card():
    history = [dr.HistoryEntry(1.0, dr.Rank("Silver", 2, 40), dr.Rank("Platinum", 3, 50)),
               dr.HistoryEntry(2.0, dr.Rank("Silver", 2, 55), dr.Rank("Platinum", 3, 50))]
    card = driver_card(PLAYER, False, 2.0, history[:1], DriverData(PROFILE, RECORD, "Keenny Hess"))
    assert card["name"] == "Keenny Hess" and card["identity"] == "France · Team NP · #38"
    driver, safety = card["ranks"]
    assert (driver["label"], driver["value"], driver["progressText"]) == ("Driver Rank", "Silver 2", "55%")
    assert driver["change"] == "+15%" and driver["changeTone"] == 1  # change since previous rank
    assert driver["color"] == dr.RANK_COLORS["silver"] and driver["lightColor"] == dr.RANK_COLORS_LIGHT["silver"]
    assert safety["value"] == "Platinum 3" and safety["change"] == ""  # unchanged: no change shown
    assert card["badge"]["name"] == "Good Driver"
    assert card["figures"] == [{"label": "Races", "value": "4"}, {"label": "Wins", "value": "1"},
                               {"label": "Podiums", "value": "2"}, {"label": "Avg. Finish", "value": "P3.5"},
                               {"label": "Clean Races", "value": "3/4"}]
    assert card["note"] == "" and card["others"] == []
    assert len(driver_card(PLAYER, False, 2.0, history, None)["ranks"][0]["chart"]) == 2  # rank over time


def test_remembered_ranks_dated():
    assert "Last ranks seen in game menu" in driver_card(PLAYER, True, 1_900_000_000, [], None)["note"]


def test_races_only_uses_results_name():
    card = driver_card(None, False, 0.0, [], DriverData(None, RECORD, "Flo"))
    assert card["name"] == "Flo" and card["ranks"] == [] and card["badge"] == {}


def test_race_record():
    def summary(kind, status, position, contacts=0, penalties=0):
        return ri.ResultSummary._make([None] * len(ri.ResultSummary._fields))._replace(
            kind=kind, status=status, class_position=position, contacts=contacts, penalties=penalties)

    from neopedal.process import results_file as rf
    record = ri.race_record([
        summary("Race", rf.FINISHED, 1), summary("Race", rf.FINISHED, 4, contacts=2),
        summary("Race", "DNF", 0, penalties=1), summary("Qualifying", rf.FINISHED, 1),
    ])
    assert record == ri.RaceRecord(races=3, wins=1, podiums=1, average_finish=2.5, clean=1, contacts=2)


def test_other_accounts_rows():
    other = dr.OtherAccount("2", "Second", "", dr.DriverRanks("Second", "2", "", "", dr.Rank("Gold", 1, 65), None,
                                                               "sr-saint"), 1_900_000_000)
    card = driver_card(None, False, 0.0, [], None, [other])  # active account unknown yet
    assert card["name"] == "Driver" and card["others"][0]["name"] == "Second"
    assert card["others"][0]["ranks"][0]["value"] == "Gold 1" and card["others"][0]["badge"]["name"] == "Trusted Racer"


def test_stats_other_account_rows():
    from neopedal.ui.quick.stats_common import other_account_rows

    other = dr.OtherAccount("2", "", "C:/pic.png", dr.DriverRanks("", "2", "", "", None, dr.Rank("Silver", 3, 0),
                                                                     "sr-clean"), 1_900_000_000)
    row = other_account_rows([other])[0]
    assert row["name"] == "Other account" and row["avatar"].startswith("file:")
    assert row["ranks"] == [{"label": "SR", "value": "Silver 3", "color": dr.RANK_COLORS["silver"],
                             "lightColor": dr.RANK_COLORS_LIGHT["silver"]}]
    assert row["badge"]["name"] == "Good Driver" and row["when"]
