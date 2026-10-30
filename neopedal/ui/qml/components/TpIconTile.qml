import QtQuick

// Rounded square with an icon, tinted (strong: solid accent fill, white icon). Without icon font: the first
// letter of fallbackText. text: short text shown instead of the icon ("FR", "EN").
// Rows & cards of presets, modules, settings categories.
//   TpIconTile { glyph: ""; fallbackText: row.name; tint: theme.accent; strong: row.loaded }
Rectangle {
    id: tile
    property string glyph: ""
    property string fallbackText: ""
    property string text: ""
    property color tint: theme.accent
    property color glyphColor: strong ? theme.accentInk : tint
    property bool strong: false
    property bool neutral: false  // no tint: inactive item (dim icon on a plain surface)
    property real size: Math.round(theme.em * 2.1)

    implicitWidth: size
    implicitHeight: size
    radius: size > theme.controlHeight ? theme.radiusLg : theme.radiusMd
    // Translucent tints: same look on a card, a hovered card or a selected row
    color: strong ? (tint === theme.accent ? theme.accentFill : tint)
         : neutral ? theme.tint(theme.dimText, "subtle")
         : theme.tint(tint, "selected")
    Behavior on color { ColorAnimation { duration: theme.motionBase } }

    Text {
        anchors.centerIn: parent
        visible: tile.text !== ""
        text: tile.text
        textFormat: Text.PlainText
        color: tile.neutral ? theme.dimText : tile.glyphColor
        font.pointSize: theme.fontSmall
        font.weight: Font.Bold
    }
    Icon {
        anchors.centerIn: parent
        visible: tile.text === "" && text !== ""
        glyph: tile.glyph
        fallback: tile.fallbackText.charAt(0).toUpperCase()
        size: tile.size * 0.46
        color: tile.neutral ? theme.dimText : tile.glyphColor
    }
}
