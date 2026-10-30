"""Same status colors, class badges, gap texts & short names on overlays, app pages & stream graphics"""

import pytest

from neopedal.setting import cfg


@pytest.fixture
def themed(ui_env):
    from neopedal.ui import set_style_palette

    yield set_style_palette
    set_style_palette("Modern Dark")


def test_status_palette_shared_by_every_surface(themed):
    from neopedal.stream_director import director_html
    from neopedal.stream_overlay import results_html
    from neopedal.template.setting_status_colors import STATUS_COLORS, status_css
    from neopedal.ui.quick import Theme
    from neopedal.web_dashboard import dashboard_html
    from neopedal.widget._modern.theme import build_theme

    themed("Modern Dark")
    app = Theme()
    for role, getter in (("purple", app.purple), ("gain", app.gain), ("loss", app.loss), ("warning", app.warning),
                         ("gold", app.gold)):
        assert getter.name().upper() == STATUS_COLORS[role][0], role
    style = dict(cfg.default.config["overlay_style"], overlay_theme="Modern Dark", enable_colorblind_colors=False)
    overlay = build_theme(style)
    assert overlay.best.name().upper() == STATUS_COLORS["purple"][0]
    assert overlay.positive.name().upper() == STATUS_COLORS["gain"][0]
    assert overlay.negative.name().upper() == STATUS_COLORS["loss"][0]
    assert overlay.orange.name().upper() == STATUS_COLORS["warning"][0]
    assert overlay.warning.name().upper() == STATUS_COLORS["warning"][0]  # one warning color
    assert overlay.caution.name().upper() == STATUS_COLORS["gold"][0]
    assert overlay.accent.name().upper() == STATUS_COLORS["player"][0]
    css = status_css()
    assert "--purple:#c084fc;" in css and "--warn:#fb923c;" in css and "--player:#38bdf8;" in css
    for page in (director_html("en", "x"), results_html()):
        assert css in page and "@@" not in page
    page = dashboard_html()
    assert "--green:#4ade80;" in page and "--yellow:#facc15;" in page and "@@status" not in page


def test_pit_finish_penalty_meanings():
    from neopedal.penalty_info import Penalty
    from neopedal.widget._modern.rows import pit_cell
    from neopedal.widget._modern.theme import build_theme

    theme = build_theme(cfg.default.config["overlay_style"])
    assert pit_cell(theme, 1, False, False).fill == theme.orange  # pit: orange everywhere
    assert pit_cell(theme, 0, False, True).fill == theme.positive  # finished: green everywhere
    assert pit_cell(theme, 2, False, False).fill == theme.surface_strong  # garage: gray

    from neopedal.widget._modern.rows import RowStyle

    style = RowStyle.__new__(RowStyle)
    style.theme, style.wcfg = theme, {}
    assert style.pitstop_cell(-1, False, Penalty(pending=1, kind="Drive Thru")).fill == theme.negative  # red, not purple


def test_tower_state_and_energy_tone():
    from types import SimpleNamespace

    from neopedal.template.setting_status_colors import energy_tone
    from neopedal.ui.quick.director_graphics import tower_state

    car = SimpleNamespace(finish="", garage=False, in_pit=False)
    assert tower_state(car) == ""
    assert tower_state(SimpleNamespace(finish="", garage=True, in_pit=True)) == "garage"
    assert tower_state(SimpleNamespace(finish="", garage=False, in_pit=True)) == "pit"
    assert tower_state(SimpleNamespace(finish="FSTAT_DNF", garage=False, in_pit=False)) == "dnf"
    assert tower_state(SimpleNamespace(finish="FSTAT_DQ", garage=True, in_pit=False)) == "dq"
    assert [energy_tone(value) for value in (0.05, 0.1, 0.2, 0.3, 0.8)] == ["loss", "loss", "warning", "warning", "gain"]


def test_class_style_shared():
    from neopedal.formatter import class_alias, class_color, class_style, random_color_class
    from neopedal.widget._modern.rows import class_style as overlay_class_style
    from neopedal.widget._modern.theme import build_theme

    classes = {"Hypercar": {"alias": "HY", "color": "#FF0000"}, "GT3": {"color": "#00FF00"}, "Odd": "text"}
    assert class_style("Hypercar", classes) == ("HY", "#FF0000")
    assert class_style("GT3", classes) == ("GT3", "#00FF00")  # alias missing: name (was a KeyError on overlays)
    assert class_style("Odd", classes) == ("Odd", random_color_class("Odd"))
    assert class_color("LMP2", {}) == random_color_class("LMP2") and class_alias("", {}) == ""

    class Config:
        class user:
            pass

    Config.user.classes = classes
    theme = build_theme(cfg.default.config["overlay_style"])
    alias, color = overlay_class_style(Config, "GT3", theme)
    assert alias == "GT3" and color.name().upper() == "#00FF00"


@pytest.mark.parametrize(("name", "short"), [
    ("Lena Hartmann", "L. Hartmann"), ("Tobias Mueller#7949", "T. Mueller"), ("Senna", "Senna"),
    ("Jan van Dijk", "J. van Dijk"), ("Ron McLaren", "R. McLaren"), ("", ""),
])
def test_short_name_shared(name, short):
    from neopedal.formatter import driver_display_name, shorten_driver_name
    from neopedal.ui.quick.director_shared import short_name

    assert shorten_driver_name(name) == short_name(name) == short
    assert driver_display_name("Tobias Mueller#7949") == "Tobias Mueller"


def test_gap_texts_shared():
    from neopedal import i18n
    from neopedal.process.results_text import gap_seconds_text, laps_behind_text

    assert laps_behind_text(1) == "+1 lap" and laps_behind_text(3) == "+3 laps"
    assert gap_seconds_text(2.3456) == "+2.346" and gap_seconds_text(0.64, 1) == "+0.6"
    assert gap_seconds_text(62.3456) == "+1:02.346"
    i18n.set_language("Français")
    try:
        assert gap_seconds_text(2.3456) == "+2,346" and laps_behind_text(2) == "+2 tours"
    finally:
        i18n.set_language("English")


def test_laptime_formatters_same():
    from neopedal import calculation as calc
    from neopedal.race_live_data import laptime_text as live_text
    from neopedal.ui.quick.race_model import laptime_text as model_text

    for seconds in (59.9996, 83.4567, 0.0, -1.0, 3599.9999):
        assert live_text(seconds) == model_text(seconds) == calc.sec2laptime_full(max(seconds, 0.0))
