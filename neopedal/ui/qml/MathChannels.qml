import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Math channels editor: channels computed from others by an expression (+ - * / abs min max d, numbers, pi g deg),
// built-in ones (understeer angle, brake release & throttle application rates), saved with viewer settings.
// Click a channel name below the form to put it in the expression.
Popup {
    id: editor

    property string editing: ""  // name of math channel being changed, empty: new one
    property string error: ""

    parent: Overlay.overlay  // centered on page, wherever it is declared
    modal: true
    dim: true
    padding: theme.em * 1.1
    width: Math.min((parent ? parent.width : theme.em * 50) - theme.em * 4, theme.em * 46)
    height: Math.min((parent ? parent.height : theme.em * 40) - theme.em * 4, theme.em * 40)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }
    background: Rectangle {
        radius: theme.radiusXl
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }
    onOpened: edit(null)

    // Form filled with math channel (null: new one)
    function edit(item) {
        editing = item ? item.name : ""
        nameField.text = item ? item.name : ""
        expressionField.text = item ? item.expression : ""
        unitField.text = item ? item.unit : ""
        error = ""
        nameField.forceActiveFocus()
    }
    function check() {
        error = nameField.text === "" && expressionField.text === "" ? ""
              : backend.math.check(editing, nameField.text, expressionField.text)
    }
    function save() {
        var refused = backend.math.save(editing, nameField.text, expressionField.text, unitField.text)
        if (refused === "") editing = nameField.text
        error = refused
    }
    function insert(name) {
        expressionField.insert(expressionField.cursorPosition, name)
        expressionField.forceActiveFocus()
    }

    component Field: TextField {
        id: field
        Layout.fillWidth: true
        color: theme.text
        placeholderTextColor: theme.dimText
        selectByMouse: true
        background: Rectangle {
            radius: theme.radiusMd
            color: theme.base
            border.width: 1
            border.color: field.activeFocus ? theme.accent : theme.border
        }
    }

    contentItem: ColumnLayout {
        spacing: theme.em * 0.5

        Text { text: i18n.tr("Math Channels"); color: theme.text; font.weight: Font.DemiBold; font.pointSize: theme.fontSubtitle }
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
            spacing: theme.em * 0.3
            visible: backend.math.items.length > 0
            Repeater {
                model: backend.math.items
                TpButton {
                    text: modelData.name + (modelData.unit ? " (" + modelData.unit + ")" : "")
                    flat: true
                    implicitHeight: theme.em * 1.8
                    checked: editor.editing === modelData.name
                    tip: modelData.expression
                    onClicked: editor.edit(modelData)
                }
            }
        }
        // Built-in math channels
        Flow {
            Layout.fillWidth: true
            spacing: theme.em * 0.3
            Text { text: i18n.tr("Built-in:"); color: theme.dimText; height: theme.em * 1.8; verticalAlignment: Text.AlignVCenter }
            Repeater {
                model: backend.math.presets
                TpButton {
                    text: "+ " + modelData.title
                    flat: true
                    implicitHeight: theme.em * 1.8
                    tip: modelData.expression
                    onClicked: editor.error = backend.math.addPreset(index)
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: theme.em * 0.5
            rowSpacing: theme.em * 0.35
            Text { text: i18n.tr("Name"); color: theme.dimText }
            Field { id: nameField; placeholderText: i18n.tr("Understeer Angle"); onTextEdited: editor.check() }
            Text { text: i18n.tr("Expression"); color: theme.dimText }
            Field {
                id: expressionField
                placeholderText: "max(-d(brake), 0) * 100"
                font.family: theme.monoFont
                onTextEdited: editor.check()
                onAccepted: if (editor.error === "") editor.save()
            }
            Text { text: i18n.tr("Unit"); color: theme.dimText }
            Field { id: unitField; placeholderText: "%/s"; Layout.fillWidth: false; Layout.preferredWidth: theme.em * 6 }
        }
        Text {
            Layout.fillWidth: true
            visible: editor.error !== ""
            text: editor.error
            color: theme.warning
            wrapMode: Text.WordWrap
        }

        // Channel names usable in expression
        Text { text: i18n.tr("Channels (click to insert):"); color: theme.dimText; font.pointSize: theme.fontSmall }
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
                spacing: theme.em * 0.3
                Repeater {
                    model: backend.math.inputs
                    Rectangle {
                        width: nameText.implicitWidth + theme.em * 0.7
                        height: theme.em * 1.5
                        radius: height / 2
                        color: nameArea.containsMouse ? theme.hover : theme.base
                        border.width: 1
                        border.color: theme.border
                        Text {
                            id: nameText
                            anchors.centerIn: parent
                            text: modelData
                            color: theme.text
                            font.pointSize: theme.fontCaption
                        }
                        MouseArea {
                            id: nameArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: editor.insert(modelData)
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
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
            TpButton {
                text: i18n.tr("Save")
                accent: true
                enabled: editor.error === "" && nameField.text !== "" && expressionField.text !== ""
                onClicked: editor.save()
            }
            TpButton { text: i18n.tr("Close"); onClicked: editor.close() }
        }
    }
}
