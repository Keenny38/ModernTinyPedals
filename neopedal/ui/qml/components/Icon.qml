import QtQuick

// Glyph of Segoe Fluent Icons / MDL2 Assets. Without icon font (Linux, older Windows): fallback text
// ("✓", "▾", "›"...) in the UI font, hidden when there is none
Text {
    property string glyph: ""
    property string fallback: ""
    property real size: theme.em * 1.05
    readonly property bool iconShown: theme.iconFont !== "" && glyph !== ""
    text: iconShown ? glyph : (theme.iconFont === "" ? fallback : "")
    visible: text !== ""
    font.family: iconShown ? theme.iconFont : Qt.application.font.family
    font.pixelSize: iconShown ? size : Math.round(size * 0.9)
    font.weight: iconShown ? Font.Normal : Font.DemiBold
    color: theme.text
    verticalAlignment: Text.AlignVCenter
    horizontalAlignment: Text.AlignHCenter
}
