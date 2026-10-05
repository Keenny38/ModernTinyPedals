import QtQuick
import QtQuick.Controls.Basic

// Race calculator tyre plan wheel: tyre fitted (compound dot, name dimmed once used before), tread at
// stint start & end (bar & text in tread color), tyre of stock dropped on it, click: pick or take off
Rectangle {
    id: cell
    property int row: 0
    property int corner: 0
    property var info: ({})  // name, text, color, fraction, endFraction, dim, compound
    property var menu: null  // tyres of stock to pick (shared by the cells), see RaceTyreTab wheelMenu
    property var compoundColor: function(name) { return theme.dimText }
    readonly property bool fitted: info.name !== undefined && info.name !== ""

    implicitHeight: Math.round(theme.em * 2.7)
    implicitWidth: theme.em * 7
    radius: theme.em * 0.4
    color: drop.containsDrag ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.22)
         : area.containsMouse || activeFocus ? theme.hover
         : theme.dark ? Qt.darker(theme.base, 1.2) : Qt.darker(theme.base, 1.02)
    border.width: drop.containsDrag || activeFocus ? 1.5 : 1
    border.color: drop.containsDrag || activeFocus ? theme.accent : theme.border
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: fitted ? info.name + " " + info.text : i18n.tr("Empty")
    Behavior on color { ColorAnimation { duration: 120 } }
    Keys.onDeletePressed: if (fitted) backend.clearTyre(row, corner)
    Keys.onSpacePressed: if (menu) menu.openFor(cell)

    Row {
        visible: cell.fitted
        x: theme.em * 0.45
        y: theme.em * 0.3
        width: cell.width - theme.em * 0.9
        spacing: theme.em * 0.3
        Rectangle {
            width: Math.round(theme.em * 0.55); height: width; radius: width / 2
            color: cell.fitted ? cell.compoundColor(cell.info.name) : "transparent"
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, 0.25)
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: cell.info.name || ""
            color: cell.info.dim ? theme.dimText : theme.text
            font.weight: cell.info.dim ? Font.Normal : Font.DemiBold
            font.pointSize: theme.fontPoint * 0.9
            elide: Text.ElideRight
            width: parent.width - theme.em
        }
    }
    Text {
        visible: cell.fitted
        anchors.right: parent.right
        anchors.rightMargin: theme.em * 0.45
        y: cell.height - height - theme.em * 0.4
        text: cell.info.text || ""
        color: cell.info.color || theme.text
        font.pointSize: theme.fontPoint * 0.82
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
    }
    Rectangle {  // tread bar: tread at stint start, darker part worn over the stint
        visible: cell.fitted
        x: theme.em * 0.45
        y: cell.height - height - theme.em * 0.22
        width: (cell.width - theme.em * 0.9) * 0.45
        height: 3
        radius: 1.5
        color: theme.border
        Rectangle {
            width: parent.width * (cell.info.fraction || 0)
            height: parent.height
            radius: 1.5
            color: cell.info.color || theme.accent
            opacity: 0.45
            Behavior on width { NumberAnimation { duration: 200 } }
        }
        Rectangle {
            width: parent.width * (cell.info.endFraction || 0)
            height: parent.height
            radius: 1.5
            color: cell.info.color || theme.accent
            Behavior on width { NumberAnimation { duration: 200 } }
        }
    }
    Text {
        visible: !cell.fitted
        anchors.centerIn: parent
        text: drop.containsDrag ? i18n.tr("Drop") : "+"
        color: theme.dimText
        font.pointSize: theme.fontPoint * (drop.containsDrag ? 0.9 : 1.2)
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            cell.forceActiveFocus()
            if (cell.menu)
                cell.menu.openFor(cell)
        }
    }
    DropArea {
        id: drop
        anchors.fill: parent
        keys: ["tyre"]
        onDropped: function(event) {
            backend.assignTyre(cell.row, cell.corner, event.source.tyreName)
            event.accept()
        }
    }

}
