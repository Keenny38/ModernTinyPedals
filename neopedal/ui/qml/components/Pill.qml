import QtQuick
import QtQuick.Controls.Basic

// Small rounded tag: tinted outline (or solid fill: error badges), optional icon glyph (fallback text without icon
// font) or status dot (pulsing: a few pulses when the state starts). maximumTextWidth > 0: long texts cut with "..."
// (full text in tooltip). onStage: drawn over an overlay preview (always dark): stage backdrop & ink when not solid.
//   Pill { text: i18n.tr("Error"); solid: true; tint: theme.lossFill; glyph: ""; fallback: "!"; tip: ... }
Rectangle {
    id: pill
    property string text: ""
    property string glyph: ""
    property string fallback: ""
    property color tint: theme.accent
    property bool solid: false
    property bool onStage: false
    property bool dot: false
    property bool pulsing: false
    property string tip: ""
    property real maximumTextWidth: 0
    property string size: "md"  // "sm": in dense rows
    // Text over solid fill: dark on light colors, white on dark ones
    readonly property color fillInk: theme.inkOn(tint)
    readonly property color ink: solid ? fillInk : onStage ? theme.stageInk : theme.tintInk(tint)

    implicitHeight: Math.round(size === "sm" ? theme.chipHeightSm : theme.chipHeight)
    implicitWidth: row.implicitWidth + (size === "sm" ? theme.em * 0.7 : theme.em * 0.9)
    radius: height / 2
    color: solid ? tint : onStage ? theme.stageScrim : theme.tint(tint, "selected")
    border.width: solid ? 0 : 1
    border.color: onStage ? theme.tint(theme.stageInk, "strong") : theme.tint(tint, "outline")

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
            fallback: pill.fallback
            size: theme.iconXs
            color: pill.ink
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: label
            text: pill.text
            textFormat: Text.PlainText
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
