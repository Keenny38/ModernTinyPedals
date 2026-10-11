import QtQuick
import QtQuick.Controls.Basic

// Popup menu: rounded, fades in, items highlighted on hover, check marks, separators (MenuSeparator {})
Menu {
    id: menu
    padding: 4
    implicitWidth: Math.max(theme.em * 13, contentItem.implicitWidth + 8)

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 120; easing.type: Easing.OutCubic }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 90 } }

    background: Rectangle {
        implicitWidth: theme.em * 13
        radius: theme.em * 0.6
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    delegate: MenuItem {
        id: item
        implicitHeight: theme.em * 2.1
        implicitWidth: label.implicitWidth + theme.em * 3.2 + (item.subMenu ? theme.em * 1.5 : 0)
        contentItem: Item {
            Icon {
                id: check
                x: 0
                anchors.verticalCenter: parent.verticalCenter
                glyph: ""  // check mark
                size: theme.em * 0.8
                color: theme.accent
                visible: item.checkable && item.checked && theme.iconFont !== ""
            }
            Text {
                id: label
                x: theme.em * 1.4
                anchors.verticalCenter: parent.verticalCenter
                text: item.text
                color: item.enabled ? (item.highlighted ? theme.text : theme.text) : theme.dimText
            }
            Icon {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                glyph: ""  // chevron right
                size: theme.em * 0.7
                color: theme.dimText
                visible: item.subMenu !== null
            }
        }
        indicator: Item {}
        arrow: Item {}
        background: Rectangle {
            radius: theme.em * 0.4
            color: item.highlighted ? theme.hover : "transparent"
        }
    }
}
