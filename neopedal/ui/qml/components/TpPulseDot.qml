import QtQuick

// Status dot: a few pulses when its state starts or page shows again, then still (no endless redraw)
Rectangle {
    id: dot
    property bool pulsing: false  // state to pulse for (page shown & animations on checked here)
    property real low: 0.35  // opacity at bottom of a pulse
    property int pulseDuration: theme.pulseDuration  // each half of a pulse (ms), one rhythm everywhere
    property int pulseEasing: Easing.InOutSine

    width: theme.em * 0.6
    height: width
    radius: width / 2

    SequentialAnimation on opacity {
        running: dot.pulsing && pageState.active && theme.animate
        loops: 3
        onRunningChanged: if (!running) dot.opacity = 1
        NumberAnimation { to: dot.low; duration: dot.pulseDuration; easing.type: dot.pulseEasing }
        NumberAnimation { to: 1; duration: dot.pulseDuration; easing.type: dot.pulseEasing }
    }
}
