"""Pytest shared setup"""

import faulthandler
import os
import sys

import pytest

# Run from repository root, headless Qt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

# QApplication must exist before collecting tests, as UI modules read font metrics on import
QT_APP = QApplication.instance() or QApplication(sys.argv)



@pytest.fixture(scope="session", autouse=True)
def isolated_user_paths(tmp_path_factory):
    """Every user data path in a temp folder for whole test session

    Tests without ui_env (benchmark, widgets) may still save presets (new brake or compound
    found...): never in repository folder or real user config.
    """
    from tinypedal.setting import FilePath, cfg

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
def quit_like_app(isolated_user_paths):
    """Session end does what app exit does: lap viewer worker process stopped, lap & setting saving finished

    Left running, interpreter exit waits for them (Windows, Python 3.11 runner hung 30 minutes after the
    last test). Torn down before user paths are restored: nothing saved to real user folders.
    """
    yield
    # Exit still hanging: stack of every thread printed and run stopped, instead of blocking until job timeout
    faulthandler.dump_traceback_later(120, exit=True)
    lap_backend = sys.modules.get("tinypedal.ui.quick.lap_backend")
    if lap_backend is not None:
        lap_backend.quit_workers()
    module_recorder = sys.modules.get("tinypedal.module.module_recorder")
    if module_recorder is not None:
        module_recorder.LAP_SAVER.shutdown(wait=True, cancel_futures=True)
    from tinypedal.setting import cfg

    cfg.flush()


@pytest.fixture(autouse=True)
def offline_lap_reference(monkeypatch):
    """Community lap times never downloaded in tests (tests feed sheet text themselves)"""
    from tinypedal.userfile import lap_reference

    def offline(url, timeout=15):
        raise OSError("offline in tests")

    monkeypatch.setattr(lap_reference, "fetch_sheet", offline)


@pytest.fixture(autouse=True)
def offline_track_geometry(monkeypatch):
    """Official circuit never asked to a running game in tests (tests feed game answers themselves)"""
    from tinypedal.userfile import track_geometry

    monkeypatch.setattr(track_geometry, "rest_get", lambda *args, **kwargs: None)


@pytest.fixture
def ui_env(monkeypatch, tmp_path):
    """Isolated setting for UI tests: default presets, data paths in tmp folder, saving disabled"""
    from tinypedal.setting import FilePath, Preset, Setting, cfg
    from tinypedal.userfile.json_setting import copy_setting

    cfg.default.set_default()
    for name in Preset.__slots__:
        monkeypatch.setattr(cfg.user, name, copy_setting(dict(getattr(cfg.default, name))), raising=False)
    for name in FilePath.__slots__:
        folder = tmp_path / name
        folder.mkdir()
        monkeypatch.setattr(cfg.path, name, f"{folder.as_posix()}/")
    (tmp_path / "settings" / "default.json").write_text("{}", encoding="utf-8")
    # API connected but not started, reader returns neutral values
    from tinypedal.api_control import api

    api.connect()
    monkeypatch.setattr(api, "read", _FakeReader())
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
        from tinypedal.adapter import APIDataReader

        group = _FakeGroup(APIDataReader.__annotations__.get(name))
        setattr(self, name, group)  # cache, so the same object is returned next time
        return group


@pytest.fixture(scope="session")
def bundled_fonts():
    """Bundled fonts (Barlow...) loaded once: widgets render & size text as in the app, on every platform"""
    from tinypedal.main import load_bundled_fonts

    load_bundled_fonts()
