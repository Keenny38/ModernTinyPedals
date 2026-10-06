"""App startup & reload: single instance PID file, environment, restart command, load order"""

import os
import sys
from types import SimpleNamespace

import pytest

from tinypedal import loader, main, realtime_state
from tinypedal.setting import cfg


# --- Single instance (PID file)
def test_pid_file_of_running_app(ui_env):
    main.save_pid_file()
    assert main.is_pid_exist()  # this process, same creation time


@pytest.mark.parametrize("content", ["", "not a pid", "999999999,0", f"{os.getpid()},12345.0"])
def test_pid_file_stale_or_invalid(ui_env, content):
    from tinypedal.const_file import LogFile

    with open(f"{cfg.path.config}{LogFile.PID}", "w", encoding="utf-8") as file:
        file.write(content)
    assert not main.is_pid_exist()  # other process, reused PID or broken file


def test_pid_file_unwritable_or_locked(ui_env, monkeypatch, caplog):
    """Locked pid file or read-only config folder: no crash at launch"""
    def locked(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(main, "open", locked, raising=False)
    with caplog.at_level("WARNING", logger="tinypedal"):
        main.save_pid_file()
    assert "PID file not saved" in caplog.text
    assert not main.is_pid_exist()


def test_single_instance_modes(ui_env, monkeypatch):
    from tinypedal.const_file import LogFile

    pid_file = f"{cfg.path.config}{LogFile.PID}"
    monkeypatch.setattr(realtime_state, "singleton", False)
    main.single_instance_check(False)
    assert not realtime_state.singleton and not os.path.exists(pid_file)
    monkeypatch.setenv("TINYPEDAL_RESTART", "TRUE")  # restarted: no check, PID saved
    main.single_instance_check(True)
    assert realtime_state.singleton and os.path.exists(pid_file) and "TINYPEDAL_RESTART" not in os.environ
    os.remove(pid_file)
    main.single_instance_check(True)  # first instance
    assert os.path.exists(pid_file)


def test_second_instance_exits(ui_env, monkeypatch):
    shown = []
    monkeypatch.setattr(main, "is_pid_exist", lambda: True)
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
        with caplog.at_level("INFO", logger="tinypedal"):
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
    monkeypatch.setattr(sys, "executable", "C:/App/tinypedal.exe")
    assert loader.restart_command() == ["C:/App/tinypedal.exe", "--log-level", "2"]


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
    monkeypatch.setenv("TINYPEDAL_RESTART", "")
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
    monkeypatch.setenv("TINYPEDAL_RESTART", "")
    loader.restart()
    assert "exit" not in controls and "TINYPEDAL_RESTART" not in os.environ
    assert controls.index("api.close") < controls.index("api.connect") < controls.index("api.start")
    assert controls.index("api.start") < controls.index("mctrl.start")


def test_api_stop_after_close():
    """close() run again (quit after failed restart): stopping closed API is no error"""
    from tinypedal.api_control import APIControl

    control = APIControl()
    control.close()
    control.stop()


def test_screen_layout_sync_optional(controls, monkeypatch):
    from tinypedal.userfile import layout_profile

    synced = []
    monkeypatch.setattr(layout_profile, "sync_layout", lambda *args: synced.append(args) or False)
    monkeypatch.setitem(cfg.application, "enable_layout_per_screen_setup", False)
    loader.sync_screen_layout()
    assert not synced
    monkeypatch.setitem(cfg.application, "enable_layout_per_screen_setup", True)
    loader.sync_screen_layout()
    assert synced
