"""Relative module ordering tests

The standings widget shows the top few of each class plus a window around the player. That
window is built by the pure helpers below, which had no coverage: an off-by-one here silently
shows the wrong cars.
"""

import pytest

from tinypedal.module.module_relative import (
    calc_standings_index,
    create_reference_place,
    max_vehicles_in_class,
    min_top_vehicles_in_class,
    sort_class_collection,
    split_class_list,
    standings_index_from_place_reference,
    standings_index_from_same_class,
    update_position_in_class,
)


# (class name, place, vehicle index, class best laptime, last laptime)
def entry(class_name, place, index, best=100.0, last=101.0):
    return (class_name, place, index, best, last)


# --- Reference place window
def test_whole_field_shown_when_it_fits():
    assert create_reference_place(3, 6, 4, 10) == (1, 2, 3, 4, 5, 6)


def test_leader_window_is_just_the_top():
    """A player inside the top N needs no separate window"""
    assert create_reference_place(3, 20, 2, 8) == (1, 2, 3, 4, 5, 6, 7, 8)


def test_midfield_player_gets_top_plus_a_window_around_themselves():
    places = create_reference_place(3, 20, 12, 8)
    assert places[:3] == (1, 2, 3)  # class leaders always shown
    assert 12 in places  # the player
    assert len(places) == 8  # never more than the limit
    assert places == tuple(sorted(places)), "places must stay in running order"


def test_window_at_the_back_does_not_run_past_the_field():
    places = create_reference_place(3, 20, 20, 8)
    assert max(places) == 20
    assert len(places) == 8
    assert 20 in places


def test_window_keeps_at_least_as_many_cars_ahead_as_behind():
    """Seeing who you are catching matters more than seeing who is catching you"""
    places = create_reference_place(3, 30, 15, 9)
    window = [place for place in places if place > 3]
    ahead = [place for place in window if place < 15]
    behind = [place for place in window if place > 15]
    assert len(ahead) >= len(behind)


# --- Index lists
def test_place_reference_maps_to_vehicle_indexes_and_ends_with_a_gap():
    class_list = [entry("GT3", place, index) for place, index in ((1, 7), (2, 3), (3, 9))]
    result = list(standings_index_from_place_reference((1, 2, 3), class_list, 3))
    assert result == [7, 3, 9, -1]  # -1 separates classes


def test_place_reference_stops_at_the_end_of_the_field():
    class_list = [entry("GT3", 1, 7)]
    assert list(standings_index_from_place_reference((1, 2, 3), class_list, 1)) == [7, -1]


def test_standings_index_for_the_player_class():
    class_pos_list = [entry("GT3", place, place * 10) for place in range(1, 5)]
    class_pos_list += [entry("LMP2", place, place) for place in range(1, 3)]
    result = standings_index_from_same_class(3, class_pos_list, "GT3", 2, 10)
    assert result == [10, 20, 30, 40, -1]


def test_standings_index_is_empty_when_the_player_class_is_absent():
    class_pos_list = [entry("LMP2", 1, 1)]
    assert standings_index_from_same_class(3, class_pos_list, "GT3", 1, 10) == [-1]


def test_standings_index_respects_the_vehicle_limit():
    class_list = [entry("GT3", place, place) for place in range(1, 21)]
    result = calc_standings_index(3, 6, 12, class_list)
    assert len(result) == 7  # six vehicles plus the gap marker
    assert result[-1] == -1


# --- Class splitting and ordering
def test_class_list_splits_on_each_class_change():
    class_list = [
        entry("LMP2", 1, 0), entry("LMP2", 2, 1), entry("GT3", 1, 2), entry("GT3", 2, 3), entry("GTE", 1, 4),
    ]
    groups = [[vehicle[0] for vehicle in group] for group in split_class_list(class_list)]
    assert groups == [["LMP2", "LMP2"], ["GT3", "GT3"], ["GTE"]]


def test_single_class_field_yields_one_group():
    class_list = [entry("GT3", 1, 0), entry("GT3", 2, 1)]
    assert len(list(split_class_list(class_list))) == 1


def test_classes_are_ordered_by_their_best_laptime():
    slow = [entry("GT3", 1, 0, best=110.0)]
    fast = [entry("LMP2", 1, 1, best=95.0)]
    assert sorted([slow, fast], key=sort_class_collection) == [fast, slow]


# --- Limits
@pytest.mark.parametrize(("value", "expected"), [(0, 1), (1, 1), (3, 3), (5, 5), (99, 5), (-4, 1)])
def test_top_vehicle_count_is_clamped(value, expected):
    assert min_top_vehicles_in_class(value) == expected


def test_class_vehicle_limit_never_cuts_into_the_top():
    assert max_vehicles_in_class(2, 3) == 3  # asking for fewer than the top count
    assert max_vehicles_in_class(10, 3) == 10
    assert max_vehicles_in_class(2, 3, 2) == 5  # player class keeps extra slots


# --- Position in class
def test_position_in_class_numbers_each_class_separately(ui_env):
    from tinypedal.module_info import minfo

    sorted_veh_class = [
        entry("LMP2", 1, 0, best=95.0, last=96.0),
        entry("LMP2", 2, 1, best=95.0, last=95.5),
        entry("GT3", 3, 2, best=110.0, last=111.0),
        entry("GT3", 4, 3, best=110.0, last=110.5),
    ]
    class_name, place = update_position_in_class(sorted_veh_class, plr_index=3)

    assert (class_name, place) == ("GT3", 2)
    veh_data = minfo.vehicles.dataSet
    assert [veh_data[index].positionInClass for index in range(4)] == [1, 2, 1, 2]
    assert veh_data[0].classLeaderIndex == 0
    assert veh_data[2].classLeaderIndex == 2  # a class of its own, own leader
    assert veh_data[0].classAheadIndex == -1  # class leader has nobody ahead
    assert veh_data[1].classAheadIndex == 0
    # Fastest last lap is marked once per class
    assert veh_data[1].isClassFastestLastLap
    assert veh_data[3].isClassFastestLastLap
    assert not veh_data[0].isClassFastestLastLap
