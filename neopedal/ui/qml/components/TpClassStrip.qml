import QtQuick
import QtQuick.Layouts

// Thin vertical bar in the class color at the left of a row (driver lists of Spectate & Broadcast Director).
// In a RowLayout it fills the row height minus inset; elsewhere set height or anchors. No class color: border.
//   TpClassStrip { tint: row.classColor }
Rectangle {
    property string tint: ""
    property real inset: theme.space3

    implicitWidth: Math.round(theme.em * 0.28)
    Layout.preferredWidth: implicitWidth
    Layout.fillHeight: true
    Layout.topMargin: inset
    Layout.bottomMargin: inset
    radius: width / 2
    color: tint !== "" ? tint : theme.border
}
