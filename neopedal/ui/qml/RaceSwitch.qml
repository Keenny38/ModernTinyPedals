import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator switch: on / off input of the backend (key), or own checked state (no key),
// label wraps in narrow columns, tooltip on hover
AbstractButton {
    id: control
    property var store  // page: inputs
    property string key: ""
    property string tip: ""
    property bool on: key !== "" && store ? Boolean(store.inputs[key]) : checked
    signal switched(bool on)

    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    Layout.fillWidth: true
    implicitHeight: Math.max(Math.round(theme.em * 2), label.implicitHeight + theme.em * 0.4)
    implicitWidth: track.width + label.implicitWidth + theme.em * 0.6
    opacity: enabled ? 1 : 0.5
    Accessible.role: Accessible.CheckBox
    Accessible.checked: on
    Accessible.name: text

    ToolTip.visible: tip !== "" && hovered
    ToolTip.text: tip
    ToolTip.delay: 600

    onClicked: {
        if (key !== "")
            backend.setInput(key, !on)
        switched(!on)
    }
    Keys.onSpacePressed: clicked()

    contentItem: Item {
        Rectangle {
            id: track
            width: theme.em * 2.2
            height: theme.em * 1.2
            radius: height / 2
            anchors.verticalCenter: parent.verticalCenter
            color: control.on ? theme.accent : (control.hovered ? theme.hover : theme.raised)
            border.width: control.on ? 0 : 1
            border.color: control.activeFocus ? theme.accent : theme.border
            Behavior on color { ColorAnimation { duration: 150 } }
            Rectangle {
                width: parent.height - theme.em * 0.36
                height: width
                radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                x: control.on ? parent.width - width - theme.em * 0.18 : theme.em * 0.18
                color: control.on ? "white" : theme.dimText
                Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            }
        }
        Text {
            id: label
            text: control.text
            color: theme.text
            wrapMode: Text.Wrap
            anchors.left: track.right
            anchors.leftMargin: theme.em * 0.5
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
