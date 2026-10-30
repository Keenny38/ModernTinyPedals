import QtQuick
import QtQuick.Controls.Basic
import NeoPedal
import "../components"

// Positions lap by lap (races): place of every car at end of each lap (class place when a class is picked),
// grid at lap 0. Other cars dimmed in their class color, player in accent color, car picked in text color.
// Hover: nearest car highlighted with its name & place. Click: pick that car.
// Lines drawn by the GPU (GpuShape), built by backend in plot pixels once the plot size settles: resize only
// scales them meanwhile, hover & pick only show other lines. Lines revealed by a clip.
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
    property int hoverLap: -1  // lap under mouse & place of the hovered car there (tooltip)
    property int hoverPlace: 0
    // Place table of the lap under the mouse, asked to the backend once per lap (not per mouse move)
    property int cachedLap: -1
    property var cachedPlaces: []
    property real reveal: 1
    readonly property bool revealed: reveal >= 1
    readonly property int picked: seriesIndex(backend.selectedEntry)
    readonly property bool highlighted: picked >= 0 || hovered >= 0
    readonly property bool drawn: active && series.length > 0 && laps > 0
    readonly property var players: {
        var found = []
        for (var i = 0; i < series.length; i++) if (series[i].player) found.push(series[i])
        return found
    }
    // Names at end of highlighted lines (car picked, player, hovered car)
    readonly property var labels: {
        var found = []
        for (var n = 0; n < series.length; n++) {
            var item = series[n]
            if ((n !== picked && n !== hovered && !item.player) || item.last.length === 0) continue
            found.push({ "lap": item.last[0], "place": item.last[1], "name": item.name,
                         "color": item.player ? theme.accent : n === picked ? theme.text : item.color })
        }
        return found
    }
    // Plot size lines were built for (sent to backend once size settles), lines scaled to plot size meanwhile
    property real builtWidth: 0
    property real builtHeight: 0
    readonly property real thinWidth: Math.max(theme.em * 0.11, 1.2)
    readonly property real thickWidth: theme.em * 0.22
    readonly property real wideWidth: theme.em * 0.26
    readonly property var lineMatrix: Qt.matrix4x4(
        builtWidth > 0 ? plotWidth / builtWidth : 1, 0, 0, plotX,
        0, builtHeight > 0 ? plotHeight / builtHeight : 1, 0, plotY,
        0, 0, 1, 0,
        0, 0, 0, 1)
    readonly property int placeStep: places > 30 ? 5 : places > 12 ? 2 : 1
    readonly property int lapStep: laps > 80 ? 10 : laps > 30 ? 5 : laps > 12 ? 2 : 1

    function px(lap) { return plotX + (laps > 0 ? lap / laps : 0) * plotWidth }
    function py(place) { return plotY + (places > 1 ? (place - 1) / (places - 1) : 0.5) * plotHeight }
    function seriesIndex(key) {
        for (var i = 0; i < series.length; i++) if (series[i].key === key) return i
        return -1
    }
    function nearest(mouseX, mouseY) {
        if (laps <= 0 || series.length === 0) return -1
        var lap = Math.round((mouseX - plotX) / plotWidth * laps)
        lap = Math.max(Math.min(lap, laps), 0)
        var best = -1, bestDistance = theme.em * 1.2, bestPlace = 0
        if (lap !== cachedLap) {  // place tables of backend: one call per lap crossed, no scan of points
            cachedPlaces = backend.placesAt(lap)
            cachedLap = lap
        }
        var atLap = cachedPlaces
        for (var i = 0; i < series.length; i++) {
            var place = atLap[i]
            if (!(place > 0)) continue
            var distance = Math.abs(py(place) - mouseY)
            if (distance < bestDistance) { bestDistance = distance; best = i; bestPlace = place }
        }
        hoverLap = best >= 0 ? lap : -1
        hoverPlace = bestPlace
        return best
    }
    function sendView() {
        if (!active || width < 1 || height < 1) return
        var lineWidth = Math.round(plotWidth), lineHeight = Math.round(plotHeight)
        backend.setChartView(lineWidth, lineHeight, thinWidth, thickWidth, wideWidth)
        builtWidth = lineWidth
        builtHeight = lineHeight
    }
    function sizeChanged() {
        if (builtWidth <= 0) Qt.callLater(sendView)  // first lines at once
        else settleTimer.restart()
    }

    onData_Changed: { hovered = -1; cachedLap = -1; cachedPlaces = []; if (active) revealAnimation.restart() }
    onActiveChanged: if (active) { sizeChanged(); revealAnimation.restart() }
    onPlotWidthChanged: sizeChanged()
    onPlotHeightChanged: sizeChanged()
    onThinWidthChanged: sizeChanged()
    onThickWidthChanged: sizeChanged()
    Component.onCompleted: sizeChanged()

    Timer {
        id: settleTimer
        interval: 150
        onTriggered: chart.sendView()
    }

    NumberAnimation {
        id: revealAnimation
        target: chart
        property: "reveal"
        from: 0
        to: 1
        duration: theme.animate ? 650 : 0  // animations off: lines drawn at once
        easing.type: Easing.OutCubic
    }

    // Legend
    Row {
        x: chart.plotX
        y: theme.em * 0.6
        spacing: theme.space6
        visible: chart.series.length > 0
        Row {
            spacing: theme.space3
            Rectangle { width: theme.em * 1.2; height: Math.round(chart.wideWidth); radius: height / 2; color: theme.accent; anchors.verticalCenter: parent.verticalCenter }
            Text { text: i18n.tr("Your car"); color: theme.dimText; font.pointSize: theme.fontSmall }
        }
        Row {
            spacing: theme.space3
            Rectangle { width: theme.em * 1.2; height: Math.round(chart.thickWidth); radius: height / 2; color: theme.text; anchors.verticalCenter: parent.verticalCenter }
            Text { text: i18n.tr("Car picked"); color: theme.dimText; font.pointSize: theme.fontSmall }
        }
    }

    // Grid: place lines, lap ticks (items follow plot size, nothing painted)
    Item {
        anchors.fill: parent
        visible: chart.drawn
        Repeater {
            model: chart.drawn ? chart.places : 0
            Item {
                required property int index
                readonly property int place: index + 1
                readonly property real gridY: Math.round(chart.py(place))
                visible: place === 1 || place % chart.placeStep === 0
                Rectangle {
                    x: chart.plotX
                    y: parent.gridY
                    width: chart.plotWidth
                    height: 1
                    color: theme.chartGrid
                }
                Text {
                    x: chart.plotX - theme.em * 0.5 - width
                    y: parent.gridY + 0.5 - height / 2
                    text: parent.place
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontCaption
                    font.features: { "tnum": 1 }
                }
            }
        }
        Repeater {
            model: chart.drawn ? Math.floor(chart.laps / chart.lapStep) + 1 : 0
            Text {
                required property int index
                readonly property int lap: index * chart.lapStep
                x: chart.px(lap) - width / 2
                y: chart.plotY + chart.plotHeight + theme.em * 0.5
                text: lap === 0 ? i18n.tr("Grid") : lap
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontCaption
                font.features: { "tnum": 1 }
            }
        }
    }

    // Lines: rendered in a multisampled layer while shown (smooth edges, window itself without MSAA)
    Item {
        id: lineLayer
        objectName: "positionsLines"
        width: chart.width
        height: chart.height
        visible: chart.drawn
        layer.enabled: chart.drawn && pageState.active  // texture released while page hidden
        layer.samples: 4
        // Drawn up to the lap revealed (whole width once revealed: names at line ends)
        Item {
            id: revealClip
            width: chart.revealed ? chart.width : Math.max(0, chart.px(chart.laps * chart.reveal))
            height: chart.height
            clip: !chart.revealed
            Item {
                transform: Matrix4x4 { matrix: chart.lineMatrix }  // one transform for every line
                // Other cars, dimmed more while a car is picked or hovered (hovered one covered by its line)
                Repeater {
                    model: chart.series
                    GpuShape {
                        required property var modelData
                        required property int index
                        visible: index !== chart.picked && !modelData.player
                        key: modelData.thin
                        color: modelData.color
                        opacity: chart.highlighted ? 0.28 : 0.55
                    }
                }
                GpuShape {  // car picked
                    readonly property bool shown: chart.picked >= 0 && !chart.series[chart.picked].player
                    visible: shown
                    key: shown ? chart.series[chart.picked].thick : ""
                    color: theme.text
                }
                Repeater {  // player
                    model: chart.players
                    GpuShape {
                        required property var modelData
                        key: modelData.wide
                        color: theme.accent
                    }
                }
                GpuShape {  // hovered car
                    readonly property bool shown: chart.hovered >= 0 && chart.hovered !== chart.picked
                                                  && !chart.series[chart.hovered].player
                    visible: shown
                    key: shown ? chart.series[chart.hovered].thick : ""
                    color: shown ? chart.series[chart.hovered].color : "transparent"
                }
            }
        }
    }

    // Names at end of highlighted lines, once lines are drawn
    Repeater {
        model: chart.drawn && chart.revealed ? chart.labels : []
        Text {
            required property var modelData
            x: chart.px(modelData.lap) + theme.em * 0.5
            y: chart.py(modelData.place) - height / 2
            width: Math.min(implicitWidth, Math.max(chart.width - x, theme.em * 2))  // cut at the chart edge
            elide: Text.ElideRight
            text: "P" + modelData.place + "  " + modelData.name
            textFormat: Text.PlainText
            color: modelData.color
            font.pointSize: theme.fontSmall
            font.weight: Font.DemiBold
        }
    }

    // Hovered car: number, name & place at lap under mouse (grid at lap 0), tooltip of the app look
    TpToolTip {
        id: hoverTip
        readonly property var item: chart.hovered >= 0 ? chart.series[chart.hovered] : null
        parent: chart
        visible: item !== null && area.containsMouse
        text: item === null ? ""
            : (item.number !== "" ? "#" + item.number + "  " : "") + item.name + "\n"
              + (chart.hoverLap === 0 ? i18n.tr("Grid") : i18n.tr("Lap") + " " + chart.hoverLap) + ": P" + chart.hoverPlace
        x: Math.max(0, Math.min(area.mouseX + theme.em, chart.width - width - theme.space4))
        y: Math.max(area.mouseY - height - theme.space4, 0)
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

    TpStateView {
        anchors.centerIn: parent
        empty: chart.series.length === 0
        compact: true
        glyph: ""  // chart
        title: i18n.tr("No lap completed")
    }
    Accessible.role: Accessible.Graphic
    Accessible.name: i18n.tr("Positions")
}
