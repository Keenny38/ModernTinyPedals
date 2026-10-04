import QtQuick

// Map view shared by track maps: world coordinates (meters) to screen, animated zoom & move.
// Content items use canvas.matrix (GpuShape transform) or screenX/screenY (labels, markers).
// Wheel: zoom at cursor, drag: move, double-click: whole map, click: clicked(world x, y),
// mouse over map: hovered(world x, y), then hoverEnded() when mouse leaves.
Item {
    id: canvas
    clip: true

    property real minX: 0
    property real minY: 0
    property real maxX: 1
    property real maxY: 1
    property bool flipY: true  // game coordinates: y up on screen
    property real margin: theme.em * 1.2
    property real maxZoom: 60
    property real zoom: 1
    property real panX: 0
    property real panY: 0
    property bool animate: false
    property bool showControls: true
    property bool interactive: true
    default property alias content: layer.data

    readonly property bool hasBounds: maxX > minX || maxY > minY
    readonly property real centerX: (minX + maxX) / 2
    readonly property real centerY: (minY + maxY) / 2
    readonly property real baseScale: Math.max(Math.min((width - margin * 2) / Math.max(maxX - minX, 1),
                                                        (height - margin * 2) / Math.max(maxY - minY, 1)), 1e-6)
    readonly property real mapScale: baseScale * zoom
    readonly property real ySign: flipY ? -1 : 1
    readonly property real tx: width / 2 - centerX * mapScale + panX
    readonly property real ty: height / 2 - ySign * centerY * mapScale + panY
    readonly property real metersPerPixel: 1 / mapScale
    readonly property var matrix: Qt.matrix4x4(mapScale, 0, 0, tx, 0, ySign * mapScale, 0, ty, 0, 0, 1, 0, 0, 0, 0, 1)

    signal clicked(real x, real y)
    signal hovered(real x, real y)
    signal hoverEnded()
    signal settled()  // zoom stopped: rebuild what depends on scale
    signal userZoomed(real zoom)  // zoom chosen with wheel or buttons

    Behavior on zoom { enabled: canvas.animate; NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
    Behavior on panX { enabled: canvas.animate; NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
    Behavior on panY { enabled: canvas.animate; NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }

    function screenX(x) { return x * mapScale + tx }
    function screenY(y) { return ySign * y * mapScale + ty }
    function worldX(px) { return (px - tx) / mapScale }
    function worldY(py) { return (py - ty) / (ySign * mapScale) }

    function setView(nextZoom, nextPanX, nextPanY, animated) {
        animate = animated
        zoom = nextZoom
        panX = nextPanX
        panY = nextPanY
    }
    function zoomAt(factor, px, py) {
        var next = Math.max(1, Math.min(zoom * factor, maxZoom))
        userZoomed(next)
        var x = worldX(px), y = worldY(py)
        var scale = baseScale * next
        if (next === 1) setView(1, 0, 0, true)
        else setView(next, px - width / 2 - (x - centerX) * scale, py - height / 2 - ySign * (y - centerY) * scale, true)
    }
    function reset(animated) { setView(1, 0, 0, animated) }
    // Center view on world point at zoom, at once (followed vehicle)
    function centerOn(x, y, nextZoom) {
        var next = Math.max(1, Math.min(nextZoom, maxZoom))
        var scale = baseScale * next
        setView(next, (centerX - x) * scale, ySign * (centerY - y) * scale, false)
    }
    // Show area (world coordinates), keeping some room around it
    function fit(x0, y0, x1, y1, animated) {
        var areaWidth = Math.max(x1 - x0, 20), areaHeight = Math.max(y1 - y0, 20)
        var scale = Math.min((width - margin * 4) / areaWidth, (height - margin * 4) / areaHeight)
        var next = Math.max(1, Math.min(scale / baseScale, maxZoom))
        var final = baseScale * next
        setView(next, (centerX - (x0 + x1) / 2) * final, ySign * (centerY - (y0 + y1) / 2) * final, animated)
    }

    // Moving only: nothing to rebuild (followed vehicle moves view often).
    // Zoom changing for long (followed vehicles drifting apart): settled at most twice a second meanwhile.
    property double lastSettled: 0
    onMapScaleChanged: {
        if (Date.now() - lastSettled > 500 && settleTimer.running) settleTimer.triggered()
        settleTimer.restart()
    }
    Timer {
        id: settleTimer
        interval: 120
        onTriggered: { canvas.lastSettled = Date.now(); canvas.settled() }
    }

    MouseArea {
        anchors.fill: parent
        enabled: canvas.interactive && canvas.hasBounds
        hoverEnabled: true
        property real pressX: 0
        property real pressY: 0
        property real startPanX: 0
        property real startPanY: 0
        property bool moved: false
        cursorShape: pressed && moved ? Qt.ClosedHandCursor : Qt.PointingHandCursor
        onPressed: function(mouse) {
            pressX = mouse.x; pressY = mouse.y; startPanX = canvas.panX; startPanY = canvas.panY; moved = false
        }
        onPositionChanged: function(mouse) {
            if (!pressed) { canvas.hovered(canvas.worldX(mouse.x), canvas.worldY(mouse.y)); return }
            if (Math.abs(mouse.x - pressX) + Math.abs(mouse.y - pressY) > 4) moved = true
            if (moved && canvas.zoom > 1) canvas.setView(canvas.zoom, startPanX + mouse.x - pressX, startPanY + mouse.y - pressY, false)
        }
        onClicked: function(mouse) { if (!moved) canvas.clicked(canvas.worldX(mouse.x), canvas.worldY(mouse.y)) }
        onDoubleClicked: canvas.reset(true)
        onExited: canvas.hoverEnded()
        // Zoom follows wheel amount: smooth on touchpads & high resolution wheels
        onWheel: function(wheel) { if (wheel.angleDelta.y !== 0) canvas.zoomAt(Math.pow(1.0019, wheel.angleDelta.y), wheel.x, wheel.y) }
    }

    Item {
        id: layer
        anchors.fill: parent
    }

    // Scale bar: round length about a sixth of view width
    Item {
        id: scaleBar
        visible: canvas.showControls && canvas.hasBounds
        readonly property real meters: {
            var raw = canvas.width / 6 * canvas.metersPerPixel
            var magnitude = Math.pow(10, Math.floor(Math.log(Math.max(raw, 1e-6)) / Math.LN10))
            var steps = [1, 2, 5, 10]
            for (var i = 0; i < steps.length; i++)
                if (raw <= steps[i] * magnitude) return steps[i] * magnitude
            return 10 * magnitude
        }
        anchors { right: parent.right; bottom: parent.bottom; margins: theme.em * 0.6 }
        width: meters * canvas.mapScale
        height: theme.em * 1.4
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: theme.dimText }
        Rectangle { anchors.bottom: parent.bottom; width: 2; height: theme.em * 0.5; color: theme.dimText }
        Rectangle { anchors.bottom: parent.bottom; anchors.right: parent.right; width: 2; height: theme.em * 0.5; color: theme.dimText }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            text: scaleBar.meters >= 1000 ? (scaleBar.meters / 1000) + " km" : scaleBar.meters + " m"
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.8
        }
    }

    // Zoom buttons
    Column {
        visible: canvas.showControls && canvas.hasBounds
        anchors { right: parent.right; top: parent.top; margins: theme.em * 0.4 }
        spacing: 2
        Repeater {
            model: [["", 1.5], ["", 1 / 1.5], ["", 0]]  // add, remove, fit
            TpButton {
                glyph: modelData[0]
                flat: true
                implicitHeight: theme.em * 1.9
                opacity: hovered ? 1 : 0.7
                onClicked: modelData[1] === 0 ? canvas.reset(true)
                                              : canvas.zoomAt(modelData[1], canvas.width / 2, canvas.height / 2)
            }
        }
    }
}
