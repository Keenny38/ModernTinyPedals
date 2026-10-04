import QtQuick
import QtQuick.Layouts

// Stat card: small title, large value, detail lines
Card {
    id: card
    property string title: ""
    property string value: ""
    property color accentColor: theme.text
    property var lines: []

    Layout.fillWidth: true
    implicitHeight: column.implicitHeight + theme.em * 1.2

    Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.6 }
        spacing: 2
        Text { text: card.title; color: theme.dimText; font.pointSize: theme.fontPoint * 0.85 }
        Text {
            width: parent.width
            text: card.value
            color: card.accentColor
            font.pointSize: theme.fontPoint * 1.6
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
            Behavior on color { ColorAnimation { duration: 200 } }
        }
        Repeater {
            model: card.lines
            Text {
                width: column.width
                text: modelData
                visible: text !== ""
                color: theme.text
                font.features: { "tnum": 1 }
                elide: Text.ElideRight
            }
        }
    }
}
