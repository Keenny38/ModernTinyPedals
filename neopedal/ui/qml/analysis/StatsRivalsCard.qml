import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// People of your class met in several online races; a rival opens a menu on the last race together
TpSectionCard {  // people of your class met in several online races (results files)
    id: card
    signal rivalClicked(string track, string vehicle, string path, Item button)  // page opens its menu
    // Backend tone name in its status color (gain, loss), else fallback
    function tone(name, fallback) { return name === "loss" || name === "gain" ? theme.tone(name) : fallback }
    objectName: "rivalsCard"
    visible: backend.rivals.length > 0
    title: i18n.tr("Rivals")
    glyph: ""  // people
    tip: i18n.tr("People of your class met in several online races: times finished ahead & behind, best lap gap")
    RowLayout {  // columns of the rows (inside their padding)
        Layout.fillWidth: true
        Layout.leftMargin: theme.space2
        Layout.rightMargin: theme.space2
        spacing: theme.space3
        TpHeaderCell { text: i18n.tr("Driver"); Layout.fillWidth: true }
        TpHeaderCell { text: i18n.tr("Races"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 4.8 }
        TpHeaderCell { text: i18n.tr("Ahead-Behind"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 7 }
        TpHeaderCell { text: i18n.tr("Gap"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 4.4 }
    }
    Repeater {
        model: backend.rivals
        StatsRowButton {  // last race together: results, its track & your vehicle (menu)
            id: rivalRow
            required property var modelData
            tip: modelData.tip
            Accessible.name: modelData.name
            onClicked: card.rivalClicked(modelData.track, modelData.vehicle, modelData.path, rivalRow)
            Text { text: rivalRow.modelData.name; color: theme.text; elide: Text.ElideRight; Layout.fillWidth: true; textFormat: Text.PlainText }
            Text {
                text: rivalRow.modelData.races
                textFormat: Text.PlainText
                color: theme.dimText
                font.features: { "tnum": 1 }
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: theme.em * 4.8
            }
            Text {
                text: rivalRow.modelData.record
                textFormat: Text.PlainText
                color: card.tone(rivalRow.modelData.tone, theme.text)
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: theme.em * 7
            }
            Text {
                text: rivalRow.modelData.gap
                textFormat: Text.PlainText
                color: card.tone(rivalRow.modelData.gapTone, theme.dimText)
                font.features: { "tnum": 1 }
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: theme.em * 4.4
            }
        }
    }
}
