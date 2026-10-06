"""Settings page: rows in a ListView reusing delegates, navigation entries cached until state changes"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.setting import cfg


def test_categories_cached_until_state_changes(ui_env):
    from tinypedal.ui.quick.settings_backend import SettingsBackend

    class Host:
        pass

    backend = SettingsBackend(None, Host())
    try:
        first = backend.categories
        assert backend.categories is first  # same reads: built once
        backend.setSearch("port")
        searched = backend.categories
        assert searched is not first and any(entry["matches"] for entry in searched)
        backend.setSearch("")
        backend.selectCategory("web_dashboard")
        assert backend.categories is not searched
        key = backend.model.rows[1]["key"]
        assert backend.optionIndex(key) == 1 and backend.optionIndex("nothing/here") == -1
    finally:
        backend.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def window(ui_env, monkeypatch):
    from tinypedal import loader
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    monkeypatch.setattr(loader, "reload", lambda **kwargs: None)
    monkeypatch.setattr(loader, "restart", lambda *args, **kwargs: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            backend = getattr(page.dialog, "backend", None)
            if backend is not None and hasattr(backend, "discard"):
                backend.discard()
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def find_list(view):
    stack = [view.rootObject()]
    while stack:
        item = stack.pop()
        if item.metaObject().className().startswith("QQuickListView") and item.property("reuseItems"):
            return item
        stack.extend(item.childItems())
    raise AssertionError("no options list")


def rows_made(listing):
    return [item for item in listing.property("contentItem").childItems() if item.property("editorWidth") is not None]


def test_rows_reused_between_categories(window):
    from tinypedal.ui.menu import open_config_application

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        page = open_config_application(window, "application")
        QTest.qWait(50)
        listing = find_list(page.view)
        shown = page.backend.model.rowCount()
        made = {id(item) for item in rows_made(listing)}
        assert 0 < len(made) < shown  # rows of the part shown only
        page.backend.selectCategory("user_path")
        QTest.qWait(50)
        assert listing.property("contentY") == listing.property("originY")  # back to top
        page.backend.setSearch("a")  # most options of every category
        QTest.qWait(50)
        assert len(rows_made(listing)) < page.backend.model.rowCount()
        page.backend.setSearch("")
        page.backend.selectCategory("web_dashboard")
        QTest.qWait(50)
        header = listing.property("headerItem")
        assert header is not None and header.property("height") > 0  # status card above the rows
        page.backend.focus_option("application", "snap_distance")  # scrolled to & flashed
        QTest.qWait(150)
        rows = page.backend.model.rows
        index = next(number for number, row in enumerate(rows) if row["key"] == "application/snap_distance")
        item = next(item for item in rows_made(listing) if item.property("index") == index)
        top = item.property("y") - listing.property("contentY")
        assert 0 <= top < listing.property("height")
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages
