"""UI/UX audit, overlays / stream / spectate / Broadcast Director zone: shared components & tokens instead of local
copies (TpChip, TpListRow, TpCardHeader, TpStateView, TpClassStrip, theme.tone), icon buttons readable without icon
font, no faded text, kinds told by shape too, keyboard on lists, chips & cameras, confirmations before losing the
league logo or the captured classification, accent color checked, Broadcast Director stacked in tabs on narrow
pages, pages load without QML warnings"""

import re

import pytest
from PySide6.QtCore import QMetaObject, QObject, Qt
from PySide6.QtTest import QTest

from neopedal.ui.quick import qml_path
from tests.test_audit_g_qml_pages import item_named, items_of, pump, shown_director, wait_until
from tests.test_broadcast_director import car, director_page  # noqa: F401
from tests.test_overlay_options import window  # noqa: F401
from tests.test_overlay_view import overlays, page  # noqa: F401
from tests.test_perf_page_state import qml_warnings  # noqa: F401
from tests.test_spectate_page import setups  # noqa: F401

ZONE = ("Overlays", "OverlayCard", "OverlayListRow", "OverlayOptions", "OverlayOptionRow", "StreamOverlays",
        "Spectate", "SpectateRow", "BroadcastDirector", "DirectorCars", "DirectorCommentary", "DirectorDesk",
        "DirectorGraphics", "DirectorLaps", "DirectorSettings", "DirectorSheet", "DirectorTiming", "StandingsPanel",
        "IncidentPanel", "TpClassStrip")


def qml(name: str) -> str:
    with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
        return file.read()


def blocks(text: str, start: str) -> list[str]:
    """Text of each QML block opened by start ("TpButton {"), nested blocks included"""
    found = []
    for match in re.finditer(re.escape(start), text):
        depth, index = 0, match.start()
        for index in range(match.start(), len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    break
        found.append(text[match.start(): index + 1])
    return found


# --- Static: shared components & tokens
def test_shared_components_instead_of_local_copies():
    for name in ZONE:
        text = qml(name)
        assert "function tone(" not in text, name  # theme.tone()
        assert 'theme.iconFont === ""' not in text and 'theme.iconFont !== ""' not in text, name  # fallback
        assert "OverlayChip {" not in text, name  # TpChip
        assert "SpinBox {" not in text, name  # NumberField
        assert not re.search(r'"#[0-9A-Fa-f]{3,8}"', text), name  # theme colors (stage tokens...)
        assert "font.pixelSize: theme.em" not in text, name
        assert "Qt.rgba(theme." not in text, name  # theme.tint()
    for name in ("Spectate", "Overlays", "DirectorCars", "StandingsPanel", "IncidentPanel", "DirectorGraphics"):
        assert "TpChip {" in qml(name), name
    for name in ("OverlayCard", "OverlayListRow", "SpectateRow"):
        assert "FocusRing { target: surface" in qml(name), name
    for name in ("StreamOverlays", "BroadcastDirector"):
        toast = blocks(qml(name), "TpToast {")[0]
        assert "duration:" not in toast, name  # reading time from text length


def test_icon_buttons_readable_without_icon_font():
    """Icon only buttons give a fallback text (or have a text): never an empty button without icon font"""
    for name in ZONE:
        for button in blocks(qml(name), "TpButton {"):
            head = button.split("{", 1)[1]
            own = re.sub(r"\{[^{}]*\}", "", head)  # nested blocks (dialogs) left out
            if "glyph:" in own:
                text = re.search(r"\n\s*text: (.*)", own)
                always_text = text and not re.search(r'\?\s*""|:\s*""\s*$', text.group(1))
                assert "fallback:" in own or always_text, (name, button[:160])


def test_no_faded_text():
    """Dimmed rows & disabled server in dim text, not opacity (contrast kept)"""
    assert "opacity: dimmed ? 0.45" not in qml("OverlayOptions")
    assert "opacity: row.dimmed ? 0.55" not in qml("OverlayOptionRow")
    assert "opacity: row.dimmed ? 0.6" not in qml("OverlayOptionRow")
    assert "opacity: live ? 1 : 0.6" not in qml("DirectorCommentary")
    assert "opacity: backend.enabled ? 1 : 0.55" not in qml("StreamOverlays")
    assert "Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.72)" not in qml("OverlayListRow")


def test_kinds_told_by_shape_not_color_alone():
    incidents = qml("IncidentPanel")
    assert "radius: marker.wall ? Math.max(1, width * 0.15) : width / 2" in incidents  # wall square
    assert 'fallback: row.wall ? "■" : "●"' in incidents
    for name in ("DirectorLaps", "DirectorSheet"):
        assert '"◆ "' in qml(name), name  # best of class
    from neopedal.ui.quick.director_timing import timing_cell  # timing cells made in Python

    row = {"best": "1:30.000", "bestTone": "fastest", "last": "1:31.000", "lastTone": ""}
    assert timing_cell(row, "best") == {"text": "◆ 1:30.000", "tone": "fastest"}  # best of class
    assert timing_cell(row, "last") == {"text": "1:31.000", "tone": ""}  # plain: no mark
    assert 'toneName === "fastest" ? 0.5' in qml("DirectorCars")  # sector bar heights
    assert '"◉" : row.yellow ? "⚠"' in qml("DirectorTiming")  # on air / yellow marks
    assert "◆ " in qml("StandingsPanel")


def test_keyboard_reaches_rows_cameras_and_chips():
    desk = qml("DirectorDesk")
    camera = blocks(desk, "component CameraButton: AbstractButton {")[0]
    assert "focusPolicy: Qt.TabFocus" in camera and "Keys.onShortcutOverride" in camera
    assert "text: story.index + 1" in desk  # suggestion numbers (keys 1 to 6)
    for name, list_id in (("DirectorCars", "carList"), ("DirectorDesk", "suggestionList"), ("DirectorTiming", "timingList")):
        text = qml(name)
        view = text[text.index(f'objectName: "{list_id}"'):]
        assert "activeFocusOnTab: true" in view[:1500] and "Keys.onShortcutOverride" in view[:2500], name
    assert "component KeyList: ListView" in qml("DirectorCommentary")
    standings = qml("StandingsPanel")
    incidents_button = blocks(standings, "AbstractButton {")[0]
    assert "focusPolicy: Qt.TabFocus" in incidents_button
    assert "Accessible.name: i18n.tr(\"Copy Address\")" not in qml("StreamOverlays")  # token never in tooltips
    assert "tip: source.url" not in qml("StreamOverlays")


# --- Broadcast Director page
def test_director_page_stacks_and_loads_without_warnings(qml_warnings, director_page):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0))
    tabs = item_named(root, "deskTabs")
    assert tabs is not None and not tabs.isVisible()  # 1500 px: three columns
    for name in ("graphicsPopup", "settingsPopup"):
        root.findChild(QObject, name).setProperty("visible", True)
        pump(0.1)
    backend.selectCar(1)
    backend.showLaps(1)
    pump(0.2)
    root.findChild(QObject, "timingTable").setProperty("visible", True)
    pump(0.2)
    for name in ("graphicsPopup", "settingsPopup", "timingTable"):
        root.findChild(QObject, name).setProperty("visible", False)
    backend.showLaps(-1)
    director_page.resize(640, 700)  # under bpWide: one panel at a time
    pump(0.2)
    assert wait_until(lambda: tabs.isVisible())
    cars = item_named(root, "carList")
    assert not cars.isVisible()  # desk tab first
    tabs.setProperty("currentIndex", 0)
    root.setProperty("deskTab", 0)
    pump(0.1)
    assert cars.isVisible() and not item_named(root, "suggestionList").isVisible()
    root.setProperty("deskTab", 2)
    pump(0.1)
    assert item_named(root, "feedList").isVisible() and not cars.isVisible()
    assert not qml_warnings, qml_warnings


def test_car_list_enter_opens_sheet_not_take_best(director_page):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0))
    cars = item_named(root, "carList")
    cars.forceActiveFocus()
    pump()
    assert wait_until(lambda: cars.property("activeFocus"))
    QTest.keyClick(director_page.view, Qt.Key.Key_Down)
    QTest.keyClick(director_page.view, Qt.Key.Key_Return)
    pump()
    assert wait_until(lambda: backend.sheetCar.get("slot") is not None)  # list's Enter: car sheet


def test_logo_removal_confirmed_and_enabled_only_with_logo(director_page, tmp_path):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1))
    graphics = backend.graphics
    graphics.clear_logo()
    assert graphics.hasLogo is False
    picture = tmp_path / "league.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    told = []
    graphics.logoChanged.connect(lambda: told.append(1))
    assert graphics.set_logo(str(picture)) and graphics.hasLogo is True and told
    popup = root.findChild(QObject, "graphicsPopup")
    popup.setProperty("visible", True)
    pump(0.2)
    remove = popup.findChild(QObject, "removeLogo") or item_named(root, "removeLogo")
    dialog = popup.findChild(QObject, "removeLogoDialog") or root.findChild(QObject, "removeLogoDialog")
    assert remove is not None and dialog is not None and remove.property("enabled")
    assert popup.findChild(QObject, "clearResultsDialog") or root.findChild(QObject, "clearResultsDialog")
    assert graphics.clear_logo() and graphics.hasLogo is False
    popup.setProperty("visible", False)


def test_accent_color_checked_before_sent(director_page):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1))
    graphics = backend.graphics
    popup = root.findChild(QObject, "graphicsPopup")
    popup.setProperty("visible", True)
    popup.setProperty("tab", 2)
    pump(0.2)
    field = popup.findChild(QObject, "accentColor") or item_named(root, "accentColor")
    assert field is not None and not field.property("invalid")
    before = graphics.graphicsSettings["accent"]
    field.setProperty("text", "red")
    pump()
    assert field.property("invalid")
    field.setProperty("text", "#12AB34")
    pump()
    assert not field.property("invalid")
    assert graphics.graphicsSettings["accent"] == before  # sent only once typing is finished
    popup.setProperty("visible", False)


# --- Overlays page
def test_overlays_page_chips_and_rows_load_without_warnings(qml_warnings, page):  # noqa: F811
    page.show()
    pump(0.2)
    root = page.view.rootObject()
    chips = [item for item in items_of(root) if "TpChip" in item.metaObject().className()]
    assert chips and all(chip.property("focusPolicy") == Qt.FocusPolicy.TabFocus for chip in chips)
    page.backend.setGridView(False)
    pump(0.2)
    page.backend.setGridView(True)
    pump(0.2)
    assert not qml_warnings, qml_warnings


@pytest.mark.parametrize("name", ["OverlayOptions"])
def test_discard_keeps_undo_a_few_seconds(name):
    text = qml(name)
    bar = text[text.index("id: bar"):]
    assert "undoGrace.running" in bar and "interval: 6000" in bar and 'i18n.tr("Changes discarded")' in bar
    assert "visible: shown || heightAnim.running" in bar  # no hidden buttons in Tab order


# --- Spectate & Overlay Options pages
def test_spectate_page_loads_without_warnings(qml_warnings, setups):  # noqa: F811
    from neopedal.ui.spectate_view import SpectateList
    from tests.test_spectate_page import Reader, flush

    reader = Reader()
    view = SpectateList(None)
    view.backend._reader = lambda: reader
    view.resize(900, 600)
    view.show()
    try:
        pump(0.3)
        root = view.view.rootObject()
        chips = [item for item in items_of(root) if "TpChip" in item.metaObject().className()]
        assert len(chips) >= 2  # All & classes
        view.resize(500, 600)  # compact
        pump(0.1)
    finally:
        view.close()
        view.deleteLater()
        flush()
    assert not qml_warnings, qml_warnings


def test_overlay_options_page_loads_without_warnings(qml_warnings, window):  # noqa: F811
    from neopedal.ui.overlay_options import open_overlay_options

    options_page = open_overlay_options(window, "fuel")
    pump(0.3)
    options_page.backend.setNumber("fuel/opacity", 0.5)
    pump(0.2)
    root = options_page.view.rootObject()
    discard = next(item for item in items_of(root) if item.property("text") == "Discard" and item.isVisible()
                   and "TpButton" in item.metaObject().className())
    QMetaObject.invokeMethod(discard, "click")
    pump(0.2)
    assert options_page.backend.pendingCount == 0
    texts = {item.property("text") for item in items_of(root) if item.isVisible()}
    assert "Changes discarded" in texts  # Undo stays a few seconds
    options_page.backend.selectOverlay("black_box")
    pump(0.3)
    assert not qml_warnings, qml_warnings
