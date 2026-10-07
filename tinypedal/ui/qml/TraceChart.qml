import QtQuick
import QtQuick.Controls.Basic
import TinyPedal

// Stacked channel charts along lap distance (or lap time), lines drawn by GPU
// Wheel: zoom (eased every frame: smooth), drag: move, click: keep position, double-click: reset,
// panel menu: values fitted to visible part, drag a channel name: reorder, drag a channel lower edge: resize,
// right-click: menu.
// Keyboard: +/- zoom, left/right one recorded frame (Ctrl: farther, Shift: move view, while playing: 2 s),
// Alt+left/right previous / next zoom, Home or 0 reset, [ ] previous / next corner, A / B markers,
// Esc clear markers (then kept position), R reference = highlighted lap, Space play, L loop A-B, , . speed,
// ? keyboard help.
FocusScope {
    id: chart

    readonly property real maxX: Math.max(backend.maxX, 1)
    property real targetStart: 0
    property real targetEnd: maxX
    // Shown range [start, end], eased toward target range every frame: one assignment per frame, so bindings
    // placing items along axis (xOf) run once per frame, not once per end
    property var viewRange: [0, 1]
    readonly property real viewStart: viewRange[0]
    readonly property real viewEnd: viewRange[1]
    // Pixels per axis unit: labels overlap depends on it only (moving the view changes none)
    readonly property real viewScale: plotArea.width / Math.max(viewRange[1] - viewRange[0], 1e-9)
    // Scale corner labels were placed for: placed again once scale changed by 0.5% (zoom easing), or settled
    // (view moved without zoom: rounding changes of scale ignored)
    property real labelScale: 1
    onViewScaleChanged: {
        var change = Math.abs(viewScale - labelScale)
        if (change > labelScale * 0.005 || (!viewEasing.running && change > labelScale * 1e-6)) labelScale = viewScale
    }
    property bool animate: false
    property real cursorX: NaN
    property string cursorSource: "mouse"  // what moved cursor: mouse, key, play, map (map follows play & key)
    readonly property bool hasCursor: !isNaN(cursorX)
    readonly property bool cursorShown: hasCursor && cursorX >= viewRange[0] && cursorX <= viewRange[1]
    property string cursorTitle: ""
    property var cursorValues: []
    // Per panel from cursorValues (worked out once per cursor update, not per item & frame):
    // count of values shown, row of each series in bubble, compact text (built when first asked)
    property var cursorPanels: []
    property var cursorMap: []  // map position of each lap at cursor (TrackMap)
    property var cursorG: []  // G circle position of each lap at cursor (GCircle)
    readonly property bool zoomed: targetEnd - targetStart < maxX - 1
    readonly property real labelWidth: theme.em * 7
    readonly property real gap: theme.em * 0.35
    property var panels: backend.panels
    readonly property var emptyPanel: ({ "column": "", "title": "", "unit": "", "parts": [], "series": [],
                                         "available": false, "weight": 1, "note": "" })
    // Lists read once from backend (each read converts a Python list)
    readonly property var sectors: backend.sectorLines
    readonly property var marks: backend.cornerMarks
    readonly property real pinX: backend.pinnedX
    property int movingFrom: -1
    property int movingTo: -1
    property var lineOffsets: [[0, 0], [0.5, 0.5]]
    property int resizing: -1  // panel whose height is dragged
    property real resizeWeight: 0
    property string hoverKey: ""  // lap highlighted while hovering its legend chip
    property string pinnedKey: ""  // lap highlighted by clicking its legend chip
    readonly property string highlightKey: hoverKey || pinnedKey
    // Markers A & B kept as reference lap distances (like kept position): same place on track when time axis
    // is toggled or reference lap changes, axis positions follow (chartChanged)
    property real markerDistanceA: NaN
    property real markerDistanceB: NaN
    property string markerTrack: ""  // track markers were set on (set once, not a binding: change seen first)
    readonly property real markerA: { backend.timeAxis; return axisAt(markerDistanceA) }
    readonly property real markerB: { backend.timeAxis; return axisAt(markerDistanceB) }
    readonly property bool hasRange: !isNaN(markerA) && !isNaN(markerB) && markerA !== markerB
    property bool playing: false
    property real playSpeed: 1
    property real playTime: 0
    property real playFrom: 0  // played part: whole lap, or between markers A & B (reference lap time)
    property real playTo: 0
    property bool playLoop: true  // part between markers played again and again
    readonly property var playSpeeds: [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4]
    readonly property real skipStep: 2  // seconds moved by back / forward buttons, and arrow keys while playing
    property var viewHistory: []  // zooms shown (settled), Alt+left / right go back & forth
    property int historyIndex: -1
    property bool browsingHistory: false
    // Time of each shown lap between markers A & B (passage), fastest flagged
    readonly property var passage: hasRange && backend.legend.length > 0 ? backend.passageTimes(markerA, markerB) : []
    readonly property real minPanelHeight: theme.em * 3.2
    readonly property real totalWeight: {
        var sum = 0
        for (var i = 0; i < panels.length; i++) sum += panelWeight(i)
        return sum || 1
    }
    readonly property real contentHeight: Math.max(scroller.height, totalWeight * minPanelHeight)
    // Top of each panel (prefix sums of weights), one more entry: bottom of last panel
    readonly property var panelTops: {
        var tops = [0]
        var weight = 0
        var scale = plotArea.height / totalWeight
        for (var i = 0; i < panels.length; i++) {
            weight += panelWeight(i)
            tops.push(weight * scale)
        }
        return tops
    }
    // Corner names shown in strip above panels: a label too close to previous shown one, or to a sector label, is hidden.
    // Distances between labels only depend on scale: placed from axis origin at labelScale
    readonly property var cornerLabelShown: {
        var marks = chart.marks
        var scale = labelScale
        var sectors = [0].concat(chart.sectors.map(function(line) { return line.x * scale }))
        var shown = []
        var last = -1e9
        for (var i = 0; i < marks.length; i++) {
            var px = marks[i].x * scale
            var free = px - last >= marks[i].label.length * theme.em * 0.55 + theme.em * 0.4
            for (var j = 0; j < sectors.length && free; j++)
                if (px > sectors[j] - marks[i].label.length * theme.em * 0.55 - theme.em * 0.3 && px < sectors[j] + theme.em * 1.8) free = false
            shown.push(free)
            if (free) last = px
        }
        return shown
    }

    signal pictureRequested(bool copy)
    signal rangeSet()
    signal helpRequested()
    signal setupRequested(string lapKey)

    // Value axis of panels fitted to visible part of lap: column: axis (low, high, ticks, lowText, highText).
    // Panels without one show their whole value range
    property var yViews: ({})
    function axisOf(info) {
        var view = info ? yViews[info.column] : undefined
        return view && view.low !== undefined ? view : info
    }
    function updateAutoscale() {
        var views = {}
        for (var i = 0; i < panels.length; i++) {
            var column = panels[i].column
            if (panels[i].autoscale) views[column] = backend.autoscaleAxis(column, targetStart, targetEnd)
        }
        yViews = views
    }
    Timer { id: autoscaleTimer; interval: 40; onTriggered: chart.updateAutoscale() }
    function setAutoscale(index, enabled) {
        var info = panels[index]
        if (!info) return
        backend.setPanelAutoscale(info.column, enabled)
        autoscaleTimer.restart()
    }

    // Reduced copy of a series drawn when each of its buckets is at most a pixel wide (same look, fewer vertices).
    // Level worked out once for the chart: series keys change only when the level does (not every zoom frame)
    readonly property var lodLevels: backend.lodLevels  // buckets over whole lap, finest last
    readonly property int lodTier: {
        var needed = Screen.devicePixelRatio * maxX * viewScale
        for (var i = 0; i < lodLevels.length; i++) if (lodLevels[i] >= needed) return i
        return lodLevels.length
    }
    function seriesKey(series) {
        var lods = series.lods || []
        return lodTier < lods.length ? lods[lodTier][1] : series.key
    }
    // Shown range eased toward target every frame (exponential): wheel steps blend into one smooth move
    FrameAnimation {
        id: viewEasing
        onTriggered: {
            var ease = 1 - Math.exp(-frameTime / 0.07)
            var span = Math.max(chart.targetEnd - chart.targetStart, 1e-9)
            var start = chart.viewRange[0] + (chart.targetStart - chart.viewRange[0]) * ease
            var end = chart.viewRange[1] + (chart.targetEnd - chart.viewRange[1]) * ease
            if (Math.abs(start - chart.targetStart) < span * 1e-4 && Math.abs(end - chart.targetEnd) < span * 1e-4) {
                stop()  // first: settled scale places corner labels exactly
                chart.viewRange = [chart.targetStart, chart.targetEnd]
            } else {
                chart.viewRange = [start, end]
            }
        }
    }
    property bool settingView: false
    function followTarget() {
        if (settingView) return
        if (animate) { if (!viewEasing.running) viewEasing.start() }
        else { viewEasing.stop(); viewRange = [targetStart, targetEnd] }
    }
    Component.onCompleted: { viewRange = [targetStart, targetEnd]; labelScale = viewScale; markerTrack = backend.currentTrack + "|" + backend.trackLabel }

    function setView(start, end, animated) {
        var span = end - start
        if (span >= maxX) { start = 0; end = maxX }
        else if (start < 0) { end -= start; start = 0 }
        else if (end > maxX) { start -= end - maxX; end = maxX }
        animate = animated
        settingView = true  // both ends set before shown range follows
        targetStart = Math.max(start, 0)
        targetEnd = Math.min(end, maxX)
        settingView = false
        backend.setChartView(targetStart, targetEnd)
        followTarget()
        if (!browsingHistory) historyTimer.restart()
        autoscaleTimer.restart()
    }
    function resetView(animated) { setView(0, maxX, animated) }
    function zoom(factor, center, animated) {
        if (center === undefined || isNaN(center)) center = (targetStart + targetEnd) / 2
        var start = center - (center - targetStart) * factor
        var end = center + (targetEnd - center) * factor
        if (end - start >= (backend.timeAxis ? 0.5 : 5)) setView(start, end, animated)
    }
    function showX(x, source) {
        if (x < targetStart || x > targetEnd) {
            var span = targetEnd - targetStart
            setView(x - span / 2, x + span / 2, true)
        }
        setCursor(x, source)
    }
    function zoomRange(range, margin) {
        if (range.length !== 2) return
        var extra = (range[1] - range[0]) * margin
        setView(range[0] - extra, range[1] + extra, true)
    }
    function zoomSector(sector) { zoomRange(backend.sectorRange(sector), 0.02) }
    function sectorAt(x) {
        var lines = chart.sectors
        var sector = 1
        for (var i = 0; i < lines.length; i++) if (x >= lines[i].x) sector = lines[i].index + 1
        return sector
    }
    // Previous / next corner (zoomed on), from view center
    function stepCorner(direction) {
        var ranges = backend.cornerRanges
        if (ranges.length === 0) return
        var center = zoomed ? (targetStart + targetEnd) / 2 : (direction > 0 ? -1 : maxX + 1)
        var index = -1
        if (direction > 0) {
            for (var i = 0; i < ranges.length; i++)
                if ((ranges[i][0] + ranges[i][1]) / 2 > center + 1) { index = i; break }
        } else {
            for (var j = ranges.length - 1; j >= 0; j--)
                if ((ranges[j][0] + ranges[j][1]) / 2 < center - 1) { index = j; break }
        }
        if (index >= 0) zoomRange(ranges[index], 0.15)
    }
    // Cursor line moves at once, values (chart bubbles, map, G circle) asked to backend once per frame
    property bool cursorPending: false
    FrameAnimation {
        running: chart.cursorPending
        onTriggered: { chart.cursorPending = false; chart.fetchCursor() }
    }
    function setCursor(x, source) {
        cursorSource = source || "mouse"
        cursorX = x
        if (isNaN(x)) {
            cursorPending = false
            cursorTitle = ""
            cursorValues = []
            cursorPanels = []
            cursorMap = []
            cursorG = []
            return
        }
        if (cursorSource === "mouse") cursorPending = true
        else fetchCursor()
    }
    function fetchCursor() {
        if (isNaN(cursorX)) return
        var state = backend.cursorState(cursorX)
        cursorTitle = state.title
        cursorPanels = state.values.map(cursorPanel)
        cursorValues = state.values
        // Map & G circle positions empty while hidden: not set again (their items not updated every move)
        if (state.map.length > 0 || cursorMap.length > 0) cursorMap = state.map
        if (state.g.length > 0 || cursorG.length > 0) cursorG = state.g
    }
    function cursorPanel(values) {
        var rows = []
        var count = 0
        for (var i = 0; i < values.length; i++) {
            rows.push(count)
            if (values[i] && values[i].text !== "") count++
        }
        return { "count": count, "rows": rows, "values": values, "compact": undefined }
    }
    // Mouse left charts or map: cursor back to kept position (or none)
    function restoreCursor() {
        var pinned = backend.pinnedX
        if (pinned >= 0) setCursor(pinned, "pin")
        else setCursor(NaN)
    }
    function zoomCornerAt(x) {
        var ranges = backend.cornerRanges
        for (var i = 0; i < ranges.length; i++)
            if (x >= ranges[i][0] && x <= ranges[i][1]) { zoomRange(ranges[i], 0.15); return }
        var span = maxX * 0.03
        setView(x - span, x + span, true)
    }
    function axisAt(distance) { return isNaN(distance) ? NaN : backend.xAtDistance(distance) }
    function setMarker(which, x) {
        if (isNaN(x)) return
        if (which === "A") markerDistanceA = backend.distanceAt(x)
        else markerDistanceB = backend.distanceAt(x)
        if (hasRange) rangeSet()
    }
    function clearMarkers() { markerDistanceA = NaN; markerDistanceB = NaN }
    // Play lap, or only part between markers A & B (looped), from cursor if inside played part
    function togglePlay() {
        if (playing) { playing = false; return }
        if (backend.referenceLapTime <= 0) return
        updatePlayRange()
        if (hasRange) {
            var low = Math.min(markerA, markerB), high = Math.max(markerA, markerB)
            if (targetStart > low || targetEnd < high) zoomRange([low, high], 0.08)  // passage in view
        }
        var start = hasCursor ? backend.referenceTimeAt(cursorX) : backend.referenceTimeAt(targetStart)
        playTime = start >= playFrom && start < playTo - 0.05 ? start : playFrom
        playing = true
    }
    function xOf(value) { return (value - viewRange[0]) / Math.max(viewRange[1] - viewRange[0], 1e-9) * plotArea.width }
    function valueOf(px) { return viewRange[0] + px / Math.max(plotArea.width, 1) * (viewRange[1] - viewRange[0]) }
    function panelInfo(index) { return panels[index] || emptyPanel }
    function panelWeight(index) {
        if (index === resizing) return resizeWeight
        return panels[index] ? panels[index].weight : 1
    }
    function panelTop(index) { return panelTops[Math.max(0, Math.min(index, panelTops.length - 1))] }
    function panelHeight(index) { return panelWeight(index) / totalWeight * plotArea.height - gap }
    function panelAt(y) {
        for (var i = 0; i < panels.length; i++)
            if (y < panelTops[i + 1] - gap / 2) return i
        return panels.length - 1
    }
    function rangeOf(index) {
        var info = panels[index]
        return info ? [info.low, info.high] : [0, 1]
    }
    function cursorEntry(panelIndex, seriesIndex) {
        var values = cursorValues[panelIndex]
        return values && values[seriesIndex] ? values[seriesIndex] : null
    }
    function valueCount(panelIndex) {
        var panel = cursorPanels[panelIndex]
        return panel ? panel.count : 0
    }
    // Line of a series value in its panel bubble: values shown before it (empty ones hidden)
    function valueRow(panelIndex, seriesIndex) {
        var panel = cursorPanels[panelIndex]
        if (!panel) return 0
        return seriesIndex < panel.rows.length ? panel.rows[seriesIndex] : panel.count
    }
    // Cursor values bubble fits in panel, else values shown under channel name
    function bubbleFits(panelIndex) {
        return panelHeight(panelIndex) > valueCount(panelIndex) * theme.em * 1.3 + theme.em * 0.4
    }
    // Values of panel on one line (bubble does not fit), built once per cursor update when first asked
    function compactValues(panelIndex) {
        var panel = cursorPanels[panelIndex]
        if (!panel) return ""
        if (panel.compact === undefined) {
            var values = panel.values
            var texts = []
            for (var i = 0; i < values.length && texts.length < 4; i++)
                if (values[i].text !== "") texts.push("<font color='" + values[i].color + "'>" + values[i].text + "</font>")
            panel.compact = texts.join(" ")
        }
        return panel.compact
    }
    function lapOpacity(lapKey) { return highlightKey === "" || lapKey === highlightKey ? 1 : 0.18 }
    function niceStep(span, count) {
        var raw = Math.max(span / Math.max(count, 1), 1e-9)
        var magnitude = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10))
        var multiples = [1, 2, 5, 10]
        for (var i = 0; i < multiples.length; i++)
            if (raw <= multiples[i] * magnitude) return multiples[i] * magnitude
        return 10 * magnitude
    }
    readonly property real distanceScale: backend.distanceScale  // user distance unit (m or ft) per meter
    readonly property string distanceUnit: backend.distanceUnit
    // Decimals of axis labels: as many as tick step needs (zoomed in to 5 m or 0.5 s: steps below one)
    function stepDecimals(step) { return Math.min(Math.max(Math.ceil(-Math.log(step) / Math.LN10 - 1e-6), 0), 3) }
    function axisText(value) {
        if (!backend.timeAxis) {
            var distance = (value * distanceScale).toFixed(stepDecimals(tickStep * distanceScale))
            return distance.replace(".", theme.decimalPoint) + " " + distanceUnit
        }
        var decimals = stepDecimals(tickStep)
        var factor = Math.pow(10, decimals)
        var total = Math.round(value * factor) / factor  // rounded first: 119.5 s is 2:00, never 1:60
        if (total < 60) return total.toFixed(decimals).replace(".", theme.decimalPoint) + "s"
        var minutes = Math.floor(total / 60 + 1e-9)
        var seconds = Math.max(total - minutes * 60, 0)
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds.toFixed(decimals).replace(".", theme.decimalPoint)
    }

    // Laps added or removed: same zoom kept if still inside lap, whole lap otherwise
    onMaxXChanged: {
        if (zoomed && targetStart < maxX) setView(targetStart, Math.min(targetEnd, maxX), false)
        else resetView(false)
    }
    onTargetStartChanged: viewChanged()
    onTargetEndChanged: viewChanged()
    function viewChanged() {
        if (settingView) return  // setView tells backend once both ends are set
        backend.setChartView(targetStart, targetEnd)
        followTarget()
        if (!browsingHistory) historyTimer.restart()
        autoscaleTimer.restart()
    }
    onMarkerAChanged: markersMoved()
    onMarkerBChanged: markersMoved()
    // Markers moved: shown on map, passage played follows them
    function markersMoved() {
        backend.setMapRange(hasRange ? markerA : -1, hasRange ? markerB : -1)
        if (playing) updatePlayRange()
    }
    function updatePlayRange() {
        if (hasRange) {
            playFrom = backend.referenceTimeAt(Math.min(markerA, markerB))
            playTo = backend.referenceTimeAt(Math.max(markerA, markerB))
            if (playTime < playFrom || playTime > playTo) playTime = playFrom
        } else {
            playFrom = 0
            playTo = backend.referenceLapTime
        }
    }
    // Zoom history: view kept once it stays the same for a moment, as reference lap distances (same part of lap
    // shown again after time axis is toggled)
    Timer {
        id: historyTimer
        interval: 700
        onTriggered: {
            var view = [backend.distanceAt(chart.targetStart), backend.distanceAt(chart.targetEnd)]
            var last = chart.viewHistory[chart.historyIndex]
            if (last && Math.abs(last[0] - view[0]) < 1e-3 && Math.abs(last[1] - view[1]) < 1e-3) return
            var kept = chart.viewHistory.slice(0, chart.historyIndex + 1)
            kept.push(view)
            if (kept.length > 40) kept.shift()
            chart.viewHistory = kept
            chart.historyIndex = kept.length - 1
        }
    }
    function stepHistory(direction) {
        historyTimer.stop()
        var index = historyIndex + direction
        if (index < 0 || index >= viewHistory.length) return
        historyIndex = index
        browsingHistory = true
        setView(backend.xAtDistance(viewHistory[index][0]), backend.xAtDistance(viewHistory[index][1]), true)
        browsingHistory = false
    }
    function changeSpeed(direction) {
        var index = playSpeeds.indexOf(playSpeed)
        playSpeed = playSpeeds[Math.max(0, Math.min(playSpeeds.length - 1, (index < 0 ? playSpeeds.indexOf(1) : index) + direction))]
    }
    // Back or forth in time along reference lap: played time while playing (stays in played part),
    // else cursor (from view center if none), view follows it
    function skipTime(seconds) {
        if (backend.referenceLapTime <= 0) return
        if (playing) {
            playTime = Math.max(playFrom, Math.min(playTime + seconds, playTo))
            return
        }
        var start = backend.referenceTimeAt(hasCursor ? cursorX : (targetStart + targetEnd) / 2)
        var x = backend.xAtReferenceTime(Math.max(0, Math.min(start + seconds, backend.referenceLapTime)))
        var span = targetEnd - targetStart
        if (x < targetStart || x > targetEnd) setView(x - span / 2, x + span / 2, false)
        setCursor(x, "key")
    }
    onPanelsChanged: {
        if (hasCursor) setCursor(cursorX, cursorSource)
        autoscaleTimer.restart()  // laps or channels changed: fitted ranges again
    }

    Connections {
        target: backend
        function onViewRestored(start, end) { chart.setView(start, end, false) }
        function onPageHidden() { chart.playing = false }  // no cursor update every frame while page is hidden
        function onTracksChanged() {  // markers A & B are distances of one circuit: cleared for another track
            var circuit = backend.currentTrack + "|" + backend.trackLabel  // label: circuit shown without track folder
            if (circuit === chart.markerTrack) return
            chart.markerTrack = circuit
            chart.clearMarkers()
        }
        function onPinChanged() { if (!chart.hasCursor || chart.cursorSource === "pin") chart.restoreCursor() }
        // Side tab changed: map & G circle positions only sent while shown, asked again
        function onOptionsChanged() { if (chart.hasCursor) chart.fetchCursor() }
        function onChartChanged() {
            var keys = backend.legend.map(function(item) { return item.key })
            if (keys.indexOf(chart.pinnedKey) < 0) chart.pinnedKey = ""
            if (keys.indexOf(chart.hoverKey) < 0) chart.hoverKey = ""
            if (keys.length === 0) chart.playing = false
        }
    }

    // Playback: cursor moves along reference lap at real time (x speed), once per drawn frame (same clock as
    // other animations: no frame drawn without cursor move, no double step), view slides on when cursor nears its end
    FrameAnimation {
        running: chart.playing
        onTriggered: {
            chart.playTime += Math.min(frameTime, 0.1) * chart.playSpeed
            if (chart.playTime >= chart.playTo) {
                if (chart.hasRange && chart.playLoop) {  // passage A-B again
                    chart.playTime = chart.playFrom
                } else {
                    chart.playTime = chart.playTo
                    chart.playing = false
                }
            }
            var x = backend.xAtReferenceTime(chart.playTime)
            var span = chart.targetEnd - chart.targetStart
            var margin = chart.hasRange ? 0 : span * 0.1  // passage A-B kept in view as zoomed
            if (chart.zoomed && (x > chart.targetEnd - margin || x < chart.targetStart))
                chart.setView(x - span * 0.3, x + span * 0.7, true)
            chart.setCursor(x, "play")
        }
    }

    readonly property real tickStep: niceStep(viewRange[1] - viewRange[0], plotArea.width / (theme.em * 6))
    readonly property real firstTick: Math.ceil(viewRange[0] / tickStep) * tickStep

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
        var span = targetEnd - targetStart
        var shift = (event.modifiers & Qt.ShiftModifier) !== 0
        var control = (event.modifiers & Qt.ControlModifier) !== 0
        var alt = (event.modifiers & Qt.AltModifier) !== 0
        var direction = event.key === Qt.Key_Left ? -1 : 1
        if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) zoom(0.8, cursorX, true)
        else if (event.key === Qt.Key_Minus) zoom(1.25, cursorX, true)
        else if ((event.key === Qt.Key_Left || event.key === Qt.Key_Right) && alt) stepHistory(direction)
        else if ((event.key === Qt.Key_Left || event.key === Qt.Key_Right) && shift) {
            var move = direction * span * 0.2
            setView(targetStart + move, targetEnd + move, true)
        } else if ((event.key === Qt.Key_Left || event.key === Qt.Key_Right) && playing) {
            skipTime(direction * skipStep)
        } else if (event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
            var start = hasCursor ? cursorX : (targetStart + targetEnd) / 2
            var x = control ? start + span / Math.max(plotArea.width, 1) * 40 * direction  // far: 40 pixels
                            : backend.stepFrame(start, direction)  // one recorded frame of reference lap
            x = Math.max(0, Math.min(x, maxX))
            if (x < targetStart || x > targetEnd) setView(targetStart + x - start, targetEnd + x - start, false)
            setCursor(x, "key")
        }
        else if (event.key === Qt.Key_L) playLoop = !playLoop
        else if (event.key === Qt.Key_Comma) changeSpeed(-1)
        else if (event.key === Qt.Key_Period) changeSpeed(1)
        else if (event.key === Qt.Key_Home || digitOf(event) === 0) resetView(true)
        else if (event.key === Qt.Key_BracketRight) stepCorner(1)
        else if (event.key === Qt.Key_BracketLeft) stepCorner(-1)
        else if (event.key === Qt.Key_A) setMarker("A", cursorX)
        else if (event.key === Qt.Key_B) setMarker("B", cursorX)
        else if (event.key === Qt.Key_Escape) {
            if (!isNaN(markerA) || !isNaN(markerB)) clearMarkers()
            else backend.clearPinned()
        }
        else if (event.key === Qt.Key_Space) togglePlay()
        else if (event.key === Qt.Key_R && highlightKey !== "") backend.setReference(highlightKey)
        else if (event.key === Qt.Key_Question || event.key === Qt.Key_F1) helpRequested()
        else return
        event.accepted = true
    }

    // Legend: lap colors. Hover: highlight lap, click: keep highlighted, double-click: reference, x: hide lap
    Flow {
        id: legendRow
        anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: chart.labelWidth }
        spacing: theme.em * 0.35
        Repeater {
            model: backend.legendModel  // kept model: chips of laps still shown stay
            Rectangle {
                id: chip
                readonly property bool pinned: chart.pinnedKey === model.key
                height: theme.em * 1.8
                width: chipRow.implicitWidth + theme.em * 0.9
                radius: height / 2
                color: Qt.rgba(Qt.color(model.color).r, Qt.color(model.color).g, Qt.color(model.color).b,
                               pinned ? 0.3 : 0.14)
                border.width: model.reference || pinned ? 1.5 : 0
                border.color: model.color
                opacity: chart.highlightKey === "" || chart.highlightKey === model.key ? 1 : 0.55
                ToolTip.visible: chipArea.containsMouse
                ToolTip.text: model.full + (model.tip ? "\n" + model.tip : "")
                              + (model.excluded ? "\n" + model.excluded : "")
                              + "\n" + i18n.tr("Click: highlight · double-click: set as reference · right-click: menu")
                ToolTip.delay: 600
                MouseArea {
                    id: chipArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onEntered: chart.hoverKey = model.key
                    onExited: if (chart.hoverKey === model.key) chart.hoverKey = ""
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.RightButton) {
                            chipMenu.lapKey = model.key
                            chipMenu.reference = model.reference
                            chipMenu.popup(chip, mouse.x, mouse.y)
                        } else {
                            chart.pinnedKey = chip.pinned ? "" : model.key
                        }
                    }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.setReference(model.key) }
                }
                Row {
                    id: chipRow
                    anchors.centerIn: parent
                    spacing: theme.em * 0.4
                    Rectangle { width: theme.em * 0.55; height: width; radius: width / 2; color: model.color; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: model.label
                        color: model.excluded ? theme.dimText : theme.text
                        font.pointSize: theme.fontPoint * 0.9
                        font.italic: model.excluded !== ""
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        visible: model.reference
                        text: i18n.tr("REF")
                        color: model.color
                        font.pointSize: theme.fontPoint * 0.75
                        font.weight: Font.Bold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {  // shifted to align braking points
                        visible: model.offset !== "" && !backend.timeAxis
                        text: model.offset
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.75
                        font.features: { "tnum": 1 }
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        visible: !model.reference && (chipArea.containsMouse || closeArea.containsMouse)
                        text: "×"
                        color: closeArea.containsMouse ? theme.text : theme.dimText
                        font.weight: Font.Bold
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea {
                            id: closeArea
                            anchors.fill: parent
                            anchors.margins: -4
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.setLapChecked(model.key, false)
                        }
                    }
                }
            }
        }
    }
    // Delta measured against ideal lap: its time after lap chips
    Rectangle {
        parent: legendRow
        visible: backend.idealTime !== ""
        height: theme.em * 1.8
        width: idealText.implicitWidth + theme.em * 0.9
        radius: height / 2
        color: Qt.rgba(theme.purple.r, theme.purple.g, theme.purple.b, 0.16)
        border.width: 1.5
        border.color: theme.purple
        ToolTip.visible: idealArea.containsMouse
        ToolTip.text: i18n.tr("Delta & time gain/loss against ideal lap: fastest clean shown lap in each mini-sector")
        ToolTip.delay: 500
        Text {
            id: idealText
            anchors.centerIn: parent
            text: i18n.tr("Ideal") + " " + backend.idealTime
            color: theme.purple
            font.pointSize: theme.fontPoint * 0.9
            font.weight: Font.DemiBold
        }
        MouseArea { id: idealArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
    }
    // Laps aligned on braking point of a corner: corner, click to put laps back at their place
    Rectangle {
        parent: legendRow
        visible: backend.alignment.label !== undefined
        height: theme.em * 1.8
        width: alignText.implicitWidth + theme.em * 0.9
        radius: height / 2
        color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, alignArea.containsMouse ? 0.24 : 0.14)
        border.width: 1.5
        border.color: theme.accent
        ToolTip.visible: alignArea.containsMouse
        ToolTip.text: (backend.timeAxis ? i18n.tr("Laps are aligned on distance axis only") + "\n" : "")
                      + i18n.tr("Laps shifted along distance so their braking starts line up with reference lap") + "\n"
                      + i18n.tr("Click: laps back at their place")
        ToolTip.delay: 500
        Text {
            id: alignText
            anchors.centerIn: parent
            text: "↔ " + i18n.tr("Aligned on braking") + " " + (backend.alignment.label || "") + "  ×"
            color: theme.accent
            font.pointSize: theme.fontPoint * 0.9
            font.weight: Font.DemiBold
        }
        MouseArea {
            id: alignArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: backend.alignBraking(-1)
        }
    }
    TpMenu {
        id: chipMenu
        property string lapKey: ""
        property bool reference: false
        Action { text: i18n.tr("Set as Reference"); enabled: !chipMenu.reference; onTriggered: backend.setReference(chipMenu.lapKey) }
        Action {
            text: i18n.tr("Compare Corner by Corner")
            enabled: !chipMenu.reference
            onTriggered: backend.setCompareKey(chipMenu.lapKey)
        }
        Action {
            text: i18n.tr("Highlight")
            checkable: true
            checked: chart.pinnedKey === chipMenu.lapKey
            onTriggered: chart.pinnedKey = checked ? chipMenu.lapKey : ""
        }
        Action {
            text: i18n.tr("Open Replay Here")
            enabled: chart.hasCursor
            onTriggered: backend.openReplay(chart.cursorX, chipMenu.lapKey)
        }
        Action {
            text: i18n.tr("Setup Differences with Reference...")
            enabled: !chipMenu.reference
            onTriggered: chart.setupRequested(chipMenu.lapKey)
        }
        MenuSeparator {}
        Action { text: i18n.tr("Hide Lap"); enabled: !chipMenu.reference; onTriggered: backend.setLapChecked(chipMenu.lapKey, false) }
    }

    // Header: cursor position, playback, zoom
    Item {
        id: header
        anchors { left: parent.left; right: parent.right; top: legendRow.bottom; leftMargin: chart.labelWidth }
        anchors.topMargin: legendRow.height > 0 ? theme.em * 0.3 : 0
        height: theme.em * 2
        Row {
            id: playRow
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.2
            visible: backend.legend.length > 0
            // Back / forward in time, held: repeated (rewind / fast forward)
            TpButton {
                glyph: ""  // rewind
                flat: true
                implicitHeight: theme.em * 1.8
                enabled: backend.referenceLapTime > 0
                autoRepeat: true
                tip: i18n.tr("2 s back (hold: rewind)")
                onClicked: chart.skipTime(-chart.skipStep)
            }
            TpButton {
                glyph: chart.playing ? "" : ""  // pause, play
                flat: true
                implicitHeight: theme.em * 1.8
                tip: chart.hasRange ? i18n.tr("Play passage between markers A and B (Space)")
                                    : i18n.tr("Play lap: cursor follows reference lap at real speed (Space)")
                onClicked: chart.togglePlay()
            }
            TpButton {
                glyph: ""  // fast forward
                flat: true
                implicitHeight: theme.em * 1.8
                enabled: backend.referenceLapTime > 0
                autoRepeat: true
                tip: i18n.tr("2 s forward (hold: fast forward)")
                onClicked: chart.skipTime(chart.skipStep)
            }
            TpButton {
                visible: chart.hasRange
                glyph: "\uE8EE"  // repeat
                flat: true
                implicitHeight: theme.em * 1.8
                checked: chart.playLoop
                tip: i18n.tr("Play only passage between markers A and B, again and again") + " (L)"
                onClicked: chart.playLoop = !chart.playLoop
            }
            // Playback speed: slider on speed steps, value clicked: normal speed again
            Slider {
                id: speedSlider
                anchors.verticalCenter: parent.verticalCenter
                width: theme.em * 6.5
                height: theme.em * 1.8
                leftPadding: theme.em * 0.5
                rightPadding: theme.em * 0.5
                from: 0
                to: chart.playSpeeds.length - 1
                stepSize: 1
                snapMode: Slider.SnapAlways
                focusPolicy: Qt.NoFocus
                value: chart.playSpeeds.indexOf(chart.playSpeed)
                onMoved: chart.playSpeed = chart.playSpeeds[Math.round(value)]
                ToolTip.visible: hovered && !pressed
                ToolTip.text: i18n.tr("Playback speed") + " (, .)"
                ToolTip.delay: 600
                background: Item {
                    x: speedSlider.leftPadding
                    width: speedSlider.availableWidth
                    height: speedSlider.height
                    Rectangle {  // track, filled up to speed
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        height: 3
                        radius: 1.5
                        color: theme.border
                        Rectangle {
                            width: speedSlider.visualPosition * parent.width
                            height: parent.height
                            radius: parent.radius
                            color: theme.accent
                        }
                    }
                    Repeater {  // one notch per speed step, normal speed marked
                        model: chart.playSpeeds
                        Rectangle {
                            x: index / (chart.playSpeeds.length - 1) * parent.width - width / 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: modelData === 1 ? 2 : 1
                            height: modelData === 1 ? theme.em * 0.8 : theme.em * 0.45
                            color: index <= speedSlider.value ? theme.accent : theme.border
                        }
                    }
                }
                handle: Rectangle {
                    x: speedSlider.leftPadding + speedSlider.visualPosition * (speedSlider.availableWidth - width)
                    y: (speedSlider.height - height) / 2
                    width: theme.em * 0.95
                    height: width
                    radius: width / 2
                    color: speedSlider.pressed ? Qt.darker(theme.accent, 1.15) : theme.accent
                    border.width: 2
                    border.color: theme.base
                    scale: speedSlider.pressed || speedSlider.hovered ? 1.15 : 1
                    Behavior on scale { NumberAnimation { duration: 120 } }
                }
            }
            TpButton {
                text: chart.playSpeed + "×"
                flat: true
                implicitHeight: theme.em * 1.8
                implicitWidth: theme.em * 3.2
                checked: chart.playSpeed !== 1
                tip: i18n.tr("Back to normal speed")
                onClicked: chart.playSpeed = 1
            }
        }
        Text {
            anchors.left: playRow.right
            anchors.leftMargin: theme.em * 0.5
            anchors.right: zoomRow.left
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            text: chart.hasCursor ? chart.cursorTitle
                : panels.length ? i18n.tr("Wheel: zoom · drag: move · click: keep position · right-click: menu · [ ]: corners · A/B: markers")
                : ""
            color: chart.hasCursor ? theme.text : theme.dimText
            font.weight: chart.hasCursor ? Font.DemiBold : Font.Normal
            font.features: { "tnum": 1 }
        }
        Row {
            id: zoomRow
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.4
            opacity: chart.zoomed ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "×" + (chart.maxX / Math.max(chart.targetEnd - chart.targetStart, 1e-9)).toFixed(1).replace(".", theme.decimalPoint)
                color: theme.dimText
            }
            TpButton {
                glyph: ""  // zoom out
                text: i18n.tr("Reset")
                flat: true
                implicitHeight: theme.em * 1.8
                onClicked: chart.resetView(true)
            }
        }
    }

    Text {
        anchors.centerIn: scroller
        visible: panels.length === 0 || backend.legend.length === 0
        text: backend.loading ? "" : i18n.tr("Select recorded laps to compare.")
        color: theme.dimText
    }

    // Passage between markers A & B: time of each shown lap, gap to fastest
    Flow {
        id: passageRow
        anchors { left: parent.left; right: parent.right; top: header.bottom; leftMargin: chart.labelWidth }
        visible: chart.passage.length > 0
        height: visible ? implicitHeight : 0
        spacing: theme.em * 0.5
        Text {
            text: "A ↔ B"
            color: theme.accent
            font.pointSize: theme.fontPoint * 0.8
            font.weight: Font.Bold
            height: theme.em * 1.4
            verticalAlignment: Text.AlignVCenter
        }
        Repeater {
            model: chart.passage
            Row {
                spacing: theme.em * 0.25
                height: theme.em * 1.4
                Rectangle { width: theme.em * 0.5; height: width; radius: width / 2; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.label + " " + modelData.time + " s"
                    color: modelData.best ? theme.gold : theme.text
                    font.pointSize: theme.fontPoint * 0.8
                    font.weight: modelData.best ? Font.Bold : Font.Normal
                    font.features: { "tnum": 1 }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: modelData.gap !== ""
                    text: modelData.gap
                    color: theme.loss
                    font.pointSize: theme.fontPoint * 0.8
                    font.features: { "tnum": 1 }
                }
            }
        }
    }

    // Sector & corner names above panels (not over lines): click a sector to zoom on it, a corner to zoom on corner
    Item {
        id: marksStrip
        anchors { left: parent.left; right: parent.right; top: passageRow.bottom; leftMargin: chart.labelWidth }
        height: visible ? theme.em * 1.35 : 0
        visible: backend.legend.length > 0 && (chart.sectors.length > 0 || chart.marks.length > 0)
        clip: true
        Text {
            visible: chart.sectors.length > 0 && chart.xOf(0) >= -theme.em
            x: Math.round(chart.xOf(0)) + 2
            anchors.verticalCenter: parent.verticalCenter
            text: "S1"
            color: s1Area.containsMouse ? theme.accent : theme.text
            font.pointSize: theme.fontPoint * 0.8
            font.weight: Font.Bold
            MouseArea { id: s1Area; anchors.fill: parent; anchors.margins: -3; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chart.zoomSector(1) }
        }
        Repeater {
            model: chart.sectors
            Text {
                readonly property real px: chart.xOf(modelData.x)
                visible: px >= 0 && px <= marksStrip.width
                x: Math.round(px) + 2
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.label
                color: sectorArea.containsMouse ? theme.accent : theme.text
                font.pointSize: theme.fontPoint * 0.8
                font.weight: Font.Bold
                MouseArea {
                    id: sectorArea
                    anchors.fill: parent
                    anchors.margins: -3
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: chart.zoomSector(modelData.index + 1)
                }
            }
        }
        Repeater {
            model: chart.marks
            Text {
                readonly property real px: chart.xOf(modelData.x)
                visible: px >= 0 && px <= marksStrip.width && chart.cornerLabelShown[index] === true
                x: Math.round(px) + 2
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.label
                color: cornerArea.containsMouse ? theme.accent : theme.dimText
                font.pointSize: theme.fontPoint * 0.78
                MouseArea {
                    id: cornerArea
                    anchors.fill: parent
                    anchors.margins: -3
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: chart.zoomCornerAt(modelData.x)
                }
            }
        }
        // Kept position
        Text {
            readonly property real px: chart.xOf(chart.pinX)
            visible: chart.pinX >= 0 && px >= 0 && px <= marksStrip.width
            x: Math.round(px) - width / 2
            anchors.bottom: parent.bottom
            text: "\u25BC"
            color: theme.accent
            font.pointSize: theme.fontPoint * 0.7
        }
    }

    // Channel names & charts, scrolled when channels need more room than shown
    Flickable {
        id: scroller
        anchors { left: parent.left; right: parent.right; top: marksStrip.bottom; bottom: axis.top }
        contentWidth: width
        contentHeight: chart.contentHeight
        interactive: false
        clip: true
        visible: backend.legend.length > 0
        ScrollBar.vertical: ScrollBar { policy: scroller.contentHeight > scroller.height + 1 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }

        // Channel names: drag to reorder, lower edge: resize (double-click: reset heights)
        Item {
            id: labels
            width: chart.labelWidth
            height: chart.contentHeight

            Repeater {
                model: chart.panels.length  // count: same delegates kept when panels change
                Item {
                    id: labelItem
                    readonly property var info: chart.panelInfo(index)
                    y: chart.panelTop(index)
                    width: labels.width - theme.em * 0.6
                    height: chart.panelHeight(index)
                    opacity: index === chart.movingFrom ? 0.5 : 1
                    readonly property bool roomy: height > theme.em * 3.4 && info.available
                    readonly property var axis: chart.axisOf(info)  // fitted values, else whole range
                    readonly property bool valuesFitted: chart.yViews[info.column] !== undefined
                    readonly property real lowValue: axis.low
                    readonly property real highValue: axis.high
                    // Value range of panel, next to panel top & bottom edges (not over lines)
                    Text {
                        anchors { right: parent.right; top: parent.top }
                        visible: labelItem.roomy
                        text: labelItem.axis.highText
                        color: labelItem.valuesFitted ? theme.accent : theme.dimText
                        font.pointSize: theme.fontPoint * 0.72
                        font.features: { "tnum": 1 }
                    }
                    Text {
                        anchors { right: parent.right; bottom: parent.bottom }
                        visible: labelItem.roomy
                        text: labelItem.axis.lowText
                        color: labelItem.valuesFitted ? theme.accent : theme.dimText
                        font.pointSize: theme.fontPoint * 0.72
                        font.features: { "tnum": 1 }
                    }
                    // Values between range limits, next to their grid line (tall panels only)
                    Repeater {
                        model: labelItem.height > theme.em * 6 && labelItem.info.available ? labelItem.axis.ticks : []
                        Text {
                            readonly property real pad: Math.min(theme.em * 0.4, labelItem.height * 0.1)
                            readonly property real level: labelItem.height - pad - (modelData.value - labelItem.lowValue)
                                                          / Math.max(labelItem.highValue - labelItem.lowValue, 1e-9) * (labelItem.height - pad * 2)
                            anchors.right: parent.right
                            y: level - height / 2
                            // Not over range limits nor channel name
                            visible: y > theme.em * 1.1 && y + height < labelItem.height - theme.em * 1.1
                                     && (y + height < titleColumn.y - 2 || y > titleColumn.y + titleColumn.height + 2)
                            text: modelData.text
                            color: theme.dimText
                            opacity: 0.8
                            font.pointSize: theme.fontPoint * 0.68
                            font.features: { "tnum": 1 }
                        }
                    }
                    Column {
                        id: titleColumn
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        Text {
                            anchors.right: parent.right
                            text: labelItem.info.title
                            color: labelItem.info.available ? theme.text : theme.dimText
                            font.weight: Font.DemiBold
                            width: Math.min(implicitWidth, labels.width - theme.em)
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                        }
                        Text {
                            anchors.right: parent.right
                            visible: text !== "" && (chart.bubbleFits(index) || !chart.hasCursor)
                            text: labelItem.info.unit
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                        }
                        // Values fitted to visible part
                        Text {
                            anchors.right: parent.right
                            visible: labelItem.valuesFitted && labelItem.height > theme.em * 2.6
                            text: i18n.tr("fitted")
                            color: theme.accent
                            font.pointSize: theme.fontPoint * 0.7
                            font.weight: Font.DemiBold
                        }
                        // Sub-channels of combined panel
                        Flow {
                            anchors.right: parent.right
                            width: Math.min(parent.width, implicitWidth)
                            visible: labelItem.info.parts.length > 0
                            layoutDirection: Qt.RightToLeft
                            spacing: theme.em * 0.3
                            Repeater {
                                model: labelItem.info.parts
                                Text { text: modelData.label; color: modelData.color; font.pointSize: theme.fontPoint * 0.72; font.weight: Font.DemiBold }
                            }
                        }
                        // Cursor values when bubble does not fit in panel
                        Text {
                            anchors.right: parent.right
                            width: parent.width
                            horizontalAlignment: Text.AlignRight
                            visible: chart.cursorShown && !chart.bubbleFits(index) && chart.valueCount(index) > 0
                            text: visible ? chart.compactValues(index) : ""
                            textFormat: Text.StyledText
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            font.pointSize: theme.fontPoint * 0.75
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
            Rectangle {
                visible: chart.movingFrom >= 0 && chart.movingTo !== chart.movingFrom
                width: scroller.width
                height: 3
                radius: 1.5
                color: theme.accent
                y: chart.movingTo < 0 ? 0 : chart.movingTo < chart.movingFrom
                    ? chart.panelTop(chart.movingTo) - chart.gap / 2 - 1
                    : chart.panelTop(chart.movingTo) + chart.panelHeight(chart.movingTo) + chart.gap / 2 - 1
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: pressed ? Qt.SizeVerCursor : Qt.OpenHandCursor
                onPressed: function(mouse) { chart.movingFrom = chart.panelAt(mouse.y); chart.movingTo = chart.movingFrom }
                onPositionChanged: function(mouse) { if (pressed) chart.movingTo = chart.panelAt(mouse.y) }
                onReleased: {
                    var from = chart.movingFrom, to = chart.movingTo
                    chart.movingFrom = -1
                    chart.movingTo = -1
                    if (from >= 0 && to >= 0 && from !== to) backend.moveChannel(from, to)
                }
                onWheel: function(wheel) {
                    scroller.contentY = Math.max(0, Math.min(scroller.contentY - wheel.angleDelta.y / 120 * theme.em * 3,
                                                             scroller.contentHeight - scroller.height))
                }
            }
            // Panel lower edges: drag to resize
            Repeater {
                model: chart.panels.length
                MouseArea {
                    readonly property real edge: chart.panelTop(index) + chart.panelHeight(index)
                    x: theme.em * 0.4
                    width: scroller.width - x
                    y: edge - 2
                    height: chart.gap + 4
                    hoverEnabled: true
                    cursorShape: Qt.SizeVerCursor
                    property real startY: 0
                    property real startHeight: 0
                    onPressed: function(mouse) {
                        startY = mapToItem(labels, mouse.x, mouse.y).y
                        startHeight = chart.panelHeight(index) + chart.gap
                        chart.resizeWeight = chart.panelInfo(index).weight
                        chart.resizing = index
                    }
                    onPositionChanged: function(mouse) {
                        if (!pressed) return
                        var height = Math.max(startHeight + mapToItem(labels, mouse.x, mouse.y).y - startY, theme.em * 2)
                        var others = 0
                        for (var i = 0; i < chart.panels.length; i++) if (i !== index) others += chart.panels[i].weight
                        var total = chart.contentHeight
                        if (height < total - theme.em) chart.resizeWeight = Math.max(0.2, Math.min(6, height * others / (total - height)))
                    }
                    onReleased: {
                        var weight = chart.resizeWeight
                        chart.resizing = -1
                        backend.setPanelWeight(chart.panelInfo(index).column, weight)
                    }
                    onDoubleClicked: backend.resetPanelWeights()
                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.width
                        height: 2
                        color: theme.accent
                        visible: parent.containsMouse || parent.pressed
                        opacity: 0.6
                    }
                }
            }
        }

        // Charts area
        Item {
            id: plotArea
            x: chart.labelWidth
            width: scroller.width - chart.labelWidth - (scroller.ScrollBar.vertical.visible ? scroller.ScrollBar.vertical.width : 0)
            height: chart.contentHeight

            // Panel backgrounds
            Repeater {
                model: chart.panels.length
                Rectangle {
                    y: chart.panelTop(index)
                    width: plotArea.width
                    height: chart.panelHeight(index)
                    radius: theme.em * 0.35
                    color: theme.dark ? Qt.darker(theme.base, 1.18) : Qt.darker(theme.base, 1.015)
                    border.width: 1
                    border.color: index === chart.movingFrom ? theme.accent : (theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border)
                }
            }

            // Range between markers A & B
            Rectangle {
                visible: chart.hasRange
                x: chart.xOf(Math.min(chart.markerA, chart.markerB))
                width: Math.abs(chart.xOf(chart.markerB) - chart.xOf(chart.markerA))
                height: plotArea.height
                color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.08)
            }

            // Distance grid
            Repeater {
                model: 40
                Rectangle {
                    readonly property real value: chart.firstTick + index * chart.tickStep
                    visible: value <= chart.viewRange[1]
                    x: visible ? Math.round(chart.xOf(value)) : 0
                    width: 1
                    height: plotArea.height
                    color: theme.text
                    opacity: 0.06
                }
            }

            // Sector lines & corner apexes of reference lap (their names in strip above panels)
            Repeater {
                model: chart.sectors
                Rectangle {
                    readonly property real px: chart.xOf(modelData.x)
                    visible: px >= 0 && px <= plotArea.width
                    x: Math.round(px)
                    width: 1
                    height: plotArea.height
                    color: theme.text
                    opacity: 0.22
                }
            }
            Repeater {
                model: chart.marks
                Rectangle {
                    readonly property real px: chart.xOf(modelData.x)
                    visible: px >= 0 && px <= plotArea.width
                    x: Math.round(px)
                    width: 1
                    height: plotArea.height
                    color: theme.text
                    opacity: 0.09
                }
            }

            // Channel lines (kept model: showing one more lap only adds its lines)
            Repeater {
                model: backend.panelModel
                Item {
                    id: panel
                    readonly property var info: model
                    readonly property var axis: chart.axisOf(info)  // fitted values, else whole range
                    readonly property var range: [axis.low, axis.high]
                    readonly property real pad: Math.min(theme.em * 0.4, height * 0.1)  // lines at range limits stay visible
                    readonly property real sy: (height - pad * 2) / Math.max(range[1] - range[0], 1e-9)
                    readonly property real ty: height - pad + range[0] * sy
                    // Data to panel pixels, horizontal scale from shown range read once (one update per frame)
                    function lineMatrix(dx, dy) {
                        var shown = chart.viewRange
                        var sx = width / Math.max(shown[1] - shown[0], 1e-9)
                        return Qt.matrix4x4(sx, 0, 0, -shown[0] * sx + dx, 0, -sy, 0, ty + dy, 0, 0, 1, 0, 0, 0, 0, 1)
                    }
                    y: chart.panelTop(index)
                    width: plotArea.width
                    height: chart.panelHeight(index)
                    clip: true

                    Rectangle {
                        visible: panel.range[0] < 0 && panel.range[1] > 0
                        y: Math.round(panel.ty)
                        width: parent.width
                        height: 1
                        color: theme.text
                        opacity: 0.18
                    }
                    // Value grid (same values as labels beside panel)
                    Repeater {
                        model: panel.height > theme.em * 6 && panel.info.available ? panel.axis.ticks : []
                        Rectangle {
                            y: Math.round(panel.ty - modelData.value * panel.sy)
                            width: panel.width
                            height: 1
                            color: theme.text
                            opacity: 0.07
                        }
                    }
                    // Lowest & highest value of laps (consistency band)
                    GpuShape {
                        visible: panel.info.envelope !== ""
                        key: panel.info.envelope
                        color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.12 : 0.1)
                        revision: backend.revision
                        transform: Matrix4x4 {
                            matrix: panel.lineMatrix(0, 0)
                        }
                    }
                    // Lines drawn twice, half a pixel apart: about 1.5 px wide (scene graph lines are 1 px).
                    // One transform per copy for every series of panel (not one per line: zoom frames stay cheap)
                    Repeater {
                        model: chart.lineOffsets
                        Item {
                            id: lineCopy
                            readonly property var offset: modelData
                            transform: Matrix4x4 {
                                matrix: panel.lineMatrix(lineCopy.offset[0], lineCopy.offset[1])
                            }
                            Repeater {
                                model: panel.info.seriesModel
                                GpuShape {
                                    // Min / max reduced copy when its buckets are at most a pixel wide (same peaks, far fewer vertices)
                                    key: chart.seriesKey(model)
                                    color: model.color
                                    opacity: chart.lapOpacity(model.lap)
                                    Behavior on opacity { NumberAnimation { duration: 150 } }
                                }
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: panel.info.note !== ""
                        text: panel.info.note
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.85
                    }
                }
            }

            // Markers A & B
            Repeater {
                model: [["A", chart.markerA], ["B", chart.markerB]]
                Item {
                    readonly property real px: chart.xOf(modelData[1])
                    visible: !isNaN(modelData[1]) && px >= 0 && px <= plotArea.width
                    x: Math.round(px)
                    height: plotArea.height
                    Rectangle { width: 1.5; height: parent.height; color: theme.accent; opacity: 0.8 }
                    Rectangle {
                        x: -width / 2
                        width: markerText.implicitWidth + theme.em * 0.5
                        height: markerText.implicitHeight + 2
                        radius: height / 2
                        color: theme.accent
                        Text { id: markerText; anchors.centerIn: parent; text: modelData[0]; color: "white"; font.weight: Font.Bold; font.pointSize: theme.fontPoint * 0.75 }
                    }
                }
            }

            // Kept position (click on charts or map)
            Rectangle {
                readonly property real px: chart.xOf(chart.pinX)
                visible: chart.pinX >= 0 && px >= 0 && px <= plotArea.width
                x: Math.round(px)
                width: 1.5
                height: plotArea.height
                color: theme.accent
                opacity: 0.7
            }

            // Cursor line & values
            Rectangle {
                visible: chart.cursorShown
                x: Math.round(chart.xOf(chart.cursorX))
                width: 1
                height: plotArea.height
                color: theme.text
                opacity: 0.55
            }
            Repeater {
                model: chart.panels.length
                Rectangle {
                    id: bubble
                    readonly property int panelIndex: index
                    readonly property var info: chart.panelInfo(index)
                    readonly property real px: chart.xOf(chart.cursorX)
                    visible: chart.cursorShown && chart.valueCount(index) > 0 && chart.bubbleFits(index)
                    x: px + 8 + width <= plotArea.width ? px + 8 : px - 8 - width
                    y: chart.panelTop(index) + 3
                    width: valueColumn.width + theme.em * 0.6
                    height: valueColumn.height + theme.em * 0.25
                    radius: theme.em * 0.3
                    color: Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.88)
                    border.width: 1
                    border.color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.12)
                    // Rows placed by bindings, not Column / Row: positioners lay out after values change, while
                    // frame is drawn, which asks for a second frame each cursor move (playback stutters)
                    Item {
                        id: valueColumn
                        anchors.centerIn: parent
                        readonly property real rowHeight: valueMetrics.height
                        width: {
                            var widest = 0
                            for (var i = 0; i < valueRows.count; i++) {
                                var row = valueRows.itemAt(i)
                                if (row && row.visible) widest = Math.max(widest, row.width)
                            }
                            return widest
                        }
                        height: chart.valueCount(bubble.panelIndex) * rowHeight
                        FontMetrics { id: valueMetrics; font.pointSize: theme.fontPoint * 0.85; font.weight: Font.DemiBold }
                        // One item per drawn series (kept while cursor moves), empty ones hidden
                        Repeater {
                            id: valueRows
                            model: bubble.info.series.length
                            Item {
                                readonly property var entry: chart.cursorEntry(bubble.panelIndex, index)
                                visible: entry !== null && entry.text !== ""
                                y: chart.valueRow(bubble.panelIndex, index) * valueColumn.rowHeight
                                width: valueText.implicitWidth + (diffText.text !== "" ? diffText.x - valueText.implicitWidth + diffText.implicitWidth : 0)
                                height: valueColumn.rowHeight
                                opacity: bubble.info.series[index] ? chart.lapOpacity(bubble.info.series[index].lap) : 1
                                Text {
                                    id: valueText
                                    text: parent.entry ? parent.entry.text : ""
                                    color: parent.entry ? parent.entry.color : theme.text
                                    font.pointSize: theme.fontPoint * 0.85
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                                Text {
                                    id: diffText
                                    x: valueText.implicitWidth + theme.em * 0.4
                                    visible: text !== ""
                                    text: parent.entry ? parent.entry.diff : ""
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.75
                                    font.features: { "tnum": 1 }
                                    anchors.baseline: valueText.baseline
                                }
                            }
                        }
                    }
                }
            }

            MouseArea {
                id: plotMouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                property real pressX: 0
                property real pressStart: 0
                property real pressEnd: 0
                property bool moved: false  // dragged: view moved, else click keeps position
                cursorShape: pressed && moved ? Qt.ClosedHandCursor : Qt.CrossCursor

                onPressed: function(mouse) {
                    chart.forceActiveFocus()
                    if (mouse.button === Qt.RightButton) {
                        chart.setCursor(chart.valueOf(mouse.x))
                        chartMenu.panelIndex = chart.panelAt(mouse.y)
                        chartMenu.popup(plotMouse, mouse.x, mouse.y)
                        return
                    }
                    pressX = mouse.x
                    pressStart = chart.targetStart
                    pressEnd = chart.targetEnd
                    moved = false
                }
                onPositionChanged: function(mouse) {
                    if (pressed && (pressedButtons & Qt.LeftButton)) {
                        if (Math.abs(mouse.x - pressX) > 4) moved = true
                        if (moved) {
                            var shift = (pressX - mouse.x) / Math.max(width, 1) * (pressEnd - pressStart)
                            chart.setView(pressStart + shift, pressEnd + shift, false)
                        }
                    }
                    if (!chart.playing) chart.setCursor(chart.valueOf(mouse.x))
                }
                onReleased: function(mouse) {
                    if (mouse.button === Qt.LeftButton && !moved) backend.setPinned(chart.valueOf(mouse.x))  // click: kept
                    moved = false
                }
                onExited: if (!pressed && !chart.playing && !chartMenu.visible) chart.restoreCursor()
                onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) chart.resetView(true) }
                onWheel: function(wheel) {
                    if (Math.abs(wheel.angleDelta.x) > Math.abs(wheel.angleDelta.y)) {  // touchpad sideways: move
                        var span = chart.targetEnd - chart.targetStart
                        var move = -wheel.angleDelta.x / 120 * span * 0.1
                        chart.setView(chart.targetStart + move, chart.targetEnd + move, false)
                        return
                    }
                    // Zoom follows wheel amount (touchpads & high resolution wheels), eased every frame
                    chart.zoom(Math.pow(1.0015, -wheel.angleDelta.y), chart.valueOf(wheel.x), true)
                }
            }
        }
    }

    TpMenu {
        id: chartMenu
        property int panelIndex: -1
        onClosed: if (!plotMouse.containsMouse && !chart.playing) chart.restoreCursor()
        Action { text: i18n.tr("Keep Position Here"); enabled: chart.hasCursor; onTriggered: backend.setPinned(chart.cursorX) }
        Action { text: i18n.tr("Remove Kept Position"); enabled: backend.pinnedX >= 0; onTriggered: backend.clearPinned() }
        MenuSeparator {}
        Action { text: i18n.tr("Set Marker A Here"); onTriggered: chart.setMarker("A", chart.cursorX) }
        Action { text: i18n.tr("Set Marker B Here"); onTriggered: chart.setMarker("B", chart.cursorX) }
        Action { text: i18n.tr("Clear Markers"); enabled: !isNaN(chart.markerA) || !isNaN(chart.markerB); onTriggered: chart.clearMarkers() }
        MenuSeparator {}
        Action {
            text: i18n.tr("Zoom to Sector")
            enabled: chart.sectors.length > 0 && chart.hasCursor
            onTriggered: chart.zoomSector(chart.sectorAt(chart.cursorX))
        }
        Action {
            text: i18n.tr("Zoom Between Markers")
            enabled: chart.hasRange
            onTriggered: chart.zoomRange([Math.min(chart.markerA, chart.markerB), Math.max(chart.markerA, chart.markerB)], 0.03)
        }
        Action { text: i18n.tr("Previous Zoom") + "  (Alt+←)"; enabled: chart.historyIndex > 0; onTriggered: chart.stepHistory(-1) }
        Action { text: i18n.tr("Next Zoom") + "  (Alt+→)"; enabled: chart.historyIndex < chart.viewHistory.length - 1; onTriggered: chart.stepHistory(1) }
        Action { text: i18n.tr("Reset Channel Heights"); onTriggered: backend.resetPanelWeights() }
        Action { text: i18n.tr("Sync zoom with map"); checkable: true; checked: backend.mapFollow; onTriggered: backend.setMapFollow(checked) }
        MenuSeparator {}
        // Values of panel right-clicked
        Action {
            text: i18n.tr("Fit Values to Visible Part")
            checkable: true
            enabled: chart.panels[chartMenu.panelIndex] !== undefined
            checked: chart.panels[chartMenu.panelIndex] !== undefined && chart.panels[chartMenu.panelIndex].autoscale === true
            onTriggered: chart.setAutoscale(chartMenu.panelIndex, checked)
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("Align Laps on Braking Point Here")
            enabled: chart.hasCursor && backend.cornerRanges.length > 0 && backend.legend.length > 1 && !backend.timeAxis
            onTriggered: backend.alignBrakingAt(chart.cursorX)
        }
        Action { text: i18n.tr("Stop Aligning Laps"); enabled: backend.alignment.label !== undefined; onTriggered: backend.alignBraking(-1) }
        MenuSeparator {}
        Action { text: i18n.tr("Copy Values"); enabled: chart.hasCursor; onTriggered: backend.copyValues(chart.cursorX) }
        Action { text: i18n.tr("Copy Picture"); onTriggered: chart.pictureRequested(true) }
        Action { text: i18n.tr("Open Replay Here"); enabled: chart.hasCursor; onTriggered: backend.openReplay(chart.cursorX, chart.highlightKey) }
    }

    // Distance / time axis
    Item {
        id: axis
        anchors { left: parent.left; right: parent.right; bottom: overview.top; leftMargin: chart.labelWidth }
        height: theme.em * 1.6
        visible: scroller.visible
        clip: true
        Repeater {
            model: 40
            Text {
                readonly property real value: chart.firstTick + index * chart.tickStep
                visible: value <= chart.viewRange[1]
                x: visible ? Math.max(0, Math.min(chart.xOf(value) - width / 2, axis.width - width)) : 0
                y: theme.em * 0.2
                text: visible ? chart.axisText(value) : ""
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                font.features: { "tnum": 1 }
            }
        }
    }

    // Whole lap navigator: zoomed part as a window, drag or click to move it
    Item {
        id: overview
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: chart.labelWidth }
        height: visible ? theme.em * 2.6 : 0
        visible: scroller.visible && backend.overview.key !== undefined

        Rectangle {
            anchors.fill: parent
            radius: theme.em * 0.35
            color: theme.dark ? Qt.darker(theme.base, 1.18) : Qt.darker(theme.base, 1.015)
            border.width: 1
            border.color: theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border
        }
        Item {
            id: overviewPlot
            readonly property real sx: width / chart.maxX
            readonly property real sy: height / Math.max((backend.overview.high || 1) - (backend.overview.low || 0), 1e-9)
            anchors.fill: parent
            anchors.margins: 3
            clip: true
            GpuShape {
                key: backend.overview.key || ""
                color: theme.dimText
                revision: backend.revision
                transform: Matrix4x4 {
                    matrix: Qt.matrix4x4(overviewPlot.sx, 0, 0, 0,
                                         0, -overviewPlot.sy, 0, overviewPlot.height + (backend.overview.low || 0) * overviewPlot.sy,
                                         0, 0, 1, 0, 0, 0, 0, 1)
                }
            }
        }
        Rectangle {
            visible: chart.hasRange
            x: Math.min(chart.markerA, chart.markerB) / chart.maxX * overview.width
            width: Math.abs(chart.markerB - chart.markerA) / chart.maxX * overview.width
            height: overview.height
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.12)
        }
        Rectangle {
            id: window
            x: chart.viewRange[0] / chart.maxX * overview.width
            width: Math.max((chart.viewRange[1] - chart.viewRange[0]) / chart.maxX * overview.width, 4)
            height: overview.height
            radius: theme.em * 0.35
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, chart.zoomed ? 0.16 : 0.0)
            border.width: chart.zoomed ? 1.5 : 0
            border.color: theme.accent
            Behavior on color { ColorAnimation { duration: 200 } }
        }
        Rectangle {
            visible: chart.hasCursor
            x: chart.cursorX / chart.maxX * overview.width
            width: 1
            height: overview.height
            color: theme.text
            opacity: 0.5
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            function moveTo(px, animated) {
                var span = chart.targetEnd - chart.targetStart
                var center = px / overview.width * chart.maxX
                chart.setView(center - span / 2, center + span / 2, animated)
            }
            onPressed: function(mouse) { moveTo(mouse.x, true) }
            onPositionChanged: function(mouse) { if (pressed) moveTo(mouse.x, false) }
        }
    }
}
