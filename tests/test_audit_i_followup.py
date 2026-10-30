"""Audit 2026-10-30 follow-up of findings first treated in part: saving waited off the UI thread before preset
file work (PERF-018), HTTPS dashboard set up on its own thread (PERF-030), presets folder read by one scan
(PERF-048), stream layout store told when its file is not written (BUG-021), activity Qt signal gone (BUG-014)"""

import http.client
import json
import os
import socket
import ssl
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import module_control
from neopedal.setting import cfg
from neopedal.userfile import tls_cert

pytestmark = pytest.mark.timeout(60)


def wait_until(condition, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeJobs:
    """Page jobs recorder: work & done kept, run by the test"""

    def __init__(self):
        self.runs: list = []

    def run(self, name, work, done=None, failed=None, key=None, cancellable=False) -> int:
        self.runs.append((name, work, done, key))
        return len(self.runs)

    def finish(self):
        _, work, done, _ = self.runs.pop(0)
        done(work())


@pytest.fixture
def fake_page():
    return SimpleNamespace(jobs=FakeJobs(), toasts=[], show_toast=lambda text, error=False, undo=False: None)


# --- PERF-018: saving waited off the UI thread
def test_after_saving_runs_now_without_running_save(fake_page, monkeypatch):
    from neopedal.ui.preset_management import after_saving

    monkeypatch.setattr(cfg, "is_saving", False)
    monkeypatch.setattr(module_control, "event_loop_running", lambda: True)
    ran = []
    assert after_saving(fake_page, lambda: ran.append(1))
    assert ran == [1] and not fake_page.jobs.runs


def test_after_saving_runs_now_without_event_loop(fake_page, monkeypatch):
    """App start & tests: nothing would run meanwhile, the save is waited on the calling thread as before"""
    from neopedal.ui.preset_management import after_saving

    monkeypatch.setattr(cfg, "is_saving", True)
    monkeypatch.setattr(module_control, "event_loop_running", lambda: False)
    ran = []
    assert after_saving(fake_page, lambda: ran.append(1))
    assert ran == [1] and not fake_page.jobs.runs


def test_after_saving_waits_on_a_job_while_saving(fake_page, monkeypatch):
    from neopedal.ui.preset_management import SAVING_WAIT, after_saving

    monkeypatch.setattr(cfg, "is_saving", True)
    monkeypatch.setattr(module_control, "event_loop_running", lambda: True)
    flushed = []
    monkeypatch.setattr(type(cfg), "flush", lambda self, timeout=10.0: flushed.append(timeout) or True)
    toasts = []
    fake_page.show_toast = lambda text, error=False, undo=False: toasts.append(text)
    ran = []
    assert not after_saving(fake_page, lambda: ran.append(1))
    assert not ran and toasts == [SAVING_WAIT]  # told, nothing done yet: the UI thread is free
    (_, work, _, key), = fake_page.jobs.runs
    assert key == "wait saving" and work == cfg.flush
    fake_page.jobs.finish()  # saving thread finished: file work follows on the UI thread
    assert flushed == [10.0] and ran == [1]


class Host:
    """Presets page host stub"""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def presets_backend(ui_env):
    from neopedal.ui.quick.preset_backend import PresetBackend

    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        json.dump({"speedometer": {"enable": True}}, file)
    backend = PresetBackend(None, Host())
    backend.toasts = []
    backend.toastShown.connect(lambda text, error, undo: backend.toasts.append((text, error)))
    backend.set_active(True)
    yield backend
    backend.release()
    backend.deleteLater()


def test_rename_of_loaded_preset_being_saved_waits_off_the_ui_thread(presets_backend, monkeypatch):
    from neopedal.ui.quick import preset_backend as pb

    backend = presets_backend
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    monkeypatch.setattr(cfg, "is_saving", True)
    monkeypatch.setattr(module_control, "event_loop_running", lambda: True)
    monkeypatch.setattr(type(cfg), "flush", lambda self, timeout=10.0: True)
    deferred = []
    monkeypatch.setattr(pb, "after_saving", lambda page, then: deferred.append(then) or False)
    assert backend.applyName("rename", "race.json", "race") == ""  # same name: nothing to do
    assert backend.applyName("rename", "race.json", "bad/name") != ""  # name checked at once (dialog)
    assert not deferred
    assert backend.applyName("rename", "race.json", "endurance") == ""  # accepted: file work once saved
    assert len(deferred) == 1 and os.path.exists(f"{cfg.path.settings}race.json")
    deferred[0]()
    assert os.path.exists(f"{cfg.path.settings}endurance.json") and not os.path.exists(f"{cfg.path.settings}race.json")
    assert cfg.filename.setting == "endurance.json"
    assert backend.toasts and "endurance" in backend.toasts[-1][0]
    # Deferred file work failing: told by the toast (the dialog is closed)
    monkeypatch.setattr(pb, "apply_preset_name", lambda *args: "Preset already exists.")
    assert backend.applyName("duplicate", "endurance.json", "copy") == ""
    deferred[1]()
    assert backend.toasts[-1] == ("Preset already exists.", True)


def test_rename_of_other_preset_or_idle_saver_done_at_once(presets_backend, monkeypatch):
    from neopedal.ui.quick import preset_backend as pb

    backend = presets_backend
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    monkeypatch.setattr(cfg, "is_saving", True)
    monkeypatch.setattr(module_control, "event_loop_running", lambda: True)
    monkeypatch.setattr(pb, "after_saving", lambda page, then: pytest.fail("not the loaded preset: no wait"))
    assert backend.applyName("duplicate", "race.json", "race copy") == ""
    assert os.path.exists(f"{cfg.path.settings}race copy.json")
    monkeypatch.setattr(cfg, "is_saving", False)
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    assert backend.applyName("rename", "race.json", "endurance") == ""  # loaded but no save running: at once
    assert os.path.exists(f"{cfg.path.settings}endurance.json")


def test_style_backup_restore_and_package_import_wait_for_saving(ui_env, monkeypatch):
    from neopedal.ui import preset_view
    from neopedal.ui.quick import preset_tools_backend

    waited = []

    def after_saving(page, then):
        waited.append(page)
        then()
        return True

    monkeypatch.setattr(preset_tools_backend, "after_saving", after_saving)
    monkeypatch.setattr(preset_view, "after_saving", after_saving)
    restored = []
    monkeypatch.setattr(preset_tools_backend, "restore_style_backup", lambda name: restored.append(name))
    view = preset_view.PresetList(None)
    try:
        backups = view.backend.backups
        backups._files = {"classes.json.backup-1": SimpleNamespace(style=True)}
        backups.restoreStyle("classes.json.backup-1")
        assert waited == [view.backend] and restored == ["classes.json.backup-1"]
        imported = []
        monkeypatch.setattr(view, "_import_package_now", lambda *args: imported.append(args))
        monkeypatch.setattr(preset_view, "confirm_action", lambda *args, **kwargs: True)
        monkeypatch.setattr("neopedal.userfile.overlay_package.is_overlay_package", lambda path: False)
        view.import_package_file("package.zip")
        assert waited == [view.backend, view.backend] and imported == [("package.zip", True)]
        monkeypatch.setattr(preset_view, "confirm_action", lambda *args, **kwargs: False)
        view.import_package_file("package.zip")  # styles kept: no save to wait for
        assert len(waited) == 2 and imported[-1] == ("package.zip", False)
    finally:
        view.release_page()
        view.deleteLater()


# --- PERF-048: presets folder read by one scan
def test_list_presets_by_one_scan(tmp_path):
    from neopedal.ui.quick.preset_backend import list_presets

    folder = tmp_path / "settings"
    folder.mkdir()
    for number, name in enumerate(("old.json", "new.json", "notes.txt", "bad:name.json")):
        try:
            (folder / name).write_text("{}", encoding="utf-8")
        except OSError:  # name refused by the file system: not listed either way
            continue
        os.utime(folder / name, (1000 + number, 1000 + number))
    (folder / "folder.json").mkdir()  # a folder is never a preset
    listed = list_presets(str(folder))
    assert [filename for filename, _ in listed] == ["new.json", "old.json"]  # newest first
    assert all(stat.st_mtime_ns and stat.st_size == 2 for _, stat in listed)
    assert list_presets(str(tmp_path / "missing")) == []


# --- PERF-030: HTTPS dashboard set up on its own thread
@pytest.fixture
def https_config(ui_env):
    from neopedal.web_dashboard import DashboardHandler

    port = free_port()
    cfg.user.config["web_dashboard"].update(
        enable_web_dashboard=True, web_dashboard_port=port, access_code="TESTCODE", enable_https=True,
        enable_lan_access=False)
    yield port
    DashboardHandler.secure = False


def slow_context(monkeypatch, release: threading.Event):
    from neopedal import web_dashboard

    real = web_dashboard.server_context
    entered = threading.Event()

    def building(folder, addresses):
        entered.set()
        assert release.wait(5), "test never released the TLS set-up"
        return real(folder, addresses)

    monkeypatch.setattr(web_dashboard, "server_context", building)
    return entered


def test_https_served_once_context_built_off_the_ui_thread(https_config, monkeypatch):
    from neopedal.web_dashboard import WebDashboard

    port = https_config
    monkeypatch.setattr(module_control, "event_loop_running", lambda: True)
    release = threading.Event()
    entered = slow_context(monkeypatch, release)
    server = WebDashboard()
    try:
        started = time.monotonic()
        server.enable()
        assert time.monotonic() - started < 1  # the UI thread never waited for the certificate
        assert server.running and server._thread is None  # reserved: a second enable keeps it
        assert entered.wait(5)
        server.enable()
        assert server._thread is None
        release.set()
        assert wait_until(lambda: server._thread is not None)
        context = ssl.create_default_context(cafile=tls_cert.cert_paths(cfg.path.config)[0])
        client = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
        client.request("GET", "/api/telemetry", headers={"X-Access-Code": "TESTCODE"})
        assert client.getresponse().status == 200
        client.close()
    finally:
        server.disable()
    assert not server.running


def test_https_set_up_dropped_when_disabled_meanwhile(https_config, monkeypatch):
    from neopedal.web_dashboard import WebDashboard

    port = https_config
    monkeypatch.setattr(module_control, "event_loop_running", lambda: True)
    release = threading.Event()
    entered = slow_context(monkeypatch, release)
    server = WebDashboard()
    server.enable()
    assert entered.wait(5)
    started = time.monotonic()
    server.disable()  # before it served: returns at once (no shutdown of a server never serving)
    assert time.monotonic() - started < 1 and not server.running
    release.set()

    def port_free() -> bool:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                return False
            return True

    assert wait_until(port_free)  # set-up thread closed the dropped server
    assert not server.running and server._thread is None


def test_https_set_up_failure_off_the_ui_thread_drops_server(https_config, monkeypatch):
    from neopedal import web_dashboard
    from neopedal.web_dashboard import WebDashboard

    monkeypatch.setattr(module_control, "event_loop_running", lambda: True)

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(web_dashboard, "server_context", broken)
    server = WebDashboard()
    try:
        server.enable()
        assert wait_until(lambda: not server.running)
        assert server._key is None and server._thread is None
    finally:
        server.disable()


def test_https_synchronous_without_event_loop(https_config):
    """Start & tests: served once enable returns, as before"""
    from neopedal.web_dashboard import WebDashboard

    server = WebDashboard()
    try:
        server.enable()
        assert server.running and server._thread is not None
    finally:
        server.disable()
    assert not server.running


# --- BUG-021: layout store told when its file is not written
def test_placement_store_logs_unwritten_layout(tmp_path, monkeypatch, caplog):
    from neopedal.stream_director_feeds import PlacementStore

    store = PlacementStore("layout.json", sections=("a", "b"))
    monkeypatch.setattr(PlacementStore, "folder", staticmethod(lambda: str(tmp_path / "gone")))  # no folder
    with caplog.at_level("WARNING"):
        assert store.set_active("a")  # not raised to the server handler
    assert any("layout not saved" in record.message for record in caplog.records)
    assert not any(record.message.endswith(" saved") for record in caplog.records)  # never "saved" after a failure


# --- BUG-014: no Qt signal emitted from data threads on activity change
def test_activity_change_emits_no_qt_signal():
    from neopedal import overlay_signal, realtime_state

    assert not hasattr(overlay_signal, "activity")
    version = realtime_state.version
    realtime_state.notify_change()
    assert realtime_state.version == version + 1
