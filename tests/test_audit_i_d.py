"""Audit I lot D: Director desk & timing table, shared list rows. Shortest shot bar moved on in steps (no eased move
restarted at every tick), timing cells made by the backend (one role per row, required roles), list rows fading
only to or from a state (stripe flips of sorted or recycled rows shown at once), recycled rows shown at once"""

import re
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QObject, qInstallMessageHandler
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickItem

from tests.test_broadcast_director import car, director_page, poll, race_answers  # noqa: F401

QML = Path(__file__).resolve().parents[1] / "neopedal" / "ui" / "qml"


def qml(relative: str) -> str:
    return (QML / relative).read_text(encoding="utf-8")


def process_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def descendants(item: QQuickItem):
    for child in item.childItems():
        yield child
        yield from descendants(child)


# --- Timing cells made by the backend (architecture 4 & 5)
def timing_row(**values) -> dict:
    row = {"tyreList": ["S", "M"], "battle": False, "trend": 0, "changeValue": 0, "energyLevel": -1.0,
           "intervalTone": "", "gapTone": "", "bestTone": "", "lastTone": "", "s1Tone": "", "s2Tone": "", "s3Tone": "",
           "energyTone": "", "statusTone": "", "interval": "+0.8", "gap": "+1.2", "best": "1:30.000", "change": "",
           "energy": "", "status": "", "driver": "Driver 1", "penalties": "", "tyres": "S/M"}
    row.update(values)
    return row


def test_timing_cell_texts_and_tones():
    from neopedal.ui.quick.director_timing import timing_cell, timing_cells

    assert timing_cell(timing_row(), "tyres") == {"text": "", "tone": "", "tyres": ["S", "M"]}
    assert timing_cell(timing_row(bestTone="fastest"), "best") == {"text": "1:30.000 ◆", "tone": "fastest"}  # mark after
    assert timing_cell(timing_row(bestTone="gain"), "best") == {"text": "1:30.000 ●", "tone": "gain"}
    assert timing_cell(timing_row(bestTone="yellow"), "best") == {"text": "1:30.000", "tone": "yellow"}
    assert timing_cell(timing_row(), "driver") == {"text": "Driver 1", "tone": ""}
    # Battle: trend arrow, accent unless the gap has its own color (no tone mark)
    assert timing_cell(timing_row(battle=True, trend=-1), "interval") == {"text": "▼ +0.8", "tone": "accent"}
    assert timing_cell(timing_row(battle=True, trend=1, intervalTone="loss"), "interval") == {"text": "▲ +0.8",
                                                                                            "tone": "loss"}
    assert timing_cell(timing_row(battle=True), "interval")["text"] == "• +0.8"
    assert timing_cell(timing_row(intervalTone="warning"), "interval") == {"text": "+0.8", "tone": "warning"}
    # Places gained: no mark, gain or loss color
    assert timing_cell(timing_row(change="▲2", changeValue=2), "change") == {"text": "▲2", "tone": "gain"}
    assert timing_cell(timing_row(change="▼1", changeValue=-1), "change") == {"text": "▼1", "tone": "loss"}
    assert timing_cell(timing_row(), "change") == {"text": "", "tone": ""}
    # Energy: level for the bar, tone & mark as the other toned columns; status mark too
    assert timing_cell(timing_row(energy="80%", energyLevel=0.8, energyTone="gain"), "energy") == {
        "text": "● 80%", "tone": "gain", "level": 0.8}
    assert timing_cell(timing_row(status="Finished", statusTone="gain"), "status") == {"text": "● Finished",
                                                                                      "tone": "gain"}
    assert timing_cell(timing_row(penalties="2"), "penalties") == {"text": "2", "tone": ""}
    assert [cell["text"] for cell in timing_cells(timing_row(), ("driver", "gap"))] == ["Driver 1", "+1.2"]


def test_timing_rows_carry_cells_of_shown_columns(director_page):  # noqa: F811
    from neopedal.ui.quick import director_shared as ds

    page, backend = director_page, director_page.backend
    poll(page, race_answers(100.0, car(1, 1, distance=1040.0, best=90.0), car(2, 2, distance=1000.0, penalties=1)))
    timing = backend.timing
    timing.setTimingOpen(True)
    model = timing.timingRows
    roles = {bytes(name).decode() for name in model.roleNames().values()}
    assert roles == {*ds.TIMING_ROLES, "cells"}

    def texts(row: int) -> list[str]:
        return [cell["text"] for cell in model.rows[row]["cells"]]

    shown = [column["key"] for column in timing.timingColumns]
    assert len(model.rows[1]["cells"]) == len(shown)
    assert texts(1)[shown.index("driver")] == "Driver 2" and texts(1)[shown.index("penalties")] == "1"
    assert texts(1)[shown.index("interval")].endswith("+0.8") and model.rows[1]["battle"]
    assert texts(0)[shown.index("best")].endswith(" ◆")  # best of class mark
    # Column moved, shown, hidden, other view: cells follow at once (no wait for the next game answer)
    timing.moveTimingColumn(shown.index("driver"), 0)
    assert texts(1)[0] == "Driver 2"
    timing.toggleTimingColumn("team")
    assert texts(1)[-1] == "Team 2" and len(texts(1)) == len(timing.timingColumns)
    timing.setTimingView(1)
    assert [column["key"] for column in timing.timingColumns] == list(ds.TIMING_VIEWS["qualifying"])
    assert len(texts(0)) == len(ds.TIMING_VIEWS["qualifying"])
    assert {bytes(name).decode() for name in model.roleNames().values()} == roles  # roles fixed
    timing.setTimingView(0)
    timing.resetTimingColumns()
    timing.setTimingOpen(False)


def test_timing_table_cells_drawn_from_cells_role(director_page):  # noqa: F811
    page, backend = director_page, director_page.backend
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        root = page.view.rootObject()
        page.resize(1400, 900)
        page.show()
        process_events(0.2)
        cars = [car(1, 1, distance=1040.0, best=90.0), car(2, 2, distance=1000.0, penalties=1)]
        poll(page, race_answers(100.0, *cars))
        table = root.findChild(QObject, "timingTable")
        table.setProperty("visible", True)
        process_events(0.3)
        view = root.findChild(QQuickItem, "timingList")
        model = backend.timing.timingRows
        theme = page.view.rootContext().contextProperty("theme")

        def cells(key: str) -> list[QQuickItem]:
            found = [item for item in descendants(view.property("contentItem"))
                     if item.property("key") == key and item.property("size") is not None]
            return sorted(found, key=lambda item: item.mapToScene(item.position()).y())

        assert [item.property("text") for item in cells("driver")] == ["Driver 1", "Driver 2"]
        interval = cells("interval")[1]
        shown =[column["key"] for column in backend.timing.timingColumns]
        assert interval.property("text") == model.rows[1]["cells"][shown.index("interval")]["text"]
        assert QColor(interval.property("color")) == QColor(theme.property("accent"))  # battle without gap tone
        best = cells("best")[0]
        assert best.property("text").endswith(" ◆")
        assert QColor(best.property("color")) == QColor(theme.property("purple"))
        assert cells("penalties")[1].property("text") == "1"
        backend.timing.moveTimingColumn(shown.index("driver"), 0)
        process_events(0.1)
        assert [item.property("text") for item in cells("driver")] == ["Driver 1", "Driver 2"]
        marks = [item.property("text") for item in descendants(view.property("contentItem"))
                 if item.property("text") in ("◉", "⚠") and item.isVisible()]
        assert marks == ["◉"]  # car on air (focus 1)
        backend.timing.resetTimingColumns()
        table.setProperty("exit", None)
        table.setProperty("visible", False)
        process_events(0.2)
    finally:
        qInstallMessageHandler(previous)
        backend.timing.setTimingOpen(False)
    problems = [text for text in messages if "DirectorTiming" in text or "TpListRow" in text]
    assert not problems, problems


def test_timing_delegate_binds_required_roles_only():
    text = qml("director/DirectorTiming.qml")
    assert "rowData" not in text and "model." not in text.replace("model: backend", "")
    delegate = text[text.index('objectName: "timingList"'):]
    for role in ("int index", "int slot", "string classColor", "bool onAir", "bool yellow", "var cells"):
        assert f"required property {role}" in delegate, role
    assert "row.cells[index]" in delegate and "ListView.onPooled: live = false" in delegate


# --- Shortest shot bar (B2, architecture 8)
def test_shot_bar_moved_on_in_steps():
    desk = qml("director/DirectorDesk.qml")
    bar = desk[desk.index("id: shotBar"):desk.index("// Automatic mode held after an operator cut")]
    assert "animated: false" in bar
    interval = re.search(r"interval: (.+)", bar).group(1)
    assert interval.startswith("Math.max(200,")  # 5 steps a second at most
    assert "pageState.active" in bar and "shotBar.value < 1" in bar  # stops when hidden or full
    meter = qml("components/TpMeter.qml")
    assert meter.count("enabled: meter.animated") == 3  # width, height & color


# --- QML rows & meters, alone
@pytest.fixture
def rows_view(ui_env, tmp_path, monkeypatch):
    from PySide6.QtCore import QEvent, QUrl
    from PySide6.QtQuickWidgets import QQuickWidget

    import neopedal.ui.quick as quick
    from neopedal.ui.quick import Theme, Translator, qml_folder_imports, register_types, theme_copy

    monkeypatch.setattr(quick, "_ANIMATIONS", [True])  # motion tokens on (system setting may turn them off)
    register_types()
    wrapper = tmp_path / "rows.qml"
    wrapper.write_text(f'''import QtQuick
{qml_folder_imports()}
Column {{
    width: 300; height: 200
    TpListRow {{ objectName: "row"; width: 300; height: 30 }}
    TpListRow {{ objectName: "selectedRow"; width: 300; height: 30; selected: true }}
    TpMeter {{ objectName: "meter"; width: 200; value: 0.2; animated: false }}
    TpMeter {{ objectName: "easedMeter"; width: 200; value: 0.2 }}
}}
''', encoding="utf-8")
    view = QQuickWidget()
    context = view.rootContext()
    theme = theme_copy(view.engine(), Theme(view))
    context.setContextProperty("theme", theme)
    context.setContextProperty("i18n", Translator(view))
    view.setSource(QUrl.fromLocalFile(str(wrapper)))
    assert not view.errors(), [error.toString() for error in view.errors()]
    view.resize(300, 200)
    view.show()
    QCoreApplication.processEvents()
    yield view, theme
    view.close()
    view.setSource(QUrl())
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def color_of(item) -> QColor:
    return QColor(item.property("color"))


def test_list_row_fades_states_not_stripes(rows_view):
    view, theme = rows_view
    root = view.rootObject()
    row = root.findChild(QObject, "row")
    assert theme.property("motionFast") > 0
    transparent = color_of(row)
    assert transparent.alpha() == 0
    # Made selected: shown at once (no fade in when a list is filled)
    selected = root.findChild(QObject, "selectedRow")
    assert color_of(selected) == QColor(selected.property("shade")) and color_of(selected).alpha() > 0
    # Stripe alone (row moved by a sort, recycled row): at once, both ways
    row.setProperty("striped", True)
    stripe = QColor(row.property("shade"))
    assert stripe.alpha() > 0 and color_of(row) == stripe
    row.setProperty("striped", False)
    assert color_of(row) == transparent
    row.setProperty("striped", True)
    # Hover on & off: fades from the stripe and back to it
    row.setProperty("hovered", True)
    hovered = QColor(row.property("shade"))
    assert color_of(row) != hovered  # fade running
    process_events(0.4)
    assert color_of(row) == hovered
    row.setProperty("hovered", False)
    assert color_of(row) != stripe  # back to the stripe: fades too
    process_events(0.4)
    assert color_of(row) == stripe
    # Stripe flip under a state: state color kept, nothing moves
    row.setProperty("selected", True)
    process_events(0.4)
    chosen = color_of(row)
    row.setProperty("striped", False)
    assert color_of(row) == chosen
    # Recycled row fed another entry (animate false): at once
    row.setProperty("animate", False)
    row.setProperty("selected", False)
    assert color_of(row) == transparent
    row.setProperty("emphasized", True)
    assert color_of(row) == QColor(row.property("shade"))


def test_meter_shown_at_once_when_not_animated(rows_view):
    view, _ = rows_view
    root = view.rootObject()
    meter, eased = root.findChild(QObject, "meter"), root.findChild(QObject, "easedMeter")

    def fill(item) -> float:
        return item.childItems()[0].width()

    assert fill(meter) == pytest.approx(40.0)
    meter.setProperty("value", 0.7)
    assert fill(meter) == pytest.approx(140.0)  # no eased move
    eased.setProperty("value", 0.7)
    assert fill(eased) == pytest.approx(40.0)  # eased move started
    process_events(0.5)
    assert fill(eased) == pytest.approx(140.0)


# --- Recycled rows of the lists (B10): row look shown at once while fed another entry
@pytest.mark.parametrize("relative, row_id", [
    ("analysis/StatsTable.qml", "rowItem"), ("analysis/RaceHistory.qml", "lapRow"),
    ("analysis/ResultsSessionList.qml", "row"), ("analysis/RaceLiveTab.qml", "liveRow"),
    ("director/DirectorTiming.qml", "row"),
])
def test_recycled_rows_not_faded(relative, row_id):
    text = qml(relative)
    assert re.search(r"ListView\.onPooled: [^\n]*live = false", text), relative
    assert "ListView.onReused: live = true" in text, relative
    assert f"animate: {row_id}.live" in text, relative
