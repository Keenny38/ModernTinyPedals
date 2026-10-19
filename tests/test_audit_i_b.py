"""Audit 2026-10-18, lot B: global refresh bus & hidden pages

Director cuts tell the Spectate page only (no whole GUI refresh, preset saved later), hidden pages defer their
refresh until shown (PageBackend.defer_while_hidden / when_shown), Modules counts told only when changed, dropped
presets refresh once, Stream page signals split and screen size asked once, Track Map Viewer follows unit changes.
"""

import gc
import json
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent

from neopedal import app_signal
from neopedal.setting import cfg
from tests.test_audit_c_app import window  # noqa: F401
from tests.test_broadcast_director import car, director_page, poll, race_answers  # noqa: F401
from tests.test_driver_stats_e2 import stats_page  # noqa: F401
from tests.test_driver_stats_viewer import settle
from tests.test_module_page import DEPENDENCIES, MODULES, WIDGETS, FakeControl, modules  # noqa: F401
from tests.test_spectate_page import Reader, backend, setups  # noqa: F401
from tests.test_stream_overlay import page_backend, server  # noqa: F401


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


class Counter:
    """Calls of a signal"""

    def __init__(self, signal):
        self.calls: list = []
        self.signal = signal
        signal.connect(self.called)

    def called(self, *args):
        self.calls.append(args)

    def close(self):
        self.signal.disconnect(self.called)


# --- PageBackend: hidden pages defer their work, run once shown
def test_page_visible_kept_whatever_form_overridden():
    from neopedal.ui.quick.page_backend import PageBackend

    class ByActive(PageBackend):
        def set_active(self, active):
            self.seen = self.page_visible

    class ByShown(PageBackend):
        def page_shown(self):
            self.seen = self.page_visible

    class Sub(ByShown):  # wrapped again at each level: still once per call
        def page_shown(self):
            super().page_shown()

    for page in (ByActive(), ByShown(), Sub(), PageBackend()):
        assert not page.page_visible
        page.page_shown()
        assert page.page_visible and getattr(page, "seen", True)  # visible already inside the override
        page.page_hidden()
        assert not page.page_visible
        page.set_active(True)
        assert page.page_visible
        page.release()
        assert not page.page_visible  # released: never visible again
        page.deleteLater()
    flush()


def test_deferred_once_after_shown_and_dropped():
    from neopedal.ui.quick.page_backend import PageBackend

    class Page(PageBackend):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_active(self, active):
            self.calls.append(("active", active))

        def refresh(self):
            if self.defer_while_hidden(self.refresh):
                return
            self.calls.append("refresh")

        def other(self):
            self.calls.append("other")

    page = Page()
    page.refresh()
    page.refresh()
    assert not page.when_shown(page.other)
    assert page.calls == []  # hidden: nothing computed
    page.page_shown()
    assert page.calls == [("active", True), "refresh", "other"]  # after the page's own show, once, in order
    page.calls.clear()
    assert page.when_shown(page.other) and page.calls == ["other"]  # shown: run now
    page.page_hidden()
    page.refresh()
    page.drop_when_shown(page.refresh)
    page.set_active(True)
    assert page.calls == ["other", ("active", False), ("active", True)]  # dropped: page made everything again
    page.page_hidden()
    page.refresh()
    page.release()
    page.page_shown()  # released: nothing run
    assert "refresh" not in page.calls
    page.deleteLater()
    flush()


def test_deferred_methods_kept_without_reference_cycle():
    """Methods of the page kept as functions: a hidden page with deferred work is freed by reference count alone
    (a cycle freed by the garbage collector could free the QObject on another thread)"""
    import weakref

    from neopedal.ui.quick.page_backend import PageBackend

    class Page(PageBackend):
        def refresh(self):
            pass

    page = Page()
    page.defer_while_hidden(page.refresh)
    ref = weakref.ref(page)
    gc.disable()
    try:
        del page
        assert ref() is None
    finally:
        gc.enable()


# --- B1: Director cuts tell the Spectate page only, preset saved later
def test_director_cut_tells_spectate_page_only(director_page, ui_env, monkeypatch):  # noqa: F811
    from neopedal import loader
    from neopedal.api_control import api
    from neopedal.ui.quick.director_backend import DirectorBackend

    page, director = director_page, director_page.backend
    monkeypatch.setattr(type(api), "setup", lambda self: None)
    monkeypatch.setattr(loader, "_pending_writers", [])
    monkeypatch.setitem(cfg.api, "enable_player_index_override", False)
    monkeypatch.setattr(DirectorBackend, "_follow_unsaved", False)
    monkeypatch.setattr(DirectorBackend, "_follow_save_due", 0.0)
    refresh, spectate = Counter(app_signal.refresh), Counter(app_signal.spectate_changed)
    try:
        poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=600.0), focus=2))
        ui_env.clear()
        director.setFollowOverlays(True)  # spectate mode turned on: saved, whole GUI told (notification bar)
        assert refresh.calls == [(True,)] and spectate.calls == [] and ui_env == ["setting"]
        director.cutToCar(1)  # another car: Spectate page only, saved later
        director.cutToCar(2)
        assert refresh.calls == [(True,)] and spectate.calls == [(1,), (2,)]
        assert ui_env == ["setting"] and DirectorBackend._follow_unsaved
        assert cfg.api["player_index"] == 2 and cfg.api["enable_player_index_override"]
        DirectorBackend.save_followed()  # timer of the first cut (one save for many cuts)
        DirectorBackend.save_followed()
        assert ui_env == ["setting", "setting"] and not DirectorBackend._follow_unsaved
        director.cutToCar(1)
        assert loader._pending_writers == [DirectorBackend.save_followed_now]  # registered once
        loader.write_pending()  # preset reload, restart or quit: written at once
        assert ui_env == ["setting"] * 3 and not DirectorBackend._follow_unsaved
        loader.write_pending()  # nothing left to write
        assert ui_env == ["setting"] * 3
    finally:
        refresh.close()
        spectate.close()


def test_spectate_page_follows_cuts_once_shown(backend, setups):  # noqa: F811
    """Spectate page hidden: mode read at once (cheap), rows made again only once shown"""
    rows = []
    backend.model.modelReset.connect(lambda: rows.append("reset"))
    backend.model.dataChanged.connect(lambda *args: rows.append("data"))
    state = Counter(backend.stateChanged)
    backend.set_active(False)
    cfg.api["enable_player_index_override"] = True
    cfg.api["player_index"] = 7
    backend.changed_elsewhere()
    backend.changed_elsewhere()
    assert backend.enabled and state.calls == [] and rows == []  # mode known, nothing made while hidden
    backend.set_active(True)
    assert len(state.calls) == 1 and backend.spectatedSlot == 7  # once shown: made again once
    assert [row["slot"] for row in backend.model.rows if row["spectated"]] == [7]
    backend.changed_elsewhere()  # shown: at once
    assert len(state.calls) == 2
    state.close()


def test_spectate_changed_reaches_spectate_page(window, monkeypatch):  # noqa: F811
    """Main view: spectate_changed goes to the Spectate page (once built), nothing else of the GUI"""
    lazy = window.centralWidget()._lazy_pages["spectate"]
    app_signal.spectate_changed.emit(3)  # page not built: nothing to do
    page = lazy.ensure_page()
    told = []
    monkeypatch.setattr(page.backend, "changed_elsewhere", lambda: told.append(1))
    app_signal.spectate_changed.emit(3)
    assert told == [1]


# --- Architecture 1: hidden pages never recompute on refresh
def test_modules_refresh_deferred_while_hidden(modules):  # noqa: F811
    counts = Counter(modules.countsChanged)
    reads = []
    real_row = modules._row
    modules._row = lambda name: reads.append(name) or real_row(name)  # type: ignore[method-assign]
    cfg.user.setting["module_sectors"]["enable"] = True  # changed elsewhere
    modules.settings_changed()
    modules.settings_changed()
    assert reads == [] and counts.calls == []  # hidden: nothing read
    modules.page_shown()
    assert len(reads) == len(MODULES) and len(counts.calls) == 1  # once: page shown reads states again
    assert modules.activeCount == 5
    reads.clear()
    modules.settings_changed()  # shown: at once, counts unchanged so not told
    assert len(reads) == len(MODULES) and len(counts.calls) == 1
    modules.setSearch("delta")
    assert len(counts.calls) == 2 and modules.shownCount == 1 and modules.stateCounts == [1, 1, 0]
    modules.setSearch("delta ")  # same words: nothing
    assert len(counts.calls) == 2
    counts.close()


def test_module_view_shows_and_defers(ui_env, monkeypatch):
    from neopedal.ui.module_view import ModuleList

    for name in MODULES:
        cfg.user.setting[name]["enable"] = True
    view = ModuleList(None, FakeControl(MODULES), FakeControl(WIDGETS, "widget"))
    try:
        view.backend.load_dependencies(DEPENDENCIES)
        refreshed = []
        real = view.backend.refresh
        monkeypatch.setattr(view.backend, "refresh", lambda: refreshed.append(1) or real())
        view.refresh()
        assert refreshed == []  # never shown: deferred
        view.show()
        assert view.backend.page_visible and refreshed == [1]  # page shown: read once (deferred one dropped)
        view.refresh()
        assert refreshed == [1, 1]
        view.hide()
        assert not view.backend.page_visible
        view.refresh()
        assert refreshed == [1, 1]
    finally:
        view.close()
        if view.view is not None:
            from PySide6.QtCore import QUrl

            view.view.setSource(QUrl())
        view.deleteLater()
        flush()


def test_stats_settings_deferred_and_dropped_after_history_release(stats_page, monkeypatch):  # noqa: F811
    page = stats_page
    tables = []
    real = page.refresh_table
    monkeypatch.setattr(page, "refresh_table", lambda: tables.append(len(page.history)) or real())
    page.page_shown()
    tables.clear()
    app_signal.refresh.emit(True)
    assert tables == [2]  # shown: at once
    page.page_hidden()
    app_signal.refresh.emit(True)
    app_signal.refresh.emit(True)
    assert tables == [2]  # hidden: deferred
    page.page_shown()
    assert tables == [2, 2]  # once, with the history
    page.page_hidden()
    app_signal.refresh.emit(True)
    settle(page)
    page.release_history()
    assert page._history_released and tables == [2, 2]  # never made on the released (empty) history
    page.page_shown()
    assert not page._page_deferred  # dropped: table made again with the history read
    settle(page)
    assert page.history and all(count == 2 for count in tables)


def test_stream_signals_split_and_screen_asked_once(page_backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import stream_backend

    sizes = []
    monkeypatch.setattr(stream_backend.StreamOverlaysBackend, "screen_size",
                        staticmethod(lambda: sizes.append(1) or (2560, 1440)))
    status, addresses, layout = (Counter(page_backend.serverChanged), Counter(page_backend.addressesChanged),
                                 Counter(page_backend.layoutChanged))
    try:
        page_backend.refresh()
        page_backend.refresh()
        layout_calls = len(layout.calls)
        assert sizes == [1, 1]  # once per refresh (was twice)
        page_backend.refresh()
        assert len(layout.calls) == layout_calls and not status.calls and not addresses.calls  # nothing changed
        page_backend.setLayoutFormat(1)  # forced: every group told once
        assert len(status.calls) == len(addresses.calls) == 1
        status.calls.clear()
        addresses.calls.clear()
        layout.calls.clear()
        monkeypatch.setattr(stream_backend.StreamOverlaysBackend, "screen_size", staticmethod(lambda: (1920, 1080)))
        page_backend.refresh()  # screen changed: layout only
        assert len(layout.calls) == 1 and not status.calls and not addresses.calls
        assert page_backend.layoutSizeText.endswith(f"1920 {stream_backend.TIMES} 1080")
    finally:
        status.close()
        addresses.close()
        layout.close()


def test_stream_overlays_deferred_while_hidden(page_backend, monkeypatch):  # noqa: F811
    synced = []
    real = page_backend.refresh_overlays
    monkeypatch.setattr(page_backend, "refresh_overlays", lambda *args: synced.append(1) or real())
    page_backend.overlays_changed()
    assert synced == [1]  # shown: at once
    page_backend.page_hidden()
    app_signal.refresh.emit(True)
    page_backend.overlays_changed()
    assert synced == [1]
    page_backend.page_shown()
    assert synced == [1, 1]  # page shown reads everything once (deferred one dropped)


# --- file_drop: one refresh for many presets
def test_dropped_presets_refresh_once(ui_env, tmp_path):
    from neopedal.ui import file_drop

    paths = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"deltabest": {"enable": True}}), encoding="utf-8")
        paths.append(str(path))
    other = tmp_path / "notes.txt"
    other.write_text("x", encoding="utf-8")
    pages = []
    host = SimpleNamespace(centralWidget=lambda: SimpleNamespace(set_current_index=pages.append))
    refresh = Counter(app_signal.refresh)
    try:
        messages = file_drop.handle_drop(host, paths)
        assert len(messages) == 3 and len(refresh.calls) == 1
        refresh.calls.clear()
        file_drop.handle_drop(host, [paths[0], str(other), paths[1]])  # other file next: presets listed first
        assert len(refresh.calls) == 2
        refresh.calls.clear()
        file_drop.handle_drop(host, [str(other)])  # nothing imported: no refresh
        assert refresh.calls == []
    finally:
        refresh.close()


# --- Track Map Viewer: distance unit follows the settings
def test_track_map_units_follow_settings(ui_env, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick.track_map_backend import TrackMapBackend

    host = QWidget()
    page = TrackMapBackend(host)
    units = Counter(page.unitsChanged)
    try:
        monkeypatch.setitem(cfg.units, "distance_unit", "Meter")
        app_signal.refresh.emit(True)
        assert page.distanceUnit == "m" and page.distanceScale == 1.0 and units.calls == []
        monkeypatch.setitem(cfg.units, "distance_unit", "Feet")
        app_signal.refresh.emit(True)
        app_signal.refresh.emit(True)
        assert page.distanceUnit == "ft" and page.distanceScale > 3 and len(units.calls) == 1
        page.release()
        monkeypatch.setitem(cfg.units, "distance_unit", "Meter")
        app_signal.refresh.emit(True)  # released: disconnected
        assert len(units.calls) == 1
    finally:
        units.close()
        page.release()
        host.deleteLater()
        flush()
