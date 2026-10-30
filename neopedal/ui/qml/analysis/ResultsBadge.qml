import QtQuick
import QtQuick.Controls.Basic

// Session kind of race results or replays: colored letter (R race, Q qualifying, P practice, W warmup; game
// names like "R1" shown as given), one session color for every page (theme.sessionColor). Told by the letter,
// the color only adds to it. Session badge of every page (Results, Replays, Stats); tip: full session name.
Rectangle {
    id: badge
    property string code: ""
    property string tip: ""  // full session name: tooltip & screen readers
    readonly property color tone: theme.sessionColor(code.charAt(0))
    implicitWidth: Math.round(theme.em * 1.9)
    implicitHeight: implicitWidth
    radius: theme.radiusMd
    color: theme.tint(tone, "selected")
    border.width: 1
    border.color: theme.tint(tone, "outline")
    Accessible.role: Accessible.StaticText
    Accessible.name: tip !== "" ? tip : code
    HoverHandler { id: badgeHover; enabled: badge.tip !== "" }
    ToolTip.visible: badgeHover.hovered
    ToolTip.text: badge.tip
    ToolTip.delay: theme.tipDelay
    Text {
        anchors.centerIn: parent
        width: parent.width - theme.space1
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        text: badge.code
        textFormat: Text.PlainText
        color: badge.tone
        font.weight: Font.Bold
        font.pointSize: badge.code.length > 1 ? theme.fontLabel : theme.fontPoint * Math.max(badge.width / (theme.em * 1.9), 1)
    }
}
