import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Session of current track: every lap time (shown laps in their color, best in gold, invalid hollow),
// fuel & tyre wear used each lap, off tracks & track limits. Click a lap: show or hide it in charts.
// Long run: pace & lap time trend of clean laps without outliers (traffic, mistakes: faded), per % tyre wear.
Item {
    id: root
    property var chart
    readonly property var session: backend.sessionData
    readonly property var laps: session.laps || []
    readonly property var trend: session.trend || ({})
    property int hoverIndex: -1
    // Numbers with decimal separator of app language (lap times keep their dot)
    function num(value, decimals) { return Number(value).toFixed(decimals).replace(".", theme.decimalPoint) }
    function signedText(value, decimals) { return (value >= 0 ? "+" : "−") + num(Math.abs(value), decimals) }

    function lapsWith(name) {
        return laps.filter(function(lap) { return lap[name] !== undefined && lap[name] !== null && lap[name] >= 0 })
    }
    readonly property var stats: {
        var valid = laps.filter(function(lap) { return lap.valid && lap.time > 0 })
        var sum = 0, fuel = 0, fuelCount = 0
        for (var i = 0; i < valid.length; i++) sum += valid[i].time
        var mean = valid.length ? sum / valid.length : 0
        var deviation = 0
        for (var j = 0; j < valid.length; j++) deviation += Math.pow(valid[j].time - mean, 2)
        deviation = valid.length > 1 ? Math.sqrt(deviation / (valid.length - 1)) : 0
        for (var k = 0; k < laps.length; k++) if (laps[k].fuel >= 0) { fuel += laps[k].fuel; fuelCount++ }
        return {"count": valid.length, "mean": mean, "deviation": deviation, "fuel": fuel, "fuelCount": fuelCount}
    }
    function timeText(seconds) {
        if (!(seconds > 0)) return "—"
        var minutes = Math.floor(seconds / 60)
        var rest = seconds - minutes * 60
        return (minutes > 0 ? minutes + ":" + (rest < 10 ? "0" : "") : "") + rest.toFixed(3)
    }


    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.5

        ComboBox {
            id: sessionBox
            Layout.fillWidth: true
            implicitHeight: Math.round(theme.em * 2.2)
            model: backend.sessions.map(function(item) { return item.title })
            currentIndex: backend.sessions.map(function(item) { return item.key }).indexOf(backend.sessionKey)
            onActivated: function(index) { backend.setSession(backend.sessions[index].key) }
            background: Rectangle {
                radius: theme.em * 0.5
                color: sessionBox.hovered ? theme.hover : theme.raised
                border.width: 1
                border.color: theme.border
            }
            contentItem: Text {
                leftPadding: theme.em * 0.6
                text: sessionBox.displayText || i18n.tr("No session")
                color: theme.text
                font.weight: Font.DemiBold
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }

        // Summary
        Flow {
            Layout.fillWidth: true
            spacing: theme.em * 0.9
            visible: root.laps.length > 0
            Text { text: i18n.tr("Best") + " " + root.timeText(root.session.best); color: theme.gold; font.weight: Font.DemiBold; font.features: { "tnum": 1 } }
            Text { text: i18n.tr("Average") + " " + root.timeText(root.stats.mean); color: theme.text; font.features: { "tnum": 1 } }
            Text {
                text: i18n.tr("Consistency") + " ±" + root.num(root.stats.deviation, 3) + " s"
                color: theme.text
                font.features: { "tnum": 1 }
                visible: root.stats.count > 1
            }
            Text {
                visible: root.stats.fuelCount > 0
                text: i18n.tr("Fuel") + " " + root.num(root.stats.fuel * (root.session.fuelScale || 1) / Math.max(root.stats.fuelCount, 1), 2)
                      + " " + (root.session.fuelUnit || "") + "/" + i18n.tr("lap")
                color: theme.text
                font.features: { "tnum": 1 }
            }
            BusyIndicator { running: root.session.busy === true; visible: running; implicitWidth: theme.em * 1.2; implicitHeight: implicitWidth }
        }
        // Long run: clean laps without outliers
        Flow {
            Layout.fillWidth: true
            spacing: theme.em * 0.9
            visible: root.trend.pace !== undefined
            Text {
                text: i18n.tr("Long-run pace") + " " + root.timeText(root.trend.pace || 0)
                color: theme.text
                font.features: { "tnum": 1 }
                ToolTip.visible: paceArea.containsMouse
                ToolTip.text: i18n.tr("Average of clean laps, slow laps left out (traffic, mistakes)") + "\n"
                              + i18n.tr("Laps counted") + " " + (root.trend.used || 0) + " · " + i18n.tr("left out") + " " + (root.trend.left || 0)
                MouseArea { id: paceArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            }
            Text {
                visible: root.trend.slope !== undefined
                text: i18n.tr("Trend") + " " + root.signedText(root.trend.slope || 0, 3) + " s/" + i18n.tr("lap")
                color: (root.trend.slope || 0) > 0.02 ? theme.loss : (root.trend.slope || 0) < -0.02 ? theme.gain : theme.text
                font.features: { "tnum": 1 }
                ToolTip.visible: trendArea.containsMouse
                ToolTip.text: i18n.tr("Lap time change per lap over the session (tyre wear, fuel burnt, track evolution)")
                MouseArea { id: trendArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            }
            Text {
                visible: root.trend.wearSlope !== undefined
                text: root.signedText(root.trend.wearSlope || 0, 3) + " s " + i18n.tr("per % tyre wear")
                color: theme.text
                font.features: { "tnum": 1 }
            }
        }

        // Lap times, fuel & tyre wear per lap
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Item {
                id: chartCanvas
                anchors.fill: parent
                readonly property real padLeft: theme.em * 3.6
                readonly property real padRight: theme.em * 0.6
                readonly property real timeHeight: height * 0.62
                readonly property real stripGap: theme.em * 0.8
                readonly property real stripHeight: Math.max((height - timeHeight - stripGap * 2) / 2, 0)
                readonly property var range: {
                    var times = root.laps.filter(function(lap) { return lap.time > 0 && lap.kind === "lap" }).map(function(lap) { return lap.time })
                    if (times.length === 0) return [0, 1]
                    var sorted = times.slice().sort(function(a, b) { return a - b })
                    var low = sorted[0]
                    // Slowest laps (spins, traffic) clipped: scale follows normal laps
                    var high = Math.min(sorted[sorted.length - 1], sorted[Math.floor((sorted.length - 1) * 0.9)] * 1.03)
                    if (high - low < 0.5) { low -= 0.25; high += 0.25 }
                    return [low - (high - low) * 0.08, high + (high - low) * 0.08]
                }
                function xAt(index) {
                    var count = Math.max(root.laps.length, 1)
                    return padLeft + (index + 0.5) / count * (width - padLeft - padRight)
                }
                function yAt(time) {
                    var top = theme.em * 0.6, bottom = timeHeight - theme.em * 0.4
                    return bottom - (Math.min(time, range[1]) - range[0]) / (range[1] - range[0]) * (bottom - top)
                }
                function stripMax(name) {
                    var high = 0
                    for (var i = 0; i < root.laps.length; i++) high = Math.max(high, root.laps[i][name] || 0)
                    return high
                }

                // Time grid
                Repeater {
                    model: root.laps.length ? 5 : 0
                    Item {
                        readonly property real value: chartCanvas.range[0] + (chartCanvas.range[1] - chartCanvas.range[0]) * index / 4
                        y: Math.round(chartCanvas.yAt(value))
                        width: chartCanvas.width
                        Rectangle { x: chartCanvas.padLeft; width: chartCanvas.width - chartCanvas.padLeft - chartCanvas.padRight; height: 1; color: theme.border }
                        Text {
                            y: -height / 2
                            text: root.timeText(parent.value).replace(/(\.\d)\d+$/, "$1")
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.7
                            font.features: { "tnum": 1 }
                        }
                    }
                }
                // Best lap line
                Rectangle {
                    visible: root.session.best > 0
                    x: chartCanvas.padLeft
                    y: chartCanvas.yAt(root.session.best || 0)
                    width: chartCanvas.width - chartCanvas.padLeft - chartCanvas.padRight
                    height: 1
                    color: theme.gold
                    opacity: 0.7
                }
                // Long run trend line (clean laps without outliers)
                Rectangle {
                    readonly property real x0: chartCanvas.xAt(root.trend.x0 || 0)
                    readonly property real y0: chartCanvas.yAt(root.trend.y0 || 0)
                    readonly property real x1: chartCanvas.xAt(root.trend.x1 || 0)
                    readonly property real y1: chartCanvas.yAt(root.trend.y1 || 0)
                    visible: root.trend.slope !== undefined
                    x: x0
                    y: y0
                    width: Math.hypot(x1 - x0, y1 - y0)
                    height: 2
                    transformOrigin: Item.Left
                    rotation: Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI
                    color: theme.purple
                    opacity: 0.75
                }
                // Valid laps joined
                Repeater {
                    model: root.laps.length
                    Rectangle {
                        readonly property var lap: root.laps[index]
                        readonly property var previous: index > 0 ? root.laps[index - 1] : null
                        readonly property bool joined: previous !== null && lap.valid && previous.valid && lap.time > 0 && previous.time > 0
                        readonly property real x0: chartCanvas.xAt(index - 1)
                        readonly property real y0: previous ? chartCanvas.yAt(previous.time) : 0
                        readonly property real x1: chartCanvas.xAt(index)
                        readonly property real y1: chartCanvas.yAt(lap.time)
                        visible: joined
                        x: x0
                        y: y0
                        width: Math.hypot(x1 - x0, y1 - y0)
                        height: 1.5
                        transformOrigin: Item.Left
                        rotation: Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI
                        color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.3)
                    }
                }
                // Lap points: shown laps in their color, best lap gold, invalid hollow
                Repeater {
                    model: root.laps.length
                    Item {
                        readonly property var lap: root.laps[index]
                        readonly property real size: theme.em * (lap.shown ? 0.85 : 0.6) * (index === root.hoverIndex ? 1.3 : 1)
                        readonly property color tone: lap.shown ? lap.color
                            : (lap.valid && lap.time <= root.session.best + 1e-6 ? theme.gold : theme.text)
                        visible: lap.time > 0
                        opacity: lap.outlier ? 0.4 : 1
                        x: chartCanvas.xAt(index)
                        y: chartCanvas.yAt(lap.time)
                        Rectangle {
                            x: -width / 2
                            y: -height / 2
                            width: parent.size
                            height: parent.size
                            radius: width / 2
                            color: parent.lap.valid ? parent.tone : "transparent"
                            border.width: parent.lap.valid ? 1.5 : 2
                            border.color: parent.lap.valid ? theme.window : parent.tone
                        }
                        Text {  // track limits / off track count
                            visible: parent.lap.limits > 0 || parent.lap.offtrack > 0
                            x: -width / 2
                            y: -parent.size / 2 - height
                            text: parent.lap.limits > 0 ? "✕" + parent.lap.limits : "◇" + parent.lap.offtrack
                            color: parent.lap.limits > 0 ? theme.warning : theme.dimText
                            font.pointSize: theme.fontPoint * 0.68
                        }
                    }
                }
                // Fuel & tyre wear used each lap
                Repeater {
                    model: [["fuel", i18n.tr("Fuel"), "#3B82F6"], ["wear", i18n.tr("Tyre wear"), "#F59E0B"]]
                    Item {
                        id: strip
                        readonly property string name: modelData[0]
                        readonly property color tone: modelData[2]
                        readonly property real high: chartCanvas.stripMax(name)
                        y: chartCanvas.timeHeight + chartCanvas.stripGap + index * (chartCanvas.stripHeight + chartCanvas.stripGap)
                        width: chartCanvas.width
                        height: chartCanvas.stripHeight
                        visible: high > 0
                        Text { text: modelData[1]; color: theme.dimText; font.pointSize: theme.fontPoint * 0.7 }
                        Text {
                            anchors.bottom: parent.bottom
                            text: strip.name === "fuel" ? root.num(strip.high * (root.session.fuelScale || 1), 2) + " " + (root.session.fuelUnit || "")
                                                        : root.num(strip.high, 1) + " %"
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.7
                            font.features: { "tnum": 1 }
                        }
                        Repeater {
                            model: root.laps.length
                            Rectangle {
                                readonly property real value: root.laps[index][strip.name]
                                readonly property real barWidth: Math.max((chartCanvas.width - chartCanvas.padLeft - chartCanvas.padRight) / Math.max(root.laps.length, 1) * 0.6, 2)
                                visible: value >= 0 && strip.high > 0
                                x: chartCanvas.xAt(index) - barWidth / 2
                                width: barWidth
                                height: visible ? value / strip.high * (strip.height - theme.em * 0.2) : 0
                                y: strip.height - height
                                radius: 1
                                color: strip.tone
                                opacity: root.laps[index].valid ? 0.85 : 0.35
                            }
                        }
                    }
                }
            }
            MouseArea {
                id: canvasMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: root.hoverIndex >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
                function indexAt(px) {
                    var count = root.laps.length
                    if (count === 0 || px < chartCanvas.padLeft) return -1
                    var index = Math.floor((px - chartCanvas.padLeft) / (width - chartCanvas.padLeft - chartCanvas.padRight) * count)
                    return index >= 0 && index < count ? index : -1
                }
                onPositionChanged: function(mouse) { root.hoverIndex = indexAt(mouse.x) }
                onExited: root.hoverIndex = -1
                onClicked: function(mouse) {
                    var index = indexAt(mouse.x)
                    if (index >= 0) backend.setLapChecked(root.laps[index].path, !root.laps[index].shown)
                }
                onDoubleClicked: function(mouse) {
                    var index = indexAt(mouse.x)
                    if (index >= 0) backend.setReference(root.laps[index].path)
                }
            }
            // Hovered lap details
            Rectangle {
                readonly property var lap: root.hoverIndex >= 0 ? root.laps[root.hoverIndex] : null
                visible: lap !== null
                x: Math.max(0, Math.min(chartCanvas.xAt(root.hoverIndex) + theme.em, parent.width - width))
                y: theme.em * 0.3
                width: lapText.implicitWidth + theme.em
                height: lapText.implicitHeight + theme.em * 0.5
                radius: theme.em * 0.35
                color: theme.raised
                border.width: 1
                border.color: lap && lap.color ? lap.color : theme.border
                Text {
                    id: lapText
                    anchors.centerIn: parent
                    color: theme.text
                    font.pointSize: theme.fontPoint * 0.82
                    font.features: { "tnum": 1 }
                    text: {
                        var lap = parent.lap
                        if (!lap) return ""
                        var lines = [i18n.tr("Lap") + " " + lap.number + " · " + lap.text + (lap.valid ? "" : " · " + i18n.tr("invalid"))
                                     + (lap.outlier ? " · " + i18n.tr("left out of long run") : "")]
                        var details = []
                        if (lap.fuel >= 0) details.push(i18n.tr("Fuel") + " " + root.num(lap.fuel * (root.session.fuelScale || 1), 2) + " " + (root.session.fuelUnit || ""))
                        if (lap.wear >= 0) details.push(i18n.tr("Tyre wear") + " " + root.num(lap.wear, 2) + " %")
                        if (lap.temp !== null) details.push(i18n.tr("Track Temp") + " " + root.num(lap.temp, 1) + (root.session.temperatureUnit || "°C"))
                        if (details.length) lines.push(details.join(" · "))
                        var events = []
                        if (lap.limits >= 0) events.push("✕ " + i18n.tr("Track limits exceeded") + " " + lap.limits)
                        if (lap.offtrack >= 0) events.push("◇ " + i18n.tr("Off track") + " " + lap.offtrack)
                        if (events.length) lines.push(events.join(" · "))
                        lines.push(lap.shown ? i18n.tr("Click: hide from charts") : i18n.tr("Click: show in charts · double-click: reference"))
                        return lines.join("\n")
                    }
                }
            }
        }
        Text {
            visible: root.laps.length === 0
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18n.tr("No lap recorded in this session.")
            color: theme.dimText
        }
    }
}
