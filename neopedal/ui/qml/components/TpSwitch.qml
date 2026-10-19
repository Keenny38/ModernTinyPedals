import QtQuick
import QtQuick.Controls.Basic

// Toggle switch with label, knob slides with the checked state.
// Long labels: cut with "..." (full label in tooltip), or wrapped over lines with wrap: true
AbstractButton {
    id: control
    checkable: true
    hoverEnabled: true
    focusPolicy: Qt.TabFocus  // Tab reaches it, Space or Enter toggles
    property string tip: ""
    property bool wrap: false
    Accessible.role: Accessible.CheckBox
    Accessible.name: text !== "" ? text : tip
    Accessible.description: text !== "" ? tip : ""
    Accessible.checked: checked
    implicitHeight: Math.max(Math.round(theme.controlHeight), wrap ? label.implicitHeight + theme.em * 0.5 : 0)
    implicitWidth: track.width + label.implicitWidth + theme.em * 0.6
    opacity: enabled ? 1 : theme.disabledOpacity

    ToolTip.visible: (tip !== "" || label.truncated) && (hovered || visualFocus)
    ToolTip.text: tip !== "" ? (label.truncated ? text + "\n" + tip : tip) : text
    ToolTip.delay: theme.tipDelay
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()
    // Focused switch takes Enter & Space: page shortcuts on these keys do not fire
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
            event.accepted = true
    }

    contentItem: Item {
        Rectangle {
            id: track
            width: theme.em * 2.4
            height: theme.em * 1.3
            radius: height / 2
            anchors.verticalCenter: parent.verticalCenter
            color: control.checked ? (control.hovered ? Qt.darker(theme.accentFill, 1.07) : theme.accentFill)
                 : (control.hovered ? theme.hover : theme.raised)
            border.width: control.checked ? 0 : 1
            border.color: theme.border
            Behavior on color { ColorAnimation { duration: theme.motionBase } }
            FocusRing { visible: control.visualFocus }
            Rectangle {
                width: parent.height - theme.em * 0.4
                height: width
                radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                x: control.checked ? parent.width - width - theme.em * 0.2 : theme.em * 0.2
                color: control.checked ? "white" : theme.dimText
                Behavior on x { NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutCubic } }
            }
        }
        Text {
            id: label
            text: control.text
            color: theme.text
            width: Math.max(0, Math.min(implicitWidth, control.width - track.width - theme.em * 0.5))  // cut when squeezed
            elide: control.wrap ? Text.ElideNone : Text.ElideRight
            wrapMode: control.wrap ? Text.WordWrap : Text.NoWrap
            maximumLineCount: control.wrap ? 3 : 1
            anchors.left: track.right
            anchors.leftMargin: theme.em * 0.5
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
