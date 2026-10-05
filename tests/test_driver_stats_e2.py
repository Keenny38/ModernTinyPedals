"""Driver stats phase 2 (package E2): stint pace & degradation by compound, consistency index, session history
export, friend's stats compared"""

import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tests.test_driver_stats_viewer import OREGA, SPA, STATS, write_stats
from tests.test_lap_viewer_e2 import lap_info, write_lap
from tinypedal.setting import cfg
from tinypedal.ui.quick import stint_analysis as sa
from tinypedal.userfile import driver_history
from tinypedal.userfile.driver_history import SessionRecord

FOLDER = f"{SPA} - LMP2_ELMS"
START = 1_700_000_000


def lap(time_value, kind="lap", compound="Medium", valid=True, timestamp=0.0):
    return sa.StintLap(time_value, valid, kind, compound, timestamp, "Practice", START)


def test_stints_split_clean_laps_and_trend():
    laps = [lap(130, "out"), lap(120.0), lap(120.2), lap(120.4), lap(120.6), lap(140.0), lap(125, "in"),
            lap(131, "out", "Soft"), lap(119.0, compound="Soft"), lap(119.0, compound="Soft"), lap(119.3, compound="Soft"),
            lap(118.0, compound="Soft", valid=False)]
    stints = sa.split_stints(laps)
    assert [len(stint) for stint in stints] == [7, 5]
    assert [time_value for _, time_value in sa.clean_times(stints[0])] == [120.0, 120.2, 120.4, 120.6]  # outlier out
    first = sa.stint_summary(stints[0])
    assert first["compound"] == "Medium" and first["clean"] == 4 and first["laps"] == 7
    assert first["pace"] == pytest.approx(120.3) and first["slope"] == pytest.approx(0.2)
    second = sa.stint_summary(stints[1])
    assert second["slope"] is None and second["clean"] == 3  # trend needs 4 clean laps
    assert sa.stint_summary([lap(120.0), lap(121.0)]) is None
    rows = sa.compound_summary([first, second])
    assert [row["compound"] for row in rows] == ["Soft", "Medium"]  # fastest first
    assert rows[1]["slope"] == pytest.approx(0.2) and rows[0]["slope"] is None
    assert sa.variation([100.0, 101.0, 99.0]) == pytest.approx(1.0) and sa.variation([100.0, 101.0]) is None
    assert sa.track_consistency([{"index": 0.5}, {"index": 0.2}, {"index": 0.9}]) == 0.5
    assert sa.track_consistency([{"index": 0.2}, {"index": 0.4}]) == pytest.approx(0.3)
    assert sa.track_consistency([]) is None
    report = sa.stint_report([laps])
    assert len(report["stints"]) == 2 and report["sessions"][0]["clean"] == 7 and report["index"] > 0
    assert sa.lap_compound({"compound": ["Soft", "Medium"]}) == "Soft/Medium"


def test_history_export_and_friend_comparison(tmp_path):
    records = [SessionRecord(START + 10, SPA, OREGA, 1, 121.5, 10, 2, 50000.0, 1800.0),
               SessionRecord(START, "Monza", "GT3 - BMW", 4, 107.2, 5, 0, 20000.0, 600.0, 3, 1, "GT3")]
    document = sa.history_document(records, STATS, {OREGA: "LMP2_ELMS"})
    assert document["format"] == sa.HISTORY_FORMAT and [row["track"] for row in document["sessions"]] == ["Monza", SPA]
    assert document["stats"][SPA][OREGA]["pb"] == 121.5 and "liters" not in document["stats"][SPA][OREGA]
    target = tmp_path / "Max.json"
    sa.write_history_json(str(target), document)
    friend = sa.load_friend(str(target))
    assert friend["name"] == "Max" and len(friend["sessions"]) == 2 and friend["classes"] == {OREGA: "LMP2_ELMS"}
    faster = json.loads(target.read_text(encoding="utf-8"))
    faster["stats"][SPA][OREGA]["pb"] = 120.9
    faster["driver"] = "Max V."
    target.write_text(json.dumps(faster), encoding="utf-8")
    friend = sa.load_friend(str(target))
    assert friend["name"] == "Max V."

    def mine_class(vehicle: str) -> str:
        return vehicle.split(" - ", 1)[0]

    rows = sa.compare_friend(STATS, mine_class, friend, [SPA])
    by_class = {row["class"]: row for row in rows}
    assert by_class["LMP2_ELMS"]["gap"] == pytest.approx(0.6) and by_class["Hyper"]["friend"] == 119.0
    every = sa.compare_friend(STATS, mine_class, friend)
    assert {row["track"] for row in every} == {SPA, "Monza"} and all(row["mine"] and row["friend"] for row in every)
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        sa.load_friend(str(tmp_path / "bad.json"))
    with pytest.raises(ValueError):
        sa.load_friend(str(tmp_path / "missing.json"))
    csv_file = tmp_path / "history.csv"
    sa.write_history_csv(str(csv_file), records, ["Date", "Track"], ["Test day", "Practice", "Qualifying", "Warmup",
                                                                     "Race"], ",")
    lines = csv_file.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "Date;Track" and ";Race;107,200;5;0;20000;600;3;1" in lines[1]


@pytest.fixture
def stats_page(ui_env, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.api_control import api
    from tinypedal.ui._common import BaseDialog
    from tinypedal.ui.quick.stats_backend import DriverStatsBackend

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    write_stats(STATS)
    driver_history.save_history(cfg.path.config, [
        SessionRecord(START + 4000, SPA, OREGA, 1, 121.5, 10, 2, 50000.0, 1800.0, vehicle_class="LMP2_ELMS"),
        SessionRecord(START, "Monza", "GT3 - BMW", 4, 107.2, 5, 0, 20000.0, 600.0, 3, 1, "GT3"),
    ])
    monkeypatch.setattr(type(api.read.session), "track_name", lambda self: SPA, raising=False)
    folder = cfg.path.telemetry.rstrip("/")
    times = (130.0, 121.0, 121.3, 121.6, 121.9, 122.2, 135.0, 131.0, 120.5, 120.6, 120.4, 120.8)
    kinds = ("out", "lap", "lap", "lap", "lap", "lap", "in", "out", "lap", "lap", "lap", "lap")
    compounds = ("Medium",) * 7 + ("Soft",) * 5
    stamp = START + 100
    for number, (lap_time, kind, compound) in enumerate(zip(times, kinds, compounds), 1):
        stamp += lap_time
        info = lap_info(kind=kind, compound=compound, vehicle="Oreca 07 Gibson", session_start=START,
                        track="Circuit de Spa", combo=SPA)
        write_lap(folder, number, lap_time, info=info, samples=20, combo=FOLDER, timestamp=stamp)
    host = BaseDialog(None)
    page = DriverStatsBackend(host)
    page.warnings = warnings
    yield page
    page.release()
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_stints(page):
    end = time.monotonic() + 5
    while page.stints.get("busy") and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert not page.stints.get("busy")


def test_stints_and_consistency_of_vehicle(stats_page):
    stats_page.selectTrack(SPA)
    stats_page.selectRow(OREGA)
    wait_stints(stats_page)
    stints = stats_page.stints
    assert stints["visible"] and stints["index"].endswith(" %") and stints["note"] == ""
    compounds = {row["compound"]: row for row in stints["compounds"]}
    assert set(compounds) == {"Medium", "Soft"}
    assert compounds["Medium"]["slope"].startswith("+0.300") and compounds["Medium"]["slopeColor"] == "loss"
    assert compounds["Soft"]["pace"] == "2:00.575" and compounds["Soft"]["stints"] == 1
    assert len(stints["stints"]) == 2 and stints["stints"][0]["compound"] == "Soft"  # newest first
    assert stints["sessions"][0]["laps"] == 9  # clean laps of session
    stats_page.selectRow("Hyper - Ferrari")  # no recorded lap of this class
    assert "No recorded lap" in stats_page.stints["note"]
    stats_page.selectTrack("")
    assert stats_page.stints == {}


def test_history_export_and_friend_on_page(stats_page, tmp_path):
    stats_page.selectTrack(SPA)
    target = tmp_path / "spa.json"
    assert stats_page.write_history(str(target), "json")
    document = json.loads(target.read_text(encoding="utf-8"))
    assert [row["track"] for row in document["sessions"]] == [SPA] and list(document["stats"]) == [SPA]
    csv_file = tmp_path / "spa.csv"
    assert stats_page.write_history(str(csv_file), "csv", ".")
    assert csv_file.read_text(encoding="utf-8-sig").splitlines()[0].startswith("Date,Track,Vehicle")
    stats_page.selectTrack("")
    assert stats_page.write_history(str(tmp_path / "all.json"), "json")
    friend = json.loads((tmp_path / "all.json").read_text(encoding="utf-8"))
    friend["stats"][SPA][OREGA]["pb"] = 122.0
    friend["driver"] = "Max"
    (tmp_path / "friend.json").write_text(json.dumps(friend), encoding="utf-8")
    assert stats_page.friend == {"visible": False}
    assert stats_page.load_friend(str(tmp_path / "friend.json"))
    stats_page.refresh_friend()
    view = stats_page.friend
    assert view["name"] == "Max" and {row["track"] for row in view["rows"]} == {SPA, "Monza"}
    stats_page.selectTrack(SPA)
    rows = {row["vehicleClass"]: row for row in stats_page.friend["rows"]}
    assert rows["LMP2_ELMS"]["gap"] == chr(0x2212) + "0.500" and rows["LMP2_ELMS"]["gapColor"] == "gain"
    assert "Faster on" in stats_page.friend["summary"]
    stats_page.clearFriend()
    assert stats_page.friend == {"visible": False}
    assert not stats_page.load_friend(str(tmp_path / "missing.json"))
    assert stats_page.warnings  # unreadable friend's file told


def test_driver_stats_page_with_stints_and_friend(stats_page, tmp_path):
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QWidget

    from tinypedal import i18n
    from tinypedal.ui.quick import create_quick_view

    stats_page.selectTrack("")
    stats_page.write_history(str(tmp_path / "all.json"), "json")
    stats_page.load_friend(str(tmp_path / "all.json"))
    stats_page.selectTrack(SPA)
    stats_page.selectRow(OREGA)
    wait_stints(stats_page)
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    parent = QWidget()
    i18n.set_language("Français")
    try:
        view = create_quick_view(parent, "DriverStats.qml", {"backend": stats_page})
        view.resize(1400, 900)
        view.show()
        for _ in range(10):
            QCoreApplication.processEvents()
        assert not view.errors()
        texts, stack = set(), [view.rootObject()]
        while stack:
            item = stack.pop()
            text = item.property("text")
            if isinstance(text, str):
                texts.add(text)
            stack.extend(item.childItems())
        assert "Relais et régularité" in texts and "Indice de régularité" in texts
        assert os.path.basename(str(tmp_path / "all")) in " ".join(texts)  # friend's name
    finally:
        i18n.set_language("English")
        qInstallMessageHandler(previous)
        parent.deleteLater()
    assert not [text for text in messages if ".qml" in text], messages
