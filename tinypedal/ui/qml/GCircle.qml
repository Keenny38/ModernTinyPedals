import QtQuick
import QtQuick.Layouts
import TinyPedal

// Lateral vs longitudinal acceleration of compared laps: right turn on the right, braking at bottom.
// Zoomed chart part highlighted, grip envelope (grip used in every direction) of each lap.
// Wheel: zoom at mouse, drag: move, double-click: whole circle. Lap chips: laps shown in this view.
Item {
    id: circle

    property var chart
    readonly property var info: backend.gCircle
    readonly property bool hasData: info.limit !== undefined
    readonly property real limit: info.limit || 1
    readonly property real radius: Math.max(Math.min(plot.width, plot.height) / 2 - theme.em * 1.4, 10)
    property real zoom: 1  // circle zoom, 1: whole circle
    property real centerX: 0  // G shown at plot center (zoomed)
    property real centerY: 0
    readonly property real gScale: radius / limit * zoom
    readonly property real originX: plot.width / 2 - centerX * gScale  // where 0 G is on screen
    readonly property real originY: plot.height / 2 + centerY * gScale
    readonly property bool chartZoomed: chart ? chart.zoomed : false
    readonly property var matrix: Qt.matrix4x4(gScale, 0, 0, originX, 0, -gScale, 0, originY, 0, 0, 1, 0, 0, 0, 0, 1)
    readonly property string highlightKey: chart ? chart.highlightKey : ""

    function lapOpacity(lapKey) { return highlightKey === "" || lapKey === highlightKey ? 1 : 0.15 }
    // Zoom at screen point (G under it stays under it), whole circle again at zoom 1
    function zoomAt(factor, px, py) {
        var gx = (px - originX) / gScale, gy = (originY - py) / gScale
        var next = Math.max(1, Math.min(zoom * factor, 8))
        var scale = radius / limit * next
        zoom = next
        centerX = next > 1 ? gx - (px - plot.width / 2) / scale : 0
        centerY = next > 1 ? gy + (py - plot.height / 2) / scale : 0
    }
    function resetZoom() { zoom = 1; centerX = 0; centerY = 0 }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.4

        TpSwitch {
            Layout.alignment: Qt.AlignHCenter
            visible: circle.hasData
            text: i18n.tr("Grip envelope")
            tip: i18n.tr("Outline of grip used in every direction by each lap (dots faded)")
            checked: backend.gEnvelope
            onToggled: backend.setGEnvelope(checked)
        }
        LapFilter { id: lapFilter; Layout.fillWidth: true; visible: circle.hasData && backend.legend.length > 1 }

        Item {
            id: plot
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            MouseArea {
                anchors.fill: parent
                enabled: circle.hasData
                property real pressX: 0
                property real pressY: 0
                property real startX: 0
                property real startY: 0
                cursorShape: pressed ? Qt.ClosedHandCursor : (circle.zoom > 1 ? Qt.OpenHandCursor : Qt.ArrowCursor)
                onPressed: function(mouse) { pressX = mouse.x; pressY = mouse.y; startX = circle.centerX; startY = circle.centerY }
                onPositionChanged: function(mouse) {
                    if (!pressed || circle.zoom <= 1) return
                    circle.centerX = startX - (mouse.x - pressX) / circle.gScale
                    circle.centerY = startY + (mouse.y - pressY) / circle.gScale
                }
                onDoubleClicked: circle.resetZoom()
                onWheel: function(wheel) { if (wheel.angleDelta.y !== 0) circle.zoomAt(Math.pow(1.0019, wheel.angleDelta.y), wheel.x, wheel.y) }
            }

            Text {
                anchors.centerIn: parent
                visible: !circle.hasData
                text: i18n.tr("No acceleration recorded")
                color: theme.dimText
            }

            Item {
                anchors.fill: parent
                visible: circle.hasData

                Repeater {
                    model: Math.round(circle.limit)
                    Rectangle {
                        readonly property real ringRadius: (index + 1) * circle.gScale
                        x: circle.originX - ringRadius
                        y: circle.originY - ringRadius
                        width: ringRadius * 2
                        height: width
                        radius: ringRadius
                        color: "transparent"
                        border.width: 1
                        border.color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, index === 0 ? 0.22 : 0.1)
                        Text {
                            x: parent.width / 2 + 3
                            y: 1
                            text: (index + 1) + "G"
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.75
                        }
                    }
                }
                readonly property real reach: circle.limit * circle.gScale  // outer ring radius on screen
                Rectangle { x: circle.originX - parent.reach; y: circle.originY; width: parent.reach * 2; height: 1; color: theme.text; opacity: 0.1 }
                Rectangle { x: circle.originX; y: circle.originY - parent.reach; width: 1; height: parent.reach * 2; color: theme.text; opacity: 0.1 }
                Text { text: i18n.tr("Braking"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: circle.originX - width / 2; y: circle.originY + parent.reach + 2 }
                Text { text: i18n.tr("Acceleration"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: circle.originX - width / 2; y: circle.originY - parent.reach - height - 2 }
                Text { text: i18n.tr("Left"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: circle.originX - parent.reach + 3; y: circle.originY + 2 }
                Text { text: i18n.tr("Right"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: circle.originX + parent.reach - width - 3; y: circle.originY + 2 }

                Repeater {
                    model: circle.info.dots || []
                    GpuShape {
                        key: modelData.key
                        visible: lapFilter.shown(modelData.lap)
                        color: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b,
                                       circle.chartZoomed || backend.gEnvelope ? 0.12 : 0.4)
                        opacity: circle.lapOpacity(modelData.lap)
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: circle.matrix }
                    }
                }
                Repeater {
                    model: circle.info.dots || []
                    GpuShape {
                        key: modelData.zoom
                        color: modelData.color
                        visible: circle.chartZoomed && lapFilter.shown(modelData.lap)
                        opacity: circle.lapOpacity(modelData.lap)
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: circle.matrix }
                    }
                }
                // Grip envelope: line drawn twice half a pixel apart (thicker)
                Repeater {
                    model: backend.gEnvelope ? (circle.info.dots || []) : []
                    Item {
                        readonly property var lap: modelData
                        visible: lapFilter.shown(lap.lap)
                        opacity: circle.lapOpacity(lap.lap)
                        Repeater {
                            model: [0, 0.6]
                            GpuShape {
                                key: lap.envelope
                                color: lap.color
                                revision: backend.revision
                                transform: Matrix4x4 {
                                    matrix: Qt.matrix4x4(circle.gScale, 0, 0, circle.originX + modelData, 0, -circle.gScale, 0,
                                                         circle.originY + modelData, 0, 0, 1, 0, 0, 0, 0, 1)
                                }
                            }
                        }
                    }
                }
                // Cursor position of each lap (one item per lap, kept while cursor moves)
                Repeater {
                    model: circle.info.dots ? circle.info.dots.length : 0
                    Rectangle {
                        readonly property var point: circle.chart && circle.chart.cursorG[index] ? circle.chart.cursorG[index] : null
                        readonly property real size: theme.em * 0.85
                        visible: point !== null && lapFilter.shown(point.lap)
                        x: point ? circle.originX + point.x * circle.gScale - size / 2 : 0
                        y: point ? circle.originY - point.y * circle.gScale - size / 2 : 0
                        width: size
                        height: size
                        radius: size / 2
                        color: point ? point.color : "transparent"
                        opacity: point ? circle.lapOpacity(point.lap) : 1
                        border.width: 2
                        border.color: theme.window
                    }
                }
            }
            // Zoomed: zoom factor, click for whole circle
            TpButton {
                visible: circle.zoom > 1.01
                anchors { right: parent.right; top: parent.top }
                text: "×" + circle.zoom.toFixed(1).replace(".", theme.decimalPoint)
                flat: true
                implicitHeight: theme.em * 1.8
                tip: i18n.tr("Whole circle (double-click)")
                onClicked: circle.resetZoom()
            }
        }
    }
}
