import QtQuick

// Message at bottom of page for a few seconds (click: hidden), slides in. show() after each new message
Rectangle {
    id: toast
    property string text: ""
    property bool error: false  // warning icon & red border, else check
    property int duration: 5000  // ms shown
    property bool shown: false

    function show() { shown = true; hideTimer.restart() }

    anchors.horizontalCenter: parent.horizontalCenter
    y: shown ? parent.height - height - theme.em * 1.2 : parent.height + theme.em
    width: Math.min(toastRow.implicitWidth + theme.em * 2.4, parent.width - theme.em * 4)
    height: toastRow.implicitHeight + theme.em * 1.1
    radius: theme.radiusXl
    color: theme.raised
    border.width: 1
    border.color: error ? theme.loss : theme.border
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on y { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: theme.motionSlow } }
    Timer { id: hideTimer; interval: toast.duration; onTriggered: toast.shown = false }
    MouseArea { anchors.fill: parent; onClicked: toast.shown = false }
    Row {
        id: toastRow
        anchors.centerIn: parent
        spacing: theme.em * 0.6
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            glyph: toast.error ? "" : ""  // warning, check
            color: toast.error ? theme.loss : theme.gain
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, (toast.parent ? toast.parent.width : 0) - theme.em * 7)
            text: toast.text
            color: theme.text
            wrapMode: Text.WordWrap
        }
    }
}
