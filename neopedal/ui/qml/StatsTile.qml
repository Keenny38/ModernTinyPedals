import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Driver stats key figure: icon & title, large value (level color, letter badge), detail line, optional
// share bar (valid laps). Figure is the backend tile dict: title, value, detail, color, tip, glyph, letter, ratio.
// Value changes: brief fade in.
Card {
    id: tile

    property var figure: ({})
    readonly property color tint: figure.color ? figure.color : theme.accent
    readonly property bool empty: (figure.value || "-") === "-"
    readonly property real ratio: figure.ratio !== undefined ? figure.ratio : -1

    implicitHeight: column.implicitHeight + theme.em * 1.3
    Layout.fillWidth: true
    Layout.preferredWidth: theme.em * 10
    Layout.minimumWidth: theme.em * 7

    Rectangle {  // tint strip
        width: 3
        radius: 1.5
        height: parent.height - theme.em * 1.3
        x: theme.em * 0.35
        anchors.verticalCenter: parent.verticalCenter
        color: tile.tint
        opacity: tile.empty ? 0.3 : 0.9
        Behavior on color { ColorAnimation { duration: 250 } }
    }

    ColumnLayout {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        anchors.leftMargin: theme.em * 0.9
        anchors.rightMargin: theme.em * 0.65
        anchors.topMargin: theme.em * 0.65
        spacing: 1
        RowLayout {
            spacing: theme.em * 0.4
            Layout.fillWidth: true
            Icon { glyph: tile.figure.glyph || ""; size: theme.em * 0.85; color: tile.tint }
            Text {
                text: tile.figure.title || ""
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.88
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
        RowLayout {
            spacing: theme.em * 0.45
            Layout.fillWidth: true
            Rectangle {  // level letter: level told without color
                visible: (tile.figure.letter || "") !== ""
                Layout.preferredWidth: theme.em * 1.45
                Layout.preferredHeight: theme.em * 1.45
                radius: width / 2
                color: tile.tint
                Behavior on color { ColorAnimation { duration: 250 } }
                Text {
                    anchors.centerIn: parent
                    text: tile.figure.letter || ""
                    color: "white"
                    font.pointSize: theme.fontPoint * 0.85
                    font.weight: Font.Bold
                }
            }
            Text {
                id: valueText
                text: tile.figure.value || "-"
                color: tile.figure.color ? tile.figure.color : tile.empty ? theme.dimText : theme.text
                font.pointSize: theme.fontPoint * 1.55
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                elide: Text.ElideRight
                Layout.fillWidth: true
                Behavior on color { ColorAnimation { duration: 250 } }
                onTextChanged: valueFade.restart()
                NumberAnimation { id: valueFade; target: valueText; property: "opacity"; from: 0.25; to: 1; duration: 260 }
            }
        }
        Text {
            text: (tile.figure.detail || "") !== "" ? tile.figure.detail : " "
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.86
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Item {  // share bar (valid laps), room kept on every tile: same height
            Layout.fillWidth: true
            Layout.preferredHeight: theme.em * 0.3
            Layout.topMargin: theme.em * 0.2
            Rectangle {
                visible: tile.ratio >= 0
                anchors.fill: parent
                radius: height / 2
                color: theme.hover
                Rectangle {
                    width: parent.width * Math.max(0, Math.min(tile.ratio, 1))
                    height: parent.height
                    radius: height / 2
                    color: tile.tint
                    Behavior on width { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
                }
            }
        }
    }

    HoverHandler { id: hover; enabled: (tile.figure.tip || "") !== "" }
    ToolTip.visible: hover.hovered
    ToolTip.text: tile.figure.tip || ""
    ToolTip.delay: 600
}
