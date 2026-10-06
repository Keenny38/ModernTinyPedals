"""Tests for the UI panels changed while clearing the type errors

The widget preview kept its scroll area under a name that shadowed an inherited Qt method,
and the fuel history table built its rows inside the enumerate() call that consumed them.
Neither screen had any coverage, so these pin down what they produce.
"""

import pytest

from tinypedal.module_info import ConsumptionDataSet


def lap(number: int, *, valid: bool = True) -> ConsumptionDataSet:
    return ConsumptionDataSet(
        lapNumber=number, isValidLap=int(valid), lapTimeLast=95.0 + number,
        lastLapUsedFuel=2.5, lastLapUsedEnergy=3.1, batteryDrainLast=1.0,
        batteryRegenLast=0.4, tyreAvgWearLast=0.8, capacityFuel=100.0,
    )


def test_fuel_history_table_keeps_its_columns_and_highlight(ui_env):
    from tinypedal.ui.race_calculator import RaceCalculator

    dialog = RaceCalculator(None)
    try:
        backend = dialog.backend
        backend.refresh_history([lap(1), lap(2, valid=False), lap(3)])
        history = backend.history
        rows = history["rows"]
        assert len(rows) == 3
        assert len(history["columns"]) == 10 and all(len(row["cells"]) == 10 for row in rows)
        assert rows[0]["cells"][0] == "1"  # lap number
        assert rows[0]["cells"][1] == "1:36.000"  # lap time, formatted
        # Only the invalid lap is marked (its time, fuel & energy shown in invalid color)
        assert [row["valid"] for row in rows] == [True, False, True] and history["invalidColor"] == "#FF4400"
        # A column without a highlight colour is still filled in
        assert rows[1]["cells"][0] == "2"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_fuel_history_table_accepts_an_empty_history(ui_env):
    from tinypedal.ui.race_calculator import RaceCalculator

    dialog = RaceCalculator(None)
    try:
        dialog.backend.refresh_history([])
        assert dialog.backend.history["rows"] == [] and dialog.backend.history["empty"]
    finally:
        dialog.close()
        dialog.deleteLater()


@pytest.mark.parametrize("value", [160, 0, -5])
def test_unit_hint_handles_any_stored_number(value):
    from tinypedal.ui._option import unit_hint

    assert unit_hint("tyre_pressure_target_minimum", str(value), {"tyre_pressure_unit": "bar"})


def test_pace_notes_player_ticks_in_background(ui_env):
    """Audio player is not a page: it keeps queueing notes while no window shows (no visibility check)"""
    from tinypedal.module_info import minfo
    from tinypedal.setting import cfg
    from tinypedal.ui.pace_notes_player import PaceNotesPlayer

    player = PaceNotesPlayer(None, cfg.user.setting["pace_notes_playback"])
    try:
        player.reset_playback()
        player.timerEvent(None)  # was AttributeError (isVisible) after hidden page refresh change
        assert player._last_notes_index == minfo.pacenotes.out.currentIndex
    finally:
        player.deleteLater()
