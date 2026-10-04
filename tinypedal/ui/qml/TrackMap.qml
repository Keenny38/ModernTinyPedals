import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import TinyPedal

// Lap viewer track map: circuit, driving lines of compared laps, colored by lap, time gain, speed, pedals,
// racing line (inside / outside of reference line), gear or elevation.
// Driving points of each lap in each corner: braking (diamond), apex (dot), exit at full throttle (triangle),
// with speed & distance against reference lap on hover. Wheel lockups & wheelspin, sector times, direction
// arrows, corners (click: zoom charts on corner, overlapping labels hidden).
// Mouse over a line: same point shown in charts (cursor), click: chart moved to it.
Item {
    id: root

    property var chart  // TraceChart
    property bool expanded: false  // shown over whole page (focus mode)
    signal expandToggled()

    readonly property var info: backend.trackMap
    readonly property bool hasMap: info.road !== undefined
    readonly property bool chartZoomed: chart ? chart.zoomed : false
    readonly property string mode: backend.mapMode
    readonly property var options: backend.mapOptions
    readonly property var modes: [
        ["laps", i18n.tr("Laps")], ["gain", i18n.tr("Gain / Loss")], ["speed", i18n.tr("Speed")],
        ["pedals", i18n.tr("Pedals")], ["line", i18n.tr("Racing Line")], ["gear", i18n.tr("Gear")],
        ["elevation", i18n.tr("Elevation")],
    ]
    readonly property string highlightKey: chart ? chart.highlightKey : ""
    property bool scrubbing: false  // chart cursor set by mouse over map
    // Vehicles followed while playing lap or moving cursor with keys: view centered on them, zoomed in
    readonly property bool tracking: chart !== undefined && chart !== null && hasMap && visible
                                     && options.track === true && (chart.playing || chart.cursorSource === "key")
    readonly property real trackWindow: 300  // meters shown around vehicles when following starts
    readonly property real trackMargin: 60  // meters kept around followed vehicles
    property real trackZoom: 1  // zoom while following, changed with wheel
    // Corner labels shown: highest time delta first, labels overlapping a shown one hidden
    readonly property var labelShown: {
        var corners = info.corners || []
        var order = corners.map(function(corner, index) { return index })
        order.sort(function(a, b) { return (corners[b].priority || 0) - (corners[a].priority || 0) })
        var placed = []
        var shown = []
        var lineHeight = theme.em * 1.3
        var matrix = canvas.matrix  // dependency: map moved or zoomed
        for (var i = 0; i < order.length; i++) {
            var corner = corners[order[i]]
            var width = (corner.label.length + (corner.delta ? corner.delta.length + 1 : 0)) * theme.em * 0.55 + theme.em * 0.8
            var x = canvas.screenX(corner.x) + 6, y = canvas.screenY(corner.y) - lineHeight - 4
            var free = true
            for (var j = 0; j < placed.length && free; j++) {
                var other = placed[j]
                if (x < other[0] + other[2] && x + width > other[0] && y < other[1] + lineHeight && y + lineHeight > other[1]) free = false
            }
            if (free) placed.push([x, y, width])
            shown[order[i]] = free
        }
        return shown
    }

    function tone(name, fallback) { return name === "loss" ? theme.loss : name === "gain" ? theme.gain : fallback }
    function lapOpacity(lapKey) { return highlightKey === "" || lapKey === highlightKey ? 1 : 0.2 }
    function modeTitle(name) {
        for (var i = 0; i < modes.length; i++) if (modes[i][0] === name) return modes[i][1]
        return name
    }
    function pointShown(kind) {
        if (kind === "brake") return backend.mapBraking
        return options[kind] === true
    }
    function followChart() {
        if (!backend.mapFollow || !chart || tracking) return
        if (!chart.zoomed) { canvas.reset(true); return }
        var bounds = backend.mapBounds(chart.targetStart, chart.targetEnd)
        if (bounds.length === 4) canvas.fit(bounds[0], bounds[1], bounds[2], bounds[3], true)
    }
    // Thick lines rebuilt for this map scale (two maps: side panel & focus mode)
    function updateView() {
        if (!visible || !hasMap || !chart) return
        backend.setMapView(chart.zoomed ? chart.targetStart : 0, chart.zoomed ? chart.targetEnd : 0, canvas.metersPerPixel)
        if (canvas.width > 0 && canvas.height > 0) backend.setMapAspect(canvas.width / canvas.height)
    }

    // Following starts: zoomed in on vehicles (unless already closer)
    onTrackingChanged: if (tracking) {
        var shown = Math.min(canvas.width, canvas.height) * canvas.metersPerPixel
        trackZoom = shown > trackWindow ? canvas.zoom * shown / trackWindow : canvas.zoom
    }
    // View centered on followed vehicles (highlighted lap only if any), zoomed out if needed to keep all of them,
    // eased toward target each update: smooth camera
    function trackVehicles() {
        var points = (chart.cursorMap || []).filter(function(point) {
            return point && (highlightKey === "" || point.lap === highlightKey)
        })
        if (points.length === 0 || canvas.width <= 0) return
        var x0 = points[0].x, x1 = x0, y0 = points[0].y, y1 = y0
        for (var i = 1; i < points.length; i++) {
            x0 = Math.min(x0, points[i].x); x1 = Math.max(x1, points[i].x)
            y0 = Math.min(y0, points[i].y); y1 = Math.max(y1, points[i].y)
        }
        var fitZoom = Math.min(canvas.width / (x1 - x0 + trackMargin * 2), canvas.height / (y1 - y0 + trackMargin * 2))
                      / canvas.baseScale
        var targetZoom = Math.max(1, Math.min(trackZoom, fitZoom))
        var targetX = (x0 + x1) / 2, targetY = (y0 + y1) / 2
        var centerX = canvas.worldX(canvas.width / 2), centerY = canvas.worldY(canvas.height / 2)
        var ease = 0.35
        // Zoom close to target set exactly: zoom stops changing, thick lines rebuilt for it (settled)
        var zoom = Math.abs(targetZoom - canvas.zoom) < canvas.zoom * 0.005 ? targetZoom
                 : canvas.zoom + (targetZoom - canvas.zoom) * 0.25
        canvas.centerOn(centerX + (targetX - centerX) * ease, centerY + (targetY - centerY) * ease, zoom)
    }

    Connections {
        target: root.chart
        function onTargetStartChanged() { followTimer.restart(); viewTimer.restart() }
        function onTargetEndChanged() { followTimer.restart(); viewTimer.restart() }
        function onCursorMapChanged() { if (root.tracking) root.trackVehicles() }
    }
    Timer { id: followTimer; interval: 10; onTriggered: if (root.visible) root.followChart() }
    onInfoChanged: followTimer.restart()  // map built again (laps, orientation): zoomed part shown again
    onVisibleChanged: if (visible) { followTimer.restart(); viewTimer.restart() }
    Timer { id: viewTimer; interval: 50; onTriggered: root.updateView() }

    TpMenu {
        id: modeMenu
        Repeater {
            model: root.modes
            MenuItem {
                text: modelData[1]
                checkable: true
                checked: root.mode === modelData[0]
                onTriggered: backend.setMapMode(modelData[0])
            }
        }
    }
    TpMenu {
        id: displayMenu
        Action { text: i18n.tr("Follow zoom"); checkable: true; checked: backend.mapFollow; onTriggered: { backend.setMapFollow(checked); root.followChart() } }
        Action { text: i18n.tr("Follow vehicles"); checkable: true; checked: root.options.track === true; onTriggered: backend.setMapOption("track", checked) }
        Action { text: i18n.tr("Auto orient"); checkable: true; checked: backend.mapAutoOrient; onTriggered: backend.setMapAutoOrient(checked) }
        Action { text: i18n.tr("Turn map a quarter"); onTriggered: backend.rotateMap() }
        MenuSeparator {}
        Action { text: i18n.tr("Direction arrows"); checkable: true; checked: root.options.arrows === true; onTriggered: backend.setMapOption("arrows", checked) }
        Action { text: i18n.tr("Sector times"); checkable: true; checked: root.options.sectors === true; onTriggered: backend.setMapOption("sectors", checked) }
        Action { text: i18n.tr("Speed at points"); checkable: true; checked: root.options.values === true; onTriggered: backend.setMapOption("values", checked) }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.4

        // Coloring, driving points, display options
        Flow {
            Layout.fillWidth: true
            spacing: theme.em * 0.3
            TpButton {
                id: modeButton
                glyph: ""  // color
                text: root.modeTitle(root.mode) + "  ▾"
                tip: i18n.tr("Line coloring")
                implicitHeight: theme.em * 2
                checked: modeMenu.visible
                onClicked: modeMenu.visible ? modeMenu.close() : modeMenu.popup(modeButton, 0, modeButton.height + 4)
            }
            Repeater {
                model: [
                    ["brake", "◆ " + i18n.tr("Braking"), i18n.tr("Where each lap starts braking in each corner")],
                    ["apex", "● " + i18n.tr("Apex"), i18n.tr("Minimum speed point of each lap in each corner")],
                    ["exit", "▲ " + i18n.tr("Exit"), i18n.tr("Where each lap is back at full throttle after each apex")],
                    ["slip", "○ " + i18n.tr("Lockups"), i18n.tr("Front wheel lockups under braking (ring) & rear wheelspin on throttle (triangle)")],
                ]
                TpButton {
                    readonly property bool active: modelData[0] === "slip" ? backend.mapSlip : root.pointShown(modelData[0])
                    text: modelData[1]
                    tip: modelData[2]
                    flat: true
                    implicitHeight: theme.em * 2
                    checked: active
                    onClicked: {
                        if (modelData[0] === "slip") backend.setMapSlip(!active)
                        else if (modelData[0] === "brake") backend.setMapBraking(!active)
                        else backend.setMapOption(modelData[0], !active)
                    }
                }
            }
            TpButton {
                id: displayButton
                glyph: ""  // settings
                flat: true
                implicitHeight: theme.em * 2
                tip: i18n.tr("Map display")
                checked: displayMenu.visible
                onClicked: displayMenu.visible ? displayMenu.close() : displayMenu.popup(displayButton, 0, displayButton.height + 4)
            }
            TpButton {
                glyph: root.expanded ? "" : ""  // back to window, full screen
                flat: true
                implicitHeight: theme.em * 2
                tip: root.expanded ? i18n.tr("Back to charts") : i18n.tr("Large map over charts")
                onClicked: root.expandToggled()
            }
        }
        // Gain / loss & racing line: compared lap
        Flow {
            Layout.fillWidth: true
            visible: (root.mode === "gain" || root.mode === "line") && backend.comparedLaps.length > 1
            spacing: theme.em * 0.3
            Text { text: i18n.tr("Compared:"); color: theme.dimText; height: theme.em * 1.8; verticalAlignment: Text.AlignVCenter }
            Repeater {
                model: backend.comparedLaps
                TpButton {
                    text: modelData.label
                    flat: true
                    implicitHeight: theme.em * 1.8
                    checked: backend.compareKey === modelData.key
                    onClicked: backend.setCompareKey(modelData.key)
                }
            }
        }

        MapCanvas {
            id: canvas
            Layout.fillWidth: true
            Layout.fillHeight: true
            flipY: false  // recorded positions (x, -z): y down like in-game track map, else circuit mirrored
            maxZoom: 120
            minX: root.info.minX || 0
            minY: root.info.minY || 0
            maxX: root.info.maxX || 1
            maxY: root.info.maxY || 1
            onWidthChanged: aspectTimer.restart()
            onHeightChanged: aspectTimer.restart()
            onSettled: root.updateView()
            onUserZoomed: function(zoom) { if (root.tracking) root.trackZoom = zoom }
            onClicked: function(x, y) {
                if (!root.chart) return
                var position = backend.mapPick(x, y, theme.em * 1.5 * canvas.metersPerPixel)
                if (position >= 0) { root.scrubbing = false; root.chart.showX(position, "map") }
            }
            // Mouse over a line: chart cursor follows (scrub)
            onHovered: function(x, y) {
                if (!root.chart || root.chart.playing) return
                var position = backend.mapPick(x, y, theme.em * 1.2 * canvas.metersPerPixel)
                if (position >= 0) {
                    root.scrubbing = true
                    root.chart.setCursor(position, "map")
                } else if (root.scrubbing) {
                    root.scrubbing = false
                    root.chart.setCursor(NaN)
                }
            }
            onHoverEnded: if (root.scrubbing && root.chart) { root.scrubbing = false; root.chart.setCursor(NaN) }
            Timer {
                id: aspectTimer
                interval: 200
                onTriggered: if (root.visible && canvas.width > 0 && canvas.height > 0) backend.setMapAspect(canvas.width / canvas.height)
            }

            Text {
                anchors.centerIn: parent
                visible: !root.hasMap
                text: i18n.tr("No position recorded")
                color: theme.dimText
            }

            // Circuit
            GpuShape {
                key: root.info.edge || ""
                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.16 : 0.22)
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            GpuShape {
                key: root.info.road || ""
                color: theme.dark ? Qt.lighter(theme.base, 1.45) : Qt.darker(theme.base, 1.07)
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            GpuShape {
                key: root.info.marks || ""
                color: theme.accent
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }

            // Driving direction
            Repeater {
                model: root.options.arrows === true ? (root.info.arrows || []) : []
                Text {
                    x: canvas.screenX(modelData.x) - width / 2
                    y: canvas.screenY(modelData.y) - height / 2
                    rotation: modelData.angle
                    text: "❯"  // chevron
                    color: theme.text
                    opacity: 0.35
                    font.pixelSize: theme.em * 0.9
                    font.weight: Font.Bold
                }
            }

            // Driving lines: faded when zoomed (zoomed part drawn over), or under colored line
            Repeater {
                model: root.info.lines || []
                GpuShape {
                    key: modelData.key
                    color: modelData.color
                    revision: backend.revision
                    opacity: (root.mode === "laps" ? (root.chartZoomed ? 0.3 : 0.95)
                              : root.mode === "gain" || root.mode === "line" ? (modelData.reference ? 0.45 : 0) : 0.12)
                             * root.lapOpacity(modelData.lap)
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 250 } }
                    transform: Matrix4x4 { matrix: canvas.matrix }
                }
            }
            GpuShape {
                key: root.info.colored || ""
                opacity: root.mode === "laps" ? 0 : 1
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: 250 } }
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            Repeater {
                model: root.info.lines || []
                GpuShape {
                    key: modelData.highlight
                    color: modelData.color
                    visible: root.chartZoomed && root.mode === "laps"
                    opacity: root.lapOpacity(modelData.lap)
                    revision: backend.revision
                    transform: Matrix4x4 { matrix: canvas.matrix }
                }
            }

            // Start line: checkered bar across circuit
            Item {
                id: startLine
                readonly property var start: root.info.start || []
                readonly property real x0: canvas.screenX(start[0] || 0)
                readonly property real y0: canvas.screenY(start[1] || 0)
                readonly property real x1: canvas.screenX(start[2] || 0)
                readonly property real y1: canvas.screenY(start[3] || 0)
                readonly property real length: Math.max(Math.hypot(x1 - x0, y1 - y0), theme.em * 1.2)
                visible: start.length === 4
                x: (x0 + x1) / 2
                y: (y0 + y1) / 2
                rotation: Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI
                Row {
                    x: -startLine.length / 2
                    y: -height / 2
                    height: theme.em * 0.45
                    Repeater {
                        model: 6
                        Rectangle {
                            width: startLine.length / 6
                            height: theme.em * 0.45
                            color: index % 2 ? "#111111" : "#F5F5F5"
                        }
                    }
                }
            }

            // Sector times: reference lap time, gap of compared lap
            Repeater {
                model: root.options.sectors === true ? (root.info.sectors || []) : []
                Rectangle {
                    readonly property real anchorX: canvas.screenX(modelData.x)
                    readonly property real anchorY: canvas.screenY(modelData.y)
                    // Sector on screen: label kept inside map, else hidden (not pinned to map edge)
                    visible: anchorX >= 0 && anchorX <= canvas.width && anchorY >= 0 && anchorY <= canvas.height
                    x: Math.max(2, Math.min(anchorX - width / 2, canvas.width - width - 2))
                    y: canvas.screenY(modelData.y) + theme.em * 0.7
                    width: sectorRow.implicitWidth + theme.em * 0.8
                    height: sectorRow.implicitHeight + 4
                    radius: height / 2
                    color: Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.82)
                    border.width: 1
                    border.color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.6)
                    Row {
                        id: sectorRow
                        anchors.centerIn: parent
                        spacing: theme.em * 0.35
                        Text { text: modelData.label; color: theme.accent; font.pointSize: theme.fontPoint * 0.78; font.weight: Font.Bold }
                        Text { visible: modelData.time !== ""; text: modelData.time; color: theme.text; font.pointSize: theme.fontPoint * 0.78; font.features: { "tnum": 1 } }
                        Text {
                            visible: modelData.delta !== ""
                            text: modelData.delta
                            color: root.tone(modelData.deltaColor, theme.dimText)
                            font.pointSize: theme.fontPoint * 0.78
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }

            // Wheel lockups (ring) & wheelspin (triangle)
            Repeater {
                model: backend.mapSlip ? (root.info.slips || []) : []
                Item {
                    readonly property real size: theme.em * 0.8
                    x: canvas.screenX(modelData.x) - size / 2
                    y: canvas.screenY(modelData.y) - size / 2
                    width: size
                    height: size
                    opacity: root.lapOpacity(modelData.lap)
                    Rectangle {
                        anchors.fill: parent
                        visible: modelData.kind === "lock"
                        radius: width / 2
                        color: "transparent"
                        border.width: 2.5
                        border.color: modelData.color
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: modelData.kind === "spin"
                        text: "△"
                        color: modelData.color
                        style: Text.Outline
                        styleColor: theme.window
                        font.pixelSize: parent.size
                        font.weight: Font.Bold
                    }
                    ToolTip.visible: slipArea.containsMouse
                    ToolTip.text: (modelData.kind === "lock" ? i18n.tr("Front wheel lockup") : i18n.tr("Rear wheelspin"))
                                  + " · " + modelData.distance.toFixed(0) + " m"
                    MouseArea { id: slipArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
            }

            // Driving points: braking (diamond), apex (dot), exit at full throttle (triangle pointing forward)
            Repeater {
                model: root.info.points || []
                Item {
                    id: point
                    readonly property real size: theme.em * (modelData.kind === "exit" ? 1.0 : 0.72)
                    visible: root.pointShown(modelData.kind)
                    x: canvas.screenX(modelData.x) - size / 2
                    y: canvas.screenY(modelData.y) - size / 2
                    width: size
                    height: size
                    z: pointArea.containsMouse ? 2 : 1
                    opacity: root.lapOpacity(modelData.lap)
                    scale: pointArea.containsMouse ? 1.5 : 1
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Rectangle {
                        anchors.fill: parent
                        visible: modelData.kind !== "exit"
                        rotation: modelData.kind === "brake" ? 45 : 0
                        radius: modelData.kind === "apex" ? width / 2 : 0
                        color: modelData.color
                        border.width: 1.5
                        border.color: theme.window
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: modelData.kind === "exit"
                        rotation: modelData.angle + 90  // triangle points along driving direction
                        text: "▲"
                        color: modelData.color
                        style: Text.Outline
                        styleColor: theme.window
                        font.pixelSize: point.size
                    }
                    Text {
                        visible: root.options.values === true
                        x: point.size + 2
                        y: (point.size - height) / 2 + (modelData.order - 0.5) * height * 0.9  // laps stacked
                        text: modelData.value
                        color: modelData.color
                        style: Text.Outline
                        styleColor: theme.window
                        font.pointSize: theme.fontPoint * 0.7
                        font.weight: Font.Bold
                        font.features: { "tnum": 1 }
                    }
                    ToolTip.visible: pointArea.containsMouse
                    ToolTip.text: modelData.tip
                    ToolTip.delay: 150
                    MouseArea {
                        id: pointArea
                        anchors.fill: parent
                        anchors.margins: -3
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {  // zoom charts on this corner
                            var range = backend.cornerRange(modelData.corner)
                            if (range.length === 2 && root.chart) root.chart.zoomRange(range, 0.15)
                        }
                    }
                }
            }

            // Corners: number & time lost / gained, click to zoom charts on corner
            Repeater {
                model: root.info.corners || []
                Rectangle {
                    readonly property real anchorX: canvas.screenX(modelData.x)
                    visible: root.labelShown[index] === true || cornerArea.containsMouse
                    x: anchorX + 6 + width <= canvas.width ? anchorX + 6 : anchorX - 6 - width  // kept inside map
                    y: canvas.screenY(modelData.y) - height - 4
                    z: 3
                    width: cornerRow.implicitWidth + theme.em * 0.7
                    height: cornerRow.implicitHeight + 4
                    radius: height / 2
                    color: cornerArea.containsMouse ? theme.raised : Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.85)
                    border.width: 1
                    border.color: cornerArea.containsMouse ? theme.accent : Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.15)
                    Row {
                        id: cornerRow
                        anchors.centerIn: parent
                        spacing: theme.em * 0.3
                        Text { text: modelData.label; color: theme.text; font.pointSize: theme.fontPoint * 0.78; font.weight: Font.Bold }
                        Text {
                            visible: modelData.delta !== ""
                            text: modelData.delta
                            color: root.tone(modelData.deltaColor, theme.dimText)
                            font.pointSize: theme.fontPoint * 0.78
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                    MouseArea {
                        id: cornerArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (!root.chart) return
                            var start = backend.xAtDistance(modelData.start), end = backend.xAtDistance(modelData.end)
                            var margin = (end - start) * 0.15
                            root.chart.setView(start - margin, end + margin, true)
                        }
                    }
                }
            }

            // Cursor: each lap as an arrow pointing forward, gap to reference lap (one item per lap, kept while moving)
            Repeater {
                model: root.info.lines ? root.info.lines.length : 0
                Item {
                    id: car
                    readonly property var point: root.chart && root.chart.cursorMap[index] ? root.chart.cursorMap[index] : null
                    readonly property real size: theme.em * (index === 0 ? 1.15 : 0.95)
                    visible: point !== null
                    x: point ? canvas.screenX(point.x) : 0
                    y: point ? canvas.screenY(point.y) : 0
                    z: 4
                    opacity: point ? root.lapOpacity(point.lap) : 1
                    Item {
                        rotation: car.point ? car.point.angle + 90 : 0
                        Rectangle {
                            x: -car.size / 2
                            y: -car.size / 2
                            width: car.size
                            height: car.size
                            radius: car.size / 2
                            color: car.point ? car.point.color : "transparent"
                            border.width: 2
                            border.color: theme.window
                        }
                        Text {  // nose: driving direction
                            x: -width / 2
                            y: -car.size / 2 - height * 0.62
                            text: "▲"
                            color: car.point ? car.point.color : "transparent"
                            style: Text.Outline
                            styleColor: theme.window
                            font.pixelSize: car.size * 0.75
                        }
                    }
                    Rectangle {
                        visible: car.point !== null && car.point.gap !== ""
                        x: car.size * 0.7
                        y: -height / 2
                        width: gapText.implicitWidth + theme.em * 0.6
                        height: gapText.implicitHeight + 2
                        radius: height / 2
                        color: Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.85)
                        border.width: 1
                        border.color: car.point ? car.point.color : "transparent"
                        Text {
                            id: gapText
                            anchors.centerIn: parent
                            text: car.point ? car.point.gap : ""
                            color: car.point ? car.point.color : theme.text
                            font.pointSize: theme.fontPoint * 0.75
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
        }

        // Legend: color mode
        Flow {
            Layout.fillWidth: true
            visible: root.hasMap
            spacing: theme.em * 0.8
            Repeater {
                model: root.mode === "gain" ? [[i18n.tr("Losing time"), "#EF4444"], [i18n.tr("Gaining time"), "#22C55E"]]
                     : root.mode === "pedals" ? [[i18n.tr("Throttle"), "#22C55E"], [i18n.tr("Brake"), "#EF4444"],
                                                 [i18n.tr("Both"), "#F59E0B"], [i18n.tr("Coasting"), "#9CA3AF"]]
                     : root.mode === "line" ? [[i18n.tr("Inside"), "#3B82F6"], [i18n.tr("Same line"), "#9CA3AF"],
                                               [i18n.tr("Outside"), "#F97316"]]
                     : root.mode === "gear" ? [["1", "#EF4444"], ["2", "#F97316"], ["3", "#FACC15"], ["4", "#84CC16"],
                                               ["5", "#22C55E"], ["6", "#06B6D4"], ["7", "#3B82F6"], ["8", "#A855F7"]]
                     : []
                Row {
                    spacing: theme.em * 0.3
                    Rectangle { width: theme.em * 0.6; height: width; radius: width / 2; color: modelData[1]; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: modelData[0]; color: theme.text; font.pointSize: theme.fontPoint * 0.85 }
                }
            }
            Row {
                visible: backend.mapLegend.low !== undefined && (root.mode === "speed" || root.mode === "elevation")
                spacing: theme.em * 0.4
                Text { text: backend.mapLegend.low || ""; color: theme.text; font.pointSize: theme.fontPoint * 0.85 }
                Rectangle {
                    id: legendBar
                    readonly property var colors: backend.mapLegend.colors || ["#3B82F6", "#EF4444"]
                    width: theme.em * 7
                    height: theme.em * 0.5
                    radius: height / 2
                    anchors.verticalCenter: parent.verticalCenter
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: legendBar.colors[0] }
                        GradientStop { position: 0.5; color: legendBar.colors[Math.floor(legendBar.colors.length / 2)] }
                        GradientStop { position: 1; color: legendBar.colors[legendBar.colors.length - 1] }
                    }
                }
                Text {
                    text: (backend.mapLegend.high || "") + " " + (backend.mapLegend.unit || "")
                    color: theme.text
                    font.pointSize: theme.fontPoint * 0.85
                }
            }
            Text {
                visible: root.mode === "elevation" && backend.mapLegend.low === undefined
                text: i18n.tr("Elevation not recorded")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
            }
            Text {
                visible: (root.mode === "gain" || root.mode === "line") && backend.comparedLaps.length === 0
                text: i18n.tr("Check a second lap to compare")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
            }
        }
    }
}
