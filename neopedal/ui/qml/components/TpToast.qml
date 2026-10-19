import QtQuick

// Message at bottom of page for a few seconds (click: hidden), slides in. show() after each new message.
// Shown long enough to read it (longer for errors), kept while the mouse is over it; optional action
// button (actionText, action signal): "Undo" after an action done without confirmation
Rectangle {
    id: toast
    property string text: ""
    property bool error: false  // warning icon & red border, else check
    property int duration: 0  // ms shown, 0: from text length
    property string actionText: ""
    property bool shown: false
    readonly property int shownTime: duration > 0 ? duration
        : Math.round(Math.max(3000, text.length * 55 + 1500) * (error ? 1.5 : 1) + (actionText !== "" ? 3000 : 0))
    signal action()

    function show() {
        shown = true
        if (hover.hovered)
            hideTimer.stop()
        else
            hideTimer.restart()
    }

    Accessible.role: Accessible.AlertMessage
    Accessible.name: text

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
    Timer { id: hideTimer; interval: toast.shownTime; onTriggered: toast.shown = false }
    HoverHandler {
        id: hover
        onHoveredChanged: {
            if (hovered)
                hideTimer.stop()
            else if (toast.shown)
                hideTimer.restart()
        }
    }
    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: toast.shown = false }
    Row {
        id: toastRow
        anchors.centerIn: parent
        spacing: theme.em * 0.6
        Icon {
            fallback: toast.error ? "!" : "✓"
            anchors.verticalCenter: parent.verticalCenter
            glyph: toast.error ? "" : ""  // warning, check
            color: toast.error ? theme.loss : theme.gain
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, (toast.parent ? toast.parent.width : 0) - theme.em * 7
                            - (toast.actionText !== "" ? actionButton.implicitWidth + toastRow.spacing : 0))
            text: toast.text
            color: theme.text
            wrapMode: Text.WordWrap
        }
        TpButton {
            id: actionButton
            anchors.verticalCenter: parent.verticalCenter
            visible: toast.actionText !== ""
            size: "sm"
            text: toast.actionText
            onClicked: { toast.shown = false; toast.action() }
        }
    }
}
