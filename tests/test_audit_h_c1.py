"""Architecture step 5a: overlay registry (template.widget.registry.OVERLAYS) & page registry
(template.page_registry.PAGES), every former table derived from them, unchanged"""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from neopedal.template import page_registry as pages
from neopedal.template.widget import registry

ROOT = Path(__file__).resolve().parent.parent

# Former literal tables (before registries), as they were in template/widget/__init__.py, overlay_backend.py,
# demo_data.py, tools_view.py, nav_rail.py, app.py & setting_global.py
OLD_DISPLAY_ORDER = (
    "acceleration", "battery", "brake_bias", "brake_performance", "brake_pressure", "brake_temperature", "brake_wear",
    "chat", "corner_coach", "cruise", "damage", "damage_stats", "delta_graph", "deltabest", "deltabest_extended",
    "differential",
    "driver_rank", "drs", "electric_motor", "elevation", "engine", "engine_temperature", "flag", "force",
    "friction_circle", "fuel", "fuel_energy_saver", "gap_trend", "gear", "heading", "instrument",
    "laps_and_position", "lap_time_history", "lift_and_coast_led", "navigation", "onboard_setting", "pace_notes",
    "pedal", "pit_lane_helper", "pit_stop_estimate", "push_to_pass", "race_notifications", "race_plan", "radar",
    "rake_angle", "relative", "relative_finish_order", "ride_height", "rivals", "roll_angle", "rpm_led", "sectors",
    "session", "slip_angle", "slip_ratio", "speed_delta", "speedometer", "spotter", "standings", "steering_angle",
    "steering_meter", "steering_wheel", "stint_history", "stint_timer", "suspension_force", "suspension_position",
    "suspension_travel", "system_performance", "telemetry_compare", "timing", "track_clock", "track_map",
    "track_notes", "traffic", "trailing", "tyre_carcass", "tyre_deflection", "tyre_inner_layer", "tyre_load",
    "tyre_overview", "tyre_pressure", "tyre_temp_trend", "tyre_temperature", "tyre_wear", "virtual_energy", "weather",
    "weather_forecast", "weight_distribution", "wheel_camber", "black_box", "wheel_dimension", "wheel_toe",
    "wind_direction",
)
OLD_CATEGORY_PREFIXES = (
    ("Timing", (
        "deltabest", "lap_time_history", "laps_and_position", "pit_stop_estimate", "race_plan", "relative", "rivals",
        "sectors", "session", "standings", "stint_history", "timing", "track_clock",
        "delta_graph", "gap_trend", "stint_timer", "speed_delta", "driver_rank",
    )),
    ("Tyres & Wheels", ("friction_circle", "slip_", "tyre_", "wheel_")),
    ("Brakes", ("brake_",)),
    ("Driver Inputs", ("onboard_setting", "pedal", "steering_", "trailing", "telemetry_compare", "corner_coach")),
    ("Engine & Energy", (
        "battery", "cruise", "drs", "electric_motor", "engine", "fuel", "gear", "instrument", "lift_and_coast",
        "push_to_pass", "rpm_led", "speedometer", "virtual_energy",
    )),
    ("Chassis", (
        "acceleration", "damage", "differential", "force", "rake_angle", "ride_height", "roll_angle",
        "suspension_", "weight_distribution",
    )),
    ("Track & Traffic", (
        "black_box", "chat", "elevation", "flag", "heading", "navigation", "pace_notes", "radar", "track_", "traffic",
        "weather",
        "pit_lane_helper", "race_notifications", "spotter", "wind_direction",
    )),
)
OLD_CATEGORY_COLORS = {
    "Timing": "#4C8DFF",
    "Tyres & Wheels": "#A371F7",
    "Brakes": "#E5534B",
    "Driver Inputs": "#3FB950",
    "Engine & Energy": "#F0883E",
    "Chassis": "#22B8C8",
    "Track & Traffic": "#D4A72C",
    "Other": "#8B949E",
}
OLD_TOOL_SECTIONS = (
    ("Utilities", (
        ("Race Calculator", "", "race_calculator.RaceCalculator"),
        ("Driver Stats Viewer", "", "driver_stats_viewer.DriverStatsViewer"),
        ("Track Map Viewer", "", "track_map_viewer.TrackMapViewer"),
        ("Lap Telemetry Viewer", "", "lap_viewer.LapViewer"),
        ("Broadcast Director", "", "broadcast_director.BroadcastDirector"),
        ("Results & Replays", "", "race_results_viewer.RaceResultsViewer"),
        ("Stream Overlays", "", "stream_overlay_view.StreamOverlaysView"),
    )),
    ("Editors", (
        ("Heatmap Editor", "", "heatmap_editor.HeatmapEditor"),
        ("Brake Editor", "", "brake_editor.BrakeEditor"),
        ("Tyre Compound Editor", "", "tyre_compound_editor.TyreCompoundEditor"),
        ("Vehicle Brand Editor", "", "vehicle_brand_editor.VehicleBrandEditor"),
        ("Vehicle Class Editor", "", "vehicle_class_editor.VehicleClassEditor"),
        ("Track Info Editor", "", "track_info_editor.TrackInfoEditor"),
        ("Track Notes Editor", "", "track_notes_editor.TrackNotesEditor"),
        ("Layout Editor", "", "layout_editor.LayoutEditor"),
    )),
    ("Management", (
        ("Config", "", "app_settings.AppSettings"),
        ("Preset Comparison", "", "preset_compare.PresetCompare"),
        ("Plugin Manager", "", "plugin_manager.PluginManager"),
        ("Widget Performance", "", "perf_view.PerformanceView"),
    )),
    ("Advanced", (
        ("Session Recorder", "", "replay_view.ReplayView"),
    )),
)
OLD_NAV_PAGES = (
    ("home", "Home", "", "A"),
    ("widget", "Overlays", "", "W"),
    ("module", "Module", "", "M"),
    ("preset", "Preset", "", "P"),
    ("spectate", "Spectate", "", "S"),
    ("pacenotes", "Pacenotes", "", "N"),
    ("hotkey", "Hotkey", "", "H"),
    ("tools", "Tools", "", "T"),
)
OLD_SHORT_LABELS = {
    "race_calculator": "Race", "driver_stats_viewer": "Stats", "track_map_viewer": "Map", "lap_viewer": "Telemetry",
    "replay_view": "Recorder", "broadcast_director": "Broadcast",
    "race_results_viewer": "Results", "stream_overlay_view": "Stream", "heatmap_editor": "Heatmap",
    "brake_editor": "Brakes", "tyre_compound_editor": "Compounds", "vehicle_brand_editor": "Brands",
    "vehicle_class_editor": "Classes", "track_info_editor": "Tracks", "track_notes_editor": "Notes",
    "layout_editor": "Layout", "preset_compare": "Compare", "plugin_manager": "Plugins", "perf_view": "Performance",
}
OLD_KEYWORD_TOOLS = {
    "app_settings.AppSettings", "stream_overlay_view.StreamOverlaysView", "race_results_viewer.RaceResultsViewer",
    "broadcast_director.BroadcastDirector", "race_calculator.RaceCalculator",
    "replay_view.ReplayView",
}
OLD_RAIL_ITEMS = (
    "home,widget,driver_stats_viewer,race_results_viewer,"  # game replays merged in results & replays
    "broadcast_director,stream_overlay_view,lap_viewer,race_calculator,preset"
)
OLD_PAGE_SWITCHES = {
    ("BroadcastDirector", "neopedal.ui.quick.director_backend", "director_status"),
    ("RaceCalculator", "neopedal.ui.quick.race_backend", "race_status"),
}


def old_widget_category(name: str) -> str:
    for category, prefixes in OLD_CATEGORY_PREFIXES:
        if name.startswith(prefixes):
            return category
    return "Other"


def dummy_overlay(**kwargs):
    """Overlay spec of a new overlay, default options in a copy of a template group"""
    groups = {"timing": {"dummy_overlay": {"enable": False, "update_interval": 50, "position_x": 0}}}
    return registry.overlay("dummy_overlay", registry.TIMING, groups=groups, **kwargs), groups


DUMMY_PAGE = pages.PageSpec(
    "dummy_tool", "Dummy Tool", "", "Editors", "dummy_tool.DummyTool",
    short_label="Dummy", rail=9, keywords="dummy words", status="neopedal.ui.quick.dummy_backend:dummy_status",
)


# Overlays: derived tables equal former literal tables
def test_overlay_display_order_and_filenames_unchanged():
    from neopedal.template.setting_widget import WIDGET_DEFAULT, WIDGET_FILENAME
    from neopedal.template.widget import WIDGET_CATEGORIES, WIDGET_DISPLAY_ORDER

    assert WIDGET_DISPLAY_ORDER == OLD_DISPLAY_ORDER
    assert WIDGET_FILENAME[:len(OLD_DISPLAY_ORDER)] == OLD_DISPLAY_ORDER  # plugins after
    merged = {}
    for group in WIDGET_CATEGORIES:  # former merge of template groups
        merged.update(group)
    assert set(merged) == set(OLD_DISPLAY_ORDER)
    for name in OLD_DISPLAY_ORDER:
        assert WIDGET_DEFAULT[name] is merged[name]  # same template dicts (modern & common options added)
        keys = list(WIDGET_DEFAULT[name])
        assert keys.index("enable_classic_layout") == keys.index("enable") + 1
        assert WIDGET_DEFAULT[name]["visibility_context"] == "Always"
        assert WIDGET_DEFAULT[name]["stream_visibility"] == "Screen & Stream"


def test_overlay_modern_designs_unchanged():
    from neopedal.template.widget.modern import MODERN_DESIGN_OPTIONS, MODERN_DESIGNS, MODERN_ONLY_OPTIONS

    assert frozenset(OLD_DISPLAY_ORDER) == MODERN_DESIGNS  # every built-in overlay has a modern design
    assert set(MODERN_DESIGN_OPTIONS) == set(OLD_DISPLAY_ORDER)
    for name, options in MODERN_DESIGN_OPTIONS.items():
        assert options == MODERN_ONLY_OPTIONS.get(name, {})
    assert MODERN_DESIGN_OPTIONS["relative"]["column_laptime"] is True
    assert MODERN_DESIGN_OPTIONS["weather"] == {"show_wind": True}
    assert MODERN_DESIGN_OPTIONS["sectors"] == {}


def test_overlay_categories_unchanged():
    from neopedal.ui.quick.overlay_backend import (
        CATEGORY_COLORS,
        CATEGORY_ORDER,
        CATEGORY_OTHER,
        WIDGET_CATEGORIES,
        widget_category,
    )

    for name in OLD_DISPLAY_ORDER:
        assert widget_category(name) == old_widget_category(name), name
    assert widget_category("plugin_xyz") == CATEGORY_OTHER == "Other"
    assert CATEGORY_COLORS == OLD_CATEGORY_COLORS
    assert list(CATEGORY_COLORS) == list(OLD_CATEGORY_COLORS)
    assert (*(category for category, _ in OLD_CATEGORY_PREFIXES), "Other") == CATEGORY_ORDER
    assert [category for category, _ in WIDGET_CATEGORIES] == [category for category, _ in OLD_CATEGORY_PREFIXES]


def test_overlay_demo_feeds_and_option_ui_unchanged():
    from neopedal import demo_data
    from neopedal.template.widget import WIDGET_OPTION_SECTIONS, WIDGET_OPTION_UI
    from neopedal.template.widget.black_box_ui import BLACK_BOX_UI
    from neopedal.template.widget.drivers_ui import RELATIVE_UI, RIVALS_UI, STANDINGS_UI

    assert demo_data.HISTORY_WIDGETS == ("friction_circle", "trailing")
    assert demo_data.LAP_WIDGETS == ("delta_graph",)
    assert frozenset(("chat", "flag", "race_notifications", "spotter")) == demo_data.SAMPLE_WIDGETS
    assert WIDGET_OPTION_UI == {
        "black_box": BLACK_BOX_UI, "relative": RELATIVE_UI, "standings": STANDINGS_UI, "rivals": RIVALS_UI}
    assert {name: ui.sections for name, ui in WIDGET_OPTION_UI.items()} == WIDGET_OPTION_SECTIONS


def test_widget_config_types_input_unchanged():
    """Generated settings types read WIDGET_DEFAULT in WIDGET_DISPLAY_ORDER: still up to date"""
    from neopedal.template.widget_config_types import WIDGET_CONFIG_TYPES

    assert tuple(WIDGET_CONFIG_TYPES) == OLD_DISPLAY_ORDER


def test_registry_is_plain_data():
    """Registries load no Qt GUI module & no widget module"""
    code = (
        "import sys; import neopedal.template.widget.registry, neopedal.template.page_registry, "
        "neopedal.template.widget.modern; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtQuick', "
        "'neopedal.widget', 'neopedal.ui'))]; print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


# Overlays: a new spec appears everywhere it should
def test_new_overlay_spec_appears_everywhere():
    from neopedal.template.setting_shortcuts import BINDING_GENERAL, generate_shortcut_setting
    from neopedal.template.setting_widget import widget_defaults
    from neopedal.template.widget.modern import modern_design_options

    spec, groups = dummy_overlay(demo=registry.DEMO_SAMPLE)
    assert spec.template == "timing" and spec.defaults is groups["timing"]["dummy_overlay"]
    overlays = (*registry.OVERLAYS, spec)
    registry.check_overlays(overlays, {**registry.TEMPLATE_GROUPS, "extra": groups["timing"]})
    order = registry.display_order(overlays)
    assert order == (*OLD_DISPLAY_ORDER, "dummy_overlay")
    assert registry.category_of(overlays)["dummy_overlay"] == registry.TIMING
    assert registry.demo_names(registry.DEMO_SAMPLE, overlays)[-1] == "dummy_overlay"
    assert modern_design_options(overlays)["dummy_overlay"] == {}
    assert "widget_dummy_overlay" in generate_shortcut_setting(order, BINDING_GENERAL, "widget")
    # Default setting: modern switch after "enable", common options, plugins after built-in overlays
    defaults = widget_defaults((spec,), {"plugin_x": {"enable": False}})
    assert list(defaults) == ["dummy_overlay", "plugin_x"]
    assert list(defaults["dummy_overlay"]) == [
        "enable", "enable_classic_layout", "update_interval", "position_x", "visibility_context", "stream_visibility"]
    # Without modern design: not in modern designs, no classic layout switch
    classic, _ = dummy_overlay(has_modern=False)
    assert "dummy_overlay" not in modern_design_options((*registry.OVERLAYS, classic))
    assert "enable_classic_layout" not in widget_defaults((classic,), {})["dummy_overlay"]


def test_overlay_registry_rejects_mistakes():
    with pytest.raises(RuntimeError):  # no default options
        registry.overlay("no_defaults_overlay", registry.TIMING)
    with pytest.raises(RuntimeError):  # unknown category
        registry.overlay("dummy_overlay", "Nowhere", groups={"timing": {"dummy_overlay": {}}})
    with pytest.raises(RuntimeError):  # default options without spec
        registry.check_overlays(registry.OVERLAYS, {**registry.TEMPLATE_GROUPS, "extra": {"orphan": {}}})
    with pytest.raises(RuntimeError):  # declared twice
        registry.check_overlays((*registry.OVERLAYS, registry.OVERLAYS[0]))


def test_overlay_page_category_follows_spec(monkeypatch):
    from neopedal.ui.quick import overlay_backend

    spec, _ = dummy_overlay()
    monkeypatch.setattr(overlay_backend, "_WIDGET_CATEGORY", registry.category_of((*registry.OVERLAYS, spec)))
    assert overlay_backend.widget_category("dummy_overlay") == registry.TIMING


# Tool pages: derived tables equal former literal tables
def test_tool_tables_unchanged():
    from neopedal.template.setting_global import GLOBAL_DEFAULT
    from neopedal.ui.app import PAGE_SWITCHES
    from neopedal.ui.nav_rail import NAV_PAGES, PAGE_INDEX, TOOL_SHORT_LABELS, default_rail_items
    from neopedal.ui.tools_view import TOOL_KEYWORDS, TOOL_SECTIONS

    assert TOOL_SECTIONS == OLD_TOOL_SECTIONS
    assert NAV_PAGES == OLD_NAV_PAGES
    assert {key: index for index, (key, *_) in enumerate(OLD_NAV_PAGES)} == PAGE_INDEX
    assert TOOL_SHORT_LABELS == OLD_SHORT_LABELS
    assert set(TOOL_KEYWORDS) == OLD_KEYWORD_TOOLS
    assert "reglages" in TOOL_KEYWORDS["app_settings.AppSettings"]
    assert GLOBAL_DEFAULT["application"]["rail_items"] == OLD_RAIL_ITEMS
    assert default_rail_items() == OLD_RAIL_ITEMS.split(",")
    assert set(PAGE_SWITCHES) == OLD_PAGE_SWITCHES


def test_rail_entries_unchanged():
    from neopedal.ui.nav_rail import rail_entries

    entries = rail_entries()
    assert list(entries)[:len(OLD_NAV_PAGES)] == [key for key, *_ in OLD_NAV_PAGES]
    assert entries["app_settings"].label == "Config" and entries["app_settings"].letter == "C"
    assert entries["lap_viewer"].label == "Telemetry" and entries["lap_viewer"].tooltip == "Lap Telemetry Viewer"
    assert entries["home"].letter == "A" and entries["home"].page == 0


# Tool pages: a new spec appears everywhere it should
def test_new_page_spec_appears_everywhere(monkeypatch):
    from neopedal.ui import nav_rail

    specs = (*pages.PAGES, DUMMY_PAGE)
    pages.check_pages(specs)
    sections = dict(pages.tool_sections(specs))
    assert sections["Editors"][-1] == ("Dummy Tool", "", "dummy_tool.DummyTool")
    assert pages.default_rail(specs) == OLD_RAIL_ITEMS + ",dummy_tool"
    assert DUMMY_PAGE in pages.tool_pages(specs) and DUMMY_PAGE not in pages.main_pages(specs)
    # Navigation rail entry: short label, tooltip, dialog
    monkeypatch.setattr(nav_rail, "TOOL_SECTIONS", pages.tool_sections(specs))
    monkeypatch.setattr(nav_rail, "TOOL_SHORT_LABELS", {page.name: page.short_label for page in specs if page.short_label})
    entry = nav_rail.rail_entries()["dummy_tool"]
    assert (entry.label, entry.tooltip, entry.letter, entry.dialog) == ("Dummy", "Dummy Tool", "D", "dummy_tool.DummyTool")


def test_page_registry_rejects_mistakes():
    with pytest.raises(RuntimeError):  # declared twice
        pages.check_pages((*pages.PAGES, pages.PAGES[-1]))
    with pytest.raises(RuntimeError):  # unknown category
        pages.check_pages((*pages.PAGES, replace(DUMMY_PAGE, category="Toys")))
    with pytest.raises(RuntimeError):  # dialog module not named like page
        pages.check_pages((*pages.PAGES, pages.PageSpec("dummy_tool", "Dummy", "", "Editors", "other.DummyTool")))
    with pytest.raises(RuntimeError):  # rail position taken
        pages.check_pages((*pages.PAGES, pages.PageSpec("dummy_tool", "Dummy", "", "Editors", "dummy_tool.D", rail=0)))
