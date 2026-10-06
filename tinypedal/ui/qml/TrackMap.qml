import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import TinyPedal

// Lap viewer track map: circuit (between track limits guessed from every recorded lap), driving lines colored
// by lap, time gain, speed, pedals, racing line, gear, elevation or time delta per corner.
// Driving points of each lap in each corner (braking, apex, exit at full throttle, track-out) & wheel slips are
// GPU drawn markers: hover one for its values, click to zoom charts on its corner.
// Mouse over a line: same point shown in charts (cursor), click: position kept (charts & map), Ctrl+click a line:
// lap highlighted. Zooming or moving the map zooms charts on the part of lap shown (Sync zoom), and back.
// Corner label: hover for every lap in this corner, click to zoom & select it in corner table.
// Keys: F fit, + / - zoom, arrows move, R turn, 1-9 coloring, B/C/S/O driving points, L slips, G off track,
// X track limits, Z zones, T trail, M ruler, Esc.
FocusScope {
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
        ["elevation", i18n.tr("Elevation")], ["corners", i18n.tr("Delta per corner")],
        ["minisectors", i18n.tr("Mini-sectors")], ["consistency", i18n.tr("Consistency")],
    ]
    readonly property string highlightKey: chart ? chart.highlightKey : ""
    property bool scrubbing: false  // chart cursor set by mouse over map
    property var hoverPosition: null  // last mouse position over map (world), handled once per frame
    property var hoverPoint: null  // driving point under mouse (tooltip)
    property var card: ({})  // corner card shown (every lap in a corner)
    property var cardAnchor: [0, 0]
    property bool rulerMode: false  // clicks measure distance
    property var syncedView: null  // chart range set by map: map does not follow charts back for that range
    property var placement: ({})  // lap across track under mouse (room to edges)
    property bool reportedShown: false  // map shown, told to backend (cursor trails)
    property var rulerPoints: []  // world positions
    // Vehicles followed while playing lap or moving cursor with keys: view centered on them, zoomed in
    readonly property bool tracking: chart !== undefined && chart !== null && hasMap && visible
                                     && options.track === true && (chart.playing || chart.cursorSource === "key")
    readonly property real trackWindow: 300  // meters shown around vehicles when following starts
    readonly property real trackMargin: 60  // meters kept around followed vehicles
    property real trackZoom: 1  // zoom while following, changed with wheel
    readonly property var comparedLaps: backend.comparedLaps  // read once (list built by backend)
    // Shown cursor positions: none while hidden (no item updated on every cursor move)
    readonly property var cursorPoints: visible && chart ? chart.cursorMap : []
    // Map scale corner labels were placed for: overlaps only depend on scale (moving the map changes none),
    // placed again once scale changed by 2% (zoom easing) and when zoom settles
    property real labelScale: 1  // set at start & by changes below (never a binding: one per frame)
    Connections {
        target: canvas
        function onMapScaleChanged() {
            if (Math.abs(canvas.mapScale - root.labelScale) > root.labelScale * 0.02) root.labelScale = canvas.mapScale
        }
        function onSettled() { root.labelScale = canvas.mapScale }
    }
    // Corner labels shown: highest time delta first, labels overlapping a shown one hidden
    readonly property var labelShown: {
        var corners = info.corners || []
        var order = corners.map(function(corner, index) { return index })
        order.sort(function(a, b) { return (corners[b].priority || 0) - (corners[a].priority || 0) })
        var placed = []
        var shown = []
        var lineHeight = theme.em * 1.3
        var scale = labelScale, ySign = canvas.ySign  // places relative to map origin: same overlaps wherever moved
        for (var i = 0; i < order.length; i++) {
            var corner = corners[order[i]]
            var width = (corner.label.length + (corner.delta ? corner.delta.length + 1 : 0)) * theme.em * 0.55 + theme.em * 0.8
            var x = corner.x * scale + 6, y = ySign * corner.y * scale - lineHeight - 4
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

    // Gain / loss colors: theme green & red, or blue & orange for color blindness
    function tone(name, fallback) {
        if (name === "loss") return options.colorblind === true ? "#F97316" : theme.loss
        if (name === "gain") return options.colorblind === true ? "#3B82F6" : theme.gain
        return fallback
    }
    function lapOpacity(lapKey) { return highlightKey === "" || lapKey === highlightKey ? 1 : 0.2 }
    function modeTitle(name) {
        for (var i = 0; i < modes.length; i++) if (modes[i][0] === name) return modes[i][1]
        return name
    }
    function pointShown(kind) {
        if (kind === "brake") return backend.mapBraking
        if (kind === "lock" || kind === "spin") return backend.mapSlip
        return options[kind] === true
    }
    function shownKinds() {
        return ["brake", "apex", "exit", "trackout", "lock", "spin", "offtrack", "limit"].filter(function(kind) { return root.pointShown(kind) })
    }
    function hasEvents(kind) {
        var events = info.events || []
        for (var i = 0; i < events.length; i++) if (events[i].kind === kind) return true
        return false
    }
    function togglePoint(kind) {
        if (kind === "slip") backend.setMapSlip(!backend.mapSlip)
        else if (kind === "brake") backend.setMapBraking(!backend.mapBraking)
        else backend.setMapOption(kind, !(options[kind] === true))
    }
    function followChart() {
        var synced = syncedView
        syncedView = null
        // Charts zoomed by map: map stays as user set it (only for that exact range: a range already shown
        // changes nothing, next chart zoom is followed again)
        if (synced && chart && Math.abs(chart.targetStart - synced[0]) < 1e-6 && Math.abs(chart.targetEnd - synced[1]) < 1e-6) return
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
    function zoomCorner(row) {
        var range = backend.cornerRange(row)
        if (range.length === 2 && chart) chart.zoomRange(range, 0.15)
        backend.setSelectedCorner(row)
    }
    // Mouse over map, at most once per frame: driving point tooltip, else chart cursor on line (scrub)
    function handleHover() {
        if (hoverPosition === null) return
        var x = hoverPosition[0], y = hoverPosition[1]
        if (rulerMode) return
        var point = backend.mapPointAt(x, y, theme.em * 0.8 * canvas.metersPerPixel, shownKinds())
        hoverPoint = point.tip !== undefined ? point : null
        if (!chart || chart.playing) return
        var position = backend.mapPick(x, y, theme.em * 1.2 * canvas.metersPerPixel)
        if (position >= 0) {
            scrubbing = true
            chart.setCursor(position, "map")
            placement = hoverPoint === null ? backend.placementAt(position, highlightKey) : ({})
        } else if (scrubbing) {
            scrubbing = false
            placement = ({})
            chart.restoreCursor()
        } else {
            placement = ({})
        }
    }
    // Map zoomed or moved by user: charts show the part of lap seen on map (whole lap when map zoomed out)
    function syncChart() {
        if (!backend.mapFollow || !chart || tracking || !hasMap) return
        var range = []
        if (canvas.targetZoom > 1.01) {  // view map is easing to
            var top = canvas.targetWorld(0, 0), bottom = canvas.targetWorld(canvas.width, canvas.height)
            var middle = canvas.targetWorld(canvas.width / 2, canvas.height / 2)
            range = backend.mapVisibleRange(Math.min(top[0], bottom[0]), Math.min(top[1], bottom[1]),
                                            Math.max(top[0], bottom[0]), Math.max(top[1], bottom[1]), middle[0], middle[1])
            if (range.length !== 2) return
        }
        if (range.length === 2) chart.setView(range[0], range[1], true)
        else chart.resetView(true)
        syncedView = [chart.targetStart, chart.targetEnd]
    }
    // Charts & map zoom synchronized both ways, or each zoomed on its own
    function setSync(enabled) {
        backend.setMapFollow(enabled)
        if (enabled) root.followChart()
    }
    function reportShown() {
        if (visible !== reportedShown) {
            reportedShown = visible
            backend.setMapShown(visible)
            if (visible && chart && chart.hasCursor) chart.fetchCursor()  // cursor positions skipped while hidden
        }
    }
    Component.onCompleted: { labelScale = canvas.mapScale; reportShown() }
    Component.onDestruction: if (reportedShown) backend.setMapShown(false)
    function exportPicture(copy) {
        canvas.grabToImage(function(result) {
            if (copy) backend.copyImage(result.image)
            else backend.saveImage(result.image)
        })
    }

    // Following starts: zoomed in on vehicles (unless already closer)
    onTrackingChanged: if (tracking) {
        var shown = Math.min(canvas.width, canvas.height) * canvas.metersPerPixel
        trackZoom = shown > trackWindow ? canvas.zoom * shown / trackWindow : canvas.zoom
    }
    // View centered on followed vehicles (highlighted lap only if any), zoomed out if needed to keep all of them,
    // eased toward target each update: smooth camera
    function trackVehicles(frameTime) {
        var points = (chart.cursorMap || []).filter(function(point) {
            return point && (highlightKey === "" || point.lap === highlightKey)
        })
        if (points.length === 0 || canvas.width <= 0) return true
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
        var ease = 1 - Math.exp(-(frameTime || 0.016) / 0.09)  // same feel whatever the frame rate
        // Zoom close to target set exactly: zoom stops changing, thick lines rebuilt for it (settled)
        var zoomDone = Math.abs(targetZoom - canvas.zoom) < canvas.zoom * 0.005
        var zoom = zoomDone ? targetZoom : Math.exp(Math.log(canvas.zoom) + (Math.log(targetZoom) - Math.log(canvas.zoom)) * ease)
        var moveDone = Math.hypot(targetX - centerX, targetY - centerY) * canvas.mapScale < 0.5
        canvas.centerOn(moveDone ? targetX : centerX + (targetX - centerX) * ease,
                        moveDone ? targetY : centerY + (targetY - centerY) * ease, zoom)
        return zoomDone && moveDone
    }
    FrameAnimation {
        id: camera
        onTriggered: if (!root.tracking || root.trackVehicles(frameTime)) stop()
    }

    Connections {
        target: root.chart
        function onTargetStartChanged() { followTimer.restart(); viewTimer.restart() }
        function onTargetEndChanged() { followTimer.restart(); viewTimer.restart() }
        function onCursorMapChanged() { if (root.tracking && !camera.running) camera.start() }
    }
    Timer { id: followTimer; interval: 10; onTriggered: if (root.visible) root.followChart() }
    onInfoChanged: { followTimer.restart(); hoverPoint = null; card = ({}) }  // map built again: zoomed part shown again
    onVisibleChanged: {
        reportShown()
        if (visible) { followTimer.restart(); viewTimer.restart() }
    }
    Timer { id: syncTimer; interval: 160; onTriggered: root.syncChart() }  // wheel turning stopped
    Timer { id: viewTimer; interval: 50; onTriggered: root.updateView() }
    Timer { id: hoverTimer; interval: 16; onTriggered: root.handleHover() }
    Timer {
        id: cardTimer
        interval: 350
        property int row: -1
        onTriggered: root.card = row >= 0 ? backend.cornerCard(row) : ({})
    }

    // Digit of key (0-9, else -1), also digit row of layouts typing other characters there without Shift
    // (French AZERTY: & é " ' ( - è _ ç à): Windows scan codes of digit row 1-9, 0
    function digitOf(event) {
        if (event.key >= Qt.Key_0 && event.key <= Qt.Key_9) return event.key - Qt.Key_0
        if (Qt.platform.os === "windows" && (event.modifiers & (Qt.ControlModifier | Qt.AltModifier)) === 0
                && event.nativeScanCode >= 0x02 && event.nativeScanCode <= 0x0B)
            return (event.nativeScanCode - 1) % 10
        return -1
    }

    Keys.onPressed: function(event) {
        var digit = digitOf(event) - 1  // keys 1-9: coloring, before zoom (AZERTY 6 & 8 type - & _)
        if (digit >= 0 && digit < Math.min(modes.length, 9)) {
            backend.setMapMode(modes[digit][0])
            event.accepted = true
            return
        }
        if (canvas.handleKey(event.key)) { event.accepted = true; return }  // + / - zoom, arrows move
        if (event.key === Qt.Key_F) canvas.reset(true)
        else if (event.key === Qt.Key_R) backend.rotateMap()
        else if (event.key === Qt.Key_B) togglePoint("brake")
        else if (event.key === Qt.Key_C) togglePoint("apex")
        else if (event.key === Qt.Key_S) togglePoint("exit")
        else if (event.key === Qt.Key_O) togglePoint("trackout")
        else if (event.key === Qt.Key_L) togglePoint("slip")
        else if (event.key === Qt.Key_G) togglePoint("offtrack")
        else if (event.key === Qt.Key_X) togglePoint("limit")
        else if (event.key === Qt.Key_Z) backend.setMapOption("zones", !(options.zones === true))
        else if (event.key === Qt.Key_T) backend.setMapOption("trail", !(options.trail === true))
        else if (event.key === Qt.Key_M) { rulerMode = !rulerMode; rulerPoints = [] }
        else if (event.key === Qt.Key_Escape) {  // never left to viewer window: Esc there closes it
            if (rulerMode || rulerPoints.length) { rulerMode = false; rulerPoints = [] }
            else if (expanded) expandToggled()
            else if (chart) chart.forceActiveFocus()  // keys back to charts
        }
        else return
        event.accepted = true
    }

    TpMenu {
        id: modeMenu
        Repeater {
            model: root.modes
            MenuItem {
                text: (index < 9 ? (index + 1) + "  " : "     ") + modelData[1]  // keys 1-9
                checkable: true
                checked: root.mode === modelData[0]
                onTriggered: backend.setMapMode(modelData[0])
            }
        }
    }
    TpMenu {
        id: displayMenu
        Action { text: i18n.tr("Sync zoom with charts"); checkable: true; checked: backend.mapFollow; onTriggered: root.setSync(checked) }
        Action { text: i18n.tr("Follow vehicles"); checkable: true; checked: root.options.track === true; onTriggered: backend.setMapOption("track", checked) }
        Action { text: i18n.tr("Auto orient"); checkable: true; checked: backend.mapAutoOrient; onTriggered: backend.setMapAutoOrient(checked) }
        Action { text: i18n.tr("Turn map a quarter"); onTriggered: backend.rotateMap() }
        MenuSeparator {}
        Action { text: i18n.tr("Track limits"); checkable: true; checked: root.options.limits === true; onTriggered: backend.setMapOption("limits", checked) }
        Action { text: i18n.tr("Pit lane"); checkable: true; checked: root.options.pit === true; onTriggered: backend.setMapOption("pit", checked) }
        Action { text: i18n.tr("Braking points spread"); checkable: true; checked: root.options.spread === true; onTriggered: backend.setMapOption("spread", checked) }
        Action { text: i18n.tr("Minimap"); checkable: true; checked: root.options.minimap === true; onTriggered: backend.setMapOption("minimap", checked) }
        Action { text: i18n.tr("Pedal zones"); checkable: true; checked: root.options.zones === true; onTriggered: backend.setMapOption("zones", checked) }
        Action { text: i18n.tr("Cursor trail"); checkable: true; checked: root.options.trail === true; onTriggered: backend.setMapOption("trail", checked) }
        Action { text: i18n.tr("Direction arrows"); checkable: true; checked: root.options.arrows === true; onTriggered: backend.setMapOption("arrows", checked) }
        Action { text: i18n.tr("Sector times"); checkable: true; checked: root.options.sectors === true; onTriggered: backend.setMapOption("sectors", checked) }
        Action { text: i18n.tr("Speed at points"); checkable: true; checked: root.options.values === true; onTriggered: backend.setMapOption("values", checked) }
        Action { text: i18n.tr("Distance marks"); checkable: true; checked: root.options.distances === true; onTriggered: backend.setMapOption("distances", checked) }
        Action { text: i18n.tr("Colorblind colors"); checkable: true; checked: root.options.colorblind === true; onTriggered: backend.setMapOption("colorblind", checked) }
        Action { text: i18n.tr("Remove Kept Position"); enabled: backend.mapPin.x !== undefined; onTriggered: backend.clearPinned() }
        MenuSeparator {}
        Action { text: i18n.tr("Export Map Picture..."); onTriggered: root.exportPicture(false) }
        Action { text: i18n.tr("Copy Map Picture"); onTriggered: root.exportPicture(true) }
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
                    ["brake", "◆ " + i18n.tr("Braking"), i18n.tr("Where each lap starts braking in each corner") + " (B)"],
                    ["apex", "● " + i18n.tr("Apex"), i18n.tr("Minimum speed point of each lap in each corner") + " (C)"],
                    ["exit", "▲ " + i18n.tr("Exit"), i18n.tr("Where each lap is back at full throttle after each apex") + " (S)"],
                    ["trackout", "■ " + i18n.tr("Track-out"), i18n.tr("Where each lap comes closest to the outside edge after each apex (track limits needed)") + " (O)"],
                    ["slip", "○ " + i18n.tr("Lockups"), i18n.tr("Front wheel lockups under braking (ring) & rear wheelspin on throttle (triangle)") + " (L)"],
                    ["offtrack", "◇ " + i18n.tr("Off track"), i18n.tr("Where 2 wheels or more go on grass, dirt or gravel (laps recorded with this version)") + " (G)"],
                    ["limit", "✕ " + i18n.tr("Limits"), i18n.tr("Where car goes beyond track edge, four wheels out (game track edges needed)") + " (X)"],
                ]
                TpButton {
                    readonly property bool active: root.pointShown(modelData[0] === "slip" ? "lock" : modelData[0])
                    visible: (modelData[0] !== "trackout" || backend.hasLimits)
                             && (modelData[0] !== "offtrack" && modelData[0] !== "limit" || root.hasEvents(modelData[0]))
                    text: modelData[1]
                    tip: modelData[2]
                    flat: true
                    implicitHeight: theme.em * 2
                    checked: active
                    onClicked: root.togglePoint(modelData[0])
                }
            }
            TpButton {
                glyph: ""  // ruler
                flat: true
                implicitHeight: theme.em * 2
                tip: i18n.tr("Measure distance: click two points on the map (M)")
                checked: root.rulerMode
                onClicked: { root.rulerMode = !root.rulerMode; root.rulerPoints = [] }
            }
            TpButton {
                glyph: "\uE71B"  // link
                flat: true
                implicitHeight: theme.em * 2
                checked: backend.mapFollow
                tip: (backend.mapFollow ? i18n.tr("Zoom synchronized with charts: click to zoom map and charts separately")
                                        : i18n.tr("Map and charts zoomed separately: click to synchronize zoom"))
                onClicked: root.setSync(!backend.mapFollow)
            }
            TpButton {
                id: displayButton
                glyph: ""  // settings
                flat: true
                implicitHeight: theme.em * 2
                tip: i18n.tr("Map display") + "\n" + i18n.tr("Keys: F fit, +/- zoom, arrows move, R turn, 1-9 coloring, B C S O points, L lockups, G off track, X track limits, Z zones, T trail, M ruler")
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
        // Compared lap (gain / loss, racing line, delta per corner)
        Flow {
            Layout.fillWidth: true
            visible: (root.mode === "gain" || root.mode === "line" || root.mode === "corners") && root.comparedLaps.length > 1
            spacing: theme.em * 0.3
            Text { text: i18n.tr("Compared:"); color: theme.dimText; height: theme.em * 1.8; verticalAlignment: Text.AlignVCenter }
            Repeater {
                model: root.comparedLaps
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
            feet: backend.distanceUnit === "ft"
            minX: root.info.minX || 0
            minY: root.info.minY || 0
            maxX: root.info.maxX || 1
            maxY: root.info.maxY || 1
            onWidthChanged: aspectTimer.restart()
            onHeightChanged: aspectTimer.restart()
            onSettled: root.updateView()
            onScaling: function(metersPerPixel) { if (root.visible && root.hasMap) backend.previewMapScale(metersPerPixel) }
            // Zoom starting: thick lines of target scale built in background, shown while zoom eases
            onTargetZoomChanged: if (root.visible && root.hasMap && Math.abs(targetZoom - zoom) > zoom * 0.05)
                backend.prepareMapScale(metersPerPixel * zoom / targetZoom)
            zoomFollows: root.tracking
            onUserZoomed: function(zoom) {
                if (!root.tracking) return
                root.trackZoom = zoom
                if (!camera.running) camera.start()
            }
            onUserMoved: syncTimer.restart()
            onClicked: function(x, y) {
                root.forceActiveFocus()
                if (root.rulerMode) {
                    root.rulerPoints = root.rulerPoints.length >= 2 ? [[x, y]] : root.rulerPoints.concat([[x, y]])
                    return
                }
                var point = backend.mapPointAt(x, y, theme.em * 0.8 * canvas.metersPerPixel, root.shownKinds())
                if (point.corner !== undefined && point.corner >= 0) { root.zoomCorner(point.corner); return }
                if (!root.chart) return
                if (canvas.clickModifiers & Qt.ControlModifier) {  // Ctrl+click a line: lap highlighted everywhere
                    var hit = backend.mapPickLap(x, y, theme.em * 1.5 * canvas.metersPerPixel)
                    root.chart.pinnedKey = hit.lap === undefined || root.chart.pinnedKey === hit.lap ? "" : hit.lap
                    return
                }
                var position = backend.mapPick(x, y, theme.em * 1.5 * canvas.metersPerPixel)
                if (position >= 0) {  // position kept: charts & map show it until cleared
                    root.scrubbing = false
                    backend.setPinned(position)
                    root.chart.showX(position, "pin")
                }
            }
            onHovered: function(x, y) {
                root.hoverPosition = [x, y]
                if (!hoverTimer.running) hoverTimer.start()
            }
            onHoverEnded: {
                root.hoverPosition = null
                root.hoverPoint = null
                root.placement = ({})
                if (root.scrubbing && root.chart) { root.scrubbing = false; root.chart.restoreCursor() }
            }
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

            // Pit lane (official circuit)
            GpuShape {
                visible: root.options.pit === true
                key: root.info.pit || ""
                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.22 : 0.25)
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            // Circuit: road (between track limits if guessed), edge, sector lines
            GpuShape {
                key: root.info.edge || ""
                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, root.info.limits ? (theme.dark ? 0.35 : 0.4) : (theme.dark ? 0.16 : 0.22))
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
            // Braking points range of shown laps in each corner
            GpuShape {
                visible: root.options.spread === true
                key: root.info.spread || ""
                color: Qt.rgba(0.94, 0.27, 0.27, 0.3)
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            // Chart markers A-B range & selected corner along reference line
            GpuShape {
                key: root.info.rangeKey || ""
                color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.28)
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            GpuShape {
                key: root.info.selectedKey || ""
                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.16)
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            // Distance marks, placed from map origin in an item moved with the map: moving the map moves one item,
            // not every label (same place on screen as canvas.screenX / screenY)
            Item {
                x: canvas.tx
                y: canvas.ty
                Repeater {
                    model: root.options.distances === true ? (root.info.ticks || []) : []
                    Item {
                        x: modelData.x * canvas.mapScale
                        y: canvas.ySign * modelData.y * canvas.mapScale
                        Rectangle { x: -2; y: -2; width: 4; height: 4; radius: 2; color: theme.dimText }
                        Text {
                            x: 4; y: -height - 1
                            text: modelData.label
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.68
                            style: Text.Outline
                            styleColor: theme.window
                        }
                    }
                }
            }
            // Driving direction
            GpuShape {
                visible: root.options.arrows === true
                key: root.info.arrowsKey || ""
                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.3)
                revision: backend.revision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            // Driving lines: faded when zoomed (zoomed part drawn over), or under colored line
            // (lap rows kept: showing one more lap only adds its shapes)
            Repeater {
                model: backend.mapLaps
                GpuShape {
                    key: model.key
                    color: model.color
                    revision: backend.revision
                    opacity: (root.mode === "laps" ? (root.chartZoomed ? 0.3 : 0.95)
                              : root.mode === "gain" || root.mode === "line" ? (model.reference ? 0.45 : 0) : 0.12)
                             * root.lapOpacity(model.lap)
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
                model: backend.mapLaps
                GpuShape {
                    key: model.highlight
                    color: model.color
                    visible: root.chartZoomed && root.mode === "laps"
                    opacity: root.lapOpacity(model.lap)
                    revision: backend.revision
                    transform: Matrix4x4 { matrix: canvas.matrix }
                }
            }
            // Braking & throttle application zones over lines: highlighted lap, else reference lap
            Repeater {
                model: backend.mapLaps
                Item {
                    readonly property var lap: model
                    visible: root.options.zones === true && (root.highlightKey !== "" ? lap.lap === root.highlightKey : lap.reference)
                    GpuShape {
                        key: lap.brakeZones
                        color: Qt.rgba(0.94, 0.27, 0.27, 0.45)
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                    GpuShape {
                        key: lap.throttleZones
                        color: root.options.colorblind === true ? Qt.rgba(0.23, 0.51, 0.96, 0.45) : Qt.rgba(0.13, 0.77, 0.37, 0.45)
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                }
            }

            // Cursor trail: last seconds of each lap, fading in
            Repeater {
                model: backend.mapLaps
                GpuShape {
                    key: model.trail
                    visible: root.options.trail === true && root.chart !== undefined && root.chart !== null && root.chart.hasCursor
                    opacity: root.lapOpacity(model.lap)
                    revision: backend.trailRevision
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
                    y: anchorY + theme.em * 0.7
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

            // Driving points & wheel slips: GPU markers, one shape per lap & kind (outline under fill)
            Repeater {
                model: backend.mapLaps
                Item {
                    readonly property var lap: model
                    opacity: root.lapOpacity(lap.lap)
                    Repeater {
                        model: lap.shapes
                        Item {
                            visible: root.pointShown(modelData.kind)
                            GpuShape {
                                key: modelData.outline
                                color: theme.window
                                revision: backend.revision
                                transform: Matrix4x4 { matrix: canvas.matrix }
                            }
                            GpuShape {
                                key: modelData.fill
                                color: lap.color
                                revision: backend.revision
                                transform: Matrix4x4 { matrix: canvas.matrix }
                            }
                        }
                    }
                }
            }
            // Speed next to driving points (option): laps stacked, moved with the map like distance marks
            Item {
                x: canvas.tx
                y: canvas.ty
                Repeater {
                    model: root.options.values === true ? (root.info.points || []) : []
                    Text {
                        visible: root.pointShown(modelData.kind)
                        x: modelData.x * canvas.mapScale + theme.em * 0.6
                        y: canvas.ySign * modelData.y * canvas.mapScale - height / 2 + (modelData.order - 0.5) * height * 0.9
                        opacity: root.lapOpacity(modelData.lap)
                        text: modelData.value
                        color: modelData.color
                        style: Text.Outline
                        styleColor: theme.window
                        font.pointSize: theme.fontPoint * 0.7
                        font.weight: Font.Bold
                        font.features: { "tnum": 1 }
                    }
                }
            }

            // Corners: number & time lost / gained. Hover: every lap in corner, click: zoom & select in corner table
            Repeater {
                model: root.info.corners || []
                Rectangle {
                    readonly property real anchorX: canvas.screenX(modelData.x)
                    readonly property bool selected: modelData.row >= 0 && modelData.row === backend.selectedCorner
                    visible: root.labelShown[index] === true || cornerArea.containsMouse || selected
                    x: anchorX + 6 + width <= canvas.width ? anchorX + 6 : anchorX - 6 - width  // kept inside map
                    y: canvas.screenY(modelData.y) - height - 4
                    z: 3
                    width: cornerRow.implicitWidth + theme.em * 0.7
                    height: cornerRow.implicitHeight + 4
                    radius: height / 2
                    color: cornerArea.containsMouse ? theme.raised : Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.85)
                    border.width: selected ? 1.5 : 1
                    border.color: cornerArea.containsMouse || selected ? theme.accent : Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.15)
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
                        onEntered: if (modelData.row >= 0) {
                            root.cardAnchor = [parent.x, parent.y + parent.height + 4]
                            cardTimer.row = modelData.row
                            cardTimer.restart()
                        }
                        onExited: { cardTimer.stop(); root.card = ({}) }
                        onClicked: {
                            root.forceActiveFocus()
                            if (!root.chart) return
                            if (modelData.row >= 0) { root.zoomCorner(modelData.row); return }
                            var start = backend.xAtDistance(modelData.start), end = backend.xAtDistance(modelData.end)
                            var margin = (end - start) * 0.15
                            root.chart.setView(start - margin, end + margin, true)
                        }
                    }
                }
            }

            // Cursor: each lap as an arrow pointing forward, gap to reference lap (one item per lap, kept while moving)
            Repeater {
                model: backend.mapLaps
                Item {
                    id: car
                    readonly property var point: root.cursorPoints[index] || null
                    readonly property real size: theme.em * (model.reference ? 1.15 : 0.95)  // reference lap larger
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
                    Text {  // slip angle: car pointing direction against driving direction (recorded heading)
                        visible: car.point !== null && (car.point.slip || "") !== "" && root.tracking
                        x: -width / 2
                        y: car.size * 0.75
                        text: car.point ? car.point.slip || "" : ""
                        color: car.point ? car.point.color : theme.text
                        style: Text.Outline
                        styleColor: theme.window
                        font.pointSize: theme.fontPoint * 0.72
                        font.weight: Font.Bold
                        font.features: { "tnum": 1 }
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

            // Kept position (click on map or charts)
            Item {
                readonly property var pin: backend.mapPin
                visible: pin.x !== undefined
                x: pin.x !== undefined ? canvas.screenX(pin.x) : 0
                y: pin.y !== undefined ? canvas.screenY(pin.y) : 0
                z: 4
                Rectangle {
                    x: -width / 2
                    y: -height / 2
                    width: theme.em * 1.25
                    height: width
                    radius: width / 2
                    color: "transparent"
                    border.width: 2.5
                    border.color: theme.accent
                }
                Rectangle { x: -3; y: -3; width: 6; height: 6; radius: 3; color: theme.accent }
            }

            // Ruler: two clicked points, straight distance between them
            Item {
                anchors.fill: parent
                z: 5
                visible: root.rulerPoints.length > 0
                Repeater {
                    model: root.rulerPoints
                    Rectangle {
                        readonly property real size: theme.em * 0.7
                        x: canvas.screenX(modelData[0]) - size / 2
                        y: canvas.screenY(modelData[1]) - size / 2
                        width: size
                        height: size
                        radius: size / 2
                        color: theme.accent
                        border.width: 2
                        border.color: theme.window
                    }
                }
                Rectangle {
                    readonly property var a: root.rulerPoints[0] || [0, 0]
                    readonly property var b: root.rulerPoints[1] || [0, 0]
                    readonly property real ax: canvas.screenX(a[0])
                    readonly property real ay: canvas.screenY(a[1])
                    readonly property real bx: canvas.screenX(b[0])
                    readonly property real by: canvas.screenY(b[1])
                    visible: root.rulerPoints.length === 2
                    x: ax
                    y: ay - height / 2
                    width: Math.hypot(bx - ax, by - ay)
                    height: 2
                    color: theme.accent
                    transformOrigin: Item.Left
                    rotation: Math.atan2(by - ay, bx - ax) * 180 / Math.PI
                }
                Rectangle {
                    readonly property var a: root.rulerPoints[0] || [0, 0]
                    readonly property var b: root.rulerPoints[1] || [0, 0]
                    visible: root.rulerPoints.length === 2
                    x: (canvas.screenX(a[0]) + canvas.screenX(b[0])) / 2 - width / 2
                    y: (canvas.screenY(a[1]) + canvas.screenY(b[1])) / 2 - height - 6
                    width: rulerText.implicitWidth + theme.em * 0.8
                    height: rulerText.implicitHeight + 4
                    radius: height / 2
                    color: theme.accent
                    Text {
                        id: rulerText
                        anchors.centerIn: parent
                        text: (Math.hypot(parent.b[0] - parent.a[0], parent.b[1] - parent.a[1]) * backend.distanceScale).toFixed(1)
                              .replace(".", theme.decimalPoint) + " " + backend.distanceUnit
                        color: "white"
                        font.weight: Font.Bold
                        font.features: { "tnum": 1 }
                    }
                }
            }
            Text {
                visible: root.rulerMode
                anchors { left: parent.left; top: parent.top; margins: theme.em * 0.5 }
                text: i18n.tr("Ruler: click two points (Esc to quit)")
                color: theme.accent
                font.pointSize: theme.fontPoint * 0.85
            }

            // Lap across track under mouse: room to each edge, track position
            Rectangle {
                z: 6
                visible: root.placement.text !== undefined && root.hoverPosition !== null
                readonly property real px: root.hoverPosition ? canvas.screenX(root.hoverPosition[0]) : 0
                readonly property real py: root.hoverPosition ? canvas.screenY(root.hoverPosition[1]) : 0
                x: Math.max(2, Math.min(px + theme.em, canvas.width - width - 2))
                y: py + theme.em * 1.2 + height < canvas.height ? py + theme.em * 1.2 : py - height - theme.em
                width: placementText.implicitWidth + theme.em * 0.8
                height: placementText.implicitHeight + theme.em * 0.4
                radius: theme.em * 0.3
                color: Qt.rgba(theme.raised.r, theme.raised.g, theme.raised.b, 0.94)
                border.width: 1
                border.color: root.placement.out ? theme.warning : (root.placement.color || theme.border)
                Text {
                    id: placementText
                    anchors.centerIn: parent
                    text: root.placement.text || ""
                    color: theme.text
                    font.pointSize: theme.fontPoint * 0.78
                    font.features: { "tnum": 1 }
                }
            }

            // Minimap: whole circuit & part shown, click to go there
            Rectangle {
                id: minimap
                z: 8
                readonly property real side: Math.min(theme.em * 9, canvas.width * 0.32, canvas.height * 0.32)
                readonly property real spanX: Math.max((root.info.maxX || 1) - (root.info.minX || 0), 1)
                readonly property real spanY: Math.max((root.info.maxY || 1) - (root.info.minY || 0), 1)
                readonly property real mapScale: (side - 12) / Math.max(spanX, spanY)
                readonly property real offsetX: (side - spanX * mapScale) / 2 - (root.info.minX || 0) * mapScale
                readonly property real offsetY: (side - spanY * mapScale) / 2 - (root.info.minY || 0) * mapScale
                visible: root.options.minimap === true && root.hasMap && canvas.zoom > 1.6 && side > theme.em * 4
                anchors { left: parent.left; bottom: parent.bottom; margins: theme.em * 0.5 }
                width: side
                height: side
                radius: theme.em * 0.4
                color: Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.85)
                border.width: 1
                border.color: theme.border
                clip: true
                GpuShape {
                    key: root.info.mini || ""
                    color: theme.dimText
                    revision: backend.revision
                    transform: Matrix4x4 {
                        matrix: Qt.matrix4x4(minimap.mapScale, 0, 0, minimap.offsetX, 0, minimap.mapScale, 0, minimap.offsetY, 0, 0, 1, 0, 0, 0, 0, 1)
                    }
                }
                Rectangle {  // part of circuit shown on map
                    readonly property real x0: canvas.worldX(0) * minimap.mapScale + minimap.offsetX
                    readonly property real y0: canvas.worldY(0) * minimap.mapScale + minimap.offsetY
                    readonly property real x1: canvas.worldX(canvas.width) * minimap.mapScale + minimap.offsetX
                    readonly property real y1: canvas.worldY(canvas.height) * minimap.mapScale + minimap.offsetY
                    x: Math.min(x0, x1)
                    y: Math.min(y0, y1)
                    width: Math.max(Math.abs(x1 - x0), 3)
                    height: Math.max(Math.abs(y1 - y0), 3)
                    color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.15)
                    border.width: 1.5
                    border.color: theme.accent
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function(mouse) {
                        var x = (mouse.x - minimap.offsetX) / minimap.mapScale, y = (mouse.y - minimap.offsetY) / minimap.mapScale
                        var scale = canvas.baseScale * canvas.targetZoom
                        canvas.setView(canvas.targetZoom, (canvas.centerX - x) * scale, canvas.ySign * (canvas.centerY - y) * scale, true)
                        canvas.userMoved()
                    }
                    onWheel: function(wheel) { wheel.accepted = true }
                }
            }

            // Driving point tooltip
            Rectangle {
                z: 6
                visible: root.hoverPoint !== null
                readonly property real px: root.hoverPoint ? canvas.screenX(root.hoverPoint.x) : 0
                readonly property real py: root.hoverPoint ? canvas.screenY(root.hoverPoint.y) : 0
                x: Math.max(2, Math.min(px + theme.em, canvas.width - width - 2))
                y: Math.max(2, py - height - theme.em * 0.6)
                width: tipText.implicitWidth + theme.em
                height: tipText.implicitHeight + theme.em * 0.5
                radius: theme.em * 0.35
                color: theme.raised
                border.width: 1
                border.color: root.hoverPoint ? root.hoverPoint.color : theme.border
                Text {
                    id: tipText
                    anchors.centerIn: parent
                    text: root.hoverPoint ? root.hoverPoint.tip : ""
                    color: theme.text
                    font.pointSize: theme.fontPoint * 0.85
                    font.features: { "tnum": 1 }
                }
            }

            // Corner card: every shown lap in hovered corner
            Rectangle {
                z: 7
                visible: root.card.title !== undefined
                x: Math.max(2, Math.min(root.cardAnchor[0], canvas.width - width - 2))
                y: Math.min(root.cardAnchor[1], canvas.height - height - 2)
                width: cardColumn.implicitWidth + theme.em
                height: cardColumn.implicitHeight + theme.em * 0.6
                radius: theme.em * 0.4
                color: theme.raised
                border.width: 1
                border.color: theme.accent
                Column {
                    id: cardColumn
                    anchors.centerIn: parent
                    spacing: 2
                    Text {
                        text: (root.card.title || "") + "  ·  " + (root.card.apex || "")
                        color: theme.text
                        font.weight: Font.Bold
                    }
                    Text {
                        visible: (root.card.spread || "") !== ""
                        text: "◆ " + (root.card.spread || "")
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.8
                    }
                    Text {
                        visible: (root.card.widthTitle || "") !== ""
                        text: "↔ " + (root.card.widthTitle || "")
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.78
                    }
                    Repeater {
                        model: root.card.laps || []
                        Row {
                            spacing: theme.em * 0.5
                            Rectangle { width: theme.em * 0.55; height: width; radius: width / 2; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: modelData.label; color: theme.text; font.pointSize: theme.fontPoint * 0.82; width: theme.em * 7.5; elide: Text.ElideRight }
                            Text { text: modelData.time; color: theme.text; font.pointSize: theme.fontPoint * 0.82; font.features: { "tnum": 1 } }
                            Text {
                                text: modelData.gap
                                width: theme.em * 3
                                color: root.tone(modelData.gapColor, theme.dimText)
                                font.pointSize: theme.fontPoint * 0.82
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                            Text { text: modelData.speeds; color: theme.dimText; font.pointSize: theme.fontPoint * 0.78; font.features: { "tnum": 1 } }
                            Text {
                                text: "◆ " + modelData.brake + "  ▲ " + modelData.throttle
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.78
                                font.features: { "tnum": 1 }
                            }
                            Text {
                                visible: (modelData.width || "") !== ""
                                text: "↔ " + (modelData.width || "")
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.78
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                }
            }
        }

        // Legend: color mode, driving point shapes, zones
        Flow {
            Layout.fillWidth: true
            visible: root.hasMap
            spacing: theme.em * 0.8
            Repeater {
                model: root.mode === "gain" || root.mode === "corners"
                       ? [[i18n.tr("Losing time"), root.tone("loss", "")], [i18n.tr("Gaining time"), root.tone("gain", "")]]
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
            // Driving point shapes shown
            Repeater {
                model: [
                    ["brake", "◆", i18n.tr("Braking")], ["apex", "●", i18n.tr("Apex")], ["exit", "▲", i18n.tr("Exit")],
                    ["trackout", "■", i18n.tr("Track-out")], ["lock", "○", i18n.tr("Lockup")], ["spin", "△", i18n.tr("Wheelspin")],
                    ["offtrack", "◇", i18n.tr("Off track")], ["limit", "✕", i18n.tr("Track limits exceeded")],
                ]
                Text {
                    visible: root.pointShown(modelData[0]) && (modelData[0] !== "trackout" || backend.hasLimits)
                             && (modelData[0] !== "offtrack" && modelData[0] !== "limit" || root.hasEvents(modelData[0]))
                    text: modelData[1] + " " + modelData[2]
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.8
                }
            }
            Row {
                visible: root.options.zones === true
                spacing: theme.em * 0.6
                Text { text: "▬ " + i18n.tr("Braking zone"); color: "#EF4444"; font.pointSize: theme.fontPoint * 0.8 }
                Text { text: "▬ " + i18n.tr("Throttle application"); color: root.options.colorblind === true ? "#3B82F6" : "#22C55E"; font.pointSize: theme.fontPoint * 0.8 }
            }
            // Track limits exceeded & off track count of each shown lap
            Repeater {
                model: root.pointShown("limit") || root.pointShown("offtrack") ? (root.info.violations || []) : []
                Row {
                    spacing: theme.em * 0.25
                    Rectangle { width: theme.em * 0.5; height: width; radius: width / 2; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: modelData.label + (modelData.limits > 0 ? "  ✕" + modelData.limits : "") + (modelData.offtrack > 0 ? "  ◇" + modelData.offtrack : "")
                        color: modelData.limits > 0 ? theme.warning : theme.dimText
                        font.pointSize: theme.fontPoint * 0.8
                        font.features: { "tnum": 1 }
                    }
                }
            }
            // Mini-sectors won by each lap, ideal lap
            Repeater {
                model: root.mode === "minisectors" ? (backend.mapLegend.mini || []) : []
                Row {
                    spacing: theme.em * 0.3
                    Rectangle { width: theme.em * 0.6; height: width; radius: width / 2; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: modelData.label + "  " + modelData.count + "/" + (backend.mapLegend.sectors || 0); color: theme.text; font.pointSize: theme.fontPoint * 0.85; font.features: { "tnum": 1 } }
                }
            }
            Text {
                visible: root.mode === "minisectors" && (backend.mapLegend.ideal || "") !== ""
                text: i18n.tr("Ideal of shown laps:") + " " + (backend.mapLegend.ideal || "")
                color: theme.gold
                font.pointSize: theme.fontPoint * 0.85
                font.weight: Font.DemiBold
            }
            // Consistency: spread (standard deviation) of mini-sector times over laps of stint, session or shown laps
            TpSegmented {
                visible: root.mode === "consistency"
                readonly property var scopes: ["stint", "session", "shown"]
                options: [i18n.tr("This stint"), i18n.tr("This session"), i18n.tr("Shown laps")]
                currentIndex: scopes.indexOf(backend.consistencyScope)
                onActivated: function(index) { backend.setConsistencyScope(scopes[index]) }
            }
            Row {
                visible: root.mode === "consistency" && backend.mapLegend.low !== undefined
                spacing: theme.em * 0.4
                Text { text: (backend.mapLegend.low || "") + " s"; color: theme.text; font.pointSize: theme.fontPoint * 0.85 }
                Rectangle {
                    id: spreadBar
                    readonly property var colors: backend.mapLegend.colors || ["#22C55E", "#FACC15", "#EF4444"]
                    width: theme.em * 7
                    height: theme.em * 0.5
                    radius: height / 2
                    anchors.verticalCenter: parent.verticalCenter
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: spreadBar.colors[0] }
                        GradientStop { position: 0.5; color: spreadBar.colors[Math.floor(spreadBar.colors.length / 2)] }
                        GradientStop { position: 1; color: spreadBar.colors[spreadBar.colors.length - 1] }
                    }
                }
                Text { text: (backend.mapLegend.high || "") + " s"; color: theme.text; font.pointSize: theme.fontPoint * 0.85 }
            }
            Text {
                visible: root.mode === "consistency"
                text: backend.mapLegend.text || ""
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                HoverHandler { id: spreadHover }
                ToolTip.visible: spreadHover.hovered
                ToolTip.delay: 400
                ToolTip.text: i18n.tr("Green: same time in this mini-sector lap after lap, red: time changes a lot (standard deviation)")
            }
            Text {
                visible: root.info.official === true
                text: "✓ " + i18n.tr("Official circuit (game)")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.8
                HoverHandler { id: officialHover }
                ToolTip.visible: officialHover.hovered
                ToolTip.delay: 400
                ToolTip.text: i18n.tr("Circuit path & pit lane given by Le Mans Ultimate") + (root.info.layout ? " (" + root.info.layout + ")" : "")
            }
            Text {
                visible: backend.limitsSource !== "" && root.options.limits !== false
                text: "┆ " + (backend.limitsSource === "game" ? i18n.tr("Track edges from game")
                                                            : i18n.tr("Track edges estimated from laps"))
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.8
                HoverHandler { id: limitsHover }
                ToolTip.visible: limitsHover.hovered
                ToolTip.delay: 400
                ToolTip.text: backend.limitsSource === "game"
                              ? i18n.tr("Track edges & car placement across track given by game")
                              : i18n.tr("Laps recorded before this version: track edges guessed from where laps drove")
            }
            Text {
                visible: root.mode === "elevation" && backend.mapLegend.low === undefined
                text: i18n.tr("Elevation not recorded")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
            }
            Text {
                visible: (root.mode === "gain" || root.mode === "line" || root.mode === "corners") && root.comparedLaps.length === 0
                text: i18n.tr("Check a second lap to compare")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
            }
        }
    }
}
