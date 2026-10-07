"""Third audit pass: data modules, presets & replay fixes"""

import json
import zipfile

import pytest

from tinypedal.setting import cfg


# Heatmap style with invalid content (edited by hand, imported from a package)
@pytest.mark.parametrize("heatmap", [
    {"abc": "#FF0000", "100": "#00FF00"},  # temperature not a number
    ["#FF0000"],  # not a dict
    {"50": 12},  # color not a text
])
def test_invalid_heatmap_falls_back_to_default(monkeypatch, heatmap):
    from tinypedal.template.setting_heatmap import HEATMAP_DEFAULT, HEATMAP_DEFAULT_TYRE
    from tinypedal.userfile.heatmap import load_heatmap_color, verify_heatmap

    assert not verify_heatmap(heatmap)
    monkeypatch.setattr(cfg.default, "heatmap", HEATMAP_DEFAULT, raising=False)
    styles = {name: dict(value) for name, value in HEATMAP_DEFAULT.items()}
    styles["broken"] = heatmap
    monkeypatch.setattr(cfg.user, "heatmap", styles, raising=False)
    monkeypatch.setattr(cfg.user, "config", {**getattr(cfg.user, "config", {}), "overlay_style": {}}, raising=False)
    colors = load_heatmap_color("broken", HEATMAP_DEFAULT_TYRE, fg_color="#000000")
    default = load_heatmap_color(HEATMAP_DEFAULT_TYRE, HEATMAP_DEFAULT_TYRE, fg_color="#000000")
    assert colors == default


def test_valid_heatmap_accepted():
    from tinypedal.userfile.heatmap import verify_heatmap

    assert verify_heatmap({"-10": "#FFFFFF", "25.5": "#000"})


# Preset package with manifest version of wrong type
@pytest.mark.parametrize("version", ["2", None, [1], True])
def test_package_manifest_version_wrong_type_is_invalid(tmp_path, version):
    from tinypedal.userfile.preset_package import PACKAGE_FORMAT, import_preset_package

    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w") as file:
        file.writestr("manifest.json", json.dumps({"format": PACKAGE_FORMAT, "version": version}))
        file.writestr("presets/shared.json", "{}")
    target = tmp_path / "settings"
    target.mkdir()
    with pytest.raises(ValueError):
        import_preset_package(str(package), f"{target.as_posix()}/")
    assert not list(target.iterdir())


# Car setup backup file name: lap time rounded to milliseconds before split
@pytest.mark.parametrize(("seconds", "text"), [
    (119.9996, "2-00-000"),
    (83.99973, "1-24-000"),
    (59.9999, "1-00-000"),
    (83.456, "1-23-456"),
    (float("inf"), "0-00-000"),
])
def test_car_setup_laptime_never_shows_1000_milliseconds(seconds, text):
    from tinypedal.userfile.car_setup import set_car_setup_laptime

    assert set_car_setup_laptime(seconds) == text
