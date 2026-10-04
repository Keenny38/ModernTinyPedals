import QtQuick
import QtQuick.Controls.Basic
import TinyPedal

// Stacked channel charts along lap distance (or lap time), lines drawn by GPU
// Wheel: zoom, Ctrl+wheel: zoom channel values, drag: move, Shift+drag: zoom to area, double-click: reset,
// drag a channel name: reorder, drag a channel lower edge: resize, right-click: menu.
// Keyboard: +/- zoom, left/right move cursor (Shift: move view), Home or 0 reset, [ ] previous / next corner,
// A / B markers, Esc clear markers, R reference = highlighted lap, Space play.
FocusScope {
    id: chart

    readonly property real maxX: Math.max(backend.maxX, 1)
    property real targetStart: 0
    property real targetEnd: maxX
    property real viewStart: targetStart
    property real viewEnd: targetEnd
    property bool animate: false
    property real cursorX: NaN
    property string cursorSource: "mouse"  // what moved cursor: mouse, key, play, map (map follows play & key)
    readonly property bool hasCursor: !isNaN(cursorX)
    readonly property bool cursorShown: hasCursor && cursorX >= viewStart && cursorX <= viewEnd
    property string cursorTitle: ""
    property var cursorValues: []
    property var cursorMap: []  // map position of each lap at cursor (TrackMap)
    property var cursorG: []  // G circle position of each lap at cursor (GCircle)
    readonly property bool zoomed: targetEnd - targetStart < maxX - 1
    readonly property real labelWidth: theme.em * 7
    readonly property real gap: theme.em * 0.35
    property var panels: backend.panels
    property int movingFrom: -1
    property int movingTo: -1
    property var lineOffsets: [[0, 0], [0.5, 0.5]]
    property int resizing: -1  // panel whose height is dragged
    property real resizeWeight: 0
    property var yRanges: ({})  // channel value range zoomed with Ctrl+wheel, by column
    property string hoverKey: ""  // lap highlighted while hovering its legend chip
    property string pinnedKey: ""  // lap highlighted by clicking its legend chip
    readonly property string highlightKey: hoverKey || pinnedKey
    property real markerA: NaN
    property real markerB: NaN
    readonly property bool hasRange: !isNaN(markerA) && !isNaN(markerB) && markerA !== markerB
    property bool playing: false
    property real playSpeed: 1
    property real playTime: 0
    property double playClock: 0
    readonly property real minPanelHeight: theme.em * 3.2
    readonly property real totalWeight: {
        var sum = 0
        for (var i = 0; i < panels.length; i++) sum += panelWeight(i)
        return sum || 1
    }
    readonly property real contentHeight: Math.max(scroller.height, totalWeight * minPanelHeight)
    // Corner numbers shown on charts: a label too close to previous shown one is hidden
    readonly property var cornerLabelShown: {
        var marks = backend.cornerMarks
        var shown = []
        var last = -1e9
        for (var i = 0; i < marks.length; i++) {
            var px = xOf(marks[i].x)
            shown.push(px - last >= marks[i].label.length * theme.em * 0.55 + theme.em * 0.4)
            if (shown[i]) last = px
        }
        return shown
    }

    signal pictureRequested(bool copy)
    signal rangeSet()

    Behavior on viewStart { enabled: chart.animate; NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
    Behavior on viewEnd { enabled: chart.animate; NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }

    function setView(start, end, animated) {
        var span = end - start
        if (span >= maxX) { start = 0; end = maxX }
        else if (start < 0) { end -= start; start = 0 }
        else if (end > maxX) { start -= end - maxX; end = maxX }
        animate = animated
        targetStart = Math.max(start, 0)
        targetEnd = Math.min(end, maxX)
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
        var lines = backend.sectorLines
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
    function setCursor(x, source) {
        cursorSource = source || "mouse"
        cursorX = x
        if (isNaN(x)) {
            cursorTitle = ""
            cursorValues = []
            cursorMap = []
            cursorG = []
            return
        }
        var state = backend.cursorState(x)
        cursorTitle = state.title
        cursorValues = state.values
        cursorMap = state.map
        cursorG = state.g
    }
    function setMarker(which, x) {
        if (isNaN(x)) return
        if (which === "A") markerA = x
        else markerB = x
        if (hasRange) rangeSet()
    }
    function clearMarkers() { markerA = NaN; markerB = NaN }
    function togglePlay() {
        if (playing) { playing = false; return }
        if (backend.referenceLapTime <= 0) return
        var start = hasCursor ? cursorX : targetStart
        playTime = backend.referenceTimeAt(start)
        if (playTime >= backend.referenceLapTime - 0.05) playTime = 0
        playClock = Date.now()
        playing = true
    }
    function xOf(value) { return (value - viewStart) / Math.max(viewEnd - viewStart, 1e-9) * plotArea.width }
    function valueOf(px) { return viewStart + px / Math.max(plotArea.width, 1) * (viewEnd - viewStart) }
    function panelWeight(index) {
        if (index === resizing) return resizeWeight
        return panels[index] ? panels[index].weight : 1
    }
    function panelTop(index) {
        var weight = 0
        for (var i = 0; i < index; i++) weight += panelWeight(i)
        return weight / totalWeight * plotArea.height
    }
    function panelHeight(index) { return panelWeight(index) / totalWeight * plotArea.height - gap }
    function panelAt(y) {
        for (var i = 0; i < panels.length; i++)
            if (y < panelTop(i) + panelHeight(i) + gap / 2) return i
        return panels.length - 1
    }
    function rangeOf(index) {
        var info = panels[index]
        if (!info) return [0, 1]
        var zoomedRange = yRanges[info.column]
        return zoomedRange ? zoomedRange : [info.low, info.high]
    }
    function zoomValues(index, factor, py) {
        var info = panels[index]
        var range = rangeOf(index)
        var height = Math.max(panelHeight(index), 1)
        var center = range[1] - (py - panelTop(index)) / height * (range[1] - range[0])
        var low = center - (center - range[0]) * factor
        var high = center + (range[1] - center) * factor
        var full = info.high - info.low
        var ranges = Object.assign({}, yRanges)
        if (high - low >= full) delete ranges[info.column]
        else if (high - low > full * 0.01) ranges[info.column] = [low, high]
        yRanges = ranges
    }
    function resetValues(index) {
        var ranges = Object.assign({}, yRanges)
        if (index < 0) ranges = {}
        else if (panels[index]) delete ranges[panels[index].column]
        yRanges = ranges
    }
    function cursorEntry(panelIndex, seriesIndex) {
        var values = cursorValues[panelIndex]
        return values && values[seriesIndex] ? values[seriesIndex] : null
    }
    function valueCount(panelIndex) {
        var values = cursorValues[panelIndex] || []
        var count = 0
        for (var i = 0; i < values.length; i++) if (values[i].text !== "") count++
        return count
    }
    // Cursor values bubble fits in panel, else values shown under channel name
    function bubbleFits(panelIndex) {
        return panelHeight(panelIndex) > valueCount(panelIndex) * theme.em * 1.3 + theme.em * 0.4
    }
    function compactValues(panelIndex) {
        var values = cursorValues[panelIndex] || []
        var texts = []
        for (var i = 0; i < values.length && texts.length < 4; i++)
            if (values[i].text !== "") texts.push("<font color='" + values[i].color + "'>" + values[i].text + "</font>")
        return texts.join(" ")
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
    function axisText(value) {
        if (!backend.timeAxis) return value.toFixed(0) + " m"
        if (value < 60) return value.toFixed(0) + "s"
        var minutes = Math.floor(value / 60)
        var seconds = Math.round(value - minutes * 60)
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    // Laps added or removed: same zoom kept if still inside lap, whole lap otherwise
    onMaxXChanged: {
        if (zoomed && targetStart < maxX) setView(targetStart, Math.min(targetEnd, maxX), false)
        else resetView(false)
    }
    onTargetStartChanged: backend.setChartView(targetStart, targetEnd)
    onTargetEndChanged: backend.setChartView(targetStart, targetEnd)
    onPanelsChanged: if (hasCursor) setCursor(cursorX, cursorSource)

    Connections {
        target: backend
        function onViewRestored(start, end) { chart.setView(start, end, false) }
        function onChartChanged() {
            var keys = backend.legend.map(function(item) { return item.key })
            if (keys.indexOf(chart.pinnedKey) < 0) chart.pinnedKey = ""
            if (keys.indexOf(chart.hoverKey) < 0) chart.hoverKey = ""
            if (keys.length === 0) chart.playing = false
        }
    }

    // Playback: cursor moves along reference lap at real time (x speed)
    Timer {
        interval: 16
        repeat: true
        running: chart.playing
        onTriggered: {
            var now = Date.now()
            chart.playTime += (now - chart.playClock) / 1000 * chart.playSpeed
            chart.playClock = now
            if (chart.playTime >= backend.referenceLapTime) {
                chart.playTime = backend.referenceLapTime
                chart.playing = false
            }
            var x = backend.xAtReferenceTime(chart.playTime)
            var span = chart.targetEnd - chart.targetStart
            if (chart.zoomed && (x > chart.targetEnd - span * 0.1 || x < chart.targetStart))
                chart.setView(x - span * 0.3, x + span * 0.7, false)
            chart.setCursor(x, "play")
        }
    }

    readonly property real tickStep: niceStep(viewEnd - viewStart, plotArea.width / (theme.em * 6))
    readonly property real firstTick: Math.ceil(viewStart / tickStep) * tickStep

    Keys.onPressed: function(event) {
        var span = targetEnd - targetStart
        var shift = (event.modifiers & Qt.ShiftModifier) !== 0
        var control = (event.modifiers & Qt.ControlModifier) !== 0
        if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) zoom(0.8, cursorX, true)
        else if (event.key === Qt.Key_Minus) zoom(1.25, cursorX, true)
        else if ((event.key === Qt.Key_Left || event.key === Qt.Key_Right) && shift) {
            var move = (event.key === Qt.Key_Left ? -1 : 1) * span * 0.2
            setView(targetStart + move, targetEnd + move, true)
        } else if (event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
            var step = span / Math.max(plotArea.width, 1) * (control ? 40 : 4) * (event.key === Qt.Key_Left ? -1 : 1)
            var x = Math.max(0, Math.min((hasCursor ? cursorX : (targetStart + targetEnd) / 2) + step, maxX))
            if (x < targetStart || x > targetEnd) setView(targetStart + step, targetEnd + step, false)
            setCursor(x, "key")
        }
        else if (event.key === Qt.Key_Home || event.key === Qt.Key_0) resetView(true)
        else if (event.key === Qt.Key_BracketRight) stepCorner(1)
        else if (event.key === Qt.Key_BracketLeft) stepCorner(-1)
        else if (event.key === Qt.Key_A) setMarker("A", cursorX)
        else if (event.key === Qt.Key_B) setMarker("B", cursorX)
        else if (event.key === Qt.Key_Escape) clearMarkers()
        else if (event.key === Qt.Key_Space) togglePlay()
        else if (event.key === Qt.Key_R && highlightKey !== "") backend.setReference(highlightKey)
        else return
        event.accepted = true
    }

    // Legend: lap colors. Hover: highlight lap, click: keep highlighted, double-click: reference, x: hide lap
    Flow {
        id: legendRow
        anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: chart.labelWidth }
        spacing: theme.em * 0.35
        Repeater {
            model: backend.legend
            Rectangle {
                id: chip
                readonly property bool pinned: chart.pinnedKey === modelData.key
                height: theme.em * 1.8
                width: chipRow.implicitWidth + theme.em * 0.9
                radius: height / 2
                color: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b,
                               pinned ? 0.3 : 0.14)
                border.width: modelData.reference || pinned ? 1.5 : 0
                border.color: modelData.color
                opacity: chart.highlightKey === "" || chart.highlightKey === modelData.key ? 1 : 0.55
                ToolTip.visible: chipArea.containsMouse
                ToolTip.text: modelData.full + "\n" + i18n.tr("Click: highlight · double-click: set as reference · right-click: menu")
                ToolTip.delay: 600
                MouseArea {
                    id: chipArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onEntered: chart.hoverKey = modelData.key
                    onExited: if (chart.hoverKey === modelData.key) chart.hoverKey = ""
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.RightButton) {
                            chipMenu.lapKey = modelData.key
                            chipMenu.reference = modelData.reference
                            chipMenu.popup(chip, mouse.x, mouse.y)
                        } else {
                            chart.pinnedKey = chip.pinned ? "" : modelData.key
                        }
                    }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.setReference(modelData.key) }
                }
                Row {
                    id: chipRow
                    anchors.centerIn: parent
                    spacing: theme.em * 0.4
                    Rectangle { width: theme.em * 0.55; height: width; radius: width / 2; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: modelData.label
                        color: theme.text
                        font.pointSize: theme.fontPoint * 0.9
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        visible: modelData.reference
                        text: i18n.tr("REF")
                        color: modelData.color
                        font.pointSize: theme.fontPoint * 0.75
                        font.weight: Font.Bold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        visible: !modelData.reference && (chipArea.containsMouse || closeArea.containsMouse)
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
                            onClicked: backend.setLapChecked(modelData.key, false)
                        }
                    }
                }
            }
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
            TpButton {
                glyph: chart.playing ? "" : ""  // pause, play
                flat: true
                implicitHeight: theme.em * 1.8
                tip: i18n.tr("Play lap: cursor follows reference lap at real speed (Space)")
                onClicked: chart.togglePlay()
            }
            TpButton {
                text: chart.playSpeed + "×"
                flat: true
                implicitHeight: theme.em * 1.8
                tip: i18n.tr("Playback speed")
                onClicked: {
                    var speeds = [0.25, 0.5, 1, 2, 4]
                    chart.playSpeed = speeds[(speeds.indexOf(chart.playSpeed) + 1) % speeds.length]
                }
            }
        }
        Text {
            anchors.left: playRow.right
            anchors.leftMargin: theme.em * 0.5
            anchors.right: zoomRow.left
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            text: chart.hasCursor ? chart.cursorTitle
                : panels.length ? i18n.tr("Wheel: zoom · drag: move · Shift+drag: zoom area · right-click: menu · [ ]: corners · A/B: markers")
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
                text: "×" + (chart.maxX / Math.max(chart.targetEnd - chart.targetStart, 1e-9)).toFixed(1)
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

    // Channel names & charts, scrolled when channels need more room than shown
    Flickable {
        id: scroller
        anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: axis.top }
        contentWidth: width
        contentHeight: chart.contentHeight
        interactive: false
        clip: true
        visible: backend.legend.length > 0
        ScrollBar.vertical: ScrollBar { policy: scroller.contentHeight > scroller.height + 1 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }

        // Channel names: drag to reorder, lower edge: resize, double-click: reset value zoom
        Item {
            id: labels
            width: chart.labelWidth
            height: chart.contentHeight

            Repeater {
                model: chart.panels
                Item {
                    y: chart.panelTop(index)
                    width: labels.width - theme.em * 0.6
                    height: chart.panelHeight(index)
                    opacity: index === chart.movingFrom ? 0.5 : 1
                    Column {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        Text {
                            anchors.right: parent.right
                            text: modelData.title
                            color: modelData.available ? theme.text : theme.dimText
                            font.weight: Font.DemiBold
                            width: Math.min(implicitWidth, labels.width - theme.em)
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                        }
                        Text {
                            anchors.right: parent.right
                            visible: text !== "" && (chart.bubbleFits(index) || !chart.hasCursor)
                            text: modelData.unit + (chart.yRanges[modelData.column] ? " ↕" : "")
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                        }
                        // Sub-channels of combined panel
                        Flow {
                            anchors.right: parent.right
                            width: Math.min(parent.width, implicitWidth)
                            visible: modelData.parts.length > 0
                            layoutDirection: Qt.RightToLeft
                            spacing: theme.em * 0.3
                            Repeater {
                                model: modelData.parts
                                Text { text: modelData.label; color: modelData.color; font.pointSize: theme.fontPoint * 0.72; font.weight: Font.DemiBold }
                            }
                        }
                        // Cursor values when bubble does not fit in panel
                        Text {
                            anchors.right: parent.right
                            width: parent.width
                            horizontalAlignment: Text.AlignRight
                            visible: chart.cursorShown && !chart.bubbleFits(index) && text !== ""
                            text: chart.compactValues(index)
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
                onDoubleClicked: function(mouse) { chart.resetValues(chart.panelAt(mouse.y)) }
                onWheel: function(wheel) {
                    scroller.contentY = Math.max(0, Math.min(scroller.contentY - wheel.angleDelta.y / 120 * theme.em * 3,
                                                             scroller.contentHeight - scroller.height))
                }
            }
            // Panel lower edges: drag to resize
            Repeater {
                model: chart.panels
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
                        chart.resizeWeight = modelData.weight
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
                        backend.setPanelWeight(modelData.column, weight)
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
                model: chart.panels
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
                    visible: value <= chart.viewEnd
                    x: Math.round(chart.xOf(value))
                    width: 1
                    height: plotArea.height
                    color: theme.text
                    opacity: 0.06
                }
            }

            // Sector lines (click label: zoom on sector) & corner apexes of reference lap
            Item {
                visible: backend.sectorLines.length > 0 && chart.xOf(0) >= -theme.em
                x: Math.round(chart.xOf(0))
                Text {
                    x: 3; y: 1
                    text: "S1"
                    color: s1Area.containsMouse ? theme.accent : theme.dimText
                    font.pointSize: theme.fontPoint * 0.8
                    font.weight: Font.DemiBold
                    MouseArea { id: s1Area; anchors.fill: parent; anchors.margins: -3; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chart.zoomSector(1) }
                }
            }
            Repeater {
                model: backend.sectorLines
                Item {
                    readonly property real px: chart.xOf(modelData.x)
                    visible: px >= 0 && px <= plotArea.width
                    x: Math.round(px)
                    height: plotArea.height
                    Rectangle { width: 1; height: parent.height; color: theme.text; opacity: 0.22 }
                    Text {
                        x: 3; y: 1
                        text: modelData.label
                        color: sectorArea.containsMouse ? theme.accent : theme.dimText
                        font.pointSize: theme.fontPoint * 0.8
                        font.weight: Font.DemiBold
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
            }
            Repeater {
                model: backend.cornerMarks
                Item {
                    readonly property real px: chart.xOf(modelData.x)
                    visible: px >= 0 && px <= plotArea.width
                    readonly property bool labelShown: chart.cornerLabelShown[index] === true
                    x: Math.round(px)
                    height: plotArea.height
                    Rectangle { width: 1; height: parent.height; color: theme.text; opacity: 0.09 }
                    Text {
                        x: 3; y: theme.em * 1.2
                        visible: parent.labelShown
                        text: modelData.label
                        color: theme.dimText
                        opacity: 0.8
                        font.pointSize: theme.fontPoint * 0.8
                    }
                }
            }

            // Channel lines
            Repeater {
                model: chart.panels
                Item {
                    id: panel
                    readonly property var info: modelData
                    readonly property var range: chart.rangeOf(index)
                    readonly property real sx: width / Math.max(chart.viewEnd - chart.viewStart, 1e-9)
                    readonly property real pad: Math.min(theme.em * 0.4, height * 0.1)  // lines at range limits stay visible
                    readonly property real sy: (height - pad * 2) / Math.max(range[1] - range[0], 1e-9)
                    readonly property real ty: height - pad + range[0] * sy
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
                    // Lowest & highest value of laps (consistency band)
                    GpuShape {
                        visible: panel.info.envelope !== ""
                        key: panel.info.envelope
                        color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.12 : 0.1)
                        revision: backend.revision
                        transform: Matrix4x4 {
                            matrix: Qt.matrix4x4(panel.sx, 0, 0, -chart.viewStart * panel.sx,
                                                 0, -panel.sy, 0, panel.ty, 0, 0, 1, 0, 0, 0, 0, 1)
                        }
                    }
                    Repeater {
                        model: panel.info.series
                        Item {
                            id: lapSeries
                            readonly property var series: modelData
                            opacity: chart.lapOpacity(series.lap)
                            Behavior on opacity { NumberAnimation { duration: 150 } }
                            // Line drawn twice, half a pixel apart: about 1.5 px wide (scene graph lines are 1 px)
                            Repeater {
                                model: chart.lineOffsets
                                GpuShape {
                                    key: lapSeries.series.key
                                    color: lapSeries.series.color
                                    revision: backend.revision
                                    transform: Matrix4x4 {
                                        matrix: Qt.matrix4x4(panel.sx, 0, 0, -chart.viewStart * panel.sx + modelData[0],
                                                             0, -panel.sy, 0, panel.ty + modelData[1],
                                                             0, 0, 1, 0,
                                                             0, 0, 0, 1)
                                    }
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
                    Text {
                        x: parent.width - width - 4; y: 1
                        text: chart.yRanges[panel.info.column] ? panel.range[1].toFixed(1) : panel.info.highText
                        color: theme.dimText
                        opacity: 0.8
                        visible: panel.height > theme.em * 2.6 && panel.info.available
                        font.pointSize: theme.fontPoint * 0.75
                    }
                    Text {
                        x: parent.width - width - 4; anchors.bottom: parent.bottom; anchors.bottomMargin: 1
                        text: chart.yRanges[panel.info.column] ? panel.range[0].toFixed(1) : panel.info.lowText
                        color: theme.dimText
                        opacity: 0.8
                        visible: panel.height > theme.em * 2.6 && panel.info.available
                        font.pointSize: theme.fontPoint * 0.75
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

            // Zoom selection (Shift+drag)
            Rectangle {
                id: selection
                property real fromX: 0
                property real toX: 0
                visible: false
                x: Math.min(fromX, toX)
                width: Math.abs(toX - fromX)
                height: plotArea.height
                color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.15)
                border.width: 1
                border.color: theme.accent
            }

            // Cursor line & values
            Rectangle {
                visible: chart.cursorShown && !selection.visible
                x: Math.round(chart.xOf(chart.cursorX))
                width: 1
                height: plotArea.height
                color: theme.text
                opacity: 0.55
            }
            Repeater {
                model: chart.panels
                Rectangle {
                    id: bubble
                    readonly property int panelIndex: index
                    readonly property real px: chart.xOf(chart.cursorX)
                    visible: chart.cursorShown && !selection.visible && chart.valueCount(index) > 0 && chart.bubbleFits(index)
                    x: px + 8 + width <= plotArea.width ? px + 8 : px - 8 - width
                    y: chart.panelTop(index) + 3
                    width: valueColumn.width + theme.em * 0.6
                    height: valueColumn.height + theme.em * 0.25
                    radius: theme.em * 0.3
                    color: Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.88)
                    border.width: 1
                    border.color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.12)
                    Column {
                        id: valueColumn
                        anchors.centerIn: parent
                        // One item per drawn series (kept while cursor moves), empty ones hidden
                        Repeater {
                            model: modelData.series.length
                            Row {
                                readonly property var entry: chart.cursorEntry(bubble.panelIndex, index)
                                visible: entry !== null && entry.text !== ""
                                spacing: theme.em * 0.4
                                opacity: chart.panels[bubble.panelIndex] && chart.panels[bubble.panelIndex].series[index]
                                         ? chart.lapOpacity(chart.panels[bubble.panelIndex].series[index].lap) : 1
                                Text {
                                    text: parent.entry ? parent.entry.text : ""
                                    color: parent.entry ? parent.entry.color : theme.text
                                    font.pointSize: theme.fontPoint * 0.85
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                                Text {
                                    visible: text !== ""
                                    text: parent.entry ? parent.entry.diff : ""
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.75
                                    font.features: { "tnum": 1 }
                                    anchors.baseline: parent.children[0].baseline
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
                property bool selecting: false
                cursorShape: pressed && !selecting ? Qt.ClosedHandCursor : Qt.CrossCursor

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
                    selecting = (mouse.modifiers & Qt.ShiftModifier) !== 0
                    if (selecting) {
                        selection.fromX = mouse.x
                        selection.toX = mouse.x
                        selection.visible = true
                    }
                }
                onPositionChanged: function(mouse) {
                    if (pressed && (pressedButtons & Qt.LeftButton) && selecting) {
                        selection.toX = Math.max(0, Math.min(mouse.x, width))
                    } else if (pressed && (pressedButtons & Qt.LeftButton)) {
                        var shift = (pressX - mouse.x) / Math.max(width, 1) * (pressEnd - pressStart)
                        chart.setView(pressStart + shift, pressEnd + shift, false)
                    }
                    if (!chart.playing) chart.setCursor(chart.valueOf(mouse.x))
                }
                onReleased: {
                    if (selecting && selection.width > 4)
                        chart.setView(chart.valueOf(selection.x), chart.valueOf(selection.x + selection.width), true)
                    selection.visible = false
                    selecting = false
                }
                onExited: if (!pressed && !chart.playing && !chartMenu.visible) chart.setCursor(NaN)
                onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) chart.resetView(true) }
                onWheel: function(wheel) {
                    if (wheel.modifiers & Qt.ControlModifier) {  // channel values zoom
                        chart.zoomValues(chart.panelAt(wheel.y), Math.pow(1.0015, -wheel.angleDelta.y), wheel.y)
                        return
                    }
                    if (Math.abs(wheel.angleDelta.x) > Math.abs(wheel.angleDelta.y)) {  // touchpad sideways: move
                        var span = chart.targetEnd - chart.targetStart
                        var move = -wheel.angleDelta.x / 120 * span * 0.1
                        chart.setView(chart.targetStart + move, chart.targetEnd + move, false)
                        return
                    }
                    // Zoom follows wheel amount: smooth on touchpads & high resolution wheels
                    chart.zoom(Math.pow(1.0015, -wheel.angleDelta.y), chart.valueOf(wheel.x), Math.abs(wheel.angleDelta.y) >= 120)
                }
            }
        }
    }

    TpMenu {
        id: chartMenu
        property int panelIndex: -1
        onClosed: if (!plotMouse.containsMouse && !chart.playing) chart.setCursor(NaN)
        Action { text: i18n.tr("Set Marker A Here"); onTriggered: chart.setMarker("A", chart.cursorX) }
        Action { text: i18n.tr("Set Marker B Here"); onTriggered: chart.setMarker("B", chart.cursorX) }
        Action { text: i18n.tr("Clear Markers"); enabled: !isNaN(chart.markerA) || !isNaN(chart.markerB); onTriggered: chart.clearMarkers() }
        MenuSeparator {}
        Action {
            text: i18n.tr("Zoom to Sector")
            enabled: backend.sectorLines.length > 0 && chart.hasCursor
            onTriggered: chart.zoomSector(chart.sectorAt(chart.cursorX))
        }
        Action {
            text: i18n.tr("Zoom Between Markers")
            enabled: chart.hasRange
            onTriggered: chart.zoomRange([Math.min(chart.markerA, chart.markerB), Math.max(chart.markerA, chart.markerB)], 0.03)
        }
        Action { text: i18n.tr("Reset Value Zoom"); enabled: Object.keys(chart.yRanges).length > 0; onTriggered: chart.resetValues(-1) }
        Action { text: i18n.tr("Reset Channel Heights"); onTriggered: backend.resetPanelWeights() }
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
                visible: value <= chart.viewEnd
                x: Math.max(0, Math.min(chart.xOf(value) - width / 2, axis.width - width))
                y: theme.em * 0.2
                text: chart.axisText(value)
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
            x: chart.viewStart / chart.maxX * overview.width
            width: Math.max((chart.viewEnd - chart.viewStart) / chart.maxX * overview.width, 4)
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
