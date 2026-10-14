import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator strategy: race laps left to right, one block per stint (one color per driver when
// drivers take turns), pit lap above each stop (tyre changes in tyre color, labels never overlap),
// safety car & rain bands, fuel in the tank below, details of stint or stop under the mouse, summary
Card {
    id: card
    property var timeline: ({})
    property var levels: []  // [position, fraction of tank]
    property var summary: ({})
    readonly property bool ready: timeline.ready === true
    readonly property real pad: theme.em * 0.8
    readonly property real labelHeight: metrics.height
    readonly property real barHeight: Math.round(theme.em * 1.6)
    readonly property color tyreColor: theme.seriesTyre

    implicitHeight: column.implicitHeight + pad * 2
    Layout.fillWidth: true

    FontMetrics { id: metrics }

    ColumnLayout {
        id: column
        x: card.pad
        y: card.pad
        width: card.width - card.pad * 2
        spacing: theme.em * 0.4

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Icon { glyph: ""; color: theme.accent; size: theme.em * 0.95 }  // flag
            Text { text: i18n.tr("Strategy"); color: theme.text; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Repeater {  // legend (items kept when the plan changes: model is the count)
                model: card.ready ? card.timeline.bands.length : 0
                Row {
                    id: legendItem
                    required property int index
                    readonly property var band: card.timeline.bands[index] || ({})
                    spacing: theme.em * 0.3
                    Rectangle {
                        width: theme.em * 0.8; height: theme.em * 0.5; radius: 2
                        color: legendItem.band.color || "transparent"; opacity: 0.6
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text { text: legendItem.band.name || ""; color: theme.dimText; font.pointSize: theme.fontSmall }
                }
            }
            Row {
                visible: card.ready && card.timeline.stops.some(function(stop) { return stop.tyres })
                spacing: theme.em * 0.3
                Rectangle {
                    width: 2; height: theme.em * 0.8; color: card.tyreColor
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text { text: i18n.tr("Tyres"); color: theme.dimText; font.pointSize: theme.fontSmall }
            }
        }

        // Timeline
        Item {
            id: area
            Layout.fillWidth: true
            implicitHeight: card.labelHeight + 6 + card.barHeight + 6 + card.labelHeight
            readonly property real edge: metrics.advanceWidth(String(card.ready ? card.timeline.last : 0)) / 2 + 2
            readonly property real barWidth: Math.max(width - edge * 2, 1)
            readonly property real barTop: card.labelHeight + 6
            readonly property int total: card.ready ? card.timeline.last - card.timeline.first : 0
            readonly property var labels: stopLabels(card.ready ? card.timeline.stops : [], barWidth)
            readonly property var ticks: {
                if (!card.ready || total <= 0)
                    return []
                var step = Math.max(1, Math.ceil(total / Math.max(barWidth / (metrics.advanceWidth("000") * 2), 1)))
                var list = []
                for (var lap = 0; lap <= total; lap += step)
                    list.push(lap / total)
                return list
            }

            function xOf(position) {
                return edge + position * barWidth
            }
            // Stop labels: "Lap 12", or "12" when the full one does not fit, none when even that does not
            function stopLabels(stops, barWidth) {
                var end = -1e9
                var list = []
                for (var index = 0; index < stops.length; index++) {
                    var x = edge + stops[index].pos * barWidth
                    var texts = [i18n.tr("Lap") + " " + stops[index].lap, String(stops[index].lap)]
                    for (var t = 0; t < texts.length; t++) {
                        var labelWidth = metrics.advanceWidth(texts[t]) + 6
                        var labelX = Math.min(Math.max(x - labelWidth / 2, 0), width - labelWidth)
                        if (labelX >= end) {
                            list.push({ x: labelX, width: labelWidth, text: texts[t], tyres: stops[index].tyres })
                            end = labelX + labelWidth
                            break
                        }
                    }
                }
                return list
            }
            function tipAt(mouseX) {
                if (!card.ready)
                    return ""
                var position = (mouseX - edge) / barWidth
                var nearPixels = 5
                var stops = card.timeline.stops
                for (var index = 0; index < stops.length; index++)
                    if (Math.abs(stops[index].pos - position) * barWidth <= nearPixels)
                        return stops[index].tip
                var stints = card.timeline.stints
                for (index = 0; index < stints.length; index++)
                    if (position >= stints[index].start && position <= stints[index].end)
                        return stints[index].tip
                return ""
            }

            Text {  // nothing to plan yet, or plan impossible
                anchors.centerIn: parent
                visible: !card.ready
                text: card.summary.warning ? card.summary.text : i18n.tr("Enter lap time, consumption and race length")
                color: card.summary.warning ? theme.loss : theme.dimText
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
            Rectangle {  // empty track
                visible: !card.ready
                x: area.edge
                y: area.barTop
                width: area.barWidth
                height: card.barHeight
                radius: theme.radiusSm
                color: "transparent"
                border.width: 1
                border.color: theme.border
                opacity: 0.6
            }

            // Safety car & rain laps: bands behind the stints. Bands, stints, stops & labels kept when the plan
            // changes (model is the count): blocks & stop lines slide to their new place
            Repeater {
                model: card.ready ? card.timeline.bands.length : 0
                Rectangle {
                    required property int index
                    readonly property var band: card.timeline.bands[index] || ({})
                    x: area.xOf(band.start || 0)
                    y: area.barTop - 3
                    width: Math.max(area.xOf(band.end || 0) - x, 2)
                    height: card.barHeight + 6
                    radius: 3
                    color: band.color || "transparent"
                    opacity: 0.45
                }
            }
            // Stints: blocks between stops, alternating shade (driver color when drivers take turns)
            Repeater {
                model: card.ready ? card.timeline.stints.length : 0
                Rectangle {
                    id: block
                    required property int index
                    readonly property var stint: card.timeline.stints[index] || ({})
                    readonly property int count: card.timeline.stints.length
                    x: area.xOf(stint.start || 0) + (index ? 1 : 0)
                    y: area.barTop
                    width: Math.max(area.xOf(stint.end || 0) - area.xOf(stint.start || 0) - (index ? 1 : 0)
                                    - (index < count - 1 ? 1 : 0), 1)
                    height: card.barHeight
                    radius: Math.min(height / 2, theme.em * 0.4)
                    color: stint.color ? stint.color : theme.accentFill
                    opacity: stint.color ? 0.88 : (index % 2 ? 0.58 : 0.9)
                    Behavior on x { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                    Behavior on width { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                    Text {
                        anchors.centerIn: parent
                        visible: block.width > implicitWidth + 8
                        text: block.stint.laps !== undefined ? block.stint.laps : ""
                        color: "white"
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontLabel
                        font.features: { "tnum": 1 }
                    }
                }
            }
            // Stops: line from pit lap label to the bar
            Repeater {
                model: card.ready ? card.timeline.stops.length : 0
                Rectangle {
                    required property int index
                    readonly property var mark: card.timeline.stops[index] || ({})
                    x: Math.round(area.xOf(mark.pos || 0))
                    y: card.labelHeight + 1
                    width: mark.tyres ? 2 : 1
                    height: area.barTop - y + card.barHeight
                    color: mark.tyres ? card.tyreColor : theme.text
                    opacity: 0.85
                    Behavior on x { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                }
            }
            Repeater {
                model: area.labels.length
                Text {
                    required property int index
                    readonly property var label: area.labels[index] || ({})
                    x: label.x || 0
                    width: label.width || 0
                    height: card.labelHeight
                    text: label.text || ""
                    color: label.tyres ? card.tyreColor : theme.text
                    horizontalAlignment: Text.AlignHCenter
                    font.features: { "tnum": 1 }
                }
            }
            // Lap ticks below the bar, first & last lap
            Repeater {
                model: area.ticks
                Rectangle {
                    required property var modelData
                    x: area.xOf(modelData)
                    y: area.barTop + card.barHeight + 2
                    width: 1
                    height: 3
                    color: theme.dimText
                }
            }
            Text {
                visible: card.ready
                x: Math.max(area.xOf(0) - implicitWidth / 2, 0)
                y: area.barTop + card.barHeight + 5
                text: card.ready ? card.timeline.first : ""
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            Text {
                visible: card.ready
                x: Math.min(area.xOf(1) - implicitWidth / 2, area.width - implicitWidth)
                y: area.barTop + card.barHeight + 5
                text: card.ready ? card.timeline.last : ""
                color: theme.dimText
                font.features: { "tnum": 1 }
            }

            MouseArea {
                id: hoverArea
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
                property string tip: ""
                onPositionChanged: function(mouse) { tip = area.tipAt(mouse.x) }
                onExited: tip = ""
                ToolTip {
                    visible: hoverArea.tip !== "" && hoverArea.containsMouse
                    text: hoverArea.tip
                    x: Math.min(hoverArea.mouseX + 12, hoverArea.width - width)
                    y: -height - 4
                    delay: 150
                }
            }
        }

        // Fuel in the tank over the race
        Item {
            id: levelArea
            visible: card.ready && card.levels.length > 1
            Layout.fillWidth: true
            implicitHeight: Math.round(theme.em * 3)
            clip: true  // canvas wider for a moment while the window narrows
            // Window resized: canvas sized (so drawn again) once the width settles, not at each step
            onWidthChanged: {
                if (levelCanvas.paintWidth > 0)
                    resizePaint.restart()
                else
                    levelCanvas.paintWidth = width
            }
            Timer { id: resizePaint; interval: 50; onTriggered: levelCanvas.paintWidth = levelArea.width }
            Canvas {
                id: levelCanvas
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.topMargin: levelLabel.height
                width: paintWidth
                renderStrategy: Canvas.Threaded  // drawn off the UI thread
                property real paintWidth: 0
                property color line: theme.accent
                property var points: card.levels
                onPointsChanged: requestPaint()
                onLineChanged: requestPaint()
                onPaint: {
                    var context = getContext("2d")
                    context.reset()
                    if (points.length < 2)
                        return
                    var left = area.edge, span = area.barWidth, height = levelCanvas.height - 2
                    context.beginPath()
                    context.moveTo(left + points[0][0] * span, 1 + height)
                    for (var index = 0; index < points.length; index++)
                        context.lineTo(left + points[index][0] * span, 1 + height * (1 - points[index][1]))
                    context.lineTo(left + points[points.length - 1][0] * span, 1 + height)
                    context.closePath()
                    context.fillStyle = Qt.rgba(line.r, line.g, line.b, 0.16)
                    context.fill()
                    context.beginPath()
                    for (index = 0; index < points.length; index++) {
                        var x = left + points[index][0] * span, y = 1 + height * (1 - points[index][1])
                        if (index)
                            context.lineTo(x, y)
                        else
                            context.moveTo(x, y)
                    }
                    context.lineWidth = 1.5
                    context.strokeStyle = line
                    context.stroke()
                }
            }
            Text {
                id: levelLabel
                text: i18n.tr("Fuel in tank")
                color: theme.dimText
                font.pointSize: theme.fontCaption
                x: area.edge
                y: 0
            }
        }

        Text {
            Layout.fillWidth: true
            visible: card.ready && text !== ""
            text: card.summary.text || ""
            textFormat: Text.StyledText
            color: card.summary.warning ? theme.loss : theme.dimText
            wrapMode: Text.Wrap
        }
    }
}
