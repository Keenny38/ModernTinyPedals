"""Driver lists: badge column apart from driver & safety ranks, class column without class name;
fuel & virtual energy: every value shown by its own option (2026-10-29)"""

import pytest

from neopedal.module_info import minfo
from neopedal.setting_preupdate import preupdate_user_setting
from tests.test_modern_parity import reader, update, widgets  # noqa: F401 (fixture)

FUEL_CELLS = ("remaining", "estimated_laps", "estimated_minutes", "estimated_consumption", "saving_target",
              "pitstop_count", "early_pitstop_count", "delta_consumption", "end_remaining")


# --- Class column: position in class alone, on class color
@pytest.mark.parametrize("name", ["relative", "standings", "rivals"])
def test_class_column_without_class_name(widgets, name):  # noqa: F811
    from neopedal.widget._modern.draw import readable_on
    from neopedal.widget._modern.rows import class_style
    from neopedal.widget._modern.table import BADGE, CLASS
    from tests.test_modern_table_rows import sample
    from tests.test_standings_gaps_columns import column_cells

    options = {"show_class_header": False} if name == "standings" else {}
    named = widgets(name, column_class=True, **options)
    cars, context = sample(named)
    named.show_field(cars, context)
    assert all(cell.kind == CLASS for cell in column_cells(named, "class"))
    plain = widgets(name, column_class=True, show_class_name=False, **options)
    plain.show_field(cars, context)
    cells = column_cells(plain, "class")
    assert cells and all(cell.kind == BADGE for cell in cells)
    class_colors = {class_style(plain.cfg, veh.vehicleClass, plain.theme)[1].rgba() for veh in cars.vehicles}
    assert all(cell.fill.rgba() in class_colors and cell.color == readable_on(cell.fill) for cell in cells)
    assert {cell.text for cell in cells} <= {f"{veh.positionInClass}" for veh in cars.vehicles}
    width = {column.key: column.width for column in plain.table.columns}["class"]
    assert width < {column.key: column.width for column in named.table.columns}["class"]
    plain.grab()  # drawn


def test_class_style_option_unused_without_class_name():
    from neopedal.template.widget.drivers_ui import class_column_inactive

    assert class_column_inactive({"column_class": True, "show_class_name": False}) == {
        "show_class_style_for_position_in_class": ("on", "show_class_name")}
    assert class_column_inactive({"column_class": True, "show_class_name": True}) == {}
    hidden = class_column_inactive({"column_class": True}, class_headers=True)
    assert hidden["show_class_name"] == ("off", "show_class_header")


def test_badge_column_in_column_lists():
    from neopedal.template.widget.drivers_ui import RELATIVE_UI, RIVALS_UI, STANDINGS_UI

    for ui in (RELATIVE_UI, STANDINGS_UI, RIVALS_UI):
        assert ui.order_toggles["display_order_driver_badge"] == "column_driver_badge"
        assert ui.order_labels["display_order_driver_badge"] == "Driver Badge"
        assert "show_driver_badge" not in ui.dependencies
        assert ui.dependencies["show_class_name"] == "column_class"


# --- Preset update: badge column where badge was shown, value pairs split
def test_badge_column_from_former_option():
    from neopedal.template.setting_widget import WIDGET_DEFAULT

    shown = {"relative": {"column_driver_ranks": True, "show_driver_badge": True},
             "standings": {"column_driver_ranks": True, "show_driver_badge": False},
             "rivals": {"column_driver_ranks": False, "show_driver_badge": True}}
    preupdate_user_setting((2, 51, 3), shown)
    assert shown["relative"] == {"column_driver_ranks": True, "column_driver_badge": True}  # default orders kept
    assert shown["standings"] == {"column_driver_ranks": True}
    assert shown["rivals"] == {"column_driver_ranks": False}
    # Display orders of user: badge right after ranks, columns after it moved one place
    orders = {key: value for key, value in WIDGET_DEFAULT["relative"].items()
              if key.startswith("display_order_") and key != "display_order_driver_badge"}  # options of 2.51.3
    orders["display_order_driver_ranks"] = 3
    orders["display_order_position"] = 30
    custom = {"relative": {"column_driver_ranks": True, "show_driver_badge": True, **orders}}
    preupdate_user_setting((2, 51, 3), custom)
    relative = custom["relative"]
    assert relative["display_order_driver_badge"] == 4
    assert relative["display_order_position"] == 31
    for key, value in orders.items():
        assert relative[key] == (value + 1 if value > 3 else value), key


@pytest.mark.parametrize("name", ["fuel", "virtual_energy"])
def test_value_pairs_split_from_former_options(name):
    preset = {name: {"show_estimated_pitstop_count": False, "show_delta_consumption_and_end_remaining": False,
                     "show_fuel_ratio_and_fuel_bias": False}}
    preupdate_user_setting((2, 51, 3), preset)
    assert preset[name] == {
        "show_estimated_pitstop_count": False, "show_early_pitstop_count": False,
        "show_delta_consumption": False, "show_end_remaining": False,
        "show_fuel_ratio": False, "show_fuel_bias": False,
    }
    shown = {name: {"show_estimated_pitstop_count": True}}
    preupdate_user_setting((2, 51, 3), shown)
    assert shown[name] == {"show_estimated_pitstop_count": True, "show_early_pitstop_count": True}
    current = {name: {"show_estimated_pitstop_count": False}}
    preupdate_user_setting((2, 51, 4), current)  # saved by this version: nothing changed
    assert current[name] == {"show_estimated_pitstop_count": False}


# --- Fuel & virtual energy: each value on its own
@pytest.mark.parametrize("name", ["fuel", "virtual_energy"])
def test_modern_tiles_each_switched(widgets, name):  # noqa: F811
    every = widgets(name)
    keys = ("laps", "minutes", "used", "save", "pits", "early", "delta", "end")
    assert every.keys == ((*keys, "ratio", "bias") if name == "virtual_energy" else keys)
    assert every.show_remaining and every.show_refill
    update(every)
    some = widgets(name, show_estimated_minutes=False, show_early_pitstop_count=False, show_end_remaining=False,
                   show_fuel_bias=False, show_refueling=False, show_refilling=False)
    assert some.keys == (("laps", "used", "save", "pits", "delta") + (("ratio",) if name == "virtual_energy" else ()))
    assert some.show_remaining and not some.show_refill
    update(some)
    assert len(some.state[0]) == len(some.keys)
    no_top = widgets(name, show_remaining=False, show_refueling=False, show_refilling=False)
    assert no_top.rect_hero.height() == 0 and no_top.height() < every.height()
    update(no_top)
    nothing = widgets(name, show_remaining=False, show_refueling=False, show_refilling=False,
                      **{f"show_{key}": False for key in ("estimated_laps", "estimated_minutes", "estimated_consumption",
                                                           "saving_target", "estimated_pitstop_count",
                                                           "early_pitstop_count", "delta_consumption",
                                                           "end_remaining", "fuel_ratio", "fuel_bias")})
    assert nothing.keys == () and nothing.width() > 0
    update(nothing)


def classic_columns(widget) -> dict[str, tuple[int, int]]:
    """Shown cell name -> (row layout: 0 upper, 1 lower, column)"""
    places = {}
    for row, layout in enumerate((widget.layout_upper, widget.layout_lower)):
        for name, cell in widget.cells.items():
            index = layout.indexOf(cell)
            if index >= 0:
                places[name] = (row, layout.getItemPosition(index)[1])
    return places


@pytest.mark.parametrize("name", ["fuel", "virtual_energy"])
def test_classic_cells_each_switched(widgets, monkeypatch, name):  # noqa: F811
    refill = "refueling" if name == "fuel" else "refilling"
    every = widgets(name, modern=False)
    places = classic_columns(every)
    assert places["pitstop_count"] == (0, 0) and places["early_pitstop_count"] == (1, 0)
    assert places["remaining"] == (0, 1) and places[refill] == (0, 2)
    assert every.column_count == (6 if name == "virtual_energy" else 5)
    # Hidden cell under a shown one: place kept (columns aligned); column of hidden cells: left out
    some = widgets(name, modern=False, show_estimated_laps=False, show_estimated_pitstop_count=False,
                   show_early_pitstop_count=False)
    places = classic_columns(some)
    assert "estimated_laps" not in places and "pitstop_count" not in places
    assert places["remaining"] == (0, 0) and places[refill] == (0, 1) and places["estimated_minutes"] == (1, 1)
    assert some.layout_lower.columnMinimumWidth(0) == some.style_width  # empty place under remaining
    assert some.column_count == every.column_count - 1
    some.timerEvent(None)  # hidden cells not updated
    some.grab()
    # Lower row only: upper row cells all hidden
    lower = widgets(name, modern=False, show_remaining=False, **{f"show_{refill}": False},
                    show_estimated_consumption=False, show_estimated_pitstop_count=False, show_delta_consumption=False,
                    show_fuel_ratio=False)
    assert {row for row, _ in classic_columns(lower).values()} == {1}
    lower.timerEvent(None)
    lower.grab()
    monkeypatch.setattr(minfo.fuel, "estimatedValidConsumption", 3.0)  # low warning without remaining cell
    lower.timerEvent(None)


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("name", ["fuel", "virtual_energy"])
def test_options_page_section_of_each_value(ui_env, name, modern):
    from neopedal.setting import cfg
    from neopedal.ui.quick.overlay_options_backend import build_layout

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    values = {**cfg.user.setting[name], "enable_classic_layout": not modern}
    layout = build_layout(name, values)
    early = layout.section_of["show_early_pitstop_count"]
    assert early.toggle == "show_early_pitstop_count"  # own section, not part of pit stops
    assert layout.section_of["decimal_places_early_pitstop_count"] is early
    assert layout.dependencies["decimal_places_early_pitstop_count"] == "show_early_pitstop_count"
    assert "show_early_pitstop_count" not in layout.dependencies
    assert layout.dependencies["decimal_places_pitstop_count"] == "show_estimated_pitstop_count"
    assert layout.dependencies["decimal_places_end_remaining"] == "show_end_remaining"
    refill = "refueling" if name == "fuel" else "refilling"
    assert layout.dependencies[f"show_absolute_{refill}"] == f"show_{refill}"
    assert layout.dependencies["decimal_places_remaining"] == "show_remaining"
