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
    from tinypedal.i18n.options import load_data

    OPTIONS = load_data("fr_options.json")
    assert OPTIONS
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


def test_option_help_french(french):
    assert "signe degré" in option_help("brake_temperature", "show_degree_sign")
    assert "Définit" in option_help("speedometer", "speed_offset_x")
    assert "<i>show_degree_sign</i>" in option_tooltip("brake_temperature", "show_degree_sign")


def test_every_option_help_is_translated():
    from tinypedal.i18n.options import _help, load_data

    helps, _ = _help()
    translations = load_data("fr_option_help.json")
    missing = {text for section in helps.values() for text in section.values()} - set(translations)
    assert not missing, f"{len(missing)} option help texts without French translation"
    assert all(value.strip() for value in translations.values())


def test_untranslated_help_falls_back_to_english(french, monkeypatch):
    from tinypedal.i18n import options

    monkeypatch.setattr(options, "_help_translations", lambda code: {})
    assert "degree sign" in option_help("brake_temperature", "show_degree_sign")

def test_missing_i18n_data_falls_back(monkeypatch, tmp_path):
    from tinypedal.i18n import options

    monkeypatch.setattr(options, "DATA_PATH", str(tmp_path))
    assert options.load_data("fr_options.json") == {}
    (tmp_path / "broken.json").write_text("[1", encoding="utf-8")
    assert options.load_data("broken.json") == {}
    (tmp_path / "list.json").write_text("[1]", encoding="utf-8")
    assert options.load_data("list.json") == {}


# --- Unit hints: numeric options are stored in a base unit, the editor shows the display unit
def test_unit_hint_converts_to_display_unit():
    from tinypedal.ui._option import unit_hint

    units = {"temperature_unit": "Fahrenheit", "tyre_pressure_unit": "psi"}
    assert unit_hint("tyre_pressure_target_minimum", "160", units) == "23.21 psi"
    assert unit_hint("tyre_temperature_warning_threshold", "160", units) == "320 °F"
    # "temperature" wins over "pressure": this option is a temperature
    assert unit_hint("hot_pressure_temperature_threshold", "160", units).endswith("°F")


def test_unit_hint_stays_silent_when_it_would_mislead():
    from tinypedal.ui._option import unit_hint

    units = {"temperature_unit": "Fahrenheit", "tyre_pressure_unit": "psi"}
    assert unit_hint("font_size", "160", units) == ""  # carries no unit
    assert unit_hint("tyre_wear_warning_threshold", "30", units) == ""  # a percentage
    # Speed options are stored in km/h in some widgets and m/s in others, so never hinted
    assert unit_hint("slip_warning_minimum_speed", "10", units) == ""
    assert unit_hint("tyre_pressure_target_minimum", "abc", units) == ""  # mid-edit
    # Nothing to convert when the user already types in the unit they read
    assert unit_hint("tyre_pressure_target_minimum", "160", {"tyre_pressure_unit": "kPa"}) == ""


def test_unit_hint_pressure_target_typed_in_psi_or_bar():
    from tinypedal.ui._option import unit_hint

    # Pressure targets read kPa, psi or bar from the value: the hint confirms how it is read
    assert unit_hint("tyre_pressure_target_minimum", "23", {"tyre_pressure_unit": "psi"}) == "23 psi"
    assert unit_hint("tyre_pressure_target_minimum", "1.6", {"tyre_pressure_unit": "psi"}) == "23.21 psi"
    assert unit_hint("tyre_pressure_target_minimum", "23", {"tyre_pressure_unit": "kPa"}) == "158.6 kPa"
    assert unit_hint("tyre_pressure_target_minimum", "160", {"tyre_pressure_unit": "bar"}) == "1.6 bar"
