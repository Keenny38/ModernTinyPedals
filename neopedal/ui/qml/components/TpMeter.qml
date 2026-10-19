import QtQuick

// Level / progress bar: value 0..1 filled in tint over a track (energy, share of valid laps, file progress)
//   TpMeter { Layout.fillWidth: true; value: 0.4; tint: theme.seriesEnergy; name: i18n.tr("Energy") }
Rectangle {
    id: meter
    property real value: 0
    property color tint: theme.accent
    property string name: ""  // screen readers: "Energy 40 %"
    property bool vertical: false
    // false: value & tint shown at once (value moved on by a timer: an eased move per tick never ends and keeps the
    // page drawn at every frame; rows of a recycled list fed another entry)
    property bool animated: true
    property real thickness: Math.max(3, Math.round(theme.em * 0.3))
    readonly property real clamped: Math.max(0, Math.min(isNaN(value) ? 0 : value, 1))

    implicitHeight: vertical ? theme.em * 4 : thickness
    implicitWidth: vertical ? thickness : theme.em * 6
    radius: Math.min(width, height) / 2
    color: theme.hover

    Accessible.role: Accessible.ProgressBar
    Accessible.name: (name !== "" ? name + " " : "") + Math.round(clamped * 100) + " %"

    Rectangle {
        x: 0
        y: meter.vertical ? meter.height - height : 0
        width: meter.vertical ? meter.width : meter.width * meter.clamped
        height: meter.vertical ? meter.height * meter.clamped : meter.height
        radius: meter.radius
        color: meter.tint
        Behavior on width { enabled: meter.animated && !meter.vertical; NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
        Behavior on height { enabled: meter.animated && meter.vertical; NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
        Behavior on color { enabled: meter.animated; ColorAnimation { duration: theme.motionBase } }
    }
}
