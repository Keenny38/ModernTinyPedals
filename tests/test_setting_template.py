"""Default setting templates: widget categories, display order, common options"""

import pkgutil
from importlib import import_module

import pytest

from tinypedal.plugin_loader import PLUGIN_PREFIX
from tinypedal.template.setting_widget import WIDGET_DEFAULT, WIDGET_FILENAME
from tinypedal.template.widget import WIDGET_CATEGORIES, WIDGET_DISPLAY_ORDER

WIDGET_MODULES = sorted(
    module.name
    for module in pkgutil.iter_modules(import_module("tinypedal.widget").__path__)
    if not module.name.startswith("_") and not module.name.startswith(PLUGIN_PREFIX)
)


def test_every_widget_module_has_default():
    """A widget without default setting cannot be configured or enabled"""
    assert set(WIDGET_MODULES) <= set(WIDGET_DEFAULT)


def test_no_default_without_widget_module():
    extra = [name for name in WIDGET_DISPLAY_ORDER if name not in WIDGET_MODULES]
    assert not extra, f"default setting without widget file: {extra}"


def test_display_order_matches_categories():
    """Every widget belongs to exactly one category and is listed once in display order"""
    categorized = [name for category in WIDGET_CATEGORIES for name in category]
    assert len(categorized) == len(set(categorized)), "widget in more than one category"
    assert sorted(categorized) == sorted(WIDGET_DISPLAY_ORDER)
    assert len(WIDGET_DISPLAY_ORDER) == len(set(WIDGET_DISPLAY_ORDER))


def test_widget_filename_follows_display_order():
    """UI widget list & keyboard shortcut names follow display order, plugins last"""
    listed = [name for name in WIDGET_FILENAME if not name.startswith(PLUGIN_PREFIX)]
    assert listed == list(WIDGET_DISPLAY_ORDER)


@pytest.mark.parametrize("name", sorted(WIDGET_DISPLAY_ORDER))
def test_common_options_present(name):
    setting = WIDGET_DEFAULT[name]
    assert isinstance(setting, dict)
    for key in ("enable", "update_interval", "position_x", "position_y", "opacity", "widget_theme"):
        assert key in setting, f"{name} missing {key}"
    assert setting["widget_theme"] == "Global"
    assert isinstance(setting["enable"], bool)
    assert setting["update_interval"] > 0
