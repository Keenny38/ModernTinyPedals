"""Widget plugin loader tests"""

import json

import pytest

from tinypedal import plugin_loader
from tinypedal.plugin_loader import (
    BUNDLED_PLUGINS,
    PLUGIN_BASE_DEFAULT,
    PLUGIN_ERRORS,
    UNTRUSTED_ERROR,
    discover_plugins,
    is_trusted,
    load_plugin_defaults,
    load_plugin_widget,
    plugin_digest,
    trust_plugin,
)


@pytest.fixture(autouse=True)
def trust_file(monkeypatch, tmp_path):
    """Trusted plugin digests in tmp folder"""
    filename = tmp_path / "plugin_trust.json"
    monkeypatch.setattr(plugin_loader, "trust_filename", lambda: str(filename))
    return filename


def make_plugin(folder, name, widget_code, setting=None, trusted=True):
    path = folder / name
    path.mkdir(parents=True)
    (path / "setting.json").write_text(json.dumps(setting or {"font_color": "#FFFFFF"}), encoding="utf-8")
    (path / "widget.py").write_text(widget_code, encoding="utf-8")
    if trusted:
        trust_plugin(f"plugin_{name}", str(folder))


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
    trust_plugin("plugin_flaky", str(tmp_path))  # code changed, trust again
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
        from PySide6.QtCore import QCoreApplication, QEvent

        manager.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # singleton freed for next tests


def test_untrusted_plugin_not_executed(tmp_path):
    marker = tmp_path / "executed.txt"
    make_plugin(tmp_path, "sneaky", f"open({str(marker)!r}, 'w').close()\nRealtime = object", trusted=False)
    module = load_plugin_widget("tinypedal.widget", "plugin_sneaky", str(tmp_path))
    assert not marker.exists()  # code never ran
    assert module.Realtime.__doc__ == "Plugin error"
    assert PLUGIN_ERRORS["plugin_sneaky"] == UNTRUSTED_ERROR
    trust_plugin("plugin_sneaky", str(tmp_path))
    load_plugin_widget("tinypedal.widget", "plugin_sneaky", str(tmp_path))
    assert marker.exists() and "plugin_sneaky" not in PLUGIN_ERRORS


def test_code_change_revokes_trust(tmp_path, trust_file):
    make_plugin(tmp_path, "gauge", "Realtime = object")
    assert is_trusted("plugin_gauge", str(tmp_path))
    assert json.loads(trust_file.read_text(encoding="utf-8"))["plugin_gauge"] == plugin_digest(str(tmp_path / "gauge"))
    (tmp_path / "gauge" / "helper.py").write_text("x = 1", encoding="utf-8")  # extra module counts too
    assert not is_trusted("plugin_gauge", str(tmp_path))
    trust_plugin("plugin_gauge", str(tmp_path))
    (tmp_path / "gauge" / "widget.py").write_text("Realtime = int", encoding="utf-8")
    assert not is_trusted("plugin_gauge", str(tmp_path))


def test_digest_ignores_line_endings_and_cache(tmp_path):
    make_plugin(tmp_path, "crlf", "a = 1\nRealtime = object\n", trusted=False)
    digest = plugin_digest(str(tmp_path / "crlf"))
    (tmp_path / "crlf" / "widget.py").write_bytes(b"a = 1\r\nRealtime = object\r\n")
    (tmp_path / "crlf" / "__pycache__").mkdir()
    (tmp_path / "crlf" / "__pycache__" / "junk.py").write_text("x", encoding="utf-8")
    (tmp_path / "crlf" / "setting.json").write_text("{}", encoding="utf-8")  # not code
    assert plugin_digest(str(tmp_path / "crlf")) == digest


def test_invalid_trust_file(tmp_path, trust_file):
    make_plugin(tmp_path, "gauge", "Realtime = object", trusted=False)
    trust_file.write_text("[broken", encoding="utf-8")
    assert not is_trusted("plugin_gauge", str(tmp_path))
    trust_plugin("plugin_gauge", str(tmp_path))  # rewrites invalid file
    assert is_trusted("plugin_gauge", str(tmp_path))


def test_bundled_plugin_digest_up_to_date():
    """Update BUNDLED_PLUGINS digest after editing a bundled plugin"""
    for widget_name, digest in BUNDLED_PLUGINS.items():
        assert plugin_digest(plugin_loader.plugin_path(widget_name)) == digest, widget_name


# --- Audit fixes
@pytest.mark.parametrize("member", [
    "evil/D:pwn.py",  # drive relative: D:\pwn.py on Windows
    "evil/C:/Users/pwn.py",
    "evil/sub/C:pwn.py",
    "evil//abs.py",
    "evil/sub/../../x.py",
    "evil/__pycache__/widget.cpython-314.pyc",
    "evil/CON.py",  # Windows device name
    "evil/aux.txt",
])
def test_install_rejects_files_outside_plugin_folder(tmp_path, member):
    import zipfile

    from tinypedal.plugin_loader import install_plugin_package

    package = tmp_path / "evil.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("evil/widget.py", "Realtime = object")
        archive.writestr("evil/setting.json", "{}")
        archive.writestr(member, "x")
    folder = tmp_path / "plugins"
    folder.mkdir()
    assert install_plugin_package(str(package), str(folder)) == "plugin_evil"
    installed = sorted(str(path.relative_to(folder)).replace("\\", "/") for path in folder.rglob("*"))
    assert installed == ["evil", "evil/setting.json", "evil/widget.py"]
    assert not (tmp_path / "pwn.py").exists() and not (tmp_path / "x.py").exists()


def test_install_keeps_safe_sub_folder(tmp_path):
    import zipfile

    from tinypedal.plugin_loader import install_plugin_package, is_safe_package_path

    package = tmp_path / "good.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("good/widget.py", "Realtime = object")
        archive.writestr("good/setting.json", "{}")
        archive.writestr("good/images/icon.png", "png")
    install_plugin_package(str(package), str(tmp_path))
    assert (tmp_path / "good" / "images" / "icon.png").exists()
    assert is_safe_package_path(["images", "icon.png"])
    assert not is_safe_package_path(["images", "icon.png."])


def test_inside_folder_check(tmp_path):
    import os

    from tinypedal.plugin_loader import is_inside_folder

    folder = os.path.realpath(tmp_path / "plugin")
    assert is_inside_folder(str(tmp_path / "plugin" / "a" / "b.py"), folder)
    assert not is_inside_folder(str(tmp_path / "other.py"), folder)
    if os.name == "nt":
        other_drive = "Z:\\pwn.py" if not folder.upper().startswith("Z:") else "Y:\\pwn.py"
        assert not is_inside_folder(other_drive, folder)  # different drive: never inside


def test_compiled_bytecode_never_runs_instead_of_source(tmp_path):
    """A shipped unchecked-hash .pyc (not covered by digest) must not replace reviewed source"""
    import importlib.util
    import py_compile

    make_plugin(tmp_path, "sneaky", "SOURCE = 'reviewed'\nRealtime = object")
    widget = tmp_path / "sneaky" / "widget.py"
    evil = tmp_path / "evil.py"
    evil.write_text("SOURCE = 'bytecode'\nRealtime = object", encoding="utf-8")
    cached = importlib.util.cache_from_source(str(widget))
    py_compile.compile(str(evil), cfile=cached, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    assert is_trusted("plugin_sneaky", str(tmp_path))  # digest covers .py files only
    module = load_plugin_widget("tinypedal.widget", "plugin_sneaky", str(tmp_path))
    assert module.SOURCE == "reviewed"
    assert not (tmp_path / "sneaky" / "__pycache__").exists()  # compiled files removed


def test_plugin_setting_values_type_checked(tmp_path):
    setting = {"enable": True, "update_interval": "x", "opacity": "high", "position_x": 1.5,
               "font_size": 20, "bar_padding": 1, "my_color": "#FF0000", "my_scale": 2.5, "my_list": [1, "a"],
               "my_dict": {"a": 1}, "my_none": None, "my_nan": float("nan"), "font_name": 5}
    (tmp_path / "typed").mkdir()
    (tmp_path / "typed" / "widget.py").write_text("Realtime = object", encoding="utf-8")
    (tmp_path / "typed" / "setting.json").write_text(json.dumps(setting), encoding="utf-8")
    defaults = load_plugin_defaults(str(tmp_path))["plugin_typed"]
    for key in ("update_interval", "opacity", "position_x", "font_name"):
        assert defaults[key] == PLUGIN_BASE_DEFAULT[key], key
    assert defaults["enable"] is True and defaults["font_size"] == 20 and defaults["bar_padding"] == 1
    assert defaults["my_color"] == "#FF0000" and defaults["my_scale"] == 2.5 and defaults["my_list"] == [1, "a"]
    assert not {"my_dict", "my_none", "my_nan"} & set(defaults)


@pytest.fixture
def fake_widgets(ui_env, monkeypatch):
    """Module control of fake plugin widgets: name: Realtime class"""
    from types import SimpleNamespace

    from tinypedal.const_file import ConfigType
    from tinypedal.module_control import ModuleControl
    from tinypedal.setting import cfg

    def control(**classes):
        for name in classes:
            monkeypatch.setitem(cfg.user.setting, name, {"enable": True})
            PLUGIN_ERRORS.pop(name, None)
        target = SimpleNamespace(__all__=list(classes), **{
            name: SimpleNamespace(Realtime=realtime) for name, realtime in classes.items()})
        return ModuleControl(target, ConfigType.WIDGET)

    return control


class FakeWidget:
    """Widget that starts & closes"""

    def __init__(self, config, name):
        self.closed = True
        self.stop_args = None

    def start(self):
        self.closed = False

    def stop(self, *args, **kwargs):
        self.stop_args = (args, kwargs)
        self.closed = True


def test_plugin_widget_crash_does_not_stop_app_start(fake_widgets):
    class CrashInit(FakeWidget):
        def __init__(self, config, name):
            raise RuntimeError("boom in init")

    class CrashStart(FakeWidget):
        def start(self):
            raise ValueError("boom in start")

    control = fake_widgets(plugin_crash_init=CrashInit, plugin_crash_start=CrashStart, plugin_good=FakeWidget)
    control.start()  # never raises
    assert list(control.active_modules) == ["plugin_good"]
    assert "boom in init" in PLUGIN_ERRORS["plugin_crash_init"]
    assert "boom in start" in PLUGIN_ERRORS["plugin_crash_start"]
    control.close()
    assert not control.active_modules


def test_stuck_module_does_not_hang_close(fake_widgets, monkeypatch):
    from tinypedal import thread_guard

    class Stuck(FakeWidget):
        def stop(self, *args, **kwargs):
            pass  # never reports closed

    monkeypatch.setattr(thread_guard, "STOP_TIMEOUT", 0.05)
    control = fake_widgets(plugin_stuck=Stuck)
    control.start()
    control.close()  # gives up after timeout
    assert not control.active_modules


def test_module_reload_discard_reaches_data_modules(ui_env, monkeypatch):
    from types import SimpleNamespace

    from tinypedal.const_file import ConfigType
    from tinypedal.module_control import ModuleControl
    from tinypedal.setting import cfg

    monkeypatch.setitem(cfg.user.setting, "module_fake", {"enable": True})
    created = []

    class Module(FakeWidget):
        def __init__(self, config, name):
            super().__init__(config, name)
            created.append(self)

    control = ModuleControl(SimpleNamespace(__all__=["module_fake"], module_fake=SimpleNamespace(Realtime=Module)),
                            ConfigType.MODULE)
    control.start()
    control.reload("module_fake", discard=True)  # data reset: unsaved data discarded
    control.reload("module_fake")
    assert created[0].stop_args == ((), {"discard": True})
    assert created[1].stop_args == ((), {})