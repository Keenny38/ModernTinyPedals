import QtQuick

// Background of a list / table row: hover, pressed, selected, emphasized & striped states (put it under the
// row content). One look for every list: selected = accent tint (theme.rowColor), emphasized = state shown
// without selection (player row, car on air) in its own tint, striped = odd row of a dense table, pressed =
// sunken surface. card: row drawn as its own card (lists of presets, overlays, drivers, search results): card
// surface & border, hovered surfaceHover, selected / emphasized tint over it with a tinted outline (never an
// accent border for hover).
//   TpListRow { anchors.fill: parent; hovered: rowArea.containsMouse; selected: ListView.isCurrentItem }
//   TpListRow { anchors.fill: parent; striped: index % 2 === 1; emphasized: onAir; tint: theme.loss }
//   TpListRow { anchors.fill: parent; card: true; hovered: area.containsMouse; selected: row.selected }
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
    property bool card: false
    property color tint: theme.accent  // selected & emphasized color
    property bool animate: true  // false while a recycled row (ListView reuseItems) is fed another entry

    readonly property bool marked: pressed || selected || emphasized || hovered  // a state shown, not the stripe
    readonly property color cardBase: hovered ? theme.surfaceHover : theme.surfaceCard
    readonly property color shade: card ? (pressed && !selected ? theme.surfaceSunken
                                           : selected ? Qt.tint(cardBase, theme.tint(tint, "selected"))
                                           : emphasized ? Qt.tint(cardBase, theme.tint(tint, "subtle"))
                                           : cardBase)
         : pressed && !selected ? theme.surfaceSunken
         : selected ? theme.tint(tint, hovered ? theme.tintSelected * 4 / 3 : theme.tintSelected)
         : emphasized ? theme.tint(tint, hovered ? theme.tintSelected : theme.tintSubtle * 1.4)
         : hovered ? theme.hover
         : striped ? theme.tint(theme.text, "stripe")
         : "transparent"
    property bool shownMarked: false  // color shown is a state: going back to the stripe (or none) fades too

    radius: card ? theme.radiusLg : theme.radiusSm
    border.width: card ? 1 : 0
    border.color: selected || emphasized ? theme.tint(tint, "outline") : theme.strokeSubtle
    color: "transparent"  // shade, set below: fade chosen from both ends of the change (no binding race)
    Component.onCompleted: { fade.enabled = false; color = shade; shownMarked = marked }  // made: shown at once
    onShadeChanged: {
        fade.enabled = animate && (marked || shownMarked)
        color = shade
        shownMarked = marked
    }
    Behavior on color { id: fade; ColorAnimation { duration: theme.motionFast } }
}
