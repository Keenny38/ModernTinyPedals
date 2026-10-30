"""UI/UX consistency audit 2026-10-29, overlay side: one colorblind palette (C2), reference lap accents (C3),
one warning & slower color (C4), neutral rivals gap (C7), captions (O1), invalid laps (O2), rivals best lap (O3),
one flash rule (O4), same defaults (O5, O8, F7), panel radius (O6), design fonts (O7), gaps without unit (O9),
labels (O10), signs, lap times & placeholders (F2, F3), class badges (C6)"""

import re
from pathlib import Path

import pytest

from neopedal.setting import cfg
from tests.test_delta_session import overlays  # noqa: F401  (fixture)

MODERN = Path(__file__).resolve().parent.parent / "neopedal" / "widget" / "_modern"


def hex_of(color) -> str:
    return color.name().upper()


# --- C2: one colorblind source
def test_colorblind_status_colors_one_source():
    from neopedal.template.setting_status_colors import COLORBLIND_STATUS_COLORS, STATUS_COLORS, status_css
    from neopedal.ui.quick import COLORBLIND_STATUS
    from neopedal.widget._style import COLORBLIND_COLORS

    assert COLORBLIND_STATUS is COLORBLIND_STATUS_COLORS
    assert set(COLORBLIND_STATUS_COLORS) == set(STATUS_COLORS)
    dark = {role: pair[0][1:].upper() for role, pair in COLORBLIND_STATUS_COLORS.items()}
    assert COLORBLIND_COLORS["9900FF"] == dark["purple"]  # best purple has a colorblind variant
    assert COLORBLIND_COLORS["FF2200"] == dark["loss"] and COLORBLIND_COLORS["22CC22"] == dark["gain"]
    assert COLORBLIND_COLORS["FF6600"] == dark["warning"] and COLORBLIND_COLORS["FFFF00"] == dark["gold"]
    assert COLORBLIND_COLORS["00CCFF"] == dark["player"]
    css = status_css(colorblind=True)
    assert "--gain:#56b4e9;" in css and "--purple:#e08ac0;" in css and "--warn:#e69f00;" in css
    assert status_css(light=True, colorblind=True) != css and status_css() != css


def test_overlay_theme_uses_colorblind_status_colors(ui_env):
    from neopedal.template.setting_status_colors import COLORBLIND_STATUS_COLORS
    from neopedal.widget._modern.theme import build_theme

    style = dict(cfg.default.config["overlay_style"], overlay_theme="Modern Dark", enable_colorblind_colors=True)
    theme = build_theme(style)
    for token, role in (("best", "purple"), ("positive", "gain"), ("negative", "loss"), ("warning", "warning"),
                        ("caution", "gold"), ("accent", "player")):
        assert hex_of(getattr(theme, token)) == COLORBLIND_STATUS_COLORS[role][0], token


def test_stream_pages_follow_colorblind_option(ui_env, monkeypatch):
    from neopedal.stream_director import director_html
    from neopedal.stream_overlay import results_html
    from neopedal.template.setting_status_colors import status_css
    from neopedal.web_dashboard import dashboard_html

    style = cfg.user.config["overlay_style"]
    monkeypatch.setitem(style, "enable_colorblind_colors", True)
    assert status_css(colorblind=True) in results_html()
    assert status_css(colorblind=True) in director_html("en", "x", colorblind=True)
    assert "--green:#56b4e9;" in dashboard_html()
    monkeypatch.setitem(style, "enable_colorblind_colors", False)
    assert status_css() in results_html() and "--green:#4ade80;" in dashboard_html()


# --- C4: one warning color, slower in gold
def test_one_warning_token(ui_env):
    from neopedal.widget._modern.theme import build_theme

    theme = build_theme(dict(cfg.default.config["overlay_style"], overlay_theme="Modern Dark"))
    assert theme.warning == theme.orange


def test_lap_delta_color_slower_gold(ui_env):
    from neopedal.widget._modern.base import lap_delta_color
    from neopedal.widget._modern.theme import build_theme

    theme = build_theme(cfg.default.config["overlay_style"])
    assert lap_delta_color(theme, 0.3) == theme.caution and lap_delta_color(theme, -0.3) == theme.positive
    assert lap_delta_color(theme, 0.0) == theme.text_dim


# --- F2, F3, F7: lap time, placeholders, signs
def test_laptime_text_signed_and_placeholders():
    from neopedal.widget._modern.base import DASH, NO_CLOCK, NO_LAPTIME, laptime_text, signed

    assert f"{DASH}:{DASH}{DASH}.{DASH}{DASH}{DASH}" == NO_LAPTIME and NO_CLOCK.count(DASH) == 5
    assert laptime_text(612.345) == "10:12.345"  # never cut (was [:8] in lap time history)
    assert laptime_text(59.1) == "0:59.100" and laptime_text(59.1, running=True) == "0:59.100"
    assert laptime_text(80.0, valid=False) == "*1:20.000"
    assert laptime_text(0) == NO_LAPTIME and laptime_text(-1) == NO_LAPTIME
    assert signed(-0.0001, 2) == "+0.00" and signed(-1.25, 1) == "-1.2" and signed(3) == "+3"


def test_modern_overlays_no_untranslated_placeholders():
    pattern = re.compile(r"TEXT_NA\b|TEXT_NOLAPTIME|TEXT_PLACEHOLDER|\"- · -\"|\"-:--:--\"")
    for path in MODERN.glob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_modern_signed_values_never_minus_zero():
    signed_format = re.compile(r":\+\.|:\+0?\d|:\+\{")  # "+" sign format without "z"
    for path in MODERN.glob("*.py"):
        assert not signed_format.search(path.read_text(encoding="utf-8")), path.name


# --- C3: reference laps
def test_reference_accents_shared(overlays):  # noqa: F811
    from neopedal.widget._modern.base import reference_accent

    timing = overlays("timing", show_session_best=True, show_session_personal_best=True, show_stint_best=True)
    extended = overlays("deltabest_extended", show_session_deltabest=True, show_stint_deltabest=True)
    speed = overlays("speed_delta", show_session_best=True, show_stint_best=True)
    theme = timing.theme
    accents = {(type(w).__module__, slot.stat.key): slot.stat for w in (timing, extended, speed) for slot in w.slots}
    personal = reference_accent(theme, "session_personal_best")
    assert accents[("neopedal.widget._modern.timing", "session_personal_best")].accent == personal
    assert accents[("neopedal.widget._modern.deltabest_extended", "session_deltabest")].accent == personal
    assert accents[("neopedal.widget._modern.speed_delta", "session_best")].accent == personal
    assert accents[("neopedal.widget._modern.deltabest_extended", "session_deltabest")].label == "Session PB"
    assert accents[("neopedal.widget._modern.speed_delta", "session_best")].label == "Session PB"
    assert accents[("neopedal.widget._modern.timing", "session_best")].accent == theme.best  # every driver
    assert personal != theme.best


# --- O1: captions
def test_show_caption_hides_modern_labels(overlays):  # noqa: F811
    shown = overlays("traffic", show_caption=True)
    assert all(slot.label.height() > 0 for slot in shown.slots)
    hidden = overlays("traffic", show_caption=False)
    assert all(slot.label.height() == 0 for slot in hidden.slots) and hidden.height() < shown.height()
    wear = overlays("tyre_wear", show_caption=False)
    assert not any(slot.label.height() for slot in wear.quad_slots)


def test_caption_off_by_default_keeps_design_labels(overlays):  # noqa: F811
    assert cfg.default.setting["brake_pressure"]["show_caption"] is False
    widget = overlays("brake_pressure", show_caption=False)
    assert widget.caption_shown() and widget.quad_slots[0].label.height() > 0


# --- O2: invalid laps
def test_timing_last_lap_follows_invalid_option(overlays, monkeypatch):  # noqa: F811
    from neopedal.module_info import minfo

    monkeypatch.setattr(minfo.delta, "isValidLap", False)
    monkeypatch.setattr(minfo.delta, "lapTimeLast", 90.0)
    for show in (True, False):
        widget = overlays("timing", show_last=True, show_invalid_lap_indicator=show)
        widget.timerEvent(None)
        value = widget.state[widget.keys.index("last")]
        assert (value.color == widget.theme.negative) is show


def test_lap_time_history_invalid_lap_option(overlays):  # noqa: F811
    assert cfg.default.setting["lap_time_history"]["show_invalid_lap_in_red"] is True
    red = overlays("lap_time_history", show_invalid_lap_in_red=True)
    cell = red.lap_row(3, 90.0, False, 0.2, 2.0, "", 1.0, 0.1).cells[1]
    assert cell.color == red.theme.negative and cell.text == "1:30.000"
    star = overlays("lap_time_history", show_invalid_lap_in_red=False)
    cell = star.lap_row(3, 90.0, False, 0.2, 2.0, "", 1.0, 0.1).cells[1]
    assert cell.color == star.theme.text and cell.text == "*1:30.000"
    delta = star.lap_row(3, 90.0, True, 0.2, 2.0, "", 1.0, 0.1).cells[2]
    assert delta.color == star.theme.caution and delta.text == "+0.20"  # slower: gold, red only invalid laps


# --- C7, O3, F6: rivals
def test_rivals_interval_neutral_and_dash():
    from neopedal.widget._modern.base import DASH
    from neopedal.widget._modern.rivals import interval_text

    assert interval_text(0, True, 1) == DASH and interval_text(2, False, 1) == "+2L" and interval_text(1, True, 1) == "-1L"
    assert interval_text(1.26, True, 1) == "-1.3" and interval_text(1.26, False, 1) == "+1.3"
    assert interval_text(-0.0001, False, 1) == "+0.0"


def test_rivals_and_standings_share_best_lap_cell():
    from neopedal.widget._modern import rivals, standings
    from neopedal.widget._modern.drivers import DriverTable

    for module in (rivals, standings):
        assert "best_lap_cell" not in vars(module.Realtime)  # DriverTable method, same purple rule
    assert "show_highlighted_fastest_last_laptime" in DriverTable.best_lap_cell.__doc__


# --- O4: one flash rule
def test_flash_lit_and_warning_flash(monkeypatch):
    from neopedal.widget import _common

    assert _common.flash_lit(0.1, 0.3) and not _common.flash_lit(0.4, 0.3) and _common.flash_lit(0.65, 0.3)
    assert _common.flash_lit(0.25, 0.3, 0.5) and not _common.flash_lit(0.35, 0.3, 0.5)
    assert _common.flash_lit(0.05, 0.01) and not _common.flash_lit(0.25, 0.01)  # minimum 0.2 s
    assert not _common.flash_lit(0.06, 0.05, minimum=0.05)  # fast flash minimum
    clock = {"now": 100.0}
    monkeypatch.setattr(_common, "monotonic", lambda: clock["now"])
    flash = _common.warning_flash(0.4, 0.4, 3)
    clock["now"] = 100.0
    states = [flash.send(True)]  # flash starts
    for step in range(1, 12):  # 0.2 s steps (off phase edges avoided): 2 flashes, steady from third flash on
        clock["now"] = 100.05 + step * 0.2
        states.append(flash.send(True))
    assert states == [True, True, False, False, True, True, False, False, True, True, True, True]
    assert flash.send(False) is False
    clock["now"] = 200.0
    assert flash.send(True) is True  # flashes again from start


# --- O5, O8, F7: same defaults (new presets)
def test_same_defaults_for_same_things():
    from neopedal.template.setting_widget import WIDGET_DEFAULT

    assert {WIDGET_DEFAULT[name]["update_interval"] for name in ("relative", "standings", "rivals")} == {100}
    assert {WIDGET_DEFAULT[name]["decimal_places_time_interval"] for name in ("standings", "rivals", "traffic")} == {1}
    assert {WIDGET_DEFAULT[name]["decimal_places_energy_remaining"]
            for name in ("relative", "standings", "rivals")} == {0}
    for key in ("decimal_places_fuel", "decimal_places_wear", "decimal_places_delta"):
        assert WIDGET_DEFAULT["lap_time_history"][key] == WIDGET_DEFAULT["stint_history"][key], key
    assert WIDGET_DEFAULT["delta_graph"]["decimal_places"] == WIDGET_DEFAULT["deltabest"]["decimal_places"]
    for name in ("deltabest", "pit_lane_helper", "race_notifications"):
        assert WIDGET_DEFAULT[name]["font_size"] == 15, name
    assert {setting["opacity"] for setting in WIDGET_DEFAULT.values() if "opacity" in setting} == {0.9}


# --- O6, O7: panel radius, design fonts
def test_panel_radius_shared():
    for path in MODERN.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "panel(painter, QRectF(self.rect())" in line:
                assert "self.panel_radius()" in line, (path.name, line)


@pytest.mark.parametrize("name", ["gear", "onboard_setting"])
def test_design_fonts_same_scale(overlays, name):  # noqa: F811
    from neopedal.widget._modern.base import DESIGN_SCALE

    widget = overlays(name)
    assert widget.fonts["label"].pixelSize() == pytest.approx(widget.unit * 0.68, abs=1)
    if name == "onboard_setting":  # default font size 25: same unit as other overlays at their default
        assert widget.unit == pytest.approx(15 * DESIGN_SCALE)


# --- O9, C6: gaps without unit, class badges
def test_traffic_class_badge_and_gap_without_unit(overlays, monkeypatch):  # noqa: F811
    from neopedal.widget._modern import traffic

    widget = overlays("traffic", show_class=True, show_driver_name_instead_of_class=False, show_estimated_laps=True,
                      show_time_interval=True)
    monkeypatch.setattr(traffic, "class_style", lambda config, name, theme: ("GT3", theme.positive))
    value = widget.traffic_value((1.5, 2.25, 0), 0.5)
    assert value.badge == "GT3" and value.badge_color == widget.theme.positive
    assert not value.sub.endswith("s") and value.sub.startswith("2.2")
    widget.grab()  # badge drawn


def test_blue_flag_gap_without_unit_and_class_badge(overlays, monkeypatch):  # noqa: F811
    from neopedal.widget._modern import flag

    widget = overlays("flag", show_blue_flag=True, show_blue_flag_gap=True, show_blue_flag_for_race_only=False)
    monkeypatch.setattr(widget, "blue_timer", type("Timer", (), {"update": lambda self, in_race, lap_etime: 3.0})())
    monkeypatch.setattr(flag, "blue_flag_class", lambda classes: "HY")
    monkeypatch.setattr(flag, "blue_flag_gap", lambda: 1.24)
    chip = widget.read_blue_flag(0.0, False, True)
    assert chip.value == "1.2" and chip.caption == "HY" and chip.badge is not None
    widget.refresh((chip,))
    widget.grab()


# --- O10: labels accounted for
def test_overlay_labels_listed():
    from neopedal.i18n.fr_overlay import OVERLAY_LABELS

    assert OVERLAY_LABELS["Delta"] == "Delta" and OVERLAY_LABELS["App"] == "App"
    assert OVERLAY_LABELS["Session PB"] != OVERLAY_LABELS["Best"]
