import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Progress of the last 7 days (All Tracks): driving summary, goals reached, new personal bests, goals near; a row
// shows its track & vehicle (stats_analysis.weekly_progress, shared with the Home page)
TpSectionCard {
    id: card
    readonly property var weekly: backend.weekly
    readonly property var rows: weekly.rows || []
    objectName: "weekCard"
    title: i18n.tr("This Week")
    glyph: ""  // calendar
    tip: i18n.tr("Last 7 days: driving time, goals reached, new personal bests & goals within half a second")
    Text {
        visible: text !== ""
        text: card.weekly.summary || ""
        textFormat: Text.PlainText
        color: theme.text
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    Repeater {
        model: card.rows
        StatsRowButton {
            id: weekRow
            required property var modelData
            tip: i18n.tr("Show this track & car")
            Accessible.name: modelData.text + ", " + modelData.detail
            onClicked: backend.openSession(modelData.track, modelData.vehicle)
            Icon {  // kind told by its icon & its words, color only adds to them
                glyph: weekRow.modelData.glyph
                fallback: weekRow.modelData.kind === "goal_near" ? "◎" : weekRow.modelData.kind === "record" ? "★" : "✓"
                size: theme.iconSm
                color: weekRow.modelData.tone === "gain" ? theme.gain : theme.accent
                Layout.alignment: Qt.AlignTop
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                Text {
                    text: weekRow.modelData.text
                    textFormat: Text.PlainText
                    color: theme.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Text {
                    text: weekRow.modelData.detail
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }
    }
    Text {
        visible: (card.weekly.more || 0) > 0
        text: i18n.tr("%1 more").arg(card.weekly.more || 0)
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontSmall
        Layout.fillWidth: true
    }
    TpStateView {  // nothing driven in the last days
        empty: (card.weekly.summary || "") === ""
        compact: true
        glyph: ""  // calendar
        text: i18n.tr("No session in the last 7 days.")
    }
}
