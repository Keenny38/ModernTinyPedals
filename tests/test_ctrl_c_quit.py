"""Ctrl+C in console quits like the Quit menu, game logos never reload themselves (binding loop)"""

import re
import signal
from pathlib import Path

import pytest

from neopedal import app_signal, loader
from neopedal.ui.quick import qml_path


def test_ctrl_c_quits_through_main_window(monkeypatch):
    """Main window connected: its quit_app runs (QML unloaded first), loader not closed under it"""
    calls = []
    monkeypatch.setattr(loader, "close", lambda: calls.append("close"))

    def quit_app():
        calls.append("quit_app")

    app_signal.quitapp.connect(quit_app)
    try:
        loader.int_signal_handler(signal.SIGINT, None)
    finally:
        app_signal.quitapp.disconnect(quit_app)
    assert calls == ["quit_app"]


def test_ctrl_c_without_window_closes_and_exits(monkeypatch):
    calls = []
    monkeypatch.setattr(loader, "close", lambda: calls.append("close"))
    with pytest.raises(SystemExit):
        loader.int_signal_handler(signal.SIGINT, None)
    assert calls == ["close"]


def test_game_logo_mipmap_not_bound():
    """A mipmap change reloads an Image: bound to its own size, it loops (status, shown, width)"""
    text = Path(qml_path("GameLogo.qml")).read_text(encoding="utf-8")
    code = "\n".join(line.split("//")[0] for line in text.splitlines())
    assert not re.search(r"^\s*mipmap\s*:", code, re.MULTILINE)
