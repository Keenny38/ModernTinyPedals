import QtQuick
import QtQuick.Controls.Basic

// On-air light (broadcast tally): filled dot & solid fill while live (a few pulses when it goes live), hollow dot
// & outline when off: told by shape & text, not only color. Optional action button (actionText, action signal).
//   TpTally { live: backend.onAir; text: live ? i18n.tr("On Air") : i18n.tr("Off Air")
//             actionText: live ? i18n.tr("Cut") : ""; onAction: backend.cut() }
Rectangle {
    id: tally
    property bool live: false
    property string text: ""
    property string tip: ""
    property color tint: theme.lossFill  // fill while live (white text 4.5:1)
    property string actionText: ""
    signal action()
    readonly property color ink: live ? theme.inkOn(tint) : theme.dimText

    implicitHeight: Math.round(actionText !== "" ? theme.controlHeightSm : theme.chipHeight)
    implicitWidth: row.implicitWidth + (actionText !== "" ? theme.space3 : theme.space5) + theme.space4
    radius: height / 2
    color: live ? tint : theme.tint(theme.dimText, "subtle")
    border.width: live ? 0 : 1
    border.color: theme.strokeStrong
    Behavior on color { ColorAnimation { duration: theme.motionBase } }

    Accessible.role: Accessible.StaticText
    Accessible.name: tip !== "" ? text + ", " + tip : text

    Row {
        id: row
        x: theme.space4
        anchors.verticalCenter: parent.verticalCenter
        spacing: theme.space3
        TpPulseDot {  // tally light: filled while live (a few pulses when it goes live), ring when off
            width: Math.round(theme.em * 0.6)
            anchors.verticalCenter: parent.verticalCenter
            color: tally.live ? tally.ink : "transparent"
            border.width: tally.live ? 0 : 1.5
            border.color: tally.ink
            pulsing: tally.live
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: tally.text
            textFormat: Text.PlainText
            color: tally.ink
            font.pointSize: theme.fontCaption
            font.weight: tally.live ? Font.Bold : Font.DemiBold
            font.capitalization: Font.AllUppercase
            font.letterSpacing: theme.letterSpacingOverline
        }
        TpButton {
            visible: tally.actionText !== ""
            anchors.verticalCenter: parent.verticalCenter
            size: "xs"
            flat: false  // own surface: readable on the live fill too
            text: tally.actionText
            onClicked: tally.action()
        }
    }

    MouseArea {  // tooltip only
        id: tipArea
        anchors.fill: parent
        z: -1
        hoverEnabled: tally.tip !== ""
        acceptedButtons: Qt.NoButton
    }
    ToolTip.visible: tally.tip !== "" && tipArea.containsMouse
    ToolTip.text: tally.tip
    ToolTip.delay: theme.tipDelay
}
