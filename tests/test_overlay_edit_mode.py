"""Overlay management on game screen: edit mode, snapping, keyboard, undo, context menu, lock"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QMouseEvent

from tinypedal import overlay_signal, realtime_state
from tinypedal.widget import _base, _edit_mode
from tinypedal.widget._common import MousePosition
from tinypedal.widget._edit_mode import MERGE_SECONDS, EditHistory, EditStep
from tinypedal.widget._snapping import (
    centered,
    constrain_axis,
    fit_on_screens,
    move_to_screen,
    snap_position,
    step_on_grid,
)

SCREEN = QRect(0, 0, 1920, 1080)
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
NONE = Qt.KeyboardModifier.NoModifier


# Placement geometry
def test_snap_to_edges_centers_and_neighbours():
    other = QRect(100, 100, 200, 50)
    # Left edges line up
    assert snap_position(QRect(104, 400, 80, 40), [other], [SCREEN], 10)[0] == QPoint(100, 400)
    # Placed right after other, with gap
    pos, snapped_x, snapped_y = snap_position(QRect(306, 400, 80, 40), [other], [SCREEN], 10, gap=4)
    assert pos == QPoint(304, 400) and snapped_x and not snapped_y
    # Centers line up (other center 200 -> left 160)
    assert snap_position(QRect(163, 400, 80, 40), [other], [SCREEN], 10)[0] == QPoint(160, 400)
    # Screen right edge & bottom edge
    assert snap_position(QRect(1835, 1036, 80, 40), [], [SCREEN], 10)[0] == QPoint(1840, 1040)
    # Screen center
    assert snap_position(QRect(915, 500, 80, 40), [], [SCREEN], 10)[0] == QPoint(920, 500)
    # Closest reference wins, too far: kept
    assert snap_position(QRect(500, 600, 80, 40), [other], [SCREEN], 10) == (QPoint(500, 600), False, False)
    assert snap_position(QRect(104, 400, 80, 40), [other], [SCREEN], 0)[0] == QPoint(104, 400)


def test_grid_steps_axis_lock_and_center():
    assert step_on_grid(13, 1, 8) == 16 and step_on_grid(13, -1, 8) == 8
    assert step_on_grid(16, 1, 8) == 24 and step_on_grid(16, -1, 8) == 8
    assert step_on_grid(16, 1, 8, 10) == 96
    assert step_on_grid(13, -1, 1, 10) == 3
    assert constrain_axis(QPoint(10, 10), QPoint(50, 20)) == QPoint(50, 10)
    assert constrain_axis(QPoint(10, 10), QPoint(15, -40)) == QPoint(10, -40)
    # Second screen right of first one: centered on it, not on first screen
    second = QRect(1920, 0, 2560, 1440)
    assert centered(QRect(0, 0, 200, 100), second, True, QPoint(2000, 50)) == QPoint(1920 + 1180, 50)
    assert centered(QRect(0, 0, 200, 100), second, False, QPoint(2000, 50)) == QPoint(2000, 670)


def test_overlay_brought_back_on_screen():
    screens = [SCREEN, QRect(1920, 0, 1920, 1080)]
    assert fit_on_screens(QRect(100, 100, 200, 50), screens) is None
    assert fit_on_screens(QRect(1900, 100, 200, 50), screens) is None  # on two screens
    assert fit_on_screens(QRect(-180, 100, 200, 50), screens) is None  # 20 x 50 pixels shown: can be grabbed
    assert fit_on_screens(QRect(-195, 100, 200, 50), screens) == QPoint(0, 100)
    assert fit_on_screens(QRect(5000, 2000, 200, 50), screens) == QPoint(3640, 1030)  # monitor gone
    assert fit_on_screens(QRect(5000, 2000, 200, 50), []) is None


def test_move_to_screen_keeps_relative_place():
    source, target = QRect(0, 0, 1920, 1080), QRect(1920, -200, 2560, 1440)
    right = QRect(1920 - 300, 0, 300, 100)  # stuck to right edge
    assert move_to_screen(right, source, target) == QPoint(1920 + 2560 - 300, -200)
    middle = QRect(810, 490, 300, 100)  # centered
    assert move_to_screen(middle, source, target) == QPoint(1920 + 1130, -200 + 670)


# Edit history
def step(name="fuel", text="Move", before=0, after=1, preset="a.json", time=0.0):
    return EditStep(name, text, {"position_x": before}, {"position_x": after}, preset, time)


def test_history_undo_redo_and_merge():
    history = EditHistory(size=3)
    history.push(step(before=0, after=1, time=0))
    history.push(step(before=1, after=2, time=MERGE_SECONDS / 2), merge=True)  # arrow key held
    assert len(history) == 1 and history.peek_undo().before == {"position_x": 0}
    history.push(step(before=2, after=3, time=10), merge=True)  # later: new step
    history.push(step(name="gear", before=5, after=6, time=10.1), merge=True)  # other overlay
    assert len(history) == 3
    assert history.undo().name == "gear" and history.peek_redo().name == "gear"
    history.push(step(before=3, after=4, time=11))  # redo stack cleared by new change
    assert history.peek_redo() is None
    history.push(step(before=4, after=5))
    assert len(history) == 3  # oldest dropped
    history.push(step(before=5, after=5))  # no change: not kept
    assert len(history) == 3
    history.keep_preset("a.json")
    assert len(history) == 3
    history.keep_preset("b.json")  # another preset loaded
    assert len(history) == 0 and history.undo() is None


# Mouse drag
def test_drag_snaps_magnetic_or_with_ctrl(ui_env):
    from PySide6.QtWidgets import QWidget

    other = QWidget()
    other.widget_name = "other"
    other.setGeometry(100, 100, 200, 50)
    other.show()
    target = QWidget()
    target.resize(80, 40)
    target.move(400, 400)
    target.show()
    try:
        mouse = MousePosition()
        grab = QPoint(10, 10)
        mouse.config(grab, False, 8, 0, 10, magnetic=True, start=target.pos())
        assert mouse.position(target, QPoint(114, 410), NONE) == QPoint(100, 400)  # snapped
        assert mouse.snapped == (True, False)
        assert mouse.position(target, QPoint(114, 410), CTRL) == QPoint(104, 400)  # Ctrl: free move
        mouse.config(grab, False, 8, 0, 10, magnetic=False, start=target.pos())
        assert mouse.position(target, QPoint(114, 410), NONE) == QPoint(104, 400)
        assert mouse.position(target, QPoint(114, 410), CTRL) == QPoint(100, 400)  # Ctrl snaps (former way)
        mouse.config(grab, True, 8, 0, 10, magnetic=True, start=target.pos())
        assert mouse.position(target, QPoint(114, 433), NONE) == QPoint(100, 424)  # y not snapped: grid
        assert mouse.position(target, QPoint(503, 459), SHIFT) == QPoint(496, 400)  # one axis, grid
    finally:
        other.deleteLater()
        target.deleteLater()


# Overlays in edit mode
@pytest.fixture
def editing(ui_env, monkeypatch):
    """Fresh edit mode state, overlays started here listed as active"""
    from tinypedal.setting import cfg

    overlays = {}
    monkeypatch.setattr(_edit_mode, "_edit_mode", None)
    monkeypatch.setattr(_edit_mode, "active_overlays", lambda: dict(overlays))
    monkeypatch.setattr(_base, "reload_widget", lambda name: None)
    saved = realtime_state.editing, realtime_state.hidden, realtime_state.active
    cfg.overlay["fixed_position"] = False
    cfg.overlay["enable_grid_move"] = False

    def start(name="speedometer", pos=(300, 300)):
        from importlib import import_module

        from tinypedal.widget._modern import create_widget

        cfg.user.setting[name]["position_x"], cfg.user.setting[name]["position_y"] = pos
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        widget.start()
        overlays[name] = widget
        return widget

    yield start, overlays, ui_env
    for widget in overlays.values():
        widget.stop()
    controller = _edit_mode._edit_mode
    if controller is not None:
        if controller.toolbar is not None:
            controller.toolbar.close()
            controller.toolbar.deleteLater()
        controller.deleteLater()
    realtime_state.editing, realtime_state.hidden, realtime_state.active = saved
    QCoreApplication.processEvents()


def key(widget, code, modifiers=NONE):
    QCoreApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, code, modifiers))


def test_unlock_enters_edit_mode_and_lock_leaves_it(editing):
    from tinypedal.overlay_control import OverlayToggle
    from tinypedal.setting import cfg

    start, _overlays, _saved = editing
    cfg.overlay["fixed_position"] = True
    toggle = OverlayToggle()
    toggle.lock()  # unlocked, but no overlay to edit
    assert not realtime_state.editing
    toggle.lock()
    widget = start()
    assert widget._edit_frame.outline is None  # locked overlay: edit parts never created
    toggle.lock()  # unlocked by user: edit mode
    controller = _edit_mode.edit_mode()
    assert realtime_state.editing and controller.toolbar.isVisible()
    frame = widget._edit_frame
    assert frame.outline.isVisibleTo(widget) and not frame.handle.isVisibleTo(widget)  # outline without hover
    realtime_state.hidden = True  # auto hide: still shown while editing
    assert not widget.should_hide()
    toggle.lock()
    assert not realtime_state.editing and not controller.toolbar.isVisible()
    assert widget.should_hide()
    assert not frame.outline.isVisibleTo(widget)


def test_lock_toggle_keeps_window_shown(editing):
    start, _overlays, _saved = editing
    widget = start()
    assert widget.isVisible()
    changes = []
    widget.windowHandle().visibleChanged.connect(changes.append)
    overlay_signal.locked.emit(True)
    assert widget.isVisible() and not changes  # flag changed in place, no hide & show
    assert widget.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert widget.windowHandle().flags() & Qt.WindowType.WindowTransparentForInput
    assert widget._edit_frame.widget is widget and not widget._edit_frame.enabled
    overlay_signal.locked.emit(False)
    assert widget.isVisible() and not changes
    assert not widget.windowFlags() & Qt.WindowType.WindowTransparentForInput


def test_arrow_keys_move_undo_redo(editing, monkeypatch):
    from tinypedal.setting import cfg

    start, _overlays, _saved = editing
    widget = start()
    stored = []
    monkeypatch.setattr(_edit_mode.EditMode, "store_layout", staticmethod(lambda: stored.append(1)))
    key(widget, Qt.Key.Key_Right)
    key(widget, Qt.Key.Key_Down, SHIFT)
    assert widget.pos() == QPoint(301, 310)
    assert (cfg.user.setting["speedometer"]["position_x"], cfg.user.setting["speedometer"]["position_y"]) == (301, 310)
    assert len(_edit_mode.edit_mode().history) == 1  # presses in a row: one step
    cfg.overlay["enable_grid_move"] = True
    key(widget, Qt.Key.Key_Left)  # grid: to grid line
    assert widget.x() == 296
    key(widget, Qt.Key.Key_Z, CTRL)
    assert widget.pos() == QPoint(300, 300)
    assert cfg.user.setting["speedometer"]["position_x"] == 300
    key(widget, Qt.Key.Key_Y, CTRL)
    assert widget.pos() == QPoint(296, 310)
    key(widget, Qt.Key.Key_Z, CTRL | SHIFT)  # undo again, Ctrl+Shift+Z redo
    key(widget, Qt.Key.Key_Z, CTRL | SHIFT)
    assert widget.pos() == QPoint(296, 310)
    _edit_mode.edit_mode()._flush_layout()
    assert stored  # layout profile written once moves stop


def test_drag_recorded_and_selection(editing):
    start, _overlays, _saved = editing
    widget = start()
    other = start("deltabest", (700, 300))
    controller = _edit_mode.edit_mode()

    def mouse(kind, local, global_pos, button=Qt.MouseButton.LeftButton, modifiers=NONE):
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
        QCoreApplication.sendEvent(widget, QMouseEvent(
            kind, QPointF(local), QPointF(global_pos), button, buttons, modifiers))

    mouse(QEvent.Type.MouseButtonPress, QPoint(5, 5), QPoint(305, 305))
    assert controller.selected == "speedometer"
    assert widget._edit_frame.selected and widget._edit_frame.handle.isVisibleTo(widget)
    mouse(QEvent.Type.MouseMove, QPoint(5, 5), QPoint(405, 503), modifiers=CTRL)  # free move, no snapping
    mouse(QEvent.Type.MouseButtonRelease, QPoint(5, 5), QPoint(405, 503))
    assert widget.pos() == QPoint(400, 498)
    assert controller.history.peek_undo().after == {"position_x": 400, "position_y": 498}
    controller.undo()
    assert widget.pos() == QPoint(300, 300)
    # Clicking another overlay moves selection
    QCoreApplication.sendEvent(other, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(705, 305), Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton, NONE))
    assert controller.selected == "deltabest" and not widget._edit_frame.selected
    key(other, Qt.Key.Key_Escape)
    assert controller.selected == ""


def menu_choice(monkeypatch, *texts):
    """Context menu answers action at path of texts (submenus first)"""
    def fake_exec(menu, *args):
        current = menu
        for text in texts:
            action = next(action for action in current.actions() if action.text() == text)
            if action.menu() is None:
                return action
            current = action.menu()
        return None

    monkeypatch.setattr(_base, "exec_menu", lambda menu, pos: fake_exec(menu))


def open_menu(widget):
    widget.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), widget.pos()))


def test_context_menu_actions_undoable(editing, monkeypatch):
    start, _overlays, _saved = editing
    widget = start()
    controller = _edit_mode.edit_mode()
    screen = widget.screen().geometry()
    menu_choice(monkeypatch, "Center Horizontally")
    open_menu(widget)
    assert widget.x() == screen.x() + (screen.width() - widget.width()) // 2
    menu_choice(monkeypatch, "Opacity", "50%")
    open_menu(widget)
    assert widget.wcfg["opacity"] == 0.5 and abs(widget.windowOpacity() - 0.5) < 0.01
    menu_choice(monkeypatch, "Visibility", "Race")
    open_menu(widget)
    assert widget.wcfg["visibility_context"] == "Race"
    assert [step.text for step in controller.history._undo] == ["Centering", "Opacity", "Visibility"]
    menu_choice(monkeypatch, "Undo: Visibility \u2013 Speedometer")
    open_menu(widget)
    assert widget.wcfg["visibility_context"] == "Always"
    controller.undo()
    controller.undo()
    assert widget.wcfg["opacity"] != 0.5 and widget.pos() == QPoint(300, 300)
    # Edit mode from menu, lock from menu
    menu_choice(monkeypatch, "Edit Mode")
    open_menu(widget)
    assert realtime_state.editing
    from tinypedal.setting import cfg

    menu_choice(monkeypatch, "Lock Overlay")
    open_menu(widget)
    assert cfg.overlay["fixed_position"] and not realtime_state.editing


def test_resize_and_disable_undoable(editing, monkeypatch):
    from tinypedal.setting import cfg

    start, _overlays, _saved = editing
    widget = start()
    controller = _edit_mode.edit_mode()
    font_size = cfg.user.setting["speedometer"]["font_size"]
    widget._edit_frame.handle.on_resized(2.0)
    assert cfg.user.setting["speedometer"]["font_size"] == font_size * 2
    controller.undo()
    assert cfg.user.setting["speedometer"]["font_size"] == font_size
    toggled = []
    monkeypatch.setattr(_base, "disable_widget", toggled.append)
    from tinypedal.module_control import ModuleControl

    monkeypatch.setattr(ModuleControl, "toggle", lambda self, name: toggled.append(("toggle", name)))
    key(widget, Qt.Key.Key_Delete)
    assert toggled == ["speedometer"]
    cfg.user.setting["speedometer"]["enable"] = False
    controller.undo()  # turned on again
    assert toggled[-1] == ("toggle", "speedometer")


def test_toolbar_actions(editing, monkeypatch):
    from PySide6.QtGui import QPixmap

    from tinypedal.setting import cfg

    start, _overlays, _saved = editing
    widget = start()
    controller = _edit_mode.edit_mode()
    assert controller.enter()
    toolbar = controller.toolbar
    assert toolbar.detail == "1 overlay"
    controller.select("speedometer")
    assert toolbar.detail.startswith(f"X {widget.x()}")
    snap = cfg.application["enable_magnetic_snap"]
    toolbar.trigger("snap")
    assert cfg.application["enable_magnetic_snap"] is not snap and "config" in editing[2]
    grid = cfg.overlay["enable_grid_move"]
    toolbar.trigger("grid")
    assert cfg.overlay["enable_grid_move"] is not grid
    undo = next(item for item in toolbar.items if item.key == "undo")
    assert not undo.enabled
    key(widget, Qt.Key.Key_Right)
    assert undo.enabled and "Move" in undo.tip
    toolbar.trigger("undo")
    toolbar.trigger("redo")
    assert widget.x() == 304  # grid move turned on above: next grid line
    for icon_family in (toolbar.icon_family, ""):  # icons, or labels without icon font
        toolbar.icon_family = icon_family
        toolbar.relayout()
        pixmap = QPixmap(toolbar.size())
        toolbar.render(pixmap)
    toolbar.trigger("close")  # toolbar hidden, overlay stays unlocked
    assert not realtime_state.editing and not cfg.overlay["fixed_position"]
    controller.enter()
    toolbar.trigger("done")
    assert cfg.overlay["fixed_position"] and not toolbar.isVisible()


def test_layout_guide_redraws_changed_parts_only(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.widget import _layout_guide

    target = QWidget()
    target.setGeometry(100, 100, 80, 40)
    guide = _layout_guide.LayoutGuide()
    guide.setGeometry(QRect(0, 0, 800, 600))
    guide._others = [QRect(100, 300, 50, 50)]
    guide.track(target)
    first = guide.changing_parts()
    assert first.contains(QPoint(120, 120)) and first.contains(QPoint(100, 590))  # outline, aligned line x=100
    assert not first.contains(QPoint(600, 400))
    assert guide._label == "X 100   Y 100" and guide.label_geometry().top() > 140
    target.move(100, 560)  # near bottom: label above
    guide.track(target)
    assert guide.label_geometry().bottom() < 560
    guide.deleteLater()
    target.deleteLater()
    _layout_guide.end_layout_guide()  # nothing shown: nothing to do
    assert _layout_guide._guide is None


def test_overlays_never_hide_base_methods():
    """An overlay attribute named like a base method (self.center = point) breaks menu & keys"""
    import pathlib
    import re

    names = ("apply_placement", "nudge_position", "move_overlay", "center_on_screen", "move_to_screen",
             "change_options", "disable_overlay", "menu_actions", "centering_rect", "should_hide",
             "screen_opacity")
    assignment = re.compile(rf"self\.({'|'.join(names)})\s*=[^=]")
    folders = [pathlib.Path("tinypedal/widget"), pathlib.Path("plugins")]
    found = [
        f"{path}: {match.group(0)}"
        for folder in folders if folder.is_dir()
        for path in folder.rglob("*.py")
        for match in assignment.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not found
