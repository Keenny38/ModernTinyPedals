import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Level of the best lap of each track & class on community lap times (All Tracks)
TpSectionCard {
    id: card
    title: i18n.tr("Levels, All Tracks")
    glyph: ""  // star
    tip: i18n.tr("Level of your best lap of each track & class on community lap times")
    Repeater {
        model: backend.levels
        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Rectangle {
                Layout.preferredWidth: theme.em * 1.3
                Layout.preferredHeight: theme.em * 1.3
                radius: width / 2
                color: modelData.color
                Text {
                    anchors.centerIn: parent
                    text: modelData.letter
                    textFormat: Text.PlainText
                    color: theme.inkOn(modelData.color)  // readable on level color
                    font.pointSize: theme.fontTiny
                    font.weight: Font.Bold
                }
            }
            Text { text: modelData.name; color: theme.text; elide: Text.ElideRight; Layout.preferredWidth: theme.em * 8; textFormat: Text.PlainText }
            TpMeter {  // share of best laps at this level (a few laps: still a visible bar)
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                thickness: Math.round(theme.em * 0.6)
                value: modelData.count ? Math.max(modelData.ratio, 0.04) : 0
                tint: modelData.color
                name: modelData.name
            }
            Text {
                text: modelData.count
                textFormat: Text.PlainText
                color: modelData.count ? theme.text : theme.dimText
                font.weight: modelData.count ? Font.DemiBold : Font.Normal
                font.features: { "tnum": 1 }
                Layout.preferredWidth: theme.em * 1.6
                horizontalAlignment: Text.AlignRight
            }
        }
    }
    Text {
        visible: text !== ""
        Layout.fillWidth: true
        text: backend.levelsInfo
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontLabel
        wrapMode: Text.WordWrap
    }
}
