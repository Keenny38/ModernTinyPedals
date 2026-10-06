"""Ordered picker: shown & available entries (navigation bar, quick access, display order)"""

import pytest
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QBoxLayout

from tinypedal.ui.ordered_picker import ROLE_HEADER, ROLE_KEY, OrderedPicker, PickerEntry


def make_entries(removable: bool = True) -> dict[str, PickerEntry]:
    return {
        "lap": PickerEntry("lap", "Lap Viewer", "", "L", "Tools", removable),
        "race": PickerEntry("race", "Race Calculator", "", "R", "Tools", removable),
        "preset": PickerEntry("preset", "Preset", "", "P", "Pages", removable),
        "palette": PickerEntry("palette", "Command Palette", "", "C", "Actions", removable),
    }


@pytest.fixture
def picker(ui_env):
    widget = OrderedPicker(None, make_entries(), ["race", "lap"])
    changes = []
    widget.changed.connect(lambda: changes.append(widget.shown_keys()))
    widget.changes = changes
    yield widget
    widget.deleteLater()


def available_rows(widget):
    rows = []
    for row in range(widget.available_list.count()):
        item = widget.available_list.item(row)
        if not item.isHidden():
            rows.append(("#" if item.data(ROLE_HEADER) else "") + (item.data(ROLE_KEY) or item.text()))
    return rows


def test_shown_and_available(picker):
    assert picker.shown_keys() == ["race", "lap"]
    assert picker.label_shown.text() == "Shown (2)" and picker.label_empty.isHidden()
    assert available_rows(picker) == ["#Pages", "preset", "#Actions", "palette"]  # grouped by kind
    picker.set_shown(["preset", "bogus", "preset", "lap"], notify=False)
    assert picker.shown_keys() == ["preset", "lap"]  # unknown & duplicate left out


def test_add_remove_move(picker):
    picker.add("palette")
    assert picker.shown_keys() == ["race", "lap", "palette"] and picker.shown_list.currentItem().data(ROLE_KEY) == "palette"
    picker.add("palette")  # already shown
    picker.move_entry("palette", -1)
    assert picker.shown_keys() == ["race", "palette", "lap"]
    picker.move_entry("race", -1)  # already first
    picker.move_selected(1)  # moved entry stays selected
    assert picker.shown_keys() == ["race", "lap", "palette"]
    picker.remove("race")
    assert picker.shown_keys() == ["lap", "palette"] and "race" in available_rows(picker)
    assert picker.changes == [
        ["race", "lap", "palette"], ["race", "palette", "lap"], ["race", "lap", "palette"], ["lap", "palette"]]
    picker.remove("lap")
    picker.remove("palette")
    assert picker.shown_keys() == [] and not picker.label_empty.isHidden()


def test_search_and_everything_shown(picker):
    picker.edit_search.setText("command")
    assert available_rows(picker) == ["#Actions", "palette"]  # empty section hidden
    picker.edit_search.setText("tools")  # kind matches too
    assert available_rows(picker) == []  # tools all shown
    assert not picker.label_all_shown.isHidden() and picker.label_all_shown.text() == "No entry found."
    picker.edit_search.clear()
    picker.set_shown(list(make_entries()))
    assert available_rows(picker) == [] and picker.label_all_shown.text() == "Every entry is shown."


def test_row_buttons_and_badges(picker):
    delegate = picker.shown_list.itemDelegate()
    first = picker.shown_list.model().index(0, 0)
    last = picker.shown_list.model().index(1, 0)
    assert delegate.buttons(first) == ("up", "down", "remove")
    assert not delegate.button_enabled("up", first) and delegate.button_enabled("down", first)
    assert not delegate.button_enabled("down", last)
    rects = delegate.button_rects(QRectF(0, 0, 300, 40), first)
    assert rects["remove"].right() < 300 and rects["up"].right() <= rects["down"].left()
    picker.run_button("down", "race")
    assert picker.shown_keys() == ["lap", "race"]
    picker.run_button("remove", "lap")
    picker.run_button("add", "preset")
    assert picker.shown_keys() == ["race", "preset"]
    available = picker.available_list.itemDelegate()
    entry = picker.available_list.model().index(1, 0)
    assert available.buttons(entry) == ("add",) and available.buttons(picker.available_list.model().index(0, 0)) == ()
    assert picker.badge_text(0) == "1"
    picker.badge = lambda row: f"Ctrl+{row + 1}" if row < 9 else ""
    assert picker.badge_text(8) == "Ctrl+9" and picker.badge_text(9) == ""


def test_keyboard(picker):
    picker.shown_list.setCurrentRow(0)
    QApplication.sendEvent(picker.shown_list, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down,
                                                        Qt.KeyboardModifier.AltModifier))
    assert picker.shown_keys() == ["lap", "race"]
    QApplication.sendEvent(picker.shown_list, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete,
                                                        Qt.KeyboardModifier.NoModifier))
    assert picker.shown_keys() == ["lap"]
    picker.available_list.setCurrentRow(next(
        row for row in range(picker.available_list.count())
        if picker.available_list.item(row).data(ROLE_KEY) == "palette"))
    QApplication.sendEvent(picker.available_list, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                            Qt.KeyboardModifier.NoModifier))
    assert picker.shown_keys() == ["lap", "palette"]


def test_reorder_only_and_layout(ui_env):
    widget = OrderedPicker(None, make_entries(removable=False), ["preset"], show_kind=False)
    assert widget.shown_keys() == ["preset", "lap", "race", "palette"]  # entries that cannot be hidden kept
    assert widget.available_card.isHidden()
    widget.remove("preset")  # cannot be removed
    assert len(widget.shown_keys()) == 4
    assert widget.shown_list.itemDelegate().buttons(widget.shown_list.model().index(0, 0)) == ("up", "down")
    widget.resize(200, 400)
    widget.show()
    QApplication.processEvents()
    assert widget.layout_main.direction() == QBoxLayout.Direction.TopToBottom  # narrow: stacked
    widget.resize(2000, 400)
    QApplication.processEvents()
    assert widget.layout_main.direction() == QBoxLayout.Direction.LeftToRight
    widget.deleteLater()


@pytest.mark.parametrize("icon_family", ["", "Segoe Fluent Icons"])
def test_rows_drawn(ui_env, icon_family):
    widget = OrderedPicker(None, make_entries(), ["race", "lap"], icon_family=icon_family)
    widget.resize(700, 400)
    image = widget.grab().toImage()
    assert not image.isNull() and image.width() == 700
    widget.deleteLater()


# --- Editors built on picker
def test_rail_editor_marks_changes_and_undo(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.ui.nav_rail import RailEditor, current_rail_items

    saved = []
    editor = RailEditor(None, lambda: saved.append(1))
    start = editor.checked_items()
    assert start == current_rail_items() and not editor.is_modified()
    assert editor.picker.badge_text(0) == "Ctrl+1" and editor.picker.badge_text(9) == ""
    editor.picker.remove(start[0])
    assert editor.is_modified() and editor.checked_items() == start[1:]
    editor.undo()
    assert editor.checked_items() == start
    editor.redo()
    editor.applying()  # Ctrl+S: saved, kept open
    assert saved == [1] and not editor.is_modified()
    assert cfg.application["rail_items"] == ",".join(start[1:])
    assert editor.save_action() == editor.applying
    editor.close()
