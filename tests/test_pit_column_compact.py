"""Pit status column of modern driver lists: one slot (status shown instead of pit stops) or both side by side"""

import pytest


@pytest.mark.parametrize("name", ["standings", "relative"])
def test_pit_column_one_slot_by_default(ui_env, bundled_fonts, name):
    from neopedal.setting import cfg
    from neopedal.widget._modern.table import PAIR, PILL
    from tests.test_modern_table_rows import new_table, sample
    from tests.test_standings_gaps_columns import column_cells

    setting = cfg.user.setting[name]
    assert not setting["show_pit_stops_beside_status"]
    compact = new_table(cfg, name)
    cars, context = sample(compact)
    cars.vehicles[cars.player_index].inPit = 1  # in pit lane (shown by both): status instead of pit stops
    compact.show_field(cars, context)
    cells = column_cells(compact, "pit_status")
    assert all(cell.kind != PAIR for cell in cells)
    assert any(cell.kind == PILL and cell.text for cell in cells)
    assert any(cell.kind != PILL for cell in cells)  # others: pit stops or penalty
    compact_width = next(column.width for column in compact.table.columns if column.key == "pit_status")
    compact.grab()
    setting["show_pit_stops_beside_status"] = True
    try:
        wide = new_table(cfg, name)
        wide.show_field(cars, context)
        assert all(cell.kind == PAIR for cell in column_cells(wide, "pit_status"))
        wide_width = next(column.width for column in wide.table.columns if column.key == "pit_status")
        assert compact_width < wide_width * 0.6
        wide.deleteLater()
    finally:
        setting["show_pit_stops_beside_status"] = False
    compact.deleteLater()
