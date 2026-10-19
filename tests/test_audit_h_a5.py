"""Audit H, lot A5 (QML pages): lap chips of G circle & XY view never leave a lap hidden for good, value
bubble width measured once per cursor update, axis ticks capped, numbers with the decimal comma in French,
animations off honoured, track map speed texts not placed on every zoom frame, shared LiveClock / TpPulseDot /
TpToast components, session tab statistics worked out by backend"""

import math
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.ui.quick import qml_folder_imports, qml_path
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import chart_of, evaluate, find, items, opener, wait, warnings  # noqa: F401


def qml(name: str) -> str:
    return Path(qml_path(name)).read_text(encoding="utf-8")


def pump(seconds: float = 0.05):
    end = time.monotonic() + seconds
    while True:
        QCoreApplication.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.005)


def child(root, name: str):
    from PySide6.QtCore import QObject

    return root.findChild(QObject, name)


@pytest.fixture
def harness(ui_env, tmp_path, monkeypatch):
    """QML text loaded as a page (theme, i18n & pageState of real pages, ui/qml components importable),
    QML warnings collected"""
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick import create_quick_view

    found: list[str] = []
    set_source = QQuickWidget.setSource

    def watched_source(view, url):
        view.engine().setOutputWarningsToStandardError(False)
        view.engine().warnings.connect(lambda errors: found.extend(error.toString() for error in errors))
        set_source(view, url)

    monkeypatch.setattr(QQuickWidget, "setSource", watched_source)
    parent = QWidget()
    loaded: list = []  # views & their context objects: kept until views are unloaded

    def load(text: str, context: dict | None = None):
        path = tmp_path / f"Harness{len(loaded)}.qml"
        path.write_text(f'import QtQuick\n{qml_folder_imports()}\n{text}', encoding="utf-8")
        view = create_quick_view(parent, str(path), context or {}, samples=0)
        loaded.append((view, context))
        assert not view.errors(), [error.toString() for error in view.errors()]
        view.resize(600, 400)
        pump()
        return view, view.rootObject()

    yield load
    for view, _ in loaded:  # pages unloaded before their backends go
        view.setSource(QUrl())
    pump()
    loaded.clear()
    parent.deleteLater()
    pump()
    assert not found, found


# --- 1. Lap chips: a lap left alone is shown, hidden laps no longer compared forgotten
def legend_backend(keys):
    from PySide6.QtCore import Property, QObject, Signal

    class Backend(QObject):
        chartChanged = Signal()

        def __init__(self):
            super().__init__()
            self._legend = [{"key": key} for key in keys]

        @Property(list, notify=chartChanged)
        def legend(self):
            return self._legend

        @Property(QObject, constant=True)
        def legendModel(self):
            return None

        def show(self, *shown):
            self._legend = [{"key": key} for key in shown]
            self.chartChanged.emit()

    return Backend()


def test_lap_filter_never_leaves_a_lap_hidden(harness):
    backend = legend_backend(["a", "b", "c"])
    _, root = harness("""Item {
    readonly property var states: [lapFilter.shown("a"), lapFilter.shown("b"), lapFilter.shown("c")]
    function hide(key) { lapFilter.toggle(key) }
    LapFilter { id: lapFilter; objectName: "lapFilter" }
}""", {"backend": backend})

    def states():
        pump()
        return [bool(value) for value in root.property("states").toVariant()]

    from PySide6.QtCore import Q_ARG, QMetaObject

    def hide(key):
        QMetaObject.invokeMethod(root, "hide", Q_ARG("QVariant", key))

    hide("a")
    hide("b")
    assert states() == [False, False, True]
    backend.show("a", "c")  # b no longer compared: forgotten, shown once compared again
    backend.show("a", "b", "c")
    assert states() == [False, True, True]
    backend.show("a")  # lap alone: shown (its chip is hidden, it could not be shown again)
    assert states()[0] is True and child(root, "lapFilter").property("visible") is False
    backend.show("a", "b")  # still shown with another lap
    assert states()[:2] == [True, True]


# --- 2 & 11. Value bubble width from one measure per cursor update, chip texts translated once
def test_value_bubble_width_measured_once(opener, warnings):  # noqa: F811
    dialog = opener()
    view = dialog.view
    chart = chart_of(view)
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.3)
    bubbles = [item for item in find(view, lambda item: item.property("panelIndex") is not None
                                     and item.property("info") is not None) if item.isVisible()]
    assert bubbles
    for bubble in bubbles:  # widest line of each panel bubble
        rows = [item for item in items(bubble) if item.property("entry") is not None and item.isVisible()]
        widest = max(item.width() for item in rows)
        measured = evaluate(view, chart, f"valueWidth({bubble.property('panelIndex')})")
        assert widest - 1 <= measured <= widest + 2
    text = qml("TraceChart.qml")
    assert "valueRows.itemAt" not in text and "bubble.visible ? chart.valueWidth(bubble.panelIndex) : 0" in text
    # Chip tooltips (LapChip): full lap name only while hovered or focused (not bound for every chip)
    assert 'tip: chip.hovered || chip.activeFocus ? model.full' in text
    assert 'tip: chip.hovered || chip.activeFocus ? model.full' in qml("LapFilter.qml")


# --- 3. Axis ticks: as many as grid & label repeaters (40) on wide charts
def test_tick_count_capped(opener, warnings):  # noqa: F811
    dialog = opener()
    view = dialog.view
    chart = chart_of(view)
    count = evaluate(view, chart, "(viewRange[1] - viewRange[0]) / niceStep(viewRange[1] - viewRange[0], "
                                  "Math.min(4000 / (theme.em * 6), 38)) + 1")
    assert count <= 40
    assert "Math.min(plotArea.width / (theme.em * 6), 38)" in qml("TraceChart.qml")
    assert qml("TraceChart.qml").count("model: 40") == 2


# --- 4. Decimal comma in French, both separators read back
@pytest.fixture
def french():
    from neopedal import i18n

    i18n.set_language("Français")
    yield
    i18n.set_language("English")


def test_number_field_decimal_comma_in_french(french, harness):
    from PySide6.QtCore import QMetaObject

    _, root = harness("""Item {
    property var edits: []
    NumberField { objectName: "field"; decimals: 2; value: 1.5; onEdited: function(value) { edits = edits.concat([value]) } }
}""")
    field = child(root, "field")
    assert field.property("text") == "1,50"
    QMetaObject.invokeMethod(field, "commit")  # text as shown: no change
    assert root.property("edits").toVariant() == []
    for typed in ("2,25", "2.75"):
        field.setProperty("text", typed)
        QMetaObject.invokeMethod(field, "commit")
    assert root.property("edits").toVariant() == [2.25, 2.75]
    assert '.toFixed(decimals).replace(".", theme.decimalPoint)' in qml("RaceFuelTab.qml")
    assert 'changeTime.toFixed(2).replace(".", theme.decimalPoint)' in qml("RaceTyreTab.qml")


# --- 5, 6, 7. Animations off honoured, ValueRow tip read from the row, no redeclared property
def test_animations_follow_theme_and_small_fixes():
    assert "duration: theme.animate ? 650 : 0" in qml("ResultsPositions.qml")
    replays = qml("ReplayList.qml")  # waiting for the game: shared spinner (runs only while the page is shown)
    assert "TpLoadingState" in replays and "loops: Animation.Infinite" not in replays
    assert "running: state.visible && pageState.active" in qml("TpLoadingState.qml")
    for name in ("SettingRow.qml", "OverlayOptionRow.qml"):
        text = qml(name)
        assert "duration: theme.animate ? 350 : 0" in text and "duration: theme.animate ? 700 : 0" in text, name
    fuel = qml("RaceFuelTab.qml")
    # Label & value rows: TpKeyValue (tooltip only when there is one)
    assert "TpKeyValue {" in fuel and "parent.tip" not in fuel
    assert 'enabled: pair.tip !== "" || labelText.truncated' in qml("TpKeyValue.qml")
    assert "property bool danger" not in qml("PresetDetails.qml")


# --- 8. Speed texts of track map placed once zoom settles, hidden while it eases
def test_map_speed_texts_wait_for_zoom(harness):
    _, root = harness("""Item {
    width: 400; height: 300
    MapCanvas { objectName: "canvas"; anchors.fill: parent; minX: 0; maxX: 100; minY: 0; maxY: 100 }
}""", {})
    canvas = child(root, "canvas")
    from PySide6.QtCore import Q_ARG, QMetaObject

    assert canvas.property("zooming") is False
    QMetaObject.invokeMethod(canvas, "setView", Q_ARG("QVariant", 3.0), Q_ARG("QVariant", 0.0),
                             Q_ARG("QVariant", 0.0), Q_ARG("QVariant", True), Q_ARG("QVariant", None))
    assert canvas.property("zooming") is True
    end = time.monotonic() + 3
    while canvas.property("zooming") and time.monotonic() < end:
        pump(0.02)
    assert canvas.property("zooming") is False and canvas.property("zoom") == pytest.approx(3.0)
    text = qml("TrackMap.qml")
    assert "visible: !canvas.zooming" in text and "modelData.x * speedLabels.pointScale" in text


# --- 9. Shared components
def test_live_clock_moves_between_answers(harness):
    _, root = harness("""Item {
    LiveClock { objectName: "clock"; active: false }
}""")
    clock = child(root, "clock")
    now_ms = time.time() * 1000
    clock.setProperty("time", 100.0)
    clock.setProperty("received", now_ms - 2000)  # answer 2 s ago
    assert clock.property("now") == 100.0
    from PySide6.QtCore import QMetaObject

    QMetaObject.invokeMethod(clock, "triggered")
    assert clock.property("now") == pytest.approx(102.0, abs=0.2)
    clock.setProperty("received", now_ms - 20000)  # no answer for long: 3 s at most
    assert clock.property("now") == 100.0  # new answer: answered time
    clock.setProperty("rate", 2.0)
    QMetaObject.invokeMethod(clock, "triggered")
    assert clock.property("now") == pytest.approx(106.0)
    assert clock.property("running") is False  # inactive (page hidden)
    clock.setProperty("active", True)
    assert clock.property("running") is True
    clock.setProperty("rate", 0.0)
    assert clock.property("running") is False  # clock still


def test_live_clock_format(harness):
    _, root = harness("""Item {
    readonly property var texts: [ticker.format(0), ticker.format(59.9), ticker.format(3725), ticker.format(-5)]
    LiveClock { id: ticker; active: false }
}""")
    assert root.property("texts").toVariant() == ["0:00:00", "0:00:59", "1:02:05", "0:00:00"]


def test_pulse_dot_and_toast(harness):
    from PySide6.QtCore import QMetaObject

    _, root = harness("""Item {
    width: 600; height: 400
    TpPulseDot { objectName: "dot"; pulsing: true; color: theme.gain }
    TpToast { objectName: "toast"; text: "Done"; error: true; duration: 50 }
}""")
    dot, toast = child(root, "dot"), child(root, "toast")
    assert dot.property("width") == dot.property("height") > 0
    assert toast.property("shown") is False
    QMetaObject.invokeMethod(toast, "show")
    assert toast.property("shown") is True
    end = time.monotonic() + 2
    while toast.property("shown") and time.monotonic() < end:
        pump(0.02)
    assert toast.property("shown") is False  # hidden after its duration


def test_pages_use_shared_components():
    for name in ("BroadcastDirector.qml", "ReplayView.qml", "IncidentPanel.qml"):
        text = qml(name)
        assert "function clock(" not in text and "LiveClock {" in text, name
    for name in ("BroadcastDirector.qml", "RaceResults.qml", "StreamOverlays.qml"):
        assert "TpToast {" in qml(name) and "toastTimer" not in qml(name), name
    for name in ("BroadcastDirector.qml", "DriverStats.qml", "ReplayView.qml", "RaceCalculator.qml",
                 "StreamOverlays.qml"):
        text = qml(name)
        # Status dot of its own, or Pill { dot: true; pulsing: ... } (TpPulseDot inside)
        assert "loops: 3" not in text and ("TpPulseDot {" in text or "pulsing:" in text), name
    stats = qml("DriverStats.qml")
    assert "component EmptyState" not in stats and "StatsEmpty {" in stats


# --- 10. Session tab statistics from backend, same numbers as the former QML code
FORMER_QML = """
(function(laps) {
    var valid = laps.filter(function(lap) { return lap.valid && lap.time > 0 })
    var sum = 0, fuel = 0, fuelCount = 0
    for (var i = 0; i < valid.length; i++) sum += valid[i].time
    var mean = valid.length ? sum / valid.length : 0
    var deviation = 0
    for (var j = 0; j < valid.length; j++) deviation += Math.pow(valid[j].time - mean, 2)
    deviation = valid.length > 1 ? Math.sqrt(deviation / (valid.length - 1)) : 0
    for (var k = 0; k < laps.length; k++) if (laps[k].fuel >= 0) { fuel += laps[k].fuel; fuelCount++ }
    var range = (function() {
        var times = laps.filter(function(lap) { return lap.time > 0 && lap.kind === "lap" }).map(function(lap) { return lap.time })
        if (times.length === 0) return [0, 1]
        var sorted = times.slice().sort(function(a, b) { return a - b })
        var low = sorted[0]
        var high = Math.min(sorted[sorted.length - 1], sorted[Math.floor((sorted.length - 1) * 0.9)] * 1.03)
        if (high - low < 0.5) { low -= 0.25; high += 0.25 }
        return [low - (high - low) * 0.08, high + (high - low) * 0.08]
    })()
    var strip = function(name) {
        var high = 0
        for (var i = 0; i < laps.length; i++) high = Math.max(high, laps[i][name] || 0)
        return high
    }
    return {"stats": {"count": valid.length, "mean": mean, "deviation": deviation, "fuel": fuel, "fuelCount": fuelCount},
            "range": range, "fuel": strip("fuel"), "wear": strip("wear")}
})
"""


def row(time_, valid=True, kind="lap", fuel=-1.0, wear=-1.0):
    return {"time": time_, "valid": valid, "kind": kind, "fuel": fuel, "wear": wear}


@pytest.mark.parametrize("rows", [
    [],
    [row(91.2, fuel=2.31)],
    [row(95.0, kind="out", fuel=2.5), row(90.123, fuel=2.31, wear=1.2), row(90.877, fuel=2.29, wear=1.1),
     row(91.5, valid=False, fuel=2.4), row(0.0), row(130.2, fuel=3.0, wear=2.5), row(90.4, wear=0.9),
     row(90.6, fuel=2.3), row(90.2), row(89.95, fuel=2.28, wear=1.0), row(90.3)],
    [row(90.0), row(90.1), row(90.2)],
])
def test_session_stats_match_former_qml(rows):
    from PySide6.QtQml import QJSEngine

    from neopedal.ui.quick.lap_session import session_stats, session_time_range

    engine = QJSEngine()
    former = engine.evaluate(FORMER_QML).call([engine.toScriptValue(rows)]).toVariant()
    stats = session_stats(rows)
    assert stats.keys() == former["stats"].keys()
    for key, value in former["stats"].items():
        assert stats[key] == pytest.approx(value, rel=1e-12, abs=1e-12), key
    assert session_time_range(rows) == pytest.approx(former["range"], rel=1e-12)
    for name in ("fuel", "wear"):
        assert max([0.0, *(item[name] or 0.0 for item in rows)]) == pytest.approx(former[name])


def test_session_data_carries_stats(laps):  # noqa: F811
    from PySide6.QtWidgets import QWidget

    from neopedal.setting import cfg
    from neopedal.ui.quick.lap_backend import LapViewerBackend
    from neopedal.ui.quick.lap_session import session_stats, session_time_range
    from tests.test_lap_viewer import wait_loaded  # noqa: F401

    parent = QWidget()
    backend = LapViewerBackend(parent, cfg.path.telemetry)
    backend.refresh()
    end = time.monotonic() + 10
    while backend.loading and time.monotonic() < end:
        pump(0.02)
    data = backend.session.session_data()
    rows = data["laps"]
    assert rows and data["stats"] == session_stats(rows) and data["range"] == session_time_range(rows)
    assert data["stats"]["count"] == sum(1 for item in rows if item["valid"] and item["time"] > 0)
    assert set(data["stripMax"]) == {"fuel", "wear"}
    assert all(math.isfinite(value) for value in data["range"])
    text = qml("SessionView.qml")
    assert "Math.pow" not in text and "sort(" not in text and "root.session.range" in text
    parent.deleteLater()
    pump()


def test_session_tab_shows_backend_stats(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(4)
    wait(0.8)
    session = find(view, lambda item: item.property("sessionState") is not None and item.property("hoverIndex") is not None)[0]
    stats = evaluate(view, session, "stats")
    data = backend.session.state["data"]
    assert stats == data["stats"] and stats["count"] > 0
    canvas = find(view, lambda item: item.property("stripHeight") is not None and item.property("range") is not None)[0]
    assert canvas.property("range") == data["range"]
