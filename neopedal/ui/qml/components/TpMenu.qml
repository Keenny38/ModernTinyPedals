import QtQuick
import QtQuick.Controls.Basic

// Popup menu: rounded, fades in, items highlighted on hover, check marks, separators (MenuSeparator {})
Menu {
    id: menu
    padding: 4
    // As wide as its widest item (long French labels), 13 em at least, never wider than the window. Measured
    // again when an item changes width, once after items are added or removed (Instantiator models insert them
    // one by one: measured at each insert, the cost grew with the square of the count) and when it opens
    property int measureSerial: 0
    readonly property real widestItem: {
        var widest = 0
        measureSerial  // items added or removed (not count: changes at each insert)
        for (var i = 0; ; ++i) {
            var entry = itemAt(i)
            if (!entry)
                break
            widest = Math.max(widest, entry.implicitWidth)
        }
        return widest
    }
    function measureItems() { measureSerial += 1 }
    onCountChanged: Qt.callLater(menu.measureItems)  // once per batch of inserts
    onAboutToShow: measureItems()  // items added just before opening: width right where it opens
    implicitWidth: Math.min(Math.max(theme.em * 13, widestItem + leftPadding + rightPadding),
                            parent && parent.Window.window ? parent.Window.width - theme.em : theme.em * 40)

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: theme.motionFast; easing.type: Easing.OutCubic }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }

    background: Rectangle {
        implicitWidth: theme.em * 13
        radius: theme.radiusLg
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    delegate: TpMenuItem {}
}
