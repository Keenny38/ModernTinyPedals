import QtQuick
import QtQuick.Layouts

// Ready step: every choice with a link back to its step, tips for the first drive
SetupStep {
    Card {
        Layout.fillWidth: true
        implicitHeight: list.implicitHeight + theme.em * 0.8

        ColumnLayout {
            id: list
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.em * 0.4
            spacing: 0
            Repeater {
                model: backend.summary
                Rectangle {
                    id: row
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: Math.max(Math.round(theme.em * 2.8), content.implicitHeight + theme.em * 0.9)
                    radius: theme.em * 0.5
                    color: rowArea.containsMouse ? theme.hover : "transparent"
                    Behavior on color { ColorAnimation { duration: 120 } }

                    Rectangle {  // separator
                        visible: row.index > 0
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: theme.em * 0.6
                        anchors.rightMargin: theme.em * 0.6
                        height: 1
                        color: theme.border
                        opacity: 0.5
                    }
                    MouseArea {
                        id: rowArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: backend.goTo(row.modelData.step)
                    }
                    RowLayout {
                        id: content
                        anchors.fill: parent
                        anchors.leftMargin: theme.em * 0.6
                        anchors.rightMargin: theme.em * 0.4
                        spacing: theme.em * 0.7
                        Icon {
                            Layout.preferredWidth: theme.em * 1.4
                            glyph: row.modelData.glyph
                            color: theme.accent
                        }
                        Text {
                            Layout.preferredWidth: theme.em * 9
                            text: row.modelData.label
                            color: theme.dimText
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: row.modelData.value
                            color: theme.text
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }
                        TpButton {
                            flat: true
                            text: i18n.tr("Change")
                            onClicked: backend.goTo(row.modelData.step)
                        }
                    }
                }
            }
        }
    }

    SetupHeading { text: i18n.tr("Good to know") }

    Card {
        Layout.fillWidth: true
        implicitHeight: tips.implicitHeight + theme.em * 1.6

        ColumnLayout {
            id: tips
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.em * 0.8
            spacing: theme.em * 0.7
            Repeater {
                model: [
                    { glyph: "", text: i18n.tr("Overlays show while you drive and hide in the game menus (Auto Hide).") },
                    { glyph: "", text: i18n.tr("Drag an overlay to place it, then use Lock Overlay so it stays put.") },
                    { glyph: "", text: i18n.tr("Ctrl+K searches and runs anything in the app.") },
                    { glyph: "", text: i18n.tr("Open this wizard again from Help > Setup Wizard.") }
                ]
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: theme.em * 0.8
                    Icon {
                        Layout.preferredWidth: theme.em * 1.4
                        Layout.alignment: Qt.AlignTop
                        glyph: modelData.glyph
                        color: theme.dimText
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.text
                        color: theme.text
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
