import QtQuick

// Background of a list / table row: hover, pressed, selected, emphasized & striped states (put it under the
// row content). One look for every list: selected = accent tint (theme.rowColor), emphasized = state shown
// without selection (player row, car on air) in its own tint, striped = odd row of a dense table.
//   TpListRow { anchors.fill: parent; hovered: rowArea.containsMouse; selected: ListView.isCurrentItem }
//   TpListRow { anchors.fill: parent; striped: index % 2 === 1; emphasized: onAir; tint: theme.loss }
// Changes to or from a state fade (animate: false while a recycled row is fed another entry, see the lists'
// ListView.onPooled / onReused); stripe only (no state) never fades: rows moved by a sort or recycled while
// scrolling flip their parity, a fade there flashes the list. color is the row color (texts: theme.dimOn(row.color)).
Rectangle {
    id: surface
    property bool hovered: false
    property bool pressed: false
    property bool selected: false
    property bool emphasized: false
    property bool striped: false
    property color tint: theme.accent  // selected & emphasized color
    property bool animate: true  // false while a recycled row (ListView reuseItems) is fed another entry

    readonly property bool marked: pressed || selected || emphasized || hovered  // a state shown, not the stripe
    readonly property color shade: pressed && !selected ? theme.border
         : selected ? Qt.rgba(tint.r, tint.g, tint.b, hovered ? theme.tintSelected * 4 / 3 : theme.tintSelected)
         : emphasized ? Qt.rgba(tint.r, tint.g, tint.b, hovered ? theme.tintSelected : theme.tintSubtle * 1.4)
         : hovered ? theme.hover
         : striped ? Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.03)
         : "transparent"
    property bool shownMarked: false  // color shown is a state: going back to the stripe (or none) fades too

    radius: theme.radiusMd
    color: "transparent"  // shade, set below: fade chosen from both ends of the change (no binding race)
    Component.onCompleted: { fade.enabled = false; color = shade; shownMarked = marked }  // made: shown at once
    onShadeChanged: {
        fade.enabled = animate && (marked || shownMarked)
        color = shade
        shownMarked = marked
    }
    Behavior on color { id: fade; ColorAnimation { duration: theme.motionFast } }
}
