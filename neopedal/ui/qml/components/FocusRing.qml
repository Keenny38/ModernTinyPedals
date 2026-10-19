import QtQuick

// Keyboard focus outline around its parent, or around target (a sibling: row surface, card), rounded like it.
// Solid accent (3:1 at least on page backgrounds): never mistaken for a checked border
//   FocusRing { visible: control.visualFocus }  /  FocusRing { target: surface; visible: row.current }
Rectangle {
    property Item target: parent
    readonly property real gap: Math.max(2, Math.round(theme.em * 0.18))
    anchors.fill: target
    anchors.margins: -gap
    radius: (target && target.radius !== undefined ? target.radius : 0) + gap
    color: "transparent"
    border.width: 2
    border.color: theme.accent
}
