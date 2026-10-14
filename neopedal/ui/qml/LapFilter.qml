import QtQuick
import QtQuick.Controls.Basic

// Lap chips of shown laps: click to hide or show a lap in this view only (charts keep every lap)
Flow {
    id: filter

    property var hidden: ({})  // lap key: true while hidden in this view
    // Chip tooltips translated once (not per chip), made while hovered
    readonly property string hideHint: i18n.tr("Click: hide in this view")
    readonly property string showHint: i18n.tr("Click: show in this view")

    // Lap alone: always shown (no chips to show it again)
    function shown(lapKey) { return backend.legend.length <= 1 || hidden[lapKey] !== true }
    // Hidden laps no longer compared forgotten (a lap compared again is shown), all of them once a lap is
    // alone (still shown when another lap is added)
    function forgetRemoved() {
        var keys = Object.keys(hidden)
        if (!keys.length) return
        var legend = backend.legend, kept = {}, changed = false
        if (legend.length <= 1) { hidden = {}; return }
        var present = {}
        for (var i = 0; i < legend.length; i++) present[legend[i].key] = true
        for (var k = 0; k < keys.length; k++) {
            if (present[keys[k]]) kept[keys[k]] = true
            else changed = true
        }
        if (changed) hidden = kept
    }
    function toggle(lapKey) {
        var next = Object.assign({}, hidden)
        if (next[lapKey] === true) delete next[lapKey]
        else next[lapKey] = true
        hidden = next
    }

    Connections {
        target: backend
        function onChartChanged() { filter.forgetRemoved() }
    }

    visible: backend.legend.length > 1
    spacing: theme.em * 0.3
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
            ToolTip.text: chipArea.containsMouse ? model.full + "\n" + (lapShown ? filter.hideHint : filter.showHint) : ""
            ToolTip.delay: theme.tipDelay
            Row {
                id: chipRow
                anchors.centerIn: parent
                spacing: theme.em * 0.3
                Rectangle { width: theme.em * 0.45; height: width; radius: width / 2; color: model.color; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: model.label
                    color: theme.text
                    font.pointSize: theme.fontCaption
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
