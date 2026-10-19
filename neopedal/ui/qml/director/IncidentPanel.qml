import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Incidents of the session (contacts between cars, or with walls; both sides listed by game merged):
// kind filter, my car only, driver chips (most incidents first), timeline (marker: jump there, click elsewhere:
// replay goes there, wheel: zoom, drag: move, double click: whole session; playhead follows replay),
// list (double click or Enter: jump, right click: camera & driver), copy or export to CSV.
// In a live session, jumping opens the replay of the session (back to live from playback).
// Kinds told by shape too (colorblind): wall ■ square marker, contact between cars ● round marker.
Item {
    id: root

    readonly property var counts: replays.counts
    property var menuEntries: []  // row menu: text, action (jump, filter), driver
    property string menuKey: ""  // incident of row menu
    readonly property bool canJump: replays.inSession && !replays.lastSession
    readonly property bool live: replays.inSession && !replays.replayActive  // jump: replay of live session
    // Replay clock of last game answer, read once per answer (playhead timer ticks between answers)
    readonly property real replayTime: replays.replayTime
    readonly property real replayRate: replays.replayRate
    readonly property real timeReceived: replays.timeReceived

    function escaped(text) { return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    function showSelected() {
        var index = replays.incidentIndex(replays.selectedIncident)
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
                    if (modelData.action === "jump") replays.jumpTo(root.menuKey, modelData.driver)
                    else if (replays.driverFilter !== modelData.driver) replays.setDriverFilter(modelData.driver)  // toggles
                }
            }
            onObjectAdded: function(index, object) { rowMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { rowMenu.removeAction(object) }
        }
        onClosed: list.forceActiveFocus()
    }

    TpMenu {
        id: exportMenu
        width: Math.max(implicitWidth, theme.em * 17)
        Action { text: i18n.tr("Copy to Clipboard"); onTriggered: replays.copyIncidents() }
        Action { text: i18n.tr("Export CSV..."); onTriggered: replays.exportIncidents() }
        onClosed: exportButton.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        anchors.topMargin: 0
        spacing: theme.em * 0.5

        // Kind filter, my car, export, previous / next incident
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TpSegmented {
                visible: root.counts.all > 0
                name: i18n.tr("Incidents")
                options: [i18n.tr("All") + "  " + root.counts.all, i18n.tr("Cars") + "  " + root.counts.cars,
                          i18n.tr("Walls") + "  " + root.counts.walls]
                currentIndex: replays.incidentFilter
                maxWidth: root.width * 0.5
                onActivated: function(index) { replays.setIncidentFilter(index) }
            }
            Pill {  // game in menus: incidents of the session left
                visible: replays.lastSession && root.counts.all > 0
                text: i18n.tr("Last Session")
                tint: theme.warning
                glyph: ""  // history
            }
            Item { Layout.fillWidth: true }
            TpSwitch {
                visible: replays.playerName !== ""
                text: i18n.tr("My car")
                tip: i18n.tr("Incidents of %1 only").arg(replays.playerName)
                checked: replays.mineOnly
                onToggled: replays.setMineOnly(checked)
            }
            TpButton {
                id: exportButton
                glyph: ""  // export
                fallback: "CSV"
                flat: true
                tip: i18n.tr("Copy or export incidents shown")
                enabled: root.counts.shown > 0
                checked: exportMenu.visible
                onClicked: exportMenu.visible ? exportMenu.close()  // right aligned: never cut by window
                                              : exportMenu.popup(exportButton, exportButton.width - exportMenu.width, exportButton.height + 4)
            }
            TpButton {
                glyph: ""  // chevron up
                fallback: "▲"
                flat: true
                tip: i18n.tr("Previous incident")
                enabled: root.counts.shown > 0
                onClicked: { replays.jumpNext(-1); root.showSelected() }
            }
            TpButton {
                glyph: ""  // chevron down
                fallback: "▼"
                flat: true
                tip: i18n.tr("Next incident")
                enabled: root.counts.shown > 0
                onClicked: { replays.jumpNext(1); root.showSelected() }
            }
        }

        // Timeline of session: incident markers drawn at once (long races: hundreds), replay playhead.
        // Wheel: zoom at mouse, drag: move zoomed view, double click: whole session.
        Item {
            id: timeline
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.em * 3.2)
            visible: root.counts.all > 0 || (replays.replayActive && replays.replayTime >= 0)
            // Playhead past known end: whole minutes, timeline span not changed on every playhead step
            readonly property real fullEnd: Math.max(replays.timelineEnd, Math.ceil(now * 1.02 / 60) * 60, 60)
            property real zoomStart: -1  // shown part of session, -1: whole session
            property real zoomEnd: -1
            readonly property real viewStart: zoomStart >= 0 ? Math.min(zoomStart, fullEnd - 30) : 0
            readonly property real viewEnd: zoomEnd > 0 ? Math.min(zoomEnd, fullEnd) : fullEnd
            readonly property real viewSpan: Math.max(viewEnd - viewStart, 1)
            readonly property bool zoomed: zoomStart >= 0
            readonly property real pad: theme.space4
            readonly property real railWidth: Math.max(width - pad * 2, 1)
            readonly property real railY: Math.round(height * 0.36)
            readonly property real now: playhead.now  // replay playhead, -1: no replay
            property string hoverKey: ""
            property real hoverTime: -1
            readonly property real step: {
                var steps = [10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600]
                var count = Math.max(2, Math.min(Math.floor(railWidth / (theme.em * 5)), 38))  // ticks: 40 at most
                for (var i = 0; i < steps.length; i++) if (viewSpan / steps[i] <= count) return steps[i]
                return 43200
            }
            readonly property real firstTick: Math.max(step, Math.ceil(viewStart / step) * step)
            function xOf(seconds) { return pad + railWidth * (seconds - viewStart) / viewSpan }
            function timeAt(px) { return Math.max(0, Math.min(viewStart + (px - pad) / railWidth * viewSpan, fullEnd)) }
            // Markers read from their items (made once per incident): no model data asked to Python per mouse move
            function markerAt(px, py) {  // nearest marker under mouse, "" if none
                if (Math.abs(py - railY) > theme.em * 0.9) return ""
                var best = theme.em * 0.6, key = ""
                for (var i = 0; i < markers.count; i++) {
                    var marker = markers.itemAt(i)
                    if (!marker) continue
                    var gap = Math.abs(markerLayer.x + marker.centerX - px)
                    if (gap < best || (gap === best && marker.shown)) { best = gap; key = marker.key }
                }
                return key
            }
            function labelOf(key) {
                for (var i = 0; i < markers.count; i++) {
                    var marker = markers.itemAt(i)
                    if (marker && marker.key === key) return marker.label
                }
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

            LiveClock {  // playhead moves between game answers at measured rate
                id: playhead
                time: replays.replayActive ? root.replayTime : -1
                received: root.timeReceived
                rate: root.replayRate
                triggeredOnStart: true  // 4 moves a second (LiveClock interval): page drawn again on each
                active: timeline.visible && replays.replayActive && pageState.active
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
                    color: theme.tint(theme.accent, 0.45)
                }
            }
            Repeater {  // time ticks: fixed items, values follow zoom (no delegate made again on wheel or drag)
                model: 40
                Item {
                    id: tick
                    required property int index
                    readonly property real value: timeline.firstTick + index * timeline.step
                    visible: value < timeline.viewEnd - timeline.step * 0.2
                    x: visible ? timeline.xOf(value) : 0
                    Rectangle { x: -0.5; y: timeline.railY + theme.space2; width: 1; height: theme.em * 0.3; color: theme.border }
                    Text {
                        x: -width / 2
                        y: timeline.railY + theme.space4
                        text: tick.visible ? playhead.format(tick.value) : ""
                        color: theme.dimText
                        font.pointSize: theme.fontTiny
                        font.features: { "tnum": 1 }
                    }
                }
            }
            Repeater {  // lap starts of car followed by camera (as game shows on its timeline)
                model: replays.lapMarks
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
                        font.pointSize: theme.fontTiny
                        font.features: { "tnum": 1 }
                    }
                }
            }
            Item {  // incident markers: dots placed in a layer moved by drag & scaled by zoom (nothing repainted;
                    // hover or pick changes two dots), my car & selected or hovered on top, ringed.
                    // Model synced by incident: a new incident adds its dot, filters & selection change roles only.
                id: markerLayer
                objectName: "incidentMarkers"
                readonly property real scaleX: timeline.railWidth / timeline.viewSpan  // pixels per second
                x: timeline.pad - timeline.viewStart * scaleX
                Repeater {
                    id: markers
                    model: replays.incidentMarkers
                    Rectangle {
                        id: marker
                        required property string key
                        required property real time
                        required property bool wall
                        required property bool mine
                        required property bool shown
                        required property string label
                        required property bool selected
                        readonly property real centerX: time * markerLayer.scaleX
                        readonly property bool hovered: key === timeline.hoverKey
                        readonly property bool ringed: selected || mine
                        readonly property real dot: theme.em * (selected ? 0.5 : hovered ? 0.43 : mine ? 0.37 : 0.28)
                        visible: markerLayer.x + centerX >= timeline.pad - 8 && markerLayer.x + centerX <= timeline.width - timeline.pad + 8
                        z: selected || hovered ? 2 : mine ? 1 : 0
                        width: dot * 2 + (ringed ? 2 : 0)  // ring centered on dot edge
                        height: width
                        // Wall: square, contact between cars: round (shape tells the kind, not color alone)
                        radius: marker.wall ? Math.max(1, width * 0.15) : width / 2
                        x: centerX - width / 2
                        y: timeline.railY - height / 2
                        opacity: shown ? 1 : 0.18
                        color: wall ? theme.warning : theme.loss
                        border.width: ringed ? 2 : 0
                        border.color: selected ? theme.text : theme.accent
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
                cursorShape: timeline.hoverKey !== "" || replays.replayActive ? Qt.PointingHandCursor
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
                        replays.selectIncident(key)
                        if (root.canJump) replays.jumpTo(key, "")
                        root.showSelected()
                    } else if (replays.replayActive) {
                        replays.seek(timeline.timeAt(mouse.x))
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
                width: hoverText.implicitWidth + theme.padCard
                height: hoverText.implicitHeight + 2
                radius: height / 2
                color: theme.raised
                border.width: 1
                border.color: timeline.hoverKey !== "" ? theme.accent : theme.border
                Text {
                    id: hoverText
                    anchors.centerIn: parent
                    text: timeline.hoverKey !== "" ? timeline.labelOf(timeline.hoverKey) : playhead.format(timeline.hoverTime)
                    color: theme.text
                    font.pointSize: theme.fontCaption
                    font.features: { "tnum": 1 }
                }
            }
            TpButton {  // zoomed: whole session again
                visible: timeline.zoomed
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                z: 6
                flat: true
                size: "xs"
                text: i18n.tr("Whole session")
                onClicked: { timeline.zoomStart = -1; timeline.zoomEnd = -1 }
            }
        }

        // Drivers with most incidents: click to see their incidents only (dot: my car)
        ListView {
            id: drivers
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.em * 2.0)
            visible: count > 1 || replays.driverFilter !== ""
            orientation: ListView.Horizontal
            spacing: theme.space3
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: replays.driverChips  // synced by driver: chips kept when counts change
            delegate: TpChip {
                id: chip
                required property string name
                required property int incidents
                required property bool mine
                required property string car
                height: drivers.height
                text: name
                count: incidents
                showDot: mine
                dotColor: theme.accent
                tip: car
                selected: replays.driverFilter === chip.name
                onClicked: replays.setDriverFilter(chip.name)
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            focus: true
            activeFocusOnTab: true
            model: replays.incidentRows
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true  // rows scrolled out fed again with other incidents (see delegate onPooled)
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: { replays.moveIncidentSelection(-1); root.showSelected() }
            Keys.onDownPressed: { replays.moveIncidentSelection(1); root.showSelected() }
            Keys.onReturnPressed: replays.jumpTo(replays.selectedIncident, "")
            Keys.onEnterPressed: replays.jumpTo(replays.selectedIncident, "")
            Keys.onShortcutOverride: function(event) {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                    event.accepted = true
            }
            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }

            delegate: Item {
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
                required property bool selected  // role changed for two rows on selection, no binding per row
                // Reused row: fed other incident values at once, no color animation from the old incident
                property bool live: true
                ListView.onPooled: { live = false; opacity = 1 }  // add transition may have been running
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * (driverCar !== "" || otherCar !== "" ? 3.1 : 2.4))
                Accessible.role: Accessible.ListItem
                Accessible.name: row.timeText + ", " + (row.wall ? i18n.tr("Wall") : i18n.tr("Contact")) + ", "
                                 + row.driver + (row.wall ? "" : ", " + row.other)

                TpListRow {
                    id: rowBack
                    anchors.fill: parent
                    animate: row.live
                    hovered: rowArea.containsMouse
                    selected: row.selected
                }
                FocusRing { target: rowBack; visible: row.selected && list.activeFocus }

                Rectangle {  // my car involved
                    visible: row.mine
                    x: 2
                    width: 3
                    height: parent.height - theme.space5
                    anchors.verticalCenter: parent.verticalCenter
                    radius: 1.5
                    color: theme.accent
                }
                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: { list.forceActiveFocus(); replays.selectIncident(row.key) }
                    onClicked: function(mouse) { if (mouse.button === Qt.RightButton) root.openMenu(row, rowArea, mouse.x, mouse.y) }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) replays.jumpTo(row.key, "") }
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.space4
                    anchors.rightMargin: theme.space3
                    spacing: theme.space4
                    Text {
                        text: row.timeText
                        color: theme.dimOn(rowBack.color)
                        font.features: { "tnum": 1 }
                    }
                    Icon {  // same shapes as the timeline markers without icon font
                        glyph: row.wall ? "" : ""  // warning (wall), lightning (cars)
                        fallback: row.wall ? "■" : "●"
                        size: theme.em * 0.9
                        color: row.wall ? theme.warning : theme.loss
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        RowLayout {  // drivers, car followed by replay camera in bold with camera mark
                            Layout.fillWidth: true
                            spacing: theme.space3
                            Text {
                                Layout.fillWidth: true
                                Layout.maximumWidth: implicitWidth
                                textFormat: Text.StyledText
                                text: (row.focused === "driver" ? "<b>" + root.escaped(row.driver) + "</b>" : root.escaped(row.driver))
                                      + "<font color=\"" + theme.dimOn(rowBack.color) + "\">  ↔  </font>"
                                      + (row.wall ? "<i>" + root.escaped(row.other) + "</i>"
                                         : row.focused === "other" ? "<b>" + root.escaped(row.other) + "</b>" : root.escaped(row.other))
                                color: theme.text
                                elide: Text.ElideRight
                            }
                            Icon {
                                visible: row.focused !== ""
                                glyph: ""  // camera
                                fallback: "◉"
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
                            color: theme.dimOn(rowBack.color)
                            font.pointSize: theme.fontSmall
                            elide: Text.ElideRight
                        }
                    }
                    Rectangle {  // contacts merged
                        visible: row.count > 1
                        implicitHeight: mergedText.implicitHeight + 2
                        implicitWidth: mergedText.implicitWidth + theme.padCard
                        radius: height / 2
                        color: theme.hover
                        ToolTip.visible: mergedArea.containsMouse
                        ToolTip.text: mergedArea.containsMouse
                            ? i18n.tr("Contacts of the same cars a moment apart, shown as one incident") : ""
                        ToolTip.delay: theme.tipDelay
                        MouseArea { id: mergedArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        Text {
                            id: mergedText
                            anchors.centerIn: parent
                            text: "×" + row.count
                            color: theme.dimOn(theme.hover)
                            font.pointSize: theme.fontCaption
                            font.features: { "tnum": 1 }
                        }
                    }
                    TpButton {  // jump button shown on the selected or hovered row (kept by pooled rows)
                        id: jumpButton
                        visible: root.canJump && (row.selected || rowArea.containsMouse || jumpButton.hovered)
                        glyph: ""  // play
                        fallback: "▶"
                        flat: !row.selected
                        accent: row.selected
                        size: "sm"
                        tip: (root.live ? i18n.tr("Replay This Moment") : i18n.tr("Jump to Incident"))
                             + " (" + i18n.tr("double click") + ")"
                        onClicked: replays.jumpTo(row.key, "")
                    }
                }
            }

            // Empty list: no session, no incident, nothing matching filters
            TpStateView {
                anchors.centerIn: parent
                empty: list.count === 0
                glyph: ""  // lightning
                text: root.counts.all > 0 ? i18n.tr("No incident matches the filters.")
                    : replays.inSession ? i18n.tr("No incident in this session.")
                    : i18n.tr("Incidents show once a session or a replay is loaded in the game.")
            }
        }

        // Jump settings
        RowLayout {
            Layout.fillWidth: true
            visible: root.counts.all > 0
            spacing: theme.em * 0.5
            Text { text: i18n.tr("Seconds Before"); color: theme.text }
            NumberField {
                id: secondsBox
                Layout.preferredWidth: theme.em * 5.5
                value: replays.secondsBefore
                minimum: 0
                maximum: 60
                suffix: " s"
                showRange: true
                tip: i18n.tr("Replay starts this long before the contact")
                onEdited: function(value) { replays.setSecondsBefore(Math.round(value)) }
            }
            Item { Layout.fillWidth: true }
            TpButton {
                accent: true
                glyph: ""  // play
                fallback: "▶"
                text: root.live ? i18n.tr("Replay This Moment") : i18n.tr("Jump to Incident")
                tip: root.live ? i18n.tr("The replay of this session opens at the selected incident (back to live from playback)")
                               : i18n.tr("Replay open in game goes to selected incident, camera on your car if involved")
                enabled: root.canJump && replays.selectedIncident !== ""
                onClicked: replays.jumpTo(replays.selectedIncident, "")
            }
        }
    }
}
