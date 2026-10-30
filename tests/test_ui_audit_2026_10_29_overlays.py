"""UI/UX audit 2026-10-29, overlays lot: switches following their backend (B1), Ctrl+F searching the page & Ctrl+D
favorites (B5), Overlay Options menus instead of combo boxes & filters menu (B6, C2), screen view locks, keyboard,
snapping & background (B7, m8, Layout Editor merged), header switch (C1), preview button (C3), Overlays page counts,
batch switch with Undo & card menu (C4), vocabulary (C5), What's New footer & Try with Undo"""

import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QAction, QImage, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from neopedal.setting import cfg
from neopedal.ui.quick import overlay_backend
from neopedal.ui.quick.overlay_backend import VIEW_SCREEN, OverlayBackend
from tests.test_overlays_page_more import NAMES, FakeControl, settle, solid
from tests.test_release_notes import notes_page, qml_warnings, update_repo  # noqa: F401  (fixtures)
from tests.test_stream_overlay import page_backend, process_events, server  # noqa: F401  (fixtures)

QML_FOLDER = Path(__file__).resolve().parent.parent / "neopedal" / "ui" / "qml"
LOT_FILES = (
    *(QML_FOLDER / "overlays").glob("*.qml"),
    *(QML_FOLDER / "home").glob("Release*.qml"),
)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def wait_jobs(page, timeout: float = 5.0):
    """Background jobs of page finished and their results delivered on the GUI thread"""
    deadline = time.monotonic() + timeout
    while page.jobs.running and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    flush()


def child(quick, name: str) -> QObject:
    found = quick.rootObject().findChild(QObject, name)
    assert found is not None, name
    return found


def children(quick, name: str) -> list[QObject]:
    """Visual items of this object name (delegates of repeaters & loaders too)"""
    found, stack = [], [quick.rootObject()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            found.append(item)
        stack.extend(item.childItems())
    return found


def click(quick, item):
    """Mouse click at the middle of a QML item"""
    point = item.mapToScene(QPointF(item.property("width") / 2, item.property("height") / 2))
    QTest.mouseClick(quick, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point.toPoint())
    QCoreApplication.processEvents()


def press(quick, item):
    """Space on a focused QML control (reached with Tab): pressed as a click"""
    quick.window().activateWindow()
    quick.setFocus()
    item.forceActiveFocus()
    QTest.keyClick(quick, Qt.Key.Key_Space)
    QCoreApplication.processEvents()


def find_key_stays_in_page(quick, host: QWidget, search_name: str):
    """Ctrl+F focuses the page search (from anywhere in the page); Ctrl+Shift+F stays the app's Find Option"""
    fired = []
    action = QAction(host)
    action.setShortcut(QKeySequence("Ctrl+Shift+F"))
    action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    action.triggered.connect(lambda: fired.append(1))
    host.addAction(action)
    host.activateWindow()
    quick.setFocus()
    quick.rootObject().forceActiveFocus()  # focus elsewhere in the page
    QCoreApplication.processEvents()
    search = child(quick, search_name)
    assert not search.property("activeFocus")
    QTest.keyClick(quick, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    QCoreApplication.processEvents()
    assert search.property("activeFocus") and not fired
    quick.rootObject().forceActiveFocus()
    QTest.keyClick(quick, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    QCoreApplication.processEvents()
    assert fired == [1] and not search.property("activeFocus")  # global search never taken by the page
    host.removeAction(action)


# --- B1: switches follow their backend (a checkable TpSwitch breaks its checked binding at the first click)
def tp_switch_blocks(text: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"\bTpSwitch\s*\{", text):
        depth, index = 0, match.end() - 1
        for index in range(match.end() - 1, len(text)):
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            if depth == 0:
                break
        blocks.append(text[match.end():index])
    return blocks


def bound_and_toggled(path: Path) -> int:
    count = 0
    for block in tp_switch_blocks(path.read_text(encoding="utf-8")):
        own = re.sub(r"\{[^{}]*\}", "", block)  # nested objects left out
        if re.search(r"^\s*checked:\s*(?!true\b|false\b)\S", own, re.M) and re.search(r"^\s*onToggled:", own, re.M):
            count += 1
    return count


def test_bound_switches_never_checkable():
    assert sum(bound_and_toggled(path) for path in LOT_FILES) == 0
    every = sum(bound_and_toggled(path) for path in QML_FOLDER.rglob("*.qml"))
    assert every <= SWITCHES_BOUND_AND_TOGGLED, every  # other pages: lower when fixed


SWITCHES_BOUND_AND_TOGGLED = 0


def test_stream_switches_follow_backend(page_backend):  # noqa: F811
    from neopedal.ui.stream_overlay_view import StreamOverlaysView

    view = StreamOverlaysView(None)
    view.resize(1200, 800)
    view.show()
    process_events(0.2)
    try:
        backend = view.backend
        enabled = child(view.view, "streamEnabledSwitch")
        assert enabled.property("checked") is True and enabled.property("checkable") is False
        click(view.view, enabled)
        assert backend.enabled is False and enabled.property("checked") is False
        backend.setEnabled(True)  # banner "Turn On Server": switch follows (binding kept after the click)
        process_events(0.05)
        assert enabled.property("checked") is True
        lan = child(view.view, "streamLanSwitch")
        press(view.view, lan)
        assert backend.lanAccess is True and lan.property("checked") is True
        backend.setLanAccess(False)
        QCoreApplication.processEvents()
        assert lan.property("checked") is False
        spectating = child(view.view, "streamSpectatingSwitch")
        before = backend.spectating
        press(view.view, spectating)
        assert backend.spectating is (not before) and spectating.property("checked") is (not before)
        backend.setSpectating(before)
        QCoreApplication.processEvents()
        assert spectating.property("checked") is before
    finally:
        view.close()
        view.deleteLater()
        flush()


def test_stream_overlays_search_and_ctrl_f(page_backend):  # noqa: F811
    from neopedal.ui.stream_overlay_view import StreamOverlaysView

    view = StreamOverlaysView(None)
    view.resize(1200, 800)
    view.show()
    process_events(0.2)
    try:
        find_key_stays_in_page(view.view, view, "streamOverlaySearch")
        assert view.backend.overlayLabels and not child(view.view, "streamNoMatch").property("visible")
        root = view.view.rootObject()
        search = child(view.view, "streamOverlaySearch")
        search.setProperty("text", "zzz no overlay")
        QCoreApplication.processEvents()
        assert root.property("searchWords").toVariant() == ["zzz", "no", "overlay"]
        assert child(view.view, "streamNoMatch").property("visible")
        label = view.backend.overlayLabels[0]
        search.setProperty("text", label.upper())
        QCoreApplication.processEvents()
        assert not child(view.view, "streamNoMatch").property("visible")
    finally:
        view.close()
        view.deleteLater()
        flush()


# --- Overlays page
class MergeWidget:
    """Running overlay moved like the real one (merged arrow presses)"""

    def __init__(self, rect: QRect):
        self.rect = QRect(rect)
        self.moves: list[tuple[QPoint, str, bool]] = []

    def geometry(self) -> QRect:
        return QRect(self.rect)

    def move_overlay(self, pos: QPoint, action: str, merge: bool = False):
        self.moves.append((QPoint(pos), action, merge))
        self.rect.moveTopLeft(pos)


@pytest.fixture
def control(ui_env, monkeypatch):
    for name in NAMES:
        cfg.user.setting[name]["enable"] = name in ("brake_temperature", "speedometer")
    monkeypatch.setattr(overlay_backend, "render_preview", lambda name: solid("#336699"))
    monkeypatch.setattr(overlay_backend, "make_live_preview", lambda name: None)
    monkeypatch.setattr(overlay_backend, "screen_rects", lambda: [("Main", QRect(0, 0, 1920, 1080), True)])
    monkeypatch.setitem(cfg.overlay, "fixed_position", False)
    fake = FakeControl(NAMES)
    fake.widgets = {name: MergeWidget(QRect(10, 10, 100, 50)) for name in NAMES}
    fake.widgets["speedometer"].rect = QRect(100, 100, 200, 100)
    fake.widgets["brake_temperature"].rect = QRect(600, 600, 100, 100)
    return fake


@pytest.fixture
def backend(control):
    page = OverlayBackend(None, control, lambda name: None, lambda text: True)
    page.set_active(True)
    yield page
    page.close()
    page.deleteLater()
    flush()


def test_screen_view_respects_overlay_lock(backend, control, monkeypatch):
    speed = control.widgets["speedometer"]
    monkeypatch.setitem(cfg.overlay, "fixed_position", True)
    told = []
    backend.lockChanged.connect(lambda: told.append(1))
    backend.setViewMode(VIEW_SCREEN)
    assert backend.positionsLocked and told == [1]
    backend.moveOverlay("speedometer", 500, 500)
    backend.nudgeOverlay("speedometer", 1, 0)
    assert speed.moves == []  # locked: never moved (as in game)
    unlocked = []

    def lock():
        unlocked.append(1)
        cfg.overlay["fixed_position"] = not cfg.overlay["fixed_position"]

    backend.ctx = SimpleNamespace(octrl=SimpleNamespace(toggle=SimpleNamespace(lock=lock)))
    backend.unlockPositions()
    assert unlocked == [1] and not backend.positionsLocked and told == [1, 1]
    backend.unlockPositions()  # already unlocked: nothing
    assert unlocked == [1]
    moved = []
    backend.overlayMoved.connect(moved.append)
    backend.nudgeOverlay("speedometer", 10, 0)
    backend.nudgeOverlay("speedometer", 0, -1)
    assert [(move[0], move[2]) for move in speed.moves] == [(QPoint(110, 100), True), (QPoint(110, 99), True)]
    assert moved == ["Speedometer", "Speedometer"]  # each press saved, undoable (merged steps)
    backend.moveOverlay("speedometer", 1900, 0)  # dragged: kept on screen, one undo step
    assert speed.moves[-1] == (QPoint(1720, 0), "Move", False)
    backend.nudgeOverlay("fuel", 1, 1)  # not running: nothing
    assert len(moved) == 3


def test_snap_while_dragging(backend, control):
    place = backend.snapOverlay("speedometer", 597, 405, 8, True)  # right edge 797, other at 600: left edge snaps
    assert (place["x"], place["y"]) == (600, 405)
    assert 600 in place["linesX"]
    free = backend.snapOverlay("speedometer", 597, 405, 8, False)  # Alt: free
    assert (free["x"], free["y"]) == (597, 405)
    edge = backend.snapOverlay("speedometer", 3, 1500, 8, True)  # kept on screen, snapped to its left edge
    assert (edge["x"], edge["y"]) == (0, 980)
    assert backend.snapOverlay("fuel", 5, 5, 8, True) == {"x": 5, "y": 5, "linesX": [], "linesY": []}


def test_locked_preset_unlocked_after_question(backend, control, monkeypatch):
    filename = cfg.filename.setting
    monkeypatch.setitem(cfg.user.filelock, filename, {"version": "1"})
    asked = []
    backend._confirm = lambda text: asked.append(text) or False
    backend.unlockPreset()
    assert filename in cfg.user.filelock and asked and filename in asked[0]
    backend._confirm = lambda text: True
    backend.unlockPreset()
    assert filename not in cfg.user.filelock
    from neopedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("Overlay moved, not saved (locked preset): Carburant") == (
            "Overlay déplacé, non enregistré (preset verrouillé) : Carburant")
    finally:
        i18n.set_language("English")


def test_background_captured_loaded_and_removed(control, tmp_path, monkeypatch):
    picture = tmp_path / "shot.png"
    QImage(1920, 1080, QImage.Format.Format_RGB32).save(str(picture))
    captured = []
    page = OverlayBackend(None, control, lambda name: None, lambda text: True,
                          capture_screen=lambda name: captured.append(name) or solid("#112233", 64, 36),
                          pick_screenshot=lambda: str(picture))
    try:
        monkeypatch.setattr(overlay_backend, "screen_scales", lambda: [(QRect(0, 0, 1920, 1080), 1.0)])
        told = []
        page.backgroundChanged.connect(lambda: told.append(1))
        page.captureBackground("Main")
        assert captured == ["Main"] and page.background["url"].startswith("image://")
        assert (page.background["x"], page.background["w"]) == (0, 1920) and told == [1]
        page.captureBackground("Unplugged")  # unknown screen: nothing taken
        assert captured == ["Main"]
        page.clearBackground()
        assert page.background == {} and told == [1, 1]
        page.loadBackground()  # screenshot read & scaled in a job, placed on the screen of its size
        wait_jobs(page)
        assert page.background["w"] == 1920 and page.background["h"] == 1080
        notices = []
        page.notice.connect(notices.append)
        page._pick_screenshot = lambda: str(tmp_path / "missing.png")
        page.loadBackground()
        wait_jobs(page)
        assert notices == ["Unable to load image."]
    finally:
        page.close()
        page.deleteLater()
        flush()


def test_batch_switch_counts_and_undo(backend, control):
    assert (backend.shownCount, backend.shownActiveCount) == (5, 2)
    told = []
    backend.bulkToggled.connect(told.append)
    backend.setSearch("brake")
    backend.disableShown()
    assert told == ["1 overlay disabled"] and not cfg.user.setting["brake_temperature"]["enable"]
    backend.undoBulk()
    assert cfg.user.setting["brake_temperature"]["enable"]
    from neopedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("3 overlays enabled") == "3 overlays activés"
        assert i18n.trm("1 overlay disabled") == "1 overlay désactivé"
    finally:
        i18n.set_language("English")


def test_test_on_screen_from_card_menu(backend, monkeypatch):
    from neopedal.ui import overlay_test

    class Test:
        running = False

        def start(self, scenario=""):
            self.running = True
            return 2

        def stop(self):
            self.running = False

    test = Test()
    monkeypatch.setattr(overlay_test, "overlay_test", lambda: test)
    notices = []
    backend.notice.connect(notices.append)
    backend.testOnScreen()
    assert test.running and "2 overlay(s) on screen" in notices[0]
    backend.testOnScreen()  # again: stopped
    assert not test.running and len(notices) == 1


@pytest.fixture
def overlays_page(control, monkeypatch):
    from neopedal.ui.overlay_view import OverlayView

    opened = []
    monkeypatch.setattr(OverlayView, "open_config", lambda self, name: opened.append(name))
    host = QWidget()
    layout = QVBoxLayout(host)
    page = OverlayView(host, control)
    layout.addWidget(page)
    host.resize(1100, 760)
    host.show()
    settle()
    page.opened = opened  # type: ignore[attr-defined]
    yield page
    host.close()
    page.backend.release()
    host.deleteLater()
    flush()


def test_overlays_page_find_and_favorite_keys(overlays_page):
    quick = overlays_page.view
    assert not quick.errors(), [error.toString() for error in quick.errors()]
    find_key_stays_in_page(quick, overlays_page.window(), "overlaySearch")
    assert "Ctrl+F" in child(quick, "overlaySearch").property("placeholderText")
    grid = child(quick, "overlayGrid")
    grid.forceActiveFocus()
    grid.setProperty("currentIndex", 0)
    QCoreApplication.processEvents()
    name = grid.property("currentItem").property("name")
    before = overlays_page.backend.source.rows[overlays_page.backend.source.index_of[name]].favorite
    QTest.keyClick(quick, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    QCoreApplication.processEvents()
    assert overlays_page.backend.source.rows[overlays_page.backend.source.index_of[name]].favorite is (not before)


def test_overlays_page_footer_counts(overlays_page):
    quick = overlays_page.view
    backend = overlays_page.backend
    assert child(quick, "enableShownButton").property("text") == "Enable (3)"
    assert child(quick, "disableShownButton").property("text") == "Disable (2)"
    assert "overlays shown" not in child(quick, "footerText").property("text")  # counts in the header & chips
    backend.setSearch("brake")
    settle(5)
    assert "2 of 5 overlays shown" in child(quick, "footerText").property("text")
    assert child(quick, "enableShownButton").property("text") == "Enable (1)"


def test_screen_view_frames_keyboard_and_locks(overlays_page, control, monkeypatch):
    quick = overlays_page.view
    backend = overlays_page.backend
    backend.setViewMode(VIEW_SCREEN)
    settle()
    assert not quick.errors(), [error.toString() for error in quick.errors()]
    frames = {frame.property("overlayName"): frame for frame in children(quick, "screenFrame")}
    assert set(frames) == {"speedometer", "brake_temperature"}
    frame = frames["speedometer"]
    assert frame.property("activeFocusOnTab")
    overlays_page.window().activateWindow()
    quick.setFocus()
    frame.forceActiveFocus()
    QTest.keyClick(quick, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    settle(3)
    speed = control.widgets["speedometer"]
    assert speed.moves[-1][0] == QPoint(110, 100) and speed.moves[-1][2]  # 10 px, merged undo step
    focused = [item for item in children(quick, "screenFrame") if item.property("activeFocus")]
    assert [item.property("overlayName") for item in focused] == ["speedometer"]  # focus kept on the new frame
    QTest.keyClick(quick, Qt.Key.Key_Return)
    QCoreApplication.processEvents()
    assert overlays_page.opened == ["speedometer"]
    monkeypatch.setitem(cfg.overlay, "fixed_position", True)
    backend._poll_screen()
    settle(3)
    assert children(quick, "positionsLockedPill")[0].property("visible")
    assert children(quick, "unlockPositionsButton")[0].property("visible")
    count = len(speed.moves)
    QTest.keyClick(quick, Qt.Key.Key_Left)
    settle(3)
    assert len(speed.moves) == count  # locked: arrows move nothing
    assert children(quick, "snapSwitch")[0].property("enabled") is False
    assert children(quick, "backgroundButton")[0].property("visible")


def test_screen_view_one_screen_at_a_time(overlays_page, monkeypatch):
    monkeypatch.setattr(overlay_backend, "screen_rects", lambda: [
        ("Left", QRect(-1920, 0, 1920, 1080), False), ("Main", QRect(0, 0, 2560, 1440), True),
        ("Right", QRect(2560, 0, 1920, 1080), False)])
    backend = overlays_page.backend
    backend.setViewMode(VIEW_SCREEN)
    settle()
    view = children(overlays_page.view, "screenView")[0]
    assert view.property("screenName") == "Main"  # main screen first
    choice = children(overlays_page.view, "screenChoice")[0]
    assert choice.property("visible") and len(choice.property("options").toVariant()) == 4  # 3 screens & all
    assert view.property("area")["w"] == 2560
    choice.activated.emit(3)
    QCoreApplication.processEvents()
    assert view.property("allScreens") and view.property("area")["w"] == 1920 * 2 + 2560


# --- Overlay Options page
class OptionsControl:
    """Overlay control: every overlay, switched on or off as the real one"""

    def __init__(self):
        from neopedal.template.setting_widget import WIDGET_DEFAULT

        self.names = list(WIDGET_DEFAULT)
        self.switched: list[tuple[list[str], bool]] = []
        self.reloaded: list[str] = []

    def set_enabled(self, names, enable):
        changed = [name for name in names if bool(cfg.user.setting[name]["enable"]) != enable]
        self.switched.append((changed, enable))
        for name in changed:
            cfg.user.setting[name]["enable"] = enable
        return changed

    def reload(self, name):
        self.reloaded.append(name)


def test_overlay_switch_at_once_never_pending(ui_env, monkeypatch):
    from neopedal import app_signal
    from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend, build_layout
    from tests.test_overlay_options import Host

    refreshed = []
    app_signal.refresh.connect(refreshed.append)
    control = OptionsControl()
    backend = OverlayOptionsBackend(None, Host(), control)
    try:
        backend.selectOverlay("speedometer")
        monkeypatch.setitem(cfg.user.setting["speedometer"], "enable", False)
        assert "enable" not in build_layout("speedometer", cfg.user.setting["speedometer"]).keys
        backend.setBool("speedometer/enable", True)  # former row: never pending
        assert backend.pendingCount == 0
        backend.setOverlayEnabled(True)
        assert control.switched == [(["speedometer"], True)] and backend.overlayInfo["enabled"] is True
        assert backend.pendingCount == 0 and refreshed
        backend.setOverlayEnabled(True)  # same state: nothing
        assert len(control.switched) == 1
    finally:
        app_signal.refresh.disconnect(refreshed.append)
        backend.close()
        backend.deleteLater()
        flush()


@pytest.fixture
def options_page(ui_env, monkeypatch):
    from neopedal.ui.overlay_options import OverlayOptions

    page = OverlayOptions(None, OptionsControl())
    page.resize(1500, 800)
    page.show()
    settle()
    yield page
    if shiboken6.isValid(page):
        page.backend.discard()
        page.close()  # deleted once closed
    flush()


def test_options_menus_filters_and_find_key(options_page):
    quick = options_page.view
    backend = options_page.backend
    assert not quick.errors(), [error.toString() for error in quick.errors()]
    text = (QML_FOLDER / "overlays" / "OverlayOptions.qml").read_text(encoding="utf-8")
    assert "Save as Profile..." not in text and "Color Theme..." not in text  # never a list used as a menu
    find_key_stays_in_page(quick, options_page, "optionSearch")
    button = child(quick, "filtersButton")
    assert button.property("text").startswith("Filters") and "(" not in button.property("text")
    backend.setModifiedOnly(True)
    backend.setUsedOnly(True)
    QCoreApplication.processEvents()
    assert "(2)" in button.property("text")
    item = child(quick, "changedOnlyItem")
    item.triggered.emit()
    QCoreApplication.processEvents()
    assert not backend.modifiedOnly and item.property("checked") is False and "(1)" in button.property("text")
    backend.setModifiedOnly(True)  # binding put back after the click
    QCoreApplication.processEvents()
    assert item.property("checked") is True
    backend.setModifiedOnly(False)
    backend.setUsedOnly(False)
    backend.selectOverlay("black_box")  # display profiles & color themes
    QCoreApplication.processEvents()
    info = backend.overlayInfo
    assert info["themes"] and info["userProfiles"]
    assert child(quick, "themeButton").property("visible") and child(quick, "profileButton").property("visible")
    theme_menu = child(quick, "themeMenu")
    assert theme_menu.property("count") == len(info["themes"])
    profile_menu = child(quick, "profileMenu")
    assert profile_menu.property("count") == len(info["userProfiles"]) + 1  # title entry first


def test_options_header_switch_and_preview_button(options_page):
    quick = options_page.view
    backend = options_page.backend
    root = quick.rootObject()
    backend.selectOverlay("speedometer")
    QCoreApplication.processEvents()
    switch = child(quick, "overlayEnabledSwitch")
    state = bool(cfg.user.setting["speedometer"]["enable"])
    assert switch.property("checked") is state and switch.property("checkable") is False
    click(quick, switch)
    assert bool(cfg.user.setting["speedometer"]["enable"]) is (not state) and switch.property("checked") is (not state)
    assert backend.pendingCount == 0
    panel = child(quick, "previewPanel")
    assert root.property("previewShown") and panel.property("visible")
    options_page.resize(760, 700)  # under 74 em: preview hidden, Preview button at top
    settle(5)
    assert not root.property("previewShown") and not panel.property("visible")
    root.setProperty("previewOpen", True)
    QCoreApplication.processEvents()
    assert panel.property("visible") and child(quick, "closePreviewButton").property("visible")
    quick.setFocus()
    root.forceActiveFocus()
    QTest.keyClick(quick, Qt.Key.Key_Escape)  # closes the preview, not the page
    QCoreApplication.processEvents()
    assert not root.property("previewOpen") and options_page.isVisible()


# --- C5: one word for the options of an overlay
def test_options_vocabulary():
    for path in LOT_FILES:
        text = path.read_text(encoding="utf-8")
        for old in ('i18n.tr("Config")', 'i18n.tr("Options of")', 'i18n.tr("Export Settings...")'):
            assert old not in text, (path.name, old)


# --- What's New
def test_try_overlay_with_undo(notes_page, monkeypatch):  # noqa: F811
    from neopedal.module_control import wctrl

    notes = "### New\n\n#### Flag: new alerts\n\n- Penalty chip (`show_penalty`)\n"
    cfg.user.setting["flag"]["enable"] = False
    switched = []

    def set_enabled(self, names, enable):
        switched.append((list(names), enable))
        cfg.user.setting["flag"]["enable"] = enable
        return list(names)

    monkeypatch.setattr(type(wctrl), "set_enabled", set_enabled)
    backend = notes_page(notes=notes).backend
    tried = []
    backend.overlayTried.connect(lambda name, text: tried.append((name, text)))
    backend.tryOverlay("flag")
    assert tried == [("flag", "Overlay turned on: Flag")] and backend.enabledOverlays == ["flag"]
    backend.undoTry("flag")
    assert switched == [(["flag"], True), (["flag"], False)] and backend.enabledOverlays == []
    from neopedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("Try Drapeau") == "Essayer Drapeau" and i18n.trm("Options: Drapeau") == "Options : Drapeau"
        assert i18n.trm("Options: 12") == "Options : 12"
        assert i18n.trm("Overlay turned on: Drapeau") == "Overlay activé : Drapeau"
    finally:
        i18n.set_language("English")


@pytest.mark.parametrize("language", ("English", "Français"))
def test_whats_new_footer_never_squeezes_main_button(notes_page, language):  # noqa: F811
    from neopedal import i18n

    i18n.set_language(language)
    try:
        dialog = notes_page(can_install=True, prompt=True, can_skip=True)
        dialog.show()
        root = dialog.view.rootObject()
        em = dialog.view.engine().rootContext().contextProperty("theme").property("em")
        for width_em in (30, 42):
            dialog.resize(round(em * width_em), 640)
            settle(10)
            install = child(dialog.view, "installButton")
            if not install.property("visible"):
                continue
            assert install.property("width") >= install.property("implicitWidth") - 1, width_em
            right = install.mapToItem(root, QPointF(install.property("width"), 0)).x()
            assert right <= root.property("width") + 1, width_em
        assert child(dialog.view, "showAfterUpdateSwitch").property("visible")
        assert "Ctrl+F" in child(dialog.view, "notesSearch").property("placeholderText")
        find_key_stays_in_page(dialog.view, dialog, "notesSearch")
    finally:
        i18n.set_language("English")


# Layout Editor merged into the screen view: tool gone, its pure functions kept
def test_layout_editor_tool_removed():
    from neopedal.template.page_registry import PAGES

    assert "layout_editor" not in {page.name for page in PAGES}
    assert not os.path.exists(Path(__file__).resolve().parent.parent / "neopedal" / "ui" / "layout_editor.py")
    from neopedal.template.setting_global import GLOBAL_DEFAULT

    assert "layout_editor" not in GLOBAL_DEFAULT["application"]["home_quick_access"]


# --- Wave 2: shared components (view selector, badges, page toasts & dialogs, header)
def test_view_selector_and_page_toast_with_undo(overlays_page, control, monkeypatch):
    quick = overlays_page.view
    backend = overlays_page.backend
    choice = child(quick, "viewChoice")
    assert choice.property("options").toVariant()[0]["tip"] == "Cards with preview"
    choice.activated.emit(1)
    assert backend.viewMode == 1
    choice.activated.emit(2)
    settle()
    undone = []
    from neopedal.widget import _edit_mode

    monkeypatch.setattr(_edit_mode.edit_mode(), "undo", lambda: undone.append(1) or True)
    backend.nudgeOverlay("speedometer", 1, 0)
    settle(3)
    toast = children(quick, "bridgeToast")[0]
    assert toast.property("text") == "Overlay moved: Speedometer" and toast.property("actionText") == "Undo"
    assert toast.property("shown")
    from neopedal.ui.quick.dialogs import page_bridge

    page_bridge(quick).toastAction()  # Undo of the toast
    settle(3)
    assert undone == [1]


def test_error_badges_are_pills(overlays_page, control):
    control.failing.add("speedometer")
    overlays_page.backend.refresh()
    settle()
    badges = [badge for badge in children(overlays_page.view, "errorBadge") if badge.property("visible")]
    assert badges and all(badge.property("solid") and badge.property("text") == "Error" for badge in badges)


def test_overlay_reset_asked_in_the_page(ui_env):
    from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend
    from tests.test_overlay_options import Host

    class AskingHost(Host):
        def __init__(self):
            super().__init__()
            self.asked = []

        def ask(self, text, action_text, on_result):
            self.asked.append((text, action_text, on_result))

    host = AskingHost()
    backend = OverlayOptionsBackend(None, host, OptionsControl())
    try:
        backend.selectOverlay("speedometer")
        backend.setNumber("speedometer/opacity", 0.5)
        backend.resetOverlay()
        assert backend.value("speedometer", "opacity") == 0.5 and host.asked  # answered later
        text, action, on_result = host.asked[0]
        assert "Speedometer" in text and action == "Reset" and not host.questions
        on_result(True)
        assert backend.value("speedometer", "opacity") != 0.5
    finally:
        backend.close()
        backend.deleteLater()
        flush()


def test_whats_new_header_status_pill(notes_page):  # noqa: F811
    dialog = notes_page(can_install=True, prompt=True)
    dialog.show()
    settle(5)
    texts = set()
    stack = [dialog.view.rootObject()]
    while stack:
        item = stack.pop()
        if isinstance(item.property("text"), str):
            texts.add(item.property("text"))
        stack.extend(item.childItems())
    assert dialog.backend.chip in texts and dialog.backend.title in texts
