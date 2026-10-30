import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator strategy: race laps left to right, one block per stint (one color per driver when
// drivers take turns), pit lap above each stop (tyre changes in tyre color with a ◆ mark, labels never
// overlap), safety car & rain bands, fuel in the tank below, details of stint or stop under the mouse (or
// Tab then Left / Right: stint by stint), summary
TpSectionCard {
    id: card
    property var timeline: ({})
    property var levels: []  // [position, fraction of tank]
    property var summary: ({})
    readonly property bool ready: timeline.ready === true
    readonly property real labelHeight: metrics.height
    readonly property real barHeight: Math.round(theme.em * 1.6)
    readonly property color tyreColor: theme.seriesTyre
    readonly property string tyreMark: "◆"  // tyre change told by a shape too, not only by its color
    readonly property real gap: Math.round(theme.space2)  // between labels, bar & ticks
    // Stint blocks: accent fill, every other one lighter (solid colors: texts on them never faded)
    readonly property color shade: Qt.rgba(theme.accentFill.r * 0.6 + theme.base.r * 0.4,
                                           theme.accentFill.g * 0.6 + theme.base.g * 0.4,
                                           theme.accentFill.b * 0.6 + theme.base.b * 0.4, 1)
    readonly property color darkInk: theme.dark ? theme.window : theme.text

    // Text on a fill: white or dark, whichever reads better
    function ink(fill) {
        return theme.contrast(Qt.color("white"), fill) >= theme.contrast(darkInk, fill) ? "white" : darkInk
    }

    Layout.fillWidth: true

    FontMetrics { id: metrics }
    glyph: ""  // flag
    title: i18n.tr("Strategy")
    spacing: theme.space3
    actions: [
        Repeater {  // legend (items kept when the plan changes: model is the count)
            model: card.ready ? card.timeline.bands.length : 0
            Row {
                id: legendItem
                required property int index
                readonly property var band: card.timeline.bands[index] || ({})
                spacing: theme.space2
                Rectangle {
                    width: theme.em * 0.8; height: theme.em * 0.5; radius: theme.radiusSm
                    color: legendItem.band.color ? theme.tint(legendItem.band.color, 0.6) : "transparent"
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: legendItem.band.name || ""
                    textFormat: Text.PlainText
                    width: Math.min(implicitWidth, theme.em * 8)
                    elide: Text.ElideRight
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                }
            }
        },
        Row {
            visible: card.ready && card.timeline.stops.some(function(stop) { return stop.tyres })
            spacing: theme.space2
            Text { text: card.tyreMark; color: card.tyreColor; font.pointSize: theme.fontSmall; textFormat: Text.PlainText }
            Text {
                text: i18n.tr("Tyres")
                width: Math.min(implicitWidth, theme.em * 8)
                elide: Text.ElideRight
                color: theme.dimText
                font.pointSize: theme.fontSmall
            }
        }
    ]


    // Timeline
    Item {
        id: area
        objectName: "strategyTimeline"
        Layout.fillWidth: true
        implicitHeight: card.labelHeight + card.gap + card.barHeight + card.gap + card.labelHeight
        readonly property real edge: metrics.advanceWidth(String(card.ready ? card.timeline.last : 0)) / 2 + 2
        readonly property real barWidth: Math.max(width - edge * 2, 1)
        readonly property real barTop: card.labelHeight + card.gap
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
        property int keyStint: -1  // stint shown with the keyboard (Left / Right), -1: none
        readonly property int stintCount: card.ready ? card.timeline.stints.length : 0
        onStintCountChanged: if (keyStint >= stintCount) keyStint = stintCount - 1

        function xOf(position) {
            return edge + position * barWidth
        }
        // Stop labels: "Lap 12", or "12" when the full one does not fit, none when even that does not;
        // tyre change: ◆ after the lap
        function stopLabels(stops, barWidth) {
            var end = -1e9
            var list = []
            for (var index = 0; index < stops.length; index++) {
                var x = edge + stops[index].pos * barWidth
                var mark = stops[index].tyres ? " " + card.tyreMark : ""  // drawn after the text (room kept)
                var texts = [i18n.tr("Lap") + " " + stops[index].lap, String(stops[index].lap)]
                for (var t = 0; t < texts.length; t++) {
                    var labelWidth = metrics.advanceWidth(texts[t] + mark) + card.gap * 2
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
            var nearPixels = Math.max(5, theme.em * 0.35)
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

        // Keyboard: Tab reaches the strategy, Left / Right show stint after stint (details in tooltip)
        activeFocusOnTab: card.ready
        Accessible.role: Accessible.Graphic
        Accessible.name: i18n.tr("Strategy")
        Accessible.description: keyStint >= 0 && card.ready ? (card.timeline.stints[keyStint].tip || "")
                                                             : i18n.tr("Left / Right: stint details")
        Keys.onLeftPressed: keyStint = Math.max(0, keyStint - 1)
        Keys.onRightPressed: keyStint = Math.min(stintCount - 1, keyStint + 1)
        Keys.onShortcutOverride: function(event) {
            if (event.key === Qt.Key_Left || event.key === Qt.Key_Right)
                event.accepted = true
        }
        onActiveFocusChanged: if (!activeFocus) keyStint = -1
        FocusRing { visible: area.activeFocus; radius: theme.radiusMd }

        Row {  // nothing to plan yet, or plan impossible (warning: icon too)
            anchors.centerIn: parent
            visible: !card.ready
            width: Math.min(implicitWidth, parent.width)
            spacing: theme.space3
            Icon {
                visible: card.summary.warning === true
                glyph: ""  // warning
                fallback: "!"
                color: theme.loss
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                width: Math.min(implicitWidth, area.width - theme.em * 1.6)
                text: card.summary.warning ? card.summary.text : i18n.tr("Enter lap time, consumption and race length")
                textFormat: Text.StyledText
                color: card.summary.warning ? theme.loss : theme.dimText
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                anchors.verticalCenter: parent.verticalCenter
            }
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
        }

        // Safety car & rain laps: bands behind the stints. Bands, stints, stops & labels kept when the plan
        // changes (model is the count): blocks & stop lines slide to their new place
        Repeater {
            model: card.ready ? card.timeline.bands.length : 0
            Rectangle {
                required property int index
                readonly property var band: card.timeline.bands[index] || ({})
                x: area.xOf(band.start || 0)
                y: area.barTop - card.gap / 2
                width: Math.max(area.xOf(band.end || 0) - x, 2)
                height: card.barHeight + card.gap
                radius: theme.radiusSm
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
                color: stint.color ? stint.color : index % 2 ? card.shade : theme.accentFill
                border.width: area.keyStint === index ? 2 : 0
                border.color: theme.text
                Behavior on x { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                Behavior on width { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                Text {
                    anchors.centerIn: parent
                    visible: block.width > implicitWidth + theme.space4
                    text: block.stint.laps !== undefined ? block.stint.laps : ""
                    textFormat: Text.PlainText
                    color: card.ink(block.color)
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontLabel
                    font.features: { "tnum": 1 }
                }
                TpToolTip {  // stint chosen with the keyboard
                    visible: area.keyStint === block.index && area.activeFocus
                    text: block.stint.tip || ""
                    textFormat: Text.StyledText  // <b> & <br> of numbers & texts of the app (race_results.timeline)
                    y: -height - card.labelHeight - card.gap
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
                text: (label.text || "") + (label.tyres ? " " + card.tyreMark : "")
                textFormat: Text.PlainText
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
                height: Math.round(card.gap)
                color: theme.dimText
            }
        }
        Text {
            visible: card.ready
            x: Math.max(area.xOf(0) - implicitWidth / 2, 0)
            y: area.barTop + card.barHeight + card.gap
            text: card.ready ? card.timeline.first : ""
            textFormat: Text.PlainText
            color: theme.dimText
            font.features: { "tnum": 1 }
        }
        Text {
            visible: card.ready
            x: Math.min(area.xOf(1) - implicitWidth / 2, area.width - implicitWidth)
            y: area.barTop + card.barHeight + card.gap
            text: card.ready ? card.timeline.last : ""
            textFormat: Text.PlainText
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
            TpToolTip {
                visible: hoverArea.tip !== "" && hoverArea.containsMouse
                text: hoverArea.tip
                textFormat: Text.StyledText  // <b> & <br> of numbers & texts of the app (race_results.timeline)
                x: Math.min(hoverArea.mouseX + theme.em * 0.8, hoverArea.width - width)
                y: -height - card.gap
                delay: theme.motionBase  // follows the mouse along the bar: quicker than button tips
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

    RowLayout {
        Layout.fillWidth: true
        visible: card.ready && (card.summary.text || "") !== ""
        spacing: theme.space3
        Icon {
            visible: card.summary.warning === true
            glyph: ""  // warning
            fallback: "!"
            color: theme.loss
            Layout.alignment: Qt.AlignTop
        }
        Text {
            Layout.fillWidth: true
            text: card.summary.text || ""
            textFormat: Text.StyledText
            color: card.summary.warning ? theme.loss : theme.dimText
            wrapMode: Text.Wrap
        }
    }
}
