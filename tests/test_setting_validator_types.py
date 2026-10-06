"""Every default option is validated by the validator of its own type

A key matched by the wrong pattern (string option checked as number or boolean)
is reset to default on every load, ex. stream overlay access token renewed on each start.
"""

import copy

import pytest

from tinypedal.setting_validator import PresetValidator
from tinypedal.template.setting_api import API_DEFAULT
from tinypedal.template.setting_common import COMMON_DEFAULT
from tinypedal.template.setting_global import GLOBAL_DEFAULT
from tinypedal.template.setting_module import MODULE_DEFAULT
from tinypedal.template.setting_widget import WIDGET_DEFAULT

EXPECTED_VALIDATORS = {
    str: {"string", "color", "clock_format", "choice_units", "choice_common"},
    bool: {"boolean"},
    int: {"integer", "numeric"},
    float: {"numeric"},
}


def leaf_options(data: dict, path: tuple = ()):
    for key, value in data.items():
        if isinstance(value, dict):
            yield from leaf_options(value, (*path, key))
        else:
            yield "/".join((*path, key)), key, value


def claiming_validator(key: str, value) -> str | None:
    for validator in PresetValidator._value_validators:
        if validator(key, {key: value}):
            return validator.__name__
    return None


@pytest.mark.parametrize("name, defaults", [
    ("global", GLOBAL_DEFAULT),
    ("common", COMMON_DEFAULT),
    ("module", MODULE_DEFAULT),
    ("widget", WIDGET_DEFAULT),
    ("api", API_DEFAULT),
])
def test_default_options_checked_by_own_type(name, defaults):
    wrong = [
        (path, type(value).__name__, claiming_validator(key, value))
        for path, key, value in leaf_options(defaults, (name,))
        if claiming_validator(key, value) not in EXPECTED_VALIDATORS.get(type(value), ())
    ]
    assert not wrong


def test_text_options_kept_by_global_validator():
    user = copy.deepcopy(GLOBAL_DEFAULT)
    user["stream_overlay"]["access_token"] = "token123"
    user["web_dashboard"]["access_code"] = "4321"
    user["fuel_calculator"]["collapsed_sections"] = "fuel,energy"
    user["driver_stats_viewer"]["hidden_columns"] = "win_rate"
    user["driver_stats_viewer"]["column_widths"] = "name:120,laps:60"
    result = PresetValidator.global_preset(user, GLOBAL_DEFAULT)
    assert result["stream_overlay"]["access_token"] == "token123"
    assert result["web_dashboard"]["access_code"] == "4321"
    assert result["fuel_calculator"]["collapsed_sections"] == "fuel,energy"
    assert result["driver_stats_viewer"]["hidden_columns"] == "win_rate"
    assert result["driver_stats_viewer"]["column_widths"] == "name:120,laps:60"


def test_dict_in_place_of_value_restored_to_default():
    """"font_size": {} reset, not kept as sub-level dict (widget TypeError)"""
    defaults = {"font_size": 15, "sub": {"a": 1}}
    user = {"font_size": {}, "sub": {"a": 2}}
    PresetValidator.remove_invalid_key(user, defaults)
    PresetValidator.add_missing_key(user, defaults)
    assert user == {"font_size": 15, "sub": {"a": 2}}


def test_port_out_of_range_reset():
    user = copy.deepcopy(GLOBAL_DEFAULT)
    user["remote_control"]["remote_control_port"] = 70000
    user["web_dashboard"]["web_dashboard_port"] = -1
    user["stream_overlay"]["stream_overlay_port"] = 8400
    result = PresetValidator.global_preset(user, GLOBAL_DEFAULT)
    assert result["remote_control"]["remote_control_port"] == GLOBAL_DEFAULT["remote_control"]["remote_control_port"]
    assert result["web_dashboard"]["web_dashboard_port"] == GLOBAL_DEFAULT["web_dashboard"]["web_dashboard_port"]
    assert result["stream_overlay"]["stream_overlay_port"] == 8400


def test_style_int_accepted_in_float_field():
    """tracks.json "pit_speed": 60 kept as 60.0, not reset"""
    from tinypedal.setting_validator import _validate_style

    user = {"Track": {"pit_speed": 60, "flag": True}, "Other": {"pit_speed": True, "flag": False}}
    _validate_style(user, {}, {"pit_speed": 0.0, "flag": False})
    assert user["Track"]["pit_speed"] == 60.0 and isinstance(user["Track"]["pit_speed"], float)
    assert user["Other"]["pit_speed"] == 0.0  # bool is not a number
