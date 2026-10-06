"""Smoke tests for Qt6 GUI (headless)"""

import importlib
import pkgutil

import pytest


def _iter_modules(package_name: str):
    package = importlib.import_module(package_name)
    for module in pkgutil.iter_modules(package.__path__):
        yield f"{package_name}.{module.name}"


@pytest.mark.parametrize("module_name", [
    *_iter_modules("tinypedal.ui"),
    *_iter_modules("tinypedal.widget"),
])
def test_import_module(module_name):
    """All UI & widget modules import without error under PySide6"""
    importlib.import_module(module_name)


@pytest.mark.parametrize("theme", ["Modern Dark", "Modern Light", "Legacy Dark", "Legacy Light"])
def test_window_style(theme):
    """Palette & style sheet can be generated for each theme"""
    from PySide6.QtWidgets import QApplication

    from tinypedal.ui import set_style_palette, set_style_window

    set_style_palette(theme)
    style = set_style_window(QApplication.font().pointSize())
    assert "QPushButton" in style


def test_about_dialog():
    """About dialog can be created"""
    from tinypedal.ui.about import About

    dialog = About(None)
    dialog.close()
