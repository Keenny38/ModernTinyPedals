"""Lap viewer lap list: delegates reused, sector times as fixed texts, tooltip texts made when hovered only"""

import time

from PySide6.QtCore import QCoreApplication, qInstallMessageHandler

from tests.test_lap_viewer_fix_list import page, sessions  # noqa: F401  # fixtures


def settle(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def everything(root):
    stack, found = [root], []
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found


def test_lap_rows_reused_with_sector_texts(page, sessions):  # noqa: F811
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import create_quick_view

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    parent = QWidget()
    try:
        view = create_quick_view(parent, "LapViewer.qml", {"backend": page})
        parent.resize(1300, 800)
        view.resize(1300, 800)
        parent.show()
        settle()
        listing = next(item for item in everything(view.rootObject()) if item.property("model") is page.lap_model)
        assert listing.property("reuseItems")
        session = next(row["session"] for row in page.lap_model.rows if row["kind"] == "session" and not row["open"])
        page.toggleSession(session)  # laps of session shown
        settle()
        lap = next(row for row in page.lap_model.rows if row["kind"] != "session")
        delegate = next(item for item in listing.property("contentItem").childItems()
                        if item.property("path") == lap["path"])
        sectors = sorted((item for item in everything(delegate) if item.property("sector") is not None),
                         key=lambda item: item.property("sector"))
        assert [item.property("text") for item in sectors] == [lap["s1"], lap["s2"], lap["s3"]]
        tips = [item for item in everything(delegate) if item.metaObject().className().startswith("QQuickMouseArea")]
        assert tips  # tooltip texts are empty until hovered: nothing translated per row
        page.toggleSession(session)  # collapsed: lap rows pooled, opacity back for reuse
        settle()
        page.toggleSession(session)
        settle()
        rows = [item for item in listing.property("contentItem").childItems()
                if item.property("kind") is not None and item.property("visible")]
        assert rows and all(item.property("opacity") == 1 for item in rows)
    finally:
        qInstallMessageHandler(previous)
        parent.deleteLater()
        QCoreApplication.processEvents()
    assert not [text for text in messages if ".qml" in text], messages
