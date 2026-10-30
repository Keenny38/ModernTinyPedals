"""Overlay Options page: rows in a ListView reusing delegates (one block per row type), every row made shows its
own option after reuse (labels, editor values), typed text taken before a row is reused, no QML warning"""

from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, Qt, qInstallMessageHandler
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from tests.test_overlay_options import flush, window  # noqa: F401


def find_list(view):
    stack = [view.rootObject()]
    while stack:
        item = stack.pop()
        if item.metaObject().className().startswith("QQuickListView") and item.property("reuseItems"):
            return item
        stack.extend(item.childItems())
    raise AssertionError("no options list")


def item_at(listing, number: int):
    return QMetaObject.invokeMethod(listing, "itemAtIndex", Q_RETURN_ARG(QQuickItem), Q_ARG(int, number))


def subtree(item):
    stack, found = [item], []
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(current.childItems())
    return found


def of_type(items, name: str):
    return [item for item in items if item.metaObject().className().startswith(name)]


def rows_made(listing):
    return [item for item in listing.property("contentItem").childItems() if item.property("rowType") is not None]


def settled_rows(listing) -> list:
    """Rows once the list stops making them (rows are incubated over several frames: a slow machine has made only
    part of the view after 50 ms)"""
    rows, same = rows_made(listing), 0
    for _ in range(60):
        QTest.qWait(50)
        now = rows_made(listing)
        same = same + 1 if len(now) == len(rows) else 0
        rows = now
        if same >= 4:
            break
    return rows


def check_shown_rows(page, listing) -> int:
    """Every row in view shows its own option: title, label, editor value; one block per row"""
    rows = page.backend.rows.rows
    checked = 0
    for number, row in enumerate(rows):
        item = item_at(listing, number)
        if item is None:
            continue
        assert item.property("rowType") == row["row"], (number, row["key"])
        items = subtree(item)
        texts = {text.property("text") for text in of_type(items, "QQuickText") if text.isVisible()}
        loaders = [loader for loader in of_type(items, "QQuickLoader") if loader.property("item") is not None]
        if row["row"] == "header":
            assert row["title"] in texts, (row["title"], texts)
        elif row["row"] == "option":
            assert (row["marked"] or row["label"]) in texts, (row["label"], texts)  # searched words in bold
            numbers = of_type(items, "NumberField")
            fields = of_type(items, "TpTextField")
            combos = of_type(items, "TpCombo")
            if row["kind"] in ("integer", "float"):
                assert len(numbers) == 1 and not fields and not combos
                text = numbers[0].property("text")
                decimals = row["decimals"]
                assert len(text.partition(".")[2]) == decimals, (row["key"], text, decimals)
                assert abs(float(text) - row["number"]) <= 0.5 * 10 ** -decimals + 1e-9, (row["key"], text)
            elif row["kind"] in ("choice", "font"):
                assert len(combos) == 1 and not numbers
                assert combos[0].property("currentIndex") == row["choiceIndex"], row["key"]
            elif row["kind"] != "bool":
                assert len(fields) == 1 and not numbers
                assert fields[0].property("text") == row["text"], (row["key"], fields[0].property("text"))
        assert len(loaders) <= 2  # its block (& editor of an option): other blocks not made
        checked += 1
    return checked


def scroll_through(page, listing):
    """Rows checked at every scroll step, top to bottom"""
    listing.setProperty("contentY", listing.property("originY"))
    QTest.qWait(30)
    checked = check_shown_rows(page, listing)
    step = listing.property("height") * 0.7
    while (listing.property("contentY") + listing.property("height")
           < listing.property("originY") + listing.property("contentHeight") - 1):
        listing.setProperty("contentY", listing.property("contentY") + step)
        QTest.qWait(30)
        checked += check_shown_rows(page, listing)
    return checked


def test_rows_reused_show_their_own_option(window):  # noqa: F811
    from neopedal.ui.overlay_options import open_overlay_options

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        page = open_overlay_options(window, "relative")
        page.backend.setAdvanced(True)
        QTest.qWait(50)
        listing = find_list(page.view)
        made = {id(item) for item in settled_rows(listing)}
        assert 0 < len(made) < page.backend.rows.rowCount()
        for name in ("relative", "fuel", "black_box", "speedometer", "relative"):
            page.backend.selectOverlay(name)
            page.backend.setAdvanced(True)
            QTest.qWait(50)
            assert scroll_through(page, listing) > 0
        assert len({id(item) for item in rows_made(listing)} | made) < 3 * len(made)  # reused, not made again
        page.backend.setScopeAll(True)
        page.backend.setSearch("color")  # rows of many overlays
        QTest.qWait(50)
        assert scroll_through(page, listing) > 0
        page.backend.setSearch("")
        page.backend.setScopeAll(False)
        page.backend.setAllCollapsed(True)
        QTest.qWait(50)
        check_shown_rows(page, listing)
        page.backend.setAllCollapsed(False)
        QTest.qWait(50)
        check_shown_rows(page, listing)
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


def test_field_text_put_back_and_typed_text_taken_on_reuse(window):  # noqa: F811
    """Field showing other text than its option (binding broken by typing): option value shown once reused;
    focused field scrolled out: typed text taken for its own option before the row is reused"""
    from neopedal.ui.overlay_options import open_overlay_options

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        check_reused_fields(open_overlay_options(window, "relative"))
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


def check_reused_fields(page):
    page.backend.setAdvanced(True)
    QTest.qWait(50)
    listing = find_list(page.view)
    rows = page.backend.rows.rows
    number = next(number for number, row in enumerate(rows)
                  if row["row"] == "option" and row["kind"] in ("integer", "float") and item_at(listing, number))
    item = item_at(listing, number)
    field = of_type(subtree(item), "NumberField")[0]
    QQmlExpression(qmlContext(field), field, "text = '987'").evaluate()  # JS assignment, as typing does
    top = listing.property("contentY")
    listing.setProperty("contentY", item.property("y") + item.property("height") + listing.property("cacheBuffer") + 50)
    QTest.qWait(50)
    assert item_at(listing, number) is None  # released to the pool
    listing.setProperty("contentY", top)
    QTest.qWait(50)
    assert any(item_at(listing, index) is item for index in range(len(rows)))  # reused
    check_shown_rows(page, listing)
    assert scroll_through(page, listing) > 0
    # Typed text, row scrolled out while focused
    number = next(number for number, row in enumerate(rows) if row["row"] == "option" and row["kind"] == "text")
    QQmlExpression(qmlContext(listing), listing, f"positionViewAtIndex({number}, ListView.Center)").evaluate()
    QTest.qWait(50)
    overlay, option = rows[number]["key"].split("/")
    field = of_type(subtree(item_at(listing, number)), "TpTextField")[0]
    page.view.setFocus()
    field.forceActiveFocus()
    QTest.keyClick(page.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(page.view, "Q")
    # Typed text taken at each key (as on the Settings page: unsaved changes bar & Ctrl+S see it)
    assert field.property("text") == "Q" and page.backend.value(overlay, option) == "Q"
    listing.setProperty("contentY", listing.property("originY"))  # row released & reused
    QTest.qWait(50)
    flush()
    assert page.backend.value(overlay, option) == "Q"
    assert scroll_through(page, listing) > 0
    page.backend.discard()


def test_class_order_list_on_page(window):  # noqa: F811
    """Standings class order shown with the order list of columns (rank, drag, arrows), arrows move classes"""
    import os

    from PySide6.QtCore import QPointF

    from neopedal.ui.overlay_options import open_overlay_options

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        page = open_overlay_options(window, "standings")
        page.backend.setAdvanced(True)
        page.resize(900, 1400)
        QTest.qWait(50)
        listing = find_list(page.view)
        number = page.backend.rows.index_of("standings/class_order")
        assert number >= 0
        QMetaObject.invokeMethod(listing, "positionViewAtIndex", Q_ARG(int, number), Q_ARG(int, 1))  # Beginning
        QTest.qWait(50)
        item = item_at(listing, number)
        assert item is not None and item.property("rowType") == "order"
        texts = {text.property("text") for text in of_type(subtree(item), "QQuickText") if text.isVisible()}
        assert {"Hypercar", "LMP2 ELMS", "GT3", "GTE"} <= texts
        QMetaObject.invokeMethod(item, "moveItem", Q_ARG("QVariant", "GT3"), Q_ARG("QVariant", -1))
        assert page.backend.value("standings", "class_order").startswith("Hypercar, Hyper, LMP2 ELMS, LMP2, GT3, LMP3")
        shot = os.environ.get("CLASS_ORDER_SHOT")
        if shot:
            top = int(item.mapToScene(QPointF(0, 0)).y())
            page.view.grab().copy(0, max(top - 40, 0), page.view.width(), int(item.height()) + 80).save(shot)
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages
