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

    // Keyboard focus (Tab) on a card out of the shown part: scrolled into view
    function ensureVisible(item) {
        for (var inside = item; inside; inside = inside.parent) {
            if (inside === column) {
                var y = item.mapToItem(column, 0, 0).y + column.y
                if (y < contentY)
                    contentY = Math.max(0, y - theme.space4)
                else if (y + item.height > contentY + height)
                    contentY = Math.min(Math.max(0, contentHeight - height), y + item.height - height + theme.space4)
                return
            }
        }
    }
    Connections {
        target: flick.Window.window
        function onActiveFocusItemChanged() {
            if (flick.Window.activeFocusItem)
                flick.ensureVisible(flick.Window.activeFocusItem)
        }
    }

    ColumnLayout {
        id: column
        width: Math.max(0, Math.min(flick.width - theme.em * 4, flick.maxWidth))
        x: Math.max(theme.em * 2, Math.round((flick.width - width) / 2))  // centered on wide windows (as its header)
        y: theme.space1
        spacing: theme.em * 0.8
    }
}
