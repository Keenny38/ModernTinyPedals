import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import TinyPedal

// Lap viewer track map: circuit, driving lines of compared laps, colored by lap, time gain, speed or pedals.
// Zoomed chart part highlighted (map follows it), braking points, corners (click: zoom charts on corner),
// cursor position of each lap. Click a line: show this point in charts.
Item {
    id: root

    property var chart  // TraceChart
    readonly property var info: backend.trackMap
    readonly property bool hasMap: info.road !== undefined
    readonly property bool chartZoomed: chart ? chart.zoomed : false
    readonly property string mode: backend.mapMode
    readonly property var modes: ["laps", "gain", "speed", "pedals"]
    property var cursorPoints: []

    function followChart() {
        if (!backend.mapFollow || !chart) return
        if (!chart.zoomed) { canvas.reset(true); return }
        var bounds = backend.mapBounds(chart.targetStart, chart.targetEnd)
        if (bounds.length === 4) canvas.fit(bounds[0], bounds[1], bounds[2], bounds[3], true)
    }

    Connections {
        target: root.chart
        function onTargetStartChanged() { followTimer.restart() }
        function onTargetEndChanged() { followTimer.restart() }
        function onCursorXChanged() {
            root.cursorPoints = isNaN(root.chart.cursorX) ? [] : backend.mapCursor(root.chart.cursorX)
        }
    }
    Timer { id: followTimer; interval: 10; onTriggered: root.followChart() }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.4

        TpSegmented {
            Layout.alignment: Qt.AlignHCenter
            options: [i18n.tr("Laps"), i18n.tr("Gain / Loss"), i18n.tr("Speed"), i18n.tr("Pedals")]
            currentIndex: root.modes.indexOf(root.mode)
            onActivated: function(index) { backend.setMapMode(root.modes[index]) }
        }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: theme.em * 0.8
            TpSwitch {
                text: i18n.tr("Follow zoom")
                tip: i18n.tr("Map zooms on the part of lap zoomed in charts")
                checked: backend.mapFollow
                onToggled: { backend.setMapFollow(checked); root.followChart() }
            }
            TpSwitch {
                text: i18n.tr("Braking points")
                tip: i18n.tr("Where each lap starts braking")
                checked: backend.mapBraking
                onToggled: backend.setMapBraking(checked)
            }
        }

        MapCanvas {
            id: canvas
            Layout.fillWidth: true
            Layout.fillHeight: true
            minX: root.info.minX || 0
            minY: root.info.minY || 0
            maxX: root.info.maxX || 1
            maxY: root.info.maxY || 1
            onSettled: if (root.hasMap && root.chart)
                backend.setMapView(root.chart.zoomed ? root.chart.targetStart : 0,
                                   root.chart.zoomed ? root.chart.targetEnd : 0, canvas.metersPerPixel)
            onClicked: function(x, y) {
                if (!root.chart) return
                var position = backend.mapPick(x, y, theme.em * 1.5 * canvas.metersPerPixel)
                if (position >= 0) root.chart.showX(position)
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

            // Driving lines: faded when zoomed (zoomed part drawn over), or under colored line
            Repeater {
                model: root.info.lines || []
                GpuShape {
                    key: modelData.key
                    color: modelData.color
                    revision: backend.revision
                    opacity: root.mode === "laps" ? (root.chartZoomed ? 0.3 : 0.95)
                           : root.mode === "gain" ? (modelData.reference ? 0.35 : 0) : 0.12
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

            // Braking points
            Repeater {
                model: backend.mapBraking ? (root.info.braking || []) : []
                Rectangle {
                    readonly property real size: theme.em * 0.55
                    x: canvas.screenX(modelData.x) - size / 2
                    y: canvas.screenY(modelData.y) - size / 2
                    width: size
                    height: size
                    rotation: 45
                    color: modelData.color
                    border.width: 1
                    border.color: theme.window
                }
            }

            // Corners: number & time lost / gained, click to zoom charts on corner
            Repeater {
                model: root.info.corners || []
                Rectangle {
                    readonly property real anchorX: canvas.screenX(modelData.x)
                    x: anchorX + 6 + width <= canvas.width ? anchorX + 6 : anchorX - 6 - width  // kept inside map
                    y: canvas.screenY(modelData.y) - height - 4
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
                            color: modelData.deltaColor || theme.dimText
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

            // Cursor position of each lap
            Repeater {
                model: root.cursorPoints
                Rectangle {
                    readonly property real size: theme.em * (index === 0 ? 1.0 : 0.8)
                    x: canvas.screenX(modelData.x) - size / 2
                    y: canvas.screenY(modelData.y) - size / 2
                    width: size
                    height: size
                    radius: size / 2
                    color: modelData.color
                    border.width: 2
                    border.color: theme.window
                }
            }
        }

        // Legend of color mode
        Item {
            Layout.fillWidth: true
            implicitHeight: legendRow.implicitHeight
            visible: root.hasMap && root.mode !== "laps"
            Row {
                id: legendRow
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: theme.em * 0.8
                Repeater {
                    model: root.mode === "gain" ? [[i18n.tr("Losing time"), "#EF4444"], [i18n.tr("Gaining time"), "#22C55E"]]
                         : root.mode === "pedals" ? [[i18n.tr("Throttle"), "#22C55E"], [i18n.tr("Brake"), "#EF4444"],
                                                     [i18n.tr("Both"), "#F59E0B"], [i18n.tr("Coasting"), "#9CA3AF"]]
                         : []
                    Row {
                        spacing: theme.em * 0.3
                        Rectangle { width: theme.em * 0.6; height: width; radius: width / 2; color: modelData[1]; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: modelData[0]; color: theme.text; font.pointSize: theme.fontPoint * 0.85 }
                    }
                }
                Row {
                    visible: root.mode === "speed" && backend.mapLegend.low !== undefined
                    spacing: theme.em * 0.4
                    Text { text: backend.mapLegend.low || ""; color: theme.text; font.pointSize: theme.fontPoint * 0.85 }
                    Rectangle {
                        width: theme.em * 8
                        height: theme.em * 0.5
                        radius: height / 2
                        anchors.verticalCenter: parent.verticalCenter
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "#3B82F6" }
                            GradientStop { position: 0.33; color: "#22C55E" }
                            GradientStop { position: 0.66; color: "#FACC15" }
                            GradientStop { position: 1; color: "#EF4444" }
                        }
                    }
                    Text {
                        text: (backend.mapLegend.high || "") + " " + (backend.mapLegend.unit || "")
                        color: theme.text
                        font.pointSize: theme.fontPoint * 0.85
                    }
                }
            }
        }
    }
}
