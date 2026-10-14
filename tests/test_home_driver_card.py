"""Driver card of Home page: ranks (change, badge, remembered date), profile, race record of results files"""

from neopedal.process import driver_ranks as dr
from neopedal.process import results_index as ri
from neopedal.process.player_profile import PlayerProfile
from neopedal.ui.home_driver import DriverData, driver_card_text

PLAYER = dr.DriverRanks("Keenny Hess", "76561190000000001", "", "FR", dr.Rank("Silver", 2, 55),
                        dr.Rank("Platinum", 3, 50), "sr-clean")
PROFILE = PlayerProfile("Keenny Hess", "", "FR", "Team NP", "38", "")
RECORD = ri.RaceRecord(races=4, wins=1, podiums=2, average_finish=3.5, clean=3, contacts=2)


def test_nothing_known_hides_card():
    assert driver_card_text(None, False, 0.0, [], None, False) is None
    assert driver_card_text(None, False, 0.0, [], DriverData(None, ri.RaceRecord(0, 0, 0, 0.0, 0, 0), ""), False) is None


def test_full_card():
    history = [dr.HistoryEntry(1.0, dr.Rank("Silver", 2, 40), dr.Rank("Platinum", 3, 50))]
    value, detail = driver_card_text(PLAYER, False, 2.0, history, DriverData(PROFILE, RECORD, "Keenny Hess"), False)
    assert "<b>Keenny Hess</b>" in value
    assert "DR Silver 2" in value and "55%" in value and "+15%" in value  # change since previous rank
    assert "SR Platinum 3" in value and "+0%" not in value  # unchanged: no change shown
    assert dr.RANK_COLORS["silver"] in value and "Good Driver" in value
    assert "Team NP" in detail and "#38" in detail
    assert "4" in detail and "3/4" in detail and "P3" in detail
    assert "Last ranks seen" not in detail


def test_remembered_ranks_dated_light_colors():
    value, detail = driver_card_text(PLAYER, True, 1_900_000_000, [], None, True)
    assert dr.RANK_COLORS_LIGHT["silver"] in value
    assert "Last ranks seen in game menu" in detail


def test_races_only_uses_results_name():
    value, detail = driver_card_text(None, False, 0.0, [], DriverData(None, RECORD, "Flo"), False)
    assert "<b>Flo</b>" in value and "DR" not in value and "3/4" in detail


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


def test_other_accounts_lines():
    other = dr.OtherAccount("2", "Second", "", dr.DriverRanks("Second", "2", "", "", dr.Rank("Gold", 1, 65), None,
                                                               "sr-saint"), 1_900_000_000)
    value, detail = driver_card_text(None, False, 0.0, [], None, False, [other])  # active account unknown yet
    assert "<b>Second</b>" not in value and "Second: " in detail
    assert dr.RANK_COLORS["gold"] in detail and "DR Gold 1" in detail and "Trusted Racer" in detail
    unnamed = other._replace(name="")
    assert "Other account: " in driver_card_text(PLAYER, False, 0.0, [], None, False, [unnamed])[1]


def test_stats_other_account_rows():
    from neopedal.ui.quick.stats_backend import other_account_rows

    other = dr.OtherAccount("2", "", "C:/pic.png", dr.DriverRanks("", "2", "", "", None, dr.Rank("Silver", 3, 0),
                                                                     "sr-clean"), 1_900_000_000)
    row = other_account_rows([other])[0]
    assert row["name"] == "Other account" and row["avatar"].startswith("file:")
    assert row["ranks"] == [{"label": "SR", "value": "Silver 3", "color": dr.RANK_COLORS["silver"],
                             "lightColor": dr.RANK_COLORS_LIGHT["silver"]}]
    assert row["badge"]["name"] == "Good Driver" and row["when"]
