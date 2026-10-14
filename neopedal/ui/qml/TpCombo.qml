import QtQuick
import QtQuick.Controls.Basic

// Combo box of texts in app look: rounded, popup fades in, current item in bold
ComboBox {
    id: box
    property string tip: ""
    property var dotColor: null  // function(text) giving a dot color, null for none
    property bool compounds: false  // texts are tyre compounds: compound badge before each (as overlays)

    implicitHeight: Math.round(theme.em * 2.05)
    implicitWidth: theme.em * 9
    focusPolicy: Qt.TabFocus
    opacity: enabled ? 1 : theme.disabledOpacity
    Accessible.name: tip !== "" ? tip : displayText

    ToolTip.visible: tip !== "" && hovered && !popup.visible
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay

    background: Rectangle {
        radius: theme.radiusMd
        color: box.hovered ? theme.hover : theme.raised
        border.width: box.visualFocus ? 1.5 : 1
        border.color: box.popup.visible || box.visualFocus ? theme.accent : theme.border
        Behavior on color { ColorAnimation { duration: theme.motionFast } }
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
        TpCompound {
            visible: box.compounds && name !== ""
            name: box.compounds ? box.displayText : ""
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: box.displayText
            color: theme.text
            elide: Text.ElideRight
            width: box.width - theme.em * 2.6 - (box.dotColor !== null ? theme.em : box.compounds ? theme.em * 1.5 : 0)
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
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: box.popup.visible ? box.delegateModel : null
            currentIndex: box.highlightedIndex
            ScrollBar.vertical: ScrollBar {}
        }
        background: Rectangle {
            radius: theme.radiusLg
            color: theme.raised
            border.width: 1
            border.color: theme.border
        }
    }
    delegate: ItemDelegate {
        id: item
        required property var modelData
        required property int index
        // Text of item: textRole of objects (model used as given, no mapped copy) or the item itself
        readonly property string label: box.textRole !== "" && modelData !== null && typeof modelData === "object"
                                        ? String(modelData[box.textRole]) : String(modelData)
        width: ListView.view ? ListView.view.width : box.width
        height: theme.em * 2.1
        highlighted: box.highlightedIndex === index
        contentItem: Row {
            spacing: theme.em * 0.5
            Rectangle {
                visible: box.dotColor !== null
                width: Math.round(theme.em * 0.6)
                height: width
                radius: width / 2
                color: box.dotColor ? box.dotColor(item.label) : "transparent"
                anchors.verticalCenter: parent.verticalCenter
            }
            TpCompound {
                visible: box.compounds && name !== ""
                name: box.compounds ? item.label : ""
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: item.label
                color: theme.text
                font.weight: box.currentIndex === item.index ? Font.DemiBold : Font.Normal
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        background: Rectangle {
            radius: theme.radiusMd
            color: item.highlighted ? theme.hover : "transparent"
        }
    }
}
