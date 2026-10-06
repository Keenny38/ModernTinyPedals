import QtQuick
import QtQuick.Layouts

// Game step: telemetry API, running game marked (and picked until the driver chooses)
SetupStep {
    Repeater {
        model: backend.games
        SetupCard {
            required property var modelData
            Layout.fillWidth: true
            glyph: ""  // car
            title: modelData.name
            text: modelData.detail
            badge: modelData.running ? i18n.tr("Running") : ""
            checked: backend.game === modelData.name
            onClicked: backend.setGame(modelData.name)
        }
    }
}
