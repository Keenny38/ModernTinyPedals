import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Incidents of the session (contacts between cars, or with walls; both sides listed by game merged):
// kind filter, my car only, driver chips (most incidents first), timeline (marker: jump there, click elsewhere:
// replay goes there, wheel: zoom, drag: move, double click: whole session; playhead follows replay),
// list (double click or Enter: jump, right click: camera & driver), copy or export to CSV.
// In a live session, jumping opens the replay of the session (back to live from playback).
Item {
    id: root

    readonly property var counts: backend.counts
    readonly property var timelineData: backend.timeline
    property var menuEntries: []  // row menu: text, action (jump, filter), driver
    property string menuKey: ""  // incident of row menu
    readonly property bool canJump: backend.inSession && !backend.lastSession
    readonly property bool live: backend.inSession && !backend.replayActive  // jump: replay of live session

    function clock(seconds) {
        var total = Math.max(Math.floor(seconds), 0)
        var hours = Math.floor(total / 3600), minutes = Math.floor(total / 60) % 60, rest = total % 60
        return hours + ":" + (minutes < 10 ? "0" : "") + minutes + ":" + (rest < 10 ? "0" : "") + rest
    }
    function escaped(text) { return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    function showSelected() {
        var index = backend.incidentIndex(backend.selectedIncident)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }
    function openMenu(row, item, x, y) {
        var entries = [{ "text": i18n.tr("Jump, camera on %1").arg(row.driver), "action": "jump", "driver": row.driver }]
        if (!row.wall) entries.push({ "text": i18n.tr("Jump, camera on %1").arg(row.other), "action": "jump", "driver": row.other })
        entries.push({ "text": i18n.tr("Only incidents of %1").arg(row.driver), "action": "filter", "driver": row.driver })
        if (!row.wall) entries.push({ "text": i18n.tr("Only incidents of %1").arg(row.other), "action": "filter", "driver": row.other })
        menuEntries = entries
        menuKey = row.key
        rowMenu.popup(item, x, y)
    }

    TpMenu {
        id: rowMenu
        Instantiator {
            model: root.menuEntries
            delegate: Action {
                required property var modelData
                text: modelData.text
                enabled: modelData.action !== "jump" || root.canJump
                onTriggered: {
                    if (modelData.action === "jump") backend.jumpTo(root.menuKey, modelData.driver)
                    else if (backend.driverFilter !== modelData.driver) backend.setDriverFilter(modelData.driver)  // toggles
                }
            }
            onObjectAdded: function(index, object) { rowMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { rowMenu.removeAction(object) }
        }
    }

    TpMenu {
        id: exportMenu
        width: Math.max(implicitWidth, theme.em * 17)
        Action { text: i18n.tr("Copy to Clipboard"); onTriggered: backend.copyIncidents() }
        Action { text: i18n.tr("Export CSV..."); onTriggered: backend.exportIncidents() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        anchors.topMargin: 0
        spacing: theme.em * 0.5

        // Kind filter, my car, export, previous / next incident
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TpSegmented {
                visible: root.counts.all > 0
                options: [i18n.tr("All") + "  " + root.counts.all, i18n.tr("Cars") + "  " + root.counts.cars,
                          i18n.tr("Walls") + "  " + root.counts.walls]
                currentIndex: backend.incidentFilter
                maxWidth: root.width * 0.5
                onActivated: function(index) { backend.setIncidentFilter(index) }
            }
            Rectangle {  // game in menus: incidents of the session left
                visible: backend.lastSession && root.counts.all > 0
                implicitHeight: lastText.implicitHeight + theme.em * 0.3
                implicitWidth: lastText.implicitWidth + theme.em * 1.0
                radius: height / 2
                color: Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.16)
                Text {
                    id: lastText
                    anchors.centerIn: parent
                    text: i18n.tr("Last Session")
                    color: theme.warning
                    font.pointSize: theme.fontPoint * 0.85
                    font.weight: Font.DemiBold
                }
            }
            Item { Layout.fillWidth: true }
            TpSwitch {
                visible: backend.playerName !== ""
                text: i18n.tr("My car")
                tip: i18n.tr("Incidents of %1 only").arg(backend.playerName)
                checked: backend.mineOnly
                onToggled: backend.setMineOnly(checked)
            }
            TpButton {
                id: exportButton
                glyph: ""  // export
                flat: true
                tip: i18n.tr("Copy or export incidents shown")
                enabled: root.counts.shown > 0
                checked: exportMenu.visible
                onClicked: exportMenu.visible ? exportMenu.close()  // right aligned: never cut by window
                                              : exportMenu.popup(exportButton, exportButton.width - exportMenu.width, exportButton.height + 4)
            }
            TpButton {
                glyph: ""  // chevron up
                flat: true
                tip: i18n.tr("Previous incident")
                enabled: root.counts.shown > 0
                onClicked: { backend.jumpNext(-1); root.showSelected() }
            }
            TpButton {
                glyph: ""  // chevron down
                flat: true
                tip: i18n.tr("Next incident")
                enabled: root.counts.shown > 0
                onClicked: { backend.jumpNext(1); root.showSelected() }
            }
        }

        // Timeline of session: incident markers drawn at once (long races: hundreds), replay playhead.
        // Wheel: zoom at mouse, drag: move zoomed view, double click: whole session.
        Item {
            id: timeline
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.em * 3.2)
            visible: root.counts.all > 0 || (backend.replayActive && backend.replayTime >= 0)
            readonly property real fullEnd: Math.max(root.timelineData.end || 60, now * 1.02, 60)
            property real zoomStart: -1  // shown part of session, -1: whole session
            property real zoomEnd: -1
            readonly property real viewStart: zoomStart >= 0 ? Math.min(zoomStart, fullEnd - 30) : 0
            readonly property real viewEnd: zoomEnd > 0 ? Math.min(zoomEnd, fullEnd) : fullEnd
            readonly property real viewSpan: Math.max(viewEnd - viewStart, 1)
            readonly property bool zoomed: zoomStart >= 0
            readonly property real pad: theme.em * 0.6
            readonly property real railWidth: Math.max(width - pad * 2, 1)
            readonly property real railY: Math.round(height * 0.36)
            property real now: backend.replayActive ? backend.replayTime : -1
            property string hoverKey: ""
            property real hoverTime: -1
            readonly property real step: {
                var steps = [10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600]
                var count = Math.max(2, Math.floor(railWidth / (theme.em * 5)))
                for (var i = 0; i < steps.length; i++) if (viewSpan / steps[i] <= count) return steps[i]
                return 43200
            }
            readonly property var ticks: {
                var result = []
                for (var t = Math.ceil(viewStart / step) * step; t < viewEnd - step * 0.2; t += step) if (t > 0) result.push(t)
                return result
            }
            function xOf(seconds) { return pad + railWidth * (seconds - viewStart) / viewSpan }
            function timeAt(px) { return Math.max(0, Math.min(viewStart + (px - pad) / railWidth * viewSpan, fullEnd)) }
            function markerAt(px, py) {  // nearest marker under mouse, "" if none
                if (Math.abs(py - railY) > theme.em * 0.9) return ""
                var markers = root.timelineData.markers || [], best = theme.em * 0.6, key = ""
                for (var i = 0; i < markers.length; i++) {
                    var gap = Math.abs(xOf(markers[i].time) - px)
                    if (gap < best || (gap === best && markers[i].shown)) { best = gap; key = markers[i].key }
                }
                return key
            }
            function labelOf(key) {
                var markers = root.timelineData.markers || []
                for (var i = 0; i < markers.length; i++) if (markers[i].key === key) return markers[i].label
                return ""
            }
            function zoomAt(factor, px) {
                var at = timeAt(px)
                var span = Math.max(30, Math.min(viewSpan * factor, fullEnd))
                if (span >= fullEnd - 0.5) { zoomStart = -1; zoomEnd = -1; return }
                var start = Math.max(0, Math.min(at - (at - viewStart) * span / viewSpan, fullEnd - span))
                zoomStart = start
                zoomEnd = start + span
            }
            function moveBy(seconds) {
                if (!zoomed) return
                var start = Math.max(0, Math.min(viewStart + seconds, fullEnd - viewSpan))
                zoomEnd = start + viewSpan
                zoomStart = start
            }

            Timer {  // playhead moves between game answers at measured rate
                interval: 100
                repeat: true
                running: timeline.visible && backend.replayActive && backend.replayRate !== 0
                onTriggered: timeline.now = backend.replayTime + backend.replayRate
                             * Math.min(Math.max((Date.now() - backend.timeReceived) / 1000, 0), 3)
            }
            Connections {
                target: backend
                function onReplayTimeChanged() { timeline.now = backend.replayActive ? backend.replayTime : -1 }
            }

            Rectangle {  // rail
                x: timeline.pad
                y: timeline.railY - height / 2
                width: timeline.railWidth
                height: Math.max(3, Math.round(theme.em * 0.28))
                radius: height / 2
                color: theme.hover
                Rectangle {  // played
                    visible: timeline.now >= 0
                    width: Math.max(0, Math.min(timeline.xOf(timeline.now), timeline.pad + timeline.railWidth) - timeline.pad)
                    height: parent.height
                    radius: parent.radius
                    color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.45)
                }
            }
            Repeater {  // time ticks
                model: timeline.ticks
                Item {
                    required property var modelData
                    x: timeline.xOf(modelData)
                    Rectangle { x: -0.5; y: timeline.railY + theme.em * 0.3; width: 1; height: theme.em * 0.3; color: theme.border }
                    Text {
                        x: -width / 2
                        y: timeline.railY + theme.em * 0.6
                        text: root.clock(parent.modelData)
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.72
                        font.features: { "tnum": 1 }
                    }
                }
            }
            Repeater {  // lap starts of car followed by camera (as game shows on its timeline)
                model: backend.lapMarks
                Item {
                    required property var modelData
                    visible: modelData.time >= timeline.viewStart && modelData.time <= timeline.viewEnd
                    x: timeline.xOf(modelData.time)
                    Rectangle { x: -0.5; y: timeline.railY - theme.em * 0.55; width: 1; height: theme.em * 0.55; color: theme.dimText; opacity: 0.6 }
                    Text {
                        x: -width / 2
                        y: timeline.railY - theme.em * 0.55 - height
                        text: parent.modelData.lap
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.68
                        font.features: { "tnum": 1 }
                    }
                }
            }
            Canvas {  // incident markers
                id: markersCanvas
                anchors.fill: parent
                property var data: root.timelineData
                property string selected: backend.selectedIncident
                property string hover: timeline.hoverKey
                property real start: timeline.viewStart
                property real end: timeline.viewEnd
                property bool dark: theme.dark
                onDataChanged: requestPaint()
                onSelectedChanged: requestPaint()
                onHoverChanged: requestPaint()
                onStartChanged: requestPaint()
                onEndChanged: requestPaint()
                onDarkChanged: requestPaint()
                onWidthChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    var markers = (data && data.markers) || []
                    var order = [[], [], []]  // dim & others, my car, selected or hovered: drawn on top
                    for (var i = 0; i < markers.length; i++) {
                        var marker = markers[i]
                        var px = timeline.xOf(marker.time)
                        if (px < timeline.pad - 8 || px > width - timeline.pad + 8) continue
                        var top = marker.key === selected || marker.key === hover
                        order[top ? 2 : marker.mine ? 1 : 0].push([marker, px])
                    }
                    for (var layer = 0; layer < 3; layer++) {
                        for (var j = 0; j < order[layer].length; j++) {
                            var entry = order[layer][j], item = entry[0], cx = entry[1]
                            var isSelected = item.key === selected
                            var radius = theme.em * (isSelected ? 0.5 : item.key === hover ? 0.43 : item.mine ? 0.37 : 0.28)
                            ctx.globalAlpha = item.shown ? 1 : 0.18
                            ctx.beginPath()
                            ctx.arc(cx, timeline.railY, radius, 0, Math.PI * 2)
                            ctx.fillStyle = String(item.wall ? theme.warning : theme.loss)
                            ctx.fill()
                            if (isSelected || item.mine) {
                                ctx.lineWidth = 2
                                ctx.strokeStyle = String(isSelected ? theme.text : theme.accent)
                                ctx.stroke()
                            }
                        }
                    }
                }
            }
            Rectangle {  // playhead
                visible: timeline.now >= timeline.viewStart && timeline.now <= timeline.viewEnd
                x: timeline.xOf(timeline.now) - width / 2
                y: timeline.railY - theme.em * 0.75
                z: 4
                width: 2
                height: theme.em * 1.5
                radius: 1
                color: theme.accent
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: -height / 2
                    width: theme.em * 0.55
                    height: width
                    radius: width / 2
                    color: theme.accent
                }
            }
            MouseArea {
                id: timelineArea
                anchors.fill: parent
                hoverEnabled: true
                property real pressX: 0
                property bool moved: false
                cursorShape: timeline.hoverKey !== "" || backend.replayActive ? Qt.PointingHandCursor
                           : timeline.zoomed ? Qt.OpenHandCursor : Qt.ArrowCursor
                onPressed: function(mouse) { pressX = mouse.x; moved = false }
                onPositionChanged: function(mouse) {
                    if (pressed && Math.abs(mouse.x - pressX) > 4 && timeline.zoomed) {
                        moved = true
                        timeline.moveBy(-(mouse.x - pressX) / timeline.railWidth * timeline.viewSpan)
                        pressX = mouse.x
                        return
                    }
                    timeline.hoverKey = timeline.markerAt(mouse.x, mouse.y)
                    timeline.hoverTime = timeline.timeAt(mouse.x)
                }
                onExited: { timeline.hoverKey = ""; timeline.hoverTime = -1 }
                onClicked: function(mouse) {
                    if (moved) return
                    var key = timeline.markerAt(mouse.x, mouse.y)
                    if (key !== "") {
                        backend.selectIncident(key)
                        if (root.canJump) backend.jumpTo(key, "")
                        root.showSelected()
                    } else if (backend.replayActive) {
                        backend.seek(timeline.timeAt(mouse.x))
                    }
                }
                onDoubleClicked: { timeline.zoomStart = -1; timeline.zoomEnd = -1 }
                onWheel: function(wheel) {
                    if (wheel.angleDelta.y !== 0) timeline.zoomAt(Math.pow(0.998, wheel.angleDelta.y), wheel.x)
                }
            }
            Rectangle {  // marker label, or time under mouse
                visible: timelineArea.containsMouse && (timeline.hoverKey !== "" || timeline.hoverTime >= 0)
                x: Math.max(0, Math.min(timelineArea.mouseX - width / 2, timeline.width - width))
                y: 0
                z: 5
                width: hoverText.implicitWidth + theme.em * 0.7
                height: hoverText.implicitHeight + 2
                radius: height / 2
                color: theme.raised
                border.width: 1
                border.color: timeline.hoverKey !== "" ? theme.accent : theme.border
                Text {
                    id: hoverText
                    anchors.centerIn: parent
                    text: timeline.hoverKey !== "" ? timeline.labelOf(timeline.hoverKey) : root.clock(timeline.hoverTime)
                    color: theme.text
                    font.pointSize: theme.fontPoint * 0.75
                    font.features: { "tnum": 1 }
                }
            }
            TpButton {  // zoomed: whole session again
                visible: timeline.zoomed
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                z: 6
                flat: true
                implicitHeight: Math.round(theme.em * 1.6)
                text: i18n.tr("Whole session")
                onClicked: { timeline.zoomStart = -1; timeline.zoomEnd = -1 }
            }
        }

        // Drivers with most incidents: click to see their incidents only
        ListView {
            id: drivers
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.em * 2.0)
            visible: count > 1 || backend.driverFilter !== ""
            orientation: ListView.Horizontal
            spacing: theme.em * 0.35
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: backend.drivers
            delegate: AbstractButton {
                id: chip
                required property var modelData
                readonly property bool active: backend.driverFilter === modelData.name
                height: drivers.height
                width: chipRow.implicitWidth + theme.em * 1.1
                hoverEnabled: true
                focusPolicy: Qt.NoFocus
                onClicked: backend.setDriverFilter(modelData.name)
                ToolTip.visible: hovered && modelData.car !== ""
                ToolTip.text: modelData.car
                ToolTip.delay: 500
                background: Rectangle {
                    radius: height / 2
                    color: chip.active ? theme.accent : chip.hovered ? theme.hover : theme.raised
                    border.width: chip.active ? 0 : 1
                    border.color: chip.modelData.mine ? theme.accent : theme.border
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
                contentItem: Item {
                    Row {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: theme.em * 0.4
                        Text {
                            text: chip.modelData.name
                            color: chip.active ? "white" : theme.text
                            font.pointSize: theme.fontPoint * 0.9
                        }
                        Text {
                            text: chip.modelData.count
                            color: chip.active ? "white" : theme.dimText
                            font.pointSize: theme.fontPoint * 0.9
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            focus: true
            activeFocusOnTab: true
            model: backend.incidentRows
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: { backend.moveIncidentSelection(-1); root.showSelected() }
            Keys.onDownPressed: { backend.moveIncidentSelection(1); root.showSelected() }
            Keys.onReturnPressed: backend.jumpTo(backend.selectedIncident, "")
            Keys.onEnterPressed: backend.jumpTo(backend.selectedIncident, "")
            displaced: Transition { NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic } }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 } }

            delegate: Rectangle {
                id: row
                required property int index
                required property string key
                required property string timeText
                required property string driver
                required property string other
                required property bool wall
                required property bool mine
                required property int count
                required property string driverCar
                required property string otherCar
                required property string focused
                readonly property bool selected: key === backend.selectedIncident

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * (driverCar !== "" || otherCar !== "" ? 3.1 : 2.4))
                radius: theme.em * 0.5
                color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, rowArea.containsMouse ? 0.22 : 0.15)
                     : rowArea.containsMouse ? theme.hover : "transparent"
                Behavior on color { ColorAnimation { duration: 110 } }

                Rectangle {  // my car involved
                    visible: row.mine
                    x: 2
                    width: 3
                    height: parent.height - theme.em * 0.8
                    anchors.verticalCenter: parent.verticalCenter
                    radius: 1.5
                    color: theme.accent
                }
                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: { list.forceActiveFocus(); backend.selectIncident(row.key) }
                    onClicked: function(mouse) { if (mouse.button === Qt.RightButton) root.openMenu(row, rowArea, mouse.x, mouse.y) }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.jumpTo(row.key, "") }
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.6
                    anchors.rightMargin: theme.em * 0.4
                    spacing: theme.em * 0.55
                    Text {
                        text: row.timeText
                        color: theme.dimText
                        font.features: { "tnum": 1 }
                    }
                    Icon {
                        glyph: row.wall ? "" : ""  // warning (wall), lightning (cars)
                        size: theme.em * 0.9
                        color: row.wall ? theme.warning : theme.loss
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        RowLayout {  // drivers, car followed by replay camera in bold with camera mark
                            Layout.fillWidth: true
                            spacing: theme.em * 0.35
                            Text {
                                Layout.fillWidth: true
                                Layout.maximumWidth: implicitWidth
                                textFormat: Text.StyledText
                                text: (row.focused === "driver" ? "<b>" + root.escaped(row.driver) + "</b>" : root.escaped(row.driver))
                                      + "<font color=\"" + theme.dimText + "\">  ↔  </font>"
                                      + (row.wall ? "<i>" + root.escaped(row.other) + "</i>"
                                         : row.focused === "other" ? "<b>" + root.escaped(row.other) + "</b>" : root.escaped(row.other))
                                color: theme.text
                                elide: Text.ElideRight
                            }
                            Icon {
                                visible: row.focused !== ""
                                glyph: ""  // camera
                                size: theme.em * 0.8
                                color: theme.accent
                            }
                            Item { Layout.fillWidth: true }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: row.driverCar !== "" || row.otherCar !== ""
                                  ? (row.driverCar || "?") + (row.wall ? "" : "  ↔  " + (row.otherCar || "?")) : ""
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.82
                            elide: Text.ElideRight
                        }
                    }
                    Rectangle {  // contacts merged
                        visible: row.count > 1
                        implicitHeight: mergedText.implicitHeight + 2
                        implicitWidth: mergedText.implicitWidth + theme.em * 0.7
                        radius: height / 2
                        color: theme.hover
                        ToolTip.visible: mergedArea.containsMouse
                        ToolTip.text: i18n.tr("Contacts of the same cars a moment apart, shown as one incident")
                        ToolTip.delay: 400
                        MouseArea { id: mergedArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        Text {
                            id: mergedText
                            anchors.centerIn: parent
                            text: "×" + row.count
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                            font.features: { "tnum": 1 }
                        }
                    }
                    TpButton {
                        id: jumpButton
                        visible: root.canJump && (row.selected || rowArea.containsMouse || hovered)
                        glyph: ""  // play
                        flat: !row.selected
                        accent: row.selected
                        implicitHeight: Math.round(theme.em * 2.0)
                        tip: (root.live ? i18n.tr("Replay This Moment") : i18n.tr("Jump to Incident")) + " (" + i18n.tr("double click") + ")"
                        onClicked: backend.jumpTo(row.key, "")
                    }
                }
            }

            // Empty list: no session, no incident, nothing matching filters
            Column {
                anchors.centerIn: parent
                width: parent.width - theme.em * 4
                visible: list.count === 0
                spacing: theme.em * 0.6
                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    glyph: ""
                    size: theme.em * 2.2
                    color: theme.dimText
                }
                Text {
                    width: parent.width
                    text: root.counts.all > 0 ? i18n.tr("No incident matches the filters.")
                        : backend.inSession ? i18n.tr("No incident in this session.")
                        : i18n.tr("Incidents show once a session or a replay is loaded in the game.")
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        // Jump settings
        RowLayout {
            Layout.fillWidth: true
            visible: root.counts.all > 0
            spacing: theme.em * 0.5
            Text { text: i18n.tr("Seconds Before"); color: theme.text }
            SpinBox {
                id: secondsBox
                from: 0
                to: 60
                editable: true
                value: backend.secondsBefore
                implicitWidth: Math.round(theme.em * 7)
                implicitHeight: Math.round(theme.em * 2.2)
                onValueModified: backend.setSecondsBefore(value)
                ToolTip.visible: hovered
                ToolTip.text: i18n.tr("Replay starts this long before the contact")
                ToolTip.delay: 600
            }
            Item { Layout.fillWidth: true }
            TpButton {
                accent: true
                glyph: ""  // play
                text: root.live ? i18n.tr("Replay This Moment") : i18n.tr("Jump to Incident")
                tip: root.live ? i18n.tr("The replay of this session opens at the selected incident (back to live from playback)")
                               : i18n.tr("Replay open in game goes to selected incident, camera on your car if involved")
                enabled: root.canJump && backend.selectedIncident !== ""
                onClicked: backend.jumpTo(backend.selectedIncident, "")
            }
        }
    }
}
