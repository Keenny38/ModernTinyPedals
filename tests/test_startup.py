"""App startup & reload: single instance check, environment, restart command, load order"""

import os
import sys
from types import SimpleNamespace

import pytest

from neopedal import loader, main, realtime_state
from neopedal.setting import cfg


# --- Single instance (OS lock, see test_core_bugfixes_2026_10_18 for the lock itself)
def test_single_instance_modes(ui_env, monkeypatch):
    waits = []
    monkeypatch.setattr(main, "acquire_instance_lock", lambda wait=0.0: waits.append(wait) or True)
    monkeypatch.setattr(realtime_state, "singleton", False)
    main.single_instance_check(False)
    assert not realtime_state.singleton and waits == []  # no lock taken
    monkeypatch.setenv("NEOPEDAL_RESTART", "TRUE")  # restarted: waits for previous instance to exit
    main.single_instance_check(True)
    assert realtime_state.singleton and waits == [main.INSTANCE_LOCK_RESTART_WAIT]
    assert "NEOPEDAL_RESTART" not in os.environ
    main.single_instance_check(True)  # first instance
    assert waits[-1] == 0.0


def test_second_instance_exits(ui_env, monkeypatch):
    shown = []
    monkeypatch.setattr(main, "acquire_instance_lock", lambda wait=0.0: False)
    monkeypatch.setattr(main, "QApplication", lambda args: SimpleNamespace(setWindowIcon=lambda icon: None,
                                                                            setDesktopFileName=lambda name: None))
    monkeypatch.setattr(main.QMessageBox, "warning", lambda *args: shown.append(args[2]))
    with pytest.raises(SystemExit):
        main.single_instance_check(True)
    assert "already running" in shown[0]


# --- Environment
def test_environment_set_and_unset(ui_env, monkeypatch):
    for name in ("QT_QPA_PLATFORM", "QT_ENABLE_HIGHDPI_SCALING", "QT_MEDIA_BACKEND"):
        monkeypatch.setenv(name, "x")
    main.unset_environment()
    assert "QT_ENABLE_HIGHDPI_SCALING" not in os.environ and "QT_MEDIA_BACKEND" not in os.environ
    monkeypatch.setitem(cfg.application, "enable_high_dpi_scaling", False)
    main.set_environment()
    assert os.environ["QT_ENABLE_HIGHDPI_SCALING"] == "0"
    if main.PLATFORM.WINDOWS:
        assert os.environ["QT_QPA_PLATFORM"].startswith("windows")
    main.unset_environment()


def test_app_font_size_and_version_log(ui_env, caplog):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    font = app.font()
    try:
        main.set_app_font(app)
        assert app.font().pointSize() == 10
        with caplog.at_level("INFO", logger="neopedal"):
            main.get_version()
        assert "Python" in caplog.text and "Qt" in caplog.text
    finally:
        app.setFont(font)


# --- Restart & reload
def test_restart_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "--log-level", "2"])
    monkeypatch.setattr(sys, "executable", "C:/Python/python.exe")
    assert loader.restart_command() == ["C:/Python/python.exe", "run.py", "--log-level", "2"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/App/neopedal.exe")
    assert loader.restart_command() == ["C:/App/neopedal.exe", "--log-level", "2"]


@pytest.fixture
def controls(ui_env, monkeypatch):
    """Record start & stop calls of every control loaded by loader"""
    calls = []

    def control(name):
        return SimpleNamespace(**{
            action: (lambda *args, _action=action: calls.append(f"{name}.{_action}"))
            for action in ("enable", "disable", "start", "close", "stop", "restart", "connect")
        })

    for name in ("octrl", "mctrl", "wctrl", "kctrl", "cmdserver", "webdashboard", "api"):
        monkeypatch.setattr(loader, name, control(name))
    vr = control("vr")
    monkeypatch.setattr(loader, "vroverlay", lambda: vr)
    monkeypatch.setattr(type(cfg), "flush", lambda self: calls.append("cfg.flush"))
    return calls


def test_reload_order(controls):
    loader.reload()
    # Saving finished, everything stopped (widgets before modules), api restarted, then started again
    assert controls[0] == "cfg.flush"
    assert controls.index("wctrl.close") < controls.index("mctrl.close") < controls.index("octrl.disable")
    assert controls.index("octrl.disable") < controls.index("api.restart") < controls.index("octrl.enable")
    assert controls.index("mctrl.start") < controls.index("wctrl.start")


def test_reload_preset_saves_stopped_modules_data_before_loading(controls, monkeypatch):
    """Track info saved by stopping modules written before preset files are loaded again"""
    monkeypatch.setattr(type(cfg), "load_user", lambda self: controls.append("cfg.load_user"))
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(loader, "sync_screen_layout", lambda: None)
    loader.reload(reload_preset=True)
    assert controls.index("mctrl.close") < controls.index("cfg.flush", 1) < controls.index("cfg.load_user")


def test_close_stops_api_after_modules(controls):
    loader.close()
    assert controls.index("mctrl.close") < controls.index("api.stop") < controls.index("api.close")


def test_close_finishes_replay_recording(controls, monkeypatch):
    """Manual replay recording gets its trailer on quit (recorder module only stops automatic ones)"""
    monkeypatch.setattr(loader.replay, "stop_recording", lambda: controls.append("replay.stop_recording"))
    loader.close()
    assert controls.index("mctrl.close") < controls.index("replay.stop_recording") < controls.index("api.stop")


def test_restart_waits_for_lap_saving(controls, monkeypatch):
    """Restart exits the process at once: laps still being written must be finished first"""
    monkeypatch.setattr(loader.replay, "stop_recording", lambda: None)
    monkeypatch.setattr(loader, "wait_lap_saver", lambda timeout: controls.append("wait_lap_saver") or True)
    monkeypatch.setattr(loader.subprocess, "Popen", lambda *args, **kwargs: controls.append("launch"))
    monkeypatch.setattr(loader.os, "_exit", lambda code: controls.append("exit"))
    monkeypatch.setattr(loader.os, "execv", lambda *args: controls.append("exit"))
    monkeypatch.setattr(loader.logging, "shutdown", lambda: None)
    monkeypatch.setenv("NEOPEDAL_RESTART", "")
    loader.restart()
    assert controls.index("api.close") < controls.index("wait_lap_saver") < controls.index("exit")


def test_restart_failure_reloads_app(controls, monkeypatch):
    """Relaunch failed (exe moved or blocked): app reloaded and kept running, no exit"""
    def blocked(*args, **kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(loader.replay, "stop_recording", lambda: None)
    monkeypatch.setattr(loader, "wait_lap_saver", lambda timeout: True)
    monkeypatch.setattr(loader.subprocess, "Popen", blocked)
    monkeypatch.setattr(loader.os, "execv", blocked)
    monkeypatch.setattr(loader.os, "_exit", lambda code: controls.append("exit"))
    monkeypatch.setattr(loader.logging, "shutdown", lambda: None)
    monkeypatch.setenv("NEOPEDAL_RESTART", "")
    loader.restart()
    assert "exit" not in controls and "NEOPEDAL_RESTART" not in os.environ
    assert controls.index("api.close") < controls.index("api.connect") < controls.index("api.start")
    assert controls.index("api.start") < controls.index("mctrl.start")


def test_api_stop_after_close():
    """close() run again (quit after failed restart): stopping closed API is no error"""
    from neopedal.api_control import APIControl

    control = APIControl()
    control.close()
    control.stop()


def test_screen_layout_sync_optional(controls, monkeypatch):
    from neopedal.userfile import layout_profile

    synced = []
    monkeypatch.setattr(layout_profile, "sync_layout", lambda *args: synced.append(args) or False)
    monkeypatch.setitem(cfg.application, "enable_layout_per_screen_setup", False)
    loader.sync_screen_layout()
    assert not synced
    monkeypatch.setitem(cfg.application, "enable_layout_per_screen_setup", True)
    loader.sync_screen_layout()
    assert synced
