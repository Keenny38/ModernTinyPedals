import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator key figure: icon & title, large value (warning color when out of range), detail line
Card {
    id: tile
    property string title: ""
    property string value: "-"
    property string detail: ""
    property string tip: ""
    property string glyph: ""
    property color tint: theme.accent
    property bool warning: false

    implicitHeight: column.implicitHeight + theme.em * 1.2
    Layout.fillWidth: true
    Layout.preferredWidth: theme.em * 10
    Layout.minimumWidth: theme.em * 7

    Rectangle {  // tint strip
        width: 3
        radius: 1.5
        height: parent.height - theme.em * 1.2
        x: theme.em * 0.35
        anchors.verticalCenter: parent.verticalCenter
        color: tile.warning ? theme.loss : tile.tint
        opacity: tile.value === "-" ? 0.35 : 0.9
        Behavior on color { ColorAnimation { duration: 200 } }
    }

    ColumnLayout {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        anchors.leftMargin: theme.em * 1.0
        anchors.rightMargin: theme.em * 0.6
        anchors.topMargin: theme.em * 0.6
        spacing: 1
        RowLayout {
            spacing: theme.em * 0.35
            Layout.fillWidth: true
            Icon { glyph: tile.glyph; size: theme.em * 0.85; color: tile.warning ? theme.loss : tile.tint }
            Text {
                text: tile.title
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.88
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
        Text {
            text: tile.value
            color: tile.warning ? theme.loss : theme.text
            font.pointSize: theme.fontPoint * 1.55
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
            Layout.fillWidth: true
            Behavior on color { ColorAnimation { duration: 200 } }
        }
        Text {
            text: tile.detail !== "" ? tile.detail : " "
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.86
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }

    HoverHandler { id: hover; enabled: tile.tip !== "" }
    ToolTip.visible: hover.hovered
    ToolTip.text: tile.tip
    ToolTip.delay: 600
}
