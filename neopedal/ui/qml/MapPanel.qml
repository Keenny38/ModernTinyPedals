import QtQuick
import QtQuick.Controls.Basic
import NeoPedal

// Track map of the session or replay open in game: track & pit lane, cars (class color, number), car followed by
// the camera ringed in accent color, your car in white. Game on this computer: cars where its shared memory shows
// them, read 10 times a second like the Broadcast Director track map. Else between game answers, cars on track move
// along the track at their speed, with the playback clock (stopped while paused, faster while fast forward); cars
// in pit lane or off track glide to their new place.
// Click a car: camera on it. Wheel: zoom, drag: move, double click: whole map.
Item {
    id: root

    readonly property var view: replays.mapView
    readonly property bool loaded: view.road !== undefined
    // Glide well under the time between game answers (about 1.9 s replay, 4.8 s live): cars stop before the next
    // answer, scene idle (no redraw) in between. No glide while page or panel hidden: positions jump, nothing animates.
    readonly property int glide: replays.replayActive ? 1150 : 2900
    readonly property bool gliding: pageState.active && root.visible
    // Positions from shared memory (slot: [x, y]), {} if not read: each glides linearly to the next (0.25 s)
    readonly property var live: replays.mapLive
    readonly property bool liveTracking: Object.keys(live).length > 0

    // Track path & playback clock (session time now: replay time while a replay plays)
    readonly property var path: replays.mapPath
    readonly property bool hasPath: path.s !== undefined && path.s.length > 1
    readonly property bool replay: replays.replayActive
    readonly property real replayTime: replays.replayTime
    readonly property real replayRate: replays.replayRate
    readonly property real liveTime: replays.liveTime
    readonly property real timeReceived: replays.timeReceived
    property double now: Date.now()
    property real clock: 0
    function tick() {
        root.now = Date.now()
        var since = Math.max((root.now - root.timeReceived * 1000) / 1000, 0)
        root.clock = root.replay ? root.replayTime + root.replayRate * Math.min(since, 3)
                                 : root.liveTime + Math.min(since, 10)
    }
    onReplayTimeChanged: tick()
    onLiveTimeChanged: tick()
    Component.onCompleted: tick()
    // Shared memory positions: Date.now() of last car move (unchanged positions: no glide, no frame)
    property double liveMovedAt: 0
    readonly property int liveGlide: 250
    Timer {  // cars moved 30 times a second while the clock runs or shared memory cars glide (page & map shown)
        interval: 33
        repeat: true
        running: root.gliding && root.loaded
                 && (root.liveTracking ? root.now - root.liveMovedAt < root.liveGlide
                     : root.hasPath && (root.replay ? root.replayRate !== 0 : root.liveTime >= 0))
        onTriggered: if (root.liveTracking) root.now = Date.now(); else root.tick()
    }
    // Map position of distance along track path written in spot (x, y) and returned: no array made per car & tick,
    // worked out once for worldX & worldY (same distance & path: spot as is)
    function place(spot, distance) {
        var p = root.path
        if (spot.s === distance && spot.path === p)
            return spot
        spot.s = distance
        spot.path = p
        var s = p.s
        var n = s.length
        if (p.closed && p.length > 0) {
            distance = distance % p.length
            if (distance < 0)
                distance += p.length
        } else {
            distance = Math.max(0, Math.min(distance, s[n - 1]))
        }
        var low = 0
        var high = n - 1
        while (low < high) {
            var middle = (low + high + 1) >> 1
            if (s[middle] <= distance)
                low = middle
            else
                high = middle - 1
        }
        var next = low + 1 < n ? low + 1 : 0
        var span = (low + 1 < n ? s[low + 1] : p.length) - s[low]
        var ratio = span > 0 ? (distance - s[low]) / span : 0
        spot.x = p.xs[low] + (p.xs[next] - p.xs[low]) * ratio
        spot.y = p.ys[low] + (p.ys[next] - p.ys[low]) * ratio
        return spot
    }

    MapCanvas {
        id: canvas
        anchors.fill: parent
        anchors.margins: theme.em * 0.4
        anchors.topMargin: 0
        maxZoom: 40
        flipY: false  // game trackmap & car positions (x, -z): y down like overlay & in-game track map, else mirrored
        minX: root.view.minX || 0
        minY: root.view.minY || 0
        maxX: root.view.maxX || 1
        maxY: root.view.maxY || 1
        onSettled: if (root.loaded) replays.setMapScale(canvas.metersPerPixel)

        Item {  // track in a multisampled layer while shown (smooth edges, window without MSAA), cars outside
            objectName: "mapLines"
            anchors.fill: parent
            layer.enabled: root.gliding && root.loaded
            layer.samples: 4
            GpuShape {
                key: root.view.edge || ""
                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.18 : 0.25)
                revision: replays.mapRevision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            GpuShape {
                key: root.view.road || ""
                color: theme.dark ? Qt.lighter(theme.base, 1.6) : Qt.darker(theme.base, 1.1)
                revision: replays.mapRevision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
            GpuShape {
                key: root.view.pit || ""
                color: Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.35)
                revision: replays.mapRevision
                transform: Matrix4x4 { matrix: canvas.matrix }
            }
        }

        Repeater {
            model: root.loaded ? replays.mapCars : null
            Item {
                id: car
                required property string key
                required property real mapX
                required property real mapY
                required property string color
                required property string number
                required property string driver
                required property int position
                required property bool onCamera
                required property bool player
                required property bool inPit
                required property bool onTrack
                required property real pathS
                required property real speed
                required property real sampleTime
                required property real correction
                required property real receivedMs
                // Shared memory position if read; else on track: place of last answer moved along track by speed &
                // clock, easing from where it was shown (0.6 s); else world position glides to each new answer.
                // Screen position follows zoom at once
                readonly property var livePoint: root.live[key]
                readonly property bool tracked: livePoint !== undefined
                readonly property real ease: correction * Math.max(0, 1 - (root.now - receivedMs) / 600)
                readonly property var spot: ({ "s": NaN, "path": null, "x": 0, "y": 0 })  // root.place result
                readonly property var trackPoint: !liveMode && onTrack && root.hasPath ? spot : null
                readonly property real trackS: trackPoint
                    ? pathS + speed * Math.max(-2, Math.min(4, root.clock - sampleTime)) + ease : 0
                // Shared memory position: glides linearly from shown place to each new one on root ticks (no
                // animation restarted every answer: page idle once cars stop). Set by followLive only (tracked
                // binding may update after livePoint handlers): liveMode first, Behavior off before positions change
                property bool liveMode: false
                property real liveFromX: 0
                property real liveFromY: 0
                property real liveToX: 0
                property real liveToY: 0
                property double liveAt: 0  // Date.now() of last new position, 0: none
                readonly property real liveStep: Math.max(0, Math.min(1, (root.now - liveAt) / root.liveGlide))
                function followLive(animated) {
                    var point = livePoint
                    if (point === undefined) {
                        liveMode = false
                        liveAt = 0
                        return
                    }
                    var x = point[0], y = point[1]
                    if (liveAt > 0 && x === liveToX && y === liveToY) return
                    var glide = animated && root.gliding
                    var fromX = liveAt > 0 ? liveFromX + (liveToX - liveFromX) * liveStep : worldX  // shown place
                    var fromY = liveAt > 0 ? liveFromY + (liveToY - liveFromY) * liveStep : worldY
                    liveMode = true
                    liveFromX = glide ? fromX : x
                    liveFromY = glide ? fromY : y
                    liveToX = x
                    liveToY = y
                    liveAt = Date.now()
                    if (glide) root.liveMovedAt = liveAt
                }
                onLivePointChanged: followLive(true)
                Component.onCompleted: followLive(false)
                property real worldX: liveAt > 0 ? liveFromX + (liveToX - liveFromX) * liveStep
                                                 : trackPoint ? root.place(trackPoint, trackS).x : mapX
                property real worldY: liveAt > 0 ? liveFromY + (liveToY - liveFromY) * liveStep
                                                 : trackPoint ? root.place(trackPoint, trackS).y : mapY
                Behavior on worldX {
                    enabled: root.gliding && !car.liveMode && !car.onTrack
                    NumberAnimation { duration: root.glide; easing.type: Easing.OutSine }
                }
                Behavior on worldY {
                    enabled: root.gliding && !car.liveMode && !car.onTrack
                    NumberAnimation { duration: root.glide; easing.type: Easing.OutSine }
                }
                z: onCamera ? 3 : player ? 2 : 1

                Rectangle {
                    readonly property real size: theme.em * (car.onCamera ? 1.65 : 1.3)
                    x: canvas.screenX(car.worldX) - size / 2
                    y: canvas.screenY(car.worldY) - size / 2
                    width: size
                    height: size
                    radius: size / 2
                    color: car.color
                    opacity: car.inPit ? 0.45 : 1
                    border.width: car.onCamera || car.player ? 2 : 1
                    border.color: car.onCamera ? theme.accent : car.player ? "white" : Qt.rgba(0, 0, 0, 0.45)
                    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                    Text {
                        anchors.centerIn: parent
                        text: car.number
                        color: "white"
                        style: Text.Outline
                        styleColor: Qt.rgba(0, 0, 0, 0.5)
                        font.pointSize: theme.fontMicro
                        font.weight: Font.Bold
                    }
                    MouseArea {
                        id: carArea
                        anchors.fill: parent
                        anchors.margins: -3
                        hoverEnabled: true
                        cursorShape: replays.inSession ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: replays.watchCar(car.key)
                    }
                    ToolTip.visible: carArea.containsMouse
                    ToolTip.text: carArea.containsMouse  // text built only while hovered, not for every car on each answer
                        ? car.position + ". " + car.driver + (replays.inSession ? "\n" + i18n.tr("Camera on This Car") : "") : ""
                    ToolTip.delay: theme.tipDelay
                }
            }
        }

        // No map yet
        Column {
            anchors.centerIn: parent
            width: parent.width - theme.em * 4
            visible: !root.loaded
            spacing: theme.em * 0.6
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                glyph: ""  // map pin
                size: theme.em * 2.2
                color: theme.dimText
            }
            Text {
                width: parent.width
                text: replays.inSession ? i18n.tr("Asking game...")
                    : i18n.tr("Track map shows once a session or a replay is loaded in the game.")
                color: theme.dimText
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
    Connections {
        target: replays
        function onMapChanged() { canvas.reset(false) }
    }
}
