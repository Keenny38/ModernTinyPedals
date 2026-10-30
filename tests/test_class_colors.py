"""Endurance class colors: Hypercar red, GT3 green, GTE orange, former default colors updated once"""

from neopedal.setting_preupdate import PENDING_STYLE_UPDATES, preupdate_global_setting
from neopedal.setting_validator import StyleValidator, update_former_class_colors
from neopedal.template.setting_classes import CLASS_COLORS, CLASSES_DEFAULT, FORMER_DEFAULT_COLORS


def test_default_class_colors():
    assert CLASSES_DEFAULT["Hypercar"]["color"] == CLASSES_DEFAULT["Hyper"]["color"] == "#E21E19"
    assert CLASSES_DEFAULT["GT3"]["color"] == CLASSES_DEFAULT["LMGT3"]["color"] == "#009639"
    assert CLASSES_DEFAULT["GTE"]["color"] == "#F08C00"
    assert set(FORMER_DEFAULT_COLORS) <= set(CLASS_COLORS)


def test_former_colors_updated_chosen_kept():
    classes = {
        "Hypercar": {"alias": "HY", "color": "#ff4400", "preset": ""},  # former default (any case)
        "GT3": {"alias": "GT3", "color": "#123456", "preset": ""},  # chosen color kept
        "GTE": {"alias": "GTE", "color": "#00CC44", "preset": ""},
        "LMP2": {"alias": "LMP2", "color": "#0088FF", "preset": ""},  # other class untouched
    }
    assert update_former_class_colors(classes)
    assert [data["color"] for data in classes.values()] == ["#E21E19", "#123456", "#F08C00", "#0088FF"]
    assert not update_former_class_colors(classes)  # nothing left to update


def test_class_colors_update_once_from_older_setting():
    PENDING_STYLE_UPDATES.discard("class_colors")
    preupdate_global_setting((2, 51, 5), {})
    classes = {"Hypercar": {"alias": "HY", "color": "#FF4400", "preset": ""}}
    try:
        assert StyleValidator.classes(classes)
        assert classes["Hypercar"]["color"] == "#E21E19"
        classes["Hypercar"]["color"] = "#FF4400"  # chosen again after the update: kept
        assert not StyleValidator.classes(classes)
        assert classes["Hypercar"]["color"] == "#FF4400"
    finally:
        PENDING_STYLE_UPDATES.discard("class_colors")
