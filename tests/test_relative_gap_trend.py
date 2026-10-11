"""Modern relative: gap trend column (gap change per lap, green when player gains, red when player loses)"""

from types import SimpleNamespace

import pytest

from neopedal.widget._modern.table import TREND, Row
from tests.test_modern_table_rows import new_table, sample


def relative(**options):
    from neopedal.setting import cfg

    cfg.user.setting["relative"].update(options)
    return new_table(cfg, "relative")


def trend_cells(widget) -> list:
    keys = [column.key for column in widget.table.columns]
    if "gap_trend" not in keys:
        return []
    column = keys.index("gap_trend")
    return [row.cells[column] for row in widget.state if isinstance(row, Row)]


def car(player=False, in_pit=0):
    return SimpleNamespace(isPlayer=player, inPit=in_pit)


@pytest.mark.parametrize(("gap", "rate", "expected"), [
    (2.0, -0.4, (-0.4, True)),  # closing on car ahead: good, arrow down
    (2.0, 0.3, (0.3, False)),  # car ahead pulling away: bad, arrow up
    (-1.5, -0.3, (-0.3, False)),  # car behind closing: bad
    (-1.5, 0.5, (0.5, True)),  # pulling away from car behind: good
    (2.0, 0.02, None),  # steady
    (2.0, None, None),  # unknown
])
def test_trend_cell(ui_env, bundled_fonts, gap, rate, expected):
    widget = relative()
    try:
        cell = widget.trend_cell(gap, rate, car())
        assert cell.kind == TREND and cell.extra == expected
        assert widget.trend_cell(gap, -0.8, car(in_pit=1)).extra is None  # pit lane: steady dash
        assert widget.trend_cell(0.0, -0.8, car(player=True)).text == ""  # player row: empty
    finally:
        widget.deleteLater()


def test_live_trends_from_relative_module(ui_env, monkeypatch):
    from neopedal.api_control import api
    from neopedal.module_info import minfo
    from neopedal.widget._modern.relative import live_trends

    monkeypatch.setattr(api.read.timing, "estimated_laptime", lambda *args: 100.0)
    ahead, behind = minfo.relative.relativeDeltaAhead, minfo.relative.relativeDeltaBehind
    for delta in (ahead[3], behind[4], ahead[5], behind[5]):
        monkeypatch.setattr(delta, "short", 0.0)
    monkeypatch.setattr(ahead[3], "short", 0.004)  # gap to car ahead shrinking 0.004 s per second
    monkeypatch.setattr(behind[4], "short", -0.002)  # gap to car behind growing
    trend = live_trends()
    assert trend(5.0, 3) == pytest.approx(-0.4)
    assert trend(-3.0, 4) == pytest.approx(0.2)
    assert trend(5.0, 5) is None  # no average yet
    monkeypatch.setattr(api.read.timing, "estimated_laptime", lambda *args: 0.0)
    assert live_trends()(5.0, 3) is None  # lap time unknown


def test_sample_rows_show_trends_and_column_can_be_hidden(ui_env, bundled_fonts):
    widget = relative(column_gap_trend=True)
    try:
        field, context = sample(widget)
        widget.show_field(field, context)
        cells = trend_cells(widget)
        assert any(cell.extra and cell.extra[1] for cell in cells)  # player gains on some cars
        assert any(cell.extra and not cell.extra[1] for cell in cells)  # loses on others
    finally:
        widget.deleteLater()
    hidden = relative(column_gap_trend=False)
    try:
        field, context = sample(hidden)
        hidden.show_field(field, context)
        assert trend_cells(hidden) == []
    finally:
        hidden.deleteLater()
