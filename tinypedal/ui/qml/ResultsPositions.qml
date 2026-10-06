import QtQuick
import QtQuick.Controls.Basic

// Positions lap by lap (races): place of every car at end of each lap (class place when a class is picked),
// grid at lap 0. Other cars dimmed in their class color, player in accent color, car picked in text color.
// Hover: nearest car highlighted with its name & place. Click: pick that car.
// Layers: grid, other cars (painted once per data / size / theme / car picked, one canvas per dim level so
// hovering never repaints them), highlighted cars (small canvas painted on hover). Lines revealed by a clip.
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
    readonly property bool revealed: reveal >= 1
    readonly property int picked: seriesIndex(backend.selectedEntry)
    readonly property bool highlighted: picked >= 0 || hovered >= 0
    // Place of each series at each lap (last known before, 0 if none): no scan of points per mouse move
    readonly property var placeTable: buildPlaceTable(series, laps)

    function px(lap) { return plotX + (laps > 0 ? lap / laps : 0) * plotWidth }
    function py(place) { return plotY + (places > 1 ? (place - 1) / (places - 1) : 0.5) * plotHeight }
    function seriesIndex(key) {
        for (var i = 0; i < series.length; i++) if (series[i].key === key) return i
        return -1
    }
    function buildPlaceTable(rows, lapCount) {
        var table = []
        if (lapCount < 0) return table
        for (var s = 0; s < rows.length; s++) {
            var points = rows[s].points
            var places = new Int32Array(lapCount + 1)
            var place = 0, next = 0
            for (var lap = 0; lap <= lapCount; lap++) {
                while (next < points.length && points[next][0] <= lap) place = points[next++][1]
                places[lap] = place
            }
            table.push(places)
        }
        return table
    }
    function nearest(mouseX, mouseY) {
        if (laps <= 0 || series.length === 0) return -1
        var lap = Math.round((mouseX - plotX) / plotWidth * laps)
        lap = Math.max(Math.min(lap, laps), 0)
        var best = -1, bestDistance = theme.em * 1.2
        var table = placeTable
        for (var i = 0; i < table.length; i++) {
            var place = table[i][lap]
            if (place <= 0) continue
            var distance = Math.abs(py(place) - mouseY)
            if (distance < bestDistance) { bestDistance = distance; best = i }
        }
        return best
    }
    // Other cars layer of current dim level painted if out of date (other level painted when needed)
    function paintDim() {
        var canvas = highlighted ? dimHigh : dimLow
        if (!canvas.fresh) canvas.requestPaint()
    }
    function paintLines() {
        dimLow.fresh = false
        dimHigh.fresh = false
        paintDim()
        topCanvas.requestPaint()
    }
    function paintAll() {
        gridCanvas.requestPaint()
        paintLines()
    }

    onData_Changed: { hovered = -1; paintAll(); if (active) revealAnimation.restart() }
    onActiveChanged: { paintAll(); if (active) revealAnimation.restart() }
    onRevealedChanged: topCanvas.requestPaint()  // names shown once lines are drawn
    onWidthChanged: paintAll()
    onHeightChanged: paintAll()
    onHoveredChanged: topCanvas.requestPaint()
    onHighlightedChanged: paintDim()
    onPickedChanged: paintLines()
    Connections {
        target: backend
        function onDriverChanged() { chart.paintLines() }
    }
    readonly property var paintColors: [theme.accent, theme.text, theme.dark, theme.border]
    onPaintColorsChanged: paintAll()

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

    // Line of series (whole line: the reveal clip hides the part not drawn yet)
    function drawLine(ctx, index, lineWidth, color, alpha) {
        var points = series[index].points
        if (points.length === 0) return
        ctx.globalAlpha = alpha
        ctx.strokeStyle = color
        ctx.lineWidth = lineWidth
        ctx.lineJoin = "round"
        ctx.beginPath()
        ctx.moveTo(px(points[0][0]), py(points[0][1]))
        for (var i = 1; i < points.length; i++)
            ctx.lineTo(px(points[i][0]), py(points[i][1]))
        ctx.stroke()
        ctx.globalAlpha = 1
    }
    // Other cars (not picked, not player) dimmed, hovered one included (covered by its highlighted line)
    function paintOthers(ctx, alpha) {
        var picked = chart.picked
        var width = Math.max(theme.em * 0.11, 1.2)
        for (var s = 0; s < series.length; s++) {
            if (s === picked || series[s].player) continue
            drawLine(ctx, s, width, series[s].color, alpha)
        }
    }

    // Grid: place lines, lap ticks
    Canvas {
        id: gridCanvas
        anchors.fill: parent
        visible: chart.active
        renderStrategy: Canvas.Cooperative
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            if (!chart.active || chart.series.length === 0 || chart.laps <= 0) return
            var x0 = chart.plotX, x1 = chart.plotX + chart.plotWidth
            var y1 = chart.plotY + chart.plotHeight
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
        }
    }

    // Lines drawn up to the lap revealed (whole width once revealed: names at line ends)
    Item {
        id: revealClip
        visible: chart.active
        width: chart.revealed ? chart.width : Math.max(0, chart.px(chart.laps * chart.reveal))
        height: chart.height
        clip: !chart.revealed

        // Other cars, one canvas per dim level: the level needed is painted (canvases also paint themselves
        // when resized: the level not needed stays empty, out of date), the other one shown until it is ready
        Canvas {
            id: dimLow  // nothing highlighted
            objectName: "positionsDimLow"
            property int paints: 0  // times painted (tests)
            property bool fresh: false
            width: chart.width
            height: chart.height
            visible: chart.highlighted ? !dimHigh.fresh : fresh || !dimHigh.fresh
            renderStrategy: Canvas.Cooperative
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                fresh = !chart.highlighted
                if (!fresh || !chart.active || chart.series.length === 0 || chart.laps <= 0) return
                paints++
                chart.paintOthers(ctx, 0.55)
            }
        }
        Canvas {
            id: dimHigh  // car picked or hovered
            objectName: "positionsDimHigh"
            property int paints: 0  // times painted (tests)
            property bool fresh: false
            width: chart.width
            height: chart.height
            visible: !dimLow.visible
            renderStrategy: Canvas.Cooperative
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                fresh = chart.highlighted
                if (!fresh || !chart.active || chart.series.length === 0 || chart.laps <= 0) return
                paints++
                chart.paintOthers(ctx, 0.28)
            }
        }
        // Car picked, player & hovered on top, names at end of their lines
        Canvas {
            id: topCanvas
            objectName: "positionsTop"
            property int paints: 0  // times painted (tests)
            width: chart.width
            height: chart.height
            renderStrategy: Canvas.Cooperative
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                paints++
                var series = chart.series
                if (!chart.active || series.length === 0 || chart.laps <= 0) return
                var picked = chart.picked
                var hovered = chart.hovered
                if (picked >= 0 && !series[picked].player) chart.drawLine(ctx, picked, theme.em * 0.22, theme.text, 1)
                for (var p = 0; p < series.length; p++) {
                    if (series[p].player) chart.drawLine(ctx, p, theme.em * 0.26, theme.accent, 1)
                }
                if (hovered >= 0 && hovered !== picked && !series[hovered].player)
                    chart.drawLine(ctx, hovered, theme.em * 0.22, series[hovered].color, 1)
                if (!chart.revealed) return
                ctx.textAlign = "left"
                ctx.textBaseline = "middle"
                ctx.font = "600 " + Math.round(theme.em * 0.8) + "px sans-serif"
                for (var n = 0; n < series.length; n++) {
                    if (n !== picked && n !== hovered && !series[n].player) continue
                    var item = series[n]
                    if (item.points.length === 0) continue
                    var last = item.points[item.points.length - 1]
                    ctx.fillStyle = item.player ? theme.accent : n === picked ? theme.text : item.color
                    ctx.fillText("P" + last[1] + "  " + item.name, chart.px(last[0]) + theme.em * 0.5, chart.py(last[1]))
                }
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
