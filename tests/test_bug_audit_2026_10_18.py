"""Bug audit 2026-10-18: one test per fix (numbers of the audit report)"""

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from neopedal.setting import cfg
from tests.test_game_info import replays_page  # noqa: F401 (fixture)
from tests.test_overlay_edit_mode import editing  # noqa: F401 (fixture)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- 1: overlay previews keep their own driving times, the running session's ones never reset
def test_stint_timer_preview_keeps_own_driver_times():
    from neopedal.demo_state import demo_drawing
    from neopedal.widget import stint_timer

    wcfg = {"maximum_stint_minutes": 60, "stint_warning_minutes": 5, "show_stint_laps": True,
            "show_stint_countdown": True, "show_driver_times": True, "number_of_drivers": 2,
            "minimum_driving_minutes": 0}
    live = SimpleNamespace(wcfg=wcfg)
    stint_timer.StintTimerMixin.setup_stint(live)
    assert live.driver_times is stint_timer.DRIVER_TIMES
    preview = SimpleNamespace(wcfg=wcfg)
    with demo_drawing(object()):
        stint_timer.StintTimerMixin.setup_stint(preview)
    assert preview.driver_times is not stint_timer.DRIVER_TIMES
    times = stint_timer.DRIVER_TIMES
    times.reset()
    times.update("live", 10.0, "Keenny", True)
    times.update("live", 12.0, "Keenny", True)
    preview.driver_times.update("demo", 500.0, "Demo Driver", True)  # preview tick: other session
    assert times.times == {"Keenny": 2.0}
    times.reset()


# --- 2: restored style backup never written over by styles in memory (saving paused, styles reloaded)
def test_restore_style_backup_pauses_style_saving(ui_env, monkeypatch):
    from neopedal.ui import preset_management

    monkeypatch.setattr(preset_management, "app_signal", SimpleNamespace(reload=SimpleNamespace(emit=lambda *a: None)))
    replaced = []

    @contextmanager
    def styles_replaced(self, timeout=10.0):
        replaced.append("start")
        yield
        replaced.append("end")

    monkeypatch.setattr(type(cfg), "styles_replaced", styles_replaced)
    folder = cfg.path.settings
    backup = "classes.json.backup-2026-10-18-12-00-00-000000"
    with open(f"{folder}{backup}", "w", encoding="utf-8") as file:
        json.dump({"GT3": {"alias": "GT3", "color": "#FF0000"}}, file)
    preset_management.restore_style_backup(backup)  # Restore of the backups panel, once confirmed
    assert replaced == ["start", "end"]
    assert os.path.exists(f"{folder}classes.json") and not os.path.exists(f"{folder}{backup}")


# --- 3: ranks of the session's cars only (slots beyond keep drivers of a former bigger session)
def test_rank_poll_cars_of_session_only(monkeypatch):
    from neopedal import rank_info
    from neopedal.module_info import minfo
    from neopedal.widget._modern.drivers import DriverTable

    asked = []
    monkeypatch.setattr(rank_info, "poll_field", lambda names: asked.append(list(names)))
    monkeypatch.setattr(minfo.vehicles, "totalVehicles", 1)
    cars = (SimpleNamespace(driverName="Now"), SimpleNamespace(driverName="Gone"))
    DriverTable.poll_ranks(SimpleNamespace(wcfg={"column_driver_ranks": True}), cars)
    assert asked == [["Now"]]


# --- 4: Black box position moved by auto resize kept by its widget config (placement applied again later)
def test_black_box_anchored_move_kept_by_widget_config(ui_env):
    from neopedal.widget._style import StyledConfig
    from tests.test_black_box_modern import new_widget

    widget = new_widget({"resize_anchor": "Bottom Right"})
    try:
        widget.wcfg = StyledConfig(widget.wcfg, {})  # styled copy (modern style, theme, scale)
        widget.move(300, 300)
        widget.move_anchored(200, 200, 150, 150)
        assert (widget.x(), widget.y()) == (350, 350)
        assert (widget.wcfg["position_x"], widget.wcfg["position_y"]) == (350, 350)
        setting = cfg.user.setting["black_box"]
        assert (setting["position_x"], setting["position_y"]) == (350, 350) and widget.position_unsaved
    finally:
        widget.position_unsaved = False
        widget.deleteLater()
        flush()


# --- 5, 10, 11, 12, 13: game replays page
def test_replays_timers_owned_by_page(replays_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import replays_backend as rb

    backend = replays_page.backend
    shots = []
    monkeypatch.setattr(rb.QTimer, "singleShot", lambda *args: shots.append(args))
    monkeypatch.setattr(rb, "click_game_ui", lambda: True)
    backend.state, backend._shown = rb.SESSION, True
    backend.toggleGameUi()
    assert shots and shots[-1][1] is backend  # context: never run after page freed


def test_refused_replay_open_forgotten(replays_page):  # noqa: F811
    from neopedal.ui.quick import replays_backend as rb

    backend = replays_page.backend
    command = rb.play_replay("Algarve P1 1")
    backend.playing, backend.play_sent, backend.sending = "Algarve P1 1", command, (command,)
    backend.command_done(False)
    assert backend.playing == "" and backend.play_sent is None


def test_keep_latest_keeps_replays_of_unknown_time(replays_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import replays_backend as rb

    backend = replays_page.backend
    deleted = []
    monkeypatch.setattr(backend, "delete_replays", lambda replays, title: deleted.extend(r.name for r in replays))
    monkeypatch.setattr(rb.QInputDialog, "getInt", lambda *args, **kwargs: (1, True))
    backend.replays = [rb.GameReplay(0, "Unknown", "", "", "", 0.0, 1), rb.GameReplay(1, "Old", "", "", "", 1.0, 1),
                       rb.GameReplay(2, "New", "", "", "", 2.0, 1)]
    backend.keepLatest()
    assert deleted == ["Old"]


def test_go_to_lap_ahead_of_replay_time(replays_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import replays_backend as rb

    backend = replays_page.backend
    asked = []
    monkeypatch.setattr(rb.QInputDialog, "getInt", lambda *args: asked.append(args) or (0, False))
    monkeypatch.setattr(backend, "car_of", lambda key: SimpleNamespace(laps=0, driver="A", slot=1))
    backend.state = rb.REPLAY
    backend.goToLap("1")
    assert asked[0][3:] == (1, 1, rb.MAX_GO_TO_LAP)  # current lap 1, any lap up to the max


def test_hidden_replays_page_rebuilt_once_shown(replays_page, monkeypatch):  # noqa: F811
    backend = replays_page.backend
    built = []
    monkeypatch.setattr(backend, "update_replays", lambda: built.append(1))
    monkeypatch.setattr(type(backend), "page_visible", property(lambda self: False))
    backend.replays = [object()]
    backend.pictures_changed()
    assert not built  # deferred: hidden pages never rebuild


# --- 6: dashboard session cookie read by hand, one name per dashboard
def test_dashboard_session_cookie(monkeypatch):
    from neopedal import web_dashboard as wd

    assert wd.cookie_value('other=["a",1]; np_session_8338=abc', "np_session_8338") == "abc"
    assert wd.cookie_value("other=a b; np_session_8338=\"abc\"", "np_session_8338") == "abc"
    assert wd.cookie_value("np_session_9000=abc", "np_session_8338") is None
    assert wd.cookie_value("", "np_session_8338") is None
    now = time.monotonic()
    monkeypatch.setattr(wd.DashboardHandler, "sessions", {"abc": wd.Session(now, "127.0.0.1", True)})
    handler = wd.DashboardHandler.__new__(wd.DashboardHandler)
    handler.server = SimpleNamespace(server_address=("127.0.0.1", 8338))  # type: ignore[assignment]
    handler.client_address = ("127.0.0.1", 50000)
    assert handler.session_cookie() == "np_session_8338"
    handler.headers = {"Cookie": 'theme=["dark"]; np_session_8338=abc'}  # type: ignore[assignment]
    assert handler.has_session()  # unparsable cookie of another site: session kept
    handler.headers = {"Cookie": "np_session_8339=abc"}  # type: ignore[assignment]
    assert not handler.has_session()  # session of another dashboard


# --- 7: font size addend within option limit (widgets rebuilt from setting, not validated again)
def test_font_size_addend_clamped():
    """Global font override (Settings page): sizes within option limit, addend itself bounded"""
    from neopedal.template.option_limits import limit_error
    from neopedal.ui.quick.font_override import FontChoice, apply_changes, font_changes

    setting = {"speedometer": {"font_size": 195}}
    apply_changes(setting, font_changes(setting, FontChoice(font_size_addend=20)))
    assert setting["speedometer"]["font_size"] == 200
    setting = {"fuel": {"font_size": 2}}
    apply_changes(setting, font_changes(setting, FontChoice(font_size_addend=-20)))
    assert setting["fuel"]["font_size"] == 1
    assert limit_error("font_size_addend", 999) and not limit_error("font_size_addend", -20)


# --- 8: transfer to a destination removed meanwhile or not saved: told, never made again from defaults
@pytest.fixture
def transfer(ui_env, monkeypatch):
    from neopedal.ui.quick.preset_backend import PresetBackend

    monkeypatch.setattr(cfg.filename, "setting", "a.json")
    monkeypatch.setattr(cfg.user, "filelock", {})
    for name in ("a", "b"):
        with open(f"{cfg.path.settings}{name}.json", "w", encoding="utf-8") as file:
            json.dump({"speedometer": {"enable": True, "font_size": 15}}, file)
    backend = PresetBackend(None, SimpleNamespace())
    toasts = []
    backend.toastShown.connect(lambda text, error, undo: toasts.append(text))
    panel = backend.transfer
    panel.start()
    panel.setDestination("b")
    panel.setAllSettings(True)
    panel.setAllTypes(True)
    yield panel, toasts
    backend.release()
    backend.deleteLater()
    flush()


def test_transfer_destination_removed_meanwhile(transfer):
    panel, toasts = transfer
    os.remove(f"{cfg.path.settings}b.json")
    assert not panel.transfer()
    assert panel.error == "Preset not found, it may have been renamed or deleted." and not toasts
    assert not os.path.exists(f"{cfg.path.settings}b.json")


def test_transfer_not_saved_told(transfer, monkeypatch):
    from neopedal.ui import preset_management

    panel, toasts = transfer
    monkeypatch.setattr(preset_management, "save_and_verify_json_file", lambda **kwargs: False)
    assert not panel.transfer()
    assert "could not be saved" in panel.error and not toasts


# --- 9: JSON nested too deep read as corrupted (defaults & backup), never a crash at start
def test_deeply_nested_json_is_corrupted(tmp_path):
    from neopedal.userfile.json_setting import load_setting_json_file

    path = tmp_path / "deep.json"
    path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    loaded = load_setting_json_file("deep.json", f"{tmp_path}{os.sep}", {"overlay": {"enable": True}})
    assert loaded == {"overlay": {"enable": True}}
    assert any(name.startswith("deep.json.") for name in os.listdir(tmp_path) if name != "deep.json")


# --- 14: stream page origins of running servers only
def test_stream_origins_of_running_servers_only(monkeypatch):
    from neopedal import command_server

    config = {"remote_control": {"remote_control_port": 9001}, "web_dashboard": {"web_dashboard_port": 9002},
              "stream_overlay": {"stream_overlay_port": 9003}}
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    running = {"web_dashboard": False, "stream_overlay": True}
    monkeypatch.setitem(sys.modules, "neopedal.web_dashboard", SimpleNamespace(
        webdashboard=SimpleNamespace(running=running["web_dashboard"])))
    monkeypatch.setitem(sys.modules, "neopedal.stream_overlay", SimpleNamespace(
        streamoverlay=SimpleNamespace(running=running["stream_overlay"])))
    assert command_server.own_page_ports() == {9001, 9003}
    assert not command_server.is_allowed_origin("http://localhost:9002")  # dashboard off: any program there


# --- 15: layer copy root of a shared folder: owned by this user, for this user only
def test_shared_layer_root_owned_by_user(tmp_path, monkeypatch):
    from neopedal import vr_shared

    if sys.platform == "win32":
        monkeypatch.setattr(vr_shared, "WINDOWS", True)  # real owner & access (off for other tests)
    root = str(tmp_path / "NeoPedal" / "openxr_layer" / "user")
    vr_shared.secure_shared_root(root)
    assert os.path.isdir(root) and vr_shared.trusted_owner(root)
    vr_shared.secure_shared_root(root)  # again: kept
    if sys.platform == "win32":
        user = vr_shared.current_user_sid()
        # elevated admin (CI runners): new folders owned by the Administrators group, trusted too
        assert user is not None and vr_shared.path_owner_sid(root) in (user, *vr_shared.TRUSTED_OWNER_SIDS)
    other = str(tmp_path / "other" / "openxr_layer" / "user")
    os.makedirs(other)
    monkeypatch.setattr(vr_shared, "trusted_owner", lambda path: os.path.normcase(path) != os.path.normcase(other))
    with pytest.raises(PermissionError):
        vr_shared.secure_shared_root(other)  # made first by another user: never used
    source = tmp_path / "bundle"
    source.mkdir()
    (source / vr_shared.LAYER_DLL).write_bytes(b"MZ")
    (source / vr_shared.LAYER_MANIFEST).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(vr_shared, "short_path", lambda path: None)
    manifest = str(source / vr_shared.LAYER_MANIFEST)
    monkeypatch.setattr(os.path, "abspath", lambda path, real=os.path.abspath: "C:\\Jérôme\\x.json"
                        if path == manifest else real(path))
    monkeypatch.setattr(vr_shared, "layer_digest", lambda folder: "0" * 64)
    monkeypatch.setattr(vr_shared.os.path, "dirname", lambda path, real=os.path.dirname: str(source)
                        if path == "C:\\Jérôme\\x.json" else real(path))
    assert vr_shared.loadable_manifest(manifest, [other]) is None  # owner refused: next folder, none left


# --- 16: installer download bounded by its announced size
def test_download_bounded_by_announced_size(tmp_path, monkeypatch):
    from neopedal import update

    class Response:
        headers = {"Content-Length": "10"}

        def __init__(self):
            self.chunks = [b"x" * 8, b"x" * 8, b"x" * 8]

        def read(self, size):
            return self.chunks.pop(0) if self.chunks else b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(update, "open_url", lambda url, timeout: Response())
    path = str(tmp_path / "setup.exe")
    with pytest.raises(ValueError, match="larger"):
        update._download_verified("https://github.com/x", path, "0" * 64, 5, None, None)
    assert not os.listdir(tmp_path)  # partial file removed


# --- 17: quit & restart wait for a replay recording still closing its file
def test_replay_wait_closed():
    from neopedal.replay import ReplayControl

    control = ReplayControl()
    assert control.wait_closed(0.1)
    closing = threading.Thread(target=time.sleep, args=(0.2,), daemon=True)
    closing.start()
    control._rec_closing = closing
    assert not control.wait_closed(0.01)
    assert control.wait_closed(2.0)


# --- 18, 19: rank watcher without located account
def test_rank_watcher_not_located_again_every_check(tmp_path):
    from neopedal.process import driver_ranks as dr

    located = []

    def locate():
        located.append(1)
        return dr.Located("", "", ())

    watcher = dr.RankWatcher(locate, lambda: str(tmp_path / dr.HISTORY_FILE), active_account=lambda: "7656119")
    for _ in range(4):
        watcher.check()
    assert len(located) == 2  # first locate, then once for the account in use (LMU not found: never again)


def test_rank_history_unknown_account_not_repeated(tmp_path):
    from neopedal.process import driver_ranks as dr

    history = str(tmp_path / dr.HISTORY_FILE)
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()), lambda: history)
    player = dr.DriverRanks("Keenny", "", "", "", dr.Rank("Gold", 1, 10), dr.Rank("Silver", 2, 20))
    watcher.record(player, 1.0, "")
    watcher.record(player, 2.0, "")
    assert len(dr.read_history(history)) == 1
    watcher.record(player._replace(driver=dr.Rank("Gold", 1, 11)), 3.0, "")
    assert len(dr.read_history(history)) == 2


# --- 20: stale token refused: signed in again at once (token of a new sign in refused: waits, see test_field_ranks)
def test_raceos_stale_token_refused_signs_in_again():
    from neopedal.process import raceos
    from tests.test_field_ranks import NOW, FakeHttp, iso

    http = FakeHttp()
    client = raceos.RaceOSClient(lambda: "ticket", http=http, clock=lambda: 0.0, wall_clock=lambda: NOW)
    auth = {"accessToken": "tok", "expiresAt": iso(NOW + 1800), "player": None}
    http.answers = [(200, auth), (200, [1]), (401, None), (200, auth), (200, [2])]
    assert client.get("api/v1/x") == [1]
    assert client.get("api/v1/x") is None  # kept token refused (revoked)
    assert client.get("api/v1/x") == [2]  # new sign in at once


# --- 21: consumption history rewritten as it is now (laps deleted meanwhile never back in file)
def test_rewrite_consumption_history(tmp_path):
    from neopedal.module_info import ConsumptionDataSet
    from neopedal.userfile.consumption_history import read_consumption_history_file, rewrite_consumption_history

    folder = f"{tmp_path}{os.sep}"
    lap = ConsumptionDataSet(lapNumber=3, isValidLap=1, lapTimeLast=90.0, lastLapUsedFuel=2.5, capacityFuel=100.0)
    assert rewrite_consumption_history([lap, lap], folder, "combo")
    assert len(read_consumption_history_file(folder, "combo")[0]) == 2
    assert rewrite_consumption_history([lap], folder, "combo")  # one lap: placeholder row (lap 0) added
    assert [row for row in read_consumption_history_file(folder, "combo")[0] if row.lapNumber] == [lap]
    assert rewrite_consumption_history([], folder, "combo")  # none: file removed
    assert not os.listdir(tmp_path)


# --- 22: delta file with a short row refused at load (was an IndexError while driving)
def test_delta_set_short_row_refused():
    from neopedal.validator import valid_delta_set

    rows = [(float(index), float(index)) for index in range(20)]
    assert valid_delta_set(tuple(rows))
    for broken in ((*rows[:15], (), *rows[15:]), (*rows[:15], (15.5,), *rows[15:])):
        with pytest.raises(ValueError):
            valid_delta_set(broken)


# --- 23: dialog failing in its constructor never locks its type until restart
def test_singleton_dialog_freed_after_constructor_error():
    from neopedal.ui._common import DialogSingleton, singleton_dialog

    @singleton_dialog("audit_boom")
    class Boom:
        def __init__(self, *args, **kwargs):
            raise KeyError("section gone")

    for _ in range(2):
        with pytest.raises(KeyError):
            Boom(None)
    DialogSingleton.remove("audit_boom")


# --- 25: menu action of an overlay stopped while its menu was open dropped
def test_menu_action_of_stopped_overlay_dropped(editing, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    from neopedal.widget import _base

    start, overlays, _env = editing
    widget = start()
    disabled = []
    monkeypatch.setattr(type(widget), "disable_overlay", lambda self: disabled.append(1))

    def exec_menu(menu, pos):
        action = next(action for action in menu.actions() if action.text() == "Disable")
        overlays.pop(widget.widget_name).stop()  # stopped meanwhile (reload in the menu's event loop)
        return action

    monkeypatch.setattr(_base, "exec_menu", exec_menu)
    widget.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)))
    assert not disabled
