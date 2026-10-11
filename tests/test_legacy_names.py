"""Name of versions until 0.23.0: only read (plugins, presets, packages, VR layer registration)"""

import importlib
import json
import sys
import zipfile

from neopedal import plugin_loader, vr_shared
from neopedal.const_app import LEGACY_NAME, LEGACY_PACKAGE
from neopedal.setting_preupdate import preupdate_user_setting


def test_plugin_imports_legacy_package(monkeypatch):
    """Plugin of an older version imports app modules by the legacy package name: same module objects"""
    monkeypatch.setattr(sys, "meta_path", list(sys.meta_path))
    plugin_loader.install_legacy_package_finder()
    plugin_loader.install_legacy_package_finder()  # once
    assert sum(isinstance(finder, plugin_loader.LegacyPackageFinder) for finder in sys.meta_path) == 1
    try:
        legacy = importlib.import_module(f"{LEGACY_PACKAGE}.widget._base")
        import neopedal.widget._base as current

        assert legacy is current
    finally:
        for name in [name for name in sys.modules if name.split(".")[0] == LEGACY_PACKAGE]:
            del sys.modules[name]


def test_legacy_option_keys_renamed():
    legacy = {
        f"show_{LEGACY_PACKAGE}_performance": False,
        f"prefix_{LEGACY_PACKAGE}": "TP ",
        f"display_order_{LEGACY_PACKAGE}": 1,
        "show_system_performance": True,
    }
    user = {"system_performance": dict(legacy)}
    preupdate_user_setting((2, 50, 8), user)
    assert user["system_performance"] == {
        "show_neopedal_performance": False,
        "prefix_neopedal": "NP ",
        "display_order_neopedal": 1,
        "show_system_performance": True,
    }
    custom = {"system_performance": {f"prefix_{LEGACY_PACKAGE}": "APP "}}
    preupdate_user_setting((2, 50, 8), custom)
    assert custom["system_performance"] == {"prefix_neopedal": "APP "}  # own prefix kept
    current = {"system_performance": dict(legacy)}
    preupdate_user_setting((2, 50, 9), current)
    assert current["system_performance"] == legacy  # already current version: untouched


def test_legacy_preset_package_accepted(tmp_path):
    from neopedal.userfile.preset_package import read_manifest

    path = tmp_path / "old.zip"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("manifest.json", json.dumps({"format": f"{LEGACY_PACKAGE}-preset-package", "version": 1}))
    with zipfile.ZipFile(path) as package:
        assert read_manifest(package)["version"] == 1


def test_legacy_layer_registration_replaced():
    """OpenXR layer registered by an older version (other manifest name): replaced, never left loaded"""
    assert vr_shared.is_layer_entry(rf"C:\app\openxr_layer\1\{LEGACY_NAME}XrLayer.json")
    assert vr_shared.is_layer_entry(rf"C:\app\openxr_layer\1\{vr_shared.LAYER_MANIFEST}")
    assert not vr_shared.is_layer_entry(r"C:\other\OtherLayer.json")
