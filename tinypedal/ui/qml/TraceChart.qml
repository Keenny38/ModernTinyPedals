import QtQuick
import QtQuick.Controls.Basic
import TinyPedal

// Stacked channel charts along lap distance (or lap time), lines drawn by GPU
// Wheel: zoom, drag: move, Shift+drag: zoom to area, double-click: reset, drag a channel name: reorder.
// Keyboard: +/- zoom, left/right move, Home or 0 reset.
FocusScope {
    id: chart

    readonly property real maxX: Math.max(backend.maxX, 1)
    property real targetStart: 0
    property real targetEnd: maxX
    property real viewStart: targetStart
    property real viewEnd: targetEnd
    property bool animate: false
    property real cursorX: NaN
    readonly property bool hasCursor: !isNaN(cursorX)
    property var cursorValues: []
    readonly property bool zoomed: targetEnd - targetStart < maxX - 1
    readonly property real labelWidth: theme.em * 7
    readonly property real gap: theme.em * 0.35
    property var panels: backend.panels
    readonly property real totalWeight: panels.reduce(function(sum, panel) { return sum + panel.weight }, 0) || 1
    property int movingFrom: -1
    property var lineOffsets: [[0, 0], [0.5, 0.5]]
    property int movingTo: -1

    Behavior on viewStart { enabled: chart.animate; NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
    Behavior on viewEnd { enabled: chart.animate; NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }

    function setView(start, end, animated) {
        var span = end - start
        if (span >= maxX) { start = 0; end = maxX }
        else if (start < 0) { end -= start; start = 0 }
        else if (end > maxX) { start -= end - maxX; end = maxX }
        animate = animated
        targetStart = Math.max(start, 0)
        targetEnd = Math.min(end, maxX)
    }
    function resetView(animated) { setView(0, maxX, animated) }
    function zoom(factor, center, animated) {
        if (center === undefined || isNaN(center)) center = (targetStart + targetEnd) / 2
        var start = center - (center - targetStart) * factor
        var end = center + (targetEnd - center) * factor
        if (end - start >= (backend.timeAxis ? 0.5 : 5)) setView(start, end, animated)
    }
    function showX(x) {
        if (x < targetStart || x > targetEnd) {
            var span = targetEnd - targetStart
            setView(x - span / 2, x + span / 2, true)
        }
        setCursor(x)
    }
    function setCursor(x) {
        cursorX = x
        cursorValues = isNaN(x) ? [] : backend.cursorValues(x)
    }
    function xOf(value) { return (value - viewStart) / Math.max(viewEnd - viewStart, 1e-9) * plotArea.width }
    function valueOf(px) { return viewStart + px / Math.max(plotArea.width, 1) * (viewEnd - viewStart) }
    function panelTop(index) {
        var weight = 0
        for (var i = 0; i < index; i++) weight += panels[i].weight
        return weight / totalWeight * plotArea.height
    }
    function panelHeight(index) { return panels[index].weight / totalWeight * plotArea.height - gap }
    function panelAt(y) {
        for (var i = 0; i < panels.length; i++)
            if (y < panelTop(i) + panelHeight(i) + gap / 2) return i
        return panels.length - 1
    }
    function niceStep(span, count) {
        var raw = Math.max(span / Math.max(count, 1), 1e-9)
        var magnitude = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10))
        var multiples = [1, 2, 5, 10]
        for (var i = 0; i < multiples.length; i++)
            if (raw <= multiples[i] * magnitude) return multiples[i] * magnitude
        return 10 * magnitude
    }
    function axisText(value) {
        if (!backend.timeAxis) return value.toFixed(0) + " m"
        if (value < 60) return value.toFixed(0) + "s"
        var minutes = Math.floor(value / 60)
        var seconds = Math.round(value - minutes * 60)
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    onMaxXChanged: resetView(false)
    onTargetStartChanged: backend.setChartView(targetStart, targetEnd)
    onTargetEndChanged: backend.setChartView(targetStart, targetEnd)

    Connections {
        target: backend
        function onViewRestored(start, end) { chart.setView(start, end, false) }
    }
    onPanelsChanged: if (hasCursor) cursorValues = backend.cursorValues(cursorX)

    readonly property real tickStep: niceStep(viewEnd - viewStart, plotArea.width / (theme.em * 6))
    readonly property real firstTick: Math.ceil(viewStart / tickStep) * tickStep

    Keys.onPressed: function(event) {
        var span = targetEnd - targetStart
        if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) zoom(0.8, cursorX, true)
        else if (event.key === Qt.Key_Minus) zoom(1.25, cursorX, true)
        else if (event.key === Qt.Key_Left) setView(targetStart - span * 0.2, targetEnd - span * 0.2, true)
        else if (event.key === Qt.Key_Right) setView(targetStart + span * 0.2, targetEnd + span * 0.2, true)
        else if (event.key === Qt.Key_Home || event.key === Qt.Key_0) resetView(true)
        else return
        event.accepted = true
    }

    // Header: cursor position, zoom
    Item {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: chart.labelWidth }
        height: theme.em * 2
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: chart.hasCursor ? backend.cursorTitle(chart.cursorX)
                : panels.length ? i18n.tr("Wheel: zoom · drag: move · Shift+drag: zoom area · double-click: reset")
                : ""
            color: chart.hasCursor ? theme.text : theme.dimText
            font.weight: chart.hasCursor ? Font.DemiBold : Font.Normal
            font.features: { "tnum": 1 }
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.4
            opacity: chart.zoomed ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "×" + (chart.maxX / Math.max(chart.targetEnd - chart.targetStart, 1e-9)).toFixed(1)
                color: theme.dimText
            }
            TpButton {
                glyph: ""  // zoom out
                text: i18n.tr("Reset")
                flat: true
                implicitHeight: theme.em * 1.8
                onClicked: chart.resetView(true)
            }
        }
    }

    Text {
        anchors.centerIn: plotArea
        visible: panels.length === 0 || backend.legend.length === 0
        text: backend.loading ? "" : i18n.tr("Select recorded laps to compare.")
        color: theme.dimText
    }

    // Charts area
    Item {
        id: plotArea
        anchors {
            left: parent.left; right: parent.right; top: header.bottom; bottom: axis.top
            leftMargin: chart.labelWidth
        }
        visible: backend.legend.length > 0

        // Panel backgrounds
        Repeater {
            model: chart.panels
            Rectangle {
                y: chart.panelTop(index)
                width: plotArea.width
                height: chart.panelHeight(index)
                radius: theme.em * 0.35
                color: theme.dark ? Qt.darker(theme.base, 1.18) : Qt.darker(theme.base, 1.015)
                border.width: 1
                border.color: index === chart.movingFrom ? theme.accent : (theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border)
            }
        }

        // Distance grid
        Repeater {
            model: 40
            Rectangle {
                readonly property real value: chart.firstTick + index * chart.tickStep
                visible: value <= chart.viewEnd
                x: Math.round(chart.xOf(value))
                width: 1
                height: plotArea.height
                color: theme.text
                opacity: 0.06
            }
        }

        // Sector lines & corner apexes of reference lap
        Repeater {
            model: backend.sectorLines
            Item {
                readonly property real px: chart.xOf(modelData.x)
                visible: px >= 0 && px <= plotArea.width
                x: Math.round(px)
                height: plotArea.height
                Rectangle { width: 1; height: parent.height; color: theme.text; opacity: 0.22 }
                Text {
                    x: 3; y: 1
                    text: modelData.label
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.8
                    font.weight: Font.DemiBold
                }
            }
        }
        Repeater {
            model: backend.cornerMarks
            Item {
                readonly property real px: chart.xOf(modelData.x)
                visible: px >= 0 && px <= plotArea.width
                x: Math.round(px)
                height: plotArea.height
                Rectangle { width: 1; height: parent.height; color: theme.text; opacity: 0.09 }
                Text {
                    x: 3; y: theme.em * 1.2
                    text: modelData.label
                    color: theme.dimText
                    opacity: 0.8
                    font.pointSize: theme.fontPoint * 0.8
                }
            }
        }

        // Channel lines
        Repeater {
            model: chart.panels
            Item {
                id: panel
                readonly property var info: modelData
                readonly property real sx: width / Math.max(chart.viewEnd - chart.viewStart, 1e-9)
                readonly property real pad: Math.min(theme.em * 0.4, height * 0.1)  // lines at range limits stay visible
                readonly property real sy: (height - pad * 2) / Math.max(info.high - info.low, 1e-9)
                readonly property real ty: height - pad + info.low * sy
                y: chart.panelTop(index)
                width: plotArea.width
                height: chart.panelHeight(index)
                clip: true

                Rectangle {
                    visible: panel.info.zero
                    y: Math.round(panel.ty)
                    width: parent.width
                    height: 1
                    color: theme.text
                    opacity: 0.18
                }
                Repeater {
                    model: panel.info.series
                    Item {
                        id: lapSeries
                        // Line drawn twice, half a pixel apart: about 1.5 px wide (scene graph lines are 1 px)
                        Repeater {
                            model: chart.lineOffsets
                            GpuShape {
                                key: lapSeries.series.key
                                color: lapSeries.series.color
                                revision: backend.revision
                                transform: Matrix4x4 {
                                    matrix: Qt.matrix4x4(panel.sx, 0, 0, -chart.viewStart * panel.sx + modelData[0],
                                                         0, -panel.sy, 0, panel.ty + modelData[1],
                                                         0, 0, 1, 0,
                                                         0, 0, 0, 1)
                                }
                            }
                        }
                        readonly property var series: modelData
                    }
                }
                Text {
                    x: 4; y: 1
                    text: panel.info.highText
                    color: theme.dimText
                    opacity: 0.8
                    visible: panel.height > theme.em * 2.6
                    font.pointSize: theme.fontPoint * 0.75
                }
                Text {
                    x: 4; anchors.bottom: parent.bottom; anchors.bottomMargin: 1
                    text: panel.info.lowText
                    color: theme.dimText
                    opacity: 0.8
                    visible: panel.height > theme.em * 2.6
                    font.pointSize: theme.fontPoint * 0.75
                }
            }
        }

        // Zoom selection (Shift+drag)
        Rectangle {
            id: selection
            property real fromX: 0
            property real toX: 0
            visible: false
            x: Math.min(fromX, toX)
            width: Math.abs(toX - fromX)
            height: plotArea.height
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.15)
            border.width: 1
            border.color: theme.accent
        }

        // Cursor line & values
        Rectangle {
            visible: chart.hasCursor && !selection.visible
            x: Math.round(chart.xOf(chart.cursorX))
            width: 1
            height: plotArea.height
            color: theme.text
            opacity: 0.55
        }
        Repeater {
            model: chart.panels
            Rectangle {
                id: bubble
                readonly property var values: chart.cursorValues[index] || []
                readonly property real px: chart.xOf(chart.cursorX)
                visible: chart.hasCursor && !selection.visible && values.length > 0
                         && chart.panelHeight(index) > valueColumn.height
                x: px + 8 + width <= plotArea.width ? px + 8 : px - 8 - width
                y: chart.panelTop(index) + 3
                width: valueColumn.width + theme.em * 0.6
                height: valueColumn.height + theme.em * 0.25
                radius: theme.em * 0.3
                color: Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.88)
                border.width: 1
                border.color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.12)
                Column {
                    id: valueColumn
                    anchors.centerIn: parent
                    Repeater {
                        model: bubble.values
                        Text {
                            text: modelData.text
                            color: modelData.color
                            font.pointSize: theme.fontPoint * 0.85
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
        }

        MouseArea {
            id: plotMouse
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton
            property real pressX: 0
            property real pressStart: 0
            property real pressEnd: 0
            property bool selecting: false
            cursorShape: pressed && !selecting ? Qt.ClosedHandCursor : Qt.CrossCursor

            onPressed: function(mouse) {
                chart.forceActiveFocus()
                pressX = mouse.x
                pressStart = chart.targetStart
                pressEnd = chart.targetEnd
                selecting = (mouse.modifiers & Qt.ShiftModifier) !== 0
                if (selecting) {
                    selection.fromX = mouse.x
                    selection.toX = mouse.x
                    selection.visible = true
                }
            }
            onPositionChanged: function(mouse) {
                if (pressed && selecting) {
                    selection.toX = Math.max(0, Math.min(mouse.x, width))
                } else if (pressed) {
                    var shift = (pressX - mouse.x) / Math.max(width, 1) * (pressEnd - pressStart)
                    chart.setView(pressStart + shift, pressEnd + shift, false)
                }
                chart.setCursor(chart.valueOf(mouse.x))
            }
            onReleased: {
                if (selecting && selection.width > 4)
                    chart.setView(chart.valueOf(selection.x), chart.valueOf(selection.x + selection.width), true)
                selection.visible = false
                selecting = false
            }
            onExited: if (!pressed) chart.setCursor(NaN)
            onDoubleClicked: chart.resetView(true)
            onWheel: function(wheel) {
                chart.zoom(wheel.angleDelta.y > 0 ? 0.8 : 1.25, chart.valueOf(wheel.x), true)
            }
        }
    }

    // Channel names: drag to reorder
    Item {
        id: labels
        anchors { left: parent.left; top: plotArea.top; bottom: plotArea.bottom }
        width: chart.labelWidth
        visible: plotArea.visible

        Repeater {
            model: chart.panels
            Item {
                y: chart.panelTop(index)
                width: labels.width - theme.em * 0.6
                height: chart.panelHeight(index)
                opacity: index === chart.movingFrom ? 0.5 : 1
                Column {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        anchors.right: parent.right
                        text: modelData.title
                        color: theme.text
                        font.weight: Font.DemiBold
                        width: Math.min(implicitWidth, labels.width - theme.em)
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideRight
                    }
                    Text {
                        anchors.right: parent.right
                        visible: text !== ""
                        text: modelData.unit
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.8
                    }
                }
            }
        }
        Rectangle {
            visible: chart.movingFrom >= 0 && chart.movingTo !== chart.movingFrom
            width: chart.width
            height: 3
            radius: 1.5
            color: theme.accent
            y: chart.movingTo < 0 ? 0 : chart.movingTo < chart.movingFrom
                ? chart.panelTop(chart.movingTo) - chart.gap / 2 - 1
                : chart.panelTop(chart.movingTo) + chart.panelHeight(chart.movingTo) + chart.gap / 2 - 1
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: pressed ? Qt.SizeVerCursor : Qt.OpenHandCursor
            onPressed: function(mouse) { chart.movingFrom = chart.panelAt(mouse.y); chart.movingTo = chart.movingFrom }
            onPositionChanged: function(mouse) { if (pressed) chart.movingTo = chart.panelAt(mouse.y) }
            onReleased: {
                var from = chart.movingFrom, to = chart.movingTo
                chart.movingFrom = -1
                chart.movingTo = -1
                if (from >= 0 && to >= 0 && from !== to) backend.moveChannel(from, to)
            }
        }
    }

    // Distance / time axis
    Item {
        id: axis
        anchors { left: parent.left; right: parent.right; bottom: overview.top; leftMargin: chart.labelWidth }
        height: theme.em * 1.6
        visible: plotArea.visible
        clip: true
        Repeater {
            model: 40
            Text {
                readonly property real value: chart.firstTick + index * chart.tickStep
                visible: value <= chart.viewEnd
                x: Math.max(0, Math.min(chart.xOf(value) - width / 2, axis.width - width))
                y: theme.em * 0.2
                text: chart.axisText(value)
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                font.features: { "tnum": 1 }
            }
        }
    }

    // Whole lap navigator: zoomed part as a window, drag or click to move it
    Item {
        id: overview
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: chart.labelWidth }
        height: visible ? theme.em * 2.6 : 0
        visible: plotArea.visible && backend.overview.key !== undefined

        Rectangle {
            anchors.fill: parent
            radius: theme.em * 0.35
            color: theme.dark ? Qt.darker(theme.base, 1.18) : Qt.darker(theme.base, 1.015)
            border.width: 1
            border.color: theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border
        }
        Item {
            id: overviewPlot
            readonly property real sx: width / chart.maxX
            readonly property real sy: height / Math.max((backend.overview.high || 1) - (backend.overview.low || 0), 1e-9)
            anchors.fill: parent
            anchors.margins: 3
            clip: true
            GpuShape {
                key: backend.overview.key || ""
                color: theme.dimText
                revision: backend.revision
                transform: Matrix4x4 {
                    matrix: Qt.matrix4x4(overviewPlot.sx, 0, 0, 0,
                                         0, -overviewPlot.sy, 0, overviewPlot.height + (backend.overview.low || 0) * overviewPlot.sy,
                                         0, 0, 1, 0, 0, 0, 0, 1)
                }
            }
        }
        Rectangle {
            id: window
            x: chart.viewStart / chart.maxX * overview.width
            width: Math.max((chart.viewEnd - chart.viewStart) / chart.maxX * overview.width, 4)
            height: overview.height
            radius: theme.em * 0.35
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, chart.zoomed ? 0.16 : 0.0)
            border.width: chart.zoomed ? 1.5 : 0
            border.color: theme.accent
            Behavior on color { ColorAnimation { duration: 200 } }
        }
        Rectangle {
            visible: chart.hasCursor
            x: chart.cursorX / chart.maxX * overview.width
            width: 1
            height: overview.height
            color: theme.text
            opacity: 0.5
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            function moveTo(px, animated) {
                var span = chart.targetEnd - chart.targetStart
                var center = px / overview.width * chart.maxX
                chart.setView(center - span / 2, center + span / 2, animated)
            }
            onPressed: function(mouse) { moveTo(mouse.x, true) }
            onPositionChanged: function(mouse) { if (pressed) moveTo(mouse.x, false) }
        }
    }
}
