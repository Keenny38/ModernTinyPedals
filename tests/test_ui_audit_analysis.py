"""UI audit, analysis zone (driver stats, race calculator, results & replays): shared components instead of page
copies, keyboard & screen reader access, color never alone, undo after changes made without confirmation"""

import fnmatch
import os
import re

import pytest
from PySide6.QtCore import QCoreApplication, QMetaObject, QObject

from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.ui.quick import qml_files
from tests.test_driver_stats_viewer import dialogs  # noqa: F401 (fixtures)
from tests.test_driver_stats_viewer import page as stats_view  # noqa: F401
from tests.test_race_calculator import host, page, set_race  # noqa: F401

ZONE = ("DriverStats", "Stats*", "Race*", "Results*", "ReplayView", "ReplayList")


def zone_files() -> dict[str, str]:
    files = {}
    for name in ZONE:
        for path in [path for path in qml_files() if fnmatch.fnmatch(os.path.basename(path), f"{name}.qml")]:
            with open(path, encoding="utf-8") as file:
                files[os.path.basename(path)] = file.read()
    return files


def zone_matches(pattern: str) -> list[str]:
    regex = re.compile(pattern)
    return [f"{name}:{number}: {line.strip()}" for name, text in zone_files().items()
            for number, line in enumerate(text.split("\n"), 1) if regex.search(line)]


# --- Shared components, tokens
def test_page_copies_replaced_by_shared_components():
    for name in ("StatsCard", "RaceCard", "StatsTile", "RaceTile"):
        assert not any(os.path.basename(path) == f"{name}.qml" for path in qml_files()), name
        assert zone_matches(rf"\b{name}\s*\{{") == [], name
    switch = zone_files()["RaceSwitch.qml"]
    assert "TpSwitch {" in switch  # focus ring, Space / Enter, wrapped label of the shared switch


def test_no_icon_font_hacks_nor_pixel_fonts():
    """Icon only buttons use TpButton fallback; text sizes are font tokens"""
    assert zone_matches(r'theme\.iconFont === ""') == []
    assert zone_matches(r"font\.pixelSize") == []


def test_one_session_color_and_live_color():
    assert zone_matches(r"function sessionColor") == []
    badge = zone_files()["ResultsBadge.qml"]
    assert "theme.sessionColor(" in badge
    # Stats session badge: the Results & Replays one (letter & session color)
    assert "ResultsBadge {" in zone_files()["StatsRecentCard.qml"] and "ResultsBadge {" in zone_files()["StatsProgressionCard.qml"]
    # Live: theme.live everywhere (never gain or loss)
    assert zone_matches(r"i18n\.tr\(\"Live\"\).*color: theme\.(gain|loss)") == []
    replay = zone_files()["ReplayView.qml"]
    assert 'name === "session" ? theme.live' in replay


def test_color_never_alone():
    files = zone_files()
    assert "font.strikeout: invalidValue" in files["RaceHistory.qml"]  # invalid laps struck through
    # Session & own bests: shared record mark (TpLapTime ◆ / ●)
    assert 'record: tone === "purple" ? "session" : tone === "gain" ? "personal"' in files["ResultsLaps.qml"]
    assert 'tyreMark: "◆"' in files["RaceTimeline.qml"]  # tyre changes
    assert "font.italic: !stintRow.usable" in files["RaceTeamTab.qml"]


def test_no_opacity_on_texts_of_rows():
    """Dimmed rows & disabled values: dim text color, never opacity over text"""
    assert zone_matches(r"opacity: usable \? 1") == []
    assert zone_matches(r"opacity: liveRow\.known") == []
    assert zone_matches(r"opacity: detailCard") == []


def test_raw_text_fields_replaced():
    """Text inputs of the calculator: TpTextField (Esc reverts & is taken, invalid state)"""
    assert zone_matches(r"^\s*TextField \{") == []


# --- Race calculator: undo, toasts, validation, keyboard
def test_undo_redo_state_follows_history(page, host):  # noqa: F811
    backend = page.backend
    page.backend.setGameData(True)
    page.reset_undo()
    assert not backend.canUndo and not backend.canRedo
    backend.setInput("input_race_laps", 31)
    assert backend.canUndo and not backend.canRedo
    backend.undo()
    assert backend.canRedo


def test_changes_without_confirmation_offer_undo(page, host, monkeypatch):  # noqa: F811
    from neopedal.ui import race_calculator

    undo_toasts: list[str] = []
    monkeypatch.setattr(race_calculator.RaceCalculator, "toast_undo", lambda self, text: undo_toasts.append(text))
    backend = page.backend
    backend.setGameData(True)
    set_race(backend, laps=30)
    backend.resetValues()
    assert undo_toasts == ["Every input reset to zero"] and not host.asked
    backend.removeUnusedTyres()  # nothing unused: plain toast
    assert host.toasts[-1] == "No unused tyre in stock"


def test_lap_and_start_time_validity(page):  # noqa: F811
    backend = page.backend
    assert backend.lapTimeValid("1:32.500") and not backend.lapTimeValid("1:3x")
    assert backend.startTimeValid("14:30") and not backend.startTimeValid("25:99x")


def test_history_keyboard_selection_without_laps(page):  # noqa: F811
    assert page.backend.moveLapSelection(1, False) == -1


def test_page_fields_and_tabs(page, host, monkeypatch):  # noqa: F811
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    page.backend.setGameData(True)
    view = page.ensure_view()
    root = view.rootObject()
    QCoreApplication.processEvents()
    field = root.findChild(QObject, "lapTimeField")
    assert field is not None and field.property("invalid") is False
    shown = field.property("text")
    field.setProperty("text", "9:9")
    QMetaObject.invokeMethod(field, "escaped")  # Esc: typed text dropped
    assert field.property("text") == shown
    tabs = root.findChild(QObject, "raceTabs")
    assert tabs is not None and tabs.property("activeFocusOnTab")
    for tab in range(4):
        page.backend.setTab(tab)
        QCoreApplication.processEvents()
    assert not view.errors(), [error.toString() for error in view.errors()]


@pytest.mark.parametrize("width", [560, 900, 1500])
def test_page_loads_at_any_width(page, host, width):  # noqa: F811
    page.backend.setGameData(True)
    view = page.ensure_view()
    page.resize(width, 700)
    for tab in range(4):
        page.backend.setTab(tab)
        for _ in range(3):
            QCoreApplication.processEvents()
    assert not view.errors(), [error.toString() for error in view.errors()]


# --- Driver stats header: toolbar fitted to its width (texts, then icons only, then "⋯")
def toolbar_buttons(root, names):
    """Buttons of a toolbar by objectName (Repeater items: searched in the item tree)"""
    found, stack = {}, [root]
    while stack:
        item = stack.pop()
        if item.objectName() in names:
            found[item.objectName()] = item
        stack.extend(item.childItems())
    return {name: found.get(name) for name in names}


def test_stats_header_actions_fit_page_width(stats_view):  # noqa: F811
    names = ("mapButton", "telemetryButton", "undoButton", "redoButton", "exportButton", "viewButton",
             "referenceButton", "moreButton")
    stats_view.show()
    root = stats_view.view.rootObject()
    toolbar = root.findChild(QObject, "statsToolbar")
    buttons = toolbar_buttons(root, names)
    assert toolbar is not None and all(button is not None for button in buttons.values()), buttons
    stats_view.resize(1700, 860)
    for _ in range(5):
        QCoreApplication.processEvents()
    assert not toolbar.property("overflowing")
    assert buttons["exportButton"].property("text") == "Export"
    stats_view.resize(700, 860)
    for _ in range(5):
        QCoreApplication.processEvents()
    assert toolbar.property("width") >= toolbar.property("implicitWidth") or toolbar.property("overflowing")
    assert buttons["moreButton"].property("visible")  # pinned: reload, backups & delete always reachable
    assert not stats_view.view.errors(), [error.toString() for error in stats_view.view.errors()]
