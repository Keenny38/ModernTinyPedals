import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Playback of lap viewer, under charts & simple view (same place in both): back / play / forward, loop of passage
// A-B, speed, position along lap (drag or click: cursor there, playback stopped), cursor position. Keys of charts
// still work (Space, arrows, comma & period). Narrow charts: speed slider left out (speed button & , . keys stay),
// shorter cursor position: the position slider keeps room.
RowLayout {
    id: bar

    property var chart
    readonly property bool ready: chart !== null && chart !== undefined
    readonly property bool canPlay: backend.referenceLapTime > 0
    readonly property bool narrow: width < theme.bpCompact

    spacing: theme.space1
    visible: ready && chart.legendLaps.length > 0

    // Back / forward in time, held: repeated (rewind / fast forward)
    TpButton {
        glyph: ""  // rewind
        fallback: "«"
        flat: true
        size: "sm"
        enabled: bar.canPlay
        autoRepeat: true
        tip: i18n.tr("2 s back (hold: rewind)")
        onClicked: bar.chart.skipTime(-bar.chart.skipStep)
    }
    TpButton {
        objectName: "playButton"
        glyph: bar.ready && bar.chart.playing ? "" : ""  // pause, play
        fallback: bar.ready && bar.chart.playing ? "❚❚" : "▶"
        flat: true
        size: "sm"
        enabled: bar.canPlay || (bar.ready && bar.chart.playing)
        tip: bar.ready && bar.chart.hasRange ? i18n.tr("Play passage between markers A and B (Space)")
                                             : i18n.tr("Play lap: cursor follows reference lap at real speed (Space)")
        onClicked: bar.chart.togglePlay()
    }
    TpButton {
        glyph: ""  // fast forward
        fallback: "»"
        flat: true
        size: "sm"
        enabled: bar.canPlay
        autoRepeat: true
        tip: i18n.tr("2 s forward (hold: fast forward)")
        onClicked: bar.chart.skipTime(bar.chart.skipStep)
    }
    TpButton {
        visible: bar.ready && bar.chart.hasRange
        glyph: ""  // repeat
        fallback: "⟲"
        flat: true
        size: "sm"
        checked: bar.ready && bar.chart.playLoop
        tip: i18n.tr("Play only passage between markers A and B, again and again") + " (L)"
        onClicked: bar.chart.playLoop = !bar.chart.playLoop
    }
    // Playback speed: slider on speed steps (normal speed marked), value clicked: normal speed again
    TpSlider {
        id: speedSlider
        visible: !bar.narrow
        Layout.preferredWidth: theme.em * 6.5
        from: 0
        to: bar.ready ? bar.chart.playSpeeds.length - 1 : 1
        stepSize: 1
        snapMode: Slider.SnapAlways
        value: bar.ready ? bar.chart.playSpeeds.indexOf(bar.chart.playSpeed) : 0
        notches: bar.ready ? bar.chart.playSpeeds.map(function(speed, index) { return index }) : []
        markedValue: bar.ready ? bar.chart.playSpeeds.indexOf(1) : NaN
        tip: i18n.tr("Playback speed") + " (, .)"
        onMoved: bar.chart.playSpeed = bar.chart.playSpeeds[Math.round(value)]
    }
    TpButton {
        text: bar.ready ? String(bar.chart.playSpeed).replace(".", theme.decimalPoint) + "×" : ""
        flat: true
        size: "sm"
        implicitWidth: theme.em * 3.2
        checked: bar.ready && bar.chart.playSpeed !== 1
        tip: i18n.tr("Back to normal speed")
        onClicked: bar.chart.playSpeed = 1
    }
    // Position along lap
    TpSlider {
        id: scrub
        objectName: "playbackScrub"
        Layout.fillWidth: true
        Layout.minimumWidth: theme.em * 8
        Layout.leftMargin: theme.space3
        from: 0
        to: bar.ready ? bar.chart.maxX : 1
        fillShown: bar.ready && bar.chart.hasCursor
        handleShown: bar.ready && bar.chart.hasCursor
        tip: bar.ready && bar.chart.hasCursor ? "" : i18n.tr("Drag to move along lap")
        onPressedChanged: if (pressed && bar.ready) bar.chart.playing = false
        onMoved: bar.chart.setCursor(value, "key")
        Binding on value {
            when: !scrub.pressed
            value: bar.ready && bar.chart.hasCursor ? bar.chart.cursorX : 0
        }
    }
    Text {
        id: positionText
        Layout.preferredWidth: bar.narrow ? theme.em * 7 : theme.em * 13
        Layout.minimumWidth: theme.em * 5
        horizontalAlignment: Text.AlignRight
        text: bar.ready && bar.chart.hasCursor ? bar.chart.cursorTitle : ""
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
