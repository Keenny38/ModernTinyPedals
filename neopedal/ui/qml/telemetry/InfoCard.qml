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
        TpText { width: parent.width; role: "caption"; text: card.title }
        TpText {
            width: parent.width
            role: "title"
            font.pointSize: theme.fontTitle  // key figure: larger than page titles
            tabular: true
            text: card.value
            color: card.accentColor
            Behavior on color { ColorAnimation { duration: theme.motionBase } }
        }
        // Keyed on line count: new texts every update (playback: every frame) keep the same Text items
        Repeater {
            model: card.lines.length
            TpText {
                width: column.width
                role: "numeric"
                text: card.lines[index] || ""
                visible: text !== ""
            }
        }
    }
}
