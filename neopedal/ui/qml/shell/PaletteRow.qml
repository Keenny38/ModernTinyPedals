import QtQuick
import QtQuick.Layouts
import "../components"

// Result row of the command palette: icon, title, detail (menu path, page description), shortcut keys.
// current: keyboard selection (Up / Down), hover moves it; click runs it.
Item {
    id: row
    required property var modelData
    required property int index
    property bool current: false
    signal hoveredRow()
    signal activated()

    implicitHeight: theme.row
    Accessible.role: Accessible.ListItem
    Accessible.name: modelData.title + (modelData.shortcut !== "" ? ", " + modelData.shortcut : "")
    Accessible.description: modelData.detail

    TpListRow {
        anchors.fill: parent
        hovered: area.containsMouse
        pressed: area.pressed
        selected: row.current
    }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: theme.space4
        anchors.rightMargin: theme.space4
        spacing: theme.space4
        Icon {
            Layout.preferredWidth: theme.em * 1.3
            glyph: row.modelData.glyph
            fallback: row.modelData.title.charAt(0).toUpperCase()
            color: row.current ? theme.accent : theme.dimText
            size: theme.iconSm
        }
        TpText {
            Layout.maximumWidth: parent.width * 0.6
            text: row.modelData.title
            textFormat: Text.PlainText
            color: theme.text
            elide: Text.ElideRight
        }
        TpText {
            Layout.fillWidth: true  // also when empty: keys stay on the right
            role: "caption"
            text: row.modelData.detail
        }
        Rectangle {  // shortcut key cap
            visible: row.modelData.shortcut !== ""
            implicitWidth: keys.implicitWidth + theme.space4 * 2
            implicitHeight: keys.implicitHeight + theme.space1 * 2
            radius: theme.radiusSm
            color: "transparent"
            border.width: 1
            border.color: theme.strokeSubtle
            TpText {
                id: keys
                anchors.centerIn: parent
                role: "caption"
                text: row.modelData.shortcut
            }
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: row.hoveredRow()
        onClicked: row.activated()
    }
}
