"""Architecture step 3: one job mechanism (core jobs module), game Rest API client in core, page backends with
one lifecycle (PageBackend), raw page threads moved to jobs"""

import ast
import gc
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QObject

from tests.test_audit_c_update import messages, updates  # noqa: F401
from tests.test_driver_stats_e2 import OREGA, SPA, stats_page, wait_stints  # noqa: F401
from tests.test_setup_wizard import renders  # noqa: F401

PACKAGE = Path(__file__).resolve().parent.parent / "neopedal"
# App entry points building the UI: their function-level imports of neopedal.ui are allowed
UI_ENTRY_POINTS = {"loader.py", "main.py", "self_test.py"}


@pytest.fixture(autouse=True)
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def wait_for(condition, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return condition()


def ui_imports(path: Path) -> list[tuple[int, bool]]:
    """Imports of neopedal.ui in a module: (line, at module level)"""
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    package = list(parts[:-1])
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    def visit(node: ast.AST, top: bool):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                visit(child, False)
                continue
            if isinstance(child, ast.If) and isinstance(child.test, ast.Name) and child.test.id == "TYPE_CHECKING":
                continue  # type checking only
            names: list[str] = []
            if isinstance(child, ast.ImportFrom):
                base = package[:len(package) - child.level + 1] if child.level else []
                module = ".".join([*base, child.module] if child.module else base)
                names = [module, *(f"{module}.{alias.name}" for alias in child.names)]
            elif isinstance(child, ast.Import):
                names = [alias.name for alias in child.names]
            if any(name == "neopedal.ui" or name.startswith("neopedal.ui.") for name in names):
                found.append((child.lineno, top))
            visit(child, top)

    visit(tree, True)
    return found


def test_core_never_imports_ui():
    """Modules outside neopedal/ui & neopedal/widget never import the UI at module level; function-level imports
    only in app entry points (overlay widgets open pages lazily: widget/_base.py, widget/_edit_toolbar.py)"""
    module_level, function_level = [], []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        if relative.parts[0] in ("ui", "widget"):
            continue
        for line, top in ui_imports(path):
            (module_level if top else function_level).append(f"{relative}:{line}")
    assert module_level == []
    assert all(entry.split(":")[0] in UI_ENTRY_POINTS for entry in function_level), function_level


def test_ui_game_rest_is_core_module(monkeypatch):
    import neopedal.game_rest as core
    import neopedal.ui.game_rest as shim
    from neopedal import ui

    assert shim is core and ui.game_rest is core
    monkeypatch.setattr(shim, "request_game", lambda resource, max_age=0: resource)  # older patches act on core
    assert core.request_game("/a") == "/a"


def test_jobs_and_game_rest_need_qt_core_only():
    """Core job & game request modules: no Qt GUI, Qt Quick nor UI package, worker pools made when needed"""
    code = (
        "import sys\n"
        "import neopedal.game_rest, neopedal.jobs\n"
        "bad = sorted(name for name in sys.modules if name.startswith(('PySide6.QtGui', 'PySide6.QtWidgets', "
        "'PySide6.QtQuick', 'PySide6.QtQml', 'neopedal.ui')))\n"
        "assert not bad, bad\n"
        "assert neopedal.jobs._page_pool is None and neopedal.game_rest._pool is None\n"
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run([sys.executable, "-c", code], cwd=PACKAGE.parent, env=env, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr


def test_one_weak_callback_helper():
    from neopedal import game_rest, jobs
    from neopedal.ui import lazy_page
    from neopedal.ui.quick import background

    assert background.weak_callback is jobs.weak_callback is lazy_page.weak_callback is game_rest.weak_callback
    assert not hasattr(lazy_page, "_weak_callback") and not hasattr(game_rest.GameRequest, "_weak")

    class Owner:
        def method(self):
            return 1

    owner = Owner()
    held = jobs.weak_callback(owner.method)
    assert held()() == 1
    del owner
    gc.collect()
    assert held() is None
    assert jobs.weak_callback(None)() is None
    assert jobs.weak_callback(len)() is len  # functions & builtins held strongly
    assert jobs.weak_callback([].append)() is not None


def test_background_jobs_and_game_requests_share_courier():
    from neopedal import game_rest, jobs
    from neopedal.ui.quick.background import BackgroundJobs

    parent = QObject()
    try:
        BackgroundJobs(parent)
        courier = jobs.get_courier()
        game_rest.GameRequest(parent, (), lambda value: None)
        assert jobs.get_courier() is courier
    finally:
        parent.deleteLater()


# --- PageBackend: one lifecycle for page backends
def test_page_backend_shown_hidden_forms():
    from neopedal.ui.quick.page_backend import PageBackend

    class ByActive(PageBackend):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_active(self, active):
            self.calls.append(active)

    class ByShown(PageBackend):
        def __init__(self):
            super().__init__()
            self.calls = []

        def page_shown(self):
            self.calls.append("shown")

        def page_hidden(self):
            self.calls.append("hidden")

    active, shown = ByActive(), ByShown()
    active.page_shown()
    active.page_hidden()
    shown.set_active(True)
    shown.set_active(False)
    assert active.calls == [True, False] and shown.calls == ["shown", "hidden"]
    PageBackend().set_active(True)  # neither overridden: nothing


def test_page_backend_release_once():
    from neopedal.ui.quick.page_backend import PageBackend

    class Page(PageBackend):
        def __init__(self):
            super().__init__(label="Test page")
            self.released = 0
            self.timer = self.page_timer(lambda: None, 1000)

        def release_resources(self):
            self.released += 1

    page = Page()
    page.timer.start()
    gate = threading.Event()
    results = []
    page.jobs.run("wait", lambda: gate.wait(5), results.append, key="k")
    page.jobs.run("waiting", lambda: 1, results.append, key="k")
    page.release()
    page.release()
    gate.set()
    assert page.page_released and page.released == 1 and not page.timer.isActive()
    assert wait_for(lambda: page.jobs.running == 0)
    assert results == []  # running job's result & waiting job dropped


def test_main_backends_are_page_backends():
    from neopedal.ui.quick import (
        director_backend,
        lap_backend,
        module_backend,
        overlay_backend,
        overlay_options_backend,
        preset_backend,
        race_backend,
        replays_backend,
        results_backend,
        setup_backend,
        spectate_backend,
        stats_backend,
        stream_backend,
        track_map_backend,
    )
    from neopedal.ui.quick.page_backend import PageBackend

    classes = (director_backend.DirectorBackend, lap_backend.LapViewerBackend, module_backend.ModuleBackend,
               overlay_backend.OverlayBackend, overlay_options_backend.OverlayOptionsBackend,
               preset_backend.PresetBackend, race_backend.RaceBackend, replays_backend.GameReplaysBackend,
               results_backend.RaceResultsBackend, setup_backend.SetupBackend, spectate_backend.SpectateBackend,
               stats_backend.DriverStatsBackend, stream_backend.StreamOverlaysBackend,
               track_map_backend.TrackMapBackend)
    for cls in classes:
        assert issubclass(cls, PageBackend), cls
        assert "release" not in vars(cls), cls  # resources freed in release_resources, release runs it once
    for cls in (overlay_backend.OverlayBackend, overlay_options_backend.OverlayOptionsBackend):
        assert "close" in vars(cls)  # older name kept (hosts & tests)


# --- Raw page threads moved to jobs: results handed over on the UI thread
def test_reference_download_is_a_page_job(stats_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import stats_backend
    from neopedal.userfile import lap_reference

    seen = {}

    def fetch(url, timeout=15):
        seen["thread"] = threading.current_thread()
        raise OSError("offline")

    def downloaded(text, error):
        seen["done"] = (threading.current_thread(), error)

    monkeypatch.setattr(lap_reference, "fetch_sheet", fetch)
    monkeypatch.setattr(stats_page, "reference_downloaded", downloaded)
    assert not hasattr(stats_backend.DriverStatsBackend, "reference_loaded")
    stats_page.download_reference(force=True)
    assert stats_page.jobs.running >= 1
    assert wait_for(lambda: "done" in seen)
    assert seen["thread"] is not threading.main_thread()
    assert seen["done"] == (threading.main_thread(), "offline")


def test_reference_download_failure_never_left_downloading(stats_page, monkeypatch, caplog):  # noqa: F811
    from neopedal.ui.quick import stats_backend

    def broken(url):
        raise SystemExit  # not an Exception: job failed callback

    monkeypatch.setattr(stats_backend, "download_reference_sheet", broken)
    with caplog.at_level(logging.ERROR):
        stats_page.download_reference(force=True)
        assert wait_for(lambda: not stats_page._downloading)
    assert stats_page.reference_error == "download failed"


def test_download_reference_sheet_errors(monkeypatch):
    from neopedal.ui.quick import stats_backend
    from neopedal.userfile import lap_reference

    monkeypatch.setattr(lap_reference, "fetch_sheet", lambda url: "a,b")
    assert stats_backend.download_reference_sheet("x") == ("a,b", "")
    monkeypatch.setattr(lap_reference, "fetch_sheet", lambda url: (_ for _ in ()).throw(ValueError("bad")))
    assert stats_backend.download_reference_sheet("x") == ("", "bad")


def test_stints_read_is_a_page_job(stats_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import stats_backend

    threads = []
    real = stats_backend.read_laps

    def read(path, *args, **kwargs):
        threads.append(threading.current_thread())
        return real(path, *args, **kwargs)

    monkeypatch.setattr(stats_backend, "read_laps", read)
    stats_page.selectTrack(SPA)
    stats_page.selectRow(OREGA)
    stats_page.laps_timer.stop()
    stats_page.start_laps_read()
    assert stats_page.jobs.running == 1
    wait_stints(stats_page)
    assert threads and threads[-1] is not threading.main_thread() and stats_page.stints["note"] == ""
    assert stats_page._laps_running == 0


def test_stats_jobs_kept_running_once_released():
    """Driver stats edits still saved after close: a job waiting for a worker thread is never cancelled (it would
    never run, edits waiting for it neither)"""
    from neopedal.ui.quick.page_backend import PageBackend
    from neopedal.ui.quick.stats_backend import DriverStatsBackend

    assert DriverStatsBackend.CANCEL_JOBS_ON_RELEASE is False

    class Saving(PageBackend):
        CANCEL_JOBS_ON_RELEASE = False

    page = Saving()
    gate = threading.Event()
    ran = []
    page.jobs.run("wait", lambda: gate.wait(5), key="k")
    page.jobs.run("save", lambda: ran.append(1), key="k")  # waiting
    page.release()
    gate.set()
    assert wait_for(lambda: page.jobs.running == 0) and ran == [1]


def test_setup_games_detected_by_job(ui_env, renders, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import setup_backend

    seen = {}

    def running():
        seen["thread"] = threading.current_thread()
        return set(backend_games[:1])

    backend_games = [api_class.NAME for api_class in setup_backend.api.available]
    monkeypatch.setattr(setup_backend, "running_games", running)
    backend = setup_backend.SetupBackend(detect_games=True)
    try:
        assert wait_for(lambda: backend.jobs.running == 0)
        assert seen["thread"] is not threading.main_thread()
        assert backend._running == set(backend_games[:1])
    finally:
        backend.stop_previews()
        backend.deleteLater()


def test_setup_games_detection_failure(ui_env, renders, monkeypatch, caplog):  # noqa: F811
    from neopedal.ui.quick import setup_backend

    def denied():
        raise PermissionError("denied")

    monkeypatch.setattr(setup_backend, "running_games", denied)
    with caplog.at_level(logging.DEBUG, logger=setup_backend.logger.name):
        backend = setup_backend.SetupBackend(detect_games=True)
        try:
            assert wait_for(lambda: backend.jobs.running == 0)
        finally:
            backend.stop_previews()
            backend.deleteLater()
    assert backend._running == set() and "game detection failed: denied" in caplog.text


def test_update_download_is_a_job(updates, monkeypatch, messages):  # noqa: F811
    from neopedal.ui import notification

    seen = {}

    def download(asset, progress=None, cancelled=None):
        seen["thread"] = threading.current_thread().name
        progress(5, 10)
        return "Setup.exe"

    def installed(path, error):
        seen["installed"] = (threading.current_thread(), path, error)
        updates.busy = False

    monkeypatch.setattr(notification, "download_installer", download)
    monkeypatch.setattr(updates, "install_downloaded", installed)
    assert not hasattr(notification.UpdateInstaller, "downloaded")
    assert updates.download()
    assert wait_for(lambda: "installed" in seen)
    assert seen["thread"] == "Update download"
    assert seen["installed"] == (threading.main_thread(), "Setup.exe", "")
    assert wait_for(lambda: updates.received == 5)  # progress signal of the download thread
