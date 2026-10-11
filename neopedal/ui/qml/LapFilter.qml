import QtQuick
import QtQuick.Controls.Basic

// Lap chips of shown laps: click to hide or show a lap in this view only (charts keep every lap)
Flow {
    id: filter

    property var hidden: ({})  // lap key: true while hidden in this view

    function shown(lapKey) { return hidden[lapKey] !== true }
    function toggle(lapKey) {
        var next = Object.assign({}, hidden)
        if (next[lapKey] === true) delete next[lapKey]
        else next[lapKey] = true
        hidden = next
    }

    visible: backend.legend.length > 1
    spacing: theme.em * 0.25
    Repeater {
        model: backend.legendModel
        Rectangle {
            readonly property bool lapShown: filter.shown(model.key)
            height: theme.em * 1.5
            width: chipRow.implicitWidth + theme.em * 0.7
            radius: height / 2
            color: lapShown ? Qt.rgba(Qt.color(model.color).r, Qt.color(model.color).g, Qt.color(model.color).b, 0.14)
                            : "transparent"
            border.width: 1
            border.color: lapShown ? model.color : theme.border
            opacity: lapShown ? 1 : 0.55
            ToolTip.visible: chipArea.containsMouse
            ToolTip.text: model.full + "\n" + (lapShown ? i18n.tr("Click: hide in this view") : i18n.tr("Click: show in this view"))
            ToolTip.delay: 600
            Row {
                id: chipRow
                anchors.centerIn: parent
                spacing: theme.em * 0.3
                Rectangle { width: theme.em * 0.45; height: width; radius: width / 2; color: model.color; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: model.label
                    color: theme.text
                    font.pointSize: theme.fontPoint * 0.75
                    font.strikeout: !parent.parent.lapShown
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            MouseArea {
                id: chipArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: filter.toggle(model.key)
            }
        }
    }
}
