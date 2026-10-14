"""Settings saving & JSON writing in one shot, no blocking wait on GUI thread (reload, module toggle)"""

import json
import os
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from neopedal import loader, module_control, setting, thread_guard
from neopedal.const_file import ConfigType
from neopedal.module_control import ModuleControl
from neopedal.setting import Setting, cfg
from neopedal.userfile import json_setting, write_json

DATA = {"b": [1, 2.5, None, True], "a": {"name": "Pé \"x\"", "list": []}, "c": "é中"}


def old_dump(path, data, newline=None, **kwargs):
    """Previous writing: json.dump to text file"""
    with open(path, "w", encoding="utf-8", newline=newline) as file:
        json.dump(data, file, **kwargs)


def read_bytes(path) -> bytes:
    with open(path, "rb") as file:
        return file.read()


# --- write_json
@pytest.mark.parametrize("kwargs", (
    {},
    {"separators": (",", ":")},
    {"indent": 1, "ensure_ascii": False},
    {"indent": 4, "sort_keys": True},
    {"indent": 2},
))
@pytest.mark.parametrize("newline", (None, "\n", ""))
def test_write_json_byte_identical_to_json_dump(tmp_path, kwargs, newline):
    old_dump(tmp_path / "old.json", DATA, newline, **kwargs)
    assert write_json(str(tmp_path / "new.json"), DATA, newline=newline, **kwargs)
    assert read_bytes(tmp_path / "new.json") == read_bytes(tmp_path / "old.json")
    assert sorted(os.listdir(tmp_path)) == ["new.json", "old.json"]  # no temporary file left


def test_write_json_verified_before_replacing(tmp_path, monkeypatch):
    target = tmp_path / "data.json"
    target.write_text('{"old": 1}', encoding="utf-8")
    real_open = open

    def corrupting_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if mode == "rb":  # read back differs from written data
            handle.read = lambda: b"{"
        return handle

    monkeypatch.setattr("builtins.open", corrupting_open)
    assert not write_json(str(target), {"new": 1})
    with pytest.raises(OSError):
        write_json(str(target), {"new": 1}, raise_error=True)
    monkeypatch.undo()
    assert target.read_text(encoding="utf-8") == '{"old": 1}'
    assert os.listdir(tmp_path) == ["data.json"]


def test_write_json_errors(tmp_path):
    assert not write_json(str(tmp_path / "missing" / "data.json"), {})
    with pytest.raises(OSError):
        write_json(str(tmp_path / "missing" / "data.json"), {}, raise_error=True)
    with pytest.raises(TypeError):
        write_json(str(tmp_path / "data.json"), {"bad": object()})
    assert os.listdir(tmp_path) == []


def test_write_json_single_write(tmp_path, monkeypatch):
    """One write call (json.dump writes each token)"""
    monkeypatch.setattr(json, "dump", lambda *args, **kwargs: pytest.fail("json.dump used"))
    assert write_json(str(tmp_path / "data.json"), {"a": list(range(1000))}, indent=1)


# --- Setting files
@pytest.mark.parametrize("compact", (False, True))
def test_saved_setting_byte_identical(tmp_path, compact):
    folder = f"{tmp_path.as_posix()}/"
    if compact:
        old_dump(f"{folder}old.json", DATA, separators=(",", ":"))
    else:
        old_dump(f"{folder}old.json", DATA, indent=4)
    old_dump(f"{folder}new.json", {"previous": 1}, indent=4)
    assert json_setting.save_and_verify_json_file(DATA, "new.json", folder, compact_json=compact)
    assert read_bytes(f"{folder}new.json") == read_bytes(f"{folder}old.json")
    assert sorted(os.listdir(folder)) == ["new.json", "old.json"]  # temporary backup removed


def test_save_verified_by_bytes_without_parsing(tmp_path, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    dumps = []
    real_dumps = json.dumps
    monkeypatch.setattr(json_setting.json, "load", lambda *args: pytest.fail("parsed to verify"))
    monkeypatch.setattr(json_setting.json, "dumps", lambda *args, **kwargs: dumps.append(1) or real_dumps(*args, **kwargs))
    assert json_setting.save_and_verify_json_file(DATA, "data.json", folder)
    assert dumps == [1]  # serialized once


def test_save_lost_write_detected(tmp_path, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    old_dump(f"{folder}data.json", {"old": True}, indent=4)
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    monkeypatch.setattr(json_setting, "save_json_file", lambda *args, **kwargs: None)  # write lost
    assert not json_setting.save_and_verify_json_file(DATA, "data.json", folder, max_attempts=2)
    assert json.loads(read_bytes(f"{folder}data.json")) == {"old": True}
    assert os.listdir(folder) == ["data.json"]


def test_setting_text_retried_while_changed_by_other_thread(monkeypatch):
    calls = []
    real_dumps = json.dumps

    def flaky_dumps(data, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("dictionary changed size during iteration")
        return real_dumps(data, **kwargs)

    monkeypatch.setattr(json_setting.json, "dumps", flaky_dumps)
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    assert json_setting.setting_json_text({"a": 1}) == '{\n    "a": 1\n}'
    assert len(calls) == 3


def test_saver_never_deep_copies(monkeypatch, tmp_path):
    """Saving thread serializes live dict once (was: deep copy, then dump)"""
    config = Setting()
    folder = f"{tmp_path.as_posix()}/"
    config.path.settings = folder
    config.user.config = {"application": {"maximum_saving_attempts": 3, "number_of_automatic_backups": 0}}
    config.user.filelock = {}
    config.user.setting = {"overlay": {"fixed_position": True}}
    monkeypatch.setattr(setting, "deepcopy", lambda data: pytest.fail("deep copied"))
    config.save(delay=0)
    assert config.flush(timeout=5)
    with open(f"{folder}{config.filename.setting}", encoding="utf-8") as file:
        assert json.load(file) == {"overlay": {"fixed_position": True}}


# --- No blocking wait on GUI thread
class SlowModule:
    """Data module whose stop work (saving) finishes once released"""

    def __init__(self, config=None, name="module_force"):
        self.name = name
        self.closed = False
        self.done = threading.Event()
        self.started = False

    def start(self):
        self.started = True

    def stop(self, discard=False):
        threading.Timer(0.15, self.finish).start()

    def finish(self):
        self.closed = True
        self.done.set()

    def wait_closed(self, timeout):
        return self.done.wait(timeout)


@pytest.fixture
def blocking_waits(monkeypatch):
    """Blocking waits reached from GUI thread (main thread)"""
    reached = []

    def spy(name, real):
        def wrapper(*args, **kwargs):
            if threading.current_thread() is threading.main_thread():
                reached.append(name)
            return real(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(module_control, "wait_all_stopped", spy("wait_all_stopped", module_control.wait_all_stopped))
    monkeypatch.setattr(thread_guard, "wait_all_stopped", spy("wait_all_stopped", thread_guard.wait_all_stopped))
    monkeypatch.setattr(Setting, "flush", spy("cfg.flush", Setting.flush))
    monkeypatch.setattr(loader, "wait_lap_saver", spy("wait_lap_saver", loader.wait_lap_saver))
    return reached


def run_in_event_loop(action, until, seconds: float = 5.0):
    """Run action from running event loop (as GUI), then events until condition"""
    loop = QEventLoop()
    QTimer.singleShot(0, action)
    deadline = time.monotonic() + seconds

    def check():
        if until() or time.monotonic() > deadline:
            loop.quit()
        else:
            QTimer.singleShot(5, check)

    QTimer.singleShot(5, check)
    loop.exec()
    return until()


def new_control(instances):
    def realtime(config, name):
        instance = SlowModule(config, name)
        instances.append(instance)
        return instance

    target = SimpleNamespace(__all__=["module_force"], module_force=SimpleNamespace(Realtime=realtime))
    return ModuleControl(target, ConfigType.MODULE)


def test_toggle_never_waits_module_stop(ui_env, blocking_waits):
    instances = []
    control = new_control(instances)
    cfg.user.setting["module_force"]["enable"] = False
    control.toggle("module_force", wait=True)  # started
    returned = []

    def toggle_off():
        started = time.perf_counter()
        control.toggle("module_force")  # stop work takes 0.15 s
        returned.append(time.perf_counter() - started)

    assert run_in_event_loop(toggle_off, lambda: returned)
    assert returned[0] < 0.1 and not control.active_modules and not instances[0].closed
    assert control.stopping()  # polled
    assert run_in_event_loop(lambda: None, lambda: not control._stopping)
    assert instances[0].closed and blocking_waits == []


def test_toggle_on_while_stopping_starts_once_stopped(ui_env, blocking_waits, monkeypatch):
    from neopedal import app_signal

    refreshed = []
    app_signal.refresh.connect(refreshed.append)
    try:
        instances = []
        control = new_control(instances)
        cfg.user.setting["module_force"]["enable"] = False
        control.toggle("module_force", wait=True)
        old = instances[0]

        def toggle_twice():
            control.toggle("module_force")  # off: stopping
            control.toggle("module_force")  # on again: waits for previous instance, never blocking

        assert run_in_event_loop(toggle_twice, lambda: len(instances) == 2)
        assert old.closed and instances[1].started  # new instance only once old one stopped
        assert control.active_modules["module_force"] is instances[1]
        assert refreshed and blocking_waits == []
        # Off & on & off while stopping: never started
        cfg.user.setting["module_force"]["enable"] = True

        def toggle_thrice():
            control.toggle("module_force")
            control.toggle("module_force")
            control.toggle("module_force")

        run_in_event_loop(toggle_thrice, lambda: instances[1].closed and not control._stopping)
        QCoreApplication.processEvents()
        assert len(instances) == 2 and not control.active_modules and blocking_waits == []
    finally:
        app_signal.refresh.disconnect(refreshed.append)


def test_quit_waits_module_toggled_off(ui_env):
    """Quit (no event loop): module still stopping waited, pending start dropped"""
    instances = []
    control = new_control(instances)
    cfg.user.setting["module_force"]["enable"] = False
    control.toggle("module_force", wait=True)
    control.toggle("module_force", wait=False)
    control.toggle("module_force", wait=False)  # start pending
    control.close()
    assert instances[0].closed and len(instances) == 1
    QCoreApplication.processEvents()
    time.sleep(0.03)
    QCoreApplication.processEvents()
    assert len(instances) == 1 and not control.active_modules


@pytest.fixture
def reloader(ui_env, monkeypatch):
    """Reload with real module control, other controls faked"""
    calls = []
    fake = SimpleNamespace(
        enable=lambda *a: None, disable=lambda *a: None, suspend=lambda *a: None,
        restart=lambda *a: calls.append("api.restart"))
    for name in ("octrl", "kctrl", "cmdserver", "webdashboard", "streamoverlay", "api"):
        monkeypatch.setattr(loader, name, fake)
    monkeypatch.setattr(loader, "vroverlay", lambda: fake)
    monkeypatch.setattr(loader, "sync_screen_layout", lambda: None)
    monkeypatch.setattr(loader, "park_collected", lambda: None)
    monkeypatch.setattr(Setting, "load_user", lambda self: calls.append("cfg.load_user"))
    monkeypatch.setattr(loader, "_reload", loader.ReloadState())
    instances = []
    mctrl = new_control(instances)
    monkeypatch.setattr(loader, "mctrl", mctrl)
    monkeypatch.setattr(loader, "wctrl", ModuleControl(SimpleNamespace(__all__=[]), ConfigType.WIDGET))
    cfg.user.setting["module_force"]["enable"] = False
    mctrl.toggle("module_force", wait=True)
    cfg.user.setting["module_force"]["enable"] = True
    yield SimpleNamespace(calls=calls, instances=instances, mctrl=mctrl)
    loader.cancel_reload()


def test_reload_never_waits_on_gui_thread(reloader, blocking_waits, monkeypatch):
    saving = {"on": True}
    monkeypatch.setattr(cfg, "is_saving", True)  # module data being saved

    def finish_saving():
        monkeypatch.setattr(cfg, "is_saving", False)
        saving["on"] = False

    threading.Timer(0.3, finish_saving).start()
    assert run_in_event_loop(lambda: loader.reload(reload_preset=True), lambda: not loader.reloading() and
                             "cfg.load_user" in reloader.calls)
    assert not saving["on"]  # preset loaded once saving finished
    assert reloader.instances[0].closed and reloader.instances[1].started
    assert reloader.calls.index("cfg.load_user") < reloader.calls.index("api.restart")
    assert blocking_waits == []


def test_reload_gives_up_saving_after_timeout(reloader, monkeypatch, caplog):
    monkeypatch.setattr(cfg, "is_saving", True)  # saving never finishes
    monkeypatch.setattr(loader, "SAVE_TIMEOUT", 0.2)
    assert run_in_event_loop(lambda: loader.reload(reload_preset=True), lambda: not loader.reloading())
    assert "saving not finished" in caplog.text and "cfg.load_user" in reloader.calls


def test_blocking_reload_still_flushes(reloader, blocking_waits):
    """No event loop (quit, tests): reload finished before returning, saving waited"""
    loader.reload(reload_preset=True)
    assert "cfg.flush" in blocking_waits and "cfg.load_user" in reloader.calls
