import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Official races to come (option): your best lap of each class on their track; a race or a class opens a menu
// (stats, recorded laps, race calculator)
TpSectionCard {  // official races to come (option): your best lap of each class on their track
    id: card
    signal raceClicked(string track, string vehicle, Item button)  // page opens its menu below the button
    objectName: "upcomingCard"
    visible: backend.upcomingEnabled
    title: i18n.tr("Official Races to Come")
    glyph: ""  // calendar
    tip: i18n.tr("Next daily races of RaceControl with your best laps on their track (View menu to hide)")
    actions: TpButton {
        flat: true
        size: "sm"
        glyph: theme.glyphs.refresh
        fallback: i18n.tr("Read Again")
        tip: i18n.tr("Read Again")
        onClicked: backend.refreshUpcoming()
    }
    Text {
        visible: text !== ""
        text: backend.upcoming.note || ""
        textFormat: Text.PlainText
        color: theme.dimText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    Repeater {
        model: backend.upcoming.races || []
        ColumnLayout {
            id: raceItem
            required property var modelData
            readonly property real indent: theme.em * 2.6 + theme.space3  // under the circuit logo
            Layout.fillWidth: true
            spacing: theme.space1
            StatsRowButton {  // race: logo, track, start · tier · title (menu of its track)
                id: raceButton
                tip: i18n.tr("Track stats, recorded laps & race calculator")
                Accessible.name: raceItem.modelData.track
                onClicked: card.raceClicked(raceItem.modelData.known ? raceItem.modelData.track : "",
                                            raceItem.modelData.bests.length === 1 ? raceItem.modelData.bests[0].vehicle : "",
                                            raceButton)
                GameLogo {
                    source: raceItem.modelData.logo || ""
                    boxWidth: theme.em * 2.6
                    boxHeight: theme.em * 1.6
                }
                ColumnLayout {
                    spacing: 0
                    Layout.fillWidth: true
                    Text {
                        text: raceItem.modelData.track
                        textFormat: Text.PlainText
                        color: theme.text
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: [raceItem.modelData.start, raceItem.modelData.tier, raceItem.modelData.title]
                              .filter(function(part) { return part }).join(" · ")
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        font.features: { "tnum": 1 }
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }
            Repeater {
                model: raceItem.modelData.bests
                StatsRowButton {  // class: your best lap & its level (menu of this track & vehicle)
                    id: classButton
                    required property var modelData
                    Layout.leftMargin: raceItem.indent
                    tip: i18n.tr("Track stats, recorded laps & race calculator")
                    Accessible.name: raceItem.modelData.track + ", " + modelData.vehicleClass + ", " + modelData.best
                    onClicked: card.raceClicked(raceItem.modelData.track, modelData.vehicle, classButton)
                    Text {
                        text: modelData.vehicleClass
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text { text: modelData.best; color: theme.text; font.features: { "tnum": 1 }; textFormat: Text.PlainText }
                    StatsPill {
                        text: modelData.level === "—" || modelData.level === "-" ? "" : modelData.level
                        tint: modelData.color || theme.dimText
                    }
                }
            }
            Text {
                text: raceItem.modelData.note
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                Layout.leftMargin: raceItem.indent
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
        }
    }
}
