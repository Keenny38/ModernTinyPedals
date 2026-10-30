"""UI/UX audit 2026-10-29, table editors: one QML table editor (quick/table_editor.py, qml/editors/TableEditor.qml)
for brakes, tyre compounds, car classes & brands, track info & heatmaps: one save, Delete key & disabled Delete,
search, header sort, content-sized columns, units, heatmap preview, primary preset among existing presets"""

import importlib
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from neopedal.setting import cfg
from neopedal.ui._common import BaseEditor
from tests.test_perf_page_state import qml_warnings  # noqa: F401

EDITORS = {
    "brakes": ("brake_editor", "BrakeEditor"),
    "brands": ("vehicle_brand_editor", "VehicleBrandEditor"),
    "classes": ("vehicle_class_editor", "VehicleClassEditor"),
    "compounds": ("tyre_compound_editor", "TyreCompoundEditor"),
    "tracks": ("track_info_editor", "TrackInfoEditor"),
    "heatmap": ("heatmap_editor", "HeatmapEditor"),
}


class Env:
    def __init__(self, saved, warnings):
        self.saved = saved
        self.warnings = warnings


@pytest.fixture
def env(ui_env, monkeypatch):
    """Warnings recorded, no module reload after saving, exceptions in Qt slots fail the test"""
    warnings = []
    errors = []
    monkeypatch.setattr(BaseEditor, "reloading", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard))
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: errors.append(exc_info[1]))
    yield Env(ui_env, warnings)
    assert not errors


def build(name: str):
    module_name, class_name = EDITORS[name]
    module = importlib.import_module(f"neopedal.ui.{module_name}")
    return getattr(module, class_name)(None)


def close(editor):
    editor.set_unmodified()
    editor.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def pump(count: int = 5):
    for _ in range(count):
        QCoreApplication.processEvents()


@pytest.mark.parametrize("name", list(EDITORS))
def test_page_loads_without_qml_warnings(name, env, qml_warnings):  # noqa: F811
    editor = build(name)
    try:
        editor.resize(900, 600)
        editor.show()
        pump()
        assert editor.view is not None and editor.view.rootObject() is not None
        assert not qml_warnings, qml_warnings
    finally:
        close(editor)
    assert not qml_warnings, qml_warnings


# --- Page interaction (keys, header, toolbar)
def items(root) -> list:
    stack, found = [root], []
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found


def find(editor, test) -> list:
    return [item for item in items(editor.view.quickWindow().contentItem()) if test(item)]


def named(editor, name: str):
    return find(editor, lambda item: item.objectName() == name)[0]


def headers_of(editor) -> list:
    found = find(editor, lambda item: item.metaObject().className().startswith("TpHeaderCell") and item.isVisible())
    return sorted(found, key=lambda item: item.mapToScene(QPointF(0, 0)).x())  # columns from left


def key(editor, code, modifiers=Qt.KeyboardModifier.NoModifier, text: str = ""):
    if text:
        QTest.keyClicks(editor.view, text)
    else:
        QTest.keyClick(editor.view, code, modifiers)
    pump(10)


def center_of(item) -> QPoint:
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    return QPoint(int(point.x()), int(point.y()))


@pytest.fixture
def french():
    from neopedal import i18n

    i18n.set_language("Français")
    yield
    i18n.set_language("English")


@pytest.fixture
def shown(env, qml_warnings):  # noqa: F811
    """Editor page shown, table focused"""
    opened = []

    def showing(name: str, width: int = 1000):
        editor = build(name)
        opened.append(editor)
        editor.setMinimumSize(1, 1)
        editor.resize(width, 600)
        editor.show()
        editor.activateWindow()
        editor.view.setFocus()
        pump(10)
        named(editor, "editorTable").forceActiveFocus()
        pump()
        return editor

    yield showing
    for editor in opened:
        if editor.isVisible():
            close(editor)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not qml_warnings, qml_warnings


def test_delete_disabled_without_selection_then_delete_key_with_undo(shown, env):
    editor = shown("compounds")
    backend = editor.backend
    rows = len(backend.rows)
    backend.clearSelection()
    pump()
    assert not named(editor, "deleteAction").property("enabled")  # no "No data selected." alert
    key(editor, Qt.Key.Key_Delete)
    assert len(backend.rows) == rows and not env.warnings
    key(editor, Qt.Key.Key_Down)  # cursor on first row: selected
    assert backend.selectedCount == 1 and named(editor, "deleteAction").property("enabled")
    key(editor, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert backend.selectedCount == 2
    key(editor, Qt.Key.Key_Delete)
    assert len(backend.rows) == rows - 2 and backend.last_notice[2]  # toast with Undo, no question
    backend.undo()
    assert len(backend.rows) == rows


def test_enter_edits_cell_esc_cancels_without_closing(shown):
    editor = shown("classes")
    backend = editor.backend
    backend.select(backend.keys[0], 1, 0)
    pump()
    old = backend.rows[0][1]
    key(editor, Qt.Key.Key_Return)  # edit alias
    field = editor.view.quickWindow().activeFocusItem()
    assert field.property("text") == old
    key(editor, 0, text="XY")
    key(editor, Qt.Key.Key_Escape)  # put back, page kept open
    assert editor.isVisible() and backend.rows[0][1] == old
    key(editor, Qt.Key.Key_F2)
    key(editor, 0, text="ALIAS")
    key(editor, Qt.Key.Key_Return)
    assert backend.rows[0][1] == "ALIAS" and editor.is_modified()
    key(editor, Qt.Key.Key_Escape)  # selection cleared first
    assert editor.isVisible() and backend.selectedCount == 0


def test_ctrl_s_keeps_value_being_typed(shown):
    editor = shown("classes")
    backend = editor.backend
    backend.select(backend.keys[0], 1, 0)
    pump()
    key(editor, Qt.Key.Key_F2)
    key(editor, 0, text="TYPED")
    editor.save_action()()  # Ctrl+S while the field is open
    assert cfg.user.classes[backend.rows[0][0]]["alias"] == "TYPED" and not editor.is_modified()


def test_right_click_in_selection_keeps_it(shown):
    editor = shown("classes")
    backend = editor.backend
    backend.select(backend.keys[0], 0, 0)
    backend.select(backend.keys[1], 0, 1)
    backend.setCurrent(backend.keys[0], 2)
    assert backend.selectedCount == 2 and backend.currentKey == backend.keys[0] and backend.currentColumn == 2


def test_invalid_number_kept_in_field_until_valid(shown):
    editor = shown("brakes")
    backend = editor.backend
    backend.select(backend.keys[0], 1, 0)
    pump()
    key(editor, Qt.Key.Key_F2)
    field = editor.view.quickWindow().activeFocusItem()
    key(editor, 0, text="abc")
    assert field.property("invalid")
    key(editor, Qt.Key.Key_Return)  # refused: still editing
    assert editor.view.quickWindow().activeFocusItem() is field
    field.setProperty("text", "3,5")
    key(editor, Qt.Key.Key_Return)
    assert backend.rows[0][1] == 3.5


def test_header_click_sorts_and_search_filters(shown):
    editor = shown("compounds")
    backend = editor.backend
    QTest.mouseClick(editor.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     center_of(headers_of(editor)[0]))
    pump()
    names = [row[0] for row in backend.rows]
    assert names == sorted(names, key=str.casefold) and backend.sortColumn == 0
    assert editor.is_modified()  # order saved
    backend.setFilter("wet")
    pump()
    assert 0 < backend.shownCount < backend.rowCount
    assert all("wet" in " ".join(row["cells"]).casefold() for row in backend.model.rows)
    backend.setFilter("")
    assert backend.shownCount == backend.rowCount


@pytest.mark.parametrize("name", ["tracks", "brakes", "heatmap"])
def test_french_headers_never_cut(name, french, shown):
    editor = shown(name, width=500)  # narrow page: table scrolls sideways, headers whole
    headers = headers_of(editor)
    assert headers
    for header in headers:
        assert header.width() + 0.5 >= header.implicitWidth(), header.property("text")


def test_unsaved_changes_bar_apply_and_discard(shown):
    """Same unsaved changes bar as Settings (2026-10-29 audit E3): shown once edited, Apply saves & applies (page
    kept open), Discard puts the saved rows back with Undo"""
    editor = shown("brakes")
    texts = {item.property("text") for item in find(editor, lambda item: item.isVisible())}
    assert "Save" not in texts and "Apply" not in texts and "Close" not in texts  # nothing pending: no bar
    bar = named(editor, "pendingBar")
    assert not bar.isVisible()
    rows = len(editor.backend.rows)
    editor.backend.addRow()
    QTest.qWait(400)  # bar slid in or out
    apply = named(editor, "pendingApply")
    assert bar.isVisible() and apply.isVisible() and apply.property("text") == "Apply"
    QTest.mouseClick(editor.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(apply))
    QTest.qWait(400)  # bar slid in or out
    assert not editor.is_modified() and editor.isVisible()  # saved & applied, page kept open
    assert editor.save_action() == editor.applying
    assert len(editor.backend.rows) == rows + 1
    editor.backend.addRow()
    QTest.qWait(400)  # bar slid in or out
    QTest.mouseClick(editor.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     center_of(named(editor, "pendingDiscard")))
    QTest.qWait(400)  # bar slid in or out
    assert not editor.is_modified() and len(editor.backend.rows) == rows + 1  # saved rows back
    assert editor.backend.canUndo and named(editor, "pendingUndo").isVisible()  # bar kept a moment with Undo
    editor.backend.undo()
    assert editor.is_modified() and len(editor.backend.rows) == rows + 2


# --- Units, presets, heatmap preview
def test_track_values_follow_user_units(env, monkeypatch):
    monkeypatch.setitem(cfg.user.setting["units"], "distance_unit", "Feet")
    monkeypatch.setitem(cfg.user.setting["units"], "speed_unit", "KPH")
    monkeypatch.setattr(cfg.user, "tracks", {"Spa": {
        "pit_entry": 100.0, "pit_exit": 300.0, "pit_speed": 25.0, "speed_trap": 2000.0, "orientation": 0.0,
        "sunrise": "06:30", "sunset": "21:15", "preset": ""}}, raising=False)
    editor = build("tracks")
    try:
        backend = editor.backend
        headers = [column["header"] for column in backend.columns]
        assert headers[1] == "Pit entry (ft)" and headers[3] == "Pit speed (km/h)" and headers[4] == "Speed Trap (ft)"
        cells = backend.model.rows[0]["cells"]
        assert cells[1] == "328.084" and cells[3] == "90"
        assert backend.setCell(backend.keys[0], 3, "60")  # typed in km/h
        assert backend.setCell(backend.keys[0], 1, cells[1])  # unchanged text: value kept exactly
        editor.applying()
        saved = cfg.user.tracks["Spa"]
        assert saved["pit_speed"] == pytest.approx(60 / 3.6) and saved["pit_entry"] == 100.0  # stored in m/s & m
        monkeypatch.setitem(cfg.user.setting["units"], "speed_unit", "MPH")  # changed while page hidden
        backend.page_shown()
        assert backend.columns[3]["header"] == "Pit speed (mph)"
    finally:
        close(editor)


def test_primary_preset_among_existing_presets(env, monkeypatch):
    monkeypatch.setattr(cfg.user, "tracks", {"Spa": {"preset": "deleted_one"}, "Monza": {"preset": "race"}},
                        raising=False)
    for preset in ("race", "quali"):
        with open(f"{cfg.path.settings}{preset}.json", "w", encoding="utf-8") as file:
            file.write("{}")
    editor = build("tracks")
    try:
        backend = editor.backend
        assert backend.model.rows[0]["marks"][8] == "missing" and backend.model.rows[1]["marks"][8] == ""
        choices = backend.choices(backend.keys[0], 8)
        assert [choice["value"] for choice in choices] == ["deleted_one", "", "default", "quali", "race"]
        assert choices[0]["label"].endswith("(not found)") and choices[1]["label"] == "None"
        assert not backend.checkCell(8, "typo") and backend.checkCell(8, "quali")
        assert backend.setCell(backend.keys[0], 8, "quali")
        assert backend.model.rows[0]["marks"][8] == ""
    finally:
        close(editor)


def test_primary_preset_set_on_presets_page_kept(env, monkeypatch):
    """Same setting as Presets page "Set Primary for Track" (saved at once there): never overwritten by an editor
    opened before, shown when the editor is shown again"""
    monkeypatch.setattr(cfg.user, "tracks", {"Spa": {"preset": ""}, "Monza": {"preset": "race"}}, raising=False)
    for preset in ("race", "quali"):
        with open(f"{cfg.path.settings}{preset}.json", "w", encoding="utf-8") as file:
            file.write("{}")
    editor = build("tracks")
    try:
        backend = editor.backend
        assert backend.setCell(backend.keys[1], 8, "quali")  # Monza changed here
        cfg.user.tracks["Spa"]["preset"] = "race"  # Presets page meanwhile
        cfg.user.tracks["Monza"]["preset"] = ""
        assert backend.setCell(backend.keys[0], 6, "07:00")
        editor.applying()
        assert cfg.user.tracks["Spa"]["preset"] == "race" and cfg.user.tracks["Monza"]["preset"] == "quali"
        cfg.user.tracks["Spa"]["preset"] = "quali"  # Presets page while editor hidden
        backend.page_shown()
        assert backend.rows[0][8] == "quali" and not editor.is_modified()
    finally:
        close(editor)


def test_heatmap_preview_follows_edits(env):
    editor = build("heatmap")
    try:
        backend = editor.backend
        seen = []
        backend.bandsChanged.connect(lambda: seen.append(1))
        assert [band["color"] for band in backend.bands] == [row[1] for row in sorted(backend.rows)]
        assert backend.setCell(backend.keys[-1], 1, "#123456")  # unsaved edit shown
        assert seen and "#123456" in [band["color"] for band in backend.bands]
        coldest = min(range(len(backend.rows)), key=lambda number: backend.rows[number][0])
        start = backend.rows[coldest][0]
        backend.select(backend.keys[coldest], 0, 0)
        backend.offsetSelected(10, False)
        assert backend.rows[coldest][0] == pytest.approx(start + 10)
        assert backend.bands[0]["label"] == backend.display(0, start + 10)
    finally:
        close(editor)


def test_heatmap_offset_in_user_unit(env, monkeypatch):
    monkeypatch.setitem(cfg.user.setting["units"], "temperature_unit", "Fahrenheit")
    editor = build("heatmap")
    try:
        backend = editor.backend
        assert backend.columns[0]["header"] == "Temperature (°F)"
        row_key = backend.keys[1]
        assert backend.setCell(row_key, 0, "212")
        assert backend.rows[1][0] == pytest.approx(100)  # stored in Celsius
        backend.select(row_key, 0, 0)
        backend.offsetSelected(18, False)  # +18 °F = +10 °C
        assert backend.rows[1][0] == pytest.approx(110)
    finally:
        close(editor)


# --- Dead code & wording
def test_dead_code_removed():
    from neopedal.ui import _common, brake_editor

    for name in ("column_texts", "ClockTableItem", "QVAL_HEATMAP"):
        assert not hasattr(_common, name)
    with open(brake_editor.__file__, encoding="utf-8") as file:
        source = file.read()
    assert "open_replace_dialog" not in source and "TableBatchReplace" not in source


def test_brand_import_plain_wording(env):
    editor = build("brands")
    try:
        sources = editor.backend.importSources
        assert not any("Rest API" in source["label"] or "Primary" in source["label"]
                       or "Alternative" in source["label"] for source in sources)
        assert all("REST API" in source["tip"] or "JSON" in source["tip"] for source in sources)
    finally:
        close(editor)


def test_confirm_keeps_no_bound_method(env, monkeypatch):
    """Confirmed actions kept by name & a weak reference: no reference cycle page -> page (QObject freed by GC
    off-thread), nothing run once the page is closed"""
    import functools
    import weakref

    editor = build("brakes")
    asked = []
    try:
        backend = editor.backend
        monkeypatch.setattr(editor, "ask", lambda title, text, action_text, on_result: asked.append(on_result))
        backend.askReset()
        on_result = asked[0]
        assert isinstance(on_result, functools.partial) and isinstance(on_result.args[0], weakref.ref)
        on_result(False)
        assert not editor.is_modified()
        on_result(True)
        assert editor.is_modified()
        backend.askReset()
    finally:
        close(editor)
    asked[1](True)  # answered after the page closed: nothing run, no error


# --- Page dialogs & cell editors
def popup_named(editor, name: str):
    """Popup (dialog, menu) of page by object name"""
    from PySide6.QtCore import QObject

    return editor.view.rootObject().findChild(QObject, name)


def settle(seconds: float = 0.4):
    """Popup transitions run"""
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()


def test_choice_cell_edited_from_list(shown):
    editor = shown("brakes")
    backend = editor.backend
    backend.select(backend.keys[0], 2, 0)  # heatmap name
    pump()
    key(editor, Qt.Key.Key_Return)
    settle()
    combo = find(editor, lambda item: item.metaObject().className().startswith("TpCombo") and item.isVisible())[0]
    assert combo.property("activeFocus") or combo.property("popup").property("visible")  # list opened at once
    names = list(cfg.user.heatmap)
    other = next(name for name in names if name != backend.rows[0][2])
    combo.setProperty("currentIndex", combo.property("count") - 1)
    combo.activated.emit(names.index(other))  # entry chosen
    pump(20)
    assert backend.rows[0][2] == other and editor.is_modified()
    assert named(editor, "editorTable").property("activeFocus")  # back to table


def test_added_row_name_typed_at_once(shown):
    editor = shown("classes")
    backend = editor.backend
    backend.addRow()  # nothing in session: new name to type
    pump(20)
    field = editor.view.quickWindow().activeFocusItem()
    assert field.property("text") == "New Class Name 1"
    key(editor, 0, text="Hypercar 2")
    key(editor, Qt.Key.Key_Return)
    assert backend.rows[-1][0] == "Hypercar 2"


def test_reset_asks_in_page_dialog(shown, monkeypatch):
    from neopedal.ui._common import ORIGINAL_DIALOG_METHODS
    from neopedal.ui.quick.dialogs import page_bridge

    monkeypatch.setattr(QMessageBox, "question", ORIGINAL_DIALOG_METHODS["question"])  # not answered by the test

    editor = shown("brakes")
    backend = editor.backend

    backend.askReset()
    settle()
    bridge = page_bridge(editor)
    assert bridge is not None and bridge.current["kind"] == "confirm"  # dialog of the page (TpDialogHost)
    assert bridge.current["acceptText"] == "Reset"
    assert not editor.is_modified()
    bridge.answer(bridge.current["id"], True)
    settle()
    assert editor.is_modified()


def test_heatmap_new_preset_dialog(shown):
    editor = shown("heatmap")
    backend = editor.backend
    dialog = popup_named(editor, "nameDialog")
    dialog.setProperty("copy", False)
    dialog.open()
    settle()
    field = editor.view.quickWindow().activeFocusItem()
    key(editor, 0, text="thermal_infrared")  # exists
    assert dialog.property("error") == "Preset already exists." and not dialog.property("acceptEnabled")
    field.setProperty("text", "my_heatmap")
    pump()
    assert dialog.property("acceptEnabled")
    key(editor, Qt.Key.Key_Return)
    assert backend.selected_key == "my_heatmap" and editor.is_modified()
    assert backend.presetNames[backend.presetIndex] == "my_heatmap"


def test_heatmap_offset_dialog_typed_then_enter(shown):
    editor = shown("heatmap")
    backend = editor.backend
    backend.select(backend.keys[1], 0, 0)
    start = backend.rows[1][0]
    dialog = popup_named(editor, "offsetDialog")
    dialog.open()
    settle()
    field = editor.view.quickWindow().activeFocusItem()
    if field is None or field.property("suffix") is None:  # dialog gives focus to its first field
        field = find(editor, lambda item: item.metaObject().className().startswith("NumberField"))[0]
        field.forceActiveFocus()
    key(editor, 0, text="5")
    assert dialog.property("amount") == 5 and dialog.property("acceptEnabled")  # Apply usable without leaving
    key(editor, Qt.Key.Key_Return)
    settle()
    assert backend.rows[1][0] == pytest.approx(start + 5) and not dialog.property("visible")


def test_color_swatch_opens_picker(shown, monkeypatch):
    editor = shown("classes")
    backend = editor.backend
    monkeypatch.setattr(editor, "pick_color", lambda color: "#123456")
    backend.pickColor(backend.keys[0], 2)
    assert backend.rows[0][2] == "#123456" and editor.is_modified()


# --- Wave 2: long names readable, type to edit, host toast & dialogs
def test_long_name_widens_column_then_tooltip(shown, monkeypatch):
    long_name = "Oreca 07 Gibson Very Long Livery #51"  # longer than the 16 em of the column
    monkeypatch.setattr(cfg.user, "brands", {long_name: "Ferrari", "Short": "X"}, raising=False)
    editor = shown("brands", width=500)
    assert editor.backend.longest[0] == long_name
    cells = [item for item in find(editor, lambda item: item.metaObject().className().startswith("EditorCell"))
             if item.property("value") == long_name]
    assert cells
    value = next(item for item in items(cells[0]) if item.property("role") == "body")
    assert not value.property("truncated")  # column as wide as the name (table scrolls sideways)
    monkeypatch.setattr(cfg.user, "brands", {long_name * 4: "Ferrari"}, raising=False)
    editor.backend.set_rows(editor.backend.load())
    pump(10)
    cells = [item for item in find(editor, lambda item: item.metaObject().className().startswith("EditorCell"))
             if item.property("value") == long_name * 4]
    value = next(item for item in items(cells[0]) if item.property("role") == "body")
    assert value.property("truncated")  # very long: cut, full text in a tooltip on hover
    tips = [child for child in cells[0].children() if child.metaObject().className().startswith("TpToolTip")]
    assert tips
    QTest.mouseMove(editor.view, center_of(cells[0]))
    pump(10)
    assert tips[0].property("text") == long_name * 4


def test_typed_character_starts_edit(shown):
    editor = shown("classes")
    backend = editor.backend
    backend.select(backend.keys[0], 1, 0)
    pump()
    key(editor, 0, text="Z")
    field = editor.view.quickWindow().activeFocusItem()
    assert field.property("text") == "Z"  # value replaced by the typed character
    key(editor, 0, text="Q")
    key(editor, Qt.Key.Key_Return)
    assert backend.rows[0][1] == "ZQ"
    key(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)  # shortcuts with Ctrl still work
    assert backend.selectedCount == len(backend.rows)


def test_notices_go_to_page_toast(env, monkeypatch):
    from neopedal.ui import toast

    shown_toasts = []
    monkeypatch.setattr(toast, "show_toast", lambda widget, text, **kwargs: shown_toasts.append((text, kwargs)))
    editor = build("brakes")
    try:
        backend = editor.backend
        backend.select(backend.keys[0], 0, 0)
        backend.deleteSelected()
        text, options = shown_toasts[-1]
        assert text == "Row deleted" and options["action_text"] == "Undo"
        options["action"]()  # Undo of the toast
        assert len(backend.rows) == len(cfg.user.brakes)
    finally:
        close(editor)
