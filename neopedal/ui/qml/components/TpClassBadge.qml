import QtQuick
import QtQuick.Controls.Basic

// Vehicle class badge, as in overlays (Standings): class alias on class color, position in class after it
// on a darker part. Full class name in tooltip.
Rectangle {
    id: badge
    property string label: ""  // class alias of vehicle class editor (class name if not set)
    property string fullName: ""  // class name, tooltip
    property color fill: theme.border
    property string position: ""  // position in class, "" for none

    visible: label !== ""
    implicitWidth: aliasText.implicitWidth + theme.em * 0.7 + (position !== "" ? placeText.implicitWidth + theme.em * 0.6 : 0)
    implicitHeight: Math.round(theme.em * 1.35)
    width: implicitWidth
    height: implicitHeight
    radius: theme.radiusSm
    color: fill
    Text {
        id: aliasText
        x: theme.em * 0.35
        anchors.verticalCenter: parent.verticalCenter
        text: badge.label
        textFormat: Text.PlainText
        color: theme.inkOn(badge.fill)
        font.pointSize: theme.fontCaption
        font.weight: Font.Bold
    }
    Rectangle {  // position part: darker, as the overlay pill (square left edge, rounded right corners)
        visible: badge.position !== ""
        x: aliasText.x + aliasText.implicitWidth + theme.em * 0.35
        width: parent.width - x
        height: parent.height
        radius: badge.radius
        color: Qt.darker(badge.fill, 1.6)
        Rectangle { width: badge.radius; height: parent.height; color: parent.color }
        Text {
            id: placeText
            anchors.centerIn: parent
            text: badge.position
            textFormat: Text.PlainText
            color: theme.inkOn(parent.color)
            font.pointSize: theme.fontCaption
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
        }
    }
    HoverHandler { id: hover }
    ToolTip.visible: hover.hovered && badge.fullName !== "" && badge.fullName !== badge.label
    ToolTip.text: badge.fullName
    ToolTip.delay: theme.tipDelay
}
