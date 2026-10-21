import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Card of Home page: icon & title, logos on the right (trailing), content (children), buttons at the bottom
// (actions). Clickable card (opens its page): pointing hand, hover border, Tab focus, Enter / Space open it;
// buttons & links inside keep their own clicks.
//   HomeCard { glyph: ""; title: i18n.tr("Preset"); clickable: true; onOpened: backend.openPage("preset") }
Rectangle {
    id: card
    property string glyph: ""
    property string fallback: ""
    property string title: ""
    property string tip: ""  // what a click opens
    property bool clickable: false
    property color tint: theme.accent  // icon color
    default property alias content: body.data
    property alias actions: actionRow.data
    property alias trailing: trailingRow.data
    signal opened()

    implicitHeight: column.implicitHeight + theme.padCard * 2
    radius: theme.radiusXl
    readonly property bool hovered: area.containsMouse
    color: hovered && clickable ? (theme.dark ? Qt.lighter(theme.base, 1.08) : Qt.darker(theme.base, 1.015)) : theme.base
    border.width: 1
    border.color: hovered && clickable ? theme.accent : theme.cardBorder
    Behavior on color { ColorAnimation { duration: theme.motionFast } }
    Behavior on border.color { ColorAnimation { duration: theme.motionFast } }

    activeFocusOnTab: clickable
    Keys.onReturnPressed: if (clickable) card.opened()
    Keys.onEnterPressed: if (clickable) card.opened()
    Keys.onSpacePressed: if (clickable) card.opened()
    Accessible.role: clickable ? Accessible.Button : Accessible.Grouping
    Accessible.name: title
    Accessible.description: tip
    Accessible.onPressAction: if (clickable) card.opened()

    // Own items in data: the default property (content) takes children declared by users of the card
    data: [
        MouseArea {  // under the content: buttons inside take their own clicks
            id: area
            anchors.fill: parent
            enabled: card.clickable
            hoverEnabled: true
            cursorShape: card.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: card.opened()
            ToolTip.visible: card.tip !== "" && containsMouse
            ToolTip.text: card.tip
            ToolTip.delay: theme.tipDelay
        },
        FocusRing { visible: card.activeFocus },

        ColumnLayout {
            id: column
            anchors.fill: parent
            anchors.margins: theme.padCard
            spacing: theme.space2

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                Icon {
                    glyph: card.glyph
                    fallback: card.fallback
                    color: card.tint
                    size: theme.em * 1.05
                    Layout.alignment: Qt.AlignVCenter
                }
                Text {
                    text: card.title
                    color: theme.dimText
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    Accessible.role: Accessible.Heading
                    Accessible.name: text
                }
                RowLayout {
                    id: trailingRow
                    spacing: theme.space3
                    Layout.alignment: Qt.AlignVCenter
                }
            }
            ColumnLayout {
                id: body
                Layout.fillWidth: true
                spacing: theme.space2
            }
            Item { Layout.fillHeight: true }  // buttons kept at the bottom of a taller row
            RowLayout {
                id: actionRow
                visible: children.length > 0
                Layout.alignment: Qt.AlignRight
                spacing: theme.space3
            }
        }
    ]
}
