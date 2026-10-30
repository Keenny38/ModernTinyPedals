import QtQuick
import QtQuick.Layouts
import "../components"

// Units step: metric or imperial units for the preset (or its own mixed units kept)
SetupStep {
    Repeater {
        model: backend.unitSystems
        SetupCard {
            id: unitCard
            required property var modelData
            Layout.fillWidth: true
            glyph: ""  // gauge
            title: modelData.label
            checked: backend.units === modelData.key
            onClicked: backend.setUnits(modelData.key)

            Flow {
                width: parent.width
                spacing: theme.space3
                Repeater {
                    model: unitCard.modelData.units
                    Pill {
                        required property string modelData
                        text: modelData
                        tint: unitCard.checked ? theme.accent : theme.dimText
                    }
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        text: i18n.tr("Saved in the preset. Each unit can also be set on its own later.")
        color: theme.dimText
        wrapMode: Text.WordWrap
        font.pointSize: theme.fontLabel
    }
}
