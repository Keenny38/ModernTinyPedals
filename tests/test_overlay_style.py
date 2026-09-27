"""Modern overlay style tests"""

from tinypedal.widget._style import StyledConfig, modern_overrides, remap_color

STYLE = {
    "enable_modern_style": True,
    "overlay_theme": "Modern Dark",
    "enable_modern_font": True,
    "modern_font_name": "Bahnschrift",
    "corner_radius_scale": 0.2,
    "minimum_bar_gap": 2,
}


def test_remap_color():
    assert remap_color("#222222") == "#1B1F27"
    assert remap_color("#ffffff") == "#F4F6F9"
    assert remap_color("#88444444") == "#88373E4C"  # keep alpha
    assert remap_color("#123456") == "#123456"  # not in palette
    assert remap_color("#FFF") == "#FFF"  # short form untouched
    assert remap_color("") == ""


def test_only_default_values_are_restyled():
    default = {
        "font_name": "Consolas",
        "bar_gap": 0,
        "font_color": "#FFFFFF",
        "bkg_color": "#222222",
        "position_x": 0,
    }
    user = dict(default, font_color="#FF0000", position_x=100)
    overrides = modern_overrides(user, default, STYLE)
    assert overrides == {
        "font_name": "Bahnschrift",
        "bar_gap": 2,
        "bkg_color": "#1B1F27",
    }


def test_custom_font_and_gap_kept():
    default = {"font_name": "Consolas", "bar_gap": 0}
    user = {"font_name": "Arial", "bar_gap": 5}
    assert modern_overrides(user, default, STYLE) == {}


def test_disabled_options():
    default = {"font_name": "Consolas", "font_color": "#FFFFFF"}
    style = dict(STYLE, overlay_theme="Classic", enable_modern_font=False)
    assert modern_overrides(dict(default), default, style) == {}


def test_styled_config_writes_through():
    source = {"font_color": "#FFFFFF", "position_x": 0}
    styled = StyledConfig(source, {"font_color": "#F4F6F9"})
    assert styled["font_color"] == "#F4F6F9"
    styled["position_x"] = 42
    assert source["position_x"] == 42
    assert source["font_color"] == "#FFFFFF"  # override never saved


def test_theme_palettes():
    from tinypedal.widget._style import OVERLAY_THEMES, overlay_theme_names

    assert overlay_theme_names()[:len(OVERLAY_THEMES)] == tuple(OVERLAY_THEMES)
    default = {"font_color": "#FF2200"}
    for theme, expected in (
        ("Modern Dark", "#FF4D4F"),
        ("High Contrast", "#FF3B3B"),
        ("Colorblind Safe", "#D55E00"),
    ):
        style = dict(STYLE, overlay_theme=theme)
        assert modern_overrides(dict(default), default, style) == {"font_color": expected}
    assert modern_overrides(dict(default), default, dict(STYLE, overlay_theme="Classic")) == {}
