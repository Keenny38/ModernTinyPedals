"""Audit fixes: static layer cache on fractional screen scale, default API on Linux,
black box required modules, missing brand logo cache"""

from types import SimpleNamespace

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget

from tinypedal import api_connector, api_control
from tinypedal.const_api import API_LMU_NAME, API_LMULEGACY_NAME
from tinypedal.userfile import custom_image
from tinypedal.userfile.game_images import images
from tinypedal.widget._black_box import modules as bb_modules
from tinypedal.widget._painter import layer_fits


def layer(width, height, ratio):
    pixmap = QPixmap(max(round(width * ratio), 1), max(round(height * ratio), 1))
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def test_layer_fits_fractional_scale():
    widget = QWidget()
    widget.resize(101, 51)
    for ratio in (1.0, 1.25, 1.5, 1.75, 2.0):
        cached = layer(101, 51, ratio)
        assert layer_fits(cached, 101, 51, ratio)
        assert not layer_fits(cached, 101, 51, ratio + 0.25)  # screen scale changed
    # 125%: device independent size 100.8 x 51.2, old check rebuilt layer on every paint
    assert layer(101, 51, 1.25).deviceIndependentSize() != widget.size()
    assert not layer_fits(layer(100, 51, 1.25), 101, 51, 1.25)  # widget resized
    assert not layer_fits(None, 101, 51, 1.0)


def test_default_api_always_selectable(monkeypatch):
    monkeypatch.setattr(api_control, "API_DEFAULT_NAME", API_LMULEGACY_NAME)  # Linux default
    names = [_api.NAME for _api in api_control._set_available_api(False)]
    assert API_LMULEGACY_NAME in names
    monkeypatch.setattr(api_control, "API_DEFAULT_NAME", API_LMU_NAME)  # Windows default
    names = [_api.NAME for _api in api_control._set_available_api(False)]
    assert API_LMULEGACY_NAME not in names
    assert api_connector.SimLMULegacy in api_control._set_available_api(True)


def fake_mctrl(monkeypatch, starts):
    from tinypedal import module_control

    active = {}
    fake = SimpleNamespace(active_modules=active, start=lambda name: active.update({name: 1}) if starts else None)
    monkeypatch.setattr(module_control, "mctrl", fake)


def test_enable_modules_failed_start_left_off(monkeypatch):
    fake_mctrl(monkeypatch, starts=False)
    settings = {"module_wheels": {"enable": False}}
    saved = []
    assert bb_modules.enable_modules(["module_wheels"], settings, lambda: saved.append(1)) == []
    assert settings["module_wheels"]["enable"] is False
    assert not saved


def test_enable_modules_started(monkeypatch):
    fake_mctrl(monkeypatch, starts=True)
    settings = {"module_wheels": {"enable": False}}
    saved = []
    assert bb_modules.enable_modules(["module_wheels"], settings, lambda: saved.append(1)) == ["module_wheels"]
    assert settings["module_wheels"]["enable"] is True
    assert saved == [1]


def test_missing_brand_logo_looked_for_once_per_pictures_version(monkeypatch):
    calls = []

    def load(filepath, filename, max_width, max_height):
        calls.append(filename)
        return QPixmap()

    monkeypatch.setattr(custom_image, "load_brand_logo_image", load)
    monkeypatch.setattr(images, "version", 5)
    cache = {}
    for _ in range(3):
        assert custom_image.cached_brand_logo(cache, "", "Brand", 10, 10).isNull()
    assert calls == ["Brand"]
    monkeypatch.setattr(images, "version", 6)  # new game pictures: looked for again
    custom_image.cached_brand_logo(cache, "", "Brand", 10, 10)
    assert calls == ["Brand", "Brand"]


def test_found_brand_logo_kept(monkeypatch):
    calls = []

    def load(filepath, filename, max_width, max_height):
        calls.append(filename)
        pixmap = QPixmap(4, 4)
        return pixmap

    monkeypatch.setattr(custom_image, "load_brand_logo_image", load)
    cache = {}
    first = custom_image.cached_brand_logo(cache, "", "Brand", 10, 10)
    monkeypatch.setattr(images, "version", images.version + 1)
    assert custom_image.cached_brand_logo(cache, "", "Brand", 10, 10) is first
    assert calls == ["Brand"]
