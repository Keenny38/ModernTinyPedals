import QtQuick
import QtQuick.Controls.Basic

// Text input in app look: rounded, accent border while focused, red border when invalid.
// Esc drops focus (escaped signal: page puts its value back) and is always taken: never closes the page.
TextField {
    id: field
    property string tip: ""
    property bool invalid: false
    signal escaped()

    implicitHeight: Math.round(theme.fieldHeight)
    implicitWidth: theme.em * 12
    leftPadding: theme.em * 0.55
    rightPadding: theme.em * 0.55
    verticalAlignment: TextInput.AlignVCenter
    color: theme.text
    placeholderTextColor: theme.dimText
    selectionColor: theme.accentFill
    selectedTextColor: theme.accentInk
    selectByMouse: true
    opacity: enabled ? 1 : theme.disabledOpacity
    Accessible.name: tip !== "" ? tip : placeholderText

    ToolTip.visible: tip !== "" && hovered && !activeFocus
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay

    background: Rectangle {
        radius: theme.radiusSm
        color: theme.surfaceSunken
        border.width: field.activeFocus || field.invalid ? 1.5 : 1
        border.color: field.invalid ? theme.loss
                    : field.activeFocus ? theme.accent
                    : field.hovered ? theme.strokeStrong : theme.border
        Behavior on border.color { ColorAnimation { duration: theme.motionFast } }
    }

    Keys.onEscapePressed: function(event) {
        event.accepted = true
        field.escaped()
        field.focus = false
    }
}
