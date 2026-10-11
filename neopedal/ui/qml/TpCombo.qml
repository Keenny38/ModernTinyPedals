import QtQuick
import QtQuick.Controls.Basic

// Combo box of texts in app look: rounded, popup fades in, current item in bold
ComboBox {
    id: box
    property string tip: ""
    property var dotColor: null  // function(text) giving a dot color, null for none

    implicitHeight: Math.round(theme.em * 2.05)
    implicitWidth: theme.em * 9
    focusPolicy: Qt.TabFocus
    opacity: enabled ? 1 : 0.5
    Accessible.name: tip !== "" ? tip : displayText

    ToolTip.visible: tip !== "" && hovered && !popup.visible
    ToolTip.text: tip
    ToolTip.delay: 700

    background: Rectangle {
        radius: theme.em * 0.4
        color: box.hovered ? theme.hover : theme.raised
        border.width: box.visualFocus ? 1.5 : 1
        border.color: box.popup.visible || box.visualFocus ? theme.accent : theme.border
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    contentItem: Row {
        leftPadding: theme.em * 0.6
        spacing: theme.em * 0.4
        Rectangle {
            visible: box.dotColor !== null
            width: Math.round(theme.em * 0.6)
            height: width
            radius: width / 2
            color: box.dotColor ? box.dotColor(box.displayText) : "transparent"
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: box.displayText
            color: theme.text
            elide: Text.ElideRight
            width: box.width - theme.em * 2.6 - (box.dotColor !== null ? theme.em : 0)
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    indicator: Icon {
        glyph: ""  // chevron down
        size: theme.em * 0.7
        color: theme.dimText
        x: box.width - width - theme.em * 0.6
        y: (box.height - height) / 2
    }
    popup: Popup {
        y: box.height + 4
        width: Math.max(box.width, theme.em * 9)
        padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, theme.em * 22)
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 130 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 90 } }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: box.popup.visible ? box.delegateModel : null
            currentIndex: box.highlightedIndex
            ScrollBar.vertical: ScrollBar {}
        }
        background: Rectangle {
            radius: theme.em * 0.6
            color: theme.raised
            border.width: 1
            border.color: theme.border
        }
    }
    delegate: ItemDelegate {
        id: item
        required property var modelData
        required property int index
        width: ListView.view ? ListView.view.width : box.width
        height: theme.em * 2.1
        highlighted: box.highlightedIndex === index
        contentItem: Row {
            spacing: theme.em * 0.45
            Rectangle {
                visible: box.dotColor !== null
                width: Math.round(theme.em * 0.6)
                height: width
                radius: width / 2
                color: box.dotColor ? box.dotColor(String(item.modelData)) : "transparent"
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: String(item.modelData)
                color: theme.text
                font.weight: box.currentIndex === item.index ? Font.DemiBold : Font.Normal
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        background: Rectangle {
            radius: theme.em * 0.4
            color: item.highlighted ? theme.hover : "transparent"
        }
    }
}
