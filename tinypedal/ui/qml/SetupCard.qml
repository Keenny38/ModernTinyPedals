import QtQuick
import QtQuick.Layouts

// Choice card of the setup wizard: icon (or short text) tile, title, text, optional badge and content
// below (children). Selected: accent border & filled mark. Click or Space selects (Enter: next step).
Rectangle {
    id: card
    property string title: ""
    property string text: ""
    property string glyph: ""
    property string tileText: ""  // shown in the icon tile when there is no glyph
    property bool checked: false
    property bool multi: false  // check box mark (several cards checked), else radio mark
    property string badge: ""
    property color badgeTint: theme.gain
    property real padding: theme.em * 0.9
    default property alias extra: extraBox.data
    signal clicked()

    implicitWidth: theme.em * 14
    implicitHeight: column.implicitHeight + padding * 2
    radius: theme.em * 0.75
    color: area.containsMouse ? (theme.dark ? Qt.lighter(theme.base, 1.18) : Qt.darker(theme.base, 1.025)) : theme.base
    border.width: checked ? 2 : 1
    border.color: checked ? theme.accent : (theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border)
    scale: area.pressed ? 0.985 : 1
    activeFocusOnTab: true
    Behavior on color { ColorAnimation { duration: 120 } }
    Behavior on border.color { ColorAnimation { duration: 150 } }
    Behavior on scale { NumberAnimation { duration: 90 } }
    Accessible.role: multi ? Accessible.CheckBox : Accessible.RadioButton
    Accessible.name: title
    Accessible.description: text
    Accessible.checkable: true
    Accessible.checked: checked
    Keys.onSpacePressed: function(event) {
        event.accepted = true
        card.clicked()
    }

    // Keyboard focus ring
    Rectangle {
        anchors.fill: parent
        anchors.margins: -3
        radius: parent.radius + 3
        color: "transparent"
        border.width: 2
        border.color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.5)
        visible: card.activeFocus
    }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: card.padding
        spacing: theme.em * 0.7

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.75

            Rectangle {
                visible: (card.glyph !== "" && theme.iconFont !== "") || card.tileText !== ""
                Layout.preferredWidth: Math.round(theme.em * 2.4)
                Layout.preferredHeight: Math.round(theme.em * 2.4)
                Layout.alignment: Qt.AlignTop
                radius: theme.em * 0.55
                color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, card.checked ? 0.22 : (theme.dark ? 0.12 : 0.08))
                Behavior on color { ColorAnimation { duration: 150 } }
                Icon {
                    anchors.centerIn: parent
                    glyph: card.glyph
                    color: card.checked ? theme.accent : theme.text
                    size: theme.em * 1.15
                }
                Text {
                    anchors.centerIn: parent
                    visible: card.glyph === "" || theme.iconFont === ""
                    text: card.tileText
                    color: card.checked ? theme.accent : theme.text
                    font.weight: Font.Bold
                    font.pointSize: theme.fontPoint * 0.9
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: card.text !== "" ? Qt.AlignTop : Qt.AlignVCenter
                spacing: theme.em * 0.15
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.5
                    Text {
                        Layout.fillWidth: true
                        text: card.title
                        color: theme.text
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontPoint * 1.05
                        elide: Text.ElideRight
                    }
                    Pill {
                        visible: card.badge !== ""
                        text: card.badge
                        tint: card.badgeTint
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: card.text
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    font.pointSize: theme.fontPoint * 0.92
                }
            }

            // Selection mark
            Rectangle {
                Layout.alignment: Qt.AlignTop
                implicitWidth: Math.round(theme.em * 1.25)
                implicitHeight: implicitWidth
                radius: card.multi ? theme.em * 0.3 : width / 2
                color: card.checked ? theme.accent : "transparent"
                border.width: card.checked ? 0 : 1.5
                border.color: theme.border
                Behavior on color { ColorAnimation { duration: 150 } }
                Icon {
                    anchors.centerIn: parent
                    visible: card.checked && card.multi
                    glyph: ""  // check
                    color: "white"
                    size: theme.em * 0.7
                }
                Rectangle {
                    anchors.centerIn: parent
                    visible: card.checked && !card.multi
                    width: Math.round(parent.width * 0.42)
                    height: width
                    radius: width / 2
                    color: "white"
                }
            }
        }

        Item {
            id: extraBox
            Layout.fillWidth: true
            implicitHeight: childrenRect.height
            visible: children.length > 0
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: card.clicked()
    }
}
