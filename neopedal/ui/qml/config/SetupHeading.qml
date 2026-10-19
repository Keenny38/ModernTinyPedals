import QtQuick
import QtQuick.Layouts

// Section title of a setup wizard step
Text {
    Layout.fillWidth: true
    Layout.topMargin: theme.em * 0.4
    color: theme.text
    font.pointSize: theme.fontSubtitle
    font.weight: Font.DemiBold
    elide: Text.ElideRight
}
