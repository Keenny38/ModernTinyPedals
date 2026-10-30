import QtQuick

// Count badge: number of items of a header, a group or a navigation entry. One look everywhere: neutral (hover
// surface, dim text), accent (something on: filled, white text) or error (loss fill, "!" before the count: never
// color alone). Tabular figures; chip height of tags.
//   TpCountBadge { text: backend.lapCount }
//   TpCountBadge { text: entry.count; tone: entry.errors > 0 ? "error" : "accent" }
Rectangle {
    id: badge
    property string text: ""
    property string tone: "neutral"  // "neutral" | "accent" | "error"
    property string size: "md"  // "sm": in dense rows
    readonly property color fill: tone === "error" ? theme.lossFill : tone === "accent" ? theme.accentFill : theme.hover

    implicitHeight: Math.round(size === "sm" ? theme.chipHeightSm : theme.chipHeight)
    implicitWidth: Math.max(implicitHeight, label.implicitWidth + theme.space4 * 1.5)
    radius: height / 2
    color: fill
    Accessible.role: Accessible.StaticText
    Accessible.name: tone === "error" ? i18n.tr("Error") + ", " + text : text

    Text {
        id: label
        anchors.centerIn: parent
        text: badge.tone === "error" ? "! " + badge.text : badge.text
        textFormat: Text.PlainText
        color: badge.tone === "neutral" ? theme.dimOn(badge.fill) : theme.accentInk
        font.pointSize: badge.size === "sm" ? theme.fontCaption : theme.fontSmall
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
    }
}
