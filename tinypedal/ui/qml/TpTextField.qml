import QtQuick
import QtQuick.Controls.Basic

// Text input in app look: rounded, accent border while focused, red border when invalid.
// Esc drops focus (escaped signal: page puts its value back) and is always taken: never closes the page.
TextField {
    id: field
    property string tip: ""
    property bool invalid: false
    signal escaped()

    implicitHeight: Math.round(theme.em * 2.05)
    implicitWidth: theme.em * 12
    leftPadding: theme.em * 0.55
    rightPadding: theme.em * 0.55
    verticalAlignment: TextInput.AlignVCenter
    color: theme.text
    placeholderTextColor: theme.dimText
    selectionColor: theme.accent
    selectedTextColor: "white"
    selectByMouse: true
    opacity: enabled ? 1 : 0.5
    Accessible.name: tip !== "" ? tip : placeholderText

    ToolTip.visible: tip !== "" && hovered && !activeFocus
    ToolTip.text: tip
    ToolTip.delay: 700

    background: Rectangle {
        radius: theme.em * 0.4
        color: theme.dark ? Qt.darker(theme.base, 1.3) : Qt.darker(theme.base, 1.03)
        border.width: field.activeFocus || field.invalid ? 1.5 : 1
        border.color: field.invalid ? theme.loss
                    : field.activeFocus ? theme.accent
                    : field.hovered ? Qt.lighter(theme.border, 1.2) : theme.border
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    Keys.onEscapePressed: function(event) {
        event.accepted = true
        field.escaped()
        field.focus = false
    }
}
