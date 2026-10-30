"""UI/UX audit 2026-10-29, foundations lot: surfaces & shadows, type roles, shared components (cards, page header,
menus, segmented glyphs, pills, tally, chips, HUD action, transport button, rank line), dialog bridge of page
backends, toasts routed to QML pages, small text input window, styled shared tooltip"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from neopedal.ui.quick import qml_folder_imports


def settle(count: int = 5):
    for _ in range(count):
        QApplication.processEvents()


@pytest.fixture
def page(ui_env, tmp_path):
    """make(body): QML body (items of a 900 x 700 Item) loaded in a page view (theme, i18n, pageState & dialogs
    like every page), shown; (view, root, warnings) returned"""
    from neopedal.ui.quick import create_quick_view

    made = []

    def make(body: str, size=(900, 700)):
        parent = QWidget()
        parent.resize(*size)
        view = create_quick_view(parent, "Card.qml", {})
        warnings: list[str] = []
        engine = view.engine()
        engine.setOutputWarningsToStandardError(False)
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        wrapper = tmp_path / f"page{len(made)}.qml"
        wrapper.write_text(
            "import QtQuick\nimport QtQuick.Controls.Basic\nimport QtQuick.Layouts\n" + qml_folder_imports()
            + f"\nItem {{\n    id: root\n    width: {size[0]}; height: {size[1]}\n{body}\n}}\n", encoding="utf-8")
        view.setSource(QUrl.fromLocalFile(str(wrapper)))
        assert not view.errors(), [error.toString() for error in view.errors()]
        view.resize(*size)
        parent.move(-6000, -6000)
        parent.show()
        settle()
        made.append(parent)
        return view, view.rootObject(), warnings

    yield make
    for parent in made:
        view = parent.findChild(QWidget)
        if view is not None and hasattr(view, "setSource"):
            view.setSource(QUrl())
        parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def named(root, name):
    found = root.findChild(object, name)
    assert found is not None, name
    return found


def click(view, item, point=None):
    point = item.mapToScene(point if point is not None else item.boundingRect().center()).toPoint()
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)
    settle()


# --- Shared components load in every theme without warnings
@pytest.mark.parametrize("palette", ("Modern Dark", "Legacy Light"))
def test_new_components_load_without_warnings(page, palette):
    from neopedal.ui import set_style_palette

    set_style_palette(palette)
    try:
        view, root, warnings = page('''
    property int opened: 0
    property int removed: 0
    property int toggled: 0
    ColumnLayout {
        width: parent.width
        TpPageHeader {
            objectName: "header"; title: "What's New"; subtitle: "Version 0.28.0"; count: "3"
            status: [Pill { objectName: "statusPill"; text: "New"; tint: theme.gain }]
            TpButton { text: "Action" }
        }
        TpText { objectName: "title"; role: "title"; text: "Title" }
        TpText { objectName: "overline"; role: "overline"; text: "Session" }
        TpText { objectName: "numeric"; role: "numeric"; text: "1:23.456" }
        TpText { objectName: "caption"; role: "caption"; text: "Caption" }
        TpSectionCard { objectName: "plainCard"; title: "Stints"; glyph: "x"; count: "3"; Text { text: "body"; textFormat: Text.PlainText } }
        TpSectionCard {
            objectName: "clickCard"; eyebrow: "Last session"; title: "Spa"; clickable: true; tip: "Open"
            onOpened: root.opened++
            trailing: [Pill { text: "LMU" }]
            footer: [TpButton { objectName: "footerButton"; text: "Debrief" }]
            Text { text: "content"; textFormat: Text.PlainText }
        }
        TpSectionCard { objectName: "bareCard"; Text { text: "no header"; textFormat: Text.PlainText } }
        Row {
            spacing: 8
            Pill { objectName: "solidPill"; text: "Error"; solid: true; tint: theme.lossFill; glyph: "x"; fallback: "!" }
            Pill { objectName: "stagePill"; text: "Stage"; onStage: true }
            TpTally { objectName: "liveTally"; live: true; text: "On Air"; actionText: "Cut" }
            TpTally { objectName: "offTally"; live: false; text: "Off Air" }
            TpChip { objectName: "chip"; text: "Class: Hypercar"; selected: true; removable: true; onRemoveRequested: root.removed++ }
            TpTransportButton { objectName: "transport"; glyph: "x"; fallback: "»"; tip: "Play fast"; current: true; caption: "½" }
            TpTransportButton { primary: true; glyph: "x"; fallback: ">"; tip: "Play" }
        }
        TpRankLine { objectName: "rankLine"; Layout.fillWidth: true; labelShown: true; label: "Silver"
                     points: [{ "x": 0, "y": 0.2 }, { "x": 1, "y": 0.6 }] }
        TpSegmented {
            objectName: "views"; name: "View"
            options: [{ "glyph": "a", "tip": "Cards" }, { "glyph": "b", "text": "List" }, "Screen"]
        }
        TpButton { id: hudButton; objectName: "hudButton"; text: "HUD"; onClicked: hudMenu.toggleBelow(hudButton) }
    }
    TpMenu {
        id: hudMenu
        objectName: "hudMenu"
        TpHudAction { objectName: "hudChat"; key: "chat"; text: "Chat"; hudState: ({ "chat": true, "mfd": false })
                      onToggleRequested: function(key) { root.toggled++ } }
        TpHudAction { key: "missing"; text: "Missing"; hudState: ({ "chat": true }) }
    }
    readonly property int shadowStatus: shadow.status
    Rectangle { width: 60; height: 30; color: theme.surfaceFlyout; TpShadow { id: shadow } }
    TpDialogHost {}
''')
        assert warnings == []
        assert root.property("shadowStatus") == 1  # Image.Ready: picture next to TpShadow.qml
        assert named(root, "overline").property("font").capitalization() == QFont.Capitalization.AllUppercase
        assert named(root, "numeric").property("tabular") and not named(root, "caption").property("tabular")
        assert named(root, "caption").property("color") == view.rootContext().contextProperty("theme").property("dimText")
        assert named(root, "bareCard").property("headerShown") is False
        assert named(root, "plainCard").property("headerShown") is True
        assert named(root, "hudChat").property("checked") and named(root, "hudChat").property("enabled")
    finally:
        set_style_palette("Modern Dark")


def test_text_roles_display_face_only_for_titles(page):
    from neopedal.ui.quick import display_font

    _view, root, warnings = page('''
    TpText { objectName: "title"; role: "title"; text: "Title" }
    TpText { objectName: "body"; text: "Body" }
''')
    assert warnings == []
    family, style = display_font()
    assert named(root, "title").property("font").family() == family
    if style:
        assert named(root, "title").property("font").styleName() == style
    assert named(root, "body").property("font").styleName() == ""


def test_clickable_section_card_opens_by_click_and_keys(page):
    view, root, warnings = page('''
    property int opened: 0
    property int footer: 0
    readonly property color cardBorder: card.border.color
    TpSectionCard {
        id: card
        objectName: "card"; width: 400; height: 200; title: "Preset"; clickable: true
        onOpened: root.opened++
        footer: [TpButton { objectName: "footerButton"; text: "Switch"; onClicked: root.footer++ }]
        Text { text: "Default"; textFormat: Text.PlainText }
    }
''')
    card = named(root, "card")
    theme = view.rootContext().contextProperty("theme")
    click(view, card, QPointF(card.width() / 2, card.height() / 2))
    assert root.property("opened") == 1
    button = named(root, "footerButton")
    click(view, button)
    assert root.property("footer") == 1 and root.property("opened") == 1  # buttons keep their own clicks
    assert button.mapToItem(card, QPointF(0, button.height())).y() == pytest.approx(card.height() - theme.property("padCard"), abs=1)
    card.forceActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.keyClick(view, Qt.Key.Key_Space)
    settle()
    assert root.property("opened") == 3
    QTest.mouseMove(view, card.mapToScene(QPointF(10, 10)).toPoint())
    QTest.qWait(300)  # color fades in
    assert card.property("hovered") and card.property("color") == theme.property("surfaceHover")
    assert root.property("cardBorder") != theme.property("accent")  # hover: surface, not accent
    assert warnings == []


def test_menu_toggle_below_closes_on_second_click(page):
    view, root, warnings = page('''
    TpButton {
        id: source; objectName: "source"; x: 100; y: 100; text: "More"
        onClicked: menu.toggleBelow(source)
    }
    TpMenu { id: menu; objectName: "menu"; TpMenuItem { text: "One" } }
''')
    source, menu = named(root, "source"), named(root, "menu")
    click(view, source)
    QTest.qWait(50)
    assert menu.property("visible")
    item = menu.property("contentItem")
    assert menu.property("y") >= 0
    popup_top = menu.property("parent").mapToScene(QPointF(0, menu.property("y"))).y()
    assert popup_top >= source.mapToScene(QPointF(0, source.height())).y()  # below the button
    click(view, source)  # same button again: closed, not opened again
    QTest.qWait(250)
    assert not menu.property("visible")
    click(view, source)
    QTest.qWait(50)
    assert menu.property("visible")
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=source.mapToScene(QPointF(-60, 300)).toPoint())  # outside
    QTest.qWait(250)
    assert not menu.property("visible")
    assert item is not None and warnings == []


def test_segmented_glyph_options_and_radio_keys(page):
    view, root, warnings = page('''
    property int chosen: 0
    readonly property string firstName: views.optionName(views.options[0])
    readonly property string secondName: views.optionName(views.options[1])
    TpSegmented {
        id: views
        objectName: "views"; name: "View"; currentIndex: root.chosen
        options: [{ "glyph": "a", "fallback": "C", "tip": "Cards" }, { "glyph": "b", "text": "List" }, "Screen"]
        onActivated: function(index) { root.chosen = index }
    }
''')
    views = named(root, "views")
    views.forceActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Down)
    QTest.keyClick(view, Qt.Key.Key_Right)
    settle()
    assert root.property("chosen") == 2
    QTest.keyClick(view, Qt.Key.Key_Up)
    settle()
    assert root.property("chosen") == 1
    assert root.property("firstName") == "Cards" and root.property("secondName") == "List"  # icon only: its tip
    assert views.property("implicitWidth") > 0 and warnings == []


def test_chip_removable_by_button_and_delete_key(page):
    view, root, warnings = page('''
    property int removed: 0
    property int clicked: 0
    TpChip { objectName: "chip"; text: "Hypercar"; selected: true; removable: true
             onRemoveRequested: root.removed++; onClicked: root.clicked++ }
''')
    chip = named(root, "chip")
    remove = [child for child in chip.findChildren(QObject) if child.property("tip") == "Remove Hypercar"]
    assert remove
    click(view, remove[0])
    assert root.property("removed") == 1 and root.property("clicked") == 0
    chip.forceActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    settle()
    assert root.property("removed") == 2 and warnings == []


# --- Dialog bridge
@pytest.fixture
def bridged(page):
    """Page with a TpDialogHost: (view, root, bridge, host widget)"""
    view, root, warnings = page("    TpDialogHost { objectName: \"host\" }")
    bridge = view.rootContext().contextProperty("dialogs")
    assert bridge.property("attached") and warnings == []
    return view, root, bridge, view.parentWidget()


def test_text_input_in_page_refused_then_accepted(bridged):
    from neopedal.ui.quick import dialogs

    _view, root, bridge, host = bridged
    names = []
    dialogs.ask_text(host, "New Theme", "Theme name for <b>&lt;Spa&gt;</b>:",
                     lambda text: names.append(text) or text != "Taken", "Dusk")
    settle()
    dialog, field = named(root, "bridgeDialog"), named(root, "bridgeField")
    assert dialog.property("visible") and field.property("text") == "Dusk"
    assert "&lt;Spa&gt;" in named(root, "bridgeMessage").property("text")  # escaped name, never markup
    field.setProperty("text", "Taken")
    named(root, "host").accept()
    settle()
    assert dialog.property("visible") and bridge.pending == 1  # refused: input kept
    field.setProperty("text", "Night")
    named(root, "host").accept()
    QTest.qWait(250)
    assert names == ["Taken", "Night"] and bridge.pending == 0 and not dialog.property("visible")


def test_confirm_in_page_async_and_queued(bridged):
    from neopedal.ui.quick import dialogs

    _view, root, bridge, host = bridged
    results = []
    dialogs.confirm(host, "Delete Laps", "Move 3 laps to trash?", "Move to Trash", results.append, danger=True)
    dialogs.confirm(host, "Second", "Again?", "Do it", lambda chosen: results.append(("second", chosen)))
    settle()
    dialog = named(root, "bridgeDialog")
    assert dialog.property("visible") and dialog.property("danger") and dialog.property("title") == "Delete Laps"
    assert bridge.pending == 2 and results == []
    named(root, "host").accept()  # first: chosen
    settle()
    assert results == [True] and dialog.property("visible") and dialog.property("title") == "Second"  # next one
    dialog.close()  # Esc / Cancel
    QTest.qWait(250)
    settle()
    assert results == [True, ("second", False)] and bridge.pending == 0


def test_enter_answers_confirm_on_default_button(bridged):
    """Confirm opened without field: accept button focused, Enter accepts; danger: Cancel focused, Enter cancels"""
    from neopedal.ui.quick import dialogs

    view, _root, bridge, host = bridged
    view.window().show()
    results = []
    dialogs.confirm(host, "Watch", "Watch in game?", "Watch", results.append)
    QTest.qWait(250)
    settle()
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.qWait(250)
    settle()
    assert results == [True] and bridge.pending == 0
    dialogs.confirm(host, "Delete", "Delete for good?", "Delete", results.append, danger=True)
    QTest.qWait(250)
    settle()
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.qWait(250)
    settle()
    assert results == [True, False] and bridge.pending == 0


def test_alert_in_page_and_cancel_on_unload(bridged):
    from neopedal.ui.quick import dialogs

    _view, root, bridge, host = bridged
    closed, results = [], []
    dialogs.alert(host, "Error", "Not a Google Sheets address.", "error", on_closed=lambda: closed.append(1))
    settle()
    assert named(root, "bridgeDialog").property("showCancel") is False
    named(root, "host").accept()
    settle()
    assert closed == [1]
    dialogs.confirm(host, "Watch", "Watch in game?", "Watch", results.append)
    settle()
    _view.setSource(QUrl())  # page unloaded: pending request cancelled, never left waiting
    settle()
    assert results == [False] and bridge.pending == 0 and not bridge.property("attached")


def test_widget_dialogs_answer_without_host_or_when_patched(page, monkeypatch):
    """No TpDialogHost (or page hidden): widget dialogs as before; patched entry points of tests still answer"""
    from PySide6.QtWidgets import QMessageBox

    from neopedal.ui import _common
    from neopedal.ui.quick import dialogs

    view, _root, _warnings = page("    Item {}")
    host = view.parentWidget()
    assert dialogs.page_bridge(host) is None  # no host item
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    results = []
    dialogs.confirm(host, "Reset", "Reset?", "Reset", results.append)
    assert results == [True]
    shown = []
    monkeypatch.setattr(_common.TextInputDialog, "show", lambda self: shown.append(self))
    dialogs.ask_text(host, "Name", "Name:", lambda text: True)
    assert len(shown) == 1 and isinstance(shown[0], _common.TextInputDialog)
    shown[0].deleteLater()
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[1:]))
    dialogs.alert(host, "Error", "Bad <b>file</b>")
    assert warned == [("Error", "Bad <b>file</b>")]


def test_patched_entry_points_win_over_the_page(bridged, monkeypatch):
    """Tests patching QMessageBox.question / a host's confirm_operation / TextInputDialog.show keep answering after a
    page adds a TpDialogHost"""
    from PySide6.QtWidgets import QMessageBox

    from neopedal.ui import _common
    from neopedal.ui.quick import dialogs

    _view, _root, bridge, host = bridged
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    results = []
    dialogs.confirm(host, "Reset", "Reset?", "Reset", results.append)
    assert results == [False] and bridge.pending == 0
    monkeypatch.undo()
    host.confirm_operation = lambda *args, **kwargs: True  # a page dialog's confirm_operation replaced
    dialogs.confirm(host, "Reset", "Reset?", "Reset", results.append)
    assert results == [False, True] and bridge.pending == 0
    del host.confirm_operation
    shown = []
    monkeypatch.setattr(_common.TextInputDialog, "open", lambda self: shown.append(self))
    dialogs.ask_text(host, "Name", "Name:", lambda text: True)
    assert len(shown) == 1 and bridge.pending == 0
    shown[0].deleteLater()


# --- Toasts
def test_toast_routed_to_page_with_host(bridged):
    from neopedal.ui.toast import show_toast

    _view, root, bridge, host = bridged
    calls = []
    assert show_toast(host, "Laps moved: <b>Spa</b>", action_text="Undo", action=lambda: calls.append(1)) is None
    settle()
    toast = named(root, "bridgeToast")
    assert toast.property("shown") and toast.property("actionText") == "Undo" and toast.property("level") == "success"
    assert toast.property("text") == "Laps moved: <b>Spa</b>"
    bridge.toastAction()
    bridge.toastAction()  # once
    settle()
    assert calls == [1]
    show_toast(host, "Could not save", level="error")
    settle()
    assert toast.property("level") == "error" and toast.property("actionText") == ""


def test_widget_toast_levels_hover_and_durations(ui_env):
    from neopedal.ui.toast import ActionToast, Toast, show_toast, toast_duration

    host = QWidget()
    host.resize(600, 400)
    try:
        toast = show_toast(host, "Saved <b>file</b>", level="error")
        assert isinstance(toast, Toast) and toast.property("level") == "error"
        assert toast.accessibleName() == "Saved file"
        assert toast._timer.interval() == toast_duration(len("Saved file"), error=True)
        QApplication.sendEvent(toast, QEvent(QEvent.Type.Enter))
        assert not toast._timer.isActive()  # kept while hovered
        QApplication.sendEvent(toast, QEvent(QEvent.Type.Leave))
        assert toast._timer.isActive() and toast._timer.remainingTime() > toast_duration(10) - 200
        action = show_toast(host, "Deleted", action_text="Undo", action=lambda: None)
        assert isinstance(action, ActionToast) and action.property("level") == "info"
        assert action._timer.interval() == toast_duration(len("Deleted"), action=True)
    finally:
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_toast_durations_same_as_qml(page):
    from neopedal.ui.toast import toast_duration

    _view, root, _warnings = page('''
    TpToast { objectName: "plain"; text: "Saved" }
    TpToast { objectName: "long"; text: "A much longer message telling what happened to the laps"; error: true; actionText: "Undo" }
''')
    assert named(root, "plain").property("shownTime") == toast_duration(len("Saved"))
    text = "A much longer message telling what happened to the laps"
    assert named(root, "long").property("shownTime") == toast_duration(len(text), error=True, action=True)


# --- Text input window, shared tooltip
def test_text_input_is_a_small_modal_window(ui_env):
    from neopedal.ui._common import TextInputDialog, embedded_host

    host = QWidget()
    try:
        dialog = TextInputDialog(host, "Rename", "Name:", lambda text: True, "old")
        assert embedded_host(dialog) is None and not TextInputDialog.EMBED_IN_APP
        dialog.show()
        settle()
        assert dialog.isWindow() and dialog.windowModality() == Qt.WindowModality.WindowModal
        dialog.accepting()
        assert not dialog.isVisible()
    finally:
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_shared_tooltip_in_app_look(page):
    view, root, warnings = page('''
    readonly property var tipBackground: ToolTip.toolTip.background
    readonly property bool plain: ToolTip.toolTip.contentItem.textFormat === Text.PlainText
''')
    background = root.property("tipBackground")
    theme = view.rootContext().contextProperty("theme")
    assert background is not None and background.property("color") == theme.property("surfaceFlyout")
    assert root.property("plain") and warnings == []
