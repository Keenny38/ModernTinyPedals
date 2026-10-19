import QtQuick
import QtQuick.Layouts
import "../components"

// Stat card: small title, large value, detail lines
Card {
    id: card
    property string title: ""
    property string value: ""
    property color accentColor: theme.text
    property var lines: []

    Layout.fillWidth: true
    implicitHeight: column.implicitHeight + theme.padCard * 2

    Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.padCard }
        spacing: theme.space1
        Text { width: parent.width; text: card.title; color: theme.dimText; font.pointSize: theme.fontSmall; elide: Text.ElideRight }
        Text {
            width: parent.width
            text: card.value
            color: card.accentColor
            font.pointSize: theme.fontTitle
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
            Behavior on color { ColorAnimation { duration: theme.motionBase } }
        }
        // Keyed on line count: new texts every update (playback: every frame) keep the same Text items
        Repeater {
            model: card.lines.length
            Text {
                width: column.width
                text: card.lines[index] || ""
                visible: text !== ""
                color: theme.text
                font.features: { "tnum": 1 }
                elide: Text.ElideRight
            }
        }
    }
}
