import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator page: data source & race plan actions, race setup, key figures & strategy timeline
// (shared by all tabs), then Fuel (inputs, pit stop plan, scenarios, consumption history), Tyres (tyre
// wear & rules, tyre plan, stock) and Team (stints of the team car from the game) tabs.
// Inputs are applied on Enter or leaving a field, Up / Down step them, Ctrl+Z / Ctrl+Y undo & redo.
TpPage {
    id: page

    readonly property var inputs: backend.inputs
    readonly property var specs: backend.specs
    readonly property var header: backend.header
    readonly property var calc: backend.calc
    readonly property bool compact: width < theme.em * 62  // icon buttons, tiles on two rows
    readonly property color tyreColor: "#F5B342"

    function tileGlyph(key) {
        return { fuel: "", energy: "", pits: "", stint: "", refill: "", tyres: "" }[key] || ""
    }
    function tileTint(key) {
        return { fuel: "#4C9AFF", energy: "#F5A623", pits: theme.accent, stint: "#7ED321", refill: "#50E3C2",
                 tyres: page.tyreColor }[key] || theme.accent
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.55

        // Data source, live, undo & redo, race plan & data actions
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5

            GameLogo {  // circuit logo of game
                source: page.header.trackLogo || ""
                boxWidth: theme.em * 3.0
                boxHeight: theme.em * 1.8
            }
            Rectangle {  // source chip
                implicitHeight: Math.round(theme.em * 2)
                implicitWidth: Math.min(sourceDot.width + sourceText.implicitWidth + theme.em * 1.6, theme.em * 24)
                Layout.minimumWidth: theme.em * 5
                Layout.maximumWidth: theme.em * 24
                Layout.fillWidth: false
                radius: height / 2
                color: Qt.rgba(sourceDot.color.r, sourceDot.color.g, sourceDot.color.b, theme.dark ? 0.14 : 0.1)
                border.width: 1
                border.color: Qt.rgba(sourceDot.color.r, sourceDot.color.g, sourceDot.color.b, 0.5)
                Rectangle {
                    id: sourceDot
                    x: theme.em * 0.6
                    width: Math.round(theme.em * 0.55); height: width; radius: width / 2
                    color: page.header.live ? "#3DDC84" : "#5AAEFF"
                    anchors.verticalCenter: parent.verticalCenter
                    SequentialAnimation on opacity {
                        // A few pulses when state starts or page shows again, then still: no endless redraw
                        running: page.header.live && pageState.active
                        loops: 3
                        onRunningChanged: if (!running) sourceDot.opacity = 1
                        NumberAnimation { to: 0.35; duration: 900; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 900; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    id: sourceText
                    x: sourceDot.x + sourceDot.width + theme.em * 0.4
                    width: parent.width - x - theme.em * 0.6
                    anchors.verticalCenter: parent.verticalCenter
                    text: "<b>" + (page.header.live ? i18n.tr("Live") : i18n.tr("File")) + "</b> · " + page.header.source
                    textFormat: Text.StyledText
                    color: theme.text
                    elide: Text.ElideRight
                }
                HoverHandler { id: sourceHover }
                ToolTip.visible: sourceHover.hovered
                ToolTip.text: page.header.live ? i18n.trm("Live Source: " + page.header.source)
                                               : i18n.trm("File Source: " + page.header.source)
                ToolTip.delay: 500
            }
            RaceSwitch {
                Layout.fillWidth: false
                text: i18n.tr("Follow Live")
                tip: i18n.tr("Inputs follow each new lap of the live session")
                on: page.header.followLive
                onSwitched: function(on) { backend.setFollowLive(on) }
            }
            RaceSwitch {
                Layout.fillWidth: false
                text: i18n.tr("Live Race")
                tip: i18n.tr("During a race: plan of the rest of the race from now (laps & time done, fuel, energy & tyres of the car, stops done)")
                on: page.header.liveRace
                onSwitched: function(on) { backend.setLiveRace(on) }
            }
            Rectangle {  // live race status
                visible: page.header.liveStatus !== ""
                implicitHeight: Math.round(theme.em * 1.6)
                implicitWidth: liveText.implicitWidth + theme.em * 1.1
                radius: height / 2
                color: theme.hover
                Text {
                    id: liveText
                    anchors.centerIn: parent
                    text: page.header.liveStatus
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.88
                }
                HoverHandler { id: liveHover }
                ToolTip.visible: liveHover.hovered && page.header.liveTip !== ""
                ToolTip.text: page.header.liveTip
                ToolTip.delay: 300
            }
            Item { Layout.fillWidth: true }
            TpButton {
                flat: true
                glyph: ""  // undo
                text: theme.iconFont === "" ? i18n.tr("Undo") : ""
                tip: i18n.tr("Undo (Ctrl+Z)")
                onClicked: backend.undo()
                Accessible.name: i18n.tr("Undo")
            }
            TpButton {
                flat: true
                glyph: ""  // redo
                text: theme.iconFont === "" ? i18n.tr("Redo") : ""
                tip: i18n.tr("Redo (Ctrl+Y)")
                onClicked: backend.redo()
                Accessible.name: i18n.tr("Redo")
            }
            TpButton {
                id: planButton
                glyph: ""  // document
                text: page.compact ? "" : i18n.tr("Race Plan")
                tip: i18n.tr("Race setup, fuel & tyre plan in one file, to keep or share")
                onClicked: planMenu.popup(planButton, 0, planButton.height + 4)
                Accessible.name: i18n.tr("Race Plan")
                TpMenu {
                    id: planMenu
                    MenuItem { text: i18n.tr("Open Race Plan..."); onTriggered: backend.openRacePlan() }
                    MenuItem { text: i18n.tr("Save Race Plan As..."); onTriggered: backend.saveRacePlan() }
                    MenuSeparator {}
                    MenuItem { text: i18n.tr("Copy Share Code"); onTriggered: backend.copyShareCode() }
                    MenuItem { text: i18n.tr("Paste Share Code..."); onTriggered: backend.pasteShareCode() }
                    MenuSeparator {}
                    MenuItem {
                        text: i18n.tr("Save for Current Car & Track")
                        enabled: page.header.combo !== ""
                        onTriggered: backend.saveComboPlan()
                    }
                    MenuItem {
                        text: i18n.tr("Open Plan of Car & Track Automatically")
                        checkable: true
                        checked: page.header.autoCombo
                        onTriggered: backend.setAutoComboPlan(checked)
                    }
                }
            }
            TpButton {
                glyph: ""  // refresh
                text: page.compact ? "" : i18n.tr("Load Live")
                tip: i18n.tr("Laps of current session, race length of a live race")
                onClicked: backend.loadLive()
                Accessible.name: i18n.tr("Load Live")
            }
            TpButton {
                glyph: ""  // folder open
                text: page.compact ? "" : i18n.tr("Load File")
                tip: i18n.tr("Consumption history file")
                onClicked: backend.loadFile()
                Accessible.name: i18n.tr("Load File")
            }
            TpButton {
                glyph: ""  // clear
                text: page.compact ? "" : i18n.tr("Reset to Zero")
                tip: i18n.tr("Reset to Zero") + ": " + i18n.tr("Clear every input")
                onClicked: backend.resetValues()
                Accessible.name: i18n.tr("Reset to Zero")
            }
        }

        // Race setup: race type & length, formation, pit stop time, safety margin
        RaceSetup {
            Layout.fillWidth: true
            store: page
        }

        // Key figures
        GridLayout {
            Layout.fillWidth: true
            columns: page.compact ? 3 : 6
            columnSpacing: theme.em * 0.55
            rowSpacing: theme.em * 0.55
            Repeater {
                model: backend.tiles
                RaceTile {
                    required property var modelData
                    visible: modelData.visible
                    title: modelData.title
                    value: modelData.value
                    detail: modelData.detail
                    tip: modelData.tip
                    warning: modelData.warning
                    glyph: page.tileGlyph(modelData.key)
                    tint: page.tileTint(modelData.key)
                }
            }
        }

        RaceTimeline {
            Layout.fillWidth: true
            timeline: backend.timeline
            levels: backend.fuelLevels
            summary: backend.summary
        }

        // Tabs
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.2
            Repeater {
                id: tabRepeater
                model: [
                    { text: i18n.tr("Fuel"), glyph: "" },
                    { text: i18n.tr("Tyres"), glyph: "" },
                    { text: i18n.tr("Team"), glyph: "" },
                ]
                AbstractButton {
                    id: tabButton
                    required property var modelData
                    required property int index
                    readonly property bool current: page.header.tab === index
                    implicitHeight: Math.round(theme.em * 2.2)
                    implicitWidth: tabRow.implicitWidth + theme.em * 1.6
                    hoverEnabled: true
                    focusPolicy: Qt.TabFocus
                    Accessible.role: Accessible.PageTab
                    Accessible.name: modelData.text
                    onClicked: backend.setTab(index)
                    background: Rectangle {
                        radius: theme.em * 0.45
                        color: tabButton.hovered && !tabButton.current ? theme.hover : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    contentItem: Item {
                        Row {
                            id: tabRow
                            anchors.centerIn: parent
                            spacing: theme.em * 0.4
                            Icon {
                                glyph: tabButton.modelData.glyph
                                size: theme.em * 0.9
                                color: tabButton.current ? theme.accent : theme.dimText
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: tabButton.modelData.text
                                color: tabButton.current ? theme.text : theme.dimText
                                font.weight: tabButton.current ? Font.DemiBold : Font.Normal
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                }
            }
            Item { Layout.fillWidth: true }
            TpButton {
                visible: page.header.tab === 0
                flat: true
                checked: page.header.showHistory
                glyph: ""  // history
                text: page.compact ? "" : i18n.tr("History")
                tip: page.header.showHistory ? i18n.tr("Hide History") : i18n.tr("Show History")
                onClicked: backend.setShowHistory(!page.header.showHistory)
                Accessible.name: tip
            }
        }
        Item {  // tab underline: slides to current tab
            Layout.fillWidth: true
            Layout.topMargin: -theme.em * 0.55
            implicitHeight: 2
            Rectangle { anchors.fill: parent; color: theme.border; opacity: 0.6 }
            Rectangle {
                readonly property Item target: tabRepeater.itemAt(page.header.tab)
                x: target ? target.x : 0
                width: target ? target.width : 0
                height: 2
                radius: 1
                color: theme.accent
                Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: page.header.tab
            RaceFuelTab { store: page }
            Loader {  // built when first shown
                active: page.header.tab === 1 || item !== null
                sourceComponent: RaceTyreTab { store: page }
            }
            Loader {
                active: page.header.tab === 2 || item !== null
                sourceComponent: RaceTeamTab {}
            }
        }
    }
}
