"""Modern standings: class name above each class group instead of class column next to each driver"""

import pytest

from tests.test_modern_table_rows import new_table, sample
from tinypedal.widget._modern.table import SEPARATOR, ClassHeader, Row


def items(**options):
    from tinypedal.setting import cfg

    cfg.user.setting["standings"].update(options)
    table = new_table(cfg, "standings")
    field, context = sample(table)
    table.show_field(field, context)
    return table, field


def column_keys(widget) -> list[str]:
    return [column.key for column in widget.table.columns]


def test_class_name_above_each_class_group(ui_env, bundled_fonts):
    widget, _ = items(enable_multi_class_split_mode=True, show_class_header=True)
    try:
        rows = widget.state
        headers = [row for row in rows if isinstance(row, ClassHeader)]
        assert [header.text for header in headers] == ["Hypercar", "LMP2", "GT3"]
        assert isinstance(rows[0], ClassHeader)  # first group too
        for index, row in enumerate(rows[1:], 1):  # header before first car of each class only
            if isinstance(row, ClassHeader):
                assert rows[index - 1] is SEPARATOR
        assert "class" not in column_keys(widget)  # class shown by headers only
        position = column_keys(widget).index("position")
        cars = [row for row in rows if isinstance(row, Row)]
        assert [row.cells[position].text for row in cars[:3]] == ["1", "2", "3"]  # position in class
        assert widget.height() >= widget.table.content_height(rows)
    finally:
        widget.deleteLater()


def test_header_color_of_class(ui_env, bundled_fonts):
    from tinypedal.setting import cfg
    from tinypedal.widget._modern.rows import class_style

    widget, _ = items(enable_multi_class_split_mode=True, show_class_header=True)
    try:
        header = next(row for row in widget.state if isinstance(row, ClassHeader))
        assert header.color == class_style(cfg, "Hypercar", widget.theme)[1]
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("options", [
    {"enable_multi_class_split_mode": True, "show_class_header": False},  # option off
    {"enable_multi_class_split_mode": False, "show_class_header": True},  # combined: classes mixed
])
def test_class_column_without_headers(ui_env, bundled_fonts, options):
    widget, _ = items(enable_single_class_exclusive_mode=False, **options)
    try:
        assert not any(isinstance(row, ClassHeader) for row in widget.state)
        assert "class" in column_keys(widget)
        position = column_keys(widget).index("position")
        cars = [row for row in widget.state if isinstance(row, Row)]
        assert cars[0].cells[position].text == "1" and cars[-1].cells[position].text != "1"  # overall
    finally:
        widget.deleteLater()


def test_exclusive_mode_header_of_player_class(ui_env, bundled_fonts):
    widget, field = items(enable_multi_class_split_mode=False, enable_single_class_exclusive_mode=True,
                          show_class_header=True)
    try:
        headers = [row for row in widget.state if isinstance(row, ClassHeader)]
        assert [header.text for header in headers] == [field.vehicles[field.player_index].vehicleClass]
    finally:
        widget.deleteLater()


def test_header_text_words_apart(ui_env, bundled_fonts):
    widget, _ = items(enable_multi_class_split_mode=True, show_class_header=True)
    try:
        assert widget.class_header("LMP2_ELMS").text == "LMP2 ELMS"
    finally:
        widget.deleteLater()


@pytest.mark.parametrize(("others", "cars"), [(1, [1, 1, 7]), (0, [7])])
def test_cars_of_other_classes_as_asked(ui_env, bundled_fonts, others, cars):
    """Other classes show the number of cars asked, below minimum top too; 0 hides them with their header"""
    widget, field = items(enable_multi_class_split_mode=True, show_class_header=True, minimum_top_vehicles=5,
                          maximum_vehicles_per_split_others=others, maximum_vehicles_per_split_player=7)
    try:
        groups, count = [], 0
        for row in widget.state:
            if isinstance(row, ClassHeader):
                if count:
                    groups.append(count)
                count = 0
            elif isinstance(row, Row):
                count += 1
        groups.append(count)
        assert groups == cars
        headers = [row.text for row in widget.state if isinstance(row, ClassHeader)]
        assert field.vehicles[field.player_index].vehicleClass in headers and len(headers) == len(cars)
    finally:
        widget.deleteLater()


@pytest.mark.parametrize(("order", "expected"), [
    ("Hypercar, Hyper, LMP2 ELMS, LMP2, LMP3, GT3, LMGT3, GTE", ["Hypercar", "LMP2", "GT3"]),  # default
    ("GT3, lmp2", ["GT3", "LMP2", "Hypercar"]),  # unlisted class last
    ("", ["Hypercar", "LMP2", "GT3"]),  # fastest first
])
def test_class_order_of_groups(ui_env, bundled_fonts, order, expected):
    widget, _ = items(enable_multi_class_split_mode=True, show_class_header=True, class_order=order)
    try:
        assert [row.text for row in widget.state if isinstance(row, ClassHeader)] == expected
    finally:
        widget.deleteLater()


def test_default_class_order():
    from tinypedal.template.setting_widget import WIDGET_DEFAULT

    assert WIDGET_DEFAULT["standings"]["class_order"] == "Hypercar, Hyper, LMP2 ELMS, LMP2, LMP3, GT3, LMGT3, GTE"
