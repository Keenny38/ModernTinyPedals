import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Driver stats section: icon, title & count chip, header actions on the right (actions), content below
// (fills the card when the card is taller than its content).
Card {
    id: card
    property string title: ""
    property string glyph: ""
    property string tip: ""
    property string count: ""  // chip next to title
    default property alias content: body.data
    property alias actions: actionRow.data
    readonly property real pad: theme.em * 0.75

    Layout.fillWidth: true
    implicitHeight: titleRow.height + body.implicitHeight + pad * 2.6

    RowLayout {
        id: titleRow
        x: card.pad
        y: card.pad * 0.8
        width: card.width - card.pad * 2
        height: Math.round(theme.em * 2)
        spacing: theme.em * 0.45
        Icon { glyph: card.glyph; color: theme.accent; size: theme.em * 0.95 }
        Text {
            text: card.title
            color: theme.text
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: card.count === ""
            HoverHandler { id: titleHover; enabled: card.tip !== "" }
            ToolTip.visible: titleHover.hovered
            ToolTip.text: card.tip
            ToolTip.delay: 500
        }
        Rectangle {
            visible: card.count !== ""
            implicitHeight: Math.round(theme.em * 1.4)
            implicitWidth: countText.implicitWidth + theme.em * 0.9
            radius: height / 2
            color: theme.hover
            Text {
                id: countText
                anchors.centerIn: parent
                text: card.count
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
            }
        }
        Item { visible: card.count !== ""; Layout.fillWidth: true }
        Row {
            id: actionRow
            spacing: theme.em * 0.35
            Layout.alignment: Qt.AlignVCenter
        }
    }
    ColumnLayout {
        id: body
        x: card.pad
        y: titleRow.y + titleRow.height + card.pad * 0.5
        width: card.width - card.pad * 2
        height: Math.max(implicitHeight, card.height - y - card.pad)  // card taller than content: fill items grow
        spacing: theme.em * 0.4
    }
}
