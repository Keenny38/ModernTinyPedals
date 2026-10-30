"""UI/UX audit 2026-10-29, telemetry views: simple view summary band (T3: delta & speed at cursor, delta over the whole
lap, corners where time is lost), best / personal best colors (T4), track map viewer state view, car setup
differences moved to telemetry folder, tints named"""

import os
import re

import pytest

from neopedal.ui.quick import qml_path
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import chart_of, evaluate, find, named, opener, wait, warnings  # noqa: F401

TELEMETRY = os.path.dirname(qml_path("LapViewer.qml"))
MINUS, DASH = chr(0x2212), chr(0x2014)  # signed values, no value (MISSING of app pages)


def qml_text(name: str) -> str:
    with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
        return file.read()


# --- T3: simple view summary band
def test_inputs_carry_delta_and_speed(opener, warnings):  # noqa: F811
    backend = opener().backend
    backend.setSimpleView(True)
    wait(0.3)
    reference = backend.data.reference
    for lap, entry in zip(backend.data.laps, backend.dashboard.inputs_at(500.0)):
        assert entry["speedValue"] > 0 and entry["speed"] == f"{entry['speedValue']:.0f}"
        if lap is reference:
            assert entry["delta"] == "" and entry["deltaValue"] == 0.0  # compared with: no gap
        else:
            assert entry["delta"] != "" and entry["delta"][0] in ("+", "-", "0", MINUS)
    assert all(entry["delta"] == "" for entry in backend.dashboard.inputs_at(1e6))  # past end of laps


def test_delta_line_shared_vertices_kept_while_shown(opener, warnings):  # noqa: F811
    from neopedal.ui.quick.lines import VertexStore

    backend = opener().backend
    backend.setSimpleView(True)
    wait(0.3)
    dashboard = backend.dashboard
    line = dashboard.deltaLine
    compared = backend.data.delta_laps()
    assert compared and [series["lap"] for series in line["series"]] == [lap.key for lap in compared]
    assert line["high"] > line["low"]
    assert all(VertexStore.has(series["key"]) for series in line["series"])
    assert dashboard.deltaLine is line  # same laps: same dict (QML items kept)
    dashboard.setLayoutShown(True)
    assert set(dashboard.vertex_keys()) == {series["key"] for series in line["series"]}
    backend.setChannelVisible("delta", False)  # delta chart hidden: band lines kept by the page
    backend.drop_unused_vertices()
    assert all(VertexStore.has(series["key"]) for series in line["series"])
    dashboard.setLayoutShown(False)  # simple view hidden: dropped, built again once shown
    backend.drop_unused_vertices()
    assert dashboard.vertex_keys() == []
    assert not any(VertexStore.has(series["key"]) for series in line["series"])
    dashboard.setLayoutShown(True)
    assert dashboard.deltaLine is line
    assert all(VertexStore.has(series["key"]) for series in dashboard.deltaLine["series"])
    backend.resetChannels()


def test_summary_band_shown_over_simple_view(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    backend.setSimpleView(True)
    wait(0.8)
    band = named(view, "simpleSummary")
    assert band.isVisible()
    strip = named(view, "deltaStrip")
    shapes = [item for item in find(view, lambda item: item.property("key") is not None and item.property("revision")
                                    is not None) if item.parentItem() and item.parentItem().parentItem() is not None
              and evaluate(view, item, "modelData !== undefined") and strip.isAncestorOf(item)]
    assert len(shapes) == len(backend.data.delta_laps())  # one GPU line per compared lap
    delta, speed = named(view, "deltaTile"), named(view, "speedTile")
    assert delta.property("value") == speed.property("value") == DASH  # no cursor yet
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.3)
    gap = evaluate(view, band.parentItem().parentItem(), "gapLap")
    assert gap and delta.property("value") == gap["delta"] != ""
    assert backend.dashboard.inputs_at(500.0)[0]["speedUnit"] in speed.property("value")
    detail = delta.property("detail")
    assert detail.startswith("▼") if gap["deltaValue"] > 0 else detail.startswith("▲")  # words & sign, not color alone
    # Losses listed once, by the synthesis band over both views (numbered as the shaded corners of the delta line)
    assert not find(view, lambda item: item.objectName() == "lossList")
    coaching = backend.cornerTable.coaching
    assert evaluate(view, band, "lossRanges.length") == min(len(coaching), 3)
    assert named(view, "summaryBand").isVisible()
    backend.setSimpleView(False)
    wait(0.5)
    assert not band.isVisible()


def test_summary_band_keeps_simple_view_features():
    text = qml_text("SimpleView")
    for part in ("component InputsCard", "component PedalGauge", "component SteeringWheel", "component DashboardGroup",
                 "component BarItem", "component LightItem", "component WheelsItem", "component GItem",
                 "component SummaryBand", "component ReadingTile"):
        assert part in text


# --- T4: purple best, green personal best, gold podium only
def test_lap_rows_flag_personal_best(opener, warnings):  # noqa: F811
    backend = opener().backend
    rows = [row for row in backend.lap_model.rows if row["kind"] == "lap"]
    assert rows and all("personalBest" in row for row in rows)
    best = [row for row in rows if row["personalBest"]]
    assert len(best) == 1 and best[0]["title"].endswith("2")  # fastest valid lap of track (lap 4 invalid)
    assert all(not row["personalBest"] for row in backend.lap_model.rows if row["kind"] == "session")


@pytest.mark.parametrize("name", ["LapList", "SessionView", "TraceChart", "TrackMap", "CornerList", "SimpleView",
                                  "GCircle", "XYView", "RangeStats", "TrackMapViewer"])
def test_no_gold_for_best_in_telemetry(name):
    assert "theme.gold" not in qml_text(name)  # gold: podium & protected only


def test_best_colors_with_marks():
    lap_list = qml_text("LapList")
    # Shared record mark (TpLapTime: ◆ purple session best first, ● green personal best): never color alone
    assert 'record: lapContent.other ? "" : row.fastest ? "session" : row.personalBest ? "personal" : ""' in lap_list
    assert "★" not in lap_list and 'i18n.tr("PB")' not in lap_list
    assert 'record: "session"' in qml_text("SessionView") and "theme.purple" in qml_text("SessionView")
    assert "modelData.best ? theme.purple" in qml_text("TraceChart")
    assert "color: theme.purple  // ideal" in qml_text("TrackMap")


def test_session_best_point_color_sent_as_best():
    assert '"bestColor": "" + theme.purple' in qml_text("SessionView")  # GPU lap points (lap_session.session_shapes)
    assert "color: theme.accent  // not purple" in qml_text("SessionView")  # trend line never looks like best


# --- Empty states, tints, labels
def test_track_map_viewer_one_state_view():
    text = qml_text("TrackMapViewer")
    assert "TpStateView {" in text and 'objectName: "mapState"' in text
    assert "EmptyState {" not in text and "TpLoadingState {" not in text


@pytest.mark.parametrize("name", ["SimpleView", "SessionView", "GCircle", "XYView", "TrackMapViewer"])
def test_named_tints(name):
    text = qml_text(name)
    assert not re.search(r"theme\.tint\([^()]*(\([^()]*\))?[^()]*, *0?\.[0-9]+\)", text)
    assert text.count("Qt.rgba(") <= {"GCircle": 1, "TrackMapViewer": 1}.get(name, 0)


def test_passage_tool_label():
    from neopedal.i18n.fr import TRANSLATION

    assert 'i18n.tr("A-B Passage")' in qml_text("LapViewer") and 'i18n.tr("Range")' not in qml_text("LapViewer")
    assert TRANSLATION["A-B Passage"] == "Passage A-B"


# --- Car setup differences: telemetry component
def test_car_setup_diff_moved():
    assert os.path.dirname(qml_path("CarSetupDiff.qml")) == TELEMETRY
    assert not os.path.exists(os.path.join(os.path.dirname(TELEMETRY), "config", "SetupDiff.qml"))
    for name in ("LapViewer", "LapList"):
        text = qml_text(name)
        assert "CarSetupDiff {" in text and 'import "../config"' not in text


def test_car_setup_diff_loads(opener, warnings):  # noqa: F811
    from PySide6.QtCore import QObject

    dialog = opener()
    popup = dialog.view.rootObject().findChild(QObject, "setupDiff")
    assert popup is not None and popup.property("title")
    key = next(lap.key for lap in dialog.backend.data.laps if lap is not dialog.backend.data.reference)
    evaluate(dialog.view, popup, f"show({key!r})")
    wait(0.3)
    evaluate(dialog.view, popup, "close()")
