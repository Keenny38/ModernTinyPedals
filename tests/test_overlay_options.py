"""Overlay Options page: sections of every overlay, editors by option kind, pending edits of many overlays, undo & redo,
search in one or every overlay, Modified filter, apply to every overlay, display order, Black box tools, apply (saved,
edited overlays restarted), preview, page in app & every entry opening it"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.setting import cfg


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
        from tinypedal.template.setting_widget import WIDGET_DEFAULT

        self.names = list(WIDGET_DEFAULT)
        self.reloaded: list[str] = []

    def reload(self, name):
        self.reloaded.append(name)


@pytest.fixture
def options(ui_env):
    from tinypedal.ui.quick.overlay_options_backend import OverlayOptionsBackend

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


def set_classic(name: str, classic: bool = True):
    if "enable_classic_layout" in cfg.user.setting[name]:
        cfg.user.setting[name]["enable_classic_layout"] = classic


# Sections
def test_sections_of_every_overlay_hold_every_shown_option_once(ui_env):
    from tinypedal.template.setting_widget import WIDGET_DEFAULT
    from tinypedal.ui.quick.overlay_options_backend import build_layout
    from tinypedal.widget._modern import design_option_keys

    for classic in (False, True):
        for name in WIDGET_DEFAULT:
            set_classic(name, classic)
            layout = build_layout(name, cfg.user.setting[name])
            shown = design_option_keys(cfg, name, list(cfg.user.setting[name]))
            assert sorted(layout.keys) == sorted(shown), name
            assert all(section.keys for section in layout.sections), name
            for key, control in layout.dependencies.items():  # options depend on an on/off option of the overlay
                assert isinstance(cfg.user.setting[name][control], bool), (name, key, control)


def test_item_sections_follow_their_on_off_option(ui_env):
    from tinypedal.ui.quick.overlay_options_backend import build_layout
    from tinypedal.ui.quick.overlay_sections import SECTION_FONT, SECTION_GENERAL, SECTION_LAYOUT, SECTION_ORDER

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
    from tinypedal.ui.quick.overlay_options_backend import build_layout
    from tinypedal.ui.quick.overlay_sections import SECTION_SHOWN

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
    order = rows(options, "order")[0]
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
    assert len(found) == len(options._names) and options.matchCount == len(found)
    assert row(options, "fuel#layout")["title"].startswith("Fuel")
    nav = {entry["key"]: entry for entry in options.nav.rows}
    assert nav["fuel"]["matches"] == 1
    options.selectOverlay("fuel")  # overlay chosen from results: its own options again
    assert not options.scopeAll and [entry["key"] for entry in rows(options)] == ["fuel/opacity"]


def test_search_every_overlay_is_capped(options):
    from tinypedal.ui.quick.overlay_options_backend import MAX_ROWS

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
    first = [entry["key"] for entry in rows(options, "order")[0]["orders"]]
    options.moveOrder("speedometer", first[0], 1)
    moved = [entry["key"] for entry in rows(options, "order")[0]["orders"]]
    assert moved[:2] == [first[1], first[0]] and rows(options, "order")[0]["changed"]
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
    locked = [entry for entry in rows(options) if entry["locked"]]
    assert locked and all(entry["note"].startswith("Set by") for entry in locked)
    options.applyColorTheme("Colorblind Safe")
    assert options.value("black_box", "wheel_lock_color") != cfg.default.setting["black_box"]["wheel_lock_color"]


def test_black_box_sections_order_list_and_dependency_chain(options):
    from tinypedal.ui.quick.overlay_options_backend import build_layout
    from tinypedal.ui.quick.overlay_sections import SECTION_GENERAL, SECTION_ORDER

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
    from tinypedal.template.widget.black_box_ui import ORDER_LIST
    from tinypedal.ui.quick.overlay_sections import SECTION_OPTIONS, SECTION_ORDER, listed_sections, order_keys

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
    from tinypedal.template.widget.drivers_ui import RELATIVE_COLUMNS, STANDINGS_COLUMNS, order_option
    from tinypedal.ui.quick.overlay_options_backend import build_layout
    from tinypedal.ui.quick.overlay_sections import SECTION_ORDER

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
    order = rows(options, "order")[0]
    keys = [item["key"] for item in order["orders"]]
    assert keys == [order_option(column) for column in STANDINGS_COLUMNS]  # design order, not option values
    assert order["help"].startswith("Columns from left to right")
    logo = next(item for item in order["orders"] if item["key"] == "display_order_brand_logo")
    assert logo["label"] == "Brand Logo" and logo["toggle"] == "standings/column_brand_logo" and logo["checked"]
    options.setBool(logo["toggle"], False)
    logo = next(item for item in rows(options, "order")[0]["orders"] if item["key"] == "display_order_brand_logo")
    assert not logo["checked"] and logo["changed"]
    assert row(options, "standings/brand_logo_width")["dimmed"]
    # Moving one column keeps the others where the overlay shows them
    options.moveOrder("standings", keys[3], -1)
    moved = [item["key"] for item in rows(options, "order")[0]["orders"]]
    assert moved == [*keys[:2], keys[3], keys[2], *keys[4:]]
    assert [options.value("standings", key) for key in moved] == list(range(1, len(moved) + 1))
    options.resetOrder("standings")
    assert [item["key"] for item in rows(options, "order")[0]["orders"]] == keys
    assert options.value("standings", "column_brand_logo") is False  # columns shown left as set
    options.selectOverlay("relative")
    assert len(rows(options, "order")[0]["orders"]) == len(RELATIVE_COLUMNS)
    set_classic("standings")
    assert build_layout("standings", cfg.user.setting["standings"]).option_ui is None


def test_driver_list_preview_shows_sample_race(ui_env, bundled_fonts):
    from tinypedal.ui.widget_preview import render_widget
    from tinypedal.widget._modern.sample_field import FIELD, PLAYER, sample_field, sample_standings

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
    helps = [entry["help"] for entry in rows(options)]
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
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            backend = getattr(page.dialog, "backend", None)
            if backend is not None and hasattr(backend, "discard"):
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
    from tinypedal.ui.overlay_options import OverlayOptions

    return [page for page in window.centralWidget().dialog_pages() if isinstance(page.dialog, OverlayOptions)]


def test_one_page_for_every_overlay(window):
    from tinypedal.ui.overlay_options import open_overlay_options

    first = open_overlay_options(window, "speedometer")
    assert first is not None and first.backend.overlay == "speedometer"
    assert not first.view.errors(), [error.toString() for error in first.view.errors()]
    second = open_overlay_options(window, "fuel", "opacity")
    flush()
    assert second is first and first.backend.overlay == "fuel" and len(option_pages(window)) == 1
    assert option_pages(window)[0].title == "Overlay Options"


def test_page_unsaved_marker_ctrl_s_and_close(window, monkeypatch):
    from tinypedal.ui import overlay_options
    from tinypedal.ui.overlay_options import open_overlay_options

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

    from tinypedal.ui.overlay_options import open_overlay_options

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
    from tinypedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "speedometer")
    assert page not in window.config_dialogs(preset_only=True)  # refreshed, not closed by preset loading
    page.backend.setNumber("speedometer/opacity", 0.5)
    assert page in window.modified_config_dialogs(preset_only=True)  # loading asks to save first


def test_page_rebuilt_in_new_language(window):
    from tinypedal import i18n
    from tinypedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "speedometer")
    page.backend.setNumber("speedometer/opacity", 0.5)
    i18n.set_language("Français")
    try:
        page.refresh()
        assert option_pages(window)[0].title == "Options des overlays" and not page.view.errors()
        assert page.backend.pendingCount == 1 and page.backend.overlayInfo["label"] == "Compteur de vitesse"
    finally:
        i18n.set_language("English")
        page.refresh_now()
        page.backend.discard()


def test_overlay_entries_open_the_page(window, monkeypatch):
    from tinypedal.ui.overlay_options import OverlayOptions
    from tinypedal.ui.overlay_view import OverlayView
    from tinypedal.widget._base import config_widget

    overlays = OverlayView(window)
    overlays.open_config("fuel")
    page = option_pages(window)[0].dialog
    assert isinstance(page, OverlayOptions) and page.backend.overlay == "fuel"
    config_widget("speedometer")  # overlay right click menu
    assert page.backend.overlay == "speedometer" and len(option_pages(window)) == 1
    from tinypedal.module_control import wctrl
    from tinypedal.ui.command_palette import module_commands

    configure = next(command for command in module_commands(wctrl, "Overlays", window)
                     if command.title.startswith("Relative") and "⚙" in command.title)
    configure.run()
    assert page.backend.overlay == "relative"
    overlays.deleteLater()


PAGE_QML = ("OverlayOptions", "OverlayOptionRow")


def test_page_qml_bundled_modules_and_translated():
    """Release build bundles only QML_MODULES; every text of the page has a French translation"""
    import re

    from tinypedal.i18n.fr import TRANSLATION
    from tinypedal.ui.quick import QML_FOLDER
    from tinypedal.ui.quick.overlay_sections import FIXED_TITLES
    from tinypedal.ui.quick.qml_modules import QML_MODULES

    pattern = re.compile(r'i18n\.tr\("((?:[^"\\]|\\.)*)"\)')
    missing = []
    for name in PAGE_QML:
        with open(f"{QML_FOLDER}/{name}.qml", encoding="utf-8") as file:
            text = file.read()
        modules = re.findall(r"^import ([A-Za-z.]+)", text, flags=re.MULTILINE)
        assert modules and all(module.replace(".", "/") in QML_MODULES for module in modules), (name, modules)
        missing += [found for found in pattern.findall(text) if found not in TRANSLATION]
    missing += [title for title in FIXED_TITLES.values() if title not in TRANSLATION]
    assert not missing


def test_backend_texts_translated(options):
    from tinypedal import i18n

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
