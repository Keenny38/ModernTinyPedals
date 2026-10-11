"""QML pages of QQuickWidget get an incubation controller: asynchronous loaders built over several event loop
passes (not at once), pages created & deleted while incubating never crash"""

import gc
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget

from neopedal.ui import quick
from neopedal.ui.quick import Incubator, create_quick_view

LOADER_READY, LOADER_LOADING = 1, 2

PAGE = """import QtQuick
Item {
    width: 200; height: 200
    property int asyncStatus: asyncLoader.status
    property int syncStatus: syncLoader.status
    property int built: asyncLoader.item ? asyncLoader.item.children.length : 0
    property string label: syncLoader.item ? syncLoader.item.text : ""
    Loader {
        id: asyncLoader
        asynchronous: true
        sourceComponent: Item { Repeater { model: 300; Rectangle { width: 2; height: 2 } } }
    }
    Loader {
        id: syncLoader
        sourceComponent: Text { text: i18n.tr("Incubation test text") }
    }
}
"""


@pytest.fixture
def page_folder(tmp_path, monkeypatch):
    (tmp_path / "AsyncTest.qml").write_text(PAGE, encoding="utf-8", newline="\n")
    monkeypatch.setattr(quick, "QML_FOLDER", str(tmp_path))
    return tmp_path


def delete(widget: QWidget):
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def test_async_loader_built_over_event_loop_passes(page_folder):
    parent = QWidget()
    view = create_quick_view(parent, "AsyncTest.qml", {}, samples=0)
    try:
        assert not view.errors()
        root = view.rootObject()
        incubator = view.findChild(Incubator)
        assert incubator is not None and view.engine().incubationController() is not None
        assert root.property("syncStatus") == LOADER_READY  # synchronous loaders unchanged
        assert root.property("asyncStatus") == LOADER_LOADING  # not built yet: asynchronous
        assert incubator.active
        passes = 0
        deadline = time.monotonic() + 10
        while root.property("asyncStatus") != LOADER_READY:
            QCoreApplication.processEvents()
            passes += 1
            assert time.monotonic() < deadline
        assert passes >= 1
        assert root.property("built") == 301  # Repeater & its 300 delegates
        assert root.property("label") == "Incubation test text"
        QCoreApplication.processEvents()
        assert not incubator.active  # timer stopped once nothing incubates
    finally:
        delete(parent)


def test_views_deleted_while_incubating_or_after(page_folder):
    for number in range(16):
        parent = QWidget()
        view = create_quick_view(parent, "AsyncTest.qml", {}, samples=0)
        root = view.rootObject()
        for _ in range(number % 4):  # deleted at different incubation stages
            QCoreApplication.processEvents()
        if number % 3 == 0:
            deadline = time.monotonic() + 10
            while root.property("asyncStatus") != LOADER_READY and time.monotonic() < deadline:
                QCoreApplication.processEvents()
        del root, view
        if number % 2:
            delete(parent)
        else:
            del parent  # no parent: freed at once
            gc.collect()
        QCoreApplication.processEvents()


def test_page_reloaded_keeps_incubating(page_folder):
    parent = QWidget()
    view = create_quick_view(parent, "AsyncTest.qml", {}, samples=0)
    try:
        quick.reload_in_language(view)
        root = view.rootObject()
        deadline = time.monotonic() + 10
        while root.property("asyncStatus") != LOADER_READY:
            QCoreApplication.processEvents()
            assert time.monotonic() < deadline
        assert len(view.findChildren(Incubator)) == 1
    finally:
        delete(parent)
