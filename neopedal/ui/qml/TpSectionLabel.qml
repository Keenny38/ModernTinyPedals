import QtQuick

// Small uppercase label above a group of controls ("DISPLAY", "SESSION"...)
Text {
    color: theme.dimText
    font.pointSize: theme.fontCaption
    font.weight: Font.DemiBold
    font.capitalization: Font.AllUppercase
    font.letterSpacing: 0.5
    elide: Text.ElideRight
    Accessible.role: Accessible.Heading
    Accessible.name: text
}
