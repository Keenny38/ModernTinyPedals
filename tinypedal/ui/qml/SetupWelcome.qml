import QtQuick
import QtQuick.Layouts

// Welcome step: language (wizard texts change at once) & what the wizard sets up
SetupStep {
    SetupHeading { text: i18n.tr("Language") }

    Flow {
        Layout.fillWidth: true
        spacing: theme.em * 0.7
        Repeater {
            model: backend.languages
            SetupCard {
                required property var modelData
                width: Math.min(theme.em * 15, parent.width)
                tileText: modelData.code
                title: modelData.name
                text: modelData.greeting
                checked: backend.language === modelData.name
                onClicked: backend.setLanguage(modelData.name)
            }
        }
    }

    SetupHeading { text: i18n.tr("What you will set up") }

    Card {
        Layout.fillWidth: true
        implicitHeight: plan.implicitHeight + theme.em * 1.6

        ColumnLayout {
            id: plan
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.em * 0.8
            spacing: theme.em * 0.75
            Repeater {
                model: backend.steps.slice(1, backend.stepCount - 1)  // game to overlays
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: theme.em * 0.8
                    Icon {
                        Layout.preferredWidth: theme.em * 1.6
                        Layout.alignment: Qt.AlignTop
                        glyph: modelData.glyph
                        color: theme.accent
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Text {
                            Layout.fillWidth: true
                            text: modelData.label
                            color: theme.text
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.subtitle
                            color: theme.dimText
                            wrapMode: Text.WordWrap
                            font.pointSize: theme.fontPoint * 0.92
                        }
                    }
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        text: i18n.tr("Takes about a minute. Nothing is changed until you finish.")
        color: theme.dimText
        wrapMode: Text.WordWrap
        font.pointSize: theme.fontPoint * 0.92
    }
}
