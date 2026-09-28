"""Tests for the UI panels changed while clearing the type errors

The widget preview kept its scroll area under a name that shadowed an inherited Qt method,
and the fuel history table built its rows inside the enumerate() call that consumed them.
Neither screen had any coverage, so these pin down what they produce.
"""

import pytest

from tinypedal.module_info import ConsumptionDataSet
from tinypedal.setting import cfg


def lap(number: int, *, valid: bool = True) -> ConsumptionDataSet:
    return ConsumptionDataSet(
        lapNumber=number, isValidLap=int(valid), lapTimeLast=95.0 + number,
        lastLapUsedFuel=2.5, lastLapUsedEnergy=3.1, batteryDrainLast=1.0,
        batteryRegenLast=0.4, tyreAvgWearLast=0.8, capacityFuel=100.0,
    )


def test_fuel_history_table_keeps_its_columns_and_highlight(ui_env):
    from tinypedal.ui.fuel_calculator import FuelCalculator

    dialog = FuelCalculator(None)
    try:
        dialog.panel_history.refresh([lap(1), lap(2, valid=False), lap(3)])
        table = dialog.panel_history.table_history
        assert table.rowCount() == 3
        assert table.columnCount() == 10
        assert table.item(0, 0).text() == "1"  # lap number
        assert table.item(0, 1).text() == "1:36.000"  # lap time, formatted
        # Only the invalid lap's time is recoloured; the rows around it are not
        invalid = table.item(1, 1).foreground().color().name()
        assert invalid == "#ff4400"
        assert table.item(0, 1).foreground().color().name() != invalid
        # A column without a highlight colour is still filled in
        assert table.item(1, 0).text() == "2"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_fuel_history_table_accepts_an_empty_history(ui_env):
    from tinypedal.ui.fuel_calculator import FuelCalculator

    dialog = FuelCalculator(None)
    try:
        dialog.panel_history.refresh([])
        assert dialog.panel_history.table_history.rowCount() == 0
    finally:
        dialog.close()
        dialog.deleteLater()


def test_widget_preview_renders_the_widget(ui_env):
    from tinypedal.ui.widget_preview import WidgetPreview

    preview = WidgetPreview(None, cfg, "speedometer", lambda: dict(cfg.user.setting["speedometer"]))
    try:
        preview.toggle(True)
        preview.refresh()
        assert preview.label_preview.pixmap() is not None
        assert not preview.label_preview.pixmap().isNull()
        # scroll_area, not scroll: QWidget already has a scroll() method of its own
        assert hasattr(preview, "scroll_area")
        assert callable(preview.scroll)
    finally:
        preview.deleteLater()


def test_widget_preview_stops_when_toggled_off(ui_env):
    from tinypedal.ui.widget_preview import WidgetPreview

    preview = WidgetPreview(None, cfg, "speedometer", lambda: dict(cfg.user.setting["speedometer"]))
    try:
        preview.toggle(False)
        assert not preview.scroll_area.isVisible()
    finally:
        preview.deleteLater()


@pytest.mark.parametrize("value", [160, 0, -5])
def test_unit_hint_handles_any_stored_number(value):
    from tinypedal.ui._option import unit_hint

    assert unit_hint("tyre_pressure_target_minimum", str(value), {"tyre_pressure_unit": "bar"})
