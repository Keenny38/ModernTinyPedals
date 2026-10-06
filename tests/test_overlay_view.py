"""Overlays page: overlay list model, filters, previews, actions & Qt Quick page"""

from types import MappingProxyType

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage

from tinypedal.setting import cfg
from tinypedal.ui.quick import overlay_backend
from tinypedal.ui.quick.overlay_backend import (
    CATEGORY_ALL,
    CATEGORY_COLORS,
    CATEGORY_OTHER,
    FILTER_ACTIVE,
    FILTER_INACTIVE,
    PREVIEW_LOADING,
    PREVIEW_READY,
    PREVIEW_UNAVAILABLE,
    WIDGET_CATEGORIES,
    OverlayBackend,
    OverlayModel,
    PreviewCache,
    image_url,
    search_words,
    widget_category,
)

NAMES = ("brake_temperature", "brake_wear", "speedometer", "fuel", "relative", "plugin_demo")


class FakeControl:
    """Widget control: toggles setting only, enabled overlays running unless failing"""

    type_id = "widget"

    def __init__(self, names, failing=()):
        self._names = dict.fromkeys(names)
        self.failing = set(failing)
        self.toggled: list[str] = []
        self.batch: list[str] = []
        self.reloaded: list[str] = []

    @property
    def names(self):
        return self._names.keys()

    @property
    def active_modules(self):
        return MappingProxyType({
            name: None for name in self._names
            if cfg.user.setting[name]["enable"] and name not in self.failing
        })

    def toggle(self, name):
        self.toggled.append(name)
        cfg.user.setting[name]["enable"] = not cfg.user.setting[name]["enable"]

    def enable_all(self):
        self.batch.append("enable")
        for name in self._names:
            cfg.user.setting[name]["enable"] = True

    def disable_all(self):
        self.batch.append("disable")
        for name in self._names:
            cfg.user.setting[name]["enable"] = False

    def reload(self, name=""):
        self.reloaded.append(name)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def solid(color: str, width: int = 40, height: int = 20) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


@pytest.fixture
def overlays(ui_env, monkeypatch):
    """Backend over 6 overlays (brakes on, a plugin), previews drawn as solid pictures, questions answered yes"""
    cfg.user.setting["plugin_demo"] = {"enable": False}
    for name in NAMES:
        cfg.user.setting[name]["enable"] = name in ("brake_temperature", "speedometer")
    monkeypatch.setattr(overlay_backend, "render_preview", lambda name: solid("#336699"))
    control = FakeControl(NAMES)
    answers: list[str] = []
    configs: list[str] = []
    backend = OverlayBackend(None, control, configs.append, lambda text: answers.append(text) or True)
    backend.test_control = control  # type: ignore[attr-defined]
    backend.test_answers = answers  # type: ignore[attr-defined]
    backend.test_configs = configs  # type: ignore[attr-defined]
    yield backend
    backend.close()
    backend.deleteLater()
    flush()


def shown(backend) -> list[str]:
    proxy = backend.proxy
    return [proxy.data(proxy.index(row, 0), OverlayModel.NameRole) for row in range(proxy.rowCount())]


def test_categories():
    from tinypedal.template.setting_widget import WIDGET_FILENAME

    assert widget_category("tyre_pressure") == "Tyres & Wheels"
    assert widget_category("brake_wear") == "Brakes"
    assert widget_category("plugin_xyz") == CATEGORY_OTHER
    assert widget_category("onboard_setting") == "Driver Inputs"  # TC, ABS, brake bias...
    others = {name for name in WIDGET_FILENAME if widget_category(name) == CATEGORY_OTHER}
    assert others <= {"system_performance", "plugin_example_speed"}  # new built-in overlays get a category
    assert set(CATEGORY_COLORS) == {category for category, _ in WIDGET_CATEGORIES} | {CATEGORY_OTHER}


def test_search_words_fold_case_and_accents():
    assert search_words("  Température  FREINS ") == ("temperature", "freins")
    assert search_words("") == ()


def test_rows_sorted_with_roles(overlays):
    names = shown(overlays)
    labels = [overlays.proxy.data(overlays.proxy.index(row, 0), OverlayModel.LabelRole) for row in range(len(names))]
    assert sorted(names) == sorted(NAMES)
    assert labels == sorted(labels, key=str.casefold)
    index = overlays.source.index(overlays.source.index_of["brake_wear"], 0)
    assert index.data(OverlayModel.CategoryRole) == "Brakes"
    assert index.data(OverlayModel.ColorRole) == CATEGORY_COLORS["Brakes"]
    assert index.data(OverlayModel.EnabledRole) is False
    assert b"active" in overlays.source.roleNames().values()  # not "enabled": QML item property
    assert overlays.totalCount == len(NAMES) and overlays.activeCount == 2


def test_search_state_and_category_filters(overlays):
    overlays.setSearch("brake")
    assert set(shown(overlays)) == {"brake_temperature", "brake_wear"}
    assert overlays.filtered and overlays.searchText == "brake"
    overlays.setSearch("wear brake")  # every word, any order
    assert shown(overlays) == ["brake_wear"]
    overlays.setSearch("")
    overlays.setStateFilter(FILTER_ACTIVE)
    assert set(shown(overlays)) == {"brake_temperature", "speedometer"}
    overlays.setStateFilter(FILTER_INACTIVE)
    assert "speedometer" not in shown(overlays) and len(shown(overlays)) == 4
    overlays.setCategory("Brakes")
    assert shown(overlays) == ["brake_wear"]
    overlays.setCategory("Nothing")  # unknown category ignored
    assert overlays.category == "Brakes"
    overlays.clearFilters()
    assert len(shown(overlays)) == len(NAMES) and not overlays.filtered


def test_search_in_french_labels(overlays):
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        backend = OverlayBackend(None, overlays.test_control, lambda name: None, lambda text: True)
        backend.setSearch("temperature freins")  # label "Température des freins", accent left out
        assert shown(backend) == ["brake_temperature"]
        backend.setSearch("chronometrage")  # category label
        assert shown(backend) == ["relative"]
        backend.setSearch("brake temperature")  # widget name in English still found
        assert shown(backend) == ["brake_temperature"]
        backend.deleteLater()
    finally:
        i18n.set_language("English")


def test_counts_follow_other_filters(overlays):
    chips = overlays.categories
    assert chips[0]["key"] == CATEGORY_ALL
    assert [chip["key"] for chip in chips[1:]] == ["Timing", "Brakes", "Engine & Energy", CATEGORY_OTHER]
    assert overlays.categoryCounts[CATEGORY_ALL] == len(NAMES)
    overlays.setStateFilter(FILTER_ACTIVE)
    counts = overlays.categoryCounts
    assert counts["Brakes"] == 1 and counts["Timing"] == 0 and counts[CATEGORY_ALL] == 2
    overlays.setStateFilter(0)
    overlays.setCategory("Brakes")
    assert overlays.stateCounts == [2, 1, 1]  # category applied, state left out
    assert overlays.shownCount == 2


def test_toggle_updates_row_and_filter(overlays):
    overlays.setStateFilter(FILTER_ACTIVE)
    overlays.toggle("speedometer")
    assert overlays.test_control.toggled == ["speedometer"]
    assert "speedometer" not in shown(overlays)  # switched off: leaves Active view
    assert overlays.activeCount == 1
    overlays.toggle("unknown")
    assert overlays.test_control.toggled == ["speedometer"]


def test_failed_state(overlays):
    overlays.test_control.failing.add("speedometer")
    overlays.refresh()
    index = overlays.source.index(overlays.source.index_of["speedometer"], 0)
    assert index.data(OverlayModel.FailedRole) is True and overlays.failedCount == 1
    overlays._safe_mode = True  # overlays never started in safe mode: not an error
    overlays.refresh()
    assert index.data(OverlayModel.FailedRole) is False


def test_batch_toggle_shown_only(overlays, monkeypatch):
    control = overlays.test_control
    overlays.setCategory("Brakes")
    overlays.enableShown()
    assert control.toggled == ["brake_wear"] and not control.batch  # only shown & off
    assert "2 shown" not in overlays.test_answers[0] and "1 shown overlays" in overlays.test_answers[0]
    overlays.clearFilters()
    overlays.disableShown()
    assert control.batch == ["disable"]  # no filter: every overlay
    overlays.disableShown()  # nothing left to switch: no question
    assert len(overlays.test_answers) == 2
    monkeypatch.setitem(cfg.application, "show_confirmation_for_batch_toggle", False)
    overlays.enableShown()
    assert control.batch == ["disable", "enable"] and len(overlays.test_answers) == 2


def test_batch_toggle_declined(ui_env):
    control = FakeControl(("brake_wear", "fuel"))
    for name in control.names:
        cfg.user.setting[name]["enable"] = False
    backend = OverlayBackend(None, control, lambda name: None, lambda text: False)
    backend.enableShown()
    assert not control.batch and not control.toggled
    backend.deleteLater()


def test_refresh_follows_external_changes(overlays):
    cfg.user.setting["fuel"]["enable"] = True  # hotkey, tray or preset
    overlays.refresh()
    assert overlays.activeCount == 3
    overlays.test_control._names.pop("plugin_demo")  # plugin removed
    overlays.refresh()
    assert "plugin_demo" not in overlays.source.index_of
    assert CATEGORY_OTHER not in [chip["key"] for chip in overlays.categories]


def test_grid_view_setting(overlays, ui_env):
    assert overlays.gridView is True
    changed = []
    overlays.viewChanged.connect(lambda: changed.append(1))
    overlays.setGridView(False)
    assert cfg.application["show_overlay_previews"] is False and changed == [1]
    overlays.setGridView(False)
    assert changed == [1]
    assert "config" in ui_env  # saved
    cfg.application["show_overlay_previews"] = True


def test_open_config(overlays):
    overlays.openConfig("fuel")
    overlays.openConfig("unknown")
    assert overlays.test_configs == ["fuel"]


# Previews
def test_preview_cache_renders_while_active_only():
    rendered, ready = [], []
    cache = PreviewCache(lambda name: rendered.append(name) or solid("#ff0000"), ready.append)
    assert cache.role("gear", OverlayModel.PreviewStateRole) == PREVIEW_LOADING
    assert cache.role("gear", OverlayModel.PreviewRole) == ""
    assert cache.pending() == 1  # queued once
    QCoreApplication.processEvents()
    assert not rendered  # page hidden: nothing drawn
    cache.set_active(True)
    for _ in range(5):
        QCoreApplication.processEvents()
    assert rendered == ["gear"] and ready == ["gear"]
    assert cache.role("gear", OverlayModel.PreviewStateRole) == PREVIEW_READY
    url = cache.role("gear", OverlayModel.PreviewRole)
    assert url.startswith("data:image/png;base64,")
    assert cache.role("gear", OverlayModel.PreviewWidthRole) == 40
    assert cache.role("gear", OverlayModel.PreviewHeightRole) == 20
    cache.stop()


def test_preview_cache_keeps_picture_until_redrawn():
    colors = ["#ff0000", "#ff0000", "#00ff00"]
    ready = []
    cache = PreviewCache(lambda name: solid(colors.pop(0)), ready.append)
    cache.render_now("gear")
    first = cache.role("gear", OverlayModel.PreviewRole)
    cache.invalidate()
    assert cache.role("gear", OverlayModel.PreviewRole) == first  # old picture shown meanwhile
    assert cache.pending() == 1
    cache.render_now("gear")  # same picture: page not told
    assert ready == ["gear"] and cache.role("gear", OverlayModel.PreviewRole) == first
    cache.render_now("gear")
    assert ready == ["gear", "gear"] and cache.role("gear", OverlayModel.PreviewRole) != first
    cache.stop()


def test_preview_unavailable():
    ready = []
    cache = PreviewCache(lambda name: None, ready.append)
    cache.render_now("plugin_demo")
    assert cache.role("plugin_demo", OverlayModel.PreviewStateRole) == PREVIEW_UNAVAILABLE
    assert cache.role("plugin_demo", OverlayModel.PreviewRole) == ""
    cache.render_now("plugin_demo")  # still not available: page not told again
    assert ready == ["plugin_demo"]
    cache.stop()


def test_preview_data_url():
    import base64

    url = image_url(solid("#123456", 30, 10))
    assert url.startswith("data:image/png;base64,")
    image = QImage.fromData(base64.b64decode(url.split(",", 1)[1]), "PNG")
    assert (image.width(), image.height()) == (30, 10)
    assert image.pixelColor(5, 5) == QColor("#123456")


def test_render_preview(ui_env):
    image = overlay_backend.render_preview("speedometer")
    assert image is not None and not image.isNull()
    big = overlay_backend.render_preview("standings")  # scaled down to card size
    assert big is not None
    ratio = big.devicePixelRatio() or 1
    assert big.width() / ratio <= overlay_backend.PREVIEW_MAX.width()
    assert overlay_backend.render_preview("no_such_widget") is None


def test_refresh_redraws_previews_in_background(overlays):
    overlays.previews.render_now("fuel")
    first = overlays.previews.role("fuel", OverlayModel.PreviewRole)
    changed = []
    overlays.source.dataChanged.connect(lambda first_index, last, roles: changed.append(tuple(roles)))
    overlays.refresh()
    assert any(OverlayModel.PreviewRole in roles for roles in changed)  # shown rows read preview again
    assert overlays.previews.role("fuel", OverlayModel.PreviewRole) == first
    assert overlays.previews.pending() >= 1


# Page
@pytest.fixture
def page(overlays, monkeypatch):
    from tinypedal.ui.overlay_view import OverlayView

    view = OverlayView(None, overlays.test_control)
    monkeypatch.setattr(view.backend, "_confirm", lambda text: True)
    view.resize(900, 640)
    yield view
    view.close()
    view.deleteLater()
    flush()


def item_texts(view) -> set[str]:
    texts = set()
    stack = [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def test_qml_page_created_when_shown(page):
    assert page.view is None  # nothing loaded until shown
    page.show()
    assert page.view is not None
    assert not page.view.errors(), [error.toString() for error in page.view.errors()]
    assert page.layout().count() == 1  # created once (show event while loading)
    assert page.backend.previews.active
    for _ in range(20):
        QCoreApplication.processEvents()
    texts = item_texts(page.view)
    assert "Overlays" in texts and "Speedometer" in texts and "Enable All" in texts
    assert not page.view.grabFramebuffer().isNull()
    page.hide()
    assert not page.backend.previews.active  # no preview drawn while hidden


def test_qml_page_list_view_and_filters(page):
    page.show()
    page.backend.setGridView(False)
    page.backend.setSearch("brake")
    for _ in range(20):
        QCoreApplication.processEvents()
    texts = item_texts(page.view)
    assert "Enable Shown" in texts and "Speedometer" not in texts
    page.backend.setSearch("zzz")
    for _ in range(20):
        QCoreApplication.processEvents()
    assert "No overlay matches the filters" in item_texts(page.view)
    cfg.application["show_overlay_previews"] = True


def test_qml_page_translated(overlays):
    from tinypedal import i18n
    from tinypedal.ui.overlay_view import OverlayView

    i18n.set_language("Français")
    try:
        view = OverlayView(None, overlays.test_control)
        view.show()
        for _ in range(10):
            QCoreApplication.processEvents()
        texts = item_texts(view.view)
        assert "Tout activer" in texts and "Enable All" not in texts
        assert "2 / 6 activés" in texts
        view.close()
        view.deleteLater()
        flush()
    finally:
        i18n.set_language("English")


def test_config_saved_updates_card(page):
    page.backend.previews.render_now("fuel")
    cfg.user.setting["fuel"]["enable"] = True
    page.reload_overlay("fuel")
    assert page.module_control.reloaded == ["fuel"]
    index = page.backend.source.index(page.backend.source.index_of["fuel"], 0)
    assert index.data(OverlayModel.EnabledRole) is True
    assert "fuel" in page.backend.previews._stale


def test_refresh_slot(page):
    cfg.user.setting["relative"]["enable"] = True
    page.refresh(True)
    assert page.backend.activeCount == 3


def test_main_window_uses_overlay_page(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui import app as app_module
    from tinypedal.ui.overlay_view import OverlayView

    host = QWidget()
    try:
        page = app_module.build_page("widget", host, view=None, window=host, icon_family="")  # type: ignore[arg-type]
        assert isinstance(page, OverlayView)
    finally:
        host.deleteLater()
        flush()


def test_qml_imports_bundled_modules():
    """Release build bundles only QML_MODULES: page files import nothing else

    Checked statically: loading copies of the QML plugin libraries from a temporary folder made a
    later test crash (access violation when the application style sheet changed).
    """
    import re

    from tinypedal.ui.quick import QML_FOLDER
    from tinypedal.ui.quick.qml_modules import QML_MODULES

    for name in ("Overlays.qml", "OverlayCard.qml", "OverlayListRow.qml", "OverlayChip.qml"):
        with open(f"{QML_FOLDER}/{name}", encoding="utf-8") as file:
            modules = re.findall(r"^import ([A-Za-z.]+)", file.read(), flags=re.MULTILINE)
        assert modules and all(module.replace(".", "/") in QML_MODULES for module in modules), (name, modules)


def test_french_page_messages():
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("<b>Enable</b> 3 shown overlays?") == "<b>Activer</b> les 3 overlays affichés ?"
        assert i18n.trm("<b>Disable</b> all overlays?") == "<b>Désactiver</b> tous les overlays ?"
        assert i18n.trm("5 of 87 overlays shown") == "5 overlays affichés sur 87"
        assert i18n.trm("12 / 87 enabled") == "12 / 87 activés"
        assert i18n.trm("2 overlays could not start, see log.") == "2 overlays n'ont pas pu démarrer, voir le journal."
        assert i18n.tr("1 overlay could not start, see log.") == "1 overlay n'a pas pu démarrer, voir le journal."
        assert i18n.trm("Show only Freins") == "Afficher uniquement : Freins"
        assert i18n.trm("87 overlays") == "87 overlays"
    finally:
        i18n.set_language("English")
