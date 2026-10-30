import QtQuick
import QtQuick.Layouts
import "../components"

// Ready step: every choice with a link back to its step, what Finish does next (Overlays page in Screen view,
// test on screen), tips for the first drive
SetupStep {
    Card {
        Layout.fillWidth: true
        implicitHeight: list.implicitHeight + theme.em * 0.8

        ColumnLayout {
            id: list
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.space3
            spacing: 0
            Repeater {
                model: backend.summary
                Rectangle {
                    id: row
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: Math.max(Math.round(theme.em * 2.8), content.implicitHeight + theme.em * 0.9)
                    radius: theme.radiusMd
                    color: rowArea.containsMouse ? theme.hover : "transparent"
                    Behavior on color { ColorAnimation { duration: theme.motionFast } }

                    Rectangle {  // separator
                        visible: row.index > 0
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: theme.space4
                        anchors.rightMargin: theme.space4
                        height: 1
                        color: theme.cardBorder
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
                        anchors.leftMargin: theme.space4
                        anchors.rightMargin: theme.space3
                        spacing: theme.em * 0.7
                        Icon {
                            Layout.preferredWidth: theme.em * 1.4
                            glyph: row.modelData.glyph
                            color: theme.accent
                        }
                        Text {
                            Layout.preferredWidth: theme.em * 9
                            text: row.modelData.label
                            textFormat: Text.PlainText
                            color: theme.dimOn(row.color)
                            wrapMode: Text.WordWrap  // long (French) labels on 2 lines, not cut
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: row.modelData.value
                            textFormat: Text.PlainText
                            color: theme.text
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }
                        TpButton {
                            flat: true
                            size: "sm"
                            text: i18n.tr("Change")
                            onClicked: backend.goTo(row.modelData.step)
                        }
                    }
                }
            }
        }
    }

    SetupHeading { text: i18n.tr("When setup is finished") }

    Card {
        Layout.fillWidth: true
        implicitHeight: after.implicitHeight + theme.padCard * 2
        ColumnLayout {
            id: after
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.padCard
            spacing: theme.space3
            TpSwitch {
                objectName: "openScreenView"
                Layout.fillWidth: true
                wrap: true
                text: i18n.tr("Show where overlays are: Overlays page in Screen view, to move them")
                checkable: false
                checked: backend.openScreenView
                onClicked: backend.setOpenScreenView(!backend.openScreenView)
            }
            TpSwitch {
                objectName: "testOnScreen"
                Layout.fillWidth: true
                wrap: true
                text: i18n.tr("Test on screen: overlays show a simulated race for a few seconds")
                checkable: false
                checked: backend.testOnScreen
                onClicked: backend.setTestOnScreen(!backend.testOnScreen)
            }
        }
    }

    SetupHeading { text: i18n.tr("Good to know") }

    Card {
        Layout.fillWidth: true
        implicitHeight: tips.implicitHeight + theme.padCard * 2

        ColumnLayout {
            id: tips
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.padCard
            spacing: theme.em * 0.7
            Repeater {
                model: [
                    { glyph: "", text: i18n.tr("Overlays show while you drive and hide in the game menus (Auto Hide).") },
                    { glyph: "", text: i18n.tr("Move overlays in the Screen view of the Overlays page, or drag them on screen while they are unlocked.") },
                    { glyph: "", text: i18n.tr("Ctrl+K searches and runs anything in the app.") },
                    { glyph: "", text: i18n.tr("Open this wizard again from Help > Setup Wizard.") }
                ]
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: theme.space5
                    Icon {
                        Layout.preferredWidth: theme.em * 1.4
                        Layout.alignment: Qt.AlignTop
                        glyph: modelData.glyph
                        color: theme.dimText
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.text
                        textFormat: Text.PlainText
                        color: theme.text
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
