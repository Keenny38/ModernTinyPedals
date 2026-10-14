import QtQuick

// Keyboard focus outline around its parent (rounded like it): visible: control.visualFocus
Rectangle {
    anchors.fill: parent
    anchors.margins: -Math.max(2, Math.round(theme.em * 0.18))
    radius: (parent && parent.radius !== undefined ? parent.radius : 0) - anchors.margins
    color: "transparent"
    border.width: 2
    border.color: theme.accent
}
