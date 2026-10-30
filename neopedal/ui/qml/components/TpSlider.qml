import QtQuick
import QtQuick.Controls.Basic

// Slider in app look: thin track filled up to the value, round accent handle (grows on hover), optional
// notches (values from..to) with one marked value (normal speed...). Reached with Tab, arrows move it,
// a click leaves keyboard focus where it was. Tooltip after the usual delay, hidden while dragging.
//   TpSlider { from: 0; to: 10; stepSize: 1; tip: i18n.tr("Speed"); notches: [0, 1, 2]; markedValue: 1 }
Slider {
    id: slider
    property string tip: ""
    property var notches: []
    property real markedValue: NaN
    property bool fillShown: true
    property bool handleShown: true

    implicitHeight: Math.round(theme.controlHeightSm)
    implicitWidth: theme.em * 8
    leftPadding: theme.em * 0.5
    rightPadding: theme.em * 0.5
    focusPolicy: Qt.TabFocus
    hoverEnabled: true
    opacity: enabled ? 1 : theme.disabledOpacity
    Accessible.name: tip
    Keys.onShortcutOverride: function(event) {
        if ([Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End,
             Qt.Key_PageUp, Qt.Key_PageDown].indexOf(event.key) >= 0)
            event.accepted = true
    }

    ToolTip.visible: tip !== "" && (hovered || visualFocus) && !pressed
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay

    background: Item {
        x: slider.leftPadding
        width: slider.availableWidth
        height: slider.height
        Rectangle {  // track, filled up to the value
            id: track
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: Math.max(3, Math.round(theme.em * 0.28))
            radius: height / 2
            color: theme.border
            Rectangle {
                visible: slider.fillShown
                width: slider.visualPosition * parent.width
                height: parent.height
                radius: parent.radius
                color: theme.accent
            }
        }
        Repeater {  // notches, marked value taller
            model: slider.notches
            Rectangle {
                required property real modelData
                readonly property bool marked: modelData === slider.markedValue
                x: (modelData - slider.from) / Math.max(slider.to - slider.from, 1e-9) * parent.width - width / 2
                anchors.verticalCenter: parent.verticalCenter
                width: marked ? 2 : 1
                height: marked ? theme.em * 0.8 : theme.em * 0.45
                color: modelData <= slider.value ? theme.accent : theme.border
            }
        }
        FocusRing { target: track; visible: slider.visualFocus }
    }
    handle: Rectangle {
        x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
        y: slider.topPadding + (slider.availableHeight - height) / 2
        width: theme.em * 1.0
        height: width
        radius: width / 2
        visible: slider.handleShown || slider.pressed
        color: slider.pressed ? theme.accentPressed : theme.accent
        border.width: 2
        border.color: theme.surfaceCard
        scale: slider.pressed || slider.hovered ? 1.15 : 1
        Behavior on scale { NumberAnimation { duration: theme.motionFast } }
    }
}
