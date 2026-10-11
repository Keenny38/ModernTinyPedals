import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Playback of lap viewer, under charts & simple view (same place in both): back / play / forward, loop of passage
// A-B, speed, position along lap (drag or click: cursor there, playback stopped), cursor position. Keys of charts
// still work (Space, arrows, comma & period)
RowLayout {
    id: bar

    property var chart
    readonly property bool ready: chart !== null && chart !== undefined

    spacing: theme.em * 0.2
    visible: ready && chart.legendLaps.length > 0

    // Back / forward in time, held: repeated (rewind / fast forward)
    TpButton {
        glyph: ""  // rewind
        flat: true
        implicitHeight: theme.em * 1.8
        enabled: backend.referenceLapTime > 0
        autoRepeat: true
        tip: i18n.tr("2 s back (hold: rewind)")
        onClicked: bar.chart.skipTime(-bar.chart.skipStep)
    }
    TpButton {
        objectName: "playButton"
        glyph: bar.ready && bar.chart.playing ? "" : ""  // pause, play
        flat: true
        implicitHeight: theme.em * 1.8
        tip: bar.ready && bar.chart.hasRange ? i18n.tr("Play passage between markers A and B (Space)")
                                             : i18n.tr("Play lap: cursor follows reference lap at real speed (Space)")
        onClicked: bar.chart.togglePlay()
    }
    TpButton {
        glyph: ""  // fast forward
        flat: true
        implicitHeight: theme.em * 1.8
        enabled: backend.referenceLapTime > 0
        autoRepeat: true
        tip: i18n.tr("2 s forward (hold: fast forward)")
        onClicked: bar.chart.skipTime(bar.chart.skipStep)
    }
    TpButton {
        visible: bar.ready && bar.chart.hasRange
        glyph: ""  // repeat
        flat: true
        implicitHeight: theme.em * 1.8
        checked: bar.ready && bar.chart.playLoop
        tip: i18n.tr("Play only passage between markers A and B, again and again") + " (L)"
        onClicked: bar.chart.playLoop = !bar.chart.playLoop
    }
    // Playback speed: slider on speed steps, value clicked: normal speed again
    Slider {
        id: speedSlider
        Layout.preferredWidth: theme.em * 6.5
        implicitHeight: theme.em * 1.8
        leftPadding: theme.em * 0.5
        rightPadding: theme.em * 0.5
        from: 0
        to: bar.ready ? bar.chart.playSpeeds.length - 1 : 1
        stepSize: 1
        snapMode: Slider.SnapAlways
        focusPolicy: Qt.NoFocus
        value: bar.ready ? bar.chart.playSpeeds.indexOf(bar.chart.playSpeed) : 0
        onMoved: bar.chart.playSpeed = bar.chart.playSpeeds[Math.round(value)]
        ToolTip.visible: hovered && !pressed
        ToolTip.text: i18n.tr("Playback speed") + " (, .)"
        ToolTip.delay: 600
        background: Item {
            x: speedSlider.leftPadding
            width: speedSlider.availableWidth
            height: speedSlider.height
            Rectangle {  // track, filled up to speed
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 3
                radius: 1.5
                color: theme.border
                Rectangle {
                    width: speedSlider.visualPosition * parent.width
                    height: parent.height
                    radius: parent.radius
                    color: theme.accent
                }
            }
            Repeater {  // one notch per speed step, normal speed marked
                model: bar.ready ? bar.chart.playSpeeds : []
                Rectangle {
                    required property int index
                    required property real modelData
                    x: index / (bar.chart.playSpeeds.length - 1) * parent.width - width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    width: modelData === 1 ? 2 : 1
                    height: modelData === 1 ? theme.em * 0.8 : theme.em * 0.45
                    color: index <= speedSlider.value ? theme.accent : theme.border
                }
            }
        }
        handle: Rectangle {
            x: speedSlider.leftPadding + speedSlider.visualPosition * (speedSlider.availableWidth - width)
            y: (speedSlider.height - height) / 2
            width: theme.em * 0.95
            height: width
            radius: width / 2
            color: speedSlider.pressed ? Qt.darker(theme.accent, 1.15) : theme.accent
            border.width: 2
            border.color: theme.base
            scale: speedSlider.pressed || speedSlider.hovered ? 1.15 : 1
            Behavior on scale { NumberAnimation { duration: 120 } }
        }
    }
    TpButton {
        text: bar.ready ? bar.chart.playSpeed + "×" : ""
        flat: true
        implicitHeight: theme.em * 1.8
        implicitWidth: theme.em * 3.2
        checked: bar.ready && bar.chart.playSpeed !== 1
        tip: i18n.tr("Back to normal speed")
        onClicked: bar.chart.playSpeed = 1
    }
    // Position along lap
    Slider {
        id: scrub
        objectName: "playbackScrub"
        Layout.fillWidth: true
        Layout.leftMargin: theme.em * 0.4
        implicitHeight: theme.em * 1.8
        from: 0
        to: bar.ready ? bar.chart.maxX : 1
        focusPolicy: Qt.NoFocus
        onPressedChanged: if (pressed && bar.ready) bar.chart.playing = false
        onMoved: bar.chart.setCursor(value, "key")
        ToolTip.visible: hovered && !pressed && !(bar.ready && bar.chart.hasCursor)
        ToolTip.text: i18n.tr("Drag to move along lap")
        ToolTip.delay: 600
        Binding on value {
            when: !scrub.pressed
            value: bar.ready && bar.chart.hasCursor ? bar.chart.cursorX : 0
        }
        background: Rectangle {
            x: scrub.leftPadding
            y: scrub.topPadding + (scrub.availableHeight - height) / 2
            width: scrub.availableWidth
            height: 4
            radius: 2
            color: theme.border
            Rectangle {
                width: scrub.visualPosition * parent.width
                height: parent.height
                radius: parent.radius
                color: theme.accent
                visible: bar.ready && bar.chart.hasCursor
            }
        }
        handle: Rectangle {
            x: scrub.leftPadding + scrub.visualPosition * (scrub.availableWidth - width)
            y: scrub.topPadding + (scrub.availableHeight - height) / 2
            width: theme.em * 1.05
            height: width
            radius: width / 2
            visible: (bar.ready && bar.chart.hasCursor) || scrub.pressed
            color: scrub.pressed ? Qt.darker(theme.accent, 1.15) : theme.accent
            border.width: 2
            border.color: theme.base
            scale: scrub.pressed || scrub.hovered ? 1.15 : 1
            Behavior on scale { NumberAnimation { duration: 120 } }
        }
    }
    Text {
        Layout.preferredWidth: theme.em * 13
        horizontalAlignment: Text.AlignRight
        text: bar.ready && bar.chart.hasCursor ? bar.chart.cursorTitle : ""
        color: theme.text
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
        elide: Text.ElideLeft
    }
}
