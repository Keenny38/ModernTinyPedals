import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Playback bar, one transport look for the app: back / play / forward, loop, speed, position slider, position text.
// Lap viewer (chart set): under charts & simple view (same place in both), loop of passage A-B, position along lap
// (drag or click: cursor there, playback stopped). Keys of charts still work (Space, arrows, comma & period).
// Another player (session recorder) leaves chart unset, sets the values below and handles the signals; it may
// show frame by frame buttons and lap / incident / section marks on the position slider.
// Narrow bar: speed slider left out (speed button & keys stay), shorter position text: the position slider keeps room.
RowLayout {
    id: bar

    property var chart
    readonly property bool ready: chart !== null && chart !== undefined
    // State of the player (defaults: lap viewer charts)
    property bool canPlay: backend.referenceLapTime > 0
    property bool playing: ready && chart.playing
    property var speeds: ready ? chart.playSpeeds : [1]
    property real speed: ready ? chart.playSpeed : 1
    property bool loopShown: ready && chart.hasRange
    property bool loop: ready && chart.playLoop
    property real skipStep: ready ? chart.skipStep : 2
    property real duration: ready ? chart.maxX : 1
    property bool hasPosition: ready && chart.hasCursor
    property real position: hasPosition ? chart.cursorX : 0
    property string positionText: hasPosition ? chart.cursorTitle : ""
    property string playTip: ready && chart.hasRange ? i18n.tr("Play passage between markers A and B (Space)")
                                                     : i18n.tr("Play lap: cursor follows reference lap at real speed (Space)")
    property string loopTip: i18n.tr("Play only passage between markers A and B, again and again") + " (L)"
    property string scrubTip: i18n.tr("Drag to move along lap")
    property string backTip: i18n.tr("2 s back (hold: rewind)")
    property string forwardTip: i18n.tr("2 s forward (hold: fast forward)")
    property bool frameButtons: false  // previous / next recorded frame buttons
    property var laps: []  // lap marks on position slider (positions)
    property var incidents: []  // incident marks on position slider (positions)
    property real sectionStart: -1  // part shaded on position slider (start / end, -1: none or slider end)
    property real sectionEnd: -1
    readonly property bool narrow: width < theme.bpCompact

    // Requests (lap viewer: run on charts below)
    signal playToggled()
    signal skipped(real seconds)
    signal frameStepped(int frames)
    signal loopToggled()
    signal speedPicked(real speed)
    signal scrubPressed()
    signal seeked(real position)

    onPlayToggled: if (ready) chart.togglePlay()
    onSkipped: function(seconds) { if (ready) chart.skipTime(seconds) }
    onLoopToggled: if (ready) chart.playLoop = !chart.playLoop
    onSpeedPicked: function(speed) { if (ready) chart.playSpeed = speed }
    onScrubPressed: if (ready) chart.playing = false
    onSeeked: function(position) { if (ready) chart.setCursor(position, "key") }

    spacing: theme.space1
    visible: ready && chart.legendLaps.length > 0

    // Round transport buttons (one look for every player of the app): back / forward in time, held: repeated
    // (rewind / fast forward), play / pause larger
    TpTransportButton {
        objectName: "previousFrameButton"
        visible: bar.frameButtons
        glyph: "\uE892"  // previous track
        fallback: "|◀"
        enabled: bar.hasPosition
        autoRepeat: true
        tip: i18n.tr("Previous frame (Shift+Left)")
        onClicked: bar.frameStepped(-1)
    }
    TpTransportButton {
        glyph: "\uEB9E"  // rewind
        fallback: "«"
        enabled: bar.canPlay
        autoRepeat: true
        tip: bar.backTip
        onClicked: bar.skipped(-bar.skipStep)
    }
    TpTransportButton {
        objectName: "playButton"
        primary: true
        glyph: bar.playing ? "\uE769" : "\uE768"  // pause, play
        fallback: bar.playing ? "❚❚" : "▶"
        enabled: bar.canPlay || bar.playing
        tip: bar.playTip
        onClicked: bar.playToggled()
    }
    TpTransportButton {
        glyph: "\uEB9D"  // fast forward
        fallback: "»"
        enabled: bar.canPlay
        autoRepeat: true
        tip: bar.forwardTip
        onClicked: bar.skipped(bar.skipStep)
    }
    TpTransportButton {
        objectName: "nextFrameButton"
        visible: bar.frameButtons
        glyph: "\uE893"  // next track
        fallback: "▶|"
        enabled: bar.hasPosition
        autoRepeat: true
        tip: i18n.tr("Next frame (Shift+Right)")
        onClicked: bar.frameStepped(1)
    }
    TpTransportButton {
        objectName: "loopButton"
        visible: bar.loopShown
        glyph: "\uE8EE"  // repeat
        fallback: "⟲"
        current: bar.loop  // looping: accent tint & icon (Accessible checked)
        tip: bar.loopTip
        onClicked: bar.loopToggled()
    }
    // Playback speed: slider on speed steps (normal speed marked), value clicked: normal speed again
    TpSlider {
        id: speedSlider
        visible: !bar.narrow
        Layout.preferredWidth: theme.em * 6.5
        from: 0
        to: Math.max(bar.speeds.length - 1, 1)
        stepSize: 1
        snapMode: Slider.SnapAlways
        value: bar.speeds.indexOf(bar.speed)
        notches: bar.speeds.map(function(speed, index) { return index })
        markedValue: bar.speeds.indexOf(1)
        tip: i18n.tr("Playback speed") + " (, .)"
        onMoved: bar.speedPicked(bar.speeds[Math.round(value)])
    }
    TpButton {
        objectName: "speedButton"
        text: String(bar.speed).replace(".", theme.decimalPoint) + "×"
        flat: true
        size: "sm"
        implicitWidth: theme.em * 3.2
        checked: bar.speed !== 1
        tip: i18n.tr("Back to normal speed")
        onClicked: bar.speedPicked(1)
    }
    // Position: lap marks (top) and incidents (bottom, taller) on the track, section shaded
    TpSlider {
        id: scrub
        objectName: "playbackScrub"
        Layout.fillWidth: true
        Layout.minimumWidth: theme.em * 8
        Layout.leftMargin: theme.space3
        from: 0
        to: Math.max(bar.duration, 1e-6)
        fillShown: bar.hasPosition
        handleShown: bar.hasPosition
        tip: bar.hasPosition ? "" : bar.scrubTip
        onPressedChanged: if (pressed) bar.scrubPressed()
        onMoved: bar.seeked(value)
        Binding on value {
            when: !scrub.pressed
            value: bar.hasPosition ? bar.position : 0
        }
        // Over the track, under the handle (handle z 0, background z -1)
        Item {
            id: marks
            z: -0.5
            x: scrub.leftPadding
            width: scrub.availableWidth
            height: scrub.height
            visible: bar.laps.length > 0 || bar.incidents.length > 0 || bar.sectionStart >= 0 || bar.sectionEnd >= 0
            function xOf(value) { return value / Math.max(scrub.to, 1e-6) * width }
            Rectangle {
                visible: bar.sectionStart >= 0 || bar.sectionEnd >= 0
                x: marks.xOf(Math.max(bar.sectionStart, 0))
                width: Math.max(marks.xOf(bar.sectionEnd >= 0 ? bar.sectionEnd : scrub.to) - x, 1)
                height: parent.height
                radius: theme.radiusSm
                color: theme.tint(theme.accent, "selected")
            }
            Repeater {
                model: bar.laps
                Rectangle {
                    required property real modelData
                    x: Math.round(marks.xOf(modelData))
                    y: 0
                    width: 1
                    height: Math.round(marks.height * 0.3)
                    color: theme.dimText
                }
            }
            Repeater {
                model: bar.incidents
                Rectangle {
                    required property real modelData
                    x: Math.round(marks.xOf(modelData) - width / 2)
                    width: 2
                    height: Math.round(marks.height * 0.4)
                    anchors.bottom: parent.bottom
                    color: theme.loss
                }
            }
        }
    }
    Text {
        id: positionText
        objectName: "positionText"
        Layout.preferredWidth: bar.narrow ? theme.em * 7 : theme.em * 13
        Layout.minimumWidth: theme.em * 5
        horizontalAlignment: Text.AlignRight
        text: bar.positionText
        textFormat: Text.PlainText
        color: theme.text
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
        elide: Text.ElideLeft
        HoverHandler { id: positionHover }
        ToolTip.visible: positionHover.hovered && positionText.truncated
        ToolTip.text: positionText.text
        ToolTip.delay: theme.tipDelay
    }
}
