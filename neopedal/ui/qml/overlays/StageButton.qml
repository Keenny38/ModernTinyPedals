import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Round icon button on the dark preview stage of an overlay card (white tints): settings, favorite star.
// No Tab stop: the focused card answers Enter (options) and Ctrl+D (favorite).
AbstractButton {
    id: button
    property string glyph: ""
    property string fallback: ""
    property color glyphColor: theme.stageInk
    property string tip: ""

    width: Math.round(theme.em * 2)
    height: width
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    ToolTip.visible: hovered
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay
    Accessible.role: Accessible.Button
    Accessible.name: tip

    background: Rectangle {
        radius: width / 2
        color: button.down ? theme.tint(theme.stageInk, "strong") : button.hovered ? theme.tint(theme.stageInk, "selected")
             : theme.stageScrim
        border.width: 1
        border.color: theme.tint(theme.stageInk, "selected")
    }
    contentItem: Icon {
        glyph: button.glyph
        fallback: button.fallback
        size: theme.iconSm
        color: button.glyphColor
    }
}
