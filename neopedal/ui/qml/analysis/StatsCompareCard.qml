import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Friend's personal bests against yours, personal best codes (copy yours, compare another's)
TpSectionCard {
    id: card
    property bool canShare: false  // selected vehicle has a personal best: its code can be copied
    readonly property bool allTracks: backend.allTracks
    readonly property var friend: backend.friend
    readonly property bool hasFriend: friend.visible === true
    // Backend tone name in its status color (gain, loss), else fallback
    function tone(name, fallback) { return name === "loss" || name === "gain" ? theme.tone(name) : fallback }
    objectName: "compareCard"
    title: card.hasFriend ? i18n.tr("Friend") + " · " + (card.friend.name || "") : i18n.tr("Friends & Codes")
    glyph: ""  // people
    tip: i18n.tr("Personal bests of a friend (exported session history) or of a personal best code against yours")
    actions: TpButton {
        visible: card.hasFriend
        fallback: "✕"
        glyph: theme.glyphs.remove
        flat: true
        size: "sm"
        tip: i18n.tr("Stop Comparing With Friend")
        onClicked: backend.clearFriend()
    }
    Text {
        text: card.hasFriend ? (card.friend.summary || "")
                             : i18n.tr("Compare your personal bests with the session history a friend exported (Export menu).")
        color: theme.dimText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        textFormat: Text.PlainText
    }
    TpButton {
        visible: !card.hasFriend
        size: "sm"
        text: i18n.tr("Compare With a Friend's Stats…")
        onClicked: backend.importFriend()
    }
    RowLayout {
        visible: (card.friend.rows || []).length > 0
        Layout.fillWidth: true
        spacing: theme.space3
        TpHeaderCell { text: card.allTracks ? i18n.tr("Track") : i18n.tr("Class"); Layout.fillWidth: true }
        TpHeaderCell { text: i18n.tr("You"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 5 }
        TpHeaderCell { text: card.friend.name || ""; align: Qt.AlignRight; Layout.preferredWidth: theme.em * 5 }
        TpHeaderCell { text: i18n.tr("Gap"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 4.4 }
    }
    Repeater {
        model: card.friend.rows || []
        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: theme.space3
            Text {
                text: card.allTracks ? modelData.track + " · " + modelData.vehicleClass : modelData.vehicleClass
                textFormat: Text.PlainText
                color: theme.text
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Text { text: modelData.mine; color: theme.text; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5; horizontalAlignment: Text.AlignRight; textFormat: Text.PlainText }
            Text { text: modelData.friend; color: theme.text; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5; horizontalAlignment: Text.AlignRight; textFormat: Text.PlainText }
            Text {
                text: modelData.gap
                textFormat: Text.PlainText
                color: card.tone(modelData.gapColor, theme.dimText)
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                Layout.preferredWidth: theme.em * 4.4
                horizontalAlignment: Text.AlignRight
            }
        }
    }
    // Personal best codes: yours copied (selected vehicle), another driver's compared & offered as goal
    StatsLabel { text: i18n.tr("Personal Best Code") }
    Flow {
        Layout.fillWidth: true
        spacing: theme.space2
        TpButton {
            visible: !card.allTracks
            size: "sm"
            text: i18n.tr("Copy Personal Best Code")
            enabled: card.canShare
            onClicked: backend.copyPbCode()
        }
        TpButton {
            size: "sm"
            text: i18n.tr("Compare a Personal Best Code…")
            onClicked: backend.pastePbCode()
        }
    }
}
