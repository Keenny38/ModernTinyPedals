import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Cell of a table editor row (TableEditor.qml): value (color swatch, error & "not found" marks), or its editor
// while edited: text field (Enter keeps the value, Esc puts it back, leaving keeps a valid value), list of values
// opened at once (choice & preset cells). Click selects the row (Ctrl toggles, Shift extends: pressedWith),
// double click edits (editRequested), right click asks for the cell menu (menuRequested).
Item {
    id: cell
    property int rowKey: 0
    property int column: 0
    property string kind: "text"
    property string header: ""
    property string value: ""
    property string swatch: ""  // color of a color cell, "" when invalid
    property string mark: ""  // "error" (refused by Save), "missing" (preset or heatmap not found)
    property bool alignEnd: false
    property bool editing: false
    property bool cursor: false  // keyboard cursor on this cell (table focused)
    property string seed: ""  // character typed that started the edit: replaces the text
    property color ink: theme.text
    signal pressedWith(int mode)  // 0 alone, 1 Ctrl, 2 Shift
    signal editRequested()
    signal menuRequested(real x, real y)
    signal editFinished(bool moveNext)

    Accessible.role: Accessible.Cell
    Accessible.name: header + ": " + value + (mark === "missing" ? " (" + i18n.tr("not found") + ")" : "")

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.ArrowCursor
        enabled: !cell.editing
        onPressed: function(mouse) {
            var mode = mouse.modifiers & Qt.ShiftModifier ? 2 : mouse.modifiers & Qt.ControlModifier ? 1 : 0
            if (mouse.button === Qt.RightButton)
                mode = -1  // page keeps a selected row selected
            cell.pressedWith(mode)
            if (mouse.button === Qt.RightButton)
                cell.menuRequested(mouse.x, mouse.y)
        }
        onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) cell.editRequested() }
    }

    // Error: red frame & "!" (never color alone)
    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: theme.radiusSm
        color: "transparent"
        border.width: cell.cursor && !cell.editing ? 1.5 : 1
        border.color: cell.mark === "error" ? theme.loss : theme.accent
        visible: !cell.editing && (cell.cursor || cell.mark === "error")
    }

    Row {
        id: shown
        visible: !cell.editing
        anchors.verticalCenter: parent.verticalCenter
        x: theme.space2
        width: parent.width - theme.space2 * 2
        spacing: theme.space2
        layoutDirection: cell.alignEnd ? Qt.RightToLeft : Qt.LeftToRight

        TpColorSwatch {
            id: swatchBox
            visible: cell.kind === "color"
            focusable: false  // the table moves with the keys, Enter edits the cell
            width: cell.kind === "color" ? Math.round(theme.em * 1.1) : 0
            height: width
            anchors.verticalCenter: parent.verticalCenter
            color: cell.swatch
            onClicked: {
                cell.pressedWith(0)
                backend.pickColor(cell.rowKey, cell.column)
            }
        }
        TpText {
            id: markText
            visible: cell.mark !== ""
            anchors.verticalCenter: parent.verticalCenter
            role: "caption"
            text: cell.mark === "missing" ? "(" + i18n.tr("not found") + ")" : "!"
            color: cell.mark === "missing" ? theme.warning : theme.loss
            font.weight: Font.DemiBold
        }
        TpText {
            id: valueText
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, shown.width - (swatchBox.visible ? swatchBox.width + shown.spacing : 0)
                            - (markText.visible ? markText.implicitWidth + shown.spacing : 0))
            role: cell.alignEnd ? "numeric" : "body"
            text: cell.value
            elide: cell.alignEnd ? Text.ElideLeft : Text.ElideRight
            horizontalAlignment: cell.alignEnd ? Text.AlignRight : Text.AlignLeft
            color: cell.ink
        }
    }

    // Cut value: full text on hover
    HoverHandler {
        id: cellHover
        enabled: valueText.truncated
    }
    TpToolTip {
        visible: cellHover.hovered && valueText.truncated && !cell.editing
        text: cellHover.hovered ? cell.value : ""
        delay: theme.tipDelay
    }

    Loader {
        anchors.fill: parent
        active: cell.editing
        sourceComponent: cell.kind === "choice" || cell.kind === "preset" ? listEditor : textEditor
        onLoaded: item.start()  // in the scene now: focus taken
    }

    Component {
        id: textEditor
        TpTextField {
            id: field
            property bool done: false
            function start() {
                forceActiveFocus()
                if (cell.seed !== "") {
                    text = cell.seed  // typed on the table: replaces the value (spreadsheet)
                    cursorPosition = text.length
                } else {
                    selectAll()
                }
            }
            function commit(moveNext) {
                if (done)
                    return true
                if (!backend.setCell(cell.rowKey, cell.column, text))
                    return false  // invalid: kept open, marked
                done = true
                cell.editFinished(moveNext)
                return true
            }
            text: backend.editText(cell.rowKey, cell.column)
            invalid: !backend.checkCell(cell.column, text)
            horizontalAlignment: cell.alignEnd ? TextInput.AlignRight : TextInput.AlignLeft
            maximumLength: cell.kind === "color" ? 9 : 200
            Accessible.name: cell.header
            Keys.onReturnPressed: commit(false)
            Keys.onEnterPressed: commit(false)
            Keys.onTabPressed: commit(true)
            Connections {
                target: backend
                function onCommitEdits() {
                    if (!field.done && backend.checkCell(cell.column, field.text))
                        backend.setCell(cell.rowKey, cell.column, field.text)  // field stays open
                }
            }
            onEscaped: {
                done = true  // value put back
                cell.editFinished(false)
            }
            onActiveFocusChanged: {
                if (activeFocus || done)
                    return
                done = true
                backend.setCell(cell.rowKey, cell.column, text)  // left: valid value kept, invalid one put back
                cell.editFinished(false)
            }
        }
    }

    Component {
        id: listEditor
        TpCombo {
            id: combo
            property bool done: false
            property double startedAt: 0
            function start() {
                currentIndex = Math.max(0, indexOfValue(cell.value))
                startedAt = Date.now()
                popup.width = Math.max(width, theme.em * 16)  // whole names, "(not found)" too
                forceActiveFocus()
                popup.open()
            }
            function finish() {
                if (done)
                    return
                done = true
                cell.editFinished(false)
            }
            model: backend.choices(cell.rowKey, cell.column)
            textRole: "label"
            valueRole: "value"
            tip: cell.header
            // Release of the key that started editing (Enter, F2) would close the list at once: taken
            Keys.onReleased: function(event) {
                event.accepted = [Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2].indexOf(event.key) >= 0
                                 && Date.now() - startedAt < 500
            }
            onActivated: function(index) {
                if (done)
                    return
                backend.setCell(cell.rowKey, cell.column, valueAt(index))
                finish()
            }
            Connections {
                target: combo.popup
                function onClosed() { Qt.callLater(combo.finish) }  // after activated (same click)
            }
        }
    }
}
