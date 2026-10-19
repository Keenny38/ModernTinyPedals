import QtQuick

// Session kind of race results or replays: colored letter (R race, Q qualifying, P practice, W warmup; game
// names like "R1" shown as given), one session color for every page (theme.sessionColor). Told by the letter,
// the color only adds to it.
Rectangle {
    id: badge
    property string code: ""
    readonly property color tone: theme.sessionColor(code.charAt(0))
    implicitWidth: Math.round(theme.em * 1.9)
    implicitHeight: implicitWidth
    radius: theme.radiusMd
    color: theme.tint(tone, "selected")
    border.width: 1
    border.color: theme.tint(tone, 0.45)
    Accessible.role: Accessible.StaticText
    Accessible.name: code
    Text {
        anchors.centerIn: parent
        width: parent.width - theme.space1
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        text: badge.code
        color: badge.tone
        font.weight: Font.Bold
        font.pointSize: badge.code.length > 1 ? theme.fontLabel : theme.fontPoint * Math.max(badge.width / (theme.em * 1.9), 1)
    }
}
