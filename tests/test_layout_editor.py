"""Placing overlays: snapping & screenshot screen of the Overlays page screen view (formerly the Layout Editor
tool), layout profiles per screen setup"""

from PySide6.QtCore import QPoint, QRect

from neopedal.ui.quick.overlay_screen import snap_position

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


def test_snap_per_screen_center():
    """Multi-monitor: snap to each screen center, not the virtual desktop center"""
    screens = [QRect(0, 0, 1920, 1080), QRect(1920, 0, 2560, 1440)]
    target = QRect(3146, 700, 100, 40)  # center 3196, right screen center 3200
    assert snap_position(target, [], screens) == QPoint(3150, 700)
    # Center 2236 near virtual desktop center (2240): no snap
    assert snap_position(QRect(2186, 700, 100, 40), [], screens) == QPoint(2186, 700)


def test_screenshot_mapped_to_matching_screen():
    from PySide6.QtCore import QSize

    from neopedal.ui.quick.overlay_screen import screen_for_image

    left, right = QRect(0, 0, 1920, 1080), QRect(1920, 0, 2560, 1440)
    screens = [(left, 1.0), (right, 1.0)]
    assert screen_for_image(QSize(2560, 1440), screens, left) == right
    assert screen_for_image(QSize(1920, 1080), screens, right) == left
    # HiDPI: screenshot in device pixels
    assert screen_for_image(QSize(3840, 2160), [(left, 2.0), (right, 1.0)], right) == left
    # Unknown size: fallback (primary/current screen), never the whole virtual desktop
    assert screen_for_image(QSize(4480, 1440), screens, left) == left


def test_layout_profiles_per_screen_setup(tmp_path):
    from neopedal.userfile.layout_profile import load_profiles, profile_filename, sync_layout

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
