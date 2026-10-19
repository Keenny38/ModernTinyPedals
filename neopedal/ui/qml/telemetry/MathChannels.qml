import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Math channels editor: channels computed from others by an expression (+ - * / abs min max d, numbers, pi g deg),
// built-in ones (understeer angle, brake release & throttle application rates), saved with viewer settings.
// Click a channel name below the form to put it in the expression. Typed changes not saved yet: a click beside
// keeps the editor open, Close asks before dropping them.
TpPopup {
    id: editor

    property string editing: ""  // name of math channel being changed, empty: new one
    property string error: ""
    property string savedName: ""  // form as last loaded or saved (changes since: dirty)
    property string savedExpression: ""
    property string savedUnit: ""
    readonly property bool dirty: nameField.text !== savedName || expressionField.text !== savedExpression
                                  || unitField.text !== savedUnit

    parent: Overlay.overlay  // centered on page, wherever it is declared
    modal: true
    // Typed changes: neither a click beside nor Esc closes it at once (Esc asks, see contentItem keys)
    closePolicy: dirty ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: Math.min((parent ? parent.width : theme.em * 50) - theme.em * 4, theme.em * 46)
    height: Math.min((parent ? parent.height : theme.em * 40) - theme.em * 4, theme.em * 40)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    onOpened: edit(null)

    // Form filled with math channel (null: new one)
    function edit(item) {
        editing = item ? item.name : ""
        nameField.text = item ? item.name : ""
        expressionField.text = item ? item.expression : ""
        unitField.text = item ? item.unit : ""
        savedName = nameField.text
        savedExpression = expressionField.text
        savedUnit = unitField.text
        error = ""
        savedNote.shown = false
        nameField.forceActiveFocus()
    }
    function check() {
        savedNote.shown = false
        error = nameField.text === "" && expressionField.text === "" ? ""
              : backend.math.check(editing, nameField.text, expressionField.text)
    }
    function save() {
        var refused = backend.math.save(editing, nameField.text, expressionField.text, unitField.text)
        if (refused === "") {
            editing = nameField.text
            savedName = nameField.text
            savedExpression = expressionField.text
            savedUnit = unitField.text
            savedNote.shown = true  // saved: told beside Save
        }
        error = refused
    }
    function insert(name) {
        expressionField.insert(expressionField.cursorPosition, name)
        expressionField.forceActiveFocus()
        check()
    }
    // Close: typed changes not saved are dropped only once confirmed
    function requestClose() {
        if (dirty) discardDialog.open()
        else close()
    }

    contentItem: ColumnLayout {
        spacing: theme.space3
        // Esc with typed changes: asked first (Esc of a field only leaves the field)
        Keys.onEscapePressed: function(event) {
            event.accepted = true
            editor.requestClose()
        }

        TpCardHeader { level: "popup"; title: i18n.tr("Math Channels") }
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Expression over channel names: + - * / ( ), abs(x), min(a, b), max(a, b), d(x) change per second, numbers, pi, g, deg. Values in recorded units (km/h, °C, pedals & steering 0 to 1).")
            color: theme.dimText
            wrapMode: Text.WordWrap
            font.pointSize: theme.fontSmall
        }

        // Math channels: click to change or remove
        Flow {
            Layout.fillWidth: true
            spacing: theme.space2
            visible: backend.math.items.length > 0
            Repeater {
                model: backend.math.items
                TpButton {
                    required property var modelData
                    text: modelData.name + (modelData.unit ? " (" + modelData.unit + ")" : "")
                    flat: true
                    size: "sm"
                    checked: editor.editing === modelData.name
                    tip: modelData.expression
                    onClicked: editor.edit(modelData)
                }
            }
        }
        // Built-in math channels
        Flow {
            Layout.fillWidth: true
            spacing: theme.space2
            Text { text: i18n.tr("Built-in:"); color: theme.dimText; height: Math.round(theme.controlHeightSm); verticalAlignment: Text.AlignVCenter }
            Repeater {
                model: backend.math.presets
                TpButton {
                    required property var modelData
                    required property int index
                    text: "+ " + modelData.title
                    flat: true
                    size: "sm"
                    tip: modelData.expression
                    onClicked: editor.error = backend.math.addPreset(index)
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: theme.space3
            rowSpacing: theme.space2
            Text { text: i18n.tr("Name"); color: theme.dimText }
            TpTextField {
                id: nameField
                objectName: "mathNameField"
                Layout.fillWidth: true
                tip: i18n.tr("Name")
                placeholderText: i18n.tr("Understeer Angle")
                onTextEdited: editor.check()
                onAccepted: if (editor.error === "" && expressionField.text !== "") editor.save()
            }
            Text { text: i18n.tr("Expression"); color: theme.dimText }
            TpTextField {
                id: expressionField
                Layout.fillWidth: true
                tip: i18n.tr("Expression")
                invalid: editor.error !== ""
                placeholderText: "max(-d(brake), 0) * 100"
                font.family: theme.monoFont
                onTextEdited: editor.check()
                onAccepted: if (editor.error === "" && nameField.text !== "") editor.save()
            }
            Text { text: i18n.tr("Unit"); color: theme.dimText }
            TpTextField {
                id: unitField
                tip: i18n.tr("Unit")
                placeholderText: "%/s"
                Layout.preferredWidth: theme.em * 6
                onTextEdited: savedNote.shown = false
            }
        }
        // Why the formula is refused, beside the fields (warning icon, never color alone)
        RowLayout {
            Layout.fillWidth: true
            visible: editor.error !== ""
            spacing: theme.space2
            Icon { glyph: ""; fallback: "!"; color: theme.loss; Layout.alignment: Qt.AlignTop }  // warning
            Text {
                Layout.fillWidth: true
                text: editor.error
                color: theme.loss
                wrapMode: Text.WordWrap
                Accessible.role: Accessible.AlertMessage
                Accessible.name: text
            }
        }

        // Channel names usable in expression
        TpSectionLabel { Layout.fillWidth: true; text: i18n.tr("Channels (click to insert):") }
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 4
            clip: true
            contentHeight: names.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            Flow {
                id: names
                width: parent.width
                spacing: theme.space2
                Repeater {
                    model: backend.math.inputs
                    TpChip {
                        required property var modelData
                        size: "sm"
                        text: modelData
                        tip: i18n.tr("Insert in expression")
                        onClicked: editor.insert(modelData)
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpButton { text: i18n.tr("New"); flat: true; onClicked: editor.edit(null) }
            TpButton {
                text: i18n.tr("Remove")
                flat: true
                enabled: editor.editing !== ""
                onClicked: removeDialog.open()
                TpConfirmDialog {
                    id: removeDialog
                    title: i18n.tr("Remove this math channel?")
                    text: i18n.tr("Its formula is deleted and it leaves the charts.")
                    acceptText: i18n.tr("Remove")
                    onAccepted: { backend.math.remove(editor.editing); editor.edit(null) }
                }
            }
            Item { Layout.fillWidth: true }
            Text {  // saved: told beside the button (fades when typing again)
                id: savedNote
                property bool shown: false
                opacity: shown ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                text: "✓ " + i18n.tr("Saved")
                color: theme.gain
            }
            TpButton {
                text: i18n.tr("Save")
                accent: true
                enabled: editor.error === "" && nameField.text !== "" && expressionField.text !== ""
                onClicked: editor.save()
            }
            TpButton { text: i18n.tr("Close"); onClicked: editor.requestClose() }
        }
    }
    TpConfirmDialog {
        id: discardDialog
        objectName: "mathDiscardDialog"
        title: i18n.tr("Discard changes to this math channel?")
        text: i18n.tr("Name, expression or unit typed since last save are lost.")
        acceptText: i18n.tr("Discard")
        onAccepted: editor.close()
    }
}
