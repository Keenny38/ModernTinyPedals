import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Lap time goal of selected vehicle: progress since first lap time, told once beaten
TpSectionCard {  // lap time goal of selected vehicle: progress since first lap time, told once beaten
    id: card
    readonly property var goal: backend.goal
    // Backend tone name in its status color (gain, loss), else fallback
    function tone(name, fallback) { return name === "loss" || name === "gain" ? theme.tone(name) : fallback }
    objectName: "goalCard"
    visible: card.goal.visible === true
    title: i18n.tr("Lap Time Goal")
    glyph: ""  // target
    tip: i18n.tr("Lap time to beat with this car, saved: a message tells you once it is beaten")
    actions: [
        TpButton {
            visible: card.goal.set === true
            flat: true
            size: "sm"
            text: i18n.tr("Remove")
            onClicked: backend.clearGoal()
        },
        TpButton {
            size: "sm"
            text: card.goal.set === true ? i18n.tr("Change…") : i18n.tr("Set…")
            onClicked: backend.editGoal()
        }
    ]
    RowLayout {
        visible: card.goal.set === true
        Layout.fillWidth: true
        spacing: theme.space4
        Text {
            text: card.goal.time || ""
            textFormat: Text.PlainText
            color: card.goal.reached ? theme.gain : theme.accent
            font.pointSize: theme.fontLarge
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
        }
        Text {
            text: card.goal.gap || ""
            textFormat: Text.PlainText
            color: card.tone(card.goal.gapColor, theme.dimText)
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }
    TpMeter {  // progress from the first lap time of the history to the goal
        visible: card.goal.set === true && (card.goal.ratio || -1) >= 0
        Layout.fillWidth: true
        value: Math.max(card.goal.ratio || 0, 0)
        tint: card.goal.reached ? theme.gain : theme.accent
        name: i18n.tr("Lap Time Goal")
    }
    Text {
        Layout.fillWidth: true
        text: card.goal.set === true ? i18n.tr("Personal best") + " " + (card.goal.best || "—")
                                     : (card.goal.suggestion || i18n.tr("No goal yet: set a lap time to beat."))
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontLabel
        wrapMode: Text.WordWrap
    }
}
