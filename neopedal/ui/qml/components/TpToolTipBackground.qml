import QtQuick

// Tooltip surface: flyout color, subtle border, control corners, soft shadow. Used by TpToolTip and set on the
// engine's shared tooltip (ToolTip.text of every item, see quick.style_tooltips)
Rectangle {
    radius: theme.radiusSm
    color: theme.surfaceFlyout
    border.width: 1
    border.color: theme.strokeSubtle
    TpShadow { extent: theme.shadowExtent / 2; offsetY: theme.shadowOffset / 2 }
}
