"""Modern design honours classic options it used to ignore, and driver list columns shared by Relative,
Standings & Rivals (defaults keep the modern look: new columns off, option defaults give design values)"""

import pytest

from neopedal.setting import cfg
from neopedal.template.setting_widget import WIDGET_DEFAULT
from neopedal.widget._modern import modern_module
from neopedal.widget._modern.table import DELTAS, PAIR, TEXT, TREND, Row
from tests.test_design_parity import shown_options
from tests.test_modern_parity import reader, stat_value, update, widgets  # noqa: F401 (fixture)
from tests.test_modern_table_rows import sample

CLASSIC_OPTIONS = (
    ("friction_circle", "trace_fade_out_step"),
    ("sectors", "extra_digits"),
    ("rivals", "show_inverted_delta_laptime_layout"),
    ("standings", "show_inverted_delta_laptime_layout"),
    ("standings", "split_gap"),
    ("telemetry_compare", "reference_line_opacity"),
    ("speedometer", "leading_zero"),
    ("tyre_pressure", "show_compound_color_by_type"),
    ("weather_forecast", "icon_size"),
)
NEW_COLUMNS = {
    "relative": ("track_limits", "energy_per_lap", "delta_laptime"),
    "standings": ("gap_trend",),
    "rivals": ("track_limits", "driver_ranks", "gap_trend"),
}


@pytest.mark.parametrize(("name", "key"), CLASSIC_OPTIONS)
def test_classic_option_shown_for_modern_design(ui_env, name, key):
    assert key in modern_module(name).Realtime.options
    assert key in shown_options(name, True)


@pytest.mark.parametrize("name", sorted(NEW_COLUMNS))
def test_new_columns_off_by_default_and_modern_only(ui_env, name):
    options = modern_module(name).Realtime.options
    for column in NEW_COLUMNS[name]:
        assert WIDGET_DEFAULT[name][f"column_{column}"] is False
        assert f"column_{column}" in options and f"display_order_{column}" in options
        assert f"column_{column}" in shown_options(name, True)
        assert f"column_{column}" not in shown_options(name, False)  # classic layout has no such column
    orders = [value for key, value in WIDGET_DEFAULT[name].items() if key.startswith("display_order_")]
    assert len(orders) == len(set(orders))  # every column at its own place once order changed


def column_cells(widget, key: str) -> list:
    index = [column.key for column in widget.table.columns].index(key)
    return [row.cells[index] for row in widget.state if isinstance(row, Row)]


def shown_sample(widgets, name: str, **options):  # noqa: F811
    widget = widgets(name, **options)
    field, context = sample(widget)
    widget.show_field(field, context)
    return widget


@pytest.mark.parametrize("name", sorted(NEW_COLUMNS))
def test_new_columns_hidden_by_default(widgets, name):  # noqa: F811
    widget = shown_sample(widgets, name)
    keys = {column.key for column in widget.table.columns}
    assert not keys & set(NEW_COLUMNS[name])


def test_relative_track_limits_energy_and_delta_columns(widgets):  # noqa: F811
    widget = shown_sample(widgets, "relative", column_track_limits=True, column_energy_per_lap=True,
                          column_delta_laptime=True, number_of_delta_laptime=4)
    theme = widget.theme
    limits = {cell.text: cell.color for cell in column_cells(widget, "track_limits")}
    assert limits["1.25"] == theme.warning and limits["4.25"] == theme.negative  # sample penalty limit 5
    energy = [cell.text for cell in column_cells(widget, "energy_per_lap")]
    assert any(text.endswith("%") for text in energy)
    deltas = [cell for cell in column_cells(widget, "delta_laptime") if cell.extra]
    assert deltas and all(cell.kind == DELTAS and len(cell.extra) == 4 for cell in deltas)
    player_row = next(row for row in widget.state if isinstance(row, Row) and row.player)
    assert player_row.cells[[column.key for column in widget.table.columns].index("delta_laptime")].extra is None


def test_track_limits_penalty_read_only_with_column(widgets, monkeypatch):  # noqa: F811
    reader(monkeypatch, "session", "limits_points", 3.0)
    shown = widgets("rivals", column_track_limits=True)
    update(shown)
    assert shown.limit == 3.0
    hidden = widgets("rivals", column_track_limits=False)
    update(hidden)
    assert hidden.limit == 0.0


def test_standings_gap_trend_by_race_position(widgets):  # noqa: F811
    widget = shown_sample(widgets, "standings", column_gap_trend=True, enable_multi_class_split_mode=False)
    trends = [cell for cell in column_cells(widget, "gap_trend") if cell.kind == TREND and cell.extra]
    assert any(good for _, good in (cell.extra for cell in trends))
    assert any(not good for _, good in (cell.extra for cell in trends))
    widget.grab()


def test_rivals_track_limits_ranks_and_gap_trend(widgets):  # noqa: F811
    widget = shown_sample(widgets, "rivals", column_track_limits=True, column_driver_ranks=True,
                          column_gap_trend=True)
    ahead, behind = column_cells(widget, "gap_trend")
    assert ahead.extra == (-0.4, True)  # closing on car ahead: good
    assert behind.extra == (-0.3, False)  # car behind closing: bad
    assert all(cell.kind == PAIR for cell in column_cells(widget, "driver_ranks"))
    assert all(cell.kind == TEXT for cell in column_cells(widget, "track_limits"))
    widget.grab()


@pytest.mark.parametrize("name", ["standings", "rivals", "relative"])
def test_inverted_delta_layout(widgets, name):  # noqa: F811
    normal = shown_sample(widgets, name, column_delta_laptime=True)
    inverted = shown_sample(widgets, name, column_delta_laptime=True, show_inverted_delta_laptime_layout=True)
    pairs = [(a.extra, b.extra) for a, b in zip(column_cells(normal, "delta_laptime"),
                                                column_cells(inverted, "delta_laptime")) if a.extra]
    assert pairs and all(after == before[::-1] for before, after in pairs)


def test_standings_split_gap(widgets):  # noqa: F811
    default = widgets("standings")
    assert default.table.separator == default.table.row_height * 0.32  # design space at default (5)
    assert widgets("standings", split_gap=0).table.separator == 0
    wide = widgets("standings", split_gap=10)
    assert wide.table.separator == pytest.approx(default.table.separator * 2)


def test_friction_circle_trace_fade_step(widgets):  # noqa: F811
    from neopedal.widget._modern.friction_circle import TRACE_PARTS, trace_alpha

    default = widgets("friction_circle", show_trace_fade_out=True)
    assert [color.alpha() for color in default.trace_colors] == [
        round(255 * (index + 1) / TRACE_PARTS) for index in range(TRACE_PARTS)]  # design gradient at default
    fast = [trace_alpha(index, 0.9) for index in range(TRACE_PARTS)]
    slow = [trace_alpha(index, 0.1) for index in range(TRACE_PARTS)]
    assert fast[-1] == slow[-1] == 255 and fast[0] == 0 and slow[0] > default.trace_colors[0].alpha()
    assert trace_alpha(0, 5.0) == trace_alpha(0, 0.9)  # range of classic design
    widget = widgets("friction_circle", show_trace_fade_out=True, trace_fade_out_step=0.9)
    from PySide6.QtCore import QPointF

    widget.trace.extend(QPointF(index, index * 2) for index in range(60))
    widget.grab()  # faded out parts skipped


def test_sectors_extra_digits(widgets):  # noqa: F811
    default = widgets("sectors")
    assert default.lap_text(83.456) == "1:23.456" and default.sector_text("+12.345") == "+12.345"
    assert default.rect_tiles[0].width() == default.text_width("value", "+8:88.888") + default.unit * 0.9
    short = widgets("sectors", extra_digits=0)
    assert short.lap_text(83.456) == "1:23.456" and short.sector_text("1:23.456") == "1:23.45"
    assert short.rect_tiles[0].width() < default.rect_tiles[0].width()
    short.restore_best_sectors((30.123, 71.234, 40.5))
    assert [tile[1] for tile in short.tiles] == ["30.123", "1:11.23", "40.500"]


def test_speedometer_leading_zero(widgets, monkeypatch):  # noqa: F811
    reader(monkeypatch, "vehicle", "speed", 10.0)  # 36 km/h
    default = widgets("speedometer")
    update(default)
    assert stat_value(default, "speed").text == "36.0"
    padded = widgets("speedometer", leading_zero=3, decimal_places=0)
    update(padded)
    assert stat_value(padded, "speed").text == "036"


def test_weather_forecast_icon_size(widgets):  # noqa: F811
    default = widgets("weather_forecast")
    unit = default.unit
    assert default.rows["weather_icon"].height() == unit * 2.3 and default.icon_stroke == max(unit * 0.12, 1.2)
    big = widgets("weather_forecast", icon_size=64)
    assert big.rows["weather_icon"].height() == pytest.approx(unit * 4.6)
    assert big.column_w > default.column_w and big.height() > default.height()
    assert widgets("weather_forecast", icon_size=1).rows["weather_icon"].height() == pytest.approx(unit * 1.15)


def test_telemetry_compare_reference_opacity(widgets):  # noqa: F811
    from neopedal.widget._modern.telemetry_compare import DEFAULT_REFERENCE_OPACITY

    assert WIDGET_DEFAULT["telemetry_compare"]["reference_line_opacity"] == DEFAULT_REFERENCE_OPACITY
    default = widgets("telemetry_compare")
    assert {pen.color().alpha() for pen in default.pens_reference.values()} == {130}  # design opacity
    assert {color.alpha() for color in default.fills.values()} == {50}
    full = widgets("telemetry_compare", reference_line_opacity=1.0)
    assert {pen.color().alpha() for pen in full.pens_reference.values()} == {255}
    hidden = widgets("telemetry_compare", reference_line_opacity=0.0)
    assert {color.alpha() for color in hidden.fills.values()} == {0}


def test_tyre_pressure_compound_color_by_type(widgets, monkeypatch):  # noqa: F811
    from neopedal.widget._modern.rows import compound_badge

    reader(monkeypatch, "vehicle", "in_pits", True)
    reader(monkeypatch, "tyre", "compound_class", ("GT3 - Soft",) * 4)
    by_type = widgets("tyre_pressure", show_tyre_compound=True)
    update(by_type)
    assert by_type.compounds.badges[0] == (compound_badge("GT3 - Soft"),)
    plain = widgets("tyre_pressure", show_tyre_compound=True, show_compound_color_by_type=False)
    update(plain)
    (symbol, color), = plain.compounds.badges[0]
    assert symbol == compound_badge("GT3 - Soft")[0] and color == plain.theme.surface_raised


def test_options_page_places_new_options(ui_env):
    from neopedal.ui.quick.overlay_options_backend import build_layout

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    standings = build_layout("standings", cfg.user.setting["standings"])
    assert standings.section_of["split_gap"].title == "Classes & Number of Cars"
    assert standings.section_of["show_inverted_delta_laptime_layout"].title == "Delta Lap Time"
    assert "display_order_gap_trend" in standings.keys
    relative = build_layout("relative", cfg.user.setting["relative"])
    assert relative.section_of["number_of_delta_laptime"].title == "Delta Lap Time"
    assert relative.section_of["show_energy_per_lap_average"].title == "Energy per Lap"
    rivals = build_layout("rivals", cfg.user.setting["rivals"])
    assert rivals.section_of["show_driver_badge"].title == "Driver & Safety Rank"
