import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import NeoPedal
import "../components"

// XY tab: one channel against another at the same place on track (dots of each lap: grip, understeer, slip...),
// or share of lap time spent in each value range of a channel (histogram). Zoomed chart part only when zoomed.
// Scatter: wheel zoom at mouse, drag: move, double-click: whole plot. Lap chips: laps shown in this view.
Item {
    id: root

    property var chart
    property string mode: "scatter"
    property string xColumn: "speed_kph"
    property string yColumn: "accel_lat"
    property string histogramColumn: "throttle"
    property var scatterData: ({})
    property var histogramData: ({})
    readonly property var channels: backend.xyChannels
    readonly property string highlightKey: chart ? chart.highlightKey : ""
    readonly property var presets: [
        ["speed_kph", "accel_lat", i18n.tr("Speed / Lateral G")],
        ["steering", "accel_lat", i18n.tr("Steering / Lateral G")],
        ["throttle", "slip_rl", i18n.tr("Throttle / Wheel Slip")],
        ["speed_kph", "accel_long", i18n.tr("Speed / Longitudinal G")],
    ]

    function columnIndex(column) {
        for (var i = 0; i < channels.length; i++) if (channels[i].column === column) return i
        return -1
    }
    property bool stale: false  // laps, channels or chart zoom changed while tab hidden
    function update() {
        if (!visible) { stale = true; return }  // tab kept hidden: refreshed when shown again
        stale = false
        if (mode === "scatter") scatterData = backend.scatter(xColumn, yColumn)
        else histogramData = backend.histogram(histogramColumn)
    }
    onVisibleChanged: if (visible && stale) update()
    function lapOpacity(lapKey) { return highlightKey === "" || lapKey === highlightKey ? 1 : 0.15 }

    // Scatter zoom: part of plot shown (fractions of whole plot, y up)
    property real zoom: 1
    property real viewX: 0
    property real viewY: 0
    readonly property bool zoomed: zoom > 1.001
    function zoomAt(factor, px, py) {
        var span = 1 / zoom
        var fx = viewX + px / Math.max(plot.width, 1) * span, fy = viewY + (1 - py / Math.max(plot.height, 1)) * span
        var next = Math.max(1, Math.min(zoom * factor, 20))
        var nextSpan = 1 / next
        viewX = Math.max(0, Math.min(fx - px / Math.max(plot.width, 1) * nextSpan, 1 - nextSpan))
        viewY = Math.max(0, Math.min(fy - (1 - py / Math.max(plot.height, 1)) * nextSpan, 1 - nextSpan))
        zoom = next
    }
    function resetZoom() { zoom = 1; viewX = 0; viewY = 0 }
    // Axis values of part shown: plot fraction (at) & text. Round values worked out here (same as backend), their
    // texts asked to backend only when values or text precision change (not on every drag or wheel step)
    readonly property var labelCache: ({"count": 0, "texts": {}})  // never assigned: no binding depends on changes
    function niceStep(span, count) {
        var raw = Math.max(span / Math.max(count, 1), 1e-9)
        var magnitude = Math.pow(10, Math.floor(Math.log10(raw)))
        var multiples = [1, 2, 5, 10]
        for (var i = 0; i < multiples.length; i++) if (raw <= multiples[i] * magnitude) return multiples[i] * magnitude
        return 10 * magnitude
    }
    function ticksIn(column, range, start, whole) {
        if (!zoomed || !range) return whole || []
        var low = range[0] + (range[1] - range[0]) * start, high = low + (range[1] - range[0]) / zoom
        if (!(high > low)) return []
        var span = high - low
        var step = niceStep(span, 4)
        var first = Math.ceil(low / step) * step
        var values = []
        for (var i = 0; i < 10; i++) {
            var value = first + i * step
            if (value <= high) values.push(value)
        }
        var precision = span >= 20 ? 2 : span >= 2 ? 1 : 0  // label decimals change with span only there
        var key = column + "|" + first + "|" + step + "|" + values.length + "|" + precision
        var cache = labelCache
        var texts = cache.texts[key]
        if (texts === undefined) {
            texts = backend.charts.axisLabels(column, values, span)
            if (cache.count > 200) { cache.texts = {}; cache.count = 0 }
            cache.texts[key] = texts
            cache.count++
        }
        return values.map(function(value, index) {
            return {"at": (value - low) / Math.max(span, 1e-9), "text": texts[index] || ""}
        })
    }
    readonly property var xTicks: ticksIn(xColumn, scatterData.xRange, viewX, scatterData.xTicks)
    readonly property var yTicks: ticksIn(yColumn, scatterData.yRange, viewY, scatterData.yTicks)

    // Choices kept by backend (tab created again when viewer opens)
    property bool restored: false
    function save() { if (restored) backend.setXyState(mode, xColumn, yColumn, histogramColumn) }
    Component.onCompleted: {
        var state = backend.xyState
        mode = state.mode || "scatter"
        xColumn = state.x || xColumn
        yColumn = state.y || yColumn
        histogramColumn = state.histogram || histogramColumn
        restored = true
        update()
    }
    // Choices restored one by one: nothing computed until the last (one update once restored)
    onModeChanged: { if (!restored) return; save(); update() }
    onXColumnChanged: { if (!restored) return; save(); resetZoom(); refresh.restart() }
    onYColumnChanged: { if (!restored) return; save(); resetZoom(); refresh.restart() }
    onHistogramColumnChanged: { if (!restored) return; save(); refresh.restart() }
    Timer { id: refresh; interval: 120; onTriggered: root.update() }
    Connections {
        target: backend
        function onChartChanged() { refresh.restart() }
        function onChannelsChanged() { refresh.restart() }
    }
    Connections {  // zoomed chart part followed
        target: root.chart
        function onTargetStartChanged() { refresh.restart() }
        function onTargetEndChanged() { refresh.restart() }
    }

    // Channel list (click leaves keys to charts, Tab reaches it): closed popup gives keys back to charts
    component ChannelBox: TpCombo {
        id: box
        property string column: ""
        property var chartItem: null
        signal picked(string column)
        Connections {
            target: box.popup
            function onClosed() { if (box.chartItem) box.chartItem.forceActiveFocus() }
        }
        Layout.fillWidth: true
        textRole: "title"
        onActivated: function(index) { picked(model[index].column) }
        // Picking an item replaces the index binding: kept in step with column (presets) & channel list here
        function indexFor(name) {
            var channels = model || []
            for (var i = 0; i < channels.length; i++) if (channels[i].column === name) return i
            return -1
        }
        onColumnChanged: currentIndex = indexFor(column)
        onModelChanged: currentIndex = indexFor(column)
        Component.onCompleted: currentIndex = indexFor(column)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.space3

        TpSegmented {
            Layout.alignment: Qt.AlignHCenter
            name: i18n.tr("XY")
            options: [i18n.tr("Scatter"), i18n.tr("Histogram")]
            currentIndex: root.mode === "scatter" ? 0 : 1
            onActivated: function(index) { root.mode = index === 0 ? "scatter" : "histogram" }
        }

        // Scatter: channels & presets
        GridLayout {
            visible: root.mode === "scatter"
            Layout.fillWidth: true
            columns: 2
            columnSpacing: theme.space3
            rowSpacing: theme.space2
            Text { text: "X"; color: theme.dimText; font.weight: Font.DemiBold }
            ChannelBox {
                tip: i18n.tr("Channel along X axis")
                chartItem: root.chart
                model: root.channels
                column: root.xColumn
                onPicked: function(column) { root.xColumn = column }
            }
            Text { text: "Y"; color: theme.dimText; font.weight: Font.DemiBold }
            ChannelBox {
                tip: i18n.tr("Channel along Y axis")
                chartItem: root.chart
                model: root.channels
                column: root.yColumn
                onPicked: function(column) { root.yColumn = column }
            }
        }
        Flow {
            visible: root.mode === "scatter"
            Layout.fillWidth: true
            spacing: theme.space2
            Repeater {
                model: root.presets
                TpButton {
                    text: modelData[2]
                    flat: true
                    size: "sm"
                    enabled: root.columnIndex(modelData[0]) >= 0 && root.columnIndex(modelData[1]) >= 0
                    onClicked: { root.xColumn = modelData[0]; root.yColumn = modelData[1] }
                }
            }
        }
        RowLayout {
            visible: root.mode === "histogram"
            Layout.fillWidth: true
            spacing: theme.space3
            ChannelBox {
                tip: i18n.tr("Channel")
                chartItem: root.chart
                model: root.channels
                column: root.histogramColumn
                onPicked: function(column) { root.histogramColumn = column }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: root.chart ? root.chart.zoomed : false
            text: i18n.tr("Zoomed chart part only")
            color: theme.dimText
            font.pointSize: theme.fontCaption
        }
        LapFilter { id: lapFilter; Layout.fillWidth: true }

        // Scatter plot
        Item {
            id: scatterArea
            visible: root.mode === "scatter"
            Layout.fillWidth: true
            Layout.fillHeight: true
            readonly property real padLeft: theme.em * 3.2
            readonly property real padBottom: theme.em * 2.6
            readonly property bool hasData: root.scatterData.laps !== undefined

            TpStateView {
                anchors.centerIn: parent
                compact: true
                loading: !scatterArea.hasData && backend.loading
                empty: !scatterArea.hasData && !backend.loading
                loadingText: i18n.tr("Reading laps...")
                glyph: "\uE9D2"  // chart
                title: lapFilter.legend.length === 0 ? i18n.tr("Select recorded laps to compare.") : i18n.tr("Not recorded in shown laps")
            }
            Item {
                id: plot
                visible: scatterArea.hasData
                x: scatterArea.padLeft
                width: scatterArea.width - scatterArea.padLeft - theme.em * 0.4
                height: scatterArea.height - scatterArea.padBottom
                clip: true
                Rectangle {
                    anchors.fill: parent
                    radius: theme.radiusSm
                    color: theme.plotBase
                    border.width: 1
                    border.color: theme.plotBorder
                }
                // Wheel: zoom at mouse, drag: move, double-click: whole plot (told by tooltip while not zoomed)
                HoverHandler { id: plotHover }
                ToolTip.visible: plotHover.hovered && !root.zoomed
                ToolTip.text: i18n.tr("Wheel: zoom · drag: move · double-click: whole plot")
                ToolTip.delay: theme.tipDelay * 2
                MouseArea {
                    anchors.fill: parent
                    property real pressX: 0
                    property real pressY: 0
                    property real startX: 0
                    property real startY: 0
                    cursorShape: pressed && root.zoomed ? Qt.ClosedHandCursor : (root.zoomed ? Qt.OpenHandCursor : Qt.CrossCursor)
                    onPressed: function(mouse) { pressX = mouse.x; pressY = mouse.y; startX = root.viewX; startY = root.viewY }
                    onPositionChanged: function(mouse) {
                        if (!pressed || !root.zoomed) return
                        var span = 1 / root.zoom
                        root.viewX = Math.max(0, Math.min(startX - (mouse.x - pressX) / plot.width * span, 1 - span))
                        root.viewY = Math.max(0, Math.min(startY + (mouse.y - pressY) / plot.height * span, 1 - span))
                    }
                    onDoubleClicked: root.resetZoom()
                    onWheel: function(wheel) { if (wheel.angleDelta.y !== 0) root.zoomAt(Math.pow(1.0019, wheel.angleDelta.y), wheel.x, wheel.y) }
                }
                // Grids & axis values: fixed item count (items kept while zooming & moving, ticks read by index)
                Repeater {  // vertical grid
                    model: 10
                    Rectangle {
                        readonly property var tick: root.xTicks[index]
                        visible: tick !== undefined
                        x: tick ? Math.round(tick.at * plot.width) : 0; width: 1; height: plot.height; color: theme.text; opacity: 0.06
                    }
                }
                Repeater {  // horizontal grid
                    model: 10
                    Rectangle {
                        readonly property var tick: root.yTicks[index]
                        visible: tick !== undefined
                        y: tick ? Math.round((1 - tick.at) * plot.height) : 0; width: plot.width; height: 1; color: theme.text; opacity: 0.06
                    }
                }
                Rectangle {  // zero lines
                    readonly property real at: root.scatterData.zero ? (root.scatterData.zero[0] - root.viewX) * root.zoom : -1
                    visible: at > 0 && at < 1
                    x: Math.round(at * plot.width); width: 1; height: plot.height; color: theme.text; opacity: 0.2
                }
                Rectangle {
                    readonly property real at: root.scatterData.zero ? (root.scatterData.zero[1] - root.viewY) * root.zoom : -1
                    visible: at > 0 && at < 1
                    y: Math.round((1 - at) * plot.height); width: plot.width; height: 1; color: theme.text; opacity: 0.2
                }
                Item {  // multisampled layer while shown (smooth dots, window without MSAA)
                    anchors.fill: parent
                    layer.enabled: pageState.active && plot.visible
                    layer.samples: 4
                    Item {  // dots of every lap: one transform for all of them (zoom & move frames stay cheap)
                        transform: Matrix4x4 {
                            matrix: Qt.matrix4x4(plot.width * root.zoom, 0, 0, -root.viewX * root.zoom * plot.width,
                                                 0, -plot.height * root.zoom, 0, plot.height + root.viewY * root.zoom * plot.height,
                                                 0, 0, 1, 0, 0, 0, 0, 1)
                        }
                        Repeater {
                            model: root.scatterData.laps || []
                            GpuShape {
                                key: modelData.key
                                visible: lapFilter.shown(modelData.lap)
                                color: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.55)
                                opacity: root.lapOpacity(modelData.lap)
                                revision: backend.revision
                            }
                        }
                    }
                }
                TpButton {  // zoomed: zoom factor, click for whole plot
                    visible: root.zoomed
                    anchors { right: parent.right; top: parent.top }
                    text: "×" + root.zoom.toFixed(1).replace(".", theme.decimalPoint)
                    flat: true
                    size: "sm"
                    tip: i18n.tr("Whole plot (double-click)")
                    onClicked: root.resetZoom()
                }
            }
            Repeater {  // y values
                model: 10
                Text {
                    readonly property var tick: scatterArea.hasData ? root.yTicks[index] : undefined
                    x: scatterArea.padLeft - width - theme.em * 0.3
                    y: tick ? (1 - tick.at) * plot.height - height / 2 : 0
                    visible: tick !== undefined && y > -height / 2 && y < plot.height
                    text: tick ? tick.text : ""
                    color: theme.dimText
                    font.pointSize: theme.fontTiny
                    font.features: { "tnum": 1 }
                }
            }
            Repeater {  // x values
                model: 10
                Text {
                    readonly property var tick: scatterArea.hasData ? root.xTicks[index] : undefined
                    visible: tick !== undefined
                    x: tick ? scatterArea.padLeft + tick.at * plot.width - width / 2 : 0
                    y: plot.height + theme.em * 0.15
                    text: tick ? tick.text : ""
                    color: theme.dimText
                    font.pointSize: theme.fontTiny
                    font.features: { "tnum": 1 }
                }
            }
            Text {
                visible: scatterArea.hasData
                anchors.horizontalCenter: plot.horizontalCenter
                anchors.bottom: parent.bottom
                text: root.scatterData.xTitle || ""
                color: theme.text
                font.pointSize: theme.fontCaption
            }
            Text {
                visible: scatterArea.hasData
                x: theme.em * 0.1
                y: plot.height / 2 + width / 2
                rotation: -90
                transformOrigin: Item.TopLeft
                text: root.scatterData.yTitle || ""
                color: theme.text
                font.pointSize: theme.fontCaption
            }
        }

        // Histogram: share of lap time in each value range
        Item {
            id: histogramArea
            visible: root.mode === "histogram"
            Layout.fillWidth: true
            Layout.fillHeight: true
            readonly property var bins: root.histogramData.bins || []
            readonly property var laps: (root.histogramData.laps || []).filter(function(lap) { return lapFilter.shown(lap.lap) })
            readonly property real peak: Math.max(root.histogramData.max || 1, 1)  // not "top": anchor line of Item
            readonly property real padBottom: theme.em * 1.6
            readonly property real padLeft: theme.em * 2.6
            readonly property real binWidth: (width - padLeft) / Math.max(bins.length, 1)
            readonly property int labelEvery: Math.max(1, Math.ceil(theme.em * 3 / Math.max(binWidth, 1)))
            readonly property real plotHeight: height - padBottom
            readonly property real barWidth: Math.max((binWidth * 0.8) / Math.max(laps.length, 1) - 1, 1)
            readonly property real barsOffset: (binWidth - (barWidth + 1) * laps.length + 1) / 2  // bars centered in bin
            function barHeight(binIndex, lapIndex) {
                var lap = laps[lapIndex]
                return lap ? (lap.values[binIndex] || 0) / peak * plotHeight : 0
            }
            // Bin & lap of bar under mouse (one mouse area over plot), [-1, -1] if none
            function barAt(px, py) {
                var binIndex = Math.floor((px - padLeft) / Math.max(binWidth, 1e-9))
                if (binIndex < 0 || binIndex >= bins.length) return [-1, -1]
                var along = px - padLeft - binIndex * binWidth - barsOffset
                var lapIndex = Math.floor(along / (barWidth + 1))
                if (along < 0 || lapIndex >= laps.length || along - lapIndex * (barWidth + 1) > barWidth) return [-1, -1]
                if (py < plotHeight - barHeight(binIndex, lapIndex) || py > plotHeight) return [-1, -1]
                return [binIndex, lapIndex]
            }

            TpStateView {
                anchors.centerIn: parent
                compact: true
                loading: histogramArea.bins.length === 0 && backend.loading
                empty: histogramArea.bins.length === 0 && !backend.loading
                loadingText: i18n.tr("Reading laps...")
                glyph: "\uE9D2"  // chart
                title: lapFilter.legend.length === 0 ? i18n.tr("Select recorded laps to compare.") : i18n.tr("Not recorded in shown laps")
            }
            Repeater {  // share grid
                model: histogramArea.bins.length ? 4 : 0
                Item {
                    readonly property real share: histogramArea.peak * (index + 1) / 4
                    y: (histogramArea.height - histogramArea.padBottom) * (1 - (index + 1) / 4)
                    width: histogramArea.width
                    Rectangle { x: histogramArea.padLeft; width: histogramArea.width - histogramArea.padLeft; height: 1; color: theme.text; opacity: 0.07 }
                    Text {
                        y: -height / 2
                        width: histogramArea.padLeft - theme.em * 0.3
                        horizontalAlignment: Text.AlignRight
                        text: parent.share.toFixed(0) + "%"
                        color: theme.dimText
                        font.pointSize: theme.fontTiny
                    }
                }
            }
            Repeater {
                model: histogramArea.bins.length
                Item {
                    id: bin
                    readonly property int binIndex: index
                    x: histogramArea.padLeft + index * histogramArea.binWidth
                    width: histogramArea.binWidth
                    height: histogramArea.height - histogramArea.padBottom
                    // Bars of laps (count as model: kept while laps are filtered, read by index)
                    Repeater {
                        model: histogramArea.laps.length
                        Rectangle {
                            required property int index
                            readonly property var lap: histogramArea.laps[index]
                            x: histogramArea.barsOffset + index * (histogramArea.barWidth + 1)
                            y: bin.height - height
                            width: histogramArea.barWidth
                            height: histogramArea.barHeight(bin.binIndex, index)
                            radius: Math.min(width / 2, 2)
                            color: lap ? lap.color : "transparent"
                            opacity: root.highlightKey === "" ? 0.85 : 0.6
                        }
                    }
                    Text {
                        visible: bin.binIndex % histogramArea.labelEvery === 0
                        anchors.top: parent.bottom
                        anchors.topMargin: theme.em * 0.2
                        x: 0
                        text: histogramArea.bins[bin.binIndex]
                        color: theme.dimText
                        font.pointSize: theme.fontTiny
                        font.features: { "tnum": 1 }
                    }
                }
            }
            // Bar under mouse: tooltip placed over it (bin & lap worked out from mouse position)
            Item {
                id: hoveredBar
                objectName: "histogramHover"
                property int binIndex: -1
                property int lapIndex: -1
                readonly property var lap: binIndex >= 0 ? histogramArea.laps[lapIndex] : undefined
                readonly property real value: lap ? lap.values[binIndex] || 0 : 0
                x: histogramArea.padLeft + binIndex * histogramArea.binWidth + histogramArea.barsOffset
                   + lapIndex * (histogramArea.barWidth + 1)
                y: histogramArea.plotHeight - height
                width: histogramArea.barWidth
                height: lap ? histogramArea.barHeight(binIndex, lapIndex) : 0
                ToolTip.visible: lap !== undefined
                ToolTip.text: !lap ? "" : lap.label + " · " + histogramArea.bins[binIndex] + " " + (root.histogramData.unit || "")
                                          + " · " + value.toFixed(1).replace(".", theme.decimalPoint) + "%"
                ToolTip.delay: theme.tipDelay
            }
            MouseArea {
                anchors.fill: parent
                visible: histogramArea.bins.length > 0
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
                function pick(px, py) {
                    var found = containsMouse ? histogramArea.barAt(px, py) : [-1, -1]
                    hoveredBar.binIndex = found[0]
                    hoveredBar.lapIndex = found[1]
                }
                onPositionChanged: function(mouse) { pick(mouse.x, mouse.y) }
                onContainsMouseChanged: pick(mouseX, mouseY)
            }
        }
    }
}
