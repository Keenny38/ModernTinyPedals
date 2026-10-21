"""Audit I lot G1: TpMenu measured once per batch of items, tyre tab menus built when opened (one row menu),
RaceSection animating only folding, TpToolbar measuring with one probe, Recent menus checking network paths in
background"""

import os
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtQml import QQmlEngine, QQmlExpression

from neopedal.setting import cfg
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import named, opener, wait, warnings  # noqa: F401
from tests.test_race_calculator import host, page  # noqa: F401 (fixtures)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def settle(rounds: int = 5):
    for _ in range(rounds):
        QCoreApplication.processEvents()


def inside(item, expression: str):
    """Expression evaluated in the QML file context of item (ids of that file)"""
    run = QQmlExpression(QQmlEngine.contextForObject(item), item, expression)
    value, _undefined = run.evaluate()
    assert not run.hasError(), f"{expression}: {run.error().toString()}"
    return value


def inner(item, expression: str):
    """Expression evaluated in the context of the QML file of item itself (its own ids): context of its first
    child item (item's own context is the file that declared it)"""
    return inside(item.childItems()[0], expression)


def visual_items(root) -> list:
    found = []
    for item in root.childItems():
        found.append(item)
        found.extend(visual_items(item))
    return found


def find_class(root, prefix: str) -> list:
    """Objects (QObject children) & items (visual tree: repeater delegates) of a QML type"""
    objects = {id(item): item for item in root.findChildren(QObject)}
    objects.update((id(item), item) for item in visual_items(root))
    return [item for item in objects.values() if item.metaObject().className().startswith(prefix)]


def as_list(value) -> list:
    return list(value.toVariant() if hasattr(value, "toVariant") else value)


@pytest.fixture
def component(ui_env, tmp_path):
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui.quick import PageState, Theme, Translator, qml_folder_imports, register_types, theme_copy

    register_types()
    views = []

    def loading(body: str, width: int = 600, height: int = 300):
        wrapper = tmp_path / f"wrapper{len(views)}.qml"
        wrapper.write_text(f"import QtQuick\nimport QtQuick.Controls.Basic\nimport QtQuick.Layouts\n"
                           f"import QtQml.Models\n{qml_folder_imports()}\n{body}\n", encoding="utf-8")
        view = QQuickWidget()
        views.append(view)
        view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        context = view.rootContext()
        context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
        context.setContextProperty("i18n", Translator(view))
        context.setContextProperty("pageState", PageState(view))
        view.setSource(QUrl.fromLocalFile(str(wrapper)))
        assert not view.errors(), [error.toString() for error in view.errors()]
        view.resize(width, height)
        view.move(-6000, -6000)
        view.show()
        settle()
        return view

    yield loading
    for view in views:
        view.close()
        view.setSource(QUrl())
        view.deleteLater()
    flush()


# --- TpMenu: widest item measured once per batch of inserts, kept right while closed
MENU = '''Item {
    id: root
    property var names: []
    property int shown: 0
    property alias menu: menu
    TpMenu {
        id: menu
        objectName: "menu"
        onAboutToShow: root.shown += 1  // handler of the user too (TpMenu has its own)
        Instantiator {
            model: root.names
            delegate: TpMenuItem { required property var modelData; text: modelData }
            onObjectAdded: function(index, object) { menu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { menu.removeItem(object) }
        }
        TpMenuItem { objectName: "last"; text: "Last" }
    }
}'''


def widest(menu) -> float:
    return max(inside(menu, f"menu.itemAt({index}).implicitWidth") for index in range(menu.property("count")))


def test_menu_measured_once_per_batch(component):
    view = component(MENU)
    root = view.rootObject()
    menu = root.findChild(QObject, "menu")
    start = menu.property("measureSerial")
    root.setProperty("names", [f"Tyre #{index}" for index in range(60)] + ["A much longer tyre name than the others"])
    assert menu.property("count") == 62
    settle()
    assert menu.property("measureSerial") - start == 1  # 61 inserts, measured once
    assert menu.property("widestItem") == widest(menu)
    assert menu.property("implicitWidth") >= widest(menu)  # right while closed: right-aligned popups use it
    long_width = menu.property("widestItem")
    root.setProperty("names", ["A", "B"])  # same items count again later: measured again (not by count)
    settle()
    assert menu.property("widestItem") == widest(menu) < long_width
    last = root.findChild(QObject, "last")
    last.setProperty("text", "Last entry now far longer than every other entry of the menu")
    assert menu.property("widestItem") == widest(menu) == last.property("implicitWidth")  # item width followed


def test_menu_measured_when_opened(component):
    view = component(MENU)
    root = view.rootObject()
    menu = root.findChild(QObject, "menu")
    root.setProperty("names", ["Short", "An entry wider than the minimum menu width of thirteen em"])
    start = menu.property("measureSerial")
    inside(menu, "menu.popup(root, 0, 0)")  # items added just before: measured at once, not after
    assert menu.property("measureSerial") > start and menu.property("widestItem") == widest(menu)
    assert root.property("shown") == 1
    inside(menu, "menu.close()")
    settle()


# --- RaceSection: content height followed at once, folding animated
SECTION = '''Item {
    id: root
    property alias section: section
    property alias block: block
    width: 400
    QtObject { id: store; property var inputs: ({}); property var header: ({ collapsed: [] }) }
    function fold(on) { store.header = { collapsed: on ? ["demo"] : [] } }
    RaceSection {
        id: section
        objectName: "section"
        width: 400
        store: store
        name: "demo"
        title: "Demo"
        Rectangle { id: block; objectName: "block"; Layout.fillWidth: true; implicitHeight: 40 }
    }
}'''


def test_section_follows_content_then_animates_folding(component):
    view = component(SECTION)
    root = view.rootObject()
    section = root.findChild(QObject, "section")
    block = root.findChild(QObject, "block")
    unfolded = section.property("implicitHeight")
    body = inner(section, "body.implicitHeight")
    block.setProperty("implicitHeight", 140)  # content grew (wrap on resize, rows added): no lag
    deadline = time.monotonic() + 2
    while inner(section, "body.implicitHeight") < body + 100 and time.monotonic() < deadline:
        settle(1)
        time.sleep(0.005)
    # Same moment the body grew: section as tall (an animated height would still be at its old value)
    assert section.property("implicitHeight") == pytest.approx(unfolded + 100)
    assert section.property("openness") == 1
    unfolded += 100
    inside(root, "root.fold(true)")
    if inside(section, "theme.motionBase") > 0:
        assert section.property("implicitHeight") > unfolded / 2  # folding animated
    deadline = time.monotonic() + 3
    while section.property("openness") > 0 and time.monotonic() < deadline:
        settle(1)
        time.sleep(0.01)
    folded = section.property("implicitHeight")
    assert folded < unfolded
    block.setProperty("implicitHeight", 300)  # folded: content height ignored
    assert section.property("implicitHeight") == folded


# --- TpToolbar: one probe, widths of the shown buttons
TOOLBAR = '''Item {
    id: root
    property alias bar: bar
    property string label: "Export"
    property bool liveShown: true
    RowLayout {
        anchors.fill: parent
        TpToolbar {
            id: bar
            objectName: "bar"
            Layout.fillWidth: true
            TpAction { name: "imp"; text: "Import laps"; glyph: "\\uE8B5"; fallback: "+"; priority: 2 }
            TpAction { name: "exp"; text: root.label; glyph: "\\uEDE1"; priority: 1 }
            TpAction { name: "live"; text: "Live"; glyph: "\\uE768"; checkable: true; priority: 0; shown: root.liveShown }
            TpAction { name: "save"; text: "Save replay"; glyph: "\\uE74E"; accent: true; priority: 3 }
            TpAction { name: "tip"; tip: "Settings only"; glyph: "\\uE713"; fallback: "S"; priority: 4 }
        }
    }
}'''


def toolbar_buttons(bar) -> dict:
    return {item.objectName(): item for item in find_class(bar, "TpButton") if item.objectName()}


def check_widths(bar):
    modes = list(bar.property("modes").toVariant()) if hasattr(bar.property("modes"), "toVariant") \
        else list(bar.property("modes"))
    full = bar.property("fullWidths")
    icon = bar.property("iconWidths")
    full = list(full.toVariant()) if hasattr(full, "toVariant") else list(full)
    icon = list(icon.toVariant()) if hasattr(icon, "toVariant") else list(icon)
    buttons = toolbar_buttons(bar)
    names = ["imp", "exp", "live", "save", "tip"]
    for index, name in enumerate(names):
        if modes[index] == 2 or not buttons[name].property("visible"):
            continue
        expected = full[index] if modes[index] == 0 else icon[index]
        assert buttons[name].property("implicitWidth") == pytest.approx(expected), (name, modes)
    return modes


def test_toolbar_widths_match_buttons(component):
    view = component(TOOLBAR, width=1400, height=60)
    root = view.rootObject()
    bar = root.findChild(QObject, "bar")
    # One hidden probe: 5 shown buttons + "⋯" + probe (was 3 buttons per action)
    assert len(find_class(bar, "TpButton")) == 5 + 2
    assert check_widths(bar) == [0, 0, 0, 0, 0]
    full = bar.property("fullWidth")
    for width in (round(full * 0.8), round(full * 0.5), round(full * 0.25), 1400):
        view.resize(width, 60)
        settle()
        check_widths(bar)
    assert check_widths(bar) == [0, 0, 0, 0, 0]
    root.setProperty("label", "Export every lap of the session")  # text changed: measured again once
    settle()
    assert check_widths(bar) == [0, 0, 0, 0, 0] and bar.property("fullWidth") > full
    wider = bar.property("fullWidth")
    root.setProperty("liveShown", False)  # action hidden: row fitted again
    settle()
    assert bar.property("fullWidth") < wider


@pytest.mark.parametrize("language", ["English", "Français"])
def test_lap_toolbar_measured_by_probe(opener, warnings, language):  # noqa: F811
    """Lap viewer toolbar (window minimum width to wide): shown buttons as wide as measured, row inside the
    toolbar once anything went into the menu"""
    from neopedal import i18n

    i18n.set_language(language)
    try:
        dialog = opener()
        toolbar = named(dialog.view, "lapToolbar")
        for width in (dialog.minimumWidth(), 900, 1300, 2200):
            dialog.resize(width, 800)
            wait(0.3)
            modes = as_list(toolbar.property("modes"))
            full = as_list(toolbar.property("fullWidths"))
            icon = as_list(toolbar.property("iconWidths"))
            assert len(full) == len(icon) == len(modes) and all(value > 0 for value in full)
            row = next(item for item in toolbar.childItems() if item.metaObject().className() == "QQuickRow")
            buttons = [item for item in row.childItems() if item.metaObject().className().startswith("TpButton")
                       and item.objectName() != "toolbarMore"]
            assert len(buttons) == len(modes)
            for index, button in enumerate(buttons):  # shown buttons exactly as wide as measured
                if button.property("visible"):
                    expected = full[index] if modes[index] == 0 else icon[index]
                    assert button.property("implicitWidth") == pytest.approx(expected), (width, index, modes)
            if 2 in modes:
                assert row.property("width") <= toolbar.property("width") + 0.5, (width, modes)
    finally:
        i18n.set_language("English")


# --- Tyre tab: stock menu built when opened, one row menu for every row
def tyre_tab(page):  # noqa: F811
    view = page.ensure_view()
    page.backend.setTab(1)
    settle()
    tabs = find_class(view.rootObject(), "RaceTyreTab")
    assert tabs and not view.errors(), [error.toString() for error in view.errors()]
    return tabs[0]


def test_tyre_menus_built_when_opened(page, host):  # noqa: F811
    backend = page.backend
    for _ in range(6):
        backend.addTyre()
    backend.addRow()
    backend.addRow()
    tab = tyre_tab(page)
    assert inner(tab, "wheelMenu.count") == 2  # closed: separator & Remove Tyre only
    menus = len(find_class(tab, "TpMenu"))
    backend.addRow()  # plan changed: no tyre items made while closed, no menu per row
    settle()
    assert inner(tab, "wheelMenu.count") == 2 and len(find_class(tab, "TpMenu")) == menus
    cells = find_class(tab, "RaceTyreCell")
    assert len(cells) == 4 * 4
    cell = next(item for item in cells if item.property("row") == 1 and item.property("corner") == 2)
    inner(tab, "wheelMenu").setProperty("current", "")
    run = QQmlExpression(QQmlEngine.contextForObject(tab.childItems()[0]), cell, "wheelMenu.openFor(this)")
    run.evaluate()
    assert not run.hasError(), run.error().toString()
    assert inner(tab, "wheelMenu.count") == 6 + 2
    assert inner(tab, "wheelMenu.visible")
    texts = [inner(tab, f"wheelMenu.itemAt({index}).text") for index in range(6)]
    assert texts == [f"Medium #{index}" for index in range(1, 7)]
    inner(tab, "wheelMenu.itemAt(2).triggered()")  # picked: tyre on the wheel of the cell
    inner(tab, "wheelMenu.close()")
    assert backend.tyres.rows[1][2] == "Medium #3"
    deadline = time.monotonic() + 2
    while inner(tab, "wheelMenu.visible") and time.monotonic() < deadline:
        settle(1)
        time.sleep(0.01)
    settle()
    assert inner(tab, "wheelMenu.count") == 2  # closed: tyre items freed


def test_one_row_menu_for_every_row(page, host):  # noqa: F811
    backend = page.backend
    backend.addTyre()
    backend.assignTyre(0, 0, "Medium #1")
    backend.addRow()
    backend.addRow()
    tab = tyre_tab(page)
    assert backend.tyrePlan["linked"] is False and len(backend.tyres.rows) == 3
    buttons = [item for item in find_class(tab, "TpButton") if item.property("tip") == "Row"]
    assert len(buttons) == 3
    assert len(find_class(tab, "TpMenu")) == len({id(menu) for menu in find_class(tab, "TpMenu")})
    run = QQmlExpression(QQmlEngine.contextForObject(tab.childItems()[0]), buttons[0], "planRowMenu.openFor(this, 0)")
    run.evaluate()
    assert not run.hasError(), run.error().toString()
    assert inner(tab, "planRowMenu.visible") and buttons[0].property("checked")
    assert not buttons[1].property("checked")
    duplicate = next(index for index in range(inner(tab, "planRowMenu.count"))
                     if inner(tab, f"planRowMenu.itemAt({index}).text") == "Duplicate Row")
    inner(tab, f"planRowMenu.itemAt({duplicate}).triggered()")
    assert len(backend.tyres.rows) == 4 and backend.tyres.rows[1][0] == "Medium #1"
    inner(tab, "planRowMenu.close()")
    settle()


# --- Recent menus: network paths never checked on the UI thread
def wait_jobs(backend, seconds: float = 5.0):
    deadline = time.monotonic() + seconds
    while backend.jobs.running and time.monotonic() < deadline:
        settle(1)
        time.sleep(0.01)
    settle()


def test_recent_network_paths_checked_in_background(page, host, tmp_path, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_backend
    from neopedal.ui.quick.race_backend import RaceBackend

    local = tmp_path / "local.race-plan"
    local.write_text("{}", encoding="utf-8")
    gone_local = (tmp_path / "gone.race-plan").as_posix()
    shared = "//server/share/kept.race-plan"
    gone_shared = "//server/share/gone.race-plan"
    cfg.user.config["fuel_calculator"]["recent_race_plan_file_names"] = "|".join(
        (shared, local.as_posix(), gone_shared, gone_local))
    checked: list[tuple[str, bool]] = []
    main = threading.current_thread()
    real_isfile = os.path.isfile

    def isfile(path):
        checked.append((path, threading.current_thread() is main))
        return path == shared or real_isfile(path)

    monkeypatch.setattr(race_backend.os.path, "isfile", isfile)
    backend = RaceBackend(page, page)
    try:
        # Local ones checked at once, network ones kept until checked on a worker thread
        assert backend.recentFiles["race_plan"] == [
            {"path": path, "name": os.path.basename(path)} for path in (shared, local.as_posix(), gone_shared)]
        wait_jobs(backend)
        assert all(not on_main for path, on_main in checked if race_backend.network_path(path))
        assert {path for path, _on_main in checked} >= {shared, gone_shared}
        assert [item["path"] for item in backend.recentFiles["race_plan"]] == [shared, local.as_posix()]
        assert cfg.user.config["fuel_calculator"]["recent_race_plan_file_names"] == f"{shared}|{local.as_posix()}"
        # Menu opened: checked again in background, never on the UI thread
        checked.clear()
        backend.refreshRecent()
        assert all(not on_main for path, on_main in checked if race_backend.network_path(path))
        wait_jobs(backend)
        assert any(path == shared for path, _on_main in checked)
    finally:
        backend.release()


def test_recent_network_check_dropped_when_file_saved_meanwhile(page, host, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_files

    backend = page.backend
    shared = "//server/share/plan.race-plan"
    backend.keep_recent("race_plan", [shared])
    release = threading.Event()

    def slow_missing(serial, paths):
        release.wait(5)
        return serial, set(paths)  # "missing" when the check started

    monkeypatch.setattr(race_files, "missing_files_of", slow_missing)
    backend.check_network_recent()
    backend.remember_recent("race_plan", "//server/share/other.race-plan")  # saved meanwhile
    release.set()
    wait_jobs(backend)
    assert shared in [item["path"] for item in backend.recentFiles["race_plan"]]  # stale check dropped
    assert race_files.network_path("\\\\server\\share\\a.race-plan") and not race_files.network_path("C:/a")


def test_page_loads_without_errors_after_changes(page, host):  # noqa: F811
    """Race calculator page: every tab built without QML errors or warnings of the changed files"""
    view = page.ensure_view()
    for tab in range(4):
        page.backend.setTab(tab)
        settle()
    assert not view.errors(), [error.toString() for error in view.errors()]
