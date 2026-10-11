import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator result card: icon & title (warning color), header actions on the right, content below
Card {
    id: card
    property string title: ""
    property string glyph: ""
    property string tip: ""
    property bool warning: false
    default property alias content: body.data
    property alias actions: actionRow.data
    readonly property real pad: theme.em * 0.75

    Layout.fillWidth: true
    implicitHeight: titleRow.height + body.implicitHeight + pad * 2.6

    RowLayout {
        id: titleRow
        x: card.pad
        y: card.pad
        width: card.width - card.pad * 2
        height: Math.round(theme.em * 2)
        spacing: theme.em * 0.45
        Icon { glyph: card.glyph; color: card.warning ? theme.loss : theme.accent; size: theme.em * 0.95 }
        Text {
            text: card.title
            color: card.warning ? theme.loss : theme.text
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: true
            HoverHandler { id: titleHover; enabled: card.tip !== "" }
            ToolTip.visible: titleHover.hovered
            ToolTip.text: card.tip
            ToolTip.delay: 500
        }
        Row {
            id: actionRow
            spacing: theme.em * 0.35
            Layout.alignment: Qt.AlignVCenter
        }
    }
    ColumnLayout {
        id: body
        x: card.pad
        y: titleRow.y + titleRow.height + card.pad * 0.6
        width: card.width - card.pad * 2
        height: Math.max(implicitHeight, card.height - y - card.pad)  // card taller than content: fill items grow
        spacing: theme.em * 0.4
    }
}
