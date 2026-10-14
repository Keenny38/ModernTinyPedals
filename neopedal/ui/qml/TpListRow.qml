import QtQuick

// Background of a list / table row: hover, pressed & selected states (put it under the row content)
//   TpListRow { anchors.fill: parent; hovered: rowArea.containsMouse; selected: ListView.isCurrentItem }
Rectangle {
    property bool hovered: false
    property bool pressed: false
    property bool selected: false
    property color tint: theme.accent  // selected color

    radius: theme.radiusMd
    color: pressed && !selected ? theme.border
         : selected && tint !== theme.accent ? Qt.rgba(tint.r, tint.g, tint.b, hovered ? theme.tintSelected + 0.06 : theme.tintSelected)
         : theme.rowColor(hovered, selected)
    Behavior on color { ColorAnimation { duration: theme.motionFast } }
}
