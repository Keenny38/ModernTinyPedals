import QtQuick
import QtQuick.Controls.Basic

// Menu entry of TpMenu: check mark (kept in place when unchecked), label cut with ..., key of the action
// (shortcut: "Del", "F2", "Ctrl+D", right-aligned & dim, never in the label text), submenu chevron, hover
// background. Declare entries as TpMenuItem (a plain MenuItem keeps the Basic style look)
//   TpMenuItem { text: i18n.tr("Delete"); shortcut: i18n.tr("Del"); onTriggered: ... }
MenuItem {
    id: item
    property string shortcut: ""  // key shown at the right (translated key name), the menu entry does not bind it
    readonly property real shortcutWidth: shortcut !== "" ? keyText.implicitWidth + theme.em * 1.5 : 0
    implicitHeight: theme.rowCompact
    implicitWidth: label.implicitWidth + theme.em * 3.2 + shortcutWidth + (item.subMenu ? theme.em * 1.5 : 0)
    Accessible.description: shortcut
    contentItem: Item {
        Icon {
            id: check
            x: 0
            anchors.verticalCenter: parent.verticalCenter
            glyph: ""  // check mark
            fallback: "✓"
            size: theme.iconSm
            color: theme.accent
            opacity: item.checkable && item.checked ? 1 : 0  // kept in place: labels stay aligned
        }
        Text {
            id: label
            x: theme.em * 1.4
            width: Math.max(0, Math.min(implicitWidth, parent.width - x - item.shortcutWidth - (item.subMenu ? theme.em * 1.5 : 0)))
            elide: Text.ElideRight
            anchors.verticalCenter: parent.verticalCenter
            text: item.text
            textFormat: Text.PlainText
            color: item.enabled ? theme.text : theme.dimText
        }
        Text {
            id: keyText
            objectName: "menuShortcut"
            anchors.right: parent.right
            anchors.rightMargin: item.subMenu ? theme.em * 1.5 : 0
            anchors.verticalCenter: parent.verticalCenter
            visible: item.shortcut !== ""
            text: item.shortcut
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontLabel
        }
        Icon {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            glyph: ""  // chevron right
            fallback: "›"
            size: theme.iconXs
            color: theme.dimText
            visible: item.subMenu !== null && text !== ""
        }
    }
    indicator: Item {}
    arrow: Item {}
    background: Rectangle {
        radius: theme.radiusSm
        color: item.highlighted ? theme.hover : "transparent"
    }
}
