"""Per tick work of standings & black box, shared game REST answers, rank file parsing: same results, less work"""

import json
import os
from array import array

import pytest

from neopedal import calculation as calc
from neopedal.const_common import MAX_SECONDS
from tests.test_modern_graphic_widgets import reader, render, widgets  # noqa: F401  (fixture)
from tests.test_perf_overlay_repaint import count_updates


# --- Classic standings: raw values compared, text made once changed
def test_classic_standings_formats_once_changed(widgets, monkeypatch):  # noqa: F811
    from neopedal.widget.standings import lap_time_key, pit_time_key

    widget = widgets("standings", modern=False)
    target = widget.bars_lpt[0]
    widget.update_lpt(target, pit_time_key(1, 12.31), False, False, 0)
    assert target.text == f"PIT{12.31:>5.1f}"
    last = target.last
    widget.update_lpt(target, pit_time_key(1, 12.34), False, False, 0)  # same tenth: same data
    assert target.last == last and target.text == f"PIT{12.31:>5.1f}"
    widget.update_lpt(target, pit_time_key(0, 0.0), False, False, 0)
    assert target.text == widget.set_laptime(-1.0)[:8]
    widget.update_lpt(target, lap_time_key(95.123, False), False, False, 0)
    assert target.text == f"*{calc.sec2laptime_full(95.123)}"[:8]
    widget.update_lpt(target, lap_time_key(95.123), False, False, 0)
    assert target.text == calc.sec2laptime_full(95.123)[:8]


@pytest.mark.parametrize("decimals", [0, 1, 3])
def test_classic_standings_gap_texts(widgets, decimals):  # noqa: F811
    widget = widgets("standings", modern=False)
    widget.gap_decimals = widget.int_decimals = decimals
    leader = widget.wcfg["time_gap_leader_text"]
    for gap, position in ((1.2341, 2), (2, 3), (0.05, 2), (15.0, 1), (float("inf"), 4)):
        old = leader if position == 1 else f"{gap:.0f}L" if isinstance(gap, int) else f"{gap:.{decimals}f}"
        assert widget.gap_text(widget.gap_key_race(gap, position), decimals) == old
    for best, leader_best in ((90.5, 90.5), (91.2345, 90.5), (0.0, 90.5), (89.0, 90.5)):
        time = best - leader_best
        old = (leader if time == 0 and best > 0 else "-" if time < 0 or best < 1 else f"{time:.{decimals}f}")
        assert widget.gap_text(widget.gap_key_best(best, leader_best), decimals) == old
    assert widget.gap_key_race(1.2341, 2) == widget.gap_key_race(1.2342, 2)  # same text: same key
    gap = widget.bars_gap[0]
    widget.update_gap(gap, widget.gap_key_race(2, 3), False, 0)
    assert gap.text == "2L"
    widget.update_gap(gap, widget.gap_key_race(2.0, 3), False, 0)  # laps & seconds never equal keys
    assert gap.text == f"{2.0:.{decimals}f}"[:widget.gap_width].strip(".")


def test_classic_standings_delta_from_recent_laps(widgets, monkeypatch):  # noqa: F811
    from neopedal.module_info import DeltaLapTimeHistory

    widget = widgets("standings", modern=False, show_delta_laptime=True)
    car = DeltaLapTimeHistory("d", (0, 90.0, 91.0, 0, 92.5))
    player = DeltaLapTimeHistory("d", (89.0, 0, 90.0, 91.0, 92.0))
    recent = 5 - widget.max_delta
    target = widget.bars_dlt[0]
    updates = count_updates(monkeypatch, target)
    widget.update_dlt(target, car[recent:], player[recent:], False, 0)
    assert target.delta == tuple(car.delta(player, widget.max_delta))
    widget.update_dlt(target, array("d", car[recent:]), array("d", player[recent:]), False, 0)  # same laps
    assert len(updates) == 1
    car[4] = 92.0
    widget.update_dlt(target, car[recent:], player[recent:], False, 0)
    assert target.delta == tuple(car.delta(player, widget.max_delta)) and target.delta[-1] == 0.0
    assert MAX_SECONDS in target.delta


def test_classic_standings_ticks_same_texts(widgets):  # noqa: F811
    from PySide6.QtCore import QTimerEvent

    from neopedal.module_info import minfo

    widget = widgets("standings", modern=False, show_time_interval=True, show_best_laptime=True)
    widget.timerEvent(QTimerEvent(0))
    texts = [bar.text for bar in (*widget.bars_gap, *widget.bars_int, *widget.bars_lpt)]
    assert any(text.strip() for text in texts)
    for car in minfo.vehicles.dataSet:
        if isinstance(car.gapBehindLeader, float):
            car.gapBehindLeader += 1e-6  # under display precision
    widget.timerEvent(QTimerEvent(0))
    assert [bar.text for bar in (*widget.bars_gap, *widget.bars_int, *widget.bars_lpt)] == texts


# --- Modern driver tables: column builders made once, shared colors & cells
def test_modern_builders_rows_and_shared_cells(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from tests.test_modern_table_rows import new_table, sample

    setting = cfg.user.setting["standings"]
    monkeypatch.setitem(setting, "column_class", True)
    monkeypatch.setitem(setting, "show_class_style_for_position_in_class", True)
    monkeypatch.setitem(setting, "column_tyre_compound", True)
    widget = new_table(cfg, "standings")
    field, context = sample(widget)
    assert len(widget.builders) == len(widget.table.columns)
    car = field.vehicles[0]
    first, second = widget.driver_row(car, context), widget.driver_row(car, context)
    assert first == second
    keys = [column.key for column in widget.table.columns]
    for key in ("class", "tyre_compound"):
        if key in keys:
            index = keys.index(key)
            assert first.cells[index] is second.cells[index] or first.cells[index].color is second.cells[index].color
    if "class" in keys:
        cell = first.cells[keys.index("class")]
        assert cell.color == cell.fill.darker(150)
    widget.deleteLater()


def test_modern_standings_compares_rows_once(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from tests.test_modern_table_rows import new_table, sample

    widget = new_table(cfg, "standings")
    field, context = sample(widget)
    widget.show_field(field, context)
    compared = []
    original = widget.refresh_rows
    monkeypatch.setattr(widget, "refresh_rows", lambda rows: compared.append(rows) or original(rows))
    height = widget.height()
    widget.show_field(field, context)  # unchanged: one compare, no resize
    assert len(compared) == 1 and widget.height() == height
    assert widget.refresh(widget.state) is False
    widget.deleteLater()


# --- Energy usage: last laps only, shared answers, body parsed once
def full_usages(laps: list) -> list[float]:
    """Energy used per lap as before (whole lap list walked)"""
    used, before = [], None
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        energy = lap.get("ve")
        if not isinstance(energy, (int, float)) or isinstance(energy, bool):
            before = None
            continue
        if before is not None and not lap.get("pit") and energy < before:
            used.append(before - energy)
        before = energy
    return used


def test_lap_usages_from_last_laps():
    from neopedal.energy_usage import AVERAGE_LAPS, driver_key, lap_usages

    laps: list = [{"lap": index, "ve": 1.0 - index * 0.03, "pit": index == 6} for index in range(12)]
    laps[3]["ve"] = None
    laps[8:8] = ["text", {"lap": 8, "ve": True}]
    laps.append({"lap": 13, "ve": 0.9})  # refill without pit flag
    laps.append({"lap": 14, "ve": 0.86})
    for count in range(1, 12):
        cut = laps[:count + 4]
        assert lap_usages(cut) == full_usages(cut)
        assert lap_usages(cut, AVERAGE_LAPS) == full_usages(cut)[-AVERAGE_LAPS:]
    assert driver_key(" Bart BUSSER ") == "bart busser"


def test_route_poller_parses_changed_body_only():
    from neopedal.game_rest_poll import RoutePoller

    parsed = []
    answers = [(200, b'{"a": 1}'), (200, b'{"a": 1}'), (200, b'{"a": 2}'), (0, b""), (200, b'{"a": 2}')]
    poller = RoutePoller("/rest/x", lambda data: parsed.append(data) or data, {}, 10.0, lambda: answers.pop(0))
    for _ in range(5):
        poller.check()
    assert parsed == [{"a": 1}, {"a": 2}, {"a": 2}]  # same body skipped, read again after game left
    assert poller.value == {"a": 2}


def test_energy_usage_shares_game_answers(monkeypatch):
    from neopedal.energy_usage import ROUTE, EnergyUsage
    from neopedal.game_rest_cache import rest_cache

    body = json.dumps({"Bart": [{"ve": 0.9}, {"ve": 0.86}]}).encode()
    asked = []
    monkeypatch.setattr(rest_cache, "fetch", lambda address, route, timeout: asked.append(route) or (200, body))
    monkeypatch.setattr("neopedal.game_rest_cache.lmu_address", lambda: ("localhost", 6397))
    usage = EnergyUsage()
    usage.check()
    assert usage.usage("bart").last == pytest.approx(0.04)
    value = usage.value
    assert rest_cache.json(ROUTE, 5.0) is not None  # race calculator: same answer
    usage.check()
    assert asked == [ROUTE] and usage.value is value


# --- Driver ranks: flat walk, same content not parsed again, history last entry kept
def nodes_before(value, depth=0):
    """Nodes as found before (nested generators)"""
    from neopedal.process import driver_ranks as dr

    if depth > dr.MAX_DEPTH:
        return
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "[") and ("Rank" in text):
            try:
                yield from nodes_before(json.loads(text), depth + 1)
            except ValueError:
                return
    elif isinstance(value, dict):
        yield value
        for item in value.values():
            yield from nodes_before(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from nodes_before(item, depth + 1)


def test_rank_nodes_same_order_and_depth():
    from neopedal.process import driver_ranks as dr
    from tests.test_driver_ranks import storage_text

    data = json.loads(storage_text())
    assert list(dr._nodes(data)) == list(nodes_before(data))
    deep: object = {"driverRank": {"rank": "Gold"}}
    for level in range(dr.MAX_DEPTH + 3):
        deep = [deep] if level % 3 else json.dumps({"x": deep, "Rank": level})
    for value in (deep, {"a": deep}, [" {broken Rank", "  [1, {\"Rank\": 2}]"]):
        assert list(dr._nodes(value)) == list(nodes_before(value))


def test_rank_watcher_skips_same_content_and_keeps_last_entry(tmp_path, monkeypatch):
    from neopedal.process import driver_ranks as dr
    from tests.test_driver_ranks import PROFILE, storage_text

    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    history = tmp_path / dr.HISTORY_FILE
    parsed, reads = [], []
    parse, read = dr.parse_storage, dr.read_history
    monkeypatch.setattr(dr, "parse_storage", lambda text: parsed.append(1) or parse(text))
    monkeypatch.setattr(dr, "read_history", lambda name: reads.append(1) or read(name))
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), "76561190000000001", ()), lambda: str(history))
    watcher.check()
    os.utime(path, (1_900_000_000, 1_900_000_000))  # saved again, same content
    watcher.check()
    assert len(parsed) == 1 and watcher.serial == 1 and watcher.updated == 1_900_000_000
    profile = {**PROFILE, "driverRank": {**PROFILE["driverRank"], "progress": 55}}
    path.write_text(storage_text(profile), encoding="utf-8")
    os.utime(path, (2_000_000_000, 2_000_000_000))
    watcher.check()
    assert len(parsed) == 2 and watcher.player.driver.progress == 55 and watcher.serial == 2
    assert len(reads) == 1  # history file read once, last entry kept
    assert [entry.driver.progress for entry in read(str(history))] == [40, 55]


# --- Black box: game values read once per update
def test_black_box_reads_values_once_per_update(ui_env, monkeypatch):
    from neopedal.api_control import api
    from tests.test_black_box_events import new_widget

    calls: dict[str, int] = {}

    def counted(group, name, value):
        def read(*args):
            calls[name] = calls.get(name, 0) + 1
            return value
        monkeypatch.setattr(getattr(api.read, group), name, read)

    counted("tyre", "load", (3000.0, 3000.0, 3500.0, 3500.0))
    counted("lap", "number", 3)
    counted("session", "elapsed", 100.0)
    counted("engine", "oil_temperature", 100.0)
    counted("engine", "water_temperature", 85.0)
    widget = new_widget({
        "show_tyre_load": True, "show_suspension": True, "show_incident_recorder": True,
        "show_event_log": True, "show_engine_status": True, "show_engine_overheat_events": True,
        "show_suspension_lap_stats": True, "slow_data_update_interval": 0,
        "enable_incident_file_export": False,
    })
    try:
        widget.timerEvent(None)
        assert calls == {"load": 1, "number": 1, "elapsed": 1, "oil_temperature": 1, "water_temperature": 1}
        assert widget.tick_reads is None
        widget.update_recorder(30.0)  # outside an update: read again
        assert calls["load"] == 2
    finally:
        widget.deleteLater()
