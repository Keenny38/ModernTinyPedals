"""TpSearchField debounce: one search per pause in typing, Enter / Esc / clear applied at once"""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def find_search(root):
    stack = [root]
    while stack:
        item = stack.pop()
        if item.property("searchDelay") is not None:
            return item
        stack.extend(item.childItems())
    raise AssertionError("no TpSearchField")


def test_search_debounced_and_enter_flushes(ui_env):
    from tinypedal.ui.option_finder import OptionFinder

    page = OptionFinder(None)
    try:
        opened = []
        page.backend._open_option = opened.append
        searches = []
        page.backend.filterChanged.connect(lambda: searches.append(page.backend.searchText))
        page.show()
        page.activateWindow()
        search = find_search(page.view.rootObject())
        search.forceActiveFocus()
        QTest.keyClicks(page.view, "snap gap")
        QCoreApplication.processEvents()
        assert page.backend.searchText == ""  # still typing: nothing searched per key
        QTest.keyClick(page.view, Qt.Key.Key_Return)  # pending search applied before the page opens current
        assert searches == ["snap gap"]
        QTest.qWait(50)  # result list laid out
        QTest.keyClick(page.view, Qt.Key.Key_Return)
        assert opened and opened[0].key == "snap_gap" and searches == ["snap gap"]  # nothing pending: no search
        QTest.keyClicks(page.view, "x")
        QTest.qWait(300)
        assert searches == ["snap gap", "snap gapx"]  # applied after a pause
        QTest.keyClick(page.view, Qt.Key.Key_Escape)  # cleared at once
        assert searches[-1] == "" and search.property("text") == ""
    finally:
        page.close()
        page.deleteLater()
        flush()
