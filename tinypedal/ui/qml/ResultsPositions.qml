import QtQuick
import QtQuick.Controls.Basic

// Positions lap by lap (races): place of every car at end of each lap (class place when a class is picked),
// grid at lap 0. Other cars dimmed in their class color, player in accent color, car picked in text color.
// Hover: nearest car highlighted with its name & place. Click: pick that car.
Item {
    id: chart

    property bool active: true  // tab shown: drawn only then
    readonly property var data_: backend.positions
    readonly property var series: data_.series || []
    readonly property int laps: data_.laps || 0
    readonly property int places: data_.places || 0
    readonly property real labelWidth: theme.em * 2.4
    readonly property real nameWidth: theme.em * 9
    readonly property real plotX: labelWidth
    readonly property real plotY: theme.em * 2.4
    readonly property real plotWidth: Math.max(width - plotX - nameWidth, 1)
    readonly property real plotHeight: Math.max(height - plotY - theme.em * 2.0, 1)
    property int hovered: -1  // series index under mouse
    property real reveal: 1

    function px(lap) { return plotX + (laps > 0 ? lap / laps : 0) * plotWidth }
    function py(place) { return plotY + (places > 1 ? (place - 1) / (places - 1) : 0.5) * plotHeight }
    function seriesIndex(key) {
        for (var i = 0; i < series.length; i++) if (series[i].key === key) return i
        return -1
    }
    // Place of series at lap (last known before), 0 if none
    function placeAt(points, lap) {
        var place = 0
        for (var i = 0; i < points.length && points[i][0] <= lap; i++) place = points[i][1]
        return place
    }
    function nearest(mouseX, mouseY) {
        if (laps <= 0 || series.length === 0) return -1
        var lap = Math.round((mouseX - plotX) / plotWidth * laps)
        lap = Math.max(Math.min(lap, laps), 0)
        var best = -1, bestDistance = theme.em * 1.2
        for (var i = 0; i < series.length; i++) {
            var place = placeAt(series[i].points, lap)
            if (place <= 0) continue
            var distance = Math.abs(py(place) - mouseY)
            if (distance < bestDistance) { bestDistance = distance; best = i }
        }
        return best
    }

    onData_Changed: { hovered = -1; if (active) revealAnimation.restart() }
    onActiveChanged: if (active) revealAnimation.restart()
    onRevealChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
    onHoveredChanged: canvas.requestPaint()
    Connections {
        target: backend
        function onDriverChanged() { canvas.requestPaint() }
    }
    readonly property var paintColors: [theme.accent, theme.text, theme.dark, theme.border]
    onPaintColorsChanged: canvas.requestPaint()

    NumberAnimation {
        id: revealAnimation
        target: chart
        property: "reveal"
        from: 0
        to: 1
        duration: 650
        easing.type: Easing.OutCubic
    }

    // Legend
    Row {
        x: chart.plotX
        y: theme.em * 0.6
        spacing: theme.em * 1.2
        visible: chart.series.length > 0
        Row {
            spacing: theme.em * 0.4
            Rectangle { width: theme.em * 1.2; height: 3; radius: 1.5; color: theme.accent; anchors.verticalCenter: parent.verticalCenter }
            Text { text: i18n.tr("Your car"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.85 }
        }
        Row {
            spacing: theme.em * 0.4
            Rectangle { width: theme.em * 1.2; height: 3; radius: 1.5; color: theme.text; anchors.verticalCenter: parent.verticalCenter }
            Text { text: i18n.tr("Car picked"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.85 }
        }
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        visible: chart.active
        renderStrategy: Canvas.Cooperative
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var series = chart.series
            if (!chart.active || series.length === 0 || chart.laps <= 0) return
            var x0 = chart.plotX, x1 = chart.plotX + chart.plotWidth
            var y0 = chart.plotY, y1 = chart.plotY + chart.plotHeight
            var lastLap = chart.laps * chart.reveal
            // Grid: place lines, lap ticks
            var placeStep = chart.places > 30 ? 5 : chart.places > 12 ? 2 : 1
            var lapStep = chart.laps > 80 ? 10 : chart.laps > 30 ? 5 : chart.laps > 12 ? 2 : 1
            ctx.lineWidth = 1
            ctx.strokeStyle = Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.06 : 0.08)
            ctx.fillStyle = theme.dimText
            ctx.font = Math.round(theme.em * 0.78) + "px sans-serif"
            ctx.textAlign = "right"
            ctx.textBaseline = "middle"
            ctx.beginPath()
            for (var place = 1; place <= chart.places; place++) {
                if (place !== 1 && place % placeStep !== 0) continue
                var gy = Math.round(chart.py(place)) + 0.5
                ctx.moveTo(x0, gy)
                ctx.lineTo(x1, gy)
                ctx.fillText(place, x0 - theme.em * 0.5, gy)
            }
            ctx.stroke()
            ctx.textAlign = "center"
            ctx.textBaseline = "top"
            for (var lap = 0; lap <= chart.laps; lap += lapStep) {
                ctx.fillText(lap === 0 ? i18n.tr("Grid") : lap, chart.px(lap), y1 + theme.em * 0.5)
            }
            // Lines: others first, then car picked, player & hovered on top
            var picked = chart.seriesIndex(backend.selectedEntry)
            function draw(index, width, color, alpha) {
                var points = series[index].points
                if (points.length === 0) return
                ctx.globalAlpha = alpha
                ctx.strokeStyle = color
                ctx.lineWidth = width
                ctx.lineJoin = "round"
                ctx.beginPath()
                var started = false
                for (var i = 0; i < points.length; i++) {
                    var lapNumber = points[i][0]
                    if (lapNumber > lastLap) {
                        if (i > 0 && started) {  // part of segment revealed
                            var share = (lastLap - points[i - 1][0]) / Math.max(lapNumber - points[i - 1][0], 1e-6)
                            var yPrevious = chart.py(points[i - 1][1])
                            ctx.lineTo(chart.px(lastLap), yPrevious + (chart.py(points[i][1]) - yPrevious) * share)
                        }
                        break
                    }
                    var x = chart.px(lapNumber), y = chart.py(points[i][1])
                    if (!started) { ctx.moveTo(x, y); started = true }
                    else ctx.lineTo(x, y)
                }
                ctx.stroke()
                ctx.globalAlpha = 1
            }
            var highlighted = picked >= 0 || chart.hovered >= 0
            for (var s = 0; s < series.length; s++) {
                if (s === picked || s === chart.hovered || series[s].player) continue
                draw(s, Math.max(theme.em * 0.11, 1.2), series[s].color, highlighted ? 0.28 : 0.55)
            }
            if (picked >= 0 && !series[picked].player) draw(picked, theme.em * 0.22, theme.text, 1)
            for (var p = 0; p < series.length; p++) {
                if (series[p].player) draw(p, theme.em * 0.26, theme.accent, 1)
            }
            if (chart.hovered >= 0 && chart.hovered !== picked && !series[chart.hovered].player)
                draw(chart.hovered, theme.em * 0.22, series[chart.hovered].color, 1)
            // Names at end of highlighted lines
            if (chart.reveal < 1) return
            ctx.textAlign = "left"
            ctx.textBaseline = "middle"
            ctx.font = "600 " + Math.round(theme.em * 0.8) + "px sans-serif"
            var labelled = []
            for (var n = 0; n < series.length; n++) {
                if (n === picked || n === chart.hovered || series[n].player) labelled.push(n)
            }
            for (var l = 0; l < labelled.length; l++) {
                var item = series[labelled[l]]
                if (item.points.length === 0) continue
                var last = item.points[item.points.length - 1]
                ctx.fillStyle = item.player ? theme.accent : labelled[l] === picked ? theme.text : item.color
                var label = "P" + last[1] + "  " + item.name
                ctx.fillText(label, chart.px(last[0]) + theme.em * 0.5, chart.py(last[1]))
            }
        }
    }

    // Hovered car: name, number & place at lap under mouse
    Rectangle {
        id: hoverTip
        visible: chart.hovered >= 0 && area.containsMouse
        readonly property var item: chart.hovered >= 0 ? chart.series[chart.hovered] : null
        x: Math.min(area.mouseX + theme.em, chart.width - width - theme.em * 0.5)
        y: Math.max(area.mouseY - height - theme.em * 0.6, 0)
        width: tipText.implicitWidth + theme.em * 1.2
        height: tipText.implicitHeight + theme.em * 0.6
        radius: theme.em * 0.4
        color: theme.raised
        border.width: 1
        border.color: theme.border
        Text {
            id: tipText
            anchors.centerIn: parent
            text: hoverTip.item ? (hoverTip.item.number !== "" ? "#" + hoverTip.item.number + "  " : "") + hoverTip.item.name : ""
            color: theme.text
            font.weight: Font.DemiBold
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: chart.hovered >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
        onPositionChanged: function(mouse) { chart.hovered = chart.nearest(mouse.x, mouse.y) }
        onExited: chart.hovered = -1
        onClicked: if (chart.hovered >= 0) backend.selectEntry(chart.series[chart.hovered].key)
    }

    Text {
        anchors.centerIn: parent
        visible: chart.series.length === 0
        text: i18n.tr("No lap completed")
        color: theme.dimText
    }
}
