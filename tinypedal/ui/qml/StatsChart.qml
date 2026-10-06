import QtQuick
import QtQuick.Controls.Basic

// Personal best progression: best lap of each session (dots, new personal best in accent color, slow
// sessions clipped hollow at bottom), personal best so far (steps over a soft area), level limits (dashed,
// level color & letter), round lap time grid lines. Data from backend: points x & y from 0 to 1 (y 0: fastest,
// at top), grid ticks, date marks. Drawn from left to right when data changes.
// Hover: guide line, date, session & lap time of nearest session.
Item {
    id: chart

    property var chartData: ({})
    readonly property var points: chartData.points || []
    readonly property real labelWidth: theme.em * 4.6
    readonly property real dateHeight: theme.em * 1.5
    readonly property real plotX: labelWidth
    readonly property real plotY: theme.em * 0.7
    readonly property real plotWidth: Math.max(width - labelWidth - theme.em * 1.6, 1)
    readonly property real plotHeight: Math.max(height - plotY - dateHeight, 1)
    property int hovered: -1
    property real reveal: 1  // share of chart drawn (animated when data changes)

    function px(value) { return plotX + value * plotWidth }
    function py(value) { return plotY + value * plotHeight }

    // Session nearest to x (pixels), -1 if none within 2 em: points evenly spaced from 0 to 1 (session order),
    // so the nearest one is found from x alone (no scan per mouse move); midway: the earlier one
    function nearest(mouseX) {
        var count = points.length
        if (count === 0) return -1
        var index = count > 1 ? Math.ceil((mouseX - plotX) / plotWidth * (count - 1) - 0.5) : 0
        index = Math.max(0, Math.min(index, count - 1))
        return Math.abs(px(points[index].x) - mouseX) < theme.em * 2 ? index : -1
    }
    function paintAll() {
        gridCanvas.requestPaint()
        dataCanvas.requestPaint()
        hoverCanvas.requestPaint()
    }

    onChartDataChanged: {
        hovered = -1
        paintAll()
        revealAnimation.restart()
    }
    // Layers: grid & limits, data (painted once per data / size / theme, revealed by a clip), hovered session.
    // Mouse moves & reveal frames paint nothing but the small hover layer.
    onWidthChanged: paintAll()
    onHeightChanged: paintAll()
    onHoveredChanged: hoverCanvas.requestPaint()
    // Colors painted: canvas painted again when light / dark theme switches (theme copy has no changed signal)
    readonly property var paintColors: [theme.accent, theme.text, theme.dark, theme.border]
    onPaintColorsChanged: paintAll()

    NumberAnimation {
        id: revealAnimation
        target: chart
        property: "reveal"
        from: 0
        to: 1
        duration: 520
        easing.type: Easing.OutCubic
    }

    // Grid: round lap times, level limits (dashed)
    Canvas {
        id: gridCanvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var points = chart.points
            if (points.length < 2) return
            var x0 = chart.plotX, span = chart.plotWidth
            var ticks = chart.chartData.ticks || []
            ctx.lineWidth = 1
            ctx.strokeStyle = Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.07 : 0.09)
            ctx.beginPath()
            for (var t = 0; t < ticks.length; t++) {
                var ty = Math.round(chart.py(ticks[t].y)) + 0.5
                ctx.moveTo(x0, ty)
                ctx.lineTo(x0 + span, ty)
            }
            ctx.stroke()
            var dash = theme.em * 0.35
            var limits = chart.chartData.limits || []
            for (var l = 0; l < limits.length; l++) {
                var y = Math.round(chart.py(limits[l].y)) + 0.5
                ctx.strokeStyle = limits[l].color
                ctx.globalAlpha = 0.75
                ctx.beginPath()
                for (var x = x0; x < x0 + span; x += dash * 2) {
                    ctx.moveTo(x, y)
                    ctx.lineTo(Math.min(x + dash, x0 + span), y)
                }
                ctx.stroke()
            }
            ctx.globalAlpha = 1
        }
    }

    // Drawn part (left to right while data changes): clip over layers painted in full
    Item {
        id: revealClip
        width: Math.max(0, chart.plotX + chart.plotWidth * chart.reveal + theme.em * 0.5)
        height: chart.height
        clip: true

        // Personal best so far (steps over a soft area), session best laps
        Canvas {
            id: dataCanvas
            objectName: "statsData"
            property int paints: 0  // times painted (tests)
            width: chart.width
            height: chart.height
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                paints++
                var points = chart.points
                if (points.length < 2) return
                var y1 = chart.plotY + chart.plotHeight
                var accent = theme.accent
                ctx.beginPath()
                ctx.moveTo(chart.px(points[0].x), chart.py(points[0].pbY))
                for (var i = 1; i < points.length; i++) {
                    ctx.lineTo(chart.px(points[i].x), chart.py(points[i - 1].pbY))
                    ctx.lineTo(chart.px(points[i].x), chart.py(points[i].pbY))
                }
                ctx.lineTo(chart.px(points[points.length - 1].x), y1)
                ctx.lineTo(chart.px(points[0].x), y1)
                ctx.closePath()
                var gradient = ctx.createLinearGradient(0, chart.plotY, 0, y1)
                gradient.addColorStop(0, Qt.rgba(accent.r, accent.g, accent.b, theme.dark ? 0.24 : 0.16))
                gradient.addColorStop(1, Qt.rgba(accent.r, accent.g, accent.b, 0))
                ctx.fillStyle = gradient
                ctx.fill()
                ctx.strokeStyle = accent
                ctx.lineWidth = Math.max(2, theme.em * 0.14)
                ctx.lineJoin = "round"
                ctx.beginPath()
                ctx.moveTo(chart.px(points[0].x), chart.py(points[0].pbY))
                for (var s = 1; s < points.length; s++) {
                    ctx.lineTo(chart.px(points[s].x), chart.py(points[s - 1].pbY))
                    ctx.lineTo(chart.px(points[s].x), chart.py(points[s].pbY))
                }
                ctx.stroke()
                var muted = Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.5)
                for (var p = 0; p < points.length; p++)
                    chart.paintDot(ctx, points[p], false, accent, muted)
            }
        }

        // Hovered session: guide line & bigger dot
        Canvas {
            id: hoverCanvas
            objectName: "statsHover"
            property int paints: 0  // times painted (tests)
            width: chart.width
            height: chart.height
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                paints++
                var points = chart.points
                if (points.length < 2 || chart.hovered < 0 || chart.hovered >= points.length) return
                var point = points[chart.hovered]
                var hx = Math.round(chart.px(point.x)) + 0.5
                ctx.strokeStyle = Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.35)
                ctx.lineWidth = 1
                ctx.beginPath()
                ctx.moveTo(hx, chart.plotY)
                ctx.lineTo(hx, chart.plotY + chart.plotHeight)
                ctx.stroke()
                chart.paintDot(ctx, point, true, theme.accent, Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.5))
            }
        }
    }

    function paintDot(ctx, point, hovered, accent, muted) {
        var radius = theme.em * (hovered ? 0.42 : point.newPb ? 0.3 : 0.24)
        var cx = px(point.x), cy = py(point.y)
        ctx.beginPath()
        ctx.arc(cx, cy, radius, 0, Math.PI * 2)
        if (point.clipped) {
            ctx.lineWidth = 1.2
            ctx.strokeStyle = muted
            ctx.stroke()
        } else if (point.newPb) {
            ctx.fillStyle = accent
            ctx.fill()
            ctx.lineWidth = Math.max(1.5, theme.em * 0.1)
            ctx.strokeStyle = theme.base
            ctx.stroke()
        } else {
            ctx.fillStyle = hovered ? theme.text : muted
            ctx.fill()
        }
    }

    // Lap time labels: grid lines, personal best (accent)
    Repeater {
        model: chart.chartData.ticks || []
        Text {
            required property var modelData
            visible: Math.abs(chart.py(modelData.y) - chart.py(chart.chartData.pbY || 0)) > theme.em * 1.1
            x: 0
            width: chart.labelWidth - theme.em * 0.5
            y: chart.py(modelData.y) - height / 2
            text: modelData.text
            color: theme.dimText
            horizontalAlignment: Text.AlignRight
            font.pointSize: theme.fontPoint * 0.8
            font.features: { "tnum": 1 }
        }
    }
    Text {
        visible: chart.points.length >= 2
        x: 0
        width: chart.labelWidth - theme.em * 0.5
        y: chart.py(chart.chartData.pbY || 0) - height / 2
        text: chart.chartData.top || ""
        color: theme.accent
        horizontalAlignment: Text.AlignRight
        font.pointSize: theme.fontPoint * 0.85
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
    }
    // Level of each limit line: letter at its right end
    Repeater {
        model: chart.chartData.limits || []
        Rectangle {
            required property var modelData
            x: chart.plotX + chart.plotWidth + theme.em * 0.35
            y: chart.py(modelData.y) - height / 2
            width: theme.em * 1.05
            height: width
            radius: width / 2
            color: modelData.color
            ToolTip.visible: limitHover.hovered
            ToolTip.text: modelData.name
            ToolTip.delay: 400
            HoverHandler { id: limitHover }
            Text {
                anchors.centerIn: parent
                text: modelData.letter || ""
                color: "white"
                font.pointSize: theme.fontPoint * 0.62
                font.weight: Font.Bold
            }
        }
    }
    // Date marks: first, middle & last session
    Repeater {
        model: chart.chartData.dates || []
        Text {
            required property var modelData
            y: chart.plotY + chart.plotHeight + theme.em * 0.35
            x: Math.max(chart.plotX, Math.min(chart.px(modelData.x) - width / 2, chart.plotX + chart.plotWidth - width))
            text: modelData.text
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.8
            font.features: { "tnum": 1 }
        }
    }

    MouseArea {
        id: hoverArea
        x: chart.plotX - theme.em * 0.5
        width: chart.plotWidth + theme.em
        height: chart.height
        hoverEnabled: true
        onPositionChanged: function(mouse) { chart.hovered = chart.nearest(mouse.x + hoverArea.x) }
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
