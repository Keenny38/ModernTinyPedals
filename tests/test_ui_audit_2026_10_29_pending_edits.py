"""UI/UX audit 2026-10-29, saving & pending edits (E2-E6) and names (V8, V9): one option editor & row menu for
Settings and Overlay Options (typed text taken at each key, Esc back to the saved value, searched words in bold),
"Changed Only" in Settings, one unsaved changes bar (TpPendingBar) & one close question (TpUnsavedDialog), Modules
batch switch at once with Undo, screen view snapping from the edit mode options, On / Off switch labels"""

import os

import pytest

from neopedal.setting import cfg
from neopedal.ui.quick import qml_path
from tests.test_overlay_options import options  # noqa: F401
from tests.test_overlay_options import row as option_row
from tests.test_perf_page_state import qml_warnings  # noqa: F401
from tests.test_settings_page import row as setting_row
from tests.test_settings_page import settings, window  # noqa: F401


def qml_text(name: str) -> str:
    with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
        return file.read()


def option_of_kind(backend, kind: str) -> dict:
    return next(row for row in backend.rows.rows if row["row"] == "option" and row["kind"] == kind
                and not row["locked"])


# --- E2: one option editor
def test_settings_and_overlay_rows_share_one_editor_and_menu():
    editor = qml_text("TpOptionEditor")
    for name in ("SettingRow", "OverlayOptionRow"):
        text = qml_text(name)
        assert "TpOptionEditor {" in text and "Component {" not in text, name  # no editor copy left
        assert "onTextTyped:" in text and "onReverted: backend.revertOption" in text, name
        assert "Qt.Key_Menu" in text and "Qt.RightButton" in text and "More actions" in text, name
        assert "row.marked" in text, name  # searched words in bold
    assert "OptionResultRow" in qml_text("OptionFinder") and "Keys.onMenuPressed" in qml_text("OptionFinder")
    assert editor.count('fallback: "…"') == 2 and 'fallback: "..."' not in editor  # one browse mark
    assert "TpColorSwatch {" in editor and "MouseArea" not in editor  # one color swatch (keyboard & hover, S15)
    for name in ("Settings", "OverlayOptions", "OptionFinder"):
        assert 'i18n.tr("Copy Option Key")' in qml_text(name), name
    assert "Copy Option Name" not in qml_text("OverlayOptions")


def test_overlay_typed_text_taken_at_each_key_then_esc_back_to_saved(options):  # noqa: F811
    backend = options
    backend.selectOverlay("relative")
    row = option_of_kind(backend, "text")
    oid = row["key"]
    name, key = oid.split("/")
    saved = cfg.user.setting[name][key]
    backend.typeText(oid, "A")
    backend.typeText(oid, "AB")
    assert backend.value(name, key) == "AB" and backend.pendingCount == 1  # bar & Ctrl+S see it at once
    assert option_row(backend, oid)["text"] == "AB"  # shown as typed
    backend.setText(oid, "AB")  # field left
    assert len(backend._undo) == 1  # keys typed in a row & the field left: one undo step
    backend.revertOption(oid)  # Esc: saved value back
    assert backend.value(name, key) == saved and backend.pendingCount == 0
    assert option_row(backend, oid)["text"] == saved
    backend.undo()  # typed text again
    assert backend.value(name, key) == "AB"
    backend.discard()


def test_overlay_typed_invalid_number_marked_while_typing(options):  # noqa: F811
    backend = options
    backend.selectOverlay("relative")
    row = option_of_kind(backend, "integer")
    oid = row["key"]
    backend.typeText(oid, "12x")
    assert backend.errorCount == 1 and option_row(backend, oid)["error"] != ""
    assert option_row(backend, oid)["text"] == "12x"
    backend.revertOption(oid)
    assert backend.errorCount == 0 and backend.pendingCount == 0


def test_overlay_copy_key_told_and_folder_opened(options):  # noqa: F811
    backend = options
    backend.copyText("font_color")
    assert backend.host.notices[-1] == "Copied"  # nothing else shows the copy
    opened = []
    backend.host.open_folder = opened.append
    backend.selectOverlay("relative")
    oid = option_of_kind(backend, "text")["key"]
    backend.openFolder(oid)
    assert opened and os.path.isabs(opened[0])
    backend.openFolder("unknown/option")
    assert len(opened) == 1


def test_search_marks_words_in_bold(settings, options):  # noqa: F811
    settings.setSearch("snap dist")
    marked = setting_row(settings, "application/snap_distance")["marked"]
    assert "<b>" in marked and marked.replace("<b>", "").replace("</b>", "") == setting_row(
        settings, "application/snap_distance")["label"]
    settings.setSearch("")
    settings.selectCategory("overlay_style")  # Overlay Editing group
    assert setting_row(settings, "application/snap_distance")["marked"] == ""
    options.selectOverlay("relative")
    word = option_of_kind(options, "bool")["label"].split()[-1]
    options.setSearch(word)
    found = [row for row in options.rows.rows if row["row"] == "option" and word in row["label"]]
    assert found and all(f"<b>{word}</b>" in row["marked"] for row in found)
    options.setSearch("")
    assert all(row["marked"] == "" for row in options.rows.rows)


# --- Settings: "Changed Only"
def test_settings_changed_only_every_category(settings):  # noqa: F811
    cfg.user.config["application"]["snap_distance"] = 25  # saved apart from default
    settings.refresh()
    settings.setNumber("application/minimum_update_interval", 30)
    settings.setChangedOnly(True)
    keys = [row["key"] for row in settings.model.rows]
    assert settings.changedOnly and settings.searching
    assert "application/snap_distance" in keys and "application/minimum_update_interval" in keys
    assert all(row["modified"] or row["changed"] for row in settings.model.rows)
    assert settings.matchCount == len(keys)
    settings.setSearch("snap")
    assert [row["key"] for row in settings.model.rows] == ["application/snap_distance"]  # search & filter
    settings.selectCategory("application")  # a category: search & filter left
    assert not settings.changedOnly and not settings.searching
    settings.discard()


def test_settings_show_first_error_from_bar(settings):  # noqa: F811
    settings.typeText("application/snap_distance", "abc")
    assert settings.errorCount == 1
    settings.selectCategory("user_path")
    settings.showFirstError()
    assert settings.category == "overlay_style" and settings.highlightKey == "application/snap_distance"
    settings.discard()


# --- E3 & E4: one unsaved changes bar, one close question
def test_one_pending_bar_and_verb():
    bar = qml_text("TpPendingBar")
    assert 'i18n.tr("Apply")' in bar and 'i18n.tr("Discard")' in bar and "showErrorRequested" in bar
    for name in ("Settings", "OverlayOptions", "TableEditor", "TrackNotesEditor", "PresetComparePanel"):
        assert "TpPendingBar {" in qml_text(name), name
    assert 'objectName: "saveButton"' not in qml_text("TableEditor")
    assert 'name: "saveButton"' not in qml_text("TrackNotesEditor") and "saveAsButton" in qml_text("TrackNotesEditor")
    assert 'i18n.tr("Save")' not in qml_text("PresetComparePanel")
    for name in ("Settings", "OverlayOptions"):
        assert "interval: 6000" not in qml_text(name), name  # Discard grace kept by the bar only
    for name in ("PresetComparePanel", "MathChannels"):
        text = qml_text(name)
        assert "TpUnsavedDialog {" in text and "onApplyChosen" in text and "onDiscardChosen" in text, name
        assert "TpConfirmDialog {\n        id: discard" not in text, name


def test_track_notes_discard_reads_file_again_with_undo(ui_env, tmp_path):
    from neopedal.ui.track_notes_editor import TrackNotesEditor

    page = TrackNotesEditor(None)
    try:
        backend = page.backend
        backend.addRow()
        assert backend.modified
        rows = backend.rowCount
        backend.discard()  # new notes: one empty note again
        assert not backend.modified and backend.rowCount == rows - 1 and backend.canUndo
        backend.undo()
        assert backend.modified and backend.rowCount == rows
    finally:
        page.backend.set_modified(False)
        page.close()


# --- E6: screen view snapping from the edit mode options
def test_screen_view_snapping_follows_edit_mode_options(ui_env, monkeypatch):
    from neopedal.ui.quick.overlay_backend import OverlayBackend
    from tests.test_overlay_view import FakeControl

    saved = []
    monkeypatch.setattr(type(cfg), "save", lambda *args, **kwargs: saved.append(kwargs.get("config_type")))
    backend = OverlayBackend(None, FakeControl(("fuel",)), lambda name: None, lambda text: False)
    try:
        monkeypatch.setitem(cfg.application, "enable_magnetic_snap", True)
        monkeypatch.setitem(cfg.application, "snap_distance", 25)
        monkeypatch.setitem(cfg.application, "snap_gap", 5)
        monkeypatch.setitem(cfg.application, "show_layout_guides", False)
        assert backend.snapSettings() == {"magnetic": True, "distance": 25, "guides": False}
        backend.setMagneticSnap(False)  # Snap switch of the view: the option of the in-game toolbar
        assert cfg.application["enable_magnetic_snap"] is False and saved
        backend.setMagneticSnap(False)
        assert len(saved) == 1
    finally:
        backend.deleteLater()
    view = qml_text("OverlayScreenView")
    assert "backend.snapSettings()" in view and "Qt.ControlModifier" in view and "Qt.AltModifier" not in view
    assert "view.snapping.guides" in view and "view.snapping.distance" in view


# --- V8, V9
@pytest.mark.parametrize("name", ["Hotkeys", "Spectate", "StreamOverlays", "Settings", "OverlayOptions"])
def test_main_switches_say_enabled_or_disabled(name):
    """One state text for switches: Enabled / Disabled (French: Activé / Désactivé, "On" reads "Oui")"""
    text = qml_text(name)
    assert 'i18n.tr("Enabled") : i18n.tr("Disabled")' in text
    assert 'i18n.tr("On") : i18n.tr("Off")' not in text
    assert 'text: i18n.tr("Enabled")\n' not in text  # state text follows the switch


def test_same_action_same_name():
    assert 'i18n.tr("Export Options...")' not in qml_text("Overlays")
    assert qml_text("Overlays").count('i18n.tr("Export Overlay Settings…")') == 2
    assert 'i18n.tr("Export Overlay Settings…")' in qml_text("OverlayOptions")




# --- Pages in app: row menu (Menu key, right click), Changed only, pending bar, no QML warning
def page_items(view) -> list:
    stack, found = [view.rootObject()], []
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found


def wait(seconds: float = 0.3):
    from PySide6.QtTest import QTest

    QTest.qWait(int(seconds * 1000))


def shown(view, name: str) -> bool:
    from PySide6.QtCore import QObject

    found = view.rootObject().findChild(QObject, name)
    return found is not None and bool(found.property("visible"))


def row_of(item):
    """Option row (SettingRow / OverlayOptionRow) holding item"""
    while item is not None and item.property("marked") is None:
        item = item.parentItem()
    return item


def open_menu_by_keys_and_click(page, field, menu: str):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    field.forceActiveFocus()
    QTest.keyClick(page.view, Qt.Key.Key_Menu)  # Menu key in the editor: more actions
    wait(0.25)
    assert shown(page.view, menu)
    QTest.keyClick(page.view, Qt.Key.Key_Escape)  # menu closed, page kept
    wait(0.25)
    assert not shown(page.view, menu) and page.isVisible()
    row = row_of(field)
    point = row.mapToScene(row.boundingRect().topLeft()).toPoint() + QPoint(int(row.width() * 0.3), int(row.height() - 6))
    QTest.mouseClick(page.view, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, point)
    wait(0.25)
    assert shown(page.view, menu)  # right click: same menu
    QTest.keyClick(page.view, Qt.Key.Key_Escape)
    wait(0.25)


def test_settings_page_row_menu_changed_only_and_bar(window, qml_warnings):  # noqa: F811
    from PySide6.QtCore import QObject

    from neopedal.i18n.options import option_label
    from neopedal.ui.menu import open_config_application

    page = open_config_application(window, "application")
    page.view.setFocus()
    page.backend.focus_option("application", "snap_distance")
    wait()
    label = option_label("snap_distance")
    field = next(item for item in page_items(page.view)
                 if "NumberField" in item.metaObject().className() and item.property("tip") == label)
    open_menu_by_keys_and_click(page, field, "settingMenu")
    page.backend.setNumber("application/snap_distance", 33)
    wait(0.4)
    bar = page.view.rootObject().findChild(QObject, "pendingBar")
    assert bar.property("visible") and bar.property("pendingCount") == 1
    switch = page.view.rootObject().findChild(QObject, "changedOnlySwitch")
    assert switch is not None and switch.property("checked") is False
    page.backend.setChangedOnly(True)
    wait()
    assert switch.property("checked") is True
    assert "application/snap_distance" in [entry["key"] for entry in page.backend.model.rows]
    page.backend.setChangedOnly(False)
    page.backend.discard()
    wait()
    assert not qml_warnings, qml_warnings


def test_overlay_options_page_typing_menu_and_bar(window, qml_warnings):  # noqa: F811
    from PySide6.QtCore import QObject, Qt
    from PySide6.QtTest import QTest

    from neopedal.ui.overlay_options import open_overlay_options

    page = open_overlay_options(window, "relative")
    wait()
    backend = page.backend
    backend.setAdvanced(True)  # every option (simple mode shows switches & choices)
    option = option_of_kind(backend, "text")
    backend.focus_option(*option["key"].split("/"))  # scrolled to
    wait()
    field = next(item for item in page_items(page.view) if "TpTextField" in item.metaObject().className()
                 and item.property("tip") == option["label"] and row_of(item) is not None)
    field.forceActiveFocus()
    QTest.keyClick(page.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(page.view, "Zq")
    wait(0.4)
    assert backend.pendingCount == 1 and field.property("text") == "Zq"  # typed text taken at each key
    bar = page.view.rootObject().findChild(QObject, "pendingBar")
    assert bar.property("visible") and bar.property("pendingCount") == 1
    QTest.keyClick(page.view, Qt.Key.Key_Escape)  # saved value back, page kept
    wait(0.4)
    assert backend.pendingCount == 0 and field.property("text") != "Zq" and page.isVisible()
    open_menu_by_keys_and_click(page, field, "optionMenu")
    assert not qml_warnings, qml_warnings
