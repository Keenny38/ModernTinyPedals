import QtQuick
import QtQuick.Layouts
import TinyPedal

// Lateral vs longitudinal acceleration of compared laps: right turn on the right, braking at bottom.
// Zoomed chart part highlighted, grip envelope (grip used in every direction) of each lap.
Item {
    id: circle

    property var chart
    readonly property var info: backend.gCircle
    readonly property bool hasData: info.limit !== undefined
    readonly property real limit: info.limit || 1
    readonly property real radius: Math.max(Math.min(plot.width, plot.height) / 2 - theme.em * 1.4, 10)
    readonly property real gScale: radius / limit
    readonly property bool chartZoomed: chart ? chart.zoomed : false
    readonly property var matrix: Qt.matrix4x4(gScale, 0, 0, plot.width / 2, 0, -gScale, 0, plot.height / 2, 0, 0, 1, 0, 0, 0, 0, 1)
    readonly property string highlightKey: chart ? chart.highlightKey : ""

    function lapOpacity(lapKey) { return highlightKey === "" || lapKey === highlightKey ? 1 : 0.15 }

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

        Item {
            id: plot
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

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
                        x: plot.width / 2 - ringRadius
                        y: plot.height / 2 - ringRadius
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
                Rectangle { x: plot.width / 2 - circle.radius; y: plot.height / 2; width: circle.radius * 2; height: 1; color: theme.text; opacity: 0.1 }
                Rectangle { x: plot.width / 2; y: plot.height / 2 - circle.radius; width: 1; height: circle.radius * 2; color: theme.text; opacity: 0.1 }
                Text { text: i18n.tr("Braking"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: plot.width / 2 - width / 2; y: plot.height / 2 + circle.radius + 2 }
                Text { text: i18n.tr("Acceleration"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: plot.width / 2 - width / 2; y: plot.height / 2 - circle.radius - height - 2 }
                Text { text: i18n.tr("Left"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: plot.width / 2 - circle.radius + 3; y: plot.height / 2 + 2 }
                Text { text: i18n.tr("Right"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.75; x: plot.width / 2 + circle.radius - width - 3; y: plot.height / 2 + 2 }

                Repeater {
                    model: circle.info.dots || []
                    GpuShape {
                        key: modelData.key
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
                        visible: circle.chartZoomed
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
                        opacity: circle.lapOpacity(lap.lap)
                        Repeater {
                            model: [0, 0.6]
                            GpuShape {
                                key: lap.envelope
                                color: lap.color
                                revision: backend.revision
                                transform: Matrix4x4 {
                                    matrix: Qt.matrix4x4(circle.gScale, 0, 0, plot.width / 2 + modelData, 0, -circle.gScale, 0,
                                                         plot.height / 2 + modelData, 0, 0, 1, 0, 0, 0, 0, 1)
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
                        visible: point !== null
                        x: point ? plot.width / 2 + point.x * circle.gScale - size / 2 : 0
                        y: point ? plot.height / 2 - point.y * circle.gScale - size / 2 : 0
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
        }
    }
}
