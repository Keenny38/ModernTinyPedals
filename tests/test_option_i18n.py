"""Option labels & help tests"""

import pytest

from tinypedal.i18n import set_language
from tinypedal.i18n.options import module_label, option_help, option_label, option_tooltip, search_text


@pytest.fixture
def french():
    set_language("Français")
    yield
    set_language("English")


def test_english_labels():
    assert option_label("font_color_speed") == "Font Color Speed"
    assert module_label("module_delta") == "Delta"


def test_french_labels(french):
    assert option_label("font_color_speed") == "Couleur du texte : vitesse"
    assert option_label("show_brake_bias") == "Afficher la répartition de freinage"
    assert module_label("brake_temperature") == "Température des freins"
    assert option_label("unknown_new_option") == "Unknown New Option"  # fallback


def test_every_option_has_french_label():
    """New options must be added by running tools/gen_fr_options.py"""
    from tinypedal.i18n.fr_options import OPTIONS
    from tinypedal.setting import cfg

    cfg.default.set_default()
    missing = [
        key
        for name in ("config", "setting")
        for options in dict(getattr(cfg.default, name)).values()
        if isinstance(options, dict)
        for key in options
        if key not in OPTIONS
    ]
    assert not missing, f"run tools/gen_fr_options.py, missing: {missing[:10]}"


def test_search_matches_both_languages(french):
    text = search_text("brake_bias")
    assert "répartition" in text and "brake bias" in text and "brake_bias" in text


def test_option_help():
    assert "degree sign" in option_help("brake_temperature", "show_degree_sign")
    assert option_help("speedometer", "position_x")  # common term
    assert option_help("speedometer", "speed_offset_x")  # wildcard *_offset_x
    assert option_help("speedometer", "font_color_speed")  # generic "color"
    assert option_help("speedometer", "no_such_option") == ""
    assert "<i>no_such_option</i>" in option_tooltip("speedometer", "no_such_option")
