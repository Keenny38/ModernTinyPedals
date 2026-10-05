import QtQuick
import QtQuick.Controls.Basic

// Personal best progression: best lap of each session (dots, new personal best in accent color, slow
// sessions clipped hollow at bottom), personal best so far (steps), level limits (dashed, level color).
// Data from backend: points x & y from 0 to 1 (y 0: fastest, at top), lap time labels & date marks.
// Hover: date, session & lap time of nearest session.
Item {
    id: chart

    property var chartData: ({})
    readonly property var points: chartData.points || []
    readonly property real labelWidth: theme.em * 4.4
    readonly property real dateHeight: theme.em * 1.5
    readonly property real plotX: labelWidth
    readonly property real plotY: theme.em * 0.7
    readonly property real plotWidth: Math.max(width - labelWidth - theme.em * 0.7, 1)
    readonly property real plotHeight: Math.max(height - plotY - dateHeight, 1)
    property int hovered: -1

    function px(value) { return plotX + value * plotWidth }
    function py(value) { return plotY + value * plotHeight }

    onChartDataChanged: { hovered = -1; canvas.requestPaint() }
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
    onHoveredChanged: canvas.requestPaint()
    Connections {
        target: theme
        function onChanged() { canvas.requestPaint() }
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var points = chart.points
            if (points.length < 2) return
            var dash = theme.em * 0.35
            // Level limits: dashed lines
            var limits = chart.chartData.limits || []
            ctx.lineWidth = 1
            for (var l = 0; l < limits.length; l++) {
                var y = Math.round(chart.py(limits[l].y)) + 0.5
                ctx.strokeStyle = limits[l].color
                ctx.beginPath()
                for (var x = chart.plotX; x < chart.plotX + chart.plotWidth; x += dash * 2) {
                    ctx.moveTo(x, y)
                    ctx.lineTo(Math.min(x + dash, chart.plotX + chart.plotWidth), y)
                }
                ctx.stroke()
            }
            // Personal best so far: steps
            ctx.strokeStyle = theme.accent
            ctx.lineWidth = Math.max(2, theme.em * 0.14)
            ctx.beginPath()
            ctx.moveTo(chart.px(points[0].x), chart.py(points[0].pbY))
            for (var i = 1; i < points.length; i++) {
                ctx.lineTo(chart.px(points[i].x), chart.py(points[i - 1].pbY))
                ctx.lineTo(chart.px(points[i].x), chart.py(points[i].pbY))
            }
            ctx.stroke()
            // Session best laps
            var muted = Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.55)
            for (var p = 0; p < points.length; p++) {
                var point = points[p]
                var radius = theme.em * (p === chart.hovered ? 0.4 : 0.26)
                ctx.beginPath()
                ctx.arc(chart.px(point.x), chart.py(point.y), radius, 0, Math.PI * 2)
                if (point.clipped) {
                    ctx.lineWidth = 1
                    ctx.strokeStyle = muted
                    ctx.stroke()
                } else {
                    ctx.fillStyle = point.newPb ? theme.accent : muted
                    ctx.fill()
                }
            }
        }
    }

    // Lap time labels: personal best (top) & slowest shown (bottom)
    Text {
        x: 0
        width: chart.labelWidth - theme.em * 0.5
        y: chart.plotY - height / 2
        text: chart.chartData.top || ""
        color: theme.dimText
        horizontalAlignment: Text.AlignRight
        font.pointSize: theme.fontPoint * 0.85
        font.features: { "tnum": 1 }
    }
    Text {
        x: 0
        width: chart.labelWidth - theme.em * 0.5
        y: chart.plotY + chart.plotHeight - height / 2
        text: chart.chartData.bottom || ""
        color: theme.dimText
        horizontalAlignment: Text.AlignRight
        font.pointSize: theme.fontPoint * 0.85
        font.features: { "tnum": 1 }
    }
    // Date marks: first, middle & last session
    Repeater {
        model: chart.chartData.dates || []
        Text {
            required property var modelData
            y: chart.plotY + chart.plotHeight + theme.em * 0.3
            x: Math.max(chart.plotX, Math.min(chart.px(modelData.x) - width / 2, chart.width - width))
            text: modelData.text
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.8
        }
    }

    MouseArea {
        id: hoverArea
        x: chart.plotX - theme.em * 0.5
        width: chart.plotWidth + theme.em
        height: chart.height
        hoverEnabled: true
        onPositionChanged: function(mouse) {
            var points = chart.points
            var nearest = -1
            var distance = theme.em * 2
            for (var i = 0; i < points.length; i++) {
                var gap = Math.abs(chart.px(points[i].x) - (mouse.x + hoverArea.x))
                if (gap < distance) { distance = gap; nearest = i }
            }
            chart.hovered = nearest
        }
        onExited: chart.hovered = -1
    }
    ToolTip {
        parent: chart
        visible: chart.hovered >= 0 && chart.hovered < chart.points.length
        text: visible ? chart.points[chart.hovered].tip : ""
        x: visible ? Math.max(0, Math.min(chart.px(chart.points[chart.hovered].x) - width / 2, chart.width - width)) : 0
        y: visible ? Math.max(0, chart.py(chart.points[chart.hovered].y) - height - theme.em * 0.6) : 0
    }
}
