import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import TinyPedal

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
    // Axis values of part shown: plot fraction (at) & text
    function ticksIn(column, range, start, whole) {
        if (!zoomed || !range) return whole || []
        var low = range[0] + (range[1] - range[0]) * start, high = low + (range[1] - range[0]) / zoom
        return backend.axisTicks(column, low, high).map(function(tick) {
            return {"at": (tick.value - low) / Math.max(high - low, 1e-9), "text": tick.text}
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
    onModeChanged: { save(); update() }
    onXColumnChanged: { save(); resetZoom(); refresh.restart() }
    onYColumnChanged: { save(); resetZoom(); refresh.restart() }
    onHistogramColumnChanged: { save(); refresh.restart() }
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

    component ChannelBox: ComboBox {
        id: box
        property string column: ""
        signal picked(string column)
        Layout.fillWidth: true
        implicitHeight: Math.round(theme.em * 2.1)
        model: root.channels
        textRole: "title"
        currentIndex: root.columnIndex(column)
        onActivated: function(index) { picked(root.channels[index].column) }
        // Picking an item replaces the binding: kept in step with column (presets) & channel list
        onColumnChanged: currentIndex = root.columnIndex(column)
        onModelChanged: currentIndex = root.columnIndex(column)
        background: Rectangle {
            radius: theme.em * 0.45
            color: box.hovered ? theme.hover : theme.raised
            border.width: 1
            border.color: theme.border
        }
        contentItem: Text {
            leftPadding: theme.em * 0.5
            text: box.displayText
            color: theme.text
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.4

        TpSegmented {
            Layout.alignment: Qt.AlignHCenter
            options: [i18n.tr("Scatter"), i18n.tr("Histogram")]
            currentIndex: root.mode === "scatter" ? 0 : 1
            onActivated: function(index) { root.mode = index === 0 ? "scatter" : "histogram" }
        }

        // Scatter: channels & presets
        GridLayout {
            visible: root.mode === "scatter"
            Layout.fillWidth: true
            columns: 2
            columnSpacing: theme.em * 0.4
            rowSpacing: theme.em * 0.3
            Text { text: "X"; color: theme.dimText; font.weight: Font.DemiBold }
            ChannelBox { column: root.xColumn; onPicked: function(column) { root.xColumn = column } }
            Text { text: "Y"; color: theme.dimText; font.weight: Font.DemiBold }
            ChannelBox { column: root.yColumn; onPicked: function(column) { root.yColumn = column } }
        }
        Flow {
            visible: root.mode === "scatter"
            Layout.fillWidth: true
            spacing: theme.em * 0.25
            Repeater {
                model: root.presets
                TpButton {
                    text: modelData[2]
                    flat: true
                    implicitHeight: theme.em * 1.8
                    enabled: root.columnIndex(modelData[0]) >= 0 && root.columnIndex(modelData[1]) >= 0
                    onClicked: { root.xColumn = modelData[0]; root.yColumn = modelData[1] }
                }
            }
        }
        RowLayout {
            visible: root.mode === "histogram"
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            ChannelBox { column: root.histogramColumn; onPicked: function(column) { root.histogramColumn = column } }
        }
        Text {
            Layout.fillWidth: true
            visible: root.chart ? root.chart.zoomed : false
            text: i18n.tr("Zoomed chart part only")
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.8
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

            Text {
                anchors.centerIn: parent
                visible: !scatterArea.hasData
                text: backend.legend.length === 0 ? i18n.tr("Select recorded laps to compare.") : i18n.tr("Not recorded in shown laps")
                color: theme.dimText
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
                    radius: theme.em * 0.35
                    color: theme.dark ? Qt.darker(theme.base, 1.18) : Qt.darker(theme.base, 1.015)
                    border.width: 1
                    border.color: theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border
                }
                MouseArea {  // wheel: zoom at mouse, drag: move, double-click: whole plot
                    anchors.fill: parent
                    property real pressX: 0
                    property real pressY: 0
                    property real startX: 0
                    property real startY: 0
                    cursorShape: pressed ? Qt.ClosedHandCursor : (root.zoomed ? Qt.OpenHandCursor : Qt.ArrowCursor)
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
                Repeater {  // vertical grid
                    model: root.xTicks
                    Rectangle { x: Math.round(modelData.at * plot.width); width: 1; height: plot.height; color: theme.text; opacity: 0.06 }
                }
                Repeater {  // horizontal grid
                    model: root.yTicks
                    Rectangle { y: Math.round((1 - modelData.at) * plot.height); width: plot.width; height: 1; color: theme.text; opacity: 0.06 }
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
                Repeater {
                    model: root.scatterData.laps || []
                    GpuShape {
                        key: modelData.key
                        visible: lapFilter.shown(modelData.lap)
                        color: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.55)
                        opacity: root.lapOpacity(modelData.lap)
                        revision: backend.revision
                        transform: Matrix4x4 {
                            matrix: Qt.matrix4x4(plot.width * root.zoom, 0, 0, -root.viewX * root.zoom * plot.width,
                                                 0, -plot.height * root.zoom, 0, plot.height + root.viewY * root.zoom * plot.height,
                                                 0, 0, 1, 0, 0, 0, 0, 1)
                        }
                    }
                }
                TpButton {  // zoomed: zoom factor, click for whole plot
                    visible: root.zoomed
                    anchors { right: parent.right; top: parent.top }
                    text: "×" + root.zoom.toFixed(1).replace(".", theme.decimalPoint)
                    flat: true
                    implicitHeight: theme.em * 1.8
                    tip: i18n.tr("Whole plot (double-click)")
                    onClicked: root.resetZoom()
                }
            }
            Repeater {  // y values
                model: scatterArea.hasData ? root.yTicks : []
                Text {
                    x: scatterArea.padLeft - width - theme.em * 0.3
                    y: (1 - modelData.at) * plot.height - height / 2
                    visible: y > -height / 2 && y < plot.height
                    text: modelData.text
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.72
                    font.features: { "tnum": 1 }
                }
            }
            Repeater {  // x values
                model: scatterArea.hasData ? root.xTicks : []
                Text {
                    x: scatterArea.padLeft + modelData.at * plot.width - width / 2
                    y: plot.height + theme.em * 0.15
                    text: modelData.text
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.72
                    font.features: { "tnum": 1 }
                }
            }
            Text {
                visible: scatterArea.hasData
                anchors.horizontalCenter: plot.horizontalCenter
                anchors.bottom: parent.bottom
                text: root.scatterData.xTitle || ""
                color: theme.text
                font.pointSize: theme.fontPoint * 0.8
            }
            Text {
                visible: scatterArea.hasData
                x: theme.em * 0.1
                y: plot.height / 2 + width / 2
                rotation: -90
                transformOrigin: Item.TopLeft
                text: root.scatterData.yTitle || ""
                color: theme.text
                font.pointSize: theme.fontPoint * 0.8
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

            Text {
                anchors.centerIn: parent
                visible: histogramArea.bins.length === 0
                text: backend.legend.length === 0 ? i18n.tr("Select recorded laps to compare.") : i18n.tr("Not recorded in shown laps")
                color: theme.dimText
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
                        font.pointSize: theme.fontPoint * 0.7
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
                    Row {
                        anchors.bottom: parent.bottom
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 1
                        Repeater {
                            model: histogramArea.laps
                            Rectangle {
                                readonly property real value: modelData.values[bin.binIndex] || 0
                                width: Math.max((bin.width * 0.8) / Math.max(histogramArea.laps.length, 1) - 1, 1)
                                height: value / histogramArea.peak * bin.height
                                anchors.bottom: parent.bottom
                                radius: Math.min(width / 2, 2)
                                color: modelData.color
                                opacity: root.highlightKey === "" ? 0.85 : 0.6
                                ToolTip.visible: barArea.containsMouse
                                ToolTip.text: modelData.label + " · " + histogramArea.bins[bin.binIndex] + " " + (root.histogramData.unit || "")
                                              + " · " + value.toFixed(1).replace(".", theme.decimalPoint) + "%"
                                ToolTip.delay: 300
                                MouseArea { id: barArea; anchors.fill: parent; hoverEnabled: true }
                            }
                        }
                    }
                    Text {
                        visible: bin.binIndex % histogramArea.labelEvery === 0
                        anchors.top: parent.bottom
                        anchors.topMargin: theme.em * 0.15
                        x: 0
                        text: histogramArea.bins[bin.binIndex]
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.7
                        font.features: { "tnum": 1 }
                    }
                }
            }
        }
    }
}
