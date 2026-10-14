"""Tyre compound colors: one palette for overlays & app pages, former default colors updated once"""

import pytest

from neopedal.template.setting_compounds import (
    COMPOUND_COLORS,
    COMPOUNDS_DEFAULT,
    FORMER_DEFAULT_COLORS,
    UNKNOWN_COMPOUND_COLOR,
    name_color,
)


@pytest.mark.parametrize(("name", "color"), [
    ("Hyper - Soft", "#EDEDED"),
    ("LMP2 - Medium", "#F5C518"),
    ("GTE - Hard", "#E5484D"),
    ("GT3 - Wet", "#3E8EF7"),
    ("Rain", "#3E8EF7"),
    ("Intermediate", "#30A46C"),
    ("Supersoft", "#F43F5E"),
    ("Formula - Dry", UNKNOWN_COMPOUND_COLOR),  # only dry compound: no soft / hard meaning
    ("Bias Ply", UNKNOWN_COMPOUND_COLOR),
    ("Prime", UNKNOWN_COMPOUND_COLOR),
])
def test_name_color(name, color):
    assert name_color(name) == color


def test_defaults_use_palette():
    """Default compounds presets: color of their name, same as app pages (dark background color)"""
    for name, data in COMPOUNDS_DEFAULT.items():
        assert data["color"] == name_color(name), name
    soft, _light = COMPOUND_COLORS["soft"]
    assert COMPOUNDS_DEFAULT["Hyper - Soft"]["color"] == soft


def test_app_pages_use_same_palette(ui_env):
    from neopedal.ui import set_style_palette
    from neopedal.ui.quick import Theme

    set_style_palette("Modern Dark")
    theme = Theme()
    for name in ("Hyper - Soft", "LMP2 - Medium", "GTE - Hard", "GT3 - Wet"):
        assert theme.compound(name.split(" - ")[1]).name().upper() == COMPOUNDS_DEFAULT[name]["color"]


def test_former_default_colors_updated_once():
    from neopedal import setting_preupdate
    from neopedal.setting_validator import StyleValidator

    user = {
        "Hyper - Soft": {"symbol": "S", "color": "#AAAAAA", "heatmap": "tyre_optimal_80"},  # former default
        "Hyper - Hard": {"symbol": "H", "color": "#ee2200", "heatmap": "tyre_optimal_100"},  # lower case too
        "GT3 - Medium": {"symbol": "M", "color": "#AAAAAA", "heatmap": "tyre_optimal_90"},  # added on the fly: gray
        "Hyper - Wet": {"symbol": "W", "color": "#123456", "heatmap": "tyre_optimal_50"},  # chosen: kept
        "Formula - Dry": {"symbol": "S", "color": "#AAAAAA", "heatmap": "tyre_optimal_80"},  # dry: stays gray
        "LMP2 - Medium": {"symbol": "M", "color": "#FFCC00", "heatmap": "tyre_optimal_90"},
    }
    setting_preupdate.PENDING_STYLE_UPDATES.discard("compound_colors")
    assert StyleValidator.compounds(user) is False  # no update pending: nothing changed
    assert user["Hyper - Soft"]["color"] == "#AAAAAA"

    setting_preupdate.preupdate_global_setting((2, 50, 9), {})
    assert "compound_colors" in setting_preupdate.PENDING_STYLE_UPDATES
    assert StyleValidator.compounds(user) is True  # saved, former file backed up
    assert "compound_colors" not in setting_preupdate.PENDING_STYLE_UPDATES  # once
    assert user["Hyper - Soft"]["color"] == "#EDEDED"  # soft white, hard red
    assert user["Hyper - Hard"]["color"] == "#E5484D"
    assert user["GT3 - Medium"]["color"] == "#F5C518"
    assert user["Hyper - Wet"]["color"] == "#123456"
    assert user["Formula - Dry"]["color"] == "#AAAAAA"
    assert user["LMP2 - Medium"]["color"] == "#F5C518"

    # Gray chosen again later: kept (update done once)
    user["Hyper - Soft"]["color"] = "#AAAAAA"
    assert StyleValidator.compounds(user) is False
    assert user["Hyper - Soft"]["color"] == "#AAAAAA"


def test_current_setting_version_has_no_pending_update():
    from neopedal import setting_preupdate, version
    from neopedal.version_check import parse_version_string

    setting_preupdate.PENDING_STYLE_UPDATES.clear()
    setting_preupdate.preupdate_global_setting(parse_version_string(version.SETTING_VERSION), {})
    assert not setting_preupdate.PENDING_STYLE_UPDATES


def test_former_defaults_cover_every_default_symbol():
    symbols = {data["symbol"] for data in COMPOUNDS_DEFAULT.values()}
    assert symbols <= set(FORMER_DEFAULT_COLORS)


def test_missing_compound_colored_by_name(ui_env, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.userfile import heatmap

    monkeypatch.setattr(cfg.user, "compounds", {})
    assert heatmap.select_compound_color("Hyper - Medium", text=False) == "#F5C518"
    assert cfg.user.compounds["Hyper - Medium"]["symbol"] == "M"
    assert heatmap.select_compound_color("Kart - Prime", text=False) == UNKNOWN_COMPOUND_COLOR
