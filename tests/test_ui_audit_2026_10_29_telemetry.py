"""UI/UX audit of 2026-10-29, telemetry lot (lap viewer): synthesis band under lap chips (T1), guided analysis (worst
corner, Shift+[ ] through lost corners), corner detection in the corner tool's "⋯" popup, Compare ▾ & checked laps
menus (T2), Best vs Last Lap in the empty charts, B / L / R keys same on map & charts, Share vs Export Data menus,
lap list drawer on narrow pages"""

import pytest
import shiboken6
from PySide6.QtCore import QMetaObject, QObject, Qt
from PySide6.QtQml import QQmlExpression

from neopedal import i18n
from tests.test_lap_viewer import flush_deleted, wait_loaded
from tests.test_lap_viewer_features import check_only, laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import (  # noqa: F401
    chart_of,
    find,
    focused,
    key,
    named,
    no_qml_warnings,
    opener,
    track_maps,
    wait,
    warnings,
)


def evaluate(view, scope, expression: str):
    value = QQmlExpression(view.rootContext(), scope, expression).evaluate()[0]
    return value.toVariant() if hasattr(value, "toVariant") else value


def menu_texts(view, menu) -> list[str]:
    """Entries of a menu: action texts, submenu titles, "" for separators"""
    return evaluate(view, menu, "(function() { var texts = []; for (var i = 0; i < count; i++) {"
                                " var item = itemAt(i); texts.push(item && item.text ? item.text : '') } return texts })()")


def shown_slower_lap(viewer, laps):  # noqa: F811
    """Fast lap 2 (reference) & slower lap 3 shown: lap 3 loses time in both corners"""
    backend = viewer.backend
    backend.setReference(laps[1])
    check_only(viewer, [laps[1], laps[2]])
    wait(0.3)


# --- T1: synthesis band
def test_summary_built_from_coaching_and_sent_on_change_only(opener, laps):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    shown_slower_lap(dialog, laps)
    table = backend.cornerTable
    summary = table.summary
    assert summary["lapKey"] == laps[2] and summary["lap"] and summary["reference"]
    assert summary["tone"] == "loss" and summary["gap"].startswith("+") and summary["gap"].endswith(" s")
    assert summary["corners"] == table.coaching and summary["corners"]  # coaching rows, worst first
    assert table.lost_corners() == [tip["index"] for tip in table.coaching]
    sent = []
    table.summaryChanged.connect(lambda: sent.append(1))
    table.build_corners()  # same laps: same band, nothing sent
    assert sent == []
    check_only(dialog, [laps[1]])  # reference alone: no band texts
    assert table.summary == {} and sent == [1]


def test_band_corner_click_zooms_and_steps(opener, laps, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    shown_slower_lap(dialog, laps)
    chart = chart_of(view)
    band = named(view, "summaryBand")
    assert band.property("visible") and band.height() > 0
    corners = sorted(find(view, lambda item: item.objectName() == "summaryCorner" and item.property("visible")),
                     key=lambda item: item.property("index"))
    assert len(corners) == len(backend.cornerTable.coaching) >= 1
    first = backend.cornerTable.coaching[0]["index"]
    QMetaObject.invokeMethod(corners[0], "clicked")
    wait(0.5)
    assert chart.property("lostIndex") == 0 and chart.property("zoomed") and backend.selectedCorner == first
    assert named(view, "lostPosition").property("text") == f"1/{len(corners)}"
    # Shift+] / ] : next lost corner (wraps), plain ] stays "next corner"
    count = len(corners)
    key(view, Qt.Key.Key_BracketRight, Qt.KeyboardModifier.ShiftModifier)
    assert chart.property("lostIndex") == (1 % count)
    key(view, Qt.Key.Key_BraceLeft)
    assert chart.property("lostIndex") == 0
    key(view, Qt.Key.Key_BracketRight)  # all corners: lost corner indicator left as it was
    assert chart.property("lostIndex") == 0
    # Band keeps its height whether a lap is compared or not (charts never jump)
    height = band.height()
    check_only(dialog, [laps[1]])
    wait(0.3)
    assert band.height() == height and chart.property("lostIndex") == -1
    assert named(view, "bandAnalyze").property("visible")


# --- Guided analysis
def test_analyze_last_lap_opens_corners_on_worst_corner(opener, laps, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    backend.analyzeLastLap()
    wait_loaded(dialog)
    wait(0.6)
    chart = chart_of(view)
    shown = {lap.key for lap in backend.data.laps}
    assert shown == {laps[1], laps[3]}  # best lap 2 against newest lap 4
    assert backend.cornerTable.compareKey == laps[3]
    lost = backend.cornerTable.lost_corners()
    assert lost and backend.sideTab == 2 and backend.selectedCorner == lost[0]
    assert chart.property("lostIndex") == 0 and chart.property("zoomed")
    assert named(view, "lostPosition").property("text") == f"1/{len(lost)}"


def test_analyze_when_last_lap_is_best(opener, laps):  # noqa: F811
    from tests.test_lap_viewer_features import BASE, save

    newest = save(9, 69.0, BASE + 900)  # newest & fastest
    dialog = opener()
    backend = dialog.backend
    backend.refresh()
    wait_loaded(dialog)
    backend.analyzeLastLap()
    wait_loaded(dialog)
    assert backend.reference_key == newest and "best lap" in backend.status


# --- Corner detection moved into the corner tool's "⋯" popup
def test_corner_detection_in_more_popup(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(2)
    wait(0.5)
    sliders = find(view, lambda item: "Slider" in item.metaObject().className() and item.property("from") == 3.0)
    assert sliders == []  # not in the tool itself any more
    button = named(view, "cornerMore")
    assert button.property("tip") and button.property("fallback")
    QMetaObject.invokeMethod(button, "clicked")
    wait(0.4)
    sliders = find(view, lambda item: "Slider" in item.metaObject().className() and item.property("from") == 3.0)
    assert len(sliders) == 1 and sliders[0].property("value") == backend.cornerTable.hysteresis


# --- T2: Compare ▾ & checked laps menus, empty charts action
def test_compare_and_checked_laps_menus(opener):  # noqa: F811
    with no_qml_warnings():
        dialog = opener()
        view = dialog.view
        lap_list = named(view, "lapList")
        compare = named(view, "compareButton")
        assert compare.property("text") == "Compare Laps ▾"
        compare_menu = lap_list.findChild(QObject, "compareMenu")
        bulk_menu = lap_list.findChild(QObject, "bulkMenu")
        assert menu_texts(view, compare_menu) == [
            "Best vs Last Lap", "3 Best Laps", "5 Best Laps", "Best Lap in Similar Conditions",
            "Similar Track Temperature", "", "Analyze My Last Lap", "", "Uncheck All",
        ]
        assert menu_texts(view, bulk_menu) == [
            "Keep Checked Laps", "Stop Keeping Checked Laps", "Export Checked Laps (MoTeC)…", "",
            "Move Checked Laps to Trash…", "Recently Deleted Laps…",
        ]
        bulk = named(view, "bulkButton")
        assert bulk.property("tip") and bulk.property("fallback") == "⋯"
        QMetaObject.invokeMethod(compare, "clicked")
        wait(0.3)
        assert compare_menu.property("visible")
        QMetaObject.invokeMethod(compare, "clicked")  # second click closes it
        wait(0.3)
        assert not compare_menu.property("visible")


def test_empty_charts_offer_best_vs_last(opener, laps, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.reference_key = ""
    backend.checked = set()
    backend.load_laps()
    wait_loaded(dialog)
    wait(0.3)
    state = named(view, "chartState")
    assert state.property("empty") and state.property("actionText") == "Best vs Last Lap"
    QMetaObject.invokeMethod(state, "action")
    wait_loaded(dialog)
    assert {lap.key for lap in backend.data.laps} == {laps[1], laps[3]}


# --- Keys: B, L & R mean the same on map & charts, map actions with Shift
def test_map_leaves_b_l_r_to_charts(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    evaluate(view, chart, "setCursor(maxX / 3, 'key')")
    side_map = track_maps(view, False)[0]
    side_map.forceActiveFocus()
    wait(0.1)
    loop = chart.property("playLoop")
    key(view, Qt.Key.Key_L)  # charts: loop A-B
    assert chart.property("playLoop") is not loop and focused(view) is side_map
    key(view, Qt.Key.Key_B)  # charts: marker B at cursor
    assert evaluate(view, chart, "!isNaN(markerB)")
    quarters = backend._map_quarters
    key(view, Qt.Key.Key_R)  # charts (no highlighted lap: nothing), map not turned
    assert backend._map_quarters == quarters
    key(view, Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier)  # map turned
    assert backend._map_quarters == (quarters + 1) % 4
    before = evaluate(view, side_map, "pointShown('brake')")
    key(view, Qt.Key.Key_B, Qt.KeyboardModifier.ShiftModifier)  # map braking points
    assert evaluate(view, side_map, "pointShown('brake')") is not before


def test_keyboard_help_lists_new_keys():
    from neopedal.ui.quick import qml_path

    with open(qml_path("LapViewer.qml"), encoding="utf-8") as file:
        text = file.read()
    assert '["Shift+[ ]", ' in text and '["Shift+R", i18n.tr("Turn map")]' in text
    assert '["Shift+L", ' in text and '["Shift+B, C S O", ' in text
    assert '["R", i18n.tr("Turn map")]' not in text and '["L", i18n.tr("Lockups' not in text


# --- Share vs Export Data: every former export entry kept
def test_share_and_export_menus(opener):  # noqa: F811
    with no_qml_warnings():
        dialog = opener()
        view = dialog.view
        root = view.rootObject()
        share = menu_texts(view, root.findChild(QObject, "shareMenu"))
        export = menu_texts(view, root.findChild(QObject, "exportMenu"))
        assert share == ["Picture (PNG)…", "Copy Picture", "Picture of Passage A ↔ B…", "",
                         "Share Reference Lap…", "Corner Report…"]
        assert export == ["MoTeC i2 (.ld)", "MoTeC, Reference Lap A ↔ B…", "Reference Lap as Delta Best…", "",
                          "CSV, Displayed Laps…", "CSV, Displayed Laps on Time Base…", "CSV, Passage A ↔ B…",
                          "CSV, Visible Part…"]
        assert named(view, "shareButton").property("text") or named(view, "shareButton").property("tip")


# --- Lap list drawer on narrow pages, English & French
@pytest.mark.parametrize("language", ("English", "Français"))
def test_lap_list_drawer_below_narrow(laps, language):  # noqa: F811
    from neopedal.ui.lap_viewer import LapViewer

    dialog = None
    i18n.set_language(language)
    try:
        with no_qml_warnings():
            dialog = LapViewer(None)
            dialog.resize(1400, 800)
            wait_loaded(dialog)
            dialog.show()
            wait(0.4)
            view = dialog.view
            root = view.rootObject()
            lap_list = named(view, "lapList")
            assert not root.property("narrow") and lap_list.parentItem().objectName() != "lapDrawerSlot"
            minimum = dialog.page_minimum_size().width()
            dialog.resize(minimum, 700)
            wait(0.6)
            assert root.property("narrow")
            drawer = named(view, "lapDrawer")
            assert not drawer.property("visible")
            QMetaObject.invokeMethod(named(view, "lapsButton"), "clicked")
            wait(0.5)
            assert root.property("lapsOpen") and drawer.property("visible")
            assert lap_list.parentItem().parentItem() is drawer and lap_list.width() > 0
            # Charts & tools fit the page: nothing cut on the right
            body = find(view, lambda item: "SplitView" in item.metaObject().className())[0]
            widths = evaluate(view, body, "(function() { var widths = []; for (var i = 0; i < contentChildren.length; i++)"
                                          " if (contentChildren[i].visible) widths.push(contentChildren[i].width);"
                                          " return widths })()")
            assert len(widths) == 2 and all(width > 0 for width in widths)  # charts & tools, list in the drawer
            assert sum(widths) <= body.width() + 1
            key(view, Qt.Key.Key_Escape)  # Esc closes the drawer
            wait(0.5)
            assert not root.property("lapsOpen")
            dialog.resize(1400, 800)
            wait(0.5)
            assert not root.property("narrow") and lap_list.parentItem().parentItem() is not drawer
            dialog.close()
    finally:
        i18n.set_language("English")
        if dialog is not None and shiboken6.isValid(dialog):
            dialog.close()
        flush_deleted()
