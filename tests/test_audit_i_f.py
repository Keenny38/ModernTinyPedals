"""Audit I, lot F: lap viewer simple view & Show menu

Groups of simple view as a list model synced in place (only while shown), steering wheel without multisampled layer
per lap card, Show menu chips made once and kept, shown state read by key."""

from PySide6.QtCore import QMetaObject, QObject

from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import chart_of, evaluate, find, items, named, opener, wait, warnings  # noqa: F401


def group_items(view) -> dict:
    """Group delegates of simple view by title"""
    return {item.property("title"): item for item in find(view, lambda item: item.property("first") is not None
                                                          and item.property("values") is not None)}


def cells_of(group) -> list:
    return [item for item in items(group) if item.property("cursorValue") is not None]


def model_rows(backend) -> list[dict]:
    return [dict(row) for row in backend.dashboard.groups.rows]


# --- Groups model
def test_groups_model_follows_layout(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    backend.setSimpleView(True)
    wait(0.5)
    for group in ("engine", "chassis"):
        backend.dashboard.setGroup(group, True)
    wait(0.2)
    layout = backend.dashboard.layout
    assert backend.dashboard.groupKeys == [group["key"] for group in layout]
    rows = model_rows(backend)
    expected = [group for group in layout if group["key"] != "driver"]  # pedal cards apart
    assert [row["key"] for row in rows] == [group["key"] for group in expected]
    for row, group in zip(rows, expected):
        assert row["first"] == group["items"][0]["index"]
        assert [item["key"] for item in row["items"]] == [item["key"] for item in group["items"]]
        assert all("index" not in item for item in row["items"])  # cells kept when items before them change
        # items of a group follow each other in values read at cursor
        assert [item["index"] for item in group["items"]] == list(range(row["first"], row["first"]
                                                                        + len(group["items"])))
    items_read = backend.dashboard.items
    assert backend.dashboard.layout and backend.dashboard.items is items_read  # same items: cursor cache kept


def test_groups_kept_in_place_on_toggle(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    backend.setSimpleView(True)
    wait(0.5)
    backend.dashboard.setGroup("chassis", True)
    wait(0.3)
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.3)
    before = group_items(view)
    timing_title = next(row["title"] for row in model_rows(backend) if row["key"] == "timing")
    chassis_title = next(row["title"] for row in model_rows(backend) if row["key"] == "chassis")
    timing, chassis = before[timing_title], before[chassis_title]
    timing_cells, chassis_cells = cells_of(timing), cells_of(chassis)
    first = chassis.property("first")
    told = []
    backend.dashboard.layoutChanged.connect(lambda: told.append(1))
    backend.setChannelVisible("rpm", True)  # engine group added between timing & chassis
    wait(0.3)
    after = group_items(view)
    assert after[timing_title] is timing and after[chassis_title] is chassis  # groups kept
    assert cells_of(timing) == timing_cells and cells_of(chassis) == chassis_cells  # their cells too
    assert chassis.property("first") == first + 1  # one item before it
    assert told  # values asked again
    assert evaluate(view, chart, "cursorDashboard.length") == len(backend.dashboard.cursor_values(500.0))
    for cell in cells_of(chassis):  # values of its items read at their new place
        if cell.property("kind") != "inputs":
            assert evaluate(view, cell, "cursorValue.key") == evaluate(view, cell, "modelData.key")
            assert evaluate(view, cell, "entries.length") > 0
    backend.setChannelVisible("rpm", False)
    wait(0.3)
    assert group_items(view)[chassis_title] is chassis and chassis.property("first") == first


def test_groups_not_synced_while_hidden(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSimpleView(True)
    wait(0.5)
    groups = group_items(view)
    assert groups
    backend.setSimpleView(False)
    wait(0.5)
    simple = find(view, lambda item: item.property("cardsShown") is not None)[0]
    assert not simple.isVisible() and evaluate(view, simple, "layout.length") == 0
    synced = []
    original = type(backend.dashboard).update_layout
    try:
        type(backend.dashboard).update_layout = lambda self: (synced.append(1), original(self))[1]
        backend.dashboard.setGroup("tyres", True)
        backend.setChannelVisible("rpm", True)
        wait(0.2)
        assert not synced  # hidden: groups kept as they were, not synced
        assert group_items(view) == groups and "tyres" not in [row["key"] for row in model_rows(backend)]
        backend.setSimpleView(True)
        wait(0.5)
        # Synced once shown (the simple view may ask once more as it becomes visible on a slow machine), never
        # while hidden (checked above)
        assert 1 <= len(synced) <= 2, synced
    finally:
        type(backend.dashboard).update_layout = original
    assert {"tyres", "engine"} <= {row["key"] for row in model_rows(backend)}
    assert evaluate(view, simple, "layout.length") == len(backend.dashboard.groupKeys) > 0


# --- Steering wheel
def test_steering_wheel_without_layer(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSimpleView(True)
    wait(0.5)
    evaluate(view, chart_of(view), "setCursor(500, 'key')")
    wait(0.3)
    wheels = find(view, lambda item: item.property("realAngle") is not None and item.property("turn") is not None)
    assert wheels
    for wheel in wheels:
        assert not evaluate(view, wheel, "layer.enabled")  # no multisampled texture per lap card
        rectangles = [item for item in items(wheel) if item.metaObject().className().startswith("QQuickRectangle")]
        assert rectangles and all(item.property("antialiasing") for item in rectangles)  # turned shapes smooth


# --- Show menu
def open_menu(view):
    button = named(view, "showButton")
    QMetaObject.invokeMethod(button, "clicked")
    wait(0.5)


def picker_of(view):
    return view.rootObject().findChild(QObject, "showPicker")


def chips_of(view) -> list:
    """Chips made (shown or not): popup content walked even while closed"""
    return [item for item in items(picker_of(view).property("contentItem")) if item.objectName() == "showChip"]


def test_show_menu_chips_kept_while_closed(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    picker = picker_of(view)
    assert not chips_of(view)  # never opened: none made
    open_menu(view)
    chips = chips_of(view)
    assert chips
    picker.close()
    wait(0.4)
    backend.setChannelVisible("rpm", "rpm" not in backend.visible)  # toggled while closed: nothing read
    wait(0.2)
    assert chips_of(view) == chips
    open_menu(view)
    assert chips_of(view) == chips  # made once, kept
    rpm = next(chip for chip in chips if chip.property("channel") == "rpm")
    assert rpm.property("shown") == ("rpm" in backend.visible)  # shown state read again on opening
    picker.close()
    wait(0.4)
    try:
        assert backend.math.save("", "Twice", "speed_kph * 2", "") == ""  # channels changed while closed
        wait(0.2)
        assert chips_of(view) == chips  # made again only once opened
        open_menu(view)
        assert chips_of(view) != chips
        assert any("Twice" in chip.property("text") for chip in chips_of(view))
    finally:
        picker.close()
        backend.math.remove("Twice")
        wait(0.3)


def test_show_menu_group_boxes(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.dashboard.setGroup("tyres", False)
    assert backend.dashboard.shownState["groups"]["tyres"] == 0
    backend.setChannelVisible("tyre_temp_fl", True)  # one wheel channel: some shown
    assert backend.dashboard.shownState["groups"]["tyres"] == 1
    backend.dashboard.setGroup("tyres", True)  # every channel but one wheel ones: all shown
    state = backend.dashboard.shownState
    assert state["groups"]["tyres"] == 2 and state["channels"]["all:tyre_temp"] is True
    assert set(state["channels"]) == set(backend.visible)
    open_menu(view)
    boxes = {item.property("modelData")["key"]: item for item in find(view, lambda item: item.property("shownLevel")
                                                                      is not None)}
    tyres = boxes["tyres"]
    assert tyres.property("allShown") and tyres.property("anyShown")
    row = next(item for item in tyres.childItems() if item.property("activeFocusOnTab"))
    evaluate(view, row, "toggle()")  # full group's box clicked: whole group hidden, one wheel channels too
    wait(0.2)
    assert not tyres.property("anyShown")
    assert not any(column.startswith(("all:tyre", "tyre_")) for column in backend.visible)
    evaluate(view, row, "toggle()")
    wait(0.2)
    assert tyres.property("allShown")
    picker_of(view).close()
    backend.resetChannels()
    wait(0.3)
