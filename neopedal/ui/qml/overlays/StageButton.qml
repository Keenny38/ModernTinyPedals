import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Round icon button on the dark preview stage of an overlay card (white tints): settings, favorite star.
// No Tab stop: the focused card answers Enter (settings) and Ctrl+F (favorite).
AbstractButton {
    id: button
    property string glyph: ""
    property string fallback: ""
    property color glyphColor: "white"
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
        color: button.down ? Qt.rgba(1, 1, 1, 0.3) : button.hovered ? Qt.rgba(1, 1, 1, 0.2) : Qt.rgba(0, 0, 0, 0.45)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.18)
    }
    contentItem: Icon {
        glyph: button.glyph
        fallback: button.fallback
        size: theme.em * 0.95
        color: button.glyphColor
    }
}
