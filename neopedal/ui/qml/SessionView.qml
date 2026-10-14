import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import NeoPedal

// Session of current track: every lap time (shown laps in their color, best in gold, invalid hollow),
// fuel & tyre wear used each lap, off tracks & track limits. Click a lap: show or hide it in charts.
// Long run: pace & lap time trend of clean laps without outliers (traffic, mistakes: faded), per % tyre wear.
Item {
    id: root
    property var chart
    // Sessions, shown session & its laps read once per change, only while tab is shown (hidden: once shown again)
    property var sessionState: ({})
    property bool stale: true
    function refresh() {
        if (!visible) { stale = true; return }
        stale = false
        hoverIndex = -1  // hovered lap of former laps: none until mouse moves again
        sessionState = backend.session.state
    }
    onVisibleChanged: if (visible && stale) refresh()
    Component.onCompleted: refresh()
    Connections {
        target: backend.session
        function onChanged() { root.refresh() }
    }
    readonly property var sessions: sessionState.sessions || []
    readonly property var session: sessionState.data || ({})
    readonly property var laps: session.laps || []
    readonly property var trend: session.trend || ({})
    property int hoverIndex: -1
    // Numbers with decimal separator of app language (lap times keep their dot)
    function num(value, decimals) { return Number(value).toFixed(decimals).replace(".", theme.decimalPoint) }
    function signedText(value, decimals) { return (value >= 0 ? "+" : "−") + num(Math.abs(value), decimals) }

    // Valid laps: count, mean, consistency, fuel used (worked out by backend)
    readonly property var stats: session.stats || ({"count": 0, "mean": 0, "deviation": 0, "fuel": 0, "fuelCount": 0})
    // Lap point of chart: shown laps in their color, best lap gold, invalid hollow
    component LapPoint: Item {
        property var lap: ({})
        property real best: 0
        property real grow: 1
        readonly property real size: theme.em * (lap.shown ? 0.85 : 0.6) * grow
        readonly property color tone: lap.shown ? lap.color
            : (lap.valid && lap.time <= best + 1e-6 ? theme.gold : theme.text)
        visible: lap.time > 0
        opacity: lap.outlier ? 0.4 : 1
        Rectangle {
            x: -width / 2
            y: -height / 2
            width: parent.size
            height: parent.size
            radius: width / 2
            color: parent.lap.valid ? parent.tone : "transparent"
            border.width: parent.lap.valid ? 1.5 : 2
            border.color: parent.lap.valid ? theme.window : parent.tone
        }
    }
    function timeText(seconds) {
        if (!(seconds > 0)) return "—"
        var minutes = Math.floor(seconds / 60)
        var rest = seconds - minutes * 60
        return (minutes > 0 ? minutes + ":" + (rest < 10 ? "0" : "") : "") + rest.toFixed(3)
    }


    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.5

        ComboBox {
            id: sessionBox
            focusPolicy: Qt.NoFocus  // arrows & Space stay for charts (else ↓ switched session)
            Connections {  // keys back to charts (closed popup gives them to window)
                target: sessionBox.popup
                function onClosed() { if (root.chart) root.chart.forceActiveFocus() }
            }
            Layout.fillWidth: true
            implicitHeight: Math.round(theme.em * 2.2)
            model: root.sessions
            textRole: "title"
            currentIndex: root.sessions.findIndex(function(item) { return item.key === root.sessionState.key })
            onActivated: function(index) { backend.session.choose(root.sessions[index].key) }
            background: Rectangle {
                radius: theme.radiusMd
                color: sessionBox.hovered ? theme.hover : theme.raised
                border.width: 1
                border.color: theme.border
            }
            contentItem: Text {
                leftPadding: theme.em * 0.6
                text: sessionBox.displayText || i18n.tr("No session")
                color: theme.text
                font.weight: Font.DemiBold
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }

        // Summary
        Flow {
            Layout.fillWidth: true
            spacing: theme.em * 0.9
            visible: root.laps.length > 0
            Text { text: i18n.tr("Best") + " " + root.timeText(root.session.best); color: theme.gold; font.weight: Font.DemiBold; font.features: { "tnum": 1 } }
            Text { text: i18n.tr("Average") + " " + root.timeText(root.stats.mean); color: theme.text; font.features: { "tnum": 1 } }
            Text {
                text: i18n.tr("Consistency") + " ±" + root.num(root.stats.deviation, 3) + " s"
                color: theme.text
                font.features: { "tnum": 1 }
                visible: root.stats.count > 1
            }
            Text {
                visible: root.stats.fuelCount > 0
                text: i18n.tr("Fuel") + " " + root.num(root.stats.fuel * (root.session.fuelScale || 1) / Math.max(root.stats.fuelCount, 1), 2)
                      + " " + (root.session.fuelUnit || "") + "/" + i18n.tr("lap")
                color: theme.text
                font.features: { "tnum": 1 }
            }
            BusyIndicator { running: root.session.busy === true && pageState.active; visible: running; implicitWidth: theme.em * 1.2; implicitHeight: implicitWidth }
        }
        // Long run: clean laps without outliers
        Flow {
            Layout.fillWidth: true
            spacing: theme.em * 0.9
            visible: root.trend.pace !== undefined
            Text {
                text: i18n.tr("Long-run pace") + " " + root.timeText(root.trend.pace || 0)
                color: theme.text
                font.features: { "tnum": 1 }
                ToolTip.visible: paceArea.containsMouse
                ToolTip.text: i18n.tr("Average of clean laps, slow laps left out (traffic, mistakes)") + "\n"
                              + i18n.tr("Laps counted") + " " + (root.trend.used || 0) + " · " + i18n.tr("left out") + " " + (root.trend.left || 0)
                MouseArea { id: paceArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            }
            Text {
                visible: root.trend.slope !== undefined
                text: i18n.tr("Trend") + " " + root.signedText(root.trend.slope || 0, 3) + " s/" + i18n.tr("lap")
                color: (root.trend.slope || 0) > 0.02 ? theme.loss : (root.trend.slope || 0) < -0.02 ? theme.gain : theme.text
                font.features: { "tnum": 1 }
                ToolTip.visible: trendArea.containsMouse
                ToolTip.text: i18n.tr("Lap time change per lap over the session (tyre wear, fuel burnt, track evolution)")
                MouseArea { id: trendArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            }
            Text {
                visible: root.trend.wearSlope !== undefined
                text: root.signedText(root.trend.wearSlope || 0, 3) + " s " + i18n.tr("per % tyre wear")
                color: theme.text
                font.features: { "tnum": 1 }
            }
        }

        // Lap times, fuel & tyre wear per lap
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Item {
                id: chartCanvas
                anchors.fill: parent
                readonly property real padLeft: theme.em * 3.6
                readonly property real padRight: theme.em * 0.6
                readonly property real timeHeight: height * 0.62
                readonly property real stripGap: theme.em * 0.8
                readonly property real stripHeight: Math.max((height - timeHeight - stripGap * 2) / 2, 0)
                // Lap time scale (backend): slowest laps (spins, traffic) clipped, scale follows normal laps
                readonly property var range: root.session.range || [0, 1]
                function xAt(index) {
                    var count = Math.max(root.laps.length, 1)
                    return padLeft + (index + 0.5) / count * (width - padLeft - padRight)
                }
                function yAt(time) {
                    var top = theme.em * 0.6, bottom = timeHeight - theme.em * 0.4
                    return bottom - (Math.min(time, range[1]) - range[0]) / (range[1] - range[0]) * (bottom - top)
                }
                function stripMax(name) { return root.session.stripMax ? root.session.stripMax[name] || 0 : 0 }
                // Lines, lap points & bars drawn by the GPU (GpuShape), built by backend in chart pixels once the
                // chart size settles or laps change (not one item per lap): resize only scales them meanwhile
                property real builtWidth: 0
                property real builtHeight: 0
                property var shapeKeys: ({})
                readonly property var shapeMatrix: {
                    var plot = width - padLeft - padRight, built = builtWidth - padLeft - padRight
                    var scaleX = builtWidth > 0 && built > 0 ? plot / built : 1
                    var scaleY = builtHeight > 0 ? height / builtHeight : 1
                    return Qt.matrix4x4(scaleX, 0, 0, padLeft * (1 - scaleX), 0, scaleY, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
                }
                readonly property string shapeStyle: [theme.em, theme.window, theme.text, theme.gold].join("|")
                // Laps with track limits or off tracks: count over their point (few laps: items)
                readonly property var marked: {
                    var found = []
                    for (var i = 0; i < root.laps.length; i++) {
                        var lap = root.laps[i]
                        if (lap.time > 0 && (lap.limits > 0 || lap.offtrack > 0)) found.push(i)
                    }
                    return found
                }
                function sendShapes() {
                    if (!root.visible || width < 1 || height < 1) return
                    shapeKeys = backend.session.setChart({
                        "laps": root.laps, "width": width, "padLeft": padLeft, "padRight": padRight,
                        "top": theme.em * 0.6, "bottom": timeHeight - theme.em * 0.4, "low": range[0], "high": range[1],
                        "stripTops": [timeHeight + stripGap, timeHeight + stripGap * 2 + stripHeight],
                        "stripHeight": stripHeight, "em": theme.em, "best": root.session.best || 0,
                        "window": "" + theme.window, "text": "" + theme.text, "gold": "" + theme.gold,
                        "fuelColor": "" + theme.seriesFuel, "wearColor": "" + theme.seriesWear
                    })
                    builtWidth = width
                    builtHeight = height
                }
                function sizeChanged() {
                    if (builtWidth <= 0) Qt.callLater(sendShapes)  // first shapes at once
                    else shapeTimer.restart()
                }
                onWidthChanged: sizeChanged()
                onHeightChanged: sizeChanged()
                onRangeChanged: Qt.callLater(sendShapes)  // laps changed (range follows them)
                onShapeStyleChanged: Qt.callLater(sendShapes)
                Connections {
                    target: root
                    function onVisibleChanged() { if (root.visible) Qt.callLater(chartCanvas.sendShapes) }
                }
                Timer {
                    id: shapeTimer
                    interval: 150
                    onTriggered: chartCanvas.sendShapes()
                }

                // Time grid
                Repeater {
                    model: root.laps.length ? 5 : 0
                    Item {
                        readonly property real value: chartCanvas.range[0] + (chartCanvas.range[1] - chartCanvas.range[0]) * index / 4
                        y: Math.round(chartCanvas.yAt(value))
                        width: chartCanvas.width
                        Rectangle { x: chartCanvas.padLeft; width: chartCanvas.width - chartCanvas.padLeft - chartCanvas.padRight; height: 1; color: theme.border }
                        Text {
                            y: -height / 2
                            text: root.timeText(parent.value).replace(/(\.\d)\d+$/, "$1")
                            color: theme.dimText
                            font.pointSize: theme.fontTiny
                            font.features: { "tnum": 1 }
                        }
                    }
                }
                // Best lap line
                Rectangle {
                    visible: root.session.best > 0
                    x: chartCanvas.padLeft
                    y: chartCanvas.yAt(root.session.best || 0)
                    width: chartCanvas.width - chartCanvas.padLeft - chartCanvas.padRight
                    height: 1
                    color: theme.gold
                    opacity: 0.7
                }
                // Trend line & GPU shapes in a multisampled layer while shown (smooth edges, window without MSAA)
                Item {
                    width: chartCanvas.width
                    height: chartCanvas.height
                    layer.enabled: pageState.active && root.visible && root.laps.length > 0
                    layer.samples: 4
                    // Long run trend line (clean laps without outliers)
                    Rectangle {
                        readonly property real x0: chartCanvas.xAt(root.trend.x0 || 0)
                        readonly property real y0: chartCanvas.yAt(root.trend.y0 || 0)
                        readonly property real x1: chartCanvas.xAt(root.trend.x1 || 0)
                        readonly property real y1: chartCanvas.yAt(root.trend.y1 || 0)
                        visible: root.trend.slope !== undefined
                        x: x0
                        y: y0
                        width: Math.hypot(x1 - x0, y1 - y0)
                        height: 2
                        transformOrigin: Item.Left
                        rotation: Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI
                        color: theme.purple
                        opacity: 0.75
                    }
                    // Valid laps joined, lap points (shown laps in their color, best lap gold, invalid hollow) & fuel /
                    // tyre wear bars: GPU shapes (hovered point drawn larger on top by an item)
                    Item {
                        objectName: "sessionShapes"
                        transform: Matrix4x4 { matrix: chartCanvas.shapeMatrix }
                        GpuShape {
                            key: chartCanvas.shapeKeys.segments || ""
                            color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.3)
                        }
                        GpuShape { key: chartCanvas.shapeKeys.points || "" }
                        GpuShape { key: chartCanvas.shapeKeys.bars || "" }
                    }
                }
                // Track limits / off track count over lap points: made only for laps with some
                Repeater {
                    model: chartCanvas.marked
                    Text {
                        required property var modelData
                        readonly property var lap: root.laps[modelData] || ({})
                        readonly property real size: theme.em * (lap.shown ? 0.85 : 0.6)
                        x: chartCanvas.xAt(modelData) - width / 2
                        y: chartCanvas.yAt(lap.time || 0) - size / 2 - height
                        opacity: lap.outlier ? 0.4 : 1
                        text: lap.limits > 0 ? "✕" + lap.limits : "◇" + lap.offtrack
                        color: lap.limits > 0 ? theme.warning : theme.dimText
                        font.pointSize: theme.fontTiny
                    }
                }
                LapPoint {  // hovered lap: one item follows hover (lap points never bound to it)
                    readonly property bool hovering: root.hoverIndex >= 0 && root.hoverIndex < root.laps.length
                    visible: hovering && lap.time > 0
                    lap: hovering ? root.laps[root.hoverIndex] : ({})
                    best: root.session.best || 0
                    grow: 1.3
                    x: chartCanvas.xAt(Math.max(root.hoverIndex, 0))
                    y: chartCanvas.yAt(lap.time || 0)
                }
                // Fuel & tyre wear used each lap
                Repeater {
                    model: [["fuel", i18n.tr("Fuel"), theme.seriesFuel], ["wear", i18n.tr("Tyre wear"), theme.seriesWear]]
                    Item {
                        id: strip
                        readonly property string name: modelData[0]
                        readonly property color tone: modelData[2]
                        readonly property real high: chartCanvas.stripMax(name)
                        y: chartCanvas.timeHeight + chartCanvas.stripGap + index * (chartCanvas.stripHeight + chartCanvas.stripGap)
                        width: chartCanvas.width
                        height: chartCanvas.stripHeight
                        visible: high > 0
                        Text { text: modelData[1]; color: theme.dimText; font.pointSize: theme.fontTiny }
                        Text {
                            anchors.bottom: parent.bottom
                            text: strip.name === "fuel" ? root.num(strip.high * (root.session.fuelScale || 1), 2) + " " + (root.session.fuelUnit || "")
                                                        : root.num(strip.high, 1) + " %"
                            color: theme.dimText
                            font.pointSize: theme.fontTiny
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
            MouseArea {
                id: canvasMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: root.hoverIndex >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
                function indexAt(px) {
                    var count = root.laps.length
                    if (count === 0 || px < chartCanvas.padLeft) return -1
                    var index = Math.floor((px - chartCanvas.padLeft) / (width - chartCanvas.padLeft - chartCanvas.padRight) * count)
                    return index >= 0 && index < count ? index : -1
                }
                onPositionChanged: function(mouse) { root.hoverIndex = indexAt(mouse.x) }
                onExited: root.hoverIndex = -1
                onClicked: function(mouse) {
                    var index = indexAt(mouse.x)
                    if (index >= 0) backend.setLapChecked(root.laps[index].path, !root.laps[index].shown)
                }
                onDoubleClicked: function(mouse) {
                    var index = indexAt(mouse.x)
                    if (index >= 0) backend.setReference(root.laps[index].path)
                }
            }
            // Hovered lap details
            Rectangle {
                readonly property var lap: root.hoverIndex >= 0 ? root.laps[root.hoverIndex] || null : null
                visible: lap !== null
                x: Math.max(0, Math.min(chartCanvas.xAt(root.hoverIndex) + theme.em, parent.width - width))
                y: theme.em * 0.3
                width: lapText.implicitWidth + theme.em
                height: lapText.implicitHeight + theme.em * 0.5
                radius: theme.radiusSm
                color: theme.raised
                border.width: 1
                border.color: lap && lap.color ? lap.color : theme.border
                Text {
                    id: lapText
                    anchors.centerIn: parent
                    color: theme.text
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                    text: {
                        var lap = parent.lap
                        if (!lap) return ""
                        var lines = [i18n.tr("Lap") + " " + lap.number + " · " + lap.text + (lap.valid ? "" : " · " + i18n.tr("invalid"))
                                     + (lap.outlier ? " · " + i18n.tr("left out of long run") : "")]
                        var details = []
                        if (lap.fuel >= 0) details.push(i18n.tr("Fuel") + " " + root.num(lap.fuel * (root.session.fuelScale || 1), 2) + " " + (root.session.fuelUnit || ""))
                        if (lap.wear >= 0) details.push(i18n.tr("Tyre wear") + " " + root.num(lap.wear, 2) + " %")
                        if (lap.temp !== null) details.push(i18n.tr("Track Temp") + " " + root.num(lap.temp, 1) + (root.session.temperatureUnit || "°C"))
                        if (details.length) lines.push(details.join(" · "))
                        var events = []
                        if (lap.limits >= 0) events.push("✕ " + i18n.tr("Track limits exceeded") + " " + lap.limits)
                        if (lap.offtrack >= 0) events.push("◇ " + i18n.tr("Off track") + " " + lap.offtrack)
                        if (events.length) lines.push(events.join(" · "))
                        lines.push(lap.shown ? i18n.tr("Click: hide from charts") : i18n.tr("Click: show in charts · double-click: reference"))
                        return lines.join("\n")
                    }
                }
            }
        }
        Text {
            visible: root.laps.length === 0
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18n.tr("No lap recorded in this session.")
            color: theme.dimText
        }
    }
}
