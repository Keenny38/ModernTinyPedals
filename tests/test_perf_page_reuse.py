"""Pages whose lists recycle delegates (reuseItems): rows show their own values after scrolling, no QML warning,
Overlays page tells rows on screen to its backend (their previews rendered first)"""

import json
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QColor, QImage

from neopedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def pump(seconds: float = 0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


@pytest.fixture
def qml_messages():
    messages = []

    def handler(mode, context, message):
        if mode != QtMsgType.QtDebugMsg:
            messages.append(message)

    previous = qInstallMessageHandler(handler)
    yield messages
    qInstallMessageHandler(previous)


def find_view(view, class_prefix: str):
    stack = [view.rootObject()]
    while stack:
        item = stack.pop()
        if item.metaObject().className().startswith(class_prefix):
            return item
        stack.extend(item.childItems())
    raise AssertionError(f"no {class_prefix} in page")


def delegates(list_view) -> list:
    """Delegates shown (pooled ones flagged recycling)"""
    content = list_view.property("contentItem")
    return [item for item in content.childItems()
            if item.property("index") is not None and item.property("recycling") is False]


def pooled(list_view) -> int:
    content = list_view.property("contentItem")
    return sum(item.property("recycling") is True for item in content.childItems())


def scroll(list_view, to_end: bool):
    end = max(list_view.property("contentHeight") - list_view.property("height"), 0)
    list_view.setProperty("contentY", list_view.property("originY") + (end if to_end else 0))
    pump(0.3)


def check_rows(list_view, model, role: str, key: str):
    """Each shown delegate shows the row of its index (nothing left from a recycled row)"""
    names = model.roleNames()
    role_id = next(number for number, name in names.items() if bytes(name.data()).decode() == role)
    shown = delegates(list_view)
    assert shown
    for item in shown:
        index = item.property("index")
        assert item.property(key) == model.data(model.index(index, 0), role_id), (index, item.property(key))


def test_overlays_grid_reuses_cards(ui_env, monkeypatch, qml_messages):
    from neopedal.ui.overlay_view import OverlayView
    from neopedal.ui.quick import overlay_backend

    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(QColor("#336699"))
    monkeypatch.setattr(overlay_backend, "render_preview", lambda name: image)
    view = OverlayView(None)
    view.resize(900, 640)
    view.show()
    try:
        pump(0.5)
        grid = find_view(view.view, "QQuickGridView")
        assert grid.property("reuseItems")
        backend = view.backend
        assert backend.previews._visible  # rows on screen told
        top = set(backend.previews._visible)
        created = len(grid.property("contentItem").childItems())
        scroll(grid, to_end=True)
        assert pooled(grid) and len(grid.property("contentItem").childItems()) == created  # cards reused
        check_rows(grid, backend.proxy, "name", "name")
        bottom = set(backend.previews._visible)
        assert bottom and bottom != top
        last = backend.proxy.data(backend.proxy.index(backend.proxy.rowCount() - 1, 0), overlay_backend.OverlayModel.NameRole)
        assert last in bottom
        scroll(grid, to_end=False)
        check_rows(grid, backend.proxy, "name", "name")
        backend.setGridView(False)  # compact rows
        pump(0.3)
        scroll(grid, to_end=True)
        check_rows(grid, backend.proxy, "name", "name")
        assert not [text for text in qml_messages if "qml" in text.lower()], qml_messages
    finally:
        cfg.application["show_overlay_previews"] = True
        view.close()
        view.deleteLater()
        flush()


def test_presets_list_reuses_rows(ui_env, monkeypatch, qml_messages):
    from neopedal.ui import preset_view

    for number in range(40):
        with open(f"{cfg.path.settings}preset {number:02d}.json", "w", encoding="utf-8") as file:
            json.dump({"speedometer": {"enable": number % 2 == 0}}, file)
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    page = preset_view.PresetList(None)
    page.resize(1000, 600)
    page.show()
    try:
        deadline = time.monotonic() + 10
        while page.backend.reading and time.monotonic() < deadline:
            pump(0.05)
        pump(0.3)
        rows = find_view(page.view, "QQuickListView")
        assert rows.property("reuseItems")
        scroll(rows, to_end=True)
        check_rows(rows, page.backend.model, "key", "key")
        check_rows(rows, page.backend.model, "contentText", "contentText")
        scroll(rows, to_end=False)
        check_rows(rows, page.backend.model, "key", "key")
        assert not [text for text in qml_messages if "qml" in text.lower()], qml_messages
    finally:
        page.close()
        page.deleteLater()
        flush()


def test_spectate_list_reuses_rows(ui_env, monkeypatch, qml_messages):
    from test_spectate_page import Reader

    from neopedal import realtime_state
    from neopedal.ui.spectate_view import SpectateList

    monkeypatch.setattr(realtime_state, "paused", False)
    cars = [(f"Driver {number:02d}", f"Car {number % 5}", f"Class {number % 3}", number + 1, 100 + number)
            for number in range(40)]
    reader = Reader(cars)
    page = SpectateList(None)
    page.backend._reader = lambda: reader
    page.resize(900, 600)
    page.show()
    try:
        pump(0.5)
        rows = find_view(page.view, "QQuickListView")
        assert rows.property("reuseItems")
        scroll(rows, to_end=True)
        assert pooled(rows)  # rows reused
        check_rows(rows, page.backend.model, "name", "name")
        scroll(rows, to_end=False)
        check_rows(rows, page.backend.model, "name", "name")
        assert len(page.backend.class_model.rows) == 3
        assert not [text for text in qml_messages if "qml" in text.lower()], qml_messages
    finally:
        page.close()
        page.deleteLater()
        flush()


def test_modules_grid_reuses_cards(ui_env, qml_messages):
    from neopedal.module_control import mctrl, wctrl
    from neopedal.ui.module_view import ModuleList

    page = ModuleList(None, mctrl, wctrl)
    page.resize(700, 420)
    page.show()
    try:
        pump(0.5)
        grid = find_view(page.view, "QQuickGridView")
        assert grid.property("reuseItems")
        scroll(grid, to_end=True)
        check_rows(grid, page.backend.rows_model, "key", "key")
        scroll(grid, to_end=False)
        check_rows(grid, page.backend.rows_model, "key", "key")
        assert not [text for text in qml_messages if "qml" in text.lower()], qml_messages
    finally:
        page.close()
        page.deleteLater()
        flush()
