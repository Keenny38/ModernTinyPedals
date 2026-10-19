import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Underlined tabs: icon & text per tab, underline slides to the current tab. One Tab stop: arrows, Home & End
// choose (like TpSegmented). Extra controls after the tabs (right side): children.
//   TpTabBar { model: [{ text: i18n.tr("Fuel"), glyph: "" }, ...]; currentIndex: backend.tab
//              onActivated: function(index) { backend.setTab(index) } }
ColumnLayout {
    id: bar
    property var model: []
    property int currentIndex: 0
    property string name: ""
    default property alias trailing: trailingRow.data
    signal activated(int index)

    function choose(index) {
        if (index >= 0 && index < model.length && index !== currentIndex)
            activated(index)
    }

    Layout.fillWidth: true
    spacing: 0
    activeFocusOnTab: true
    Keys.onLeftPressed: choose(currentIndex - 1)
    Keys.onRightPressed: choose(currentIndex + 1)
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Home) { choose(0); event.accepted = true }
        else if (event.key === Qt.Key_End) { choose(model.length - 1); event.accepted = true }
    }
    Keys.onShortcutOverride: function(event) {
        if ([Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End].indexOf(event.key) >= 0)
            event.accepted = true
    }
    Accessible.role: Accessible.PageTabList
    Accessible.name: name

    RowLayout {
        Layout.fillWidth: true
        spacing: theme.space1
        Repeater {
            id: tabRepeater
            model: bar.model
            AbstractButton {
                id: tabButton
                required property var modelData
                required property int index
                readonly property bool current: bar.currentIndex === index
                implicitHeight: Math.round(theme.em * 2.2)
                implicitWidth: tabRow.implicitWidth + theme.em * 1.6
                hoverEnabled: true
                focusPolicy: Qt.NoFocus  // the bar takes Tab, arrows move
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.text
                Accessible.selected: current
                onClicked: bar.choose(index)
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                background: Rectangle {
                    radius: theme.radiusMd
                    color: tabButton.hovered && !tabButton.current ? theme.hover : "transparent"
                    Behavior on color { ColorAnimation { duration: theme.motionFast } }
                    FocusRing { visible: bar.activeFocus && tabButton.current }
                }
                contentItem: Item {
                    Row {
                        id: tabRow
                        anchors.centerIn: parent
                        spacing: theme.space3
                        Icon {
                            glyph: tabButton.modelData.glyph || ""
                            size: theme.em * 0.9
                            color: tabButton.current ? theme.accent : theme.dimText
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: tabButton.modelData.text
                            color: tabButton.current ? theme.text : theme.dimText
                            font.weight: tabButton.current ? Font.DemiBold : Font.Normal
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }
        }
        Item { Layout.fillWidth: true }
        RowLayout {
            id: trailingRow
            spacing: theme.space3
        }
    }
    Item {  // underline: slides to current tab
        Layout.fillWidth: true
        implicitHeight: 2
        Rectangle { anchors.fill: parent; color: theme.border }
        Rectangle {
            // count read: itemAt alone is never evaluated again once tab buttons are made (null at start)
            readonly property Item target: tabRepeater.count > bar.currentIndex ? tabRepeater.itemAt(bar.currentIndex) : null
            x: target ? target.x : 0
            width: target ? target.width : 0
            height: 2
            radius: 1
            color: theme.accent
            Behavior on x { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            Behavior on width { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
        }
    }
}
