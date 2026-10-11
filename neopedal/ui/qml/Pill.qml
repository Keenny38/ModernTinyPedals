import QtQuick
import QtQuick.Controls.Basic

// Small rounded tag: tinted outline (or solid fill), optional icon glyph
Rectangle {
    id: pill
    property string text: ""
    property string glyph: ""
    property color tint: theme.accent
    property bool solid: false
    property string tip: ""
    // Text over solid fill: dark on light colors, white on dark ones
    readonly property color fillInk: (0.299 * tint.r + 0.587 * tint.g + 0.114 * tint.b) > 0.62 ? "#111111" : "white"
    readonly property color ink: solid ? fillInk : theme.dark ? Qt.lighter(tint, 1.35) : Qt.darker(tint, 1.25)

    implicitHeight: Math.round(theme.em * 1.45)
    implicitWidth: row.implicitWidth + theme.em * 0.9
    radius: height / 2
    color: solid ? tint : Qt.rgba(tint.r, tint.g, tint.b, theme.dark ? 0.2 : 0.12)
    border.width: solid ? 0 : 1
    border.color: Qt.rgba(tint.r, tint.g, tint.b, 0.5)

    Accessible.role: Accessible.StaticText
    Accessible.name: tip !== "" ? text + ", " + tip : text

    Row {
        id: row
        anchors.centerIn: parent
        spacing: theme.em * 0.3
        Icon {
            glyph: pill.glyph
            size: theme.em * 0.72
            color: pill.ink
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: pill.text
            visible: text !== ""
            color: pill.ink
            font.pointSize: theme.fontPoint * 0.8
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    MouseArea {
        id: tipArea
        anchors.fill: parent
        hoverEnabled: pill.tip !== ""
        acceptedButtons: Qt.NoButton
    }
    ToolTip.visible: tip !== "" && tipArea.containsMouse
    ToolTip.text: tip
    ToolTip.delay: 500
}
