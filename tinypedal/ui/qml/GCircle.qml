import QtQuick
import TinyPedal

// Lateral vs longitudinal acceleration of compared laps (braking at bottom), zoomed chart part highlighted
Item {
    id: circle
    clip: true

    property var chart
    readonly property var info: backend.gCircle
    readonly property bool hasData: info.limit !== undefined
    readonly property real limit: info.limit || 1
    readonly property real radius: Math.max(Math.min(width, height) / 2 - theme.em * 1.2, 10)
    readonly property real gScale: radius / limit
    readonly property bool chartZoomed: chart ? chart.zoomed : false
    readonly property var matrix: Qt.matrix4x4(gScale, 0, 0, width / 2, 0, -gScale, 0, height / 2, 0, 0, 1, 0, 0, 0, 0, 1)
    property var cursorPoints: []

    Connections {
        target: circle.chart
        function onCursorXChanged() {
            circle.cursorPoints = isNaN(circle.chart.cursorX) ? [] : backend.gCursor(circle.chart.cursorX)
        }
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
                x: circle.width / 2 - ringRadius
                y: circle.height / 2 - ringRadius
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
        Rectangle { x: circle.width / 2 - circle.radius; y: circle.height / 2; width: circle.radius * 2; height: 1; color: theme.text; opacity: 0.1 }
        Rectangle { x: circle.width / 2; y: circle.height / 2 - circle.radius; width: 1; height: circle.radius * 2; color: theme.text; opacity: 0.1 }
        Text { text: i18n.tr("Braking"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: circle.width / 2 - width / 2; y: circle.height / 2 + circle.radius + 2 }

        Repeater {
            model: circle.info.dots || []
            GpuShape {
                key: modelData.key
                color: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, circle.chartZoomed ? 0.12 : 0.4)
                revision: backend.revision
                transform: Matrix4x4 { matrix: circle.matrix }
            }
        }
        Repeater {
            model: circle.info.dots || []
            GpuShape {
                key: modelData.zoom
                color: modelData.color
                visible: circle.chartZoomed
                revision: backend.revision
                transform: Matrix4x4 { matrix: circle.matrix }
            }
        }
        Repeater {
            model: circle.cursorPoints
            Rectangle {
                readonly property real size: theme.em * 0.85
                x: circle.width / 2 + modelData.x * circle.gScale - size / 2
                y: circle.height / 2 - modelData.y * circle.gScale - size / 2
                width: size
                height: size
                radius: size / 2
                color: modelData.color
                border.width: 2
                border.color: theme.window
            }
        }
    }
}
