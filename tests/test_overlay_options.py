"""Overlay Options page: sections of every overlay, editors by option kind, pending edits of many overlays, undo & redo,
search in one or every overlay, Modified filter, apply to every overlay, display order, Black box tools, apply (saved,
edited overlays restarted), preview, page in app & every entry opening it"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon

from neopedal import app_signal
from neopedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


class Host:
    """Page host: answers & records"""

    def __init__(self):
        self.answer = True
        self.questions: list[str] = []
        self.notices: list[str] = []
        self.applied_names: list[list[str]] = []
        self.color = "#123456"
        self.table: str | None = None

    def confirm(self, text):
        self.questions.append(text)
        return self.answer

    def pick_color(self, color):
        return self.color

    def pick_folder(self, folder):
        return ""

    def pick_image(self, filename):
        return ""

    def edit_table(self, text):
        return self.table

    def notify(self, text):
        self.notices.append(text)

    def applied(self, names):
        self.applied_names.append(names)


class Control:
    """Overlay control: every overlay, none running"""

    def __init__(self):
        from neopedal.template.setting_widget import WIDGET_DEFAULT

        self.names = list(WIDGET_DEFAULT)
        self.reloaded: list[str] = []

    def reload(self, name):
        self.reloaded.append(name)


@pytest.fixture
def options(ui_env):
    from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend

    host = Host()
    backend = OverlayOptionsBackend(None, host, Control())
    backend.host = host
    yield backend
    backend.close()
    backend.deleteLater()
    flush()


def rows(backend, row_type: str = "option") -> list[dict]:
    return [row for row in backend.rows.rows if row["row"] == row_type]


def row(backend, key: str) -> dict:
    return next(row for row in backend.rows.rows if row["key"] == key)


def order_list(backend) -> dict:
    """Display order list row (not a list option row, such as class order)"""
    return next(row for row in rows(backend, "order") if not row["option"])


def set_classic(name: str, classic: bool = True):
    if "enable_classic_layout" in cfg.user.setting[name]:
        cfg.user.setting[name]["enable_classic_layout"] = classic


# Sections
def test_sections_of_every_overlay_hold_every_shown_option_once(ui_env):
    from neopedal.template.setting_widget import WIDGET_DEFAULT
    from neopedal.ui.quick.overlay_options_backend import build_layout
    from neopedal.widget._modern import design_option_keys

    for classic in (False, True):
        for name in WIDGET_DEFAULT:
            set_classic(name, classic)
            layout = build_layout(name, cfg.user.setting[name])
            shown = design_option_keys(cfg, name, list(cfg.user.setting[name]))
            hidden = layout.option_ui.hidden if layout.option_ui is not None else ()  # held by page tools
            assert sorted(layout.keys) == sorted(key for key in shown if key not in hidden), name
            assert all(section.keys for section in layout.sections), name
            for key, control in layout.dependencies.items():  # options depend on an on/off option of the overlay
                assert isinstance(cfg.user.setting[name][control], bool), (name, key, control)


def test_item_sections_follow_their_on_off_option(ui_env):
    from neopedal.ui.quick.overlay_options_backend import build_layout
    from neopedal.ui.quick.overlay_sections import SECTION_FONT, SECTION_GENERAL, SECTION_LAYOUT, SECTION_ORDER

    set_classic("relative")
    layout = build_layout("relative", cfg.user.setting["relative"])
    keys = [section.key for section in layout.sections]
    assert keys[:3] == [SECTION_GENERAL, SECTION_LAYOUT, SECTION_FONT] and keys[-1] == SECTION_ORDER
    driver = layout.section_of["show_driver_name"]
    vehicle = layout.section_of["show_vehicle_name"]
    assert driver.toggle == "show_driver_name" and "font_color_driver_name" in driver.keys
    assert vehicle is not driver and "vehicle_name_uppercase" in vehicle.keys  # "name" alone is no item
    pit = layout.section_of["show_pit_status"]
    assert {"garage_status_text", "font_color_garage", "font_color_finish"} <= set(pit.keys)
    assert layout.dependencies["font_color_time_gap"] == "show_time_gap"
    set_classic("trailing")
    layout = build_layout("trailing", cfg.user.setting["trailing"])
    assert layout.section_of["show_raw_throttle"].toggle == "show_throttle"  # option of the throttle item


def test_modern_design_sections(ui_env):
    from neopedal.ui.quick.overlay_options_backend import build_layout
    from neopedal.ui.quick.overlay_sections import SECTION_SHOWN

    set_classic("standings")
    layout = build_layout("standings", cfg.user.setting["standings"])
    assert layout.section_of["show_time_gap"].toggle == "show_time_gap"  # classic: automatic sections
    set_classic("speedometer", False)
    layout = build_layout("speedometer", cfg.user.setting["speedometer"])
    shown = layout.section_of["show_speed"]
    assert shown.key == SECTION_SHOWN and "show_speed_maximum" in shown.keys  # on/off options alone: one card
    assert "font_size" in layout.section_of["position_x"].keys  # single font option with sizes


# Rows & editors
def test_rows_of_selected_overlay(options):
    set_classic("speedometer")
    options.refresh()
    options.selectOverlay("speedometer")
    headers = rows(options, "header")
    assert headers[0]["title"] == "General" and headers[0]["first"]
    speed = row(options, "speedometer#item:show_speed")
    assert speed["toggle"] == "speedometer/show_speed" and speed["toggleChecked"]
    assert "speedometer/show_speed" not in [entry["key"] for entry in rows(options)]  # header switch instead
    color = row(options, "speedometer/font_color_speed")
    assert color["kind"] == "color" and color["color"] == cfg.user.setting["speedometer"]["font_color_speed"]
    assert row(options, "speedometer/font_name")["kind"] == "font"
    interval = row(options, "speedometer/update_interval")
    assert interval["kind"] == "integer" and interval["minimum"] == 1
    order = order_list(options)
    assert next(entry["key"] for entry in order["orders"]) == "display_order_speed"
    assert rows(options)[-1]["last"] or rows(options, "order")[-1]["last"]


def test_off_item_dims_its_options(options):
    set_classic("speedometer")
    options.refresh()
    options.selectOverlay("speedometer")
    assert not row(options, "speedometer/font_color_speed_minimum")["dimmed"]
    options.setBool("speedometer/show_speed_minimum", False)
    dimmed = row(options, "speedometer/font_color_speed_minimum")
    assert dimmed["dimmed"] and dimmed["note"].endswith("Show Speed Minimum")
    assert not row(options, "speedometer#item:show_speed_minimum")["toggleChecked"]


def test_pending_edits_of_many_overlays_undo_redo_and_discard(options):
    options.selectOverlay("speedometer")
    options.setNumber("speedometer/update_interval", 50)
    options.selectOverlay("fuel")
    options.setText("fuel/update_interval", "abc")
    assert options.pendingCount == 2 and options.pendingOverlays == 2 and options.errorCount == 1
    assert row(options, "fuel/update_interval")["error"] == "Number required"
    nav = {entry["key"]: entry for entry in options.nav.rows}
    assert nav["speedometer"]["changed"] == 1 and nav["fuel"]["errors"] == 1
    options.undo()
    assert options.pendingCount == 1 and options.errorCount == 0
    options.redo()
    assert options.errorCount == 1
    options.discard()
    assert options.pendingCount == 0 and options.canUndo
    options.undo()
    assert options.pendingCount == 2


def test_apply_saves_preset_and_restarts_edited_overlays(options, ui_env):
    options.selectOverlay("speedometer")
    options.setNumber("speedometer/update_interval", 50)
    options.selectOverlay("fuel")
    options.setBool("fuel/show_caption", not cfg.user.setting["fuel"]["show_caption"])
    expected = cfg.user.setting["fuel"]["show_caption"]
    assert options.apply()
    assert cfg.user.setting["speedometer"]["update_interval"] == 50
    assert cfg.user.setting["fuel"]["show_caption"] != expected
    assert options.host.applied_names == [["speedometer", "fuel"]] and "setting" in ui_env
    assert options.pendingCount == 0 and not options.canUndo


def test_invalid_value_blocks_apply_and_shows_it(options):
    options.selectOverlay("fuel")
    options.setText("fuel/update_interval", "0")
    options.selectOverlay("speedometer")
    assert not options.apply()
    assert options.overlay == "fuel" and options.highlightKey == "fuel/update_interval"
    assert "Fuel" in options.firstError and not options.host.applied_names


def test_apply_after_another_preset_loaded_asks_first(options, monkeypatch):
    options.setNumber(f"{options.overlay}/update_interval", 77)
    monkeypatch.setattr(cfg.filename, "setting", "other.json")
    options.host.answer = False
    assert not options.apply() and options.pendingCount == 1
    assert "<b>other</b>" in options.host.questions[-1]


def test_design_switch_shows_options_of_new_design(options):
    set_classic("relative", False)
    options.refresh()
    options.selectOverlay("relative")
    keys = {entry["option"] for entry in rows(options)}
    assert "font_color_position" not in keys
    options.setBool("relative/enable_classic_layout", True)  # unsaved switch followed at once
    keys = {entry["option"] for entry in rows(options)}
    assert "font_color_position" in keys and options.overlayInfo["design"] == "Classic layout"
    options.undo()
    assert "font_color_position" not in {entry["option"] for entry in rows(options)}


def test_search_this_overlay_and_every_overlay(options):
    options.selectOverlay("speedometer")
    options.setSearch("opacity")
    assert [entry["key"] for entry in rows(options)] == ["speedometer/opacity"]
    options.setScopeAll(True)
    found = rows(options)
    opacity = [entry["overlay"] for entry in found if entry.get("option") == "opacity"]
    assert sorted(opacity) == sorted(options._names) and options.matchCount == len(found)
    assert row(options, "fuel#layout")["title"].startswith("Fuel")
    nav = {entry["key"]: entry for entry in options.nav.rows}
    assert nav["fuel"]["matches"] == 1
    options.selectOverlay("fuel")  # overlay chosen from results: its own options again
    assert not options.scopeAll and [entry["key"] for entry in rows(options)] == ["fuel/opacity"]


def test_search_every_overlay_is_capped(options):
    from neopedal.ui.quick.overlay_options_backend import MAX_ROWS

    for name in options._names:
        set_classic(name)  # every color option shown
    options.refresh()
    options.setScopeAll(True)
    options.setSearch("color")
    assert options.matchCount >= MAX_ROWS and options.truncatedCount > 0
    assert len(rows(options)) <= MAX_ROWS + 50  # stops at the section reaching the cap


def test_modified_filter(options):
    options.selectOverlay("speedometer")
    options.setModifiedOnly(True)
    assert rows(options) == []
    options.setModifiedOnly(False)
    options.setNumber("speedometer/opacity", 0.5)
    options.setModifiedOnly(True)
    assert [entry["key"] for entry in rows(options)] == ["speedometer/opacity"]
    options.setScopeAll(True)
    assert [entry["key"] for entry in rows(options)] == ["speedometer/opacity"]
    assert {entry["key"]: entry for entry in options.nav.rows}["speedometer"]["matches"] == 1


def test_apply_to_every_overlay_is_one_undo_step(options):
    options.selectOverlay("speedometer")
    options.setNumber("speedometer/opacity", 0.6)
    shared = row(options, "speedometer/opacity")["shared"]
    assert shared == len(options._names) - 1
    options.applyToAll("speedometer/opacity")
    assert all(options.value(name, "opacity") == 0.6 for name in options._names)
    assert options.pendingOverlays == len(options._names) and "set to" in options.host.notices[-1]
    options.undo()
    assert options.pendingCount == 1


def test_display_order_moves(options):
    set_classic("speedometer", False)
    options.refresh()
    options.selectOverlay("speedometer")
    first = [entry["key"] for entry in order_list(options)["orders"]]
    options.moveOrder("speedometer", first[0], 1)
    moved = [entry["key"] for entry in order_list(options)["orders"]]
    assert moved[:2] == [first[1], first[0]] and order_list(options)["changed"]
    assert [options.value("speedometer", key) for key in moved] == list(range(1, len(moved) + 1))
    options.placeOrder("speedometer", first[0], 0)
    assert options.pendingCount == 0  # back to saved order
    options.moveOrder("speedometer", first[0], -1)  # already first
    assert not options.canRedo and options.pendingCount == 0


def test_reset_option_section_and_overlay(options):
    options.selectOverlay("speedometer")
    cfg.user.setting["speedometer"]["opacity"] = 0.3
    cfg.user.setting["speedometer"]["font_size"] = 30
    cfg.user.setting["speedometer"]["enable"] = True
    options.refresh()
    options.resetOption("speedometer/opacity")
    assert options.value("speedometer", "opacity") == cfg.default.setting["speedometer"]["opacity"]
    options.undo()
    options.host.answer = False
    options.resetSection("speedometer#layout")
    assert options.pendingCount == 0 and options.host.questions
    options.host.answer = True
    options.resetOverlay()
    assert options.value("speedometer", "font_size") == cfg.default.setting["speedometer"]["font_size"]
    assert options.value("speedometer", "enable") is True  # kept


def test_collapse_sections(options):
    options.selectOverlay("speedometer")
    options.toggleSection("speedometer#general")
    header = row(options, "speedometer#general")
    assert header["collapsed"] and header["last"]
    assert "speedometer/update_interval" not in [entry["key"] for entry in rows(options)]
    options.setAllCollapsed(False)
    assert not row(options, "speedometer#general")["collapsed"]
    options.setAllCollapsed(True)
    assert rows(options) == []


def test_focus_option_expands_section_and_flashes(options):
    options.selectOverlay("fuel")
    options.toggleSection("speedometer#layout")
    options.focus_option("speedometer", "opacity")
    assert options.overlay == "speedometer" and options.highlightKey == "speedometer/opacity"
    assert options.rowIndex("speedometer/opacity") >= 0


def test_black_box_tools(options):
    options.selectOverlay("black_box")
    info = options.overlayInfo
    assert info["simpleMode"] and next(theme["name"] for theme in info["themes"]) == "Default"
    simple = {entry["option"] for entry in rows(options)}
    options.setAdvanced(True)
    assert len(rows(options)) > len(simple) and "Size & Layout" in [entry["title"] for entry in rows(options, "header")]
    options.setChoice("black_box/display_profile", row(options, "black_box/display_profile")["choices"].index("Minimal"))
    profiled = [entry for entry in rows(options) if entry["note"].startswith("Set by")]
    assert profiled and not any(entry["locked"] for entry in profiled)  # editable: profile switched to Custom
    options.applyColorTheme("Colorblind Safe")
    assert options.value("black_box", "wheel_lock_color") != cfg.default.setting["black_box"]["wheel_lock_color"]


def test_black_box_option_set_by_profile_switches_to_custom(options):
    from neopedal.template.widget.black_box_ui import DISPLAY_PROFILES

    options.selectOverlay("black_box")
    options.setAdvanced(True)
    options.setBool("black_box/show_fuel_gauge", True)
    options.setChoice("black_box/display_profile", row(options, "black_box/display_profile")["choices"].index("Sprint"))
    fuel = row(options, "black_box/show_fuel_gauge")
    assert not fuel["checked"] and not fuel["locked"] and "Sprint" in fuel["note"]  # profile value shown
    options.setBool("black_box/show_fuel_gauge", not fuel["checked"])  # one click, one undo step
    assert options.value("black_box", "display_profile") == "Custom"
    assert options.value("black_box", "show_fuel_gauge") is True
    for key, value in DISPLAY_PROFILES["Sprint"].items():  # other profile values kept
        if key != "show_fuel_gauge":
            assert options.value("black_box", key) == value, key
    assert not row(options, "black_box/show_fuel_gauge")["note"]
    options.undo()
    assert options.value("black_box", "display_profile") == "Sprint"
    # Hidden by auto compact mode: stays locked (profile change cannot show it)
    options.setNumber("black_box/display_scale", 0.6)
    options.setNumber("black_box/auto_compact_display_scale", 0.8)
    compound = row(options, "black_box/show_tyre_compound")
    assert compound["locked"] and "Changing" not in compound["note"]
    options.setBool("black_box/show_tyre_compound", True)  # not reachable from page: profile left as is
    assert options.value("black_box", "display_profile") == "Sprint"


def test_header_names_display_profile(options):
    options.selectOverlay("black_box")
    assert options.overlayInfo["profile"] == ""  # default profile (Custom): nothing to tell
    options.setChoice("black_box/display_profile", row(options, "black_box/display_profile")["choices"].index("Sprint"))
    info = options.overlayInfo
    assert info["profile"].endswith(": Sprint") and info["profileOption"] == "black_box/display_profile"
    options.setAllCollapsed(True)
    options.showOption(info["profileOption"])
    assert options.highlightKey == "black_box/display_profile" and options.rowIndex("black_box/display_profile") >= 0
    options.selectOverlay("speedometer")
    assert options.overlayInfo["profile"] == ""  # overlay without profile


def test_black_box_sections_order_list_and_dependency_chain(options):
    from neopedal.ui.quick.overlay_options_backend import build_layout
    from neopedal.ui.quick.overlay_sections import SECTION_GENERAL, SECTION_ORDER

    layout = build_layout("black_box", cfg.user.setting["black_box"])
    assert layout.sections[0].key == SECTION_GENERAL and "visibility_context" in layout.sections[0].keys
    order = layout.sections[-1]
    assert order.key == SECTION_ORDER and order.title == "Center Column Order"
    assert all(key.startswith("display_order_") for key in order.keys)
    options.selectOverlay("black_box")
    options.setAdvanced(True)
    assert rows(options, "order") and rows(options, "header")[-1]["title"] == "Center Column Order"
    options.setBool("black_box/show_tyre_pressure", True)
    options.setBool("black_box/enable_tyre_pressure_target", True)
    assert not row(options, "black_box/tyre_pressure_target_minimum")["dimmed"]
    options.setBool("black_box/show_tyre_pressure", False)  # grand parent off: whole chain dimmed
    minimum = row(options, "black_box/tyre_pressure_target_minimum")
    assert minimum["dimmed"] and minimum["note"].endswith("Show Tyre Pressure")


def test_listed_sections():
    from neopedal.template.widget.black_box_ui import ORDER_LIST
    from neopedal.ui.quick.overlay_sections import SECTION_OPTIONS, SECTION_ORDER, listed_sections, order_keys

    keys = ["enable", "font_size", "show_a", "column_a", "column_b", "display_order_a", "display_order_b", "other"]
    layout = (("Size", ("font_size", "missing")), ("Items", (ORDER_LIST,)), ("A", ("show_a",)))
    sections = listed_sections(keys, layout, "Items", ("column_a", "column_b"))
    assert [(section.key, section.title) for section in sections] == [
        ("general", "General"), ("declared:font_size", "Size"), (SECTION_ORDER, "Items"), ("declared:show_a", "A"),
        (SECTION_OPTIONS, "Options")]  # options listed nowhere last
    assert sections[2].keys == ("display_order_a", "display_order_b", "column_a", "column_b")
    assert order_keys(sections[2]) == ("display_order_a", "display_order_b")
    sections = listed_sections(keys, (("A", ("show_a",)),))  # no place given: list last, own title
    assert sections[-1].key == SECTION_ORDER and sections[-1].title == "Display Order"
    assert "column_a" in sections[-2].keys  # not switched in the list: option row


def test_driver_list_sections_and_column_list(options):
    """Modern relative, standings & rivals: sections in page order, columns switched & moved in one list,
    listed as the overlay shows them"""
    from neopedal.template.widget.drivers_ui import RELATIVE_COLUMNS, STANDINGS_COLUMNS, order_option
    from neopedal.ui.quick.overlay_options_backend import build_layout
    from neopedal.ui.quick.overlay_sections import SECTION_ORDER

    set_classic("standings", False)
    layout = build_layout("standings", cfg.user.setting["standings"])
    titles = [section.title for section in layout.sections]
    assert titles[:5] == ["General", "Position & Layout", "Rows", "Classes & Number of Cars", "Columns"]
    assert titles[5:7] == ["Position Change", "Driver Name"] and "Options" not in titles
    columns = layout.section_of["column_time_gap"]
    assert columns.key == SECTION_ORDER and "display_order_time_gap" in columns.keys
    assert layout.dependencies["brand_logo_width"] == "column_brand_logo"
    assert layout.dependencies["maximum_vehicles_exclusive_mode"] == "enable_single_class_exclusive_mode"
    relative = build_layout("relative", cfg.user.setting["relative"])
    assert "additional_players_front" in relative.section_of["show_vehicle_in_garage"].keys
    options.selectOverlay("standings")
    assert not options.overlayInfo["simpleMode"]
    order = order_list(options)
    keys = [item["key"] for item in order["orders"]]
    assert keys == [order_option(column) for column in STANDINGS_COLUMNS]  # design order, not option values
    assert order["help"].startswith("Columns from left to right")
    logo = next(item for item in order["orders"] if item["key"] == "display_order_brand_logo")
    assert logo["label"] == "Brand Logo" and logo["toggle"] == "standings/column_brand_logo" and logo["checked"]
    options.setBool(logo["toggle"], False)
    logo = next(item for item in order_list(options)["orders"] if item["key"] == "display_order_brand_logo")
    assert not logo["checked"] and logo["changed"]
    assert row(options, "standings/brand_logo_width")["dimmed"]
    # Moving one column keeps the others where the overlay shows them
    options.moveOrder("standings", keys[3], -1)
    moved = [item["key"] for item in order_list(options)["orders"]]
    assert moved == [*keys[:2], keys[3], keys[2], *keys[4:]]
    assert [options.value("standings", key) for key in moved] == list(range(1, len(moved) + 1))
    options.resetOrder("standings")
    assert [item["key"] for item in order_list(options)["orders"]] == keys
    assert options.value("standings", "column_brand_logo") is False  # columns shown left as set
    options.selectOverlay("relative")
    assert len(order_list(options)["orders"]) == len(RELATIVE_COLUMNS)
    set_classic("standings")
    assert build_layout("standings", cfg.user.setting["standings"]).option_ui is None


def test_class_order_edited_as_order_list(options):
    """Class order (text option) shown as an order list: classes of option then known classes, moved & reset"""
    from neopedal.template.setting_widget import WIDGET_DEFAULT

    cfg.user.classes = {"Hypercar": {}, "LMP2": {}, "GT3": {}, "Formula Pro": {}}
    options.selectOverlay("standings")
    lists = [item for item in rows(options, "order") if item["option"] == "class_order"]
    assert len(lists) == 1 and lists[0]["key"] == "standings/class_order"
    names = [item["label"] for item in lists[0]["orders"]]
    assert names[:8] == ["Hypercar", "Hyper", "LMP2 ELMS", "LMP2", "LMP3", "GT3", "LMGT3", "GTE"]
    assert names[8:] == ["Formula Pro"]  # known class not listed: offered last (LMP2, GT3 already listed)
    assert not lists[0]["modified"] and lists[0]["help"]
    options.moveListItem("standings", "class_order", "GT3", -5)
    assert options.value("standings", "class_order").startswith("GT3, Hypercar, Hyper, LMP2 ELMS")
    moved = row(options, "standings/class_order")
    assert moved["orders"][0]["label"] == "GT3" and moved["orders"][0]["changed"] and moved["modified"]
    options.placeListItem("standings", "class_order", "Formula Pro", 1)
    assert options.value("standings", "class_order").startswith("GT3, Formula Pro, Hypercar")
    options.moveListItem("standings", "class_order", "Unknown", 1)  # not in list: nothing
    options.resetList("standings", "class_order")
    assert options.value("standings", "class_order") == WIDGET_DEFAULT["standings"]["class_order"]
    assert order_list(options)["orders"][0]["key"] == "display_order_position"  # columns list still there


def test_driver_list_preview_shows_sample_race(ui_env, bundled_fonts):
    from neopedal.ui.widget_preview import render_widget
    from neopedal.widget._modern.sample_field import FIELD, PLAYER, sample_field, sample_standings

    field = sample_field()
    setting = dict(cfg.user.setting["standings"])
    assert setting["enable_multi_class_split_mode"]
    split = sample_standings(field, setting)
    assert split.count(-1) == 3 and PLAYER in split  # three classes, space after each
    setting["enable_multi_class_split_mode"] = False
    combined = sample_standings(field, setting)
    assert combined[-1] == -1 and -1 not in combined[:-1] and PLAYER in combined
    setting["enable_single_class_exclusive_mode"] = True
    exclusive = sample_standings(field, setting)
    assert {FIELD[index][3] for index in exclusive if index >= 0} == {FIELD[PLAYER][3]}
    heights = {}
    for name in ("standings", "relative", "rivals"):
        set_classic(name, False)
        heights[name] = render_widget(cfg, name, dict(cfg.user.setting[name])).height()
    assert heights["standings"] > heights["relative"] > heights["rivals"] > 0
    setting = dict(cfg.user.setting["standings"], maximum_vehicles_per_split_player=3)
    assert render_widget(cfg, "standings", setting).height() < heights["standings"]  # options shown live


def test_unit_hint_in_display_unit(options):
    cfg.units["tyre_pressure_unit"] = "psi"
    try:
        options.selectOverlay("black_box")
        options.setAdvanced(True)
        assert row(options, "black_box/tyre_pressure_target_minimum")["hint"] == "= 23.21 psi"  # 160 kPa stored
        options.setNumber("black_box/tyre_pressure_target_minimum", 200)
        assert row(options, "black_box/tyre_pressure_target_minimum")["hint"] == "= 29.01 psi"
        assert row(options, "black_box/tyre_wear_warning_threshold")["hint"] == ""  # a percentage, no unit
    finally:
        cfg.units["tyre_pressure_unit"] = "kPa"


def test_search_every_overlay_shows_description_once(options):
    options.setScopeAll(True)
    options.setSearch("opacity")
    helps = [entry["help"] for entry in rows(options) if entry.get("option") == "opacity"]  # not reference_line_opacity
    assert helps[0] and not any(helps[1:])


def test_compound_table_editor(options):
    options.selectOverlay("black_box")
    options.setAdvanced(True)
    entry = row(options, "black_box/tyre_target_by_compound")
    assert entry["table"]
    options.host.table = "S=160-190"
    options.editTable("black_box/tyre_target_by_compound")
    assert options.value("black_box", "tyre_target_by_compound") == "S=160-190"


def test_preview_renders_unsaved_values(options):
    options.selectOverlay("speedometer")
    options.set_active(True)
    options.render_preview()
    assert options.previewState == 2 and options.previewUrl.startswith("image://overlaypreview/") and options.previewWidth > 0
    options.setText("speedometer/font_color_speed", "bad")
    options.render_preview()
    assert options.previewState == 4  # kept, marked invalid
    options.setPreviewEnabled(False)
    assert options.previewState == 0 and options.previewUrl == ""


def test_preview_drawn_again_only_when_inputs_change(options, monkeypatch):
    """Page shown again, refreshed, edit undone: picture kept; zoomed picture released while hidden"""
    from neopedal.ui.quick import overlay_options_backend
    from neopedal.ui.quick.preview_provider import STORE, key_of

    drawn = []
    real = overlay_options_backend.render_overlay
    monkeypatch.setattr(overlay_options_backend, "render_overlay",
                        lambda name, values, zoom=1.0, scenario="": drawn.append(zoom) or real(name, values, zoom, scenario))
    options.selectOverlay("speedometer")
    options.set_active(True)
    options.render_preview()
    url = options.previewUrl
    options.set_active(False)
    options.refresh()  # page shown again: saved values read again
    options.set_active(True)
    options.render_preview()
    assert drawn == [1.0] and options.previewUrl == url
    options.setNumber("speedometer/font_size", cfg.user.setting["speedometer"]["font_size"] + 3)
    options.render_preview()
    options.undo()
    options.render_preview()
    assert drawn == [1.0, 1.0, 1.0] and options.previewState == 2
    monkeypatch.setattr(overlay_options_backend, "KEEP_HIDDEN_BYTES", 0)
    options.setPreviewScale(2.0)
    options.render_preview()
    zoomed = options.previewUrl
    assert drawn[-1] == 2.0 and STORE.get(key_of(zoomed.removeprefix("image://overlaypreview/"))) is not None
    options.set_active(False)  # hidden: zoomed picture released
    assert options.previewUrl == "" and STORE.get(key_of(zoomed.removeprefix("image://overlaypreview/"))) is None
    options.set_active(True)
    options.render_preview()
    assert options.previewState == 2 and options.previewUrl and options.previewScale == 2


def test_refresh_drops_edits_saved_elsewhere(options):
    options.selectOverlay("speedometer")
    options.setNumber("speedometer/position_x", 321)
    cfg.user.setting["speedometer"]["position_x"] = 321  # overlay moved to same place
    options.refresh()
    assert options.pendingCount == 0


def test_nav_filter_and_active_only(options):
    options.setNavFilter("speed")
    names = [entry["key"] for entry in options.nav.rows]
    assert "speedometer" in names and "fuel" not in names
    options.setNavFilter("")
    cfg.user.setting["fuel"]["enable"] = True
    options.setActiveOnly(True)
    names = [entry["key"] for entry in options.nav.rows]
    assert "fuel" in names and all(cfg.user.setting[name]["enable"] or name == options.overlay for name in names)


def test_customized_counts_warm_in_background(options):
    cfg.user.setting["fuel"]["opacity"] = 0.42
    options.refresh()
    while options._warm_queue:
        options._warm_next()
    nav = {entry["key"]: entry for entry in options.nav.rows}
    assert nav["fuel"]["customized"] == 1 and nav["speedometer"]["customized"] == 0


# Page in app
@pytest.fixture
def window(ui_env, monkeypatch):
    from neopedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            backend = getattr(page.dialog, "backend", None)
            if backend is not None and hasattr(backend, "discard"):
                if hasattr(page.dialog, "commit_edits"):
                    page.dialog.commit_edits()  # as Discard button: field being edited left first
                backend.discard()  # closed without question
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    flush()


def option_pages(window):
    from neopedal.ui.overlay_options import OverlayOptions

    return [page for page in window.centralWidget().dialog_pages() if isinstance(page.dialog, OverlayOptions)]


def test_one_page_for_every_overlay(window):
    from neopedal.ui.overlay_options import open_overlay_options

    first = open_overlay_options(window, "speedometer")
    assert first is not None and first.backend.overlay == "speedometer"
    assert not first.view.errors(), [error.toString() for error in first.view.errors()]
    second = open_overlay_options(window, "fuel", "opacity")
    flush()
    assert second is first and first.backend.overlay == "fuel" and len(option_pages(window)) == 1
    assert option_pages(window)[0].title == "Overlay Options"


def test_open_page_shown_without_building_another(window, monkeypatch):
    """Page open: shown & overlay selected, no second page built (QML view, every option read) to find it"""
    from neopedal.ui import overlay_options
    from neopedal.ui.overlay_options import OverlayOptions, open_overlay_options

    first = open_overlay_options(window, "speedometer")
    assert first is not None
    built = []
    original = OverlayOptions.__init__

    def counting(self, *args, **kwargs):
        built.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(OverlayOptions, "__init__", counting)
    flashed = []
    monkeypatch.setattr(first.backend, "focus_option", lambda name, key: flashed.append((name, key)))
    again = open_overlay_options(window, "fuel", "opacity")
    assert again is first and not built and flashed == [("fuel", "opacity")]
    assert window.centralWidget()._pages.currentWidget().dialog is first
    first.close()
    flush()
    assert isinstance(overlay_options.open_overlay_options(window, "fuel"), OverlayOptions) and len(built) == 1


def test_page_unsaved_marker_ctrl_s_and_close(window, monkeypatch):
    from neopedal.ui import overlay_options
    from neopedal.ui.overlay_options import open_overlay_options

    restarts = []
    monkeypatch.setattr(overlay_options, "run_after_saving", lambda callback: restarts.append(callback))
    page = open_overlay_options(window, "speedometer")
    page.backend.setNumber("speedometer/opacity", 0.5)
    assert page.is_marked_modified() and option_pages(window)[0].is_modified()
    assert window.centralWidget().save_current_page()  # Ctrl+S
    assert cfg.user.setting["speedometer"]["opacity"] == 0.5 and restarts and not page.is_marked_modified()
    page.backend.setNumber("speedometer/opacity", 0.7)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Cancel))
    page.close()
    assert option_pages(window)  # cancelled: kept
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard))
    page.close()
    flush()
    assert not option_pages(window) and cfg.user.setting["speedometer"]["opacity"] == 0.5


@pytest.mark.filterwarnings("ignore:libpyside. Failed to disconnect:RuntimeWarning")  # closed twice
def test_page_closed_again_while_asking_to_save(window, monkeypatch):
    """Close event delivered again during save question (nested event loop): no error"""
    from PySide6.QtGui import QCloseEvent

    from neopedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "speedometer")
    page.backend.setNumber("speedometer/opacity", 0.7)
    nested = []

    def question(*args, **kwargs):
        if not nested:
            nested.append(True)
            page.closeEvent(QCloseEvent())  # second close while first one asks
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    event = QCloseEvent()
    page.closeEvent(event)
    assert nested and event.isAccepted() and page.view is None
    page.close()
    flush()
    assert not option_pages(window)


def test_page_kept_open_when_preset_loads_unless_edited(window):
    from neopedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "speedometer")
    assert page not in window.config_dialogs(preset_only=True)  # refreshed, not closed by preset loading
    page.backend.setNumber("speedometer/opacity", 0.5)
    assert page in window.modified_config_dialogs(preset_only=True)  # loading asks to save first


def test_page_rebuilt_in_new_language(window):
    from neopedal import i18n
    from neopedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "speedometer")
    page.backend.setNumber("speedometer/opacity", 0.5)
    i18n.set_language("Français")
    try:
        page.refresh()
        assert option_pages(window)[0].title == "Options des overlays" and not page.view.errors()
        assert page.backend.pendingCount == 1 and page.backend.overlayInfo["label"] == "Compteur de vitesse"
        assert page.view.rootContext().contextProperty("i18n").property("table")["Find overlay"] == "Trouver un overlay"  # QML texts too
    finally:
        i18n.set_language("English")
        page.refresh_now()
        page.backend.discard()


def test_overlay_entries_open_the_page(window, monkeypatch):
    from neopedal.ui.overlay_options import OverlayOptions
    from neopedal.ui.overlay_view import OverlayView
    from neopedal.widget._base import config_widget

    overlays = OverlayView(window)
    overlays.open_config("fuel")
    page = option_pages(window)[0].dialog
    assert isinstance(page, OverlayOptions) and page.backend.overlay == "fuel"
    config_widget("speedometer")  # overlay right click menu
    assert page.backend.overlay == "speedometer" and len(option_pages(window)) == 1
    from neopedal.module_control import wctrl
    from neopedal.ui.command_palette import module_commands

    configure = next(command for command in module_commands(wctrl, "Overlays", window)
                     if command.title.startswith("Relative") and "⚙" in command.title)
    configure.run()
    assert page.backend.overlay == "relative"
    overlays.deleteLater()


PAGE_QML = ("OverlayOptions", "OverlayOptionRow")


def test_page_qml_bundled_modules_and_translated():
    """Release build bundles only QML_MODULES; every text of the page has a French translation"""
    import re

    from neopedal.i18n.fr import TRANSLATION
    from neopedal.ui.quick import qml_path
    from neopedal.ui.quick.overlay_sections import FIXED_TITLES
    from neopedal.ui.quick.qml_modules import QML_MODULES

    pattern = re.compile(r'i18n\.tr\("((?:[^"\\]|\\.)*)"\)')
    missing = []
    for name in PAGE_QML:
        with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
            text = file.read()
        modules = re.findall(r"^import ([A-Za-z.]+)", text, flags=re.MULTILINE)
        assert modules and all(module.replace(".", "/") in QML_MODULES for module in modules), (name, modules)
        missing += [found for found in pattern.findall(text) if found not in TRANSLATION]
    missing += [title for title in FIXED_TITLES.values() if title not in TRANSLATION]
    assert not missing


def test_backend_texts_translated(options):
    from neopedal import i18n

    set_classic("speedometer")
    options.refresh()
    i18n.set_language("Français")
    try:
        options.selectOverlay("speedometer")
        options.setBool("speedometer/show_speed_minimum", False)
        assert row(options, "speedometer#general")["title"] == "Général"
        assert row(options, "speedometer/font_color_speed_minimum")["note"].startswith("Utilisé")
        options.selectOverlay("relative")
        assert options.overlayInfo["design"] in ("Design moderne", "Disposition classique")
        options.applyToAll("relative/opacity")
        assert "overlay" in options.host.notices[-1] and "set to" not in options.host.notices[-1]
    finally:
        i18n.set_language("English")


def test_decimal_typed_in_whole_number_field(window):
    """Decimal number typed in field of a whole value (shown without decimals): taken (was: dropped when
    rounded to the shown value, 5 -> 4.6 kept 5)"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from neopedal.i18n.options import option_label
    from neopedal.ui.overlay_options import open_overlay_options

    key = "speed_minimum_reset_cooldown"
    assert cfg.user.setting["speedometer"][key] == 5
    page = open_overlay_options(window, "speedometer", key)
    page.view.setFocus()
    QTest.qWait(150)
    flush()
    label = option_label(key)
    stack, field = [page.view.rootObject()], None
    while stack and field is None:
        item = stack.pop()
        if "NumberField" in item.metaObject().className() and item.property("tip") == label:
            field = item
        stack.extend(item.childItems())
    assert field is not None
    field.forceActiveFocus()
    QTest.keyClicks(page.view, "4.6")  # focused field selects its text: replaced
    QTest.keyClick(page.view, Qt.Key.Key_Return)
    flush()
    assert page.backend.value("speedometer", key) == 4.6


def test_black_box_user_profile_saved_and_selected(options):
    from neopedal.template.widget.black_box_ui import display_overrides, parse_user_profile

    options.selectOverlay("black_box")
    assert [entry["name"] for entry in options.overlayInfo["userProfiles"]] == ["User 1", "User 2", "User 3"]
    assert options.rowIndex("black_box/user_profile_1") < 0  # held by profile tool, no row
    options.setBool("black_box/show_rpm", False)
    options.setBool("black_box/show_damage_panel", True)
    options.saveUserProfile("User 2")
    assert options.value("black_box", "display_profile") == "User 2"
    saved = parse_user_profile(options.value("black_box", "user_profile_2"))
    assert saved["show_rpm"] is False and saved["show_damage_panel"] is True
    options.setBool("black_box/show_rpm", True)  # profile option edited: back to Custom, profile values kept
    assert options.value("black_box", "display_profile") == "Custom"
    assert options.value("black_box", "show_damage_panel") is True and options.value("black_box", "show_rpm") is True
    values = {**options.values("black_box"), "display_profile": "User 2"}
    assert display_overrides(values)["show_rpm"] is False  # widget follows the saved profile
    assert display_overrides({**values, "display_profile": "User 3"}) == {}  # not saved: like Custom
    options.saveUserProfile("Nope")  # unknown profile: nothing
    assert options.value("black_box", "display_profile") == "Custom"


def test_black_box_simple_mode_main_switches_only(options):
    options.selectOverlay("black_box")
    simple = {entry["option"] for entry in rows(options)}
    assert {"show_tyre_pressure", "show_setting_change_popup", "display_profile", "layout"} <= simple
    assert not {"show_tyre_temperature_trend", "show_flag_events", "enable_shift_flash"} & simple
    options.setAdvanced(True)
    advanced = {entry["option"] for entry in rows(options)}
    assert "show_tyre_temperature_trend" in advanced and len(advanced) > len(simple) * 3
    options.setAdvanced(False)
    options.setSearch("trend")  # search finds every option, simple mode or not
    assert any(entry["option"] == "show_tyre_temperature_trend" for entry in rows(options))


def test_black_box_preview_click_shows_part_options(options):
    from neopedal.ui.widget_preview import widget_part_rects

    options.selectOverlay("black_box")
    assert options.overlayInfo["previewParts"]
    size, rects = widget_part_rects(cfg, "black_box", options.values("black_box"))
    for part, key in (("wheel0", "show_tyre_temperature"), ("leds", "show_rpm_leds"),
                      ("center", "center_column_alignment")):
        middle = rects[part].center()
        options.previewClicked(middle.x() / size.width(), middle.y() / size.height())
        assert options.highlightKey == f"black_box/{key}", part
    assert options.preview_part_option(1.5, 0.5) == ""  # outside the picture
    options.selectOverlay("speedometer")
    assert not options.overlayInfo["previewParts"] and options.preview_part_option(0.5, 0.5) == ""


def test_heatmap_choices_read_again_once_shown(options):
    """Heatmap added in heatmap editor while page open: offered once page shown again"""
    from neopedal.ui.quick.option_kinds import choice_values

    assert "my heatmap" not in choice_values(options.kind("heatmap_name"))
    cfg.user.heatmap["my heatmap"] = dict(next(iter(cfg.user.heatmap.values())))
    options.set_active(False)
    options.set_active(True)
    assert "my heatmap" in choice_values(options.kind("heatmap_name"))
    options.set_active(False)


def test_close_asks_to_save_value_typed_without_enter(window, monkeypatch):
    """Value typed, field still focused (app quit, close all): committed first, so asked to save"""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from neopedal.i18n.options import option_label
    from neopedal.ui.overlay_options import open_overlay_options

    key = "speed_minimum_reset_cooldown"
    page = open_overlay_options(window, "speedometer", key)
    page.view.setFocus()
    QTest.qWait(150)
    flush()
    stack, field = [page.view.rootObject()], None
    while stack and field is None:
        item = stack.pop()
        if "NumberField" in item.metaObject().className() and item.property("tip") == option_label(key):
            field = item
        stack.extend(item.childItems())
    assert field is not None
    field.forceActiveFocus()
    QTest.keyClicks(page.view, "7")  # no Enter
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: asked.append(True)
                        or QMessageBox.StandardButton.Save)
    page.close()
    flush()
    assert asked and cfg.user.setting["speedometer"][key] == 7


# --- Driver lists: column order of the page is the order of the overlay, unused options told
def driver_columns(name):
    from importlib import import_module

    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
    keys = [column.key for column in widget.table.columns]
    class_headers = widget.class_column_hidden  # class column left out for class headers
    widget.deleteLater()
    return keys, class_headers


def shown_columns(backend, name, class_headers):
    from neopedal.template.widget.drivers_ui import COLUMN_TITLES, order_option

    column_of = {order_option(column): column for column in COLUMN_TITLES}
    row = backend._order_row(name, backend._order_section(name))
    return [column_of[entry["key"]] for entry in row["orders"]
            if entry["checked"] and not (class_headers and column_of[entry["key"]] == "class")]


@pytest.mark.parametrize("name", ["standings", "relative", "rivals"])
def test_driver_list_columns_in_page_order(options, name):
    """Moved, dragged, switched & reset columns shown by the overlay in the order of the page (was: same
    display order values of the other design shifted moved columns after later ones)"""
    import random

    rng = random.Random(name)
    set_classic(name, False)
    options.refresh()
    options.selectOverlay(name)
    options.moveOrder(name, "display_order_position_change", 1)  # first move (was: wrong order already)
    assert options.apply()
    widget_keys, class_headers = driver_columns(name)
    assert widget_keys == shown_columns(options, name, class_headers)
    for _ in range(60):
        row = options._order_row(name, options._order_section(name))
        entry = rng.choice(row["orders"])
        action = rng.choice(("move", "place", "toggle", "toggle", "reset"))
        if action == "move":
            options.moveOrder(name, entry["key"], rng.choice((-1, 1)))
        elif action == "place":
            options.placeOrder(name, entry["key"], rng.randrange(len(row["orders"])))
        elif action == "toggle":
            options.setBool(entry["toggle"], not entry["checked"])
        else:
            options.resetOrder(name)
        assert options.apply()
        widget_keys, class_headers = driver_columns(name)
        assert widget_keys == shown_columns(options, name, class_headers), action


def test_display_order_made_unique_without_moving_items():
    from neopedal.widget._base import validate_option

    config = {"display_order_a": 1, "display_order_hidden": 4, "display_order_late": 5, "display_order_b": 2,
              "display_order_c": 4, "other": 4}
    validate_option(config)
    order = sorted((value, key) for key, value in config.items() if key.startswith("display_order_"))
    assert [key for _, key in order] == ["display_order_a", "display_order_b", "display_order_hidden",
                                         "display_order_c", "display_order_late"]  # c (4) still before late (5)
    assert len({value for value, _ in order}) == 5 and config["other"] == 4
    unique = {"display_order_a": 3, "display_order_b": 1}
    assert validate_option(dict(unique)) == unique  # nothing changed when already unique


def test_standings_options_unused_in_class_mode_told(options):
    options.selectOverlay("standings")
    set_classic("standings", False)
    options.setBool("standings/enable_single_class_exclusive_mode", True)
    options.setBool("standings/enable_multi_class_split_mode", True)
    split_cars = row(options, "standings/maximum_vehicles_per_split_player")
    assert split_cars["dimmed"] and "exclusive" in split_cars["note"].lower()
    class_order = row(options, "standings/class_order")
    assert class_order["dimmed"]
    options.setBool("standings/enable_single_class_exclusive_mode", False)
    assert row(options, "standings/maximum_vehicles_combined_mode")["dimmed"]
    assert not row(options, "standings/maximum_vehicles_per_split_player")["dimmed"]
    options.setBool("standings/show_class_header", True)
    columns = options._order_row("standings", options._order_section("standings"))["orders"]
    class_item = next(entry for entry in columns if entry["key"] == "display_order_class")
    assert class_item["note"]  # class column replaced by class headers
    options.setBool("standings/enable_multi_class_split_mode", False)
    assert row(options, "standings/show_class_header")["dimmed"]
    columns = options._order_row("standings", options._order_section("standings"))["orders"]
    assert not next(entry for entry in columns if entry["key"] == "display_order_class")["note"]
    options.discard()


# --- Options of every overlay: dimmed only while they do nothing (checked against overlay code)
def layout_of(name, modern, **options):
    from neopedal.ui.quick.overlay_options_backend import build_layout

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    return build_layout(name, dict(cfg.user.setting[name], enable_classic_layout=not modern, **options))


def test_gear_bars_led_by_bar_switch_not_inverted_switch(ui_env):
    """Classic gear: bar options were dimmed while the bar is shown (led by "inverted", off by default)"""
    layout = layout_of("gear", False)
    battery = layout.section_of["battery_bar_height"]
    assert battery.toggle == "show_battery_bar" and "show_inverted_battery" in battery.keys
    assert layout.section_of["rpm_bar_height"].toggle == "show_rpm_bar"
    assert layout.dependencies["decimal_places_battery"] == "show_battery_reading"
    assert "show_battery_bar" not in layout.section_of["show_consumption_bar"].keys  # out of Shown Items


@pytest.mark.parametrize("modern", [True, False])
def test_option_dependencies_follow_overlay_code(ui_env, modern):
    pedal = layout_of("pedal", modern)
    assert pedal.dependencies.get("wheel_slip_threshold") == "show_wheel_slip_flash"
    assert pedal.dependencies.get("show_abs_activation_flash", "") == ""
    rpm_led = layout_of("rpm_led", modern)
    assert not rpm_led.dependencies.get("rpm_multiplier_safe")  # LED zones, flickering or not
    push = layout_of("push_to_pass", modern)
    assert push.dependencies["activation_threshold_gear"] == "show_battery_charge"
    fuel = layout_of("fuel", modern)
    assert not fuel.dependencies.get("low_fuel_lap_threshold")  # low amount color, flashing or not
    assert fuel.dependencies["show_refueling_level_mark"] == "show_fuel_level_bar"
    notes = layout_of("track_notes", modern)
    assert not notes.dependencies.get("pit_notes_text")
    track_map = layout_of("track_map", modern)
    assert track_map.dependencies["auto_prediction_additional_pitstop_time"] == "enable_auto_pitout_prediction"
    black_box = layout_of("black_box", modern)
    assert black_box.dependencies["tyre_pressure_low_color"] == "enable_tyre_pressure_target"
    assert black_box.dependencies["enable_shift_flash"] == "enable_gear_rpm_color"
    assert "text_track_limits" not in black_box.dependencies  # also label of track limits points


def test_options_unused_with_other_values_told(options):
    set_classic("relative_finish_order", False)
    options.selectOverlay("relative_finish_order")
    options.setNumber("relative_finish_order/number_of_prediction", 2)
    assert row(options, "relative_finish_order/prediction_3_leader_pit_time")["dimmed"]
    assert not row(options, "relative_finish_order/prediction_2_leader_pit_time")["dimmed"]
    options.selectOverlay("radar")
    options.setBool("radar/enable_auto_hide", True)
    options.setBool("radar/enable_radar_fade", True)
    assert "fade" in row(options, "radar/auto_hide_time_threshold")["note"].lower()
    set_classic("speedometer")  # font options of classic design
    options.refresh()
    options.selectOverlay("speedometer")
    options.setBool("speedometer/enable_auto_font_offset", True)
    assert row(options, "speedometer/font_offset_vertical")["dimmed"]
    options.discard()


def test_display_orders_never_negative():
    from neopedal.widget._base import validate_option

    config = {"display_order_a": -1000, "display_order_b": 0, "display_order_c": 2}
    validate_option(config)
    assert sorted(config, key=config.get) == ["display_order_a", "display_order_b", "display_order_c"]
    assert min(config.values()) == 0


def test_negative_display_order_classic_overlay(ui_env, bundled_fonts):
    """Negative grid position (preset file, imported package) crashed Qt in classic designs"""
    from importlib import import_module

    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"
    cfg.user.setting["tyre_wear"]["display_order_remaining"] = -1000
    widget = create_widget(import_module("neopedal.widget.tyre_wear"), cfg, "tyre_wear")
    widget.grab()
    widget.deleteLater()


def test_overlay_sizes_limited():
    from neopedal.ui.option_limits import limit_error

    for key, value in (("font_size", 400), ("bar_padding", 1000), ("global_scale", 1000), ("radar_radius", 1000),
                       ("number_of_led", 1000), ("font_scale_caption", 1000), ("inner_gap", 100000)):
        assert limit_error(key, value), key
    assert not limit_error("font_size", 44) and not limit_error("horizontal_gap", 1186)


def test_option_of_several_parts_dimmed_while_every_part_off(options):
    """Label used by a status chip & by the setting change pop-up: dimmed only while both are off, event log
    events counted only while the event log is on (chain)"""
    options.selectOverlay("black_box")
    options.setAdvanced(True)
    options.setText("black_box/display_profile", "Custom")
    options.setBool("black_box/show_abs_indicator", False)
    options.setBool("black_box/show_setting_change_popup", True)
    assert not row(options, "black_box/text_abs")["dimmed"]
    options.setBool("black_box/show_setting_change_popup", False)
    label = row(options, "black_box/text_abs")
    assert label["dimmed"] and "one of" in label["note"] and "Show ABS Indicator" in label["note"]
    options.setBool("black_box/show_abs_indicator", True)
    assert not row(options, "black_box/text_abs")["dimmed"]
    options.setBool("black_box/show_engine_status", False)
    options.setBool("black_box/show_event_log", True)
    options.setBool("black_box/show_engine_overheat_events", True)
    assert not row(options, "black_box/engine_oil_warning_temperature")["dimmed"]
    options.setBool("black_box/show_event_log", False)  # overheat events not logged: temperature unused
    assert row(options, "black_box/engine_oil_warning_temperature")["dimmed"]


def test_shift_flash_interval_of_leds_and_gear_flash(options):
    options.selectOverlay("black_box")
    options.setAdvanced(True)
    options.setText("black_box/display_profile", "Custom")
    options.setBool("black_box/show_rpm_leds", False)
    options.setBool("black_box/enable_shift_flash", False)
    assert row(options, "black_box/shift_flash_interval")["dimmed"]
    options.setBool("black_box/show_gear", True)
    options.setBool("black_box/enable_gear_rpm_color", True)
    options.setBool("black_box/enable_shift_flash", True)
    assert not row(options, "black_box/shift_flash_interval")["dimmed"]
    options.setBool("black_box/enable_gear_rpm_color", False)  # gear flash off up the chain
    assert row(options, "black_box/shift_flash_interval")["dimmed"]


def class_entry(backend) -> dict:
    return next(entry for entry in order_list(backend)["orders"] if entry["toggle"] == "standings/column_class")


def test_class_column_kept_with_class_headers_if_chosen(options):
    set_classic("standings", False)
    cfg.user.setting["standings"].update(enable_multi_class_split_mode=True, show_class_header=True,
                                         column_class=True, show_class_column_with_class_header=False)
    options.refresh()
    options.selectOverlay("standings")
    assert "class" not in driver_columns("standings")[0]
    assert class_entry(options)["note"]  # why not shown
    options.setBool("standings/show_class_column_with_class_header", True)
    assert options.apply()
    assert "class" in driver_columns("standings")[0]
    assert not class_entry(options)["note"]
    options.setBool("standings/show_class_header", False)  # kept column: option of class headers only
    assert row(options, "standings/show_class_column_with_class_header")["dimmed"]


def test_used_only_hides_options_doing_nothing(options):
    set_classic("speedometer")
    options.refresh()
    options.selectOverlay("speedometer")
    options.setBool("speedometer/show_speed_minimum", False)
    options.setUsedOnly(True)
    keys = {entry["key"] for entry in rows(options)}
    assert "speedometer/font_color_speed_minimum" not in keys and options.usedOnly
    assert "speedometer#item:show_speed_minimum" in {entry["key"] for entry in options.rows.rows}  # switch kept
    options.setBool("speedometer/show_speed_minimum", True)  # used again: shown
    assert "speedometer/font_color_speed_minimum" in {entry["key"] for entry in rows(options)}
    options.setUsedOnly(False)
    options.setBool("speedometer/show_speed_minimum", False)
    assert row(options, "speedometer/font_color_speed_minimum")["dimmed"]


@pytest.mark.parametrize(("name", "scenario"), [
    ("flag", "flags"), ("flag", "pits"), ("damage", "damage"), ("weather", "rain"), ("black_box", "damage")])
def test_preview_race_situations_drawn(ui_env, bundled_fonts, name, scenario):
    """Parts drawn only in a race situation (flags, pit, damage, rain) seen on the preview"""
    from neopedal.ui.widget_preview import render_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    values = dict(cfg.user.setting[name])
    racing = render_widget(cfg, name, dict(values)).toImage()
    situation = render_widget(cfg, name, dict(values), scenario=scenario).toImage()
    assert racing != situation


def test_preview_situation_chosen_on_page(options, monkeypatch):
    from neopedal.demo_data import SCENARIOS
    from neopedal.ui.quick import overlay_options_backend

    drawn = []
    real = overlay_options_backend.render_overlay
    monkeypatch.setattr(overlay_options_backend, "render_overlay", lambda name, values, zoom=1.0, scenario="": (
        drawn.append(scenario) or real(name, values, zoom, scenario)))
    options.selectOverlay("flag")
    options.set_active(True)
    options.render_preview()
    assert options.previewScenario == 0 and len(options.scenarioNames) == len(SCENARIOS)
    options.setPreviewScenario(SCENARIOS.index("pits"))
    options.render_preview()
    assert drawn == ["", "pits"] and options.previewScenario == SCENARIOS.index("pits")
    options.setPreviewScenario(99)  # unknown: racing
    options.render_preview()
    assert drawn[-1] == "" and options.previewScenario == 0


def test_preview_of_other_design_to_compare(options, monkeypatch):
    from neopedal.ui.quick import overlay_options_backend

    drawn = []
    real = overlay_options_backend.render_overlay
    monkeypatch.setattr(overlay_options_backend, "render_overlay", lambda name, values, zoom=1.0, scenario="": (
        drawn.append(values["enable_classic_layout"]) or real(name, values, zoom, scenario)))
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    set_classic("speedometer", False)
    options.refresh()
    options.selectOverlay("speedometer")
    info = options.overlayInfo
    assert info["canCompare"] and info["otherDesign"] == "Classic layout" and "of this design only" in info["designOptions"]
    options.set_active(True)
    options.render_preview()
    options.setPreviewCompare(True)
    options.render_preview()
    assert drawn == [False, True] and options.previewCompare  # same values, classic layout drawn
    assert not options.value("speedometer", "enable_classic_layout")  # nothing edited
    cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"  # one design only with this theme
    options.refresh()
    assert not options.overlayInfo["canCompare"]


def test_preview_played_on_page(window):
    """Live Preview plays the overlay on a moving simulated race: pictures shown by the page, pause keeps the still"""
    import time

    from PySide6.QtQuick import QQuickItem

    from neopedal.ui.overlay_options import open_overlay_options

    window.resize(1900, 1000)  # preview panel shown on wide pages only
    page = open_overlay_options(window, "pedal")
    assert page is not None and not page.view.errors()
    backend = page.backend
    backend.setPreviewPlaying(True)
    deadline = time.monotonic() + 10
    while not backend.liveUrl and time.monotonic() < deadline:
        QCoreApplication.processEvents()
    assert backend.liveUrl.startswith("image://overlaypreview/") and backend.previewAnimated
    panel = page.view.rootObject().findChild(QQuickItem, "previewPanel")
    image = next(item for item in panel.findChildren(QQuickItem) if item.property("source") is not None
                 and str(item.property("source").toString()).startswith("image://overlaypreview/"))
    assert image.property("source").toString() == backend.liveUrl
    backend.setPreviewPlaying(False)
    flush()
    assert backend.liveUrl == "" and image.property("source").toString() == backend.previewUrl
