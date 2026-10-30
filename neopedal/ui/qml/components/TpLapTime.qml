import QtQuick

// Lap time with its record mark, the same on every page: ◆ purple = best of the session (or class), ● green =
// personal best; mark right of the time, time DemiBold & colored, purple first when both. Mark told by shape
// as well as color (colorblind). Room for the mark kept on every row (reserveMark) so times line up.
//   TpLapTime { text: row.best; record: row.fastest ? "session" : row.personalBest ? "personal" : "" }
Item {
    id: lapTime
    property string text: ""
    property string record: ""  // "session" (purple ◆), "personal" (green ●), "" none
    property color textColor: theme.text  // color without record
    property real pointSize: theme.fontPoint
    property bool reserveMark: true  // mark room kept without record: times aligned in a column
    property int horizontalAlignment: Text.AlignRight
    property bool italic: false
    property bool strong: false  // DemiBold without record too (main figure of a row)
    readonly property bool marked: record === "session" || record === "personal"
    readonly property color recordColor: record === "session" ? theme.purple : record === "personal" ? theme.gain
                                         : textColor
    readonly property real markRoom: reserveMark || marked ? mark.implicitWidth + theme.space2 : 0

    implicitWidth: label.implicitWidth + markRoom
    implicitHeight: label.implicitHeight

    Accessible.role: Accessible.StaticText
    Accessible.name: text + (record === "session" ? ", " + i18n.tr("Session best")
                             : record === "personal" ? ", " + i18n.tr("Personal Best") : "")

    Text {
        id: label
        anchors.verticalCenter: parent.verticalCenter
        x: lapTime.horizontalAlignment === Text.AlignLeft ? 0 : Math.max(lapTime.width - lapTime.markRoom - width, 0)
        width: Math.min(implicitWidth, Math.max(lapTime.width - lapTime.markRoom, 0))
        text: lapTime.text
        textFormat: Text.PlainText
        color: lapTime.recordColor
        font.pointSize: lapTime.pointSize
        font.weight: lapTime.marked || lapTime.strong ? Font.DemiBold : Font.Normal
        font.italic: lapTime.italic
        font.features: { "tnum": 1 }
        elide: Text.ElideLeft
    }
    Text {  // record mark: ◆ session best, ● personal best
        id: mark
        visible: lapTime.marked
        anchors.left: label.right
        anchors.leftMargin: theme.space2
        anchors.verticalCenter: parent.verticalCenter
        text: lapTime.record === "personal" ? "●" : "◆"
        textFormat: Text.PlainText
        color: lapTime.recordColor
        font.pointSize: theme.fontMicro
    }
}
