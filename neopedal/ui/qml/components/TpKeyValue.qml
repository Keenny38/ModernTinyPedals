import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Label & value pair: "row" (label left, value right aligned, tabular figures) or "stack" (label above the
// value, always in that order). tone: value color (theme.gain...), warning: loss color & warning mark.
//   TpKeyValue { label: i18n.tr("Fuel per lap"); value: "3.12 L"; tip: ... }
GridLayout {
    id: pair
    property string label: ""
    property string value: ""
    property string tip: ""
    property var tone: null
    property bool warning: false
    property string layout: "row"
    property bool large: false  // stack: value in fontLarge (key figure)

    columns: layout === "stack" ? 1 : 2
    rowSpacing: 0
    columnSpacing: theme.em * 0.5
    Layout.fillWidth: true
    Accessible.role: Accessible.StaticText
    Accessible.name: label + ": " + value

    Text {
        id: labelText
        Layout.fillWidth: true
        text: pair.label
        color: theme.dimText
        font.pointSize: pair.layout === "stack" ? theme.fontSmall : theme.fontPoint
        elide: Text.ElideRight
        HoverHandler { id: hover; enabled: pair.tip !== "" || labelText.truncated }
        ToolTip.visible: hover.hovered
        ToolTip.text: pair.tip !== "" ? pair.tip : pair.label
        ToolTip.delay: theme.tipDelay
    }
    RowLayout {
        spacing: theme.space2
        Layout.alignment: pair.layout === "stack" ? Qt.AlignLeft : Qt.AlignRight
        Icon {
            visible: pair.warning
            glyph: ""  // warning
            fallback: "!"
            color: theme.loss
            size: theme.em * 0.85
        }
        Text {
            text: pair.value
            color: pair.warning ? theme.loss : pair.tone ? pair.tone : theme.text
            font.pointSize: pair.large ? theme.fontLarge : theme.fontPoint
            font.weight: pair.large ? Font.DemiBold : Font.Normal
            font.features: { "tnum": 1 }
            horizontalAlignment: pair.layout === "stack" ? Text.AlignLeft : Text.AlignRight
        }
    }
}
