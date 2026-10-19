"""UI audit 2026-10-18, configuration zone (Settings, Find Option, Presets, Modules, Setup wizard): pending changes
bar out of the Tab order & Undo kept after Discard, "Copied" notices, Delete key guarded like the menu, wizard steps
done only once shown, pages loaded without QML warnings, shared components & tokens instead of ad-hoc values"""

import os
import re

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QWidget

# Fixtures of the page tests reused here (presets page with "race" & "practice", modules backend)
from test_module_page import modules  # noqa: F401
from test_preset_view import page as preset_page  # noqa: F401

from neopedal.setting import cfg
from neopedal.ui.quick import qml_path

ZONE_QML = (
    "Settings", "SettingRow", "OptionFinder", "OptionResultRow", "Presets", "PresetRow", "PresetDetails", "Modules",
    "ModuleCard", "SetupWizard", "SetupBackdrop", "SetupCard", "SetupDiff", "SetupGame", "SetupHeading", "SetupLook",
    "SetupOverlays", "SetupReady", "SetupStep", "SetupUnits", "SetupWelcome",
)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def settle(count: int = 20):
    for _ in range(count):
        QCoreApplication.processEvents()


def qml_text(name: str) -> str:
    with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
        return file.read()


def find(view, name: str):
    stack = [view.rootObject()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return None


def item_texts(view) -> set[str]:
    texts, stack = set(), [view.quickWindow().contentItem()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str) and item.isVisible():
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def click(view, item):
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(round(point.x()), round(point.y())))
    settle(5)


# Ad-hoc values replaced by shared components & tokens
@pytest.mark.parametrize("name", ZONE_QML)
def test_zone_pages_use_tokens_and_components(name):
    text = qml_text(name)
    assert "Qt.rgba(theme.accent.r" not in text  # theme.tint(), TpIconTile, TpListRow
    assert 'theme.iconFont === "" ?' not in text  # TpButton / Icon fallback
    assert not re.search(r"implicitHeight: Math\.round\(theme\.em \* (1\.9|2|2\.0)\)", text)  # TpButton size
    assert "Qt.lighter(theme.base, 1.3" not in text  # theme.cardBorder
    assert '"#566070"' not in text and '"#23272E"' not in text  # theme.stageTop / stageBottom
    assert "border.color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.5)" not in text  # FocusRing


def test_shared_components_used():
    assert "TpChip {" in qml_text("OptionFinder") and "OverlayChip" not in qml_text("OptionFinder")
    assert "TpNotice {" in qml_text("Modules") and "component Notice" not in qml_text("Modules")
    assert qml_text("PresetDetails").count("TpTag {") == 2
    for name in ("OptionResultRow", "PresetRow", "ModuleCard"):
        assert "FocusRing { target: surface" in qml_text(name)
        assert "TpIconTile {" in qml_text(name)
    assert "TpDialog {" in qml_text("SetupDiff") and "showCancel: false" in qml_text("SetupDiff")
    assert "dismissOnOutside: false" in qml_text("Presets")  # typed preset name never lost by a click beside
    assert "showRange: true" in qml_text("SettingRow")  # allowed values of numbers told
    for name in ("OptionFinder", "Presets", "Modules"):
        assert "search.routeTyped(event)" in qml_text(name) and "charCodeAt" not in qml_text(name)


# Settings: pending changes bar
@pytest.fixture
def settings_page(ui_env, monkeypatch):
    from neopedal.ui import app_settings

    monkeypatch.setattr(app_settings, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)  # never written
    page = app_settings.AppSettings(None)
    page.resize(1100, 760)
    page.show()
    settle()
    yield page
    page.backend.discard()
    page.close()
    page.deleteLater()
    flush()


def bool_option(backend) -> dict:
    return next(row for row in backend.model.rows if row["kind"] == "bool")


def test_pending_bar_hidden_out_of_tab_order_and_undo_after_discard(settings_page):
    backend, view = settings_page.backend, settings_page.view
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        bar = find(view, "pendingBar")
        assert bar is not None and not bar.isVisible()  # folded bar: its buttons take no Tab focus
        option = bool_option(backend)
        backend.setBool(option["key"], not option["checked"])
        QTest.qWait(400)  # bar unfolded: buttons at their place
        assert backend.pendingCount == 1 and bar.isVisible() and bar.isEnabled()
        click(view, find(view, "pendingDiscard"))
        settle()
        # Discarded: bar kept a moment, told in words with an Undo button
        assert backend.pendingCount == 0 and bar.isVisible()
        assert "Changes discarded" in item_texts(view)
        undo = find(view, "pendingUndo")
        assert undo.isVisible() and undo.property("text") == "Undo"
        assert not find(view, "pendingDiscard").isVisible()
        click(view, undo)
        settle()
        assert backend.pendingCount == 1  # change back
        assert "Changes discarded" not in item_texts(view)
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if "qml" in text.lower()], messages


class CopyHost:
    def __init__(self):
        self.toasts: list[str] = []

    def toast(self, text):
        self.toasts.append(text)


def test_copy_tells_copied(ui_env):
    from neopedal.ui.quick.settings_backend import SettingsBackend

    host = CopyHost()
    backend = SettingsBackend(None, host)  # type: ignore[arg-type]
    try:
        backend.copyText("http://192.168.1.2:8080")
        assert host.toasts == ["Copied"]
        backend._host = object()  # host without notices: copy still done
        backend.copyText("1234")
    finally:
        backend.deleteLater()
        flush()


def test_find_option_copy_key_tells_copied(ui_env, monkeypatch):
    from neopedal.ui.quick import finder_backend

    shown = []
    monkeypatch.setattr(finder_backend, "show_toast", lambda parent, text, *args, **kwargs: shown.append(text))
    parent = QWidget()
    backend = finder_backend.FinderBackend(parent, lambda entry: None)
    try:
        backend.copyKey(finder_backend.entry_key(backend.entries[0]))
        assert shown == ["Copied"]
    finally:
        parent.deleteLater()
        flush()


# Presets: Delete key as the menu
def test_delete_key_skips_loaded_preset(preset_page, monkeypatch):  # noqa: F811
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    preset_page.resize(1200, 760)
    preset_page.show()
    settle()
    view = preset_page.view
    presets = find(view, "presetList")
    loaded = next(index for index, row in enumerate(preset_page.backend.model.rows) if row["loaded"])
    presets.setProperty("currentIndex", loaded)
    presets.forceActiveFocus()
    settle()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    settle()
    assert not warnings  # no error box for a key press: loaded preset cannot be deleted (menu says so)
    assert os.path.exists(f"{cfg.path.settings}default.json") or preset_page.backend.model.rows[loaded]["loaded"]


# Modules page loads with its notices (TpNotice) & cards without QML warnings
def test_modules_page_without_qml_warnings(modules):  # noqa: F811
    from neopedal.ui.module_view import ModuleList

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    view = ModuleList(None, modules.test["control"], modules.test["widgets"])
    try:
        view.resize(900, 700)
        view.show()
        settle()
        assert view.view is not None and not view.view.errors()
        assert "Show Log" in item_texts(view.view)  # failing module notice
    finally:
        qInstallMessageHandler(previous)
        view.close()
        view.deleteLater()
        flush()
    assert not [text for text in messages if "qml" in text.lower()], messages


# Setup wizard: a step is done once shown, not when jumped over
def test_wizard_steps_done_only_once_shown(ui_env):
    from neopedal.ui.quick import setup_backend

    backend = setup_backend.SetupBackend(None, detect_games=False)
    try:
        assert backend.visitedSteps == [setup_backend.STEP_WELCOME]
        backend.goTo(setup_backend.STEP_READY)
        assert backend.visitedSteps == [setup_backend.STEP_WELCOME, setup_backend.STEP_READY]
        backend.back()
        assert setup_backend.STEP_READY - 1 in backend.visitedSteps
    finally:
        backend.stop_previews()
        backend.deleteLater()
        flush()
