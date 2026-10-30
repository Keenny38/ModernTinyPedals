import QtQuick

// Soft drop shadow under a raised surface (popups, menus, toasts, tooltips): one static blurred 9-patch picture
// (shadow.png, made by tools/gen_shadow.py) scaled to theme.shadowExtent, opacity theme.shadowOpacity (stronger on
// dark themes, flatter on Legacy ones). No shader, no layer: a scaled image shared by every shadow.
// Put it inside the surface: drawn under it (z -1), around its parent (or target, a sibling).
//   background: Rectangle { color: theme.surfaceFlyout; radius: theme.radiusLg; TpShadow {} }
BorderImage {
    id: shadow
    property Item target: parent
    property real extent: theme.shadowExtent  // reach of the shadow outside the surface (px)
    property real offsetY: theme.shadowOffset  // pushed down: light from above
    property real strength: 1  // multiplies theme.shadowOpacity (cards resting on the page: less)
    // REACH & REACH + RADIUS of tools/gen_shadow.py (pixels of the picture): its blur reach & 9-patch border
    readonly property int reach: 32
    readonly property int slice: 48
    readonly property real factor: extent / reach
    readonly property bool besideTarget: target !== null && target !== parent

    z: -1
    source: Qt.resolvedUrl("shadow.png")  // next to this file (a plain url would be read from the user of TpShadow)
    border { left: slice; top: slice; right: slice; bottom: slice }
    smooth: true
    transformOrigin: Item.TopLeft
    scale: factor
    x: (besideTarget ? target.x : 0) - extent
    y: (besideTarget ? target.y : 0) - extent + offsetY
    width: target ? (target.width + extent * 2) / factor : 0
    height: target ? (target.height + extent * 2) / factor : 0
    opacity: theme.shadowOpacity * strength
    visible: target !== null && opacity > 0 && extent > 0
    Accessible.ignored: true
}
