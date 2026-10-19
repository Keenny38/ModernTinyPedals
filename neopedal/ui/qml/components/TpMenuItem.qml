import QtQuick
import QtQuick.Controls.Basic

// Menu entry of TpMenu: check mark (kept in place when unchecked), label cut with ..., submenu chevron,
// hover background. Declare entries as TpMenuItem (a plain MenuItem keeps the Basic style look)
MenuItem {
    id: item
    implicitHeight: theme.em * 2.1
    implicitWidth: label.implicitWidth + theme.em * 3.2 + (item.subMenu ? theme.em * 1.5 : 0)
    contentItem: Item {
        Icon {
            id: check
            x: 0
            anchors.verticalCenter: parent.verticalCenter
            glyph: ""  // check mark
            fallback: "✓"
            size: theme.em * 0.8
            color: theme.accent
            opacity: item.checkable && item.checked ? 1 : 0  // kept in place: labels stay aligned
        }
        Text {
            id: label
            x: theme.em * 1.4
            width: Math.max(0, Math.min(implicitWidth, parent.width - x - (item.subMenu ? theme.em * 1.5 : 0)))
            elide: Text.ElideRight
            anchors.verticalCenter: parent.verticalCenter
            text: item.text
            color: item.enabled ? theme.text : theme.dimText
        }
        Icon {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            glyph: ""  // chevron right
            fallback: "›"
            size: theme.em * 0.7
            color: theme.dimText
            visible: item.subMenu !== null && text !== ""
        }
    }
    indicator: Item {}
    arrow: Item {}
    background: Rectangle {
        radius: theme.radiusMd
        color: item.highlighted ? theme.hover : "transparent"
    }
}
