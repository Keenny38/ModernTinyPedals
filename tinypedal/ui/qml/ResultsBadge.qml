import QtQuick

// Session kind of race results: colored letter (R race, Q qualifying, P practice, W warmup)
Rectangle {
    id: badge
    property string code: ""
    readonly property color tone: code === "R" ? theme.warning : code === "Q" ? theme.purple
                                : code === "P" ? theme.accent : theme.dimText
    implicitWidth: Math.round(theme.em * 1.9)
    implicitHeight: implicitWidth
    radius: theme.em * 0.4
    color: Qt.rgba(tone.r, tone.g, tone.b, 0.16)
    border.width: 1
    border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.45)
    Text {
        anchors.centerIn: parent
        text: badge.code
        color: badge.tone
        font.weight: Font.Bold
        font.pointSize: theme.fontPoint * Math.max(badge.width / (theme.em * 1.9), 1)
    }
}
