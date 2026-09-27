"""Layout guide & snapping tests"""

from PySide6.QtCore import QRect

from tinypedal.widget._layout_guide import alignment_lines

SCREEN = QRect(0, 0, 1920, 1080)


def test_edge_alignment():
    other = QRect(100, 100, 200, 50)
    target = QRect(100, 300, 120, 40)  # same left edge
    lines_x, lines_y = alignment_lines(target, [other], SCREEN)
    assert 100 in lines_x
    assert not lines_y


def test_center_alignment_with_screen():
    target = QRect(960 - 50, 10, 100, 20)  # centered horizontally on screen
    lines_x, _ = alignment_lines(target, [], SCREEN)
    assert lines_x == {960}


def test_no_alignment():
    lines_x, lines_y = alignment_lines(QRect(13, 17, 50, 30), [QRect(500, 500, 40, 40)], SCREEN)
    assert not lines_x and not lines_y
