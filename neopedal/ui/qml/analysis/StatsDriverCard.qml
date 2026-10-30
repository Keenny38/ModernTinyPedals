import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Driver of All Tracks: game profile, Steam picture, ranks & badge, other accounts, races of results files
TpSectionCard {  // driver: game profile, Steam picture, races of game results files
    id: card
    readonly property var driver: backend.driver
    visible: card.driver.visible === true
    title: i18n.tr("Driver")
    glyph: "\uE77B"  // contact
    tip: card.driver.info || ""
    RowLayout {
        Layout.fillWidth: true
        spacing: theme.em * 0.7
        Rectangle {  // Steam profile picture, else initials
            Layout.preferredWidth: Math.round(theme.em * 3.4)
            Layout.preferredHeight: Layout.preferredWidth
            radius: theme.radiusMd
            color: theme.tint(theme.accent, "selected")
            Text {
                anchors.centerIn: parent
                visible: avatar.status !== Image.Ready
                text: card.driver.initials || ""
                textFormat: Text.PlainText
                color: theme.accent
                font.pointSize: theme.fontHeading
                font.weight: Font.Bold
            }
            Image {
                id: avatar
                anchors.fill: parent
                anchors.margins: 1
                source: card.driver.avatar || ""
                sourceSize.width: width * 2
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                smooth: true
            }
        }
        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            Text {
                text: card.driver.name || ""
                textFormat: Text.PlainText
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontSubtitle
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Text {
                visible: text !== ""
                text: card.driver.detail || ""
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontLabel
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }
    ColumnLayout {  // driver & safety ranks of game menu: rank in its color, progress to next tier; badge
        visible: (card.driver.ranks || []).length > 0 || ((card.driver.badge || {}).name || "") !== ""
        Layout.fillWidth: true
        Layout.topMargin: theme.space2
        spacing: theme.space3
        Repeater {
            model: card.driver.ranks || []
            RowLayout {
                required property var modelData
                readonly property color rankColor: (theme.dark ? modelData.color : modelData.lightColor)
                                                   || theme.accent
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                Text {
                    text: modelData.label
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    Layout.preferredWidth: theme.em * 6.5
                    elide: Text.ElideRight
                }
                Text {
                    text: modelData.value
                    textFormat: Text.PlainText
                    color: parent.rankColor
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontSubtitle
                    Layout.preferredWidth: theme.em * 5.5
                }
                TpMeter {  // progress to next tier
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    value: modelData.progress
                    tint: parent.rankColor
                    name: modelData.label
                }
                Text {
                    text: modelData.progressText
                    textFormat: Text.PlainText
                    color: theme.text
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                    horizontalAlignment: Text.AlignRight
                    Layout.preferredWidth: theme.em * 2.6
                }
                Text {  // change since previous rank
                    visible: modelData.change !== ""
                    text: (modelData.changeTone > 0 ? "\u25B2 " : "\u25BC ") + modelData.change
                    textFormat: Text.PlainText
                    color: modelData.changeTone > 0 ? theme.gain : theme.loss
                    font.pointSize: theme.fontCaption
                    font.features: { "tnum": 1 }
                }
            }
        }
        Repeater {  // rank over time, one line per rank seen at least twice (empty chart: no line)
            model: card.driver.ranks || []
            TpRankLine {  // rank name on the left, line in the rank color
                required property var modelData
                visible: (modelData.chart || []).length > 1
                Layout.fillWidth: true
                labelShown: true
                points: modelData.chart
                tint: (theme.dark ? modelData.color : modelData.lightColor) || theme.accent
                label: modelData.label
            }
        }
        RowLayout {  // badge of game menu: game icon, name in its color, description
            readonly property var badge: card.driver.badge || {}
            readonly property color badgeColor: (theme.dark ? badge.color : badge.lightColor) || theme.text
            visible: (badge.name || "") !== ""
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Text {
                text: i18n.tr("Badge")
                color: theme.dimText
                font.pointSize: theme.fontSmall
                Layout.preferredWidth: theme.em * 6.5
                Layout.alignment: Qt.AlignTop
                elide: Text.ElideRight
            }
            Image {
                readonly property int side: Math.round(theme.em * 1.4)
                visible: source !== "" && status === Image.Ready
                source: parent.badge.icon || ""
                sourceSize: Qt.size(side * 2, side * 2)  // sharp on high DPI screen
                Layout.preferredWidth: side
                Layout.preferredHeight: side
                Layout.alignment: Qt.AlignTop
                asynchronous: true
                smooth: true
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                Text {
                    text: parent.parent.badge.name || ""
                    textFormat: Text.PlainText
                    color: parent.parent.badgeColor
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontSubtitle
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Text {
                    visible: text !== ""
                    text: parent.parent.badge.description || ""
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontCaption
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }
        Text {
            visible: text !== ""
            text: card.driver.ranksInfo || ""
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontCaption
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }
    ColumnLayout {  // other game accounts of this computer: last ranks seen, badge, date
        visible: (card.driver.otherAccounts || []).length > 0
        Layout.fillWidth: true
        Layout.topMargin: theme.space2
        spacing: theme.space2
        TpSectionLabel { text: i18n.tr("Other accounts"); Layout.fillWidth: true }
        Repeater {
            model: card.driver.otherAccounts || []
            RowLayout {
                id: accountRow
                required property var modelData
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                Image {  // Steam profile picture of account
                    readonly property int side: Math.round(theme.em * 1.5)
                    visible: source !== "" && status === Image.Ready
                    source: accountRow.modelData.avatar
                    sourceSize: Qt.size(side * 2, side * 2)
                    Layout.preferredWidth: side
                    Layout.preferredHeight: side
                    asynchronous: true
                    smooth: true
                }
                Text {
                    text: accountRow.modelData.name
                    textFormat: Text.PlainText
                    color: theme.text
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.minimumWidth: theme.em * 4
                }
                Repeater {
                    model: accountRow.modelData.ranks
                    Text {
                        required property var modelData
                        text: modelData.label + " " + modelData.value
                        textFormat: Text.PlainText
                        color: (theme.dark ? modelData.color : modelData.lightColor) || theme.text
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontSmall
                    }
                }
                Text {
                    readonly property var badge: accountRow.modelData.badge || {}
                    visible: (badge.name || "") !== ""
                    text: badge.name || ""
                    textFormat: Text.PlainText
                    color: (theme.dark ? badge.color : badge.lightColor) || theme.text
                    font.pointSize: theme.fontSmall
                }
                Text {  // when ranks were seen
                    text: accountRow.modelData.when
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontCaption
                    font.features: { "tnum": 1 }
                }
            }
        }
    }
    GridLayout {  // races of results files
        visible: (card.driver.figures || []).length > 0
        Layout.fillWidth: true
        Layout.topMargin: theme.space2
        columns: 3
        columnSpacing: theme.em * 0.5
        rowSpacing: theme.em * 0.4
        Repeater {
            model: card.driver.figures || []
            TpKeyValue {  // label above the value, as every key figure
                required property var modelData
                layout: "stack"
                large: true
                label: modelData.label
                tip: modelData.tip || ""
                value: modelData.value
                Layout.preferredWidth: 1  // equal columns
            }
        }
    }
    Text {
        visible: text !== ""
        text: card.driver.info || ""
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontCaption
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    RowLayout {  // lap times of stats missing or slower than in results files
        visible: (card.driver.fixes || 0) > 0
        Layout.fillWidth: true
        Layout.topMargin: theme.space1
        spacing: theme.em * 0.5
        Icon { glyph: "\uE916"; size: theme.iconSm; color: theme.accent }  // stopwatch
        Text {
            text: card.driver.fixText || ""
            textFormat: Text.PlainText
            color: theme.text
            font.pointSize: theme.fontLabel
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        TpButton {
            text: i18n.tr("Complete…")
            tip: i18n.tr("Add lap times of race results missing from your stats, or faster than them")
            enabled: !backend.editing
            onClicked: backend.completeLapTimes()
        }
    }
}
