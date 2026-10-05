import QtQuick

// Category filter chip of Overlays page: color dot, name & number of overlays, filled when selected
Rectangle {
    id: chip
    property string text: ""
    property color dotColor: "transparent"
    property bool showDot: true
    property int count: 0
    property bool selected: false
    signal clicked()

    implicitHeight: Math.round(theme.em * 2)
    implicitWidth: content.implicitWidth + theme.em * 1.3
    radius: height / 2
    color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.22 : 0.14)
         : area.containsMouse ? theme.hover : "transparent"
    border.width: 1
    border.color: selected ? theme.accent : area.containsMouse ? Qt.lighter(theme.border, 1.25) : theme.border
    opacity: count > 0 || selected ? 1 : 0.5
    Behavior on color { ColorAnimation { duration: 120 } }
    Behavior on border.color { ColorAnimation { duration: 120 } }
    Behavior on opacity { NumberAnimation { duration: 150 } }

    Accessible.role: Accessible.RadioButton
    Accessible.name: text
    Accessible.checked: selected

    Row {
        id: content
        anchors.centerIn: parent
        spacing: theme.em * 0.4
        Rectangle {
            visible: chip.showDot
            width: Math.round(theme.em * 0.55)
            height: width
            radius: width / 2
            color: chip.dotColor
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: chip.text
            color: theme.text
            font.weight: chip.selected ? Font.DemiBold : Font.Normal
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: chip.count
            color: chip.selected ? theme.accent : theme.dimText
            font.pointSize: theme.fontPoint * 0.85
            font.features: { "tnum": 1 }
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.clicked()
    }
}
