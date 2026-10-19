import QtQuick
import QtQuick.Controls.Basic

// Small rounded tag: tinted outline (or solid fill), optional icon glyph or status dot (pulsing: a few
// pulses when the state starts). maximumTextWidth > 0: long texts cut with "..." (full text in tooltip)
Rectangle {
    id: pill
    property string text: ""
    property string glyph: ""
    property color tint: theme.accent
    property bool solid: false
    property bool dot: false
    property bool pulsing: false
    property string tip: ""
    property real maximumTextWidth: 0
    property string size: "md"  // "sm": in dense rows
    // Text over solid fill: dark on light colors, white on dark ones
    readonly property color fillInk: theme.inkOn(tint)
    readonly property color ink: solid ? fillInk : theme.dark ? Qt.lighter(tint, 1.35) : Qt.darker(tint, 1.25)

    implicitHeight: Math.round(theme.em * (size === "sm" ? 1.25 : 1.45))
    implicitWidth: row.implicitWidth + theme.em * (size === "sm" ? 0.7 : 0.9)
    radius: height / 2
    color: solid ? tint : Qt.rgba(tint.r, tint.g, tint.b, theme.tintSelected)
    border.width: solid ? 0 : 1
    border.color: Qt.rgba(tint.r, tint.g, tint.b, 0.5)

    Accessible.role: Accessible.StaticText
    Accessible.name: tip !== "" ? text + ", " + tip : text

    Row {
        id: row
        anchors.centerIn: parent
        spacing: theme.space2
        TpPulseDot {
            visible: pill.dot
            width: theme.em * 0.5
            color: pill.solid ? pill.fillInk : pill.tint
            pulsing: pill.pulsing && visible
            anchors.verticalCenter: parent.verticalCenter
        }
        Icon {
            glyph: pill.glyph
            size: theme.em * 0.72
            color: pill.ink
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: label
            text: pill.text
            visible: text !== ""
            width: pill.maximumTextWidth > 0 ? Math.min(implicitWidth, pill.maximumTextWidth) : implicitWidth
            elide: Text.ElideRight
            color: pill.ink
            font.pointSize: pill.size === "sm" ? theme.fontTiny : theme.fontCaption
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    MouseArea {
        id: tipArea
        anchors.fill: parent
        hoverEnabled: pill.tip !== "" || label.truncated
        acceptedButtons: Qt.NoButton
    }
    ToolTip.visible: (tip !== "" || label.truncated) && tipArea.containsMouse
    ToolTip.text: tip !== "" ? (label.truncated ? text + "\n" + tip : tip) : text
    ToolTip.delay: theme.tipDelay
}
