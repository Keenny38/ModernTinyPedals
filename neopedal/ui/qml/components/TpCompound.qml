import QtQuick

// Tyre compound badge, as in overlays (Standings): compound letter on a rounded square of compound color
Rectangle {
    id: badge
    property string name: ""  // compound name or letter ("Soft", "Medium #2", "Hyper - Soft", "S")
    property string letter: theme.compoundLetter(name)
    property color fill: theme.compound(name)

    visible: name !== ""
    width: Math.round(theme.em * 1.1)
    height: width
    radius: Math.max(2, Math.round(width * 0.2))
    color: fill

    Text {
        anchors.centerIn: parent
        text: badge.letter
        textFormat: Text.PlainText
        color: theme.inkOn(badge.fill)
        font.pixelSize: Math.max(7, Math.round(badge.height * 0.66))  // letter fills the badge, as in overlays
        font.weight: Font.Bold
    }
}
