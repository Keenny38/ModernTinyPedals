import QtQuick

// Segmented control: one option selected, highlight slides between options
Rectangle {
    id: control
    property var options: []  // texts
    property int currentIndex: 0
    signal activated(int index)

    implicitHeight: Math.round(theme.em * 2.3)
    implicitWidth: row.implicitWidth + 6
    radius: theme.em * 0.6
    color: theme.dark ? Qt.darker(theme.base, 1.25) : Qt.darker(theme.window, 1.04)
    border.width: 1
    border.color: theme.border

    Rectangle {
        id: highlight
        property Item target: row.children[control.currentIndex] || null
        x: target ? target.x + row.x : 0
        width: target ? target.width : 0
        y: 3
        height: parent.height - 6
        radius: theme.em * 0.45
        color: theme.raised
        border.width: theme.dark ? 0 : 1
        border.color: theme.border
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }

    Row {
        id: row
        x: 3
        height: parent.height
        Repeater {
            model: control.options
            Item {
                width: optionText.implicitWidth + theme.em * 1.6
                height: row.height
                Text {
                    id: optionText
                    anchors.centerIn: parent
                    text: modelData
                    color: index === control.currentIndex ? theme.text : theme.dimText
                    font.weight: index === control.currentIndex ? Font.DemiBold : Font.Normal
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { control.currentIndex = index; control.activated(index) }
                }
            }
        }
    }
}
