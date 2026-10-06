import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Content of a setup wizard step: children laid out in a scrolling column with page margins
Flickable {
    id: flick
    default property alias content: column.data
    property real maxWidth: theme.em * 52
    clip: true
    contentWidth: width
    contentHeight: column.implicitHeight + theme.em * 1.6
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar {
        policy: flick.contentHeight > flick.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
    }

    ColumnLayout {
        id: column
        x: theme.em * 2
        y: theme.em * 0.2
        width: Math.min(flick.width - theme.em * 4, flick.maxWidth)
        spacing: theme.em * 0.8
    }
}
