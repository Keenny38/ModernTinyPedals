"""UI/UX audit 2026-10-29, configuration lot: Hotkeys page in QML (sections, search, "assigned only", conflicts,
clear with undo, capture dialog in the page, page built without QML warnings in English & French)"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, qInstallMessageHandler

from neopedal import i18n
from neopedal.setting import cfg
from neopedal.template.setting_shortcuts import SHORTCUTS_MODULE, SHORTCUTS_PRESET, SHORTCUTS_WIDGET


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def backend(ui_env, monkeypatch):
    from neopedal.ui.quick import hotkey_backend

    calls = []
    for action in ("reload", "enable", "disable"):
        monkeypatch.setattr(type(hotkey_backend.kctrl), action, lambda self, _action=action: calls.append(_action))
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: 0)
    cfg.application["enable_global_hotkey"] = True
    page = hotkey_backend.HotkeyBackend(None)
    page.page_shown()
    yield page
    page.release()
    page.deleteLater()
    flush()


def headers(page) -> dict[str, dict]:
    return {row["section"]: row for row in page.model.rows if row["header"]}


def bindings(page) -> list[str]:
    return [row["key"] for row in page.model.rows if not row["header"]]


def test_sections_split_and_labels(backend):
    from neopedal.ui.quick.hotkey_backend import SECTIONS, section_of

    assert list(headers(backend)) == list(SECTIONS)
    assert section_of("director_toggle") == "Broadcast Director" and section_of("spectate_mode") == "Spectate"
    assert section_of(next(iter(SHORTCUTS_PRESET))) == "Preset"
    assert section_of(next(iter(SHORTCUTS_WIDGET))) == "Overlays"
    assert section_of(next(iter(SHORTCUTS_MODULE))) == "Module"
    assert section_of("overlay_lock") == "General"
    rows = {row["key"]: row for row in backend.model.rows}
    widget = next(iter(SHORTCUTS_WIDGET))
    assert "widget" not in rows[widget]["label"].lower()  # overlay name without prefix
    assert headers(backend)["General"]["count"] == sum(
        1 for row in backend.model.rows if not row["header"] and row["section"] == "General")


def test_section_folded_and_unfolded_while_searching(backend):
    backend.toggleSection("Overlays")
    assert not headers(backend)["Overlays"]["expanded"]
    assert not any(key in SHORTCUTS_WIDGET for key in bindings(backend))
    backend.setSearch(next(iter(SHORTCUTS_WIDGET)).replace("widget_", "").replace("_", " "))
    assert any(key in SHORTCUTS_WIDGET for key in bindings(backend))  # search shows folded sections
    backend.setSearch("")
    backend.toggleSection("Overlays")
    assert headers(backend)["Overlays"]["expanded"]


def test_search_and_assigned_only(backend):
    cfg.user.shortcuts["overlay_lock"]["bind"] = "ctrl+l"
    backend.refresh()
    backend.setAssignedOnly(True)
    assert bindings(backend) == ["overlay_lock"] and backend.filtered and backend.shownCount == 1
    assert list(headers(backend)) == ["General", "Spectate", "Broadcast Director", "Preset", "Overlays", "Module"]
    assert headers(backend)["Overlays"]["count"] == 0
    backend.setAssignedOnly(False)
    backend.setSearch("ctrl + l")  # binding text found too
    assert bindings(backend) == ["overlay_lock"]
    backend.setSearch("zzz nothing")
    assert backend.model.rows == []
    backend.clearFilters()
    assert not backend.filtered and len(bindings(backend)) == backend.totalCount


def test_conflicts_marked_on_both_rows(backend):
    cfg.user.shortcuts["overlay_lock"]["bind"] = "ctrl+l"
    cfg.user.shortcuts["overlay_auto_hide"]["bind"] = "ctrl+l"
    backend.refresh()
    rows = {row["key"]: row for row in backend.model.rows}
    assert rows["overlay_lock"]["conflict"] and rows["overlay_auto_hide"]["conflict"]
    assert rows["overlay_visibility"]["conflict"] == "" and backend.conflictCount == 2


def test_clear_row_with_undo_keeps_new_binding(backend):
    cfg.user.shortcuts["overlay_lock"]["bind"] = "ctrl+l"
    backend.refresh()
    notices = []
    backend.notice.connect(lambda text, undoable: notices.append((text, undoable)))
    backend.clear("overlay_lock")
    assert cfg.user.shortcuts["overlay_lock"]["bind"] == "" and notices[-1][1] and backend.canUndo
    backend.undo()
    assert cfg.user.shortcuts["overlay_lock"]["bind"] == "ctrl+l" and not notices[-1][1]
    backend.clearAll()
    cfg.user.shortcuts["overlay_lock"]["bind"] = "alt+k"  # bound again meanwhile: kept by undo
    backend.undo()
    assert cfg.user.shortcuts["overlay_lock"]["bind"] == "alt+k"


def test_nothing_cleared_or_captured_while_hotkeys_off(backend):
    cfg.user.shortcuts["overlay_lock"]["bind"] = "ctrl+l"
    cfg.application["enable_global_hotkey"] = False
    backend.refresh()
    backend.clear("overlay_lock")
    backend.clearAll()
    backend.startCapture("overlay_lock")
    assert cfg.user.shortcuts["overlay_lock"]["bind"] == "ctrl+l" and backend.captureKey == ""


def test_preset_hotkey_capture_chooses_preset(backend):
    name = next(iter(SHORTCUTS_PRESET))
    for preset in ("race", "quali"):
        with open(f"{cfg.path.settings}{preset}.json", "w", encoding="utf-8") as file:
            file.write("{}")
    cfg.user.shortcuts[name]["preset"] = "race"
    backend.startCapture(name)
    assert backend.captureIsPreset and backend.presetChoices[0] == "Select a preset …"
    assert backend.presetChoices[backend.presetIndex] == "race"
    backend.setPresetIndex(backend.presetChoices.index("quali"))
    backend.saveCapture()
    assert cfg.user.shortcuts[name]["preset"] == "quali"


@pytest.fixture
def page(ui_env, monkeypatch):
    from neopedal.ui import hotkey_view
    from neopedal.ui.quick import hotkey_backend

    for action in ("reload", "enable", "disable"):
        monkeypatch.setattr(type(hotkey_backend.kctrl), action, lambda self: None)
    monkeypatch.setattr(hotkey_backend, "get_key_state_function", lambda: lambda code: 0)
    cfg.application["enable_global_hotkey"] = True
    widget = hotkey_view.HotkeyList(None)
    widget.resize(900, 700)
    yield widget
    widget.close()
    widget.deleteLater()
    flush()


def item_texts(view) -> set[str]:
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


@pytest.mark.parametrize("language", ("English", "Français"))
def test_page_built_and_capture_dialog_opened_without_qml_warnings(page, language):
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    i18n.set_language(language)
    try:
        assert page.view is None  # built when first shown
        page.show()
        flush()
        assert page.view is not None and not page.view.errors(), [error.toString() for error in page.view.errors()]
        texts = item_texts(page.view)
        if language == "English":
            assert {"Hotkeys", "General", "Clear All", "Assigned only"} <= texts
        else:
            assert {"Raccourcis", "Général", "Tout effacer", "Attribués seulement"} <= texts
        root = page.view.rootObject()
        root.openCapture("overlay_lock")
        flush()
        assert page.backend.captureKey == "overlay_lock" and page.backend.capturing
        dialog = next(item for item in root.findChildren(QObject) if item.metaObject().className().startswith(
            "HotkeyCaptureDialog"))
        assert dialog.property("opened") or dialog.property("visible")
        page.backend.cancelCapture()  # Esc
        flush()
        assert not page.backend.capturing
        page.backend.clearAll()  # toast shown (nothing bound: no toast either way)
        assert not page.view.grabFramebuffer().isNull()
    finally:
        i18n.set_language("English")
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


def test_page_closed_ends_capture(page, monkeypatch):
    from neopedal.ui.quick import hotkey_backend

    calls = []
    monkeypatch.setattr(type(hotkey_backend.kctrl), "enable", lambda self: calls.append("enable"))
    page.show()
    flush()
    page.backend.startCapture("overlay_lock")
    assert page.backend.capturing
    page.close()
    assert not page.backend.capturing and calls == ["enable"]
