"""Pytest shared setup"""

import faulthandler
import os
import sys
import tempfile

import pytest

# Run from repository root, headless Qt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Global config folder (and its legacy folder migration) in a temp folder, before any app import
_USER_BASE = tempfile.mkdtemp(prefix="tp_user_base_")
for _name in ("APPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
    os.environ[_name] = os.path.join(_USER_BASE, _name.lower())
    os.makedirs(os.environ[_name])

from PySide6.QtWidgets import QApplication

# QApplication must exist before collecting tests, as UI modules read font metrics on import
QT_APP = QApplication.instance() or QApplication(sys.argv)
SESSION: list[pytest.Session] = []  # test session, its exit status ends the process (pytest_unconfigure)



@pytest.fixture(scope="session", autouse=True)
def isolated_user_paths(tmp_path_factory):
    """Every user data path in a temp folder for whole test session

    Tests without ui_env (benchmark, widgets) may still save presets (new brake or compound
    found...): never in repository folder or real user config.
    """
    from neopedal.setting import FilePath, cfg

    root = tmp_path_factory.mktemp("user_paths")
    saved = {name: getattr(cfg.path, name) for name in FilePath.__slots__}
    for name in FilePath.__slots__:
        folder = root / name
        folder.mkdir()
        setattr(cfg.path, name, f"{folder.as_posix()}/")
    yield root
    for name, value in saved.items():
        setattr(cfg.path, name, value)


@pytest.fixture(scope="session", autouse=True)
def fonts_like_app():
    """Bundled fonts (Barlow...) loaded before the first window, as the app does (main.load_bundled_fonts
    runs before AppWindow): font choices cached at the first window (display font, button label metrics)
    are the same in every test order. Loaded after a main window was built, a hidden probe button and the
    shown button of a toolbar measured their label a pixel or two apart (test_audit_i_g1)."""
    from neopedal.main import load_bundled_fonts

    load_bundled_fonts()


@pytest.fixture(scope="session", autouse=True)
def quit_like_app(isolated_user_paths):
    """Session end does what app exit does: lap viewer worker process stopped, lap & setting saving finished

    Left running, interpreter exit waits for them (Windows, Python 3.11 runner hung 30 minutes after the
    last test). Torn down before user paths are restored: nothing saved to real user folders.
    """
    yield
    # Session end or exit still stuck: stack of every thread printed (real stderr, not pytest capture) and run
    # stopped, instead of blocking until job timeout
    faulthandler.dump_traceback_later(120, exit=True, file=sys.__stderr__)
    lap_backend = sys.modules.get("neopedal.ui.quick.lap_backend")
    if lap_backend is not None:
        lap_backend.quit_workers()
    module_recorder = sys.modules.get("neopedal.module.module_recorder")
    if module_recorder is not None:
        module_recorder.LAP_SAVER.shutdown(wait=True, cancel_futures=True)
    data_saver = sys.modules.get("neopedal.userfile.data_saver")
    if data_saver is not None:
        data_saver.DATA_SAVER.shutdown(wait=True, cancel_futures=True)
    from neopedal.setting import cfg

    cfg.flush()


def pytest_sessionstart(session):
    SESSION.append(session)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """Process ended with pytest exit status once pytest has reported (results, coverage files written)

    Interpreter exit hung on Windows runners after every test passed (Python 3.11, then 3.13: 30+ minutes,
    randomly). What still runs is printed first, to find what holds exit.
    """
    if not SESSION:
        return
    import multiprocessing
    import threading

    threads = [thread for thread in threading.enumerate() if thread is not threading.main_thread()]
    alive = [f"thread {thread.name}" for thread in threads if not thread.daemon]
    # Daemon threads never hold exit, but a lingering one shows a worker a test (or the app) did not stop
    alive += [f"daemon thread {thread.name}" for thread in threads if thread.daemon]
    alive += [f"process {child.name} (pid {child.pid})" for child in multiprocessing.active_children()]
    if alive:
        print("Still running at exit: " + ", ".join(alive), file=sys.__stderr__)
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        if stream is not None:
            stream.flush()
    os._exit(int(SESSION[0].exitstatus))


@pytest.fixture(autouse=True)
def no_openxr_registration(monkeypatch):
    """VR overlay never registers the OpenXR layer in the real registry nor opens the real shared memory
    (Windows): tests mock both (test_vr_shared.py)"""
    from neopedal import vr_shared

    monkeypatch.setattr(vr_shared, "WINDOWS", False)


@pytest.fixture(autouse=True)
def offline_lap_reference(monkeypatch):
    """Community lap times never downloaded in tests (tests feed sheet text themselves)"""
    from neopedal.userfile import lap_reference

    def offline(url, timeout=15):
        raise OSError("offline in tests")

    monkeypatch.setattr(lap_reference, "fetch_sheet", offline)


@pytest.fixture(autouse=True)
def offline_track_geometry(monkeypatch):
    """Official circuit never asked to a running game in tests (tests feed game answers themselves)"""
    from neopedal.userfile import track_geometry

    monkeypatch.setattr(track_geometry, "rest_get", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def offline_rest_cache(monkeypatch):
    """Shared game REST cache never asks a running game, no answer carried from one test to the next"""
    from neopedal.game_rest_cache import rest_cache

    monkeypatch.setattr(rest_cache, "fetch", lambda *args, **kwargs: (0, b""))
    rest_cache.forget()
    yield
    rest_cache.forget()


@pytest.fixture(autouse=True)
def offline_online_ranks(monkeypatch):
    """Online ranks (on by default) never ask a running game for a Steam ticket nor sign in to RaceControl
    in tests (tests feed online sources themselves)"""
    from neopedal import rank_info

    monkeypatch.setattr(rank_info, "_game_get", lambda *args, **kwargs: (0, b""))


@pytest.fixture(autouse=True)
def offline_game_images(monkeypatch):
    """Car brand & circuit pictures never asked to a running game in tests, fetch thread ended after each test

    Thread of app cache (started by first lookup) lives as long as the app; tests replacing the cache
    (monkeypatch, set up before this fixture: still replaced at teardown) would leave one thread each.
    """
    from neopedal.userfile import game_images

    monkeypatch.setattr(game_images, "fetch_from_game", lambda *args, **kwargs: (0, b""))
    app_cache = game_images.images
    yield
    for cache in {id(cache): cache for cache in (game_images.images, app_cache)}.values():
        assert cache.stop(), "game images fetch thread not ended"


@pytest.fixture
def ui_env(monkeypatch, tmp_path):
    """Isolated setting for UI tests: default presets, data paths in tmp folder, saving disabled"""
    from neopedal.setting import FilePath, Preset, Setting, cfg
    from neopedal.userfile.json_setting import copy_setting

    # Real save left running by a previous test finished first: while is_saving, run_after_saving
    # defers reloads past the end of the test
    cfg.flush()
    cfg.default.set_default()
    for name in Preset.__slots__:
        monkeypatch.setattr(cfg.user, name, copy_setting(dict(getattr(cfg.default, name))), raising=False)
    for name in FilePath.__slots__:
        folder = tmp_path / name
        folder.mkdir()
        monkeypatch.setattr(cfg.path, name, f"{folder.as_posix()}/")
    (tmp_path / "settings" / "default.json").write_text("{}", encoding="utf-8")
    # API connected but not started, reader returns neutral values
    from neopedal.api_control import api

    api.connect()
    monkeypatch.setattr(api, "read", _FakeReader())
    # No game found in Steam libraries: pages never read results files & profile of this computer
    from neopedal.process import results_file

    monkeypatch.setattr(results_file, "find_results_folders", lambda libraries=None: {})
    saved = []
    monkeypatch.setattr(Setting, "save", lambda self, *args, **kwargs: saved.append(kwargs.get("config_type", "setting")))
    return saved


_TEXT_READERS = ("version", "track_name", "combo_name", "class_name", "driver_name", "vehicle_name")
# Readers whose tuple length the annotation does not give: `tuple[float, ...]` says "a set",
# not how many. Four is the wheel count and covers every other variadic reader but this one.
_WHEEL_COUNT = 4
_VARIADIC_LENGTHS = {"surface_temperature_ico": 12, "inner_temperature_ico": 12}
_NEUTRAL = {"str": "", "bool": False, "int": 0, "float": 0.0}


def _neutral_value(annotation: str, name: str):
    """Build a neutral return value matching a reader's annotated return type

    Shapes come from the real reader's annotations rather than a hand-kept list, so a new
    reader, or one that changes shape, cannot silently hand widgets the wrong type here.
    """
    if name in _TEXT_READERS:
        return "test"
    annotation = annotation.strip()
    if annotation.startswith("tuple["):
        args = [arg.strip() for arg in annotation[6:-1].split(",")]
        element = args[0]
        if element not in _NEUTRAL:  # WeatherNode and friends, nothing neutral to build
            return ()
        if args[-1] == "...":
            length = _VARIADIC_LENGTHS.get(name, _WHEEL_COUNT)
        else:
            length = len(args)
        return (_NEUTRAL[element],) * length
    if annotation == "Penalty":
        from neopedal.penalty_info import NO_PENALTY

        return NO_PENALTY
    return _NEUTRAL.get(annotation, 0)


class _FakeGroup:
    """API reader group, any method returns a neutral value of the expected shape"""

    def __init__(self, group_type: type | None = None):
        self._returns = {}
        for name, member in vars(group_type or object).items():
            if name.startswith("_") or not callable(member):
                continue
            annotation = getattr(member, "__annotations__", {}).get("return", "")
            self._returns[name] = _neutral_value(str(annotation), name)

    def __getattr__(self, name):
        value = self._returns.get(name, 0)
        return lambda *args, **kwargs: value


class _FakeReader:
    """API reader (no game running)

    Groups are cached, so tests can monkeypatch a single reader (api.read.tyre.wear, ...).
    """

    def __getattr__(self, name):
        from neopedal.adapter import APIDataReader

        group = _FakeGroup(APIDataReader.__annotations__.get(name))
        setattr(self, name, group)  # cache, so the same object is returned next time
        return group


class ContextSwap:
    """App globals (neopedal.context.GLOBALS) replaced by fakes in every loaded neopedal module & the default
    context, all put back by restore (modules imported meanwhile too): no fake left behind for the next test"""

    def __init__(self):
        self.swapped: list[tuple[object, str, object]] = []  # module, name, real value
        self.fakes: dict[int, tuple[object, object]] = {}  # id of fake: fake (kept alive), real value
        self.previous = None
        self.active = False

    def use(self, **fakes):
        """Fakes given by context field name (api, cfg, minfo, mctrl, wctrl, octrl): context of the test returned"""
        from neopedal import context

        unknown = set(fakes) - set(context.GLOBALS)
        if unknown:
            raise TypeError(f"not app context fields: {sorted(unknown)}")
        real = context.real_context()
        for name, fake in fakes.items():
            value = getattr(real, name)
            self.fakes[id(fake)] = (fake, value)
            for module in _app_modules():
                for attribute, current in list(vars(module).items()):
                    if current is value:
                        setattr(module, attribute, fake)
                        self.swapped.append((module, attribute, value))
        ctx = real.with_(**fakes)
        previous = context.set_app_context(ctx)
        if not self.active:
            self.previous, self.active = previous, True
        return ctx

    def restore(self):
        from neopedal import context

        for module, attribute, value in reversed(self.swapped):
            setattr(module, attribute, value)
        for module in _app_modules():  # imported during the test: bound the fake
            for attribute, current in list(vars(module).items()):
                pair = self.fakes.get(id(current))
                if pair is not None and pair[0] is current:
                    setattr(module, attribute, pair[1])
        if self.active:
            context.set_app_context(self.previous)
        self.swapped.clear()
        self.fakes.clear()
        self.active = False


def _app_modules():
    return [module for name, module in list(sys.modules.items())
            if module is not None and (name == "neopedal" or name.startswith("neopedal."))]


@pytest.fixture
def app_ctx():
    """Fake app objects for a test: `ctx = app_ctx(mctrl=fake, wctrl=other)` swaps the globals everywhere
    (module globals of every neopedal module, default app_context()) and puts the real ones back after the test,
    modules imported meanwhile included. Prefer it to monkeypatching one module's copy of a global: code reading
    the same object from another module would still reach the real one (real overlays or modules started)."""
    swap = ContextSwap()
    yield swap.use
    swap.restore()


@pytest.fixture
def fake_context(app_ctx):
    """Same as app_ctx"""
    return app_ctx


@pytest.fixture(scope="session")
def bundled_fonts():
    """Bundled fonts (Barlow...) loaded once: widgets render & size text as in the app, on every platform"""
    from neopedal.main import load_bundled_fonts

    load_bundled_fonts()
