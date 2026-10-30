"""Audit I lot D2: Overlays page (screenshot decoded & scaled in background, refresh deferred while hidden, screen
view idle while hidden, live preview asynchronous), positions chart asking the place table once per lap, notification
center model, toolbar fitted once per resize, Presets page listing folders only when they changed, preset file lock &
trash lock never blocking the UI for long, Overlay Options search counting each overlay once"""

import os
import threading
import time

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, QSize
from PySide6.QtGui import QImage

from neopedal.setting import cfg
from neopedal.ui.quick import overlay_backend
from neopedal.ui.quick.overlay_backend import VIEW_CARDS, VIEW_SCREEN, OverlayBackend
from tests.test_audit_i_g1 import as_list, component  # noqa: F401  (fixture)
from tests.test_overlay_options import options, rows  # noqa: F401  (fixture)
from tests.test_overlays_page_more import NAMES, FakeControl, settle, solid
from tests.test_perf_charts import FakeResults, chart_view, positions_data  # noqa: F401  (fixture)
from tests.test_preset_management import Host, presets  # noqa: F401  (fixture)
from tests.test_ui_audit_2026_10_29_overlays import children, control, overlays_page  # noqa: F401  (fixtures)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def wait_jobs(backend, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while backend.jobs.running and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert not backend.jobs.running


# --- PERF-010: screenshot under the screen view decoded off the UI thread, kept at most 1920 px wide
def test_read_background_scales_down_and_keeps_screen_size(tmp_path):
    big = tmp_path / "4k.png"
    QImage(3840, 2160, QImage.Format.Format_RGB32).save(str(big))
    size, image = overlay_backend.read_background(str(big))
    assert size == QSize(3840, 2160) and image.size() == QSize(1920, 1080)  # screen told by the real size
    small = tmp_path / "hd.jpg"
    QImage(1280, 720, QImage.Format.Format_RGB32).save(str(small))
    size, image = overlay_backend.read_background(str(small))
    assert size == QSize(1280, 720) and image.size() == QSize(1280, 720)  # never scaled up
    size, image = overlay_backend.read_background(str(tmp_path / "missing.png"))
    assert image.isNull()
    assert overlay_backend.shrink_background(solid("#000", 4000, 1000)).size() == QSize(1920, 480)


def test_background_loaded_in_background_and_capture_shrunk(control, tmp_path, monkeypatch):  # noqa: F811
    picture = tmp_path / "shot.png"
    QImage(3840, 2160, QImage.Format.Format_RGB32).save(str(picture))
    main = threading.get_ident()
    decoded = []
    real_read = overlay_backend.read_background

    def read(filename, max_width=overlay_backend.BACKGROUND_MAX_WIDTH):
        decoded.append(threading.get_ident())
        return real_read(filename, max_width)

    monkeypatch.setattr(overlay_backend, "read_background", read)
    monkeypatch.setattr(overlay_backend, "screen_scales", lambda: [(QRect(0, 0, 3840, 2160), 1.0)])
    monkeypatch.setattr(overlay_backend, "screen_rects", lambda: [("Main", QRect(0, 0, 3840, 2160), True)])
    page = OverlayBackend(None, control, lambda name: None, lambda text: True,
                          capture_screen=lambda name: solid("#112233", 3840, 2160),
                          pick_screenshot=lambda: str(picture))
    try:
        told = []
        page.backgroundChanged.connect(lambda: told.append(1))
        page.loadBackground()
        assert told == [] and page.background == {}  # UI thread never decoded the file
        wait_jobs(page)
        assert told == [1] and decoded and decoded[0] != main
        assert (page.background["w"], page.background["h"]) == (3840, 2160)  # placed on the 4K screen
        stored = overlay_backend.STORE.get(f"{page.previews.prefix}#background")
        assert stored is not None and stored.width() == 1920  # store keeps the small picture only
        page.captureBackground("Main")
        wait_jobs(page)
        assert told == [1, 1]
        stored = overlay_backend.STORE.get(f"{page.previews.prefix}#background")
        assert stored is not None and stored.size() == QSize(1920, 1080)
        page._pick_screenshot = lambda: str(tmp_path / "missing.png")
        notices = []
        page.notice.connect(notices.append)
        page.loadBackground()
        wait_jobs(page)
        assert notices == ["Unable to load image."]
    finally:
        page.close()
        page.deleteLater()
        flush()


# --- PERF-047: refresh of the hidden Overlays page: rows follow at once, the rest once shown again
def test_refresh_while_hidden_defers_counts_filters_and_screen(ui_env, monkeypatch):
    for name in NAMES:
        cfg.user.setting[name]["enable"] = name in ("brake_temperature", "speedometer")
    monkeypatch.setattr(overlay_backend, "render_preview", lambda name: solid("#336699"))
    monkeypatch.setattr(overlay_backend, "make_live_preview", lambda name: None)
    monkeypatch.setattr(overlay_backend, "screen_rects", lambda: [("Main", QRect(0, 0, 1920, 1080), True)])
    fake = FakeControl(NAMES)
    page = OverlayBackend(None, fake, lambda name: None, lambda text: True)
    try:
        # Never shown: everything follows at once (counts read by whoever builds the page)
        cfg.user.setting["fuel"]["enable"] = True
        page.refresh()
        assert page.activeCount == 3
        page.set_active(True)
        page.set_active(False)
        counts, locks, presets_told = [], [], []
        page.countsChanged.connect(lambda: counts.append(1))
        page.lockChanged.connect(lambda: locks.append(1))
        page.presetChanged.connect(lambda: presets_told.append(1))
        cfg.user.setting["fuel"]["enable"] = False  # hotkey while racing
        monkeypatch.setitem(cfg.overlay, "fixed_position", True)
        monkeypatch.setattr(cfg.filename, "setting", "other.json")
        for _ in range(3):
            page.refresh()
        row = page.source.rows[page.source.index_of["fuel"]]
        assert not row.enabled  # row right at once
        assert page.activeCount == 3 and not counts and not locks and not presets_told  # page work waits
        page.set_active(True)
        assert page.activeCount == 2 and counts == [1] and locks == [1] and presets_told == [1]  # once
        assert page.positionsLocked and page.presetName == "other"
    finally:
        page.close()
        page.deleteLater()
        flush()


# --- PERF-038 & BUG-054: screen view idle while another view is shown, followed again once shown
def test_screen_view_follows_only_while_visible(overlays_page, control):  # noqa: F811
    quick = overlays_page.view
    backend = overlays_page.backend
    backend.setViewMode(VIEW_SCREEN)
    settle()
    view = quick.rootObject().findChild(QObject, "screenView")
    assert view is not None and view.property("visible")
    assert len(as_list(view.property("shownOverlays"))) == 2
    background = quick.rootObject().findChild(QObject, "screenBackground")
    backend._set_background(solid("#112233", 64, 36), QRect(0, 0, 1920, 1080))
    settle()
    assert background.property("source").toString().startswith("image://")
    backend.setViewMode(VIEW_CARDS)
    settle()
    assert not view.property("visible")
    assert background.property("source").toString() == ""  # texture released while hidden
    cfg.user.setting["fuel"]["enable"] = True  # one more overlay running: layout changes
    control.widgets["fuel"].rect = QRect(300, 300, 100, 50)
    backend.update_overlay("fuel")
    backend._update_screen()
    backend.screenChanged.emit()
    settle()
    assert len(as_list(view.property("shownOverlays"))) == 2  # hidden view left alone
    backend.setViewMode(VIEW_SCREEN)
    settle()
    assert len(as_list(view.property("shownOverlays"))) == 3  # followed once shown
    assert background.property("source").toString().startswith("image://")
    cfg.user.setting["fuel"]["enable"] = False


# --- PERF-063: live preview read on the image thread
def test_live_preview_image_is_asynchronous():
    with open(os.path.join("neopedal", "ui", "qml", "overlays", "OverlayCard.qml"), encoding="utf-8") as file:
        text = file.read()
    live = text[text.index("id: live"):]
    live = live[:live.index("}")]
    assert "asynchronous: true" in live and "retainWhileLoading: true" in live


# --- PERF-039: positions chart asks the place table once per lap under the mouse
def test_positions_places_asked_once_per_lap(chart_view):  # noqa: F811
    make, _ = chart_view

    class Counting(FakeResults):
        def __init__(self, positions):
            super().__init__(positions)
            self.asked = []

        def placesAt(self, lap):
            self.asked.append(lap)
            return super().placesAt(lap)

    backend = Counting(positions_data())
    view = make("ResultsPositions { }", backend)
    settle(10)
    chart = view.rootObject()
    plot_x = chart.property("plotX")
    plot_width = chart.property("plotWidth")
    laps = chart.property("laps")
    lap_width = plot_width / laps
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    def nearest(x, y):
        # Context of the chart's own file (its ids): the one of its first child item
        run = QQmlExpression(QQmlEngine.contextForObject(chart.childItems()[0]), chart, f"chart.nearest({x}, {y})")
        value, _ = run.evaluate()
        assert not run.hasError(), run.error().toString()
        return value

    x = plot_x + lap_width * 10
    for y in (40, 60, 80, 100):  # mouse moving on the same lap
        nearest(x, y)
    assert backend.asked == [10]
    nearest(x + lap_width * 5, 60)
    assert backend.asked == [10, 15]
    nearest(x, 60)  # back: asked again (one lap kept)
    assert backend.asked == [10, 15, 10]
    backend._positions = positions_data(cars=10, laps=20)
    backend.positionsChanged.emit()
    settle(3)
    assert chart.property("cachedLap") == -1  # table forgotten with the data
    nearest(x, 60)
    assert backend.asked[-1] != 15 or len(backend.asked) == 4


# --- PERF-040: notification center messages synced in place, notices on their own signal
def test_notification_center_model_synced_in_place(ui_env):
    from neopedal.ui.notification import notification_store
    from neopedal.ui.quick.notify_backend import NotificationBackend

    store = notification_store()
    store.clear()
    backend = NotificationBackend(None)
    try:
        entries_told, active_told = [], []
        backend.entriesChanged.connect(lambda: entries_told.append(1))
        backend.activeChanged.connect(lambda: active_told.append(1))
        inserted, resets = [], []
        backend.model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last)))
        backend.model.modelReset.connect(lambda: resets.append(1))
        store.add("first", "warning")
        store.add("second", "error", (("View Log", "log"),))
        assert [row["text"] for row in backend.model.rows] == ["second", "first"]  # newest first
        assert backend.entryCount == 2 and backend.unreadCount == 2 and len(backend.entries) == 2
        assert backend.model.rows[0]["entryId"] == backend.entries[0]["id"]
        assert backend.model.rows[0]["actions"] == [{"label": "View Log", "key": "log"}]
        assert inserted == [(0, 0), (0, 0)] and not resets and not active_told  # one row inserted at the top each
        changed = []
        backend.model.dataChanged.connect(lambda first, last, roles: changed.append((first.row(), last.row())))
        store.add("second", "error", (("View Log", "log"),))  # repeated: counted on the same row
        assert backend.model.rows[0]["count"] == 2 and changed == [(0, 0)] and len(inserted) == 2
        store.mark_all_read()
        assert all(row["read"] for row in backend.model.rows) and backend.unreadCount == 0
        assert len(inserted) == 2 and not resets
        before = len(entries_told)
        store.set_active([("Overlays locked", "unlock")])
        assert backend.active == [{"text": "Overlays locked", "key": "unlock"}]
        assert active_told == [1] and len(entries_told) == before  # notices never rebuild the messages
        store.remove(backend.entries[1]["id"])
        assert [row["text"] for row in backend.model.rows] == ["second"] and backend.entryCount == 1
    finally:
        store.set_active([])
        store.clear()
        backend.deleteLater()
        flush()


def test_notification_center_page_reads_the_model(ui_env, tmp_path):
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui.notification import notification_store
    from neopedal.ui.quick import PageState, Theme, Translator, qml_folder_imports, register_types, theme_copy
    from neopedal.ui.quick.notify_backend import NotificationBackend

    register_types()
    store = notification_store()
    store.clear()
    store.add("Recorder failed", "error", (("View Log", "log"),))
    store.add("Update found", "info")
    backend = NotificationBackend(None)
    view = QQuickWidget()
    try:
        wrapper = tmp_path / "center.qml"
        wrapper.write_text(f"import QtQuick\n{qml_folder_imports()}\nNotificationCenter {{ width: 400; height: 500 }}\n",
                           encoding="utf-8")
        context = view.rootContext()
        context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
        context.setContextProperty("i18n", Translator(view))
        context.setContextProperty("pageState", PageState(view))
        context.setContextProperty("backend", backend)
        view.setSource(QUrl.fromLocalFile(str(wrapper)))
        assert not view.errors(), [error.toString() for error in view.errors()]
        view.resize(400, 500)
        view.show()
        settle()
        texts = {item.property("text") for item in children(view, "") if item.property("text") is not None}
        assert "Recorder failed" in texts and "Update found" in texts and "View Log" in texts
    finally:
        view.close()
        view.setSource(QUrl())
        view.deleteLater()
        store.clear()
        backend.deleteLater()
        flush()


# --- PERF-041: toolbar fitted once per event loop turn when resized
TOOLBAR_WIDTH = '''Item {
    id: root
    property real barWidth: 1400
    TpToolbar {
        id: bar
        objectName: "bar"
        width: root.barWidth
        TpAction { name: "imp"; text: "Import laps"; glyph: "\uE8B5"; fallback: "+"; priority: 2 }
        TpAction { name: "exp"; text: "Export"; glyph: "\uEDE1"; priority: 1 }
        TpAction { name: "live"; text: "Live"; glyph: "\uE768"; checkable: true; priority: 0 }
        TpAction { name: "save"; text: "Save replay"; glyph: "\uE74E"; accent: true; priority: 3 }
        TpAction { name: "tip"; tip: "Settings only"; glyph: "\uE713"; fallback: "S"; priority: 4 }
    }
}'''


def test_toolbar_fits_once_per_resize_batch(component):  # noqa: F811
    view = component(TOOLBAR_WIDTH, width=1400, height=60)
    root = view.rootObject()
    bar = root.findChild(QObject, "bar")
    settle()
    wide = as_list(bar.property("modes"))
    assert wide == [0, 0, 0, 0, 0]
    for width in (1200, 900, 600, 400, 200):  # a drag: several widths in one turn
        root.setProperty("barWidth", width)
    assert as_list(bar.property("modes")) == wide  # nothing fitted per width change
    settle()
    narrow = as_list(bar.property("modes"))
    assert 2 in narrow  # fitted once events ran (timer), to the last width
    root.setProperty("barWidth", 1400)
    settle()
    assert as_list(bar.property("modes")) == [0, 0, 0, 0, 0]


# --- PERF-048: Presets page scans the trash only when it changed (presets stat'ed: edits in place seen)
def test_presets_trash_counted_only_when_changed(presets, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import preset_backend

    wait_jobs(presets)  # contents of every preset read & cached
    counted = []
    real_count = preset_backend.count_trash
    monkeypatch.setattr(preset_backend, "count_trash", lambda folder: counted.append(1) or real_count(folder))
    presets.refresh()
    presets.refresh()
    assert counted == []  # trash unchanged since the page was shown: not scanned again
    folder = cfg.path.settings
    os.makedirs(os.path.join(folder, "trash", "entry"))
    time.sleep(0.02)
    presets.refresh()
    assert counted == [1]  # trash changed: counted again
    presets.refresh()
    assert counted == [1]
    presets.set_active(False)
    presets.set_active(True)
    presets.refresh()
    assert counted == [1, 1]  # page shown again: counted whatever the trash time
    with open(f"{folder}a.json", "w", encoding="utf-8") as file:  # preset edited in place: still seen
        file.write('{"speedometer": {"enable": false}}')
    presets.refresh()
    assert [row["key"] for row in presets.model.rows if row["pending"]] == ["a.json"]
    wait_jobs(presets)


# --- BUG-050: preset file lock never blocks the UI for long, trash changed by one thread at a time
def test_apply_name_gives_up_when_files_are_read(presets, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import preset_backend

    monkeypatch.setattr(preset_backend, "PRESET_FILES_WAIT", 0.05)
    assert preset_backend.PRESET_FILES.acquire(timeout=1)
    try:
        started = time.monotonic()
        error = presets.applyName("duplicate", "a.json", "copy")
        assert time.monotonic() - started < 1 and error == preset_backend.TRY_AGAIN
        assert not os.path.exists(f"{cfg.path.settings}copy.json")
    finally:
        preset_backend.PRESET_FILES.release()
    assert presets.applyName("duplicate", "a.json", "copy") == ""
    assert os.path.exists(f"{cfg.path.settings}copy.json")


def test_trash_changes_wait_for_the_purge(presets, monkeypatch):  # noqa: F811
    from neopedal.ui import preset_management
    from neopedal.ui.quick import preset_tools_backend
    from neopedal.userfile.preset_trash import list_trash

    monkeypatch.setattr(preset_tools_backend, "TRASH_WAIT", 0.05)
    preset_management.trash_preset("a.json")
    trash = presets.trash
    trash.refresh()
    wait_jobs(presets)
    assert trash.count == 1
    key = trash.model.rows[0]["key"]
    assert preset_tools_backend.TRASH.acquire(timeout=1)  # the read job holds the trash (slow disk)
    try:
        trash.restore(key)
        assert presets.toasts[-1] == (preset_tools_backend.TRASH_BUSY, True)
        assert len(list_trash(cfg.path.settings)) == 1 and not os.path.exists(f"{cfg.path.settings}a.json")
        trash.remove(key)
        trash.empty()
        assert len(list_trash(cfg.path.settings)) == 1
    finally:
        preset_tools_backend.TRASH.release()
    # Entry purged meanwhile (shown row out of date): told, never an OSError
    folder = trash.model.rows[0]["key"]
    import shutil

    shutil.rmtree(folder)
    trash.restore(key)
    assert presets.toasts[-1] == (preset_tools_backend.ENTRY_GONE, True)
    wait_jobs(presets)
    assert trash.count == 0
    # Purge of the read job holds the lock while it runs
    held = []
    real_purge = preset_tools_backend.purge_trash
    monkeypatch.setattr(preset_tools_backend, "purge_trash",
                        lambda *args: held.append(preset_tools_backend.TRASH.locked()) or real_purge(*args))
    trash.refresh()
    wait_jobs(presets)
    assert held == [True]


# --- PERF-065: search in every overlay counts the matches of each overlay once
def test_search_every_overlay_counts_each_overlay_once(options, monkeypatch):  # noqa: F811
    options.selectOverlay("speedometer")
    options.setScopeAll(True)
    counted = []
    real_count = type(options).count_matches
    monkeypatch.setattr(type(options), "count_matches",
                        lambda self, name: counted.append(name) or real_count(self, name))
    built = []
    real_rows = type(options)._overlay_rows
    monkeypatch.setattr(type(options), "_overlay_rows",
                        lambda self, name, found, with_name: built.append(name) or real_rows(self, name, found, with_name))
    options.setSearch("opacity")
    assert sorted(counted) == sorted(options._names)  # once per overlay (update_rows), not again by update_nav
    nav = {entry["key"]: entry for entry in options.nav.rows}
    assert nav["fuel"]["matches"] == 1 and options.matchCount == len(rows(options))
    counted.clear()
    built.clear()
    options.setSearch("speedometer")  # label of one overlay: others never build their rows
    assert sorted(counted) == sorted(options._names)
    assert built == ["speedometer"]
    nav = {entry["key"]: entry for entry in options.nav.rows}
    assert nav["speedometer"]["matches"] > 0 and nav["fuel"]["matches"] == 0
