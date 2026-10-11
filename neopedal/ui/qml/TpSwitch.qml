import QtQuick
import QtQuick.Controls.Basic

// Toggle switch with label, knob slides with the checked state
AbstractButton {
    id: control
    checkable: true
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    property string tip: ""
    implicitHeight: Math.round(theme.em * 2.3)
    implicitWidth: track.width + label.implicitWidth + theme.em * 0.6

    ToolTip.visible: tip !== "" && hovered
    ToolTip.text: tip
    ToolTip.delay: 600

    contentItem: Item {
        Rectangle {
            id: track
            width: theme.em * 2.4
            height: theme.em * 1.3
            radius: height / 2
            anchors.verticalCenter: parent.verticalCenter
            color: control.checked ? theme.accent : (control.hovered ? theme.hover : theme.raised)
            border.width: control.checked ? 0 : 1
            border.color: theme.border
            Behavior on color { ColorAnimation { duration: 150 } }
            Rectangle {
                width: parent.height - theme.em * 0.4
                height: width
                radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                x: control.checked ? parent.width - width - theme.em * 0.2 : theme.em * 0.2
                color: control.checked ? "white" : theme.dimText
                Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            }
        }
        Text {
            id: label
            text: control.text
            color: theme.text
            width: Math.min(implicitWidth, control.width - track.width - theme.em * 0.5)  // cut when squeezed
            elide: Text.ElideRight
            anchors.left: track.right
            anchors.leftMargin: theme.em * 0.5
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
