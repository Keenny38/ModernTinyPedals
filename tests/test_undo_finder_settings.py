"""Undo & redo of Find Option page (switches & resets saved and applied, undone the same way, notice with Undo
button, Ctrl+Z / Ctrl+Y) and Settings page history kept across Apply (applied edit undone: pending again)"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from neopedal.setting import cfg

TRAY = "config/application/minimize_to_tray"


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def finder(ui_env, monkeypatch):
    from neopedal.ui.quick import finder_backend

    applied = []
    monkeypatch.setattr(finder_backend, "run_after_saving", lambda callback: applied.append(callback))
    backend = finder_backend.FinderBackend(None, lambda entry: None)
    backend.applied, backend.saved = applied, ui_env
    yield backend
    backend.deleteLater()
    flush()


def tray() -> bool:
    return cfg.user.config["application"]["minimize_to_tray"]


# Find Option page
def test_toggle_undo_redo_saved_and_applied(finder):
    before = tray()
    assert not finder.canUndo and not finder.canRedo
    finder.toggle(TRAY)
    assert tray() is (not before) and finder.canUndo and not finder.canRedo
    saves, reloads = len(finder.saved), len(finder.applied)
    finder.undo()
    assert tray() is before and finder.canRedo and not finder.canUndo
    assert len(finder.saved) == saves + 1 and len(finder.applied) == reloads + 1  # saved & applied again
    finder.redo()
    assert tray() is (not before) and finder.canUndo and not finder.canRedo
    assert len(finder.saved) == saves + 2 and len(finder.applied) == reloads + 2
    finder.redo()  # nothing to redo: nothing saved
    assert len(finder.saved) == saves + 2


def test_reset_undone_and_new_change_clears_redo(finder):
    key = "widget/speedometer/opacity"
    cfg.user.setting["speedometer"]["opacity"] = 0.5
    finder.resetOption(key)
    default = cfg.default.setting["speedometer"]["opacity"]
    assert cfg.user.setting["speedometer"]["opacity"] == default
    finder.resetOption(key)  # already default: no undo step
    finder.undo()
    assert cfg.user.setting["speedometer"]["opacity"] == 0.5 and not finder.canUndo
    finder.toggle(TRAY)  # new change: redo dropped
    assert finder.canUndo and not finder.canRedo


def test_history_capped(finder):
    from neopedal.ui.quick.finder_backend import HISTORY_LIMIT

    for _ in range(HISTORY_LIMIT + 20):
        finder.toggle(TRAY)
    assert len(finder._undo) == HISTORY_LIMIT


def test_change_made_elsewhere_not_reverted(finder, monkeypatch):
    finder.toggle(TRAY)
    toggled = tray()
    cfg.user.config["application"]["minimize_to_tray"] = not toggled  # set on Settings page meanwhile
    finder.undo()
    assert tray() is (not toggled) and not finder.canUndo and not finder.canRedo  # step dropped
    # Preset option undone after another preset was loaded: dropped too
    cfg.user.setting["speedometer"]["opacity"] = 0.5
    finder.resetOption("widget/speedometer/opacity")
    monkeypatch.setattr(cfg.filename, "setting", "other preset.json")
    finder.undo()
    assert cfg.user.setting["speedometer"]["opacity"] == cfg.default.setting["speedometer"]["opacity"]
    assert not finder.canUndo


def test_overlay_enable_undone_through_control(finder, monkeypatch):
    from neopedal.ui.quick import finder_backend

    toggled = []

    def toggle(self, name):
        toggled.append(name)
        cfg.user.setting[name]["enable"] = not cfg.user.setting[name]["enable"]

    monkeypatch.setattr(type(finder_backend.wctrl), "toggle", toggle)
    before = cfg.user.setting["speedometer"]["enable"]
    finder.toggle("widget/speedometer/enable")
    finder.undo()
    assert toggled == ["speedometer", "speedometer"] and cfg.user.setting["speedometer"]["enable"] == before
    finder.redo()
    assert toggled == ["speedometer"] * 3 and cfg.user.setting["speedometer"]["enable"] != before


def test_notice_undo_button(ui_env, monkeypatch):
    from neopedal.ui.quick import finder_backend
    from neopedal.ui.toast import ActionToast, Toast

    monkeypatch.setattr(finder_backend, "run_after_saving", lambda callback: None)
    page = QWidget()
    page.resize(800, 600)
    backend = finder_backend.FinderBackend(page, lambda entry: None)
    try:
        before = tray()
        backend.toggle(TRAY)
        backend.toggle(TRAY)  # notice replaced, not stacked
        flush()
        notices = page.findChildren(ActionToast)
        assert len(notices) == 1 and "Undo" in notices[0].button.text()
        assert "switched" in notices[0].label.text() and "<b>" in notices[0].label.text()
        notices[0].button.click()  # second switch undone
        assert tray() is (not before) and backend.canRedo
        flush()
        assert not page.findChildren(ActionToast) and len(page.findChildren(Toast)) == 1  # "Undone" notice
        # Undo button of an older change: not the last one any more, nothing undone
        backend.toggle(TRAY)
        change = backend._undo[-1]
        backend.toggle(TRAY)
        backend.undo_change(change)
        assert tray() is (not before) and len(backend._undo) == 3
    finally:
        backend.deleteLater()
        page.deleteLater()
        flush()


def test_notice_texts_translated(ui_env):
    from neopedal.i18n import set_language, trm

    set_language("Français")
    try:
        name = "<b>Opacité</b> (Compteur de vitesse)"
        assert trm(f"{name} switched on") == f"{name} activée"
        assert trm(f"{name} switched off") == f"{name} désactivée"
        assert trm(f"{name} back to default").startswith(f"{name} remise")
        assert trm(f"Undone: {name}") == f"Annulé : {name}"
        assert trm(f"Redone: {name}") == f"Rétabli : {name}"
    finally:
        set_language("English")


def find_item(item, class_prefix: str):
    stack = [item]
    while stack:
        item = stack.pop()
        if item.metaObject().className().startswith(class_prefix):
            return item
        stack.extend(item.childItems())
    return None


def test_qml_page_shortcuts(ui_env, monkeypatch):
    from neopedal.ui.option_finder import OptionFinder
    from neopedal.ui.quick import finder_backend

    monkeypatch.setattr(finder_backend, "run_after_saving", lambda callback: None)
    page = OptionFinder(None)
    try:
        assert not page.view.errors(), [error.toString() for error in page.view.errors()]
        page.show()
        page.activateWindow()
        page.set_search("minimize tray")
        for _ in range(20):
            QCoreApplication.processEvents()
        before = tray()
        page.backend.toggle(TRAY)
        results = find_item(page.view.rootObject(), "QQuickListView")
        QMetaObject.invokeMethod(results, "forceActiveFocus")
        QCoreApplication.processEvents()
        QTest.keyClick(page.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        QCoreApplication.processEvents()
        if page.backend.canUndo:  # window not active (offscreen platform): shortcuts never reached
            pytest.skip("window shortcuts need an active window")
        assert tray() is before and page.backend.canRedo
        QTest.keyClick(page.view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        QCoreApplication.processEvents()
        assert tray() is (not before)
        QTest.keyClick(page.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(
            page.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        QCoreApplication.processEvents()
        assert tray() is (not before) and page.backend.canUndo
    finally:
        page.close()
        flush()


# Settings page
class Host:
    def __init__(self):
        self.applied_sections: list[set[str]] = []

    def confirm(self, text):
        return True

    def applied(self, sections, restart):
        self.applied_sections.append(sections)


@pytest.fixture
def settings(ui_env):
    from neopedal.ui.quick.settings_backend import SettingsBackend

    host = Host()
    backend = SettingsBackend(None, host)
    backend.host = host
    yield backend
    backend.deleteLater()
    flush()


def test_applied_edit_undone_is_pending_again(settings):
    key = "application/show_at_startup"
    saved = cfg.application["show_at_startup"]
    settings.setBool(key, not saved)
    assert settings.apply() and cfg.application["show_at_startup"] is (not saved)
    assert settings.pendingCount == 0 and settings.canUndo and not settings.is_modified()
    settings.undo()  # previous value pending: Apply needed
    assert settings.pendingCount == 1 and settings.is_modified() and settings._pending[key] is saved
    assert cfg.application["show_at_startup"] is (not saved)  # nothing saved by undo
    settings.redo()  # applied value again: nothing pending
    assert settings.pendingCount == 0 and not settings.is_modified()
    settings.undo()
    assert settings.apply() and cfg.application["show_at_startup"] is saved
    assert len(settings.host.applied_sections) == 2


def test_history_across_several_applies(settings):
    show, snap = "application/show_at_startup", "application/snap_distance"
    show_saved, snap_saved = cfg.application["show_at_startup"], cfg.application["snap_distance"]
    settings.setBool(show, not show_saved)
    settings.apply()
    settings.setNumber(snap, snap_saved + 5)
    settings.apply()
    settings.undo()
    assert settings._pending == {snap: snap_saved}
    settings.undo()
    assert settings._pending == {snap: snap_saved, show: show_saved}
    settings.redo()
    settings.redo()
    assert settings._pending == {} and not settings.canRedo
    # Discard after undoing an applied edit: applied value kept
    settings.undo()
    settings.discard()
    assert settings._pending == {} and cfg.application["snap_distance"] == snap_saved + 5 and settings.canUndo


def test_typing_after_apply_is_new_undo_step(settings):
    key = "application/snap_distance"
    saved = cfg.application["snap_distance"]
    settings.typeText(key, str(saved + 1))
    settings.apply()
    settings.typeText(key, str(saved + 2))  # right away: not grouped with keys typed before Apply
    settings.undo()
    assert settings._pending == {}  # back to the applied value, not before it
    settings.undo()
    assert settings._pending == {key: saved}


def test_invalid_state_kept_across_apply(settings):
    key = "notification/font_color_locked_preset"
    saved = cfg.notification[key.split("/")[1]]
    settings.setText(key, "#12")
    settings.setText(key, "#00ff00")
    assert settings.apply()
    settings.undo()
    assert settings.errorCount == 1 and settings._invalid[key][0] == "#12"
    settings.undo()
    assert settings.errorCount == 0 and settings._pending == {key: saved}


def test_undo_skips_options_gone_since(settings):
    settings._undo.append(({"gone/option": 1, "application/snap_distance": 7}, {"gone/other": ("x", "reason")}))
    settings.undo()
    assert settings._pending == {"application/snap_distance": 7} and settings._invalid == {}
    assert settings.apply()


def test_reset_category_after_apply(settings):
    key = "application/snap_distance"
    default = cfg.default.config["application"]["snap_distance"]
    settings.selectCategory("overlay_style")  # Overlay Editing: saved in application section
    settings.setNumber(key, default + 3)
    settings.apply()
    settings.resetCategory()
    assert settings._pending.get(key) == default
    settings.undo()
    assert key not in settings._pending
    settings.undo()
    assert settings._pending.get(key) == default  # value before the applied edit
