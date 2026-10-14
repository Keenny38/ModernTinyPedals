"""Activity state (wake on change instead of polling), on demand modules, REST polling on demand,
incremental incidents decode & parse, index maps rebuilt on key change, idle wakeup budget"""

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from neopedal import realtime_state
from neopedal.adapter import restapi_connector
from neopedal.adapter.restapi_connector import AppendedListDecoder, ResOutput, RestAPIConnector, TaskState
from neopedal.const_file import ConfigType
from neopedal.process.game_info import ContactsParser, parse_contacts

STATE_NAMES = ("active", "paused", "shown", "resets", "hidden", "session_type", "in_pits", "overlays")


@pytest.fixture
def state(monkeypatch):
    """Realtime state restored after test"""
    for name in STATE_NAMES:
        monkeypatch.setattr(realtime_state, name, getattr(realtime_state, name))
    return realtime_state


# --- Activity state
def test_notify_change_wakes_waiters_and_subscribers(state):
    from neopedal import overlay_signal

    emitted = []

    def on_activity():
        emitted.append(1)

    overlay_signal.activity.connect(on_activity)
    wake = threading.Event()
    state.subscribe(wake)
    try:
        version = state.version
        assert not state.wait_change(0.01, since=version)  # nothing changed: timed out
        state.notify_change()
        assert state.version == version + 1 and wake.is_set() and emitted
        assert state.wait_change(5, since=version)  # change since version read: at once
        assert state.wait_change(5, wake) and not wake.is_set()  # kept set until consumed, then cleared
        start = time.monotonic()
        assert not state.wait_change(0.05, wake)
        assert time.monotonic() - start < 1
        # Waiter woken by change from another thread
        threading.Timer(0.05, state.notify_change).start()
        start = time.monotonic()
        assert state.wait_change(5, wake) and time.monotonic() - start < 2
    finally:
        state.unsubscribe(wake)
        overlay_signal.activity.disconnect(on_activity)
    state.notify_change()
    assert not wake.is_set()  # unsubscribed


def test_connector_freeze_and_resume_notified(state, monkeypatch):
    from neopedal.adapter import _sync
    from tests.test_data_notify import ScriptedStop, lmu_sync

    monkeypatch.setattr(_sync, "notifier", _sync.notifier.__class__())
    sync, zone, data = lmu_sync()
    data.scoring.scoringInfo.mCurrentET = 1.0
    clock = [100.0]
    monkeypatch.setattr(_sync, "monotonic", lambda: clock[0])
    versions = []

    def later():
        clock[0] += 5  # data unchanged for 5s: frozen
        zone.results.append(False)

    sync._SyncData__update_loop(ScriptedStop([
        lambda: versions.append(state.version),  # started: notified
        lambda: (zone.results.append(True), versions.append(state.version)),  # resumed
        lambda: versions.append(state.version),
        later,
        lambda: versions.append(state.version),  # frozen
    ]))
    assert versions[1] > versions[0] and versions[3] > versions[2]
    assert sync.paused


# --- Idle wakeup budget (game closed: connector frozen)
IDLE_SECONDS = 3.0
OVERLAY_CONTROL_READS = 5  # was 15 (0.2s polling)
RESTAPI_IDLE_WAKEUPS = 2  # was 6 (0.5s polling)


def test_idle_wakeup_budget(ui_env, state, monkeypatch):
    """Frozen game data, player not on track: overlay control & RestAPI threads barely wake up"""
    from neopedal import overlay_control
    from neopedal.api_control import api

    reads = []
    monkeypatch.setattr(api.read.state, "paused", lambda: True, raising=False)
    monkeypatch.setattr(api.read.state, "active", lambda: reads.append(1) or False, raising=False)
    state.paused, state.shown, state.active = True, False, False
    wakeups = []
    state_type = type(realtime_state)
    original_wait = state_type.wait_change

    def counted_wait(self, timeout, wake=None, since=None):
        if threading.current_thread().name == "RestAPI":
            wakeups.append(timeout)
        return original_wait(self, timeout, wake, since)

    monkeypatch.setattr(state_type, "wait_change", counted_wait)
    control = overlay_control.OverlayControl()
    connector = RestAPIConnector((), SimpleNamespace())
    connector.setConnection({"enable_restapi_access": True, "restapi_update_interval": 100})
    control.enable()
    connector.start()
    try:
        time.sleep(IDLE_SECONDS)
        assert len(reads) <= OVERLAY_CONTROL_READS, reads
        assert len(wakeups) <= RESTAPI_IDLE_WAKEUPS, wakeups
        # Activity change (game resumed) read at once, not after the long wait
        before = len(reads)
        realtime_state.notify_change()
        deadline = time.monotonic() + 0.5
        while len(reads) == before and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(reads) > before
    finally:
        start = time.monotonic()
        control.disable()
        connector.stop()
        assert time.monotonic() - start < 1.0  # stop wakes idle waits at once


# --- REST polling on demand
def run_repeat(monkeypatch, steps: int, **kwargs) -> tuple[list, list, SimpleNamespace]:
    connector = RestAPIConnector((), SimpleNamespace(chat=("old",)))
    task_state = TaskState()
    sleeps: list = []
    requests: list = []

    async def output(self, *args):
        requests.append(args)
        return len(requests)  # always new data

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= steps:
            task_state.cancel = True

    monkeypatch.setattr(RestAPIConnector, "output_resource", output)
    monkeypatch.setattr(restapi_connector.asyncio, "sleep", sleep)
    outputs = (ResOutput("chat", (), lambda value, default: value),)
    asyncio.run(connector.update_repeat(None, b"", "/rest/chat/", outputs, task_state, 1.0, 1.0, **kwargs))
    return sleeps, requests, connector._dataset


def test_resource_requested_only_while_overlay_runs(state, monkeypatch):
    state.overlays = frozenset({"relative"})
    sleeps, requests, _ = run_repeat(monkeypatch, 3, overlays=("chat",))
    assert not requests and sleeps == [restapi_connector.DEMAND_WAIT] * 3
    state.overlays = frozenset({"chat", "relative"})
    sleeps, requests, _ = run_repeat(monkeypatch, 3, overlays=("chat",))
    assert len(requests) == 3 and sleeps == [1.0] * 3


def test_resource_reset_once_overlay_closed(state, monkeypatch):
    state.overlays = frozenset({"chat"})
    connector = RestAPIConnector((), SimpleNamespace(chat=()))
    task_state = TaskState()
    calls = []

    async def output(self, connection, request, uri_path, output_set, last_hash, shared_age=0.0, decoder=None):
        self._dataset.chat = ("hello",)
        calls.append(1)
        return 1

    async def sleep(seconds):
        state.overlays = frozenset()  # chat overlay closed
        if seconds == restapi_connector.DEMAND_WAIT:
            task_state.cancel = True

    monkeypatch.setattr(RestAPIConnector, "output_resource", output)
    monkeypatch.setattr(restapi_connector.asyncio, "sleep", sleep)
    outputs = (ResOutput("chat", (), lambda value, default: value),)
    asyncio.run(connector.update_repeat(None, b"", "/rest/chat/", outputs, task_state, 1.0, 1.0, overlays=("chat",)))
    assert len(calls) == 1 and connector._dataset.chat == ()  # no stale chat once overlay shown again


def test_repair_refuel_slower_on_track_faster_in_pits(state, monkeypatch):
    from neopedal.adapter.lmu_restapi import lmu_restapi_tasks

    task = next(task for task in lmu_restapi_tasks() if task.path.endswith("RepairAndRefuel"))
    assert (task.interval, task.max_interval, task.pit_interval) == (1.0, 1.0, 0.5)
    state.in_pits = False
    sleeps, _, _ = run_repeat(monkeypatch, 2, pit_interval=0.5)
    assert sleeps == [1.0, 1.0]  # 1 Hz while driving (was 5 Hz)
    state.in_pits = True
    sleeps, _, _ = run_repeat(monkeypatch, 2, pit_interval=0.5)
    assert sleeps == [0.5, 0.5]


def test_chat_and_incidents_tasks_read_by_overlays():
    from neopedal.adapter.lmu_restapi import lmu_restapi_tasks

    tasks = {task.path: task for task in lmu_restapi_tasks()}
    assert tasks["/rest/chat/"].overlays == ("chat",)
    incidents = tasks["/rest/watch/getIncidentsList/1"]
    assert incidents.overlays == ("black_box",) and isinstance(incidents.decoder, AppendedListDecoder)
    assert isinstance(incidents.outputs[0].parser, ContactsParser)
    assert all(not task.overlays for path, task in tasks.items() if path not in ("/rest/chat/", incidents.path))


# --- Incremental incidents
def incident(index: int, time_: float | None = None) -> dict:
    return {"et": float(index) if time_ is None else time_, "player": f"Driver {index}", "contactWith": "Immovable"}


def test_appended_list_decoder_decodes_only_new_entries(monkeypatch):
    decoder = AppendedListDecoder()
    decoded = []
    real = restapi_connector.json_decoder

    class Spy:
        def decode(self, text):
            decoded.append(len(text))
            return real.decode(text)

    monkeypatch.setattr(restapi_connector, "json_decoder", Spy())
    entries = [incident(index) for index in range(50)]
    first = json.dumps(entries[:40])
    assert decoder(first) == entries[:40]
    full = json.dumps(entries) + "\n"
    assert decoder(full) == entries
    assert decoded[-1] < len(full) / 3  # only the 10 new entries decoded
    # Other list (new session), empty list, object: decoded in full
    other = json.dumps([incident(7, 3.0)])
    assert decoder(other) == [incident(7, 3.0)] and decoded[-1] == len(other)
    assert decoder("[]") == [] and decoder(json.dumps([incident(1)])) == [incident(1)]
    assert decoder('{"a": 1}') == {"a": 1}
    with pytest.raises(ValueError):
        decoder("[1, 2")
    # Prefix of a number is not an appended entry
    decoder("[1]")
    assert decoder("[12]") == [12]
    assert decoder("[12 , 3]") == [12, 3]


def test_contacts_parser_same_result_as_full_parse():
    parser = ContactsParser()
    entries: list = [incident(index) for index in range(5)]
    assert parser(entries, ()) == parse_contacts(entries, ())
    entries = [*entries, incident(5), {"et": "bad"}, incident(6)]
    assert parser(entries, ()) == parse_contacts(entries, ())
    entries = [*entries, incident(7, 2.5), incident(8, 2.5)]  # older times appended: order kept
    assert parser(entries, ()) == parse_contacts(entries, ())
    entries = [*entries, incident(9, 6.0)]  # same time as last
    assert parser(entries, ()) == parse_contacts(entries, ())
    new_session = [incident(1, 0.5)]
    assert parser(new_session, ()) == parse_contacts(new_session, ())
    assert parser(None, ("x",)) == ("x",) and parser([], ()) == ()
    assert parser([*new_session, incident(2)], ()) == parse_contacts([*new_session, incident(2)], ())


def test_contacts_parser_parses_only_new_entries(monkeypatch):
    from neopedal.process import game_info

    parsed = []
    real = game_info._contacts_of
    monkeypatch.setattr(game_info, "_contacts_of", lambda entries: (parsed.append(len(entries)), real(entries))[1])
    parser = ContactsParser()
    entries = [incident(index) for index in range(100)]
    parser(entries[:90], ())
    parser(entries, ())
    assert parsed == [90, 10]


# --- On demand modules
class FakeModule:
    def __init__(self, config, name):
        self.name = name
        self.closed = True

    def start(self):
        self.closed = False

    def stop(self, discard=False):
        self.closed = True

    def wait_closed(self, timeout):
        return True


def fake_target(*names):
    return SimpleNamespace(__all__=list(names), **{name: SimpleNamespace(Realtime=FakeModule) for name in names})


def test_needed_on_demand_from_overlays_features_and_unknown_code(ui_env):
    from neopedal.module_control import CodeScan, needed_on_demand
    from neopedal.template.setting_module import MODULE_ON_DEMAND

    setting = {
        "force": {"enable": True}, "pace_notes": {"enable": False}, "relative": {"enable": True},
        "module_delta": {"enable": True}, "module_force": {"enable": True}, "module_notes": {"enable": True},
        "pace_notes_playback": {"enable": False},
    }
    modules = ("module_delta", "module_force", "module_notes")
    scan = CodeScan()
    assert needed_on_demand(MODULE_ON_DEMAND, ("force", "pace_notes", "relative"), modules, setting, scan) == {
        "module_force"}
    assert needed_on_demand(MODULE_ON_DEMAND, ("relative",), modules, setting, scan) == set()
    setting["pace_notes_playback"]["enable"] = True  # audio playback reads pace notes
    assert needed_on_demand(MODULE_ON_DEMAND, ("relative",), modules, setting, scan) == {"module_notes"}
    setting["plugin_overlay"] = {"enable": True}  # code unknown: may read anything
    assert needed_on_demand(MODULE_ON_DEMAND, ("plugin_overlay",), modules, setting, scan) == set(MODULE_ON_DEMAND)


def test_on_demand_modules_follow_overlays(ui_env, state):
    from neopedal.module_control import ModuleControl
    from neopedal.setting import cfg
    from neopedal.template.setting_module import MODULE_ON_DEMAND

    setting = cfg.user.setting
    setting["force"]["enable"] = False
    setting["deltabest"]["enable"] = True
    setting["pace_notes_playback"]["enable"] = False
    control = ModuleControl(fake_target("module_delta", "module_force", "module_notes"), ConfigType.MODULE,
                            on_demand=MODULE_ON_DEMAND)
    overlays = ModuleControl(SimpleNamespace(__all__=["force", "deltabest"]), ConfigType.WIDGET)
    control.watch(overlays)
    control.update_demand()  # before start of all: nothing started
    assert not control.active_modules
    control.start()
    assert set(control.active_modules) == {"module_delta"}  # always on module only
    assert control.should_run("module_delta") and not control.should_run("module_force")
    # Overlay reading forces enabled (overlay control notifies its change)
    setting["force"]["enable"] = True
    overlays._ModuleControl__changed()
    assert "module_force" in control.active_modules
    assert state.overlays == frozenset()  # running overlays published by widget control
    # Explicitly disabled module never runs, even if needed
    control.toggle("module_force")
    assert "module_force" not in control.active_modules and not setting["module_force"]["enable"]
    control.toggle("module_force")
    assert "module_force" in control.active_modules
    # Overlay closed: module no longer needed
    setting["force"]["enable"] = False
    overlays._ModuleControl__changed()
    assert "module_force" not in control.active_modules
    # Feature needing a module
    setting["pace_notes_playback"]["enable"] = True
    control.update_demand()
    assert "module_notes" in control.active_modules
    control.close()
    setting["force"]["enable"] = True
    control.update_demand()  # closed: nothing started again until start of all
    assert not control.active_modules


def test_running_overlays_published_for_rest_tasks(ui_env, state):
    from neopedal.module_control import ModuleControl

    overlays = ModuleControl(SimpleNamespace(__all__=["chat"]), ConfigType.WIDGET)
    overlays._active_modules["chat"] = SimpleNamespace(closed=True, stop=lambda: None)
    overlays._ModuleControl__changed()
    assert state.overlays == {"chat"}
    overlays.close("chat")
    assert state.overlays == frozenset()


def test_default_modules_on_demand_are_known_modules():
    from neopedal.template.setting_module import FEATURE_MODULES, MODULE_DEFAULT, MODULE_ON_DEMAND
    from neopedal.ui.quick.module_backend import MODULE_SPECS

    for name, fields in MODULE_ON_DEMAND.items():
        assert name in MODULE_DEFAULT and MODULE_DEFAULT[name]["enable"]
        assert set(fields) == set(MODULE_SPECS[name].fields), name  # same fields as Modules page
    assert all(set(names) <= set(MODULE_ON_DEMAND) for names in FEATURE_MODULES.values())
