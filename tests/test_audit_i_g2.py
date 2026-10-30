"""Audit 2026-10-18, lot G2: race results laps & classification (reused rows, spoken text made by backend, car
picker told only what changed) and overlay options rows (roles read once per row, never for other row types)"""

from collections import Counter

from PySide6.QtCore import Q_ARG, QCoreApplication, QEvent, QMetaObject, QObject

from tests.test_perf_bridge_pages import settle, walk, window  # noqa: F401
from tests.test_perf_page_state import qml_warnings  # noqa: F401
from tests.test_race_results import (  # noqa: F401
    backend,
    english,
    race,
    results_folder,
    wait_until,
)


def counter(signal) -> list:
    told: list = []
    signal.connect(lambda *args: told.append(True))
    return told


def items_of(root, prefix: str) -> list:
    return [item for item in walk(root) if item.metaObject().className().startswith(prefix)]


# Race results: rows
def test_rows_spoken_text_made_by_backend(english, ui_env):  # noqa: F811
    from neopedal.ui.quick import results_backend as rb

    result = race()
    alice = rb.lap_rows(result, result.entries[0])
    assert [row["accessibleText"] for row in alice][:2] == [
        f"Lap 1, {alice[0]['timeText']}", f"Lap 2, {alice[1]['timeText']}, Session best"]
    bob = rb.lap_rows(result, result.entries[1])
    assert bob[1]["accessibleText"] == "Lap 2, —"  # no time: dim dash kept, no record
    assert bob[2]["accessibleText"] == f"Lap 3, {bob[2]['timeText']}, Personal best, PIT"
    rows = rb.classification_rows(result, "", "")
    assert rows[0]["accessibleText"] == "1, Alice Driver, " + ", ".join(
        part for part in (rows[0]["team"], rows[0]["gapText"], rows[0]["bestText"]) if part)
    assert all(set(row) == set(rb.CLASSIFICATION_ROLES) for row in rows)
    assert all(set(row) == set(rb.LAP_ROLES) for row in alice + bob)
    assert rb.spoken("P1", "", "Name", "") == "P1, Name"


def test_rows_spoken_text_translated(ui_env):
    from neopedal import i18n
    from neopedal.ui.quick import results_backend as rb

    i18n.set_language("Français")
    try:
        result = race()
        bob = rb.lap_rows(result, result.entries[1])
        assert bob[2]["accessibleText"].startswith(i18n.tr("Lap") + " 3, ")
        assert bob[2]["accessibleText"].endswith(f", {i18n.tr('Personal best')}, {i18n.tr('PIT')}")
    finally:
        i18n.set_language("English")


def test_car_picker_tells_only_what_changed(backend, english):  # noqa: F811
    options, index = counter(backend.driverOptionsChanged), counter(backend.driverIndexChanged)
    driver, summary = counter(backend.driverChanged), counter(backend.lapSummaryChanged)
    columns, unit = counter(backend.lapsChanged), counter(backend.speedUnitChanged)
    resets = counter(backend.lapModel.modelReset)
    listed = backend.driverOptions
    assert backend.driverIndex == 0 and backend.driverInfo["name"] == "Alice Driver"
    backend.selectEntry("1")
    assert not options and backend.driverOptions == listed  # same cars to pick: combo list kept
    assert index and driver and summary and columns and resets and not unit
    assert (backend.driverIndex, backend.driverInfo["name"]) == (1, "Bob Racer")
    for told in (index, driver, summary, columns, resets):
        told.clear()
    backend.selectEntry("1")  # same car
    backend.refresh_session()  # same session read again: nothing new
    assert not (options or index or driver or summary or columns or unit or resets)
    backend.selectEntryAt(2)  # combo pick: index in list
    assert backend.selectedEntry == listed[2]["key"] and backend.driverIndex == 2 and index and driver
    backend.selectEntryAt(9)  # out of list: ignored
    backend.selectEntryAt(-1)
    assert backend.selectedEntry == listed[2]["key"]
    index.clear()
    backend.setClassFilter("Hyper")  # car picked not in class: first car of class, list of class
    assert options and index and backend.driverIndex == 0
    assert [option["key"] for option in backend.driverOptions] == ["0", "1"]
    options.clear()
    index.clear()
    backend.setClassFilter("")
    assert options and index and backend.driverIndex == 0  # list replaced: index told again (combo reset)


def test_same_car_read_again_keeps_lap_rows(backend):  # noqa: F811
    model = backend.lapModel
    rows = [dict(row) for row in model.rows]
    resets, changed = counter(model.modelReset), counter(model.dataChanged)
    backend.refresh_driver()
    assert not resets and not changed and model.rows == rows
    backend.selectEntry("1")
    assert resets  # other car: list from the top


def test_lap_and_classification_lists_reuse_rows(results_folder, english, qml_warnings):  # noqa: F811
    from neopedal.ui.race_results_viewer import RaceResultsViewer

    viewer = RaceResultsViewer(None)
    try:
        viewer.resize(1400, 800)
        viewer.show()
        backend = viewer.backend
        assert wait_until(lambda: backend.loaded_once and backend.result is not None)
        root = viewer.view.rootObject()
        table = root.findChild(QObject, "classification")
        assert table is not None and table.property("reuseItems")
        rows = backend.classificationModel.rows
        shown = items_of(table, "QQuickItem")  # delegates: plain Items
        texts = {item.property("accessibleText") for item in shown if item.property("accessibleText")}
        assert texts == {row["accessibleText"] for row in rows}
        backend.setTab(2)  # laps
        assert wait_until(lambda: root.findChild(QObject, "lapList") is not None)
        laps = root.findChild(QObject, "lapList")
        assert laps.property("reuseItems")
        combo = items_of(items_of(root, "ResultsLaps")[0], "TpCombo")[0]
        model = combo.property("model")
        models = counter(combo.modelChanged)
        QMetaObject.invokeMethod(combo, "activated", Q_ARG(int, 1))  # car picked in combo
        settle(0.1)
        assert backend.selectedEntry == backend.driverOptions[1]["key"] and combo.property("currentIndex") == 1
        assert not models and combo.property("model") == model  # combo list not sent again

        def shown_rows():
            return {(item.property("lap"), item.property("timeText"), item.property("accessibleText"))
                    for item in items_of(laps, "QQuickItem") if item.property("accessibleText") and item.isVisible()}

        assert shown_rows() == {(row["lap"], row["timeText"], row["accessibleText"]) for row in backend.lapModel.rows}
        backend.selectEntry("0")  # rows reused for the other car's laps
        settle(0.1)
        assert shown_rows() == {(row["lap"], row["timeText"], row["accessibleText"]) for row in backend.lapModel.rows}
        assert combo.property("currentIndex") == 0
        backend.setClassFilter("GT3")  # list replaced: combo follows car picked
        settle(0.1)
        assert combo.property("count") == 1 and combo.property("currentIndex") == 0
        assert not [text for text in qml_warnings if "Results" in text], qml_warnings
    finally:
        viewer.close()
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# Overlay options: rows
def role_reads(window, names):  # noqa: F811
    """Reads of each role while overlays are switched, rows of each type shown"""
    from neopedal.ui.overlay_options import open_overlay_options
    from neopedal.ui.quick.models import DictListModel

    page = open_overlay_options(window, names[-1])
    assert page is not None and not page.view.errors()
    page.resize(1200, 900)
    page.show()
    settle()
    model = page.backend.rows
    roles = {number: bytes(name).decode() for number, name in model.roleNames().items()}
    reads: Counter = Counter()
    readers: dict = {}  # role: rows (type, key) that read it
    original = DictListModel.data

    def counting(index, role=0):
        name = roles.get(role, role)
        reads[name] += 1
        row = model.rows[index.row()] if 0 <= index.row() < len(model.rows) else {}
        readers.setdefault(name, set()).add((row.get("row"), row.get("key")))
        return original(model, index, role)

    model.data = counting  # instance attribute: called by Qt instead of the class method
    try:
        for name in names:
            page.backend.selectOverlay(name)
            settle(0.15)
    finally:
        del model.data
    return page, reads, readers


def test_option_rows_read_each_role_once(window, qml_warnings):  # noqa: F811
    _, reads, readers = role_reads(window, ("fuel", "relative", "speedometer"))
    # Header roles read once by the header block (was up to 5 reads each), never for option rows; measured on
    # these overlays: 19.6 reads per row and switch, 21.2 before, 29.3 with header roles required (fed to every row).
    # Counted by row: a role is read again by a change notice of its row (one more read, timing dependent)
    header_rows = readers["title"]
    headers = len(header_rows)
    assert 0 < headers < reads["kind"] / 2, reads
    assert {row_type for row_type, _ in header_rows} == {"header"}, header_rows
    for name in ("toggle", "toggleChecked", "collapsed", "count", "customizedCount"):
        assert readers[name] == header_rows, (name, readers[name] ^ header_rows)  # every header row, those only
        assert reads[name] < headers * 2, (name, reads)  # about once per header block
    assert reads["changedCount"] < headers * 2  # only while collapsed
    assert reads["defaultText"] == 0  # reset tip: read only while hovered
    assert reads["color"] <= reads["kind"] / 4 and reads["orders"] <= reads["kind"] / 4  # their row type only
    assert not [text for text in qml_warnings if "OverlayOption" in text], qml_warnings


def header_items(page, key: str):
    root = page.view.rootObject()
    QMetaObject.invokeMethod(root, "scrollToKey", Q_ARG("QVariant", key))  # row shown (made)
    settle(0.05)
    for row in items_of(root, "OverlayOptionRow"):
        if row.property("settled") and row.property("rowType") == "header":
            index = row.property("index")
            if page.backend.rows.rows[index]["key"] == key:
                return row, items_of(row, "QQuickItem")
    return None, []


def section_with_switch(options) -> tuple[dict, dict]:
    """Overlay picked with a section that has an item switch: its header, and an on/off option of that section"""
    for name in [row["key"] for row in options.nav.rows]:
        options.selectOverlay(name)
        header: dict = {}
        for row in options.rows.rows:
            if row["row"] == "header":
                header = row if row["toggle"] and not row["locked"] else {}  # not set by a display profile
            elif (header and row["row"] == "option" and row["kind"] == "bool" and row["key"] != header["toggle"]
                  and not row["locked"]):
                return dict(header), dict(row)  # copies: model rows are changed in place
    raise AssertionError("no section with an item switch & an on/off option")


def test_option_header_and_order_rows_follow_backend(window, qml_warnings):  # noqa: F811
    """Header block (title, count, collapse, item switch, unsaved bar) & order list read their roles once and still
    follow every change"""
    from neopedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "relative")
    page.resize(1200, 900)
    page.show()
    settle()
    options = page.backend
    header, option = section_with_switch(options)
    settle(0.2)
    item, _ = header_items(page, header["key"])
    assert item is not None
    blocks = [child for child in walk(item) if child.property("pending") is not None]
    assert len(blocks) == 1
    block = blocks[0]
    assert (block.property("title"), block.property("toggle"), block.property("toggleChecked")) == (
        header["title"], header["toggle"], header["toggleChecked"])
    assert block.property("count") == header["count"] and not block.property("collapsed")
    options.setBool(header["toggle"], not header["toggleChecked"])  # item switched: switch follows
    settle(0.1)
    assert block.property("toggleChecked") == (not header["toggleChecked"])
    options.setBool(option["key"], not option["checked"])  # unsaved edit in the section
    options.toggleSection(header["key"])  # collapsed: unsaved bar on the header
    settle(0.2)
    item, _ = header_items(page, header["key"])
    block = next(child for child in walk(item) if child.property("pending") is not None)
    assert block.property("collapsed") and block.property("pending")
    assert block.property("customizedCount") >= 1
    bars = [child for child in item.childItems()[1].childItems() if child.property("radius") is not None
            and child.isVisible() and child.property("width") < 10 and child.property("height") > 10]
    assert bars  # unsaved edit bar shown on the collapsed header
    options.toggleSection(header["key"])
    settle(0.1)
    order = next(dict(row) for name in [row["key"] for row in options.nav.rows] if options.selectOverlay(name) is None
                 for row in options.rows.rows if row["row"] == "order" and len(row["orders"]) > 1 and not row["option"])
    settle(0.2)

    def order_block():
        root = page.view.rootObject()
        QMetaObject.invokeMethod(root, "scrollToKey", Q_ARG("QVariant", order["key"]))
        settle(0.05)
        for row in items_of(root, "OverlayOptionRow"):
            if row.property("settled") and options.rows.rows[row.property("index")]["key"] == order["key"]:
                return next(child for child in walk(row) if child.property("orders") is not None)
        raise AssertionError("order list row not shown")

    block = order_block()
    assert [item["key"] for item in block.property("orders")] == [item["key"] for item in order["orders"]]
    first = order["orders"][0]["key"]
    options.moveOrder(order["overlay"], first, 1)  # first item one place down: list follows
    settle(0.1)
    block = order_block()
    assert [item["key"] for item in block.property("orders")][1] == first
    assert not [text for text in qml_warnings if "OverlayOption" in text], qml_warnings


def test_overlay_list_entries_follow_roles(window, qml_warnings):  # noqa: F811
    """Overlay list (left): required roles follow the options (selection, label, counts)"""
    from neopedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "relative")
    page.resize(1200, 900)
    page.show()
    settle()
    options = page.backend
    entries = [item for item in walk(page.view.rootObject())
               if item.property("badgeCount") is not None and item.property("overlayOn") is not None]
    assert entries
    selected = [item for item in entries if item.property("selected")]
    assert [item.property("key") for item in selected] == ["relative"]
    rows = {row["key"]: row for row in options.nav.rows}
    for item in entries:
        row = rows[item.property("key")]
        assert (item.property("label"), item.property("overlayOn"), item.property("customized")) == (
            row["label"], row["enabled"], row["customized"])
    options.selectOverlay("fuel")
    settle(0.1)
    entries = [item for item in walk(page.view.rootObject())
               if item.property("badgeCount") is not None and item.property("overlayOn") is not None]
    assert [item.property("key") for item in entries if item.property("selected")] == ["fuel"]
    assert not [text for text in qml_warnings if "OverlayOptions" in text], qml_warnings


def test_color_swatch_follows_its_option(window, qml_warnings):  # noqa: F811
    from neopedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "relative")
    page.resize(1200, 900)
    page.show()
    settle()
    options = page.backend
    # Modern designs read theme colors (no color option): classic layout (pending switch) shows them
    options.setBool("relative/enable_classic_layout", True)
    settle(0.1)
    option = next(dict(row) for row in options.rows.rows
                  if row["row"] == "option" and row["kind"] == "color" and not row["locked"])
    settle(0.2)

    def swatch():
        root = page.view.rootObject()
        QMetaObject.invokeMethod(root, "scrollToKey", Q_ARG("QVariant", option["key"]))
        settle(0.05)
        for row in items_of(root, "OverlayOptionRow"):
            if row.property("settled") and options.rows.rows[row.property("index")]["key"] == option["key"]:
                return next(child for child in walk(row) if child.property("swatchColor") is not None)
        raise AssertionError("color row not shown")

    assert swatch().property("swatchColor") == option["color"] != ""
    options.setText(option["key"], "#FF102030")
    settle(0.1)
    assert swatch().property("swatchColor").upper() == "#FF102030"
    options.setText(option["key"], "not a color")  # invalid: no swatch color ("?" shown)
    settle(0.1)
    assert swatch().property("swatchColor") == ""
    assert not [text for text in qml_warnings if "OverlayOption" in text], qml_warnings
