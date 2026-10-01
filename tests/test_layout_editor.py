"""Layout editor: snapping, dragging and applying widget positions"""

from PySide6.QtCore import QPoint, QRect

from tinypedal.ui import layout_editor
from tinypedal.ui.layout_editor import LayoutEditor, snap_position

SCREEN = QRect(0, 0, 1920, 1080)


def test_snap_to_other_edge():
    other = QRect(100, 100, 200, 50)
    target = QRect(304, 400, 100, 40)  # left edge 4px from other right edge (300)
    assert snap_position(target, [other], SCREEN) == QPoint(300, 400)


def test_snap_to_screen_center_and_edge():
    target = QRect(906, 3, 100, 40)  # center 956, screen center 960; top 3 px from edge
    assert snap_position(target, [], SCREEN) == QPoint(910, 0)


def test_no_snap_when_far():
    target = QRect(500, 500, 100, 40)
    assert snap_position(target, [QRect(0, 200, 50, 50)], SCREEN) == QPoint(500, 500)


class FakeWidget:
    def __init__(self, rect):
        self.rect = QRect(rect)

    def geometry(self):
        return self.rect

    def move(self, x, y):
        self.rect.moveTo(x, y)


def test_apply_moves_widgets_and_saves(ui_env, monkeypatch):
    from tinypedal.setting import cfg

    widgets = {"speedometer": FakeWidget(QRect(10, 10, 80, 30)), "gear": FakeWidget(QRect(400, 400, 60, 60))}
    monkeypatch.setattr(layout_editor.wctrl, "_active_modules", widgets)
    monkeypatch.setattr(layout_editor.wctrl, "active_modules", widgets)
    for name, widget in widgets.items():
        cfg.user.setting[name]["position_x"] = widget.rect.x()
        cfg.user.setting[name]["position_y"] = widget.rect.y()
    dialog = LayoutEditor(None)
    try:
        canvas = dialog.canvas
        assert set(canvas.boxes) == set(widgets)
        canvas.select("gear")
        canvas.move_selected(QPoint(200, 300), snap=False)
        assert dialog.apply() == 1
        assert widgets["gear"].rect.topLeft() == QPoint(200, 300)
        assert (cfg.user.setting["gear"]["position_x"], cfg.user.setting["gear"]["position_y"]) == (200, 300)
        assert ui_env  # preset saved
        assert dialog.apply() == 0
    finally:
        dialog.close()


def test_layout_profiles_per_screen_setup(tmp_path):
    from tinypedal.userfile.layout_profile import load_profiles, profile_filename, sync_layout

    filename = profile_filename(str(tmp_path), "race.json")
    assert filename.endswith("race.layouts")
    names = ("speedometer", "gear")
    setting = {"speedometer": {"position_x": 10, "position_y": 20}, "gear": {"position_x": 1, "position_y": 2}}
    # First time on single screen: nothing restored, positions stored
    assert not sync_layout(setting, names, filename, "1920x1080+0+0")
    # Move widgets for triple screen
    setting["speedometer"]["position_x"] = 2500
    assert not sync_layout(setting, names, filename, "5760x1080+0+0")
    # Back to single screen: single screen positions restored
    assert sync_layout(setting, names, filename, "1920x1080+0+0")
    assert setting["speedometer"]["position_x"] == 10
    assert set(load_profiles(filename)) == {"1920x1080+0+0", "5760x1080+0+0"}
