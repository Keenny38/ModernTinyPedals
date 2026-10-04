import QtQuick

// Glyph of Segoe Fluent Icons / MDL2 Assets (hidden if no icon font installed)
Text {
    property string glyph: ""
    property real size: theme.em * 1.05
    text: glyph
    visible: theme.iconFont !== "" && glyph !== ""
    font.family: theme.iconFont
    font.pixelSize: size
    color: theme.text
    verticalAlignment: Text.AlignVCenter
    horizontalAlignment: Text.AlignHCenter
}
