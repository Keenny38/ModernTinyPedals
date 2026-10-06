"""Safe mode: start after a crash at startup (marker file), command line flag, plugins & overlays off"""

import json
import os
import sys
from types import SimpleNamespace

import psutil
import pytest

from tinypedal import loader, main, plugin_loader, safe_mode
from tinypedal.setting import cfg


@pytest.fixture(autouse=True)
def normal_mode(monkeypatch):
    """Every test starts in normal mode, state restored after"""
    monkeypatch.setattr(safe_mode, "state", safe_mode.SafeModeState())
    return safe_mode.state


def write_stamp(folder: str, text: str):
    with open(safe_mode.marker_path(folder), "w", encoding="utf-8") as file:
        file.write(text)


# --- Startup marker
def test_no_marker_is_a_normal_start(tmp_path):
    assert not safe_mode.unfinished_start(f"{tmp_path}/")


def test_marker_of_process_gone_is_unfinished_start(tmp_path):
    folder = f"{tmp_path}/"
    write_stamp(folder, "999999999,12345.0")
    assert safe_mode.unfinished_start(folder)
    write_stamp(folder, "not a pid")
    assert safe_mode.unfinished_start(folder)


def test_marker_of_running_instance_is_not_a_crash(tmp_path):
    """Another instance still starting (multiple instances allowed)"""
    folder = f"{tmp_path}/"
    parent = psutil.Process().ppid()
    write_stamp(folder, safe_mode.process_stamp(parent))
    assert not safe_mode.unfinished_start(folder)
    write_stamp(folder, f"{parent},1.0")  # same id, other process (id reused)
    assert safe_mode.unfinished_start(folder)


def test_marker_written_and_cleared(tmp_path):
    folder = f"{tmp_path}/"
    safe_mode.write_marker(folder)
    with open(safe_mode.marker_path(folder), encoding="utf-8") as file:
        assert file.read() == safe_mode.process_stamp(os.getpid())
    safe_mode.clear_marker(folder)
    assert not os.path.exists(safe_mode.marker_path(folder))
    safe_mode.clear_marker(folder)  # already removed: nothing happens


def test_marker_errors_only_logged(tmp_path, caplog):
    missing = f"{tmp_path}/missing/"
    safe_mode.write_marker(missing)
    assert "unable to write startup marker" in caplog.text


# --- Start: flag, question after unfinished start, never asked on a normal start
@pytest.fixture
def ask(ui_env, monkeypatch):
    asked = []

    def answer(value):
        monkeypatch.setattr(main, "ask_safe_mode", lambda: asked.append(True) or value)
    answer(True)
    return asked, answer


def test_normal_start_never_asks(ask):
    asked, _ = ask
    main.check_safe_mode(False)
    assert not asked and not safe_mode.state.enabled
    assert os.path.exists(safe_mode.marker_path(cfg.path.config))  # start under way


def test_unfinished_start_asks_safe_mode(ask):
    asked, _ = ask
    write_stamp(cfg.path.config, "999999999,1.0")
    main.check_safe_mode(False)
    assert asked and safe_mode.state.enabled and safe_mode.state.reason == "crash"
    # Marker of this start written: removed once started
    with open(safe_mode.marker_path(cfg.path.config), encoding="utf-8") as file:
        assert file.read() == safe_mode.process_stamp(os.getpid())


def test_unfinished_start_declined(ask, normal_mode):
    asked, answer = ask
    answer(False)
    write_stamp(cfg.path.config, "999999999,1.0")
    main.check_safe_mode(False)
    assert asked and not normal_mode.enabled


def test_flag_starts_safe_mode_without_question(ask, caplog):
    asked, _ = ask
    with caplog.at_level("WARNING"):
        main.check_safe_mode(True)
    assert not asked and safe_mode.state.enabled and safe_mode.state.reason == "flag"
    assert "SAFE MODE: ON" in caplog.text


def test_question_translated(ui_env, monkeypatch):
    from tinypedal.i18n import set_language

    shown = []
    monkeypatch.setattr(main.QMessageBox, "question", staticmethod(
        lambda parent, title, text, *args: shown.append(text) or main.QMessageBox.StandardButton.Yes))
    set_language("Français")
    try:
        assert main.ask_safe_mode()
    finally:
        set_language("English")
    assert "mode sans échec" in shown[0]


def test_safe_mode_decided_before_widgets_are_imported(ui_env, monkeypatch):
    """Loader imports widgets & plugins: safe mode known before"""
    calls = []
    for name in ("single_instance_check", "unset_environment", "set_logging_level", "get_version",
                 "set_environment"):
        monkeypatch.setattr(main, name, lambda *args, _name=name: calls.append(_name))
    monkeypatch.setattr(main, "check_safe_mode", lambda flag: calls.append(f"check_safe_mode {flag}"))
    monkeypatch.setattr(main, "init_gui", lambda: calls.append("init_gui") or SimpleNamespace(exec=lambda: 0))
    monkeypatch.setattr(type(cfg), "load_global", lambda self: None)
    monkeypatch.setattr(loader, "start", lambda: calls.append("loader.start"))
    with pytest.raises(SystemExit):
        main.start_app(SimpleNamespace(single_instance=1, log_level=1, safe_mode=True))
    assert calls.index("init_gui") < calls.index("check_safe_mode True") < calls.index("loader.start")


def test_command_line_flag(monkeypatch):
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "--safe-mode"])
    assert run.get_cli_argument().safe_mode
    monkeypatch.setattr(sys, "argv", ["run.py"])
    assert not run.get_cli_argument().safe_mode


# --- Plugins & overlays off, restart is a normal start
def test_plugin_code_not_run_in_safe_mode(tmp_path, monkeypatch, normal_mode):
    marker = tmp_path / "executed.txt"
    path = tmp_path / "sneaky"
    path.mkdir()
    (path / "setting.json").write_text(json.dumps({}), encoding="utf-8")
    (path / "widget.py").write_text(f"open({str(marker)!r}, 'w').close()\nRealtime = object", encoding="utf-8")
    monkeypatch.setattr(plugin_loader, "trust_filename", lambda: str(tmp_path / "trust.json"))
    plugin_loader.trust_plugin("plugin_sneaky", str(tmp_path))
    normal_mode.enable("flag")
    module = plugin_loader.load_plugin_widget("tinypedal.widget", "plugin_sneaky", str(tmp_path))
    assert not marker.exists() and module.Realtime.__doc__ == "Plugin error"
    assert plugin_loader.PLUGIN_ERRORS["plugin_sneaky"] == plugin_loader.SAFE_MODE_ERROR
    normal_mode.enabled = False
    plugin_loader.load_plugin_widget("tinypedal.widget", "plugin_sneaky", str(tmp_path))
    assert marker.exists() and "plugin_sneaky" not in plugin_loader.PLUGIN_ERRORS


@pytest.fixture
def controls(ui_env, monkeypatch):
    """Start & stop calls of every control loaded by loader, main window & timers recorded"""
    calls = []

    def control(name):
        return SimpleNamespace(**{
            action: (lambda *args, _action=action: calls.append(f"{name}.{_action}"))
            for action in ("enable", "disable", "start", "close", "stop", "restart", "connect", "check")
        })

    for name in ("octrl", "mctrl", "wctrl", "kctrl", "cmdserver", "webdashboard", "api", "update_checker"):
        monkeypatch.setattr(loader, name, control(name))
    vr = control("vr")
    monkeypatch.setattr(loader, "vroverlay", lambda: vr)
    monkeypatch.setattr(type(cfg), "flush", lambda self: calls.append("cfg.flush"))
    monkeypatch.setattr(type(cfg), "load_user", lambda self: calls.append("cfg.load_user"))
    monkeypatch.setattr(loader, "sync_screen_layout", lambda: None)
    monkeypatch.setattr(loader.signal, "signal", lambda *args: None)
    from tinypedal.ui import app

    monkeypatch.setattr(app, "AppWindow", lambda: calls.append("window") or None)
    from PySide6.QtCore import QTimer

    timers = []
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda delay, func: timers.append((delay, func))))
    return SimpleNamespace(calls=calls, timers=timers)


def test_normal_start_starts_overlays_and_clears_marker(controls):
    safe_mode.write_marker(cfg.path.config)
    loader.start()
    assert "wctrl.start" in controls.calls and "vr.enable" in controls.calls
    assert [delay for delay, _ in controls.timers] == [safe_mode.SETTLE_MS]  # no safe mode notice
    controls.timers[0][1]()  # window & overlays up
    assert not safe_mode.unfinished_start(cfg.path.config)


def test_safe_start_keeps_overlays_off(controls, normal_mode, monkeypatch):
    normal_mode.enable("crash")
    notices = []
    monkeypatch.setattr(loader, "show_safe_mode_notice", lambda window: notices.append(window))
    loader.start()
    assert "wctrl.start" not in controls.calls and "vr.enable" not in controls.calls
    assert "mctrl.start" in controls.calls and "window" in controls.calls  # data modules & window kept
    for _, func in controls.timers:
        func()
    assert notices == [None]
    loader.reload()  # preset loaded: overlays still off
    assert "wctrl.start" not in controls.calls and "vr.enable" not in controls.calls


def test_quit_before_start_finished_is_no_crash(controls):
    safe_mode.write_marker(cfg.path.config)
    loader.close()
    assert not os.path.exists(safe_mode.marker_path(cfg.path.config))


def test_restart_starts_normally(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "--safe-mode", "-l", "2"])
    monkeypatch.setattr(sys, "executable", "C:/Python/python.exe")
    assert loader.restart_command() == ["C:/Python/python.exe", "run.py", "-l", "2"]


def test_safe_mode_notice_restarts_normally(ui_env, monkeypatch):
    from PySide6.QtWidgets import QMainWindow, QMessageBox

    from tinypedal.i18n import tr

    window = QMainWindow()
    window.setWindowTitle("Modern Tiny Pedals")
    restarted = []
    window.restart_app = lambda: restarted.append(True)  # type: ignore[attr-defined]
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(
        button for button in self.buttons() if button.text() == tr("Restart Normally")))
    loader.show_safe_mode_notice(window)
    assert window.windowTitle().endswith("Safe Mode") and restarted
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)  # closed
    loader.show_safe_mode_notice(window)
    assert restarted == [True]
    window.deleteLater()
