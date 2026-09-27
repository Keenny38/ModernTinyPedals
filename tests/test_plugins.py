"""Widget plugin loader tests"""

import json

from tinypedal.plugin_loader import (
    PLUGIN_BASE_DEFAULT,
    discover_plugins,
    load_plugin_defaults,
    load_plugin_widget,
)


def make_plugin(folder, name, widget_code, setting=None):
    path = folder / name
    path.mkdir(parents=True)
    (path / "setting.json").write_text(json.dumps(setting or {"font_color": "#FFFFFF"}), encoding="utf-8")
    (path / "widget.py").write_text(widget_code, encoding="utf-8")


def test_discover_and_defaults(tmp_path):
    make_plugin(tmp_path, "good", "Realtime = object")
    make_plugin(tmp_path, "Bad Name", "Realtime = object")  # invalid folder name
    (tmp_path / "incomplete").mkdir()  # missing files
    assert list(discover_plugins(str(tmp_path))) == ["plugin_good"]
    defaults = load_plugin_defaults(str(tmp_path))
    assert defaults["plugin_good"]["font_color"] == "#FFFFFF"
    assert defaults["plugin_good"]["position_x"] == PLUGIN_BASE_DEFAULT["position_x"]


def test_invalid_setting_json_skipped(tmp_path):
    make_plugin(tmp_path, "broken", "Realtime = object")
    (tmp_path / "broken" / "setting.json").write_text("[1, 2", encoding="utf-8")
    assert load_plugin_defaults(str(tmp_path)) == {}


def test_broken_widget_gets_placeholder(tmp_path):
    make_plugin(tmp_path, "crash", "raise RuntimeError('boom')")
    module = load_plugin_widget("tinypedal.widget", "plugin_crash", str(tmp_path))
    assert module.Realtime.__doc__ == "Plugin error"


def test_example_plugin_renders():
    """Bundled example plugin loads and renders"""
    import os

    from tinypedal.setting import cfg
    from tinypedal.userfile.json_setting import copy_setting
    from tinypedal.widget import plugin_example_speed

    cfg.default.set_default()
    backup = {name: getattr(cfg.user, name, None) for name in cfg.user.__slots__}
    for name in cfg.user.__slots__:
        setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)))
    try:
        from tinypedal.api_control import api
        api.connect()
        api.start()
        widget = plugin_example_speed.Realtime(cfg, "plugin_example_speed")
        widget.adjustSize()
        assert widget.width() > 10
        widget.deleteLater()
        api.stop()
    finally:
        for name, value in backup.items():
            if value is not None:
                setattr(cfg.user, name, value)
    assert os.path.exists("plugins/example_speed/widget.py")


def test_plugin_error_recorded_and_cleared(tmp_path):
    from tinypedal.plugin_loader import PLUGIN_ERRORS

    make_plugin(tmp_path, "flaky", "raise ValueError('bad value')")
    load_plugin_widget("tinypedal.widget", "plugin_flaky", str(tmp_path))
    assert "bad value" in PLUGIN_ERRORS["plugin_flaky"]
    (tmp_path / "flaky" / "widget.py").write_text("Realtime = object", encoding="utf-8")
    load_plugin_widget("tinypedal.widget", "plugin_flaky", str(tmp_path))
    assert "plugin_flaky" not in PLUGIN_ERRORS


def test_install_plugin_package(tmp_path):
    import zipfile

    import pytest

    from tinypedal.plugin_loader import install_plugin_package

    package = tmp_path / "plugin.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("my_gauge/widget.py", "Realtime = object")
        archive.writestr("my_gauge/setting.json", "{}")
        archive.writestr("my_gauge/../../evil.py", "x")  # path traversal, skipped
        archive.writestr("my_gauge/run.exe", "x")  # not allowed type, skipped
    folder = tmp_path / "plugins"
    assert install_plugin_package(str(package), str(folder)) == "plugin_my_gauge"
    assert sorted(path.name for path in (folder / "my_gauge").iterdir()) == ["setting.json", "widget.py"]
    assert not (tmp_path / "evil.py").exists()
    with pytest.raises(ValueError, match="already exists"):
        install_plugin_package(str(package), str(folder))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("a/widget.py", "")
        archive.writestr("b/setting.json", "")
    with pytest.raises(ValueError, match="single plugin folder"):
        install_plugin_package(str(bad), str(folder))


def test_plugin_manager(ui_env):
    from tinypedal.module_control import wctrl
    from tinypedal.ui.plugin_manager import PluginManager, reload_plugin

    manager = PluginManager(None)
    try:
        assert manager.table.rowCount() >= 1  # example plugin
        assert manager.table.item(0, 1).text() == "Loaded"
        name = manager.table.item(0, 0).data(0x0100)
        old_module = wctrl._module_pack[name]
        assert reload_plugin(name) == ""
        assert wctrl._module_pack[name] is not old_module  # code reloaded
    finally:
        manager.close()
