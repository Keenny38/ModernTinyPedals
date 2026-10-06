"""Overlay control: global state from game, auto hide, visibility context, preset auto loading"""

from types import SimpleNamespace

import pytest

from tinypedal import overlay_control, realtime_state, thread_guard
from tinypedal.overlay_control import OverlayControl, OverlayToggle


class StopAfter:
    """Event replacement: wait() returns False (keep running) a number of times, then True"""

    def __init__(self, runs: int):
        self.runs = runs

    def wait(self, timeout=None) -> bool:
        self.runs -= 1
        return self.runs < 0


def recorder(calls: list, name: str):
    return SimpleNamespace(emit=lambda *args: calls.append((name, *args)))


@pytest.fixture
def overlay(ui_env, monkeypatch):
    """Overlay control with signals recorded and game state set by test"""
    from tinypedal.api_control import api

    calls: list = []
    monkeypatch.setattr(overlay_control, "overlay_signal", SimpleNamespace(**{
        name: recorder(calls, name) for name in ("hidden", "context", "locked", "paused", "iconify")}))
    monkeypatch.setattr(overlay_control, "app_signal", SimpleNamespace(reload=recorder(calls, "reload")))
    for name in ("active", "paused", "resets", "hidden", "session_type", "in_pits"):
        monkeypatch.setattr(realtime_state, name, getattr(realtime_state, name))
    game = {"active": True, "paused": False, "resets": 3, "session_type": 4, "in_pits": False,
            "track": "Spa", "class": "GT3"}
    monkeypatch.setattr(api.read.state, "active", lambda: game["active"], raising=False)
    monkeypatch.setattr(api.read.state, "paused", lambda: game["paused"], raising=False)
    monkeypatch.setattr(api.read.state, "resets", lambda: game["resets"], raising=False)
    monkeypatch.setattr(api.read.session, "session_type", lambda: game["session_type"], raising=False)
    monkeypatch.setattr(api.read.session, "track_name", lambda: game["track"], raising=False)
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda: game["in_pits"], raising=False)
    monkeypatch.setattr(api.read.vehicle, "in_garage", lambda: False, raising=False)
    monkeypatch.setattr(api.read.vehicle, "class_name", lambda: game["class"], raising=False)
    control = OverlayControl()
    return control, game, calls


def run_loop(control: OverlayControl, runs: int = 1):
    control._OverlayControl__update_loop(StopAfter(runs))


def test_state_read_from_game(overlay):
    from tinypedal.setting import cfg

    control, game, calls = overlay
    cfg.overlay["auto_hide"] = True
    run_loop(control)
    assert (realtime_state.active, realtime_state.paused, realtime_state.resets) == (True, False, 3)
    assert (realtime_state.session_type, realtime_state.in_pits) == (4, False)
    assert ("hidden", False) in calls and ("context",) in calls and ("paused", False) in calls
    # Back to menu: hidden, overlay timer paused, no session
    calls.clear()
    game["active"] = False
    run_loop(control)
    assert ("hidden", True) in calls and ("paused", True) in calls
    assert realtime_state.session_type == -1


def test_state_signals_sent_on_change_only(overlay):
    control, game, calls = overlay
    run_loop(control, runs=3)
    assert [call for call in calls if call[0] == "paused"] == [("paused", False)]
    assert len([call for call in calls if call[0] == "context"]) == 1
    calls.clear()
    game["in_pits"] = True  # visibility context changed
    run_loop(control)
    assert ("context",) in calls and realtime_state.in_pits


def test_track_preset_auto_loaded_once(overlay, monkeypatch):
    from tinypedal.setting import cfg

    control, _game, calls = overlay
    cfg.application["enable_auto_load_preset"] = True
    open(f"{cfg.path.settings}spa race.json", "w", encoding="utf-8").close()
    monkeypatch.setitem(cfg.user.tracks, "Spa", {"preset": "spa race"})
    monkeypatch.setattr(cfg, "_setting_to_load", "")
    run_loop(control, runs=2)
    assert cfg._setting_to_load == "spa race.json" and calls.count(("reload", False)) == 1


def test_class_preset_auto_loaded_without_track_preset(overlay, monkeypatch):
    from tinypedal.setting import cfg

    control, game, calls = overlay
    cfg.application["enable_auto_load_preset"] = True
    open(f"{cfg.path.settings}gt3.json", "w", encoding="utf-8").close()
    monkeypatch.setitem(cfg.user.classes, "GT3", {**cfg.user.classes.get("GT3", {}), "preset": "gt3"})
    monkeypatch.setattr(cfg, "_setting_to_load", "")
    run_loop(control)
    assert cfg._setting_to_load == "gt3.json" and calls.count(("reload", False)) == 1
    # Already loaded: not loaded again
    monkeypatch.setattr(cfg.filename, "setting", "gt3.json")
    game["active"] = False
    run_loop(control)
    game["active"] = True
    run_loop(control)
    assert calls.count(("reload", False)) == 1


def test_missing_preset_not_loaded(overlay, monkeypatch):
    from tinypedal.setting import cfg

    control, _game, calls = overlay
    cfg.application["enable_auto_load_preset"] = True
    monkeypatch.setitem(cfg.user.tracks, "Spa", {"preset": "deleted preset"})
    monkeypatch.setitem(cfg.user.classes, "GT3", {**cfg.user.classes.get("GT3", {}), "preset": "deleted"})
    run_loop(control)
    assert ("reload", False) not in calls


def test_overlay_toggles(ui_env, monkeypatch):
    from tinypedal.setting import cfg

    calls: list = []
    monkeypatch.setattr(overlay_control, "overlay_signal", SimpleNamespace(
        locked=recorder(calls, "locked"), iconify=recorder(calls, "iconify")))
    toggle = OverlayToggle()
    for name, option in (("lock", "fixed_position"), ("vr", "vr_compatibility"),
                         ("hide", "auto_hide"), ("grid", "enable_grid_move")):
        before = cfg.overlay[option]
        getattr(toggle, name)()
        assert cfg.overlay[option] is not before, name
    assert [call[0] for call in calls] == ["locked", "iconify"]


def test_enable_and_disable_thread(overlay, monkeypatch):
    control, _game, _calls = overlay
    monkeypatch.setattr(overlay_control, "run_supervised", lambda target, name, event: event.wait(5))
    control.enable()
    assert not control._stopped()
    control.disable()  # stops thread
    assert control._stopped()


def test_disable_gives_up_on_stuck_thread(overlay, monkeypatch, caplog):
    control, _game, _calls = overlay
    monkeypatch.setattr(thread_guard, "STOP_TIMEOUT", 0.05)
    control._thread = SimpleNamespace(is_alive=lambda: True)  # thread never stops
    control.disable()  # returns anyway
    assert "not stopped" in caplog.text


def test_enable_after_stuck_thread_starts_new_thread(overlay, monkeypatch):
    """Thread outliving disable(): enable() starts a new one, old one keeps its own (set) stop event"""
    import threading

    control, _game, _calls = overlay
    release = threading.Event()
    monkeypatch.setattr(thread_guard, "STOP_TIMEOUT", 0.05)
    monkeypatch.setattr(overlay_control, "run_supervised", lambda target, name, event: release.wait(5))
    control.enable()
    old_thread, old_event = control._thread, control._event
    control.disable()  # gives up, thread still running
    assert old_thread.is_alive()
    control.enable()
    assert control._thread is not old_thread and control._thread.is_alive()
    assert old_event.is_set() and not control._event.is_set()
    new_thread = control._thread
    control.enable()  # already running: no other thread
    assert control._thread is new_thread
    release.set()
    old_thread.join(5)
    control._thread.join(5)
    assert control._stopped()
