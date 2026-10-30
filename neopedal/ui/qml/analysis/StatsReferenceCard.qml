import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Lap time reference of selected vehicle: level scale of community lap times, gap, next level, level limits
TpSectionCard {  // other vehicle: values change in place (no fade: keyboard browsing never flickers)
    id: referenceCard
    readonly property var reference: backend.reference
    title: i18n.tr("Lap Time Reference")
    glyph: ""  // globe
    tip: i18n.tr("Community lap times compared with your lap times")
    RowLayout {  // vehicle & level of its personal best
        visible: referenceCard.reference.vehicle !== undefined && referenceCard.reference.vehicle !== ""
        Layout.fillWidth: true
        spacing: theme.em * 0.5
        Text {
            text: referenceCard.reference.vehicle || ""
            textFormat: Text.PlainText
            color: theme.text
            font.pointSize: theme.fontSubtitle
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        StatsPill {
            text: referenceCard.reference.level || ""
            tint: referenceCard.reference.levelColor || theme.dimText
            strong: true
        }
    }
    Text {
        visible: referenceCard.reference.visible === true
        Layout.fillWidth: true
        text: referenceCard.reference.detail || ""
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontLabel
        wrapMode: Text.WordWrap
    }
    StatsGauge {
        visible: referenceCard.reference.visible === true && (referenceCard.reference.gauge || {}).segments !== undefined
        Layout.fillWidth: true
        Layout.topMargin: theme.space2
        scaleData: referenceCard.reference.gauge || ({})
    }
    GridLayout {  // personal best against reference, next level
        visible: referenceCard.reference.visible === true
        Layout.fillWidth: true
        columns: 2
        columnSpacing: theme.em * 0.8
        rowSpacing: theme.em * 0.15
        Text { text: i18n.tr("Reference"); color: theme.dimText; font.pointSize: theme.fontLabel }
        Text {
            text: referenceCard.reference.referenceTime || "—"
            textFormat: Text.PlainText
            color: theme.text
            font.features: { "tnum": 1 }
            Layout.fillWidth: true
        }
        Text { visible: (referenceCard.reference.gapTime || "") !== ""; text: i18n.tr("Gap"); color: theme.dimText; font.pointSize: theme.fontLabel }
        Text {
            visible: (referenceCard.reference.gapTime || "") !== ""
            text: (referenceCard.reference.gapTime || "") + "  (" + (referenceCard.reference.percent || "") + ")"
            textFormat: Text.PlainText
            color: theme.text
            font.features: { "tnum": 1 }
            Layout.fillWidth: true
        }
        Text { visible: (referenceCard.reference.next || "") !== ""; text: i18n.tr("Next level"); color: theme.dimText; font.pointSize: theme.fontLabel }
        RowLayout {
            visible: (referenceCard.reference.next || "") !== ""
            spacing: theme.space3
            Layout.fillWidth: true
            Rectangle {
                visible: (referenceCard.reference.nextLevel || {}).color !== undefined
                implicitWidth: theme.em * 0.65
                implicitHeight: implicitWidth
                radius: width / 2
                color: (referenceCard.reference.nextLevel || {}).color || "transparent"
            }
            Text {
                text: (referenceCard.reference.nextLevel || {}).name !== undefined
                      ? referenceCard.reference.nextLevel.name + "  " + referenceCard.reference.nextLevel.toFind
                      : (referenceCard.reference.next || "")
                textFormat: Text.PlainText
                color: theme.accent
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                elide: Text.ElideRight
                Layout.fillWidth: true
                HoverHandler { id: nextHover }
                ToolTip.visible: nextHover.hovered
                ToolTip.text: referenceCard.reference.next || ""
                ToolTip.delay: theme.tipDelay
            }
        }
    }
    Text {
        visible: referenceCard.reference.visible === true && (referenceCard.reference.fastest || "") !== ""
        Layout.fillWidth: true
        text: referenceCard.reference.fastest || ""
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontLabel
        wrapMode: Text.WordWrap
    }
    // Lap time limit of each level, marks of personal, qualifying & race bests
    RowLayout {  // level limits: folded by default (the scale above shows the levels), saved
        visible: referenceCard.reference.visible === true
        Layout.fillWidth: true
        Layout.topMargin: theme.space2
        StatsLabel { text: i18n.tr("Levels"); Layout.topMargin: 0 }
        TpButton {
            objectName: "levelsFold"
            flat: true
            size: "xs"
            glyph: backend.levelsOpen ? "\uE70E" : "\uE70D"  // chevron up, down
            fallback: backend.levelsOpen ? "▴" : "▾"
            tip: backend.levelsOpen ? i18n.tr("Hide lap time limits of levels") : i18n.tr("Show lap time limits of levels")
            onClicked: backend.setLevelsOpen(!backend.levelsOpen)
        }
    }
    Repeater {
        model: referenceCard.reference.visible && backend.levelsOpen ? referenceCard.reference.ladder : []
        TpListRow {  // level of the personal best: emphasized row, name in bold
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: Math.round(theme.em * 1.75)
            radius: theme.radiusSm
            emphasized: modelData.active === true
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: theme.space3
                anchors.rightMargin: theme.space3
                spacing: theme.space3
                Rectangle {
                    Layout.preferredWidth: theme.em * 0.6
                    Layout.preferredHeight: theme.em * 0.6
                    radius: width / 2
                    color: modelData.color
                }
                Text {
                    text: modelData.name
                    textFormat: Text.PlainText
                    color: theme.text
                    font.weight: modelData.active ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Repeater {
                    model: modelData.pills || []
                    StatsPill {
                        required property var modelData
                        text: modelData
                        tint: theme.accent
                    }
                }
                Text {
                    text: modelData.limit
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.features: { "tnum": 1 }
                    font.pointSize: theme.fontLabel
                    Layout.preferredWidth: theme.em * 5.2
                    horizontalAlignment: Text.AlignRight
                }
            }
        }
    }
    RowLayout {  // no reference: reason
        visible: referenceCard.reference.visible !== true && (referenceCard.reference.reason || "") !== ""
        Layout.fillWidth: true
        spacing: theme.em * 0.5
        Icon { glyph: ""; color: theme.dimText; size: theme.iconSm; Layout.alignment: Qt.AlignTop }  // info
        Text {
            Layout.fillWidth: true
            text: referenceCard.reference.reason || ""
            textFormat: Text.PlainText
            color: theme.dimText
            wrapMode: Text.WordWrap
        }
    }
}
