"""Reload without blocking GUI: modules stopping polled by timer, queued reloads, callbacks, GC policy"""

import logging
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import loader, realtime_state
from neopedal.const_file import ConfigType
from neopedal.module_control import ModuleControl
from neopedal.setting import cfg


def spin_until(condition, seconds: float = 5.0) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.002)
    return condition()


class SlowModule:
    """Data module whose stop work (saving) finishes once released"""

    def __init__(self, name, log):
        self.name = name
        self.log = log
        self.closed = False
        self.done = threading.Event()

    def stop(self, discard=False):
        self.log.append(("stop", self.name))

    def finish(self):
        self.log.append(("stopped", self.name))
        self.closed = True
        self.done.set()

    def wait_closed(self, timeout):
        return self.done.wait(timeout)


# --- Module control: stop signalled, polled
def test_stop_all_signals_without_waiting():
    log = []
    control = ModuleControl(SimpleNamespace(__all__=["module_a", "module_b"]), ConfigType.MODULE)
    fakes = {name: SlowModule(name, log) for name in ("module_a", "module_b")}
    control._active_modules.update(fakes)
    started = time.perf_counter()
    control.stop_all()
    assert time.perf_counter() - started < 0.5  # never waits
    assert not control.active_modules and log == [("stop", "module_a"), ("stop", "module_b")]
    assert control.stopping()
    fakes["module_a"].finish()
    assert control.stopping()
    fakes["module_b"].finish()
    assert not control.stopping()
    assert control.wait_stopping()  # nothing left


def test_stopping_gives_up_after_stop_timeout(caplog):
    control = ModuleControl(SimpleNamespace(__all__=["module_a"]), ConfigType.MODULE)
    control._active_modules["module_a"] = SlowModule("module_a", [])
    control.stop_all()
    assert control.stopping()
    control._stop_deadline = time.monotonic() - 1  # stop timeout passed
    with caplog.at_level(logging.ERROR):
        assert not control.stopping()  # continue anyway, as a blocking wait does
    assert "module_a not stopped after" in caplog.text


def test_module_never_started_while_previous_instance_stopping(ui_env):
    """Module started again (by hand) during reload: previous instance finished its stop work first"""
    log = []
    old = SlowModule("module_force", log)

    class New:
        def __init__(self, config, name):
            log.append(("new", name))
            self.closed = False

        def start(self):
            pass

    target = SimpleNamespace(__all__=["module_force"], module_force=SimpleNamespace(Realtime=New))
    control = ModuleControl(target, ConfigType.MODULE)
    control._active_modules["module_force"] = old
    cfg.user.setting["module_force"]["enable"] = True
    control.stop_all()
    threading.Timer(0.1, old.finish).start()
    control.start("module_force")
    assert log == [("stop", "module_force"), ("stopped", "module_force"), ("new", "module_force")]
    assert not control.stopping()


def test_close_waits_modules_signalled_before():
    """Quit during reload: modules still stopping waited (bounded) like active ones"""
    control = ModuleControl(SimpleNamespace(__all__=["module_a"]), ConfigType.MODULE)
    fake = SlowModule("module_a", [])
    control._active_modules["module_a"] = fake
    control.stop_all()
    threading.Timer(0.1, fake.finish).start()
    control.close()
    assert fake.closed and not control.stopping()


# --- Loader: reload continued once modules stopped, event loop kept running
class FakeControl:
    """Module or widget control: modules stop once released"""

    def __init__(self, name, calls):
        self.name = name
        self.calls = calls
        self.pending = False

    def __getattr__(self, action):
        return lambda *args, **kwargs: self.calls.append(f"{self.name}.{action}")

    def stop_all(self):
        self.calls.append(f"{self.name}.stop_all")
        self.pending = self.name == "mctrl"

    def stopping(self):
        return self.pending

    def wait_stopping(self, names=None):
        if self.pending:
            self.calls.append(f"{self.name}.waited")
        self.pending = False
        return True


@pytest.fixture
def reloader(ui_env, monkeypatch):
    calls = []
    controls = {}
    for name in ("octrl", "mctrl", "wctrl", "kctrl", "cmdserver", "webdashboard", "streamoverlay", "api"):
        controls[name] = FakeControl(name, calls)
        monkeypatch.setattr(loader, name, controls[name])
    monkeypatch.setattr(loader, "vroverlay", lambda: SimpleNamespace(enable=lambda: None, disable=lambda: None))
    monkeypatch.setattr(loader, "sync_screen_layout", lambda: calls.append("layout"))
    monkeypatch.setattr(type(cfg), "flush", lambda self: calls.append("cfg.flush"))
    monkeypatch.setattr(type(cfg), "load_user", lambda self: calls.append("cfg.load_user"))
    monkeypatch.setattr(loader, "_reload", loader.ReloadState())
    monkeypatch.setattr(loader, "_gc_frozen", False)
    yield SimpleNamespace(calls=calls, mctrl=controls["mctrl"])
    loader.cancel_reload()


def test_reload_returns_while_modules_stopping(reloader):
    done = []
    loader.reload(reload_preset=True, wait=False)
    loader.after_reload(lambda: done.append(list(reloader.calls)))
    assert loader.reloading() and "api.restart" not in reloader.calls and not done
    spin_until(lambda: False, 0.05)  # event loop runs, modules still stopping
    assert loader.reloading() and "api.restart" not in reloader.calls
    reloader.mctrl.pending = False  # modules stopped
    assert spin_until(lambda: done)
    calls = done[0]
    # Same steps & order as blocking reload: saved, stopped, saved again, preset loaded, api, modules
    assert calls[0] == "cfg.flush"
    assert calls.index("wctrl.stop_all") < calls.index("mctrl.stop_all") < calls.index("octrl.disable")
    assert calls.index("octrl.disable") < calls.index("cfg.flush", 1) < calls.index("cfg.load_user")
    assert calls.index("cfg.load_user") < calls.index("layout") < calls.index("api.restart")
    assert calls.index("api.restart") < calls.index("mctrl.start") < calls.index("wctrl.start")
    assert not loader.reloading()


def test_reload_asked_while_reloading_runs_once_after(reloader):
    done = []
    loader.reload(wait=False)
    loader.reload(wait=False)
    loader.reload(reload_preset=True, wait=False)  # strongest flags kept
    loader.after_reload(lambda: done.append(1))
    assert reloader.calls.count("mctrl.stop_all") == 1
    reloader.mctrl.pending = False
    assert spin_until(lambda: reloader.calls.count("mctrl.stop_all") == 2)
    assert not done and loader.reloading()  # callbacks wait for queued reload
    reloader.mctrl.pending = False
    assert spin_until(lambda: done)
    assert reloader.calls.count("api.restart") == 2 and reloader.calls.count("cfg.load_user") == 1
    spin_until(lambda: False, 0.05)
    assert done == [1] and reloader.calls.count("api.restart") == 2


def test_blocking_reload_finishes_reload_in_progress(reloader):
    done = []
    loader.reload(wait=False)
    loader.after_reload(lambda: done.append(1))
    loader.reload(reload_preset=True, wait=True)
    assert done == [1] and not loader.reloading()
    assert "mctrl.waited" in reloader.calls
    assert reloader.calls.count("api.restart") == 2 and reloader.calls.count("cfg.load_user") == 1


def test_close_cancels_reload_in_progress(reloader):
    done = []
    loader.reload(wait=False)
    loader.after_reload(lambda: done.append(1))
    loader.close()
    reloader.mctrl.pending = False
    spin_until(lambda: False, 0.1)
    assert "api.restart" not in reloader.calls and "mctrl.start" not in reloader.calls
    assert not done and not loader.reloading()
    assert reloader.calls.index("mctrl.close") > reloader.calls.index("mctrl.stop_all")


def test_after_reload_runs_at_once_when_idle(reloader):
    done = []
    loader.after_reload(lambda: done.append(1))
    assert done == [1]


def test_reload_blocking_without_event_loop(reloader):
    """Tests & quit: no event loop running, reload finished before returning"""
    assert not loader.event_loop_running()
    loader.reload()
    assert "api.restart" in reloader.calls and "mctrl.close" in reloader.calls and not loader.reloading()


def test_reload_with_real_module_control_gives_up_after_timeout(reloader, monkeypatch, caplog):
    """Module never stopping: logged, reload continued after its stop timeout (as blocking wait did)"""
    control = ModuleControl(SimpleNamespace(__all__=[]), ConfigType.MODULE)  # nothing started again
    control._active_modules["module_a"] = SlowModule("module_a", [])
    monkeypatch.setattr(loader, "mctrl", control)
    loader.reload(wait=False)
    assert loader.reloading()
    control._stop_deadline = time.monotonic() + 0.1
    with caplog.at_level(logging.ERROR):
        assert spin_until(lambda: not loader.reloading())
    assert "module_a not stopped after" in caplog.text and "api.restart" in reloader.calls


# --- Garbage collection after reload
@pytest.fixture
def gc_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(loader.gc, "freeze", lambda: calls.append("freeze"))
    monkeypatch.setattr(loader.gc, "unfreeze", lambda: calls.append("unfreeze"))
    monkeypatch.setattr(loader.gc, "collect", lambda *_: calls.append("collect"))
    timers = []
    from PySide6.QtCore import QTimer

    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda delay, func: timers.append(func)))
    monkeypatch.setattr(loader, "_gc_collect_due", False)
    monkeypatch.setattr(loader, "_gc_frozen", True)
    return SimpleNamespace(calls=calls, timers=timers)


def test_reload_while_driving_freezes_without_collecting(gc_calls, monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    loader.park_collected()
    loader.park_collected()  # second reload: one full collection only
    assert gc_calls.calls == ["freeze", "freeze"] and len(gc_calls.timers) == 1
    gc_calls.timers.pop()()  # still driving: postponed
    assert gc_calls.calls == ["freeze", "freeze"] and len(gc_calls.timers) == 1
    monkeypatch.setattr(realtime_state, "active", False)
    gc_calls.timers.pop()()  # idle: parked garbage collected, frozen again
    assert gc_calls.calls[2:] == ["unfreeze", "collect", "freeze"] and not gc_calls.timers
    assert loader._gc_frozen and not loader._gc_collect_due


def test_reload_never_freezes_before_start_finished(gc_calls, monkeypatch):
    monkeypatch.setattr(loader, "_gc_frozen", False)
    loader.park_collected()
    assert gc_calls.calls == [] and gc_calls.timers == []
