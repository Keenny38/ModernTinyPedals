import QtQuick
import QtQuick.Layouts
import "../components"

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
    radius: theme.radiusLg
    color: area.containsMouse ? theme.surfaceHover : theme.surfaceCard
    border.width: checked ? 2 : 1
    border.color: checked ? theme.accent : theme.cardBorder
    scale: area.pressed ? 0.985 : 1
    activeFocusOnTab: true
    Behavior on color { ColorAnimation { duration: theme.motionFast } }
    Behavior on border.color { ColorAnimation { duration: theme.motionBase } }
    Behavior on scale { NumberAnimation { duration: theme.motionFast } }
    Accessible.role: multi ? Accessible.CheckBox : Accessible.RadioButton
    Accessible.name: title
    Accessible.description: text
    Accessible.checkable: true
    Accessible.checked: checked
    Keys.onSpacePressed: function(event) {
        event.accepted = true
        card.clicked()
    }

    // Keyboard focus ring: solid accent outside the card (never taken for the checked border)
    FocusRing { visible: card.activeFocus }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: card.padding
        spacing: theme.em * 0.7

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space5

            Rectangle {
                visible: (card.glyph !== "" && theme.iconFont !== "") || card.tileText !== ""
                Layout.preferredWidth: Math.round(theme.em * 2.4)
                Layout.preferredHeight: Math.round(theme.em * 2.4)
                Layout.alignment: Qt.AlignTop
                radius: theme.radiusLg
                color: theme.tint(theme.accent, card.checked ? "strong" : "subtle")
                Behavior on color { ColorAnimation { duration: theme.motionBase } }
                Icon {
                    anchors.centerIn: parent
                    glyph: card.glyph
                    color: card.checked ? theme.accent : theme.text
                    size: theme.iconMd
                }
                Text {
                    anchors.centerIn: parent
                    visible: card.glyph === "" || theme.iconFont === ""
                    text: card.tileText
                    textFormat: Text.PlainText
                    color: card.checked ? theme.accent : theme.text
                    font.weight: Font.Bold
                    font.pointSize: theme.fontLabel
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: card.text !== "" ? Qt.AlignTop : Qt.AlignVCenter
                spacing: theme.space1
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.5
                    Text {
                        Layout.fillWidth: true
                        text: card.title
                        textFormat: Text.PlainText
                        color: theme.text
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontSubtitle
                        wrapMode: Text.WordWrap  // long (French) titles on 2 lines, not cut
                        maximumLineCount: 2
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
                    textFormat: Text.PlainText
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    font.pointSize: theme.fontLabel
                }
            }

            // Selection mark
            Rectangle {
                Layout.alignment: Qt.AlignTop
                implicitWidth: Math.round(theme.em * 1.25)
                implicitHeight: implicitWidth
                radius: card.multi ? theme.em * 0.3 : width / 2
                color: card.checked ? theme.accentFill : "transparent"
                border.width: card.checked ? 0 : 1.5
                border.color: theme.border
                Behavior on color { ColorAnimation { duration: theme.motionBase } }
                Icon {
                    anchors.centerIn: parent
                    visible: card.checked && card.multi
                    fallback: "✓"
                    glyph: ""  // check
                    color: theme.accentInk
                    size: theme.iconXs
                }
                Rectangle {
                    anchors.centerIn: parent
                    visible: card.checked && !card.multi
                    width: Math.round(parent.width * 0.42)
                    height: width
                    radius: width / 2
                    color: theme.accentInk
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
