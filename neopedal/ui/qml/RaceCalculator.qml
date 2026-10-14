import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator page: data source & race plan actions, race setup, key figures & strategy timeline
// (shared by all tabs), then Fuel (inputs, pit stop plan, scenarios, consumption history), Tyres (tyre
// wear & rules, tyre plan, stock), Team (stints of the team car from the game) and Live (every input
// value the game gives, race under way, tyres offered) tabs.
// Inputs are applied on Enter or leaving a field, Up / Down step them, Ctrl+Z / Ctrl+Y undo & redo.
TpPage {
    id: page

    readonly property var inputs: backend.inputs
    readonly property var specs: backend.specs
    readonly property var header: backend.header
    readonly property var calc: backend.calc
    readonly property var tiles: backend.tiles
    readonly property bool compact: width < theme.em * 62  // icon buttons, tiles on two rows
    readonly property color tyreColor: theme.seriesTyre

    function tileGlyph(key) {
        return { fuel: "", energy: "", pits: "", stint: "", refill: "", tyres: "" }[key] || ""
    }
    function tileTint(key) {
        return { fuel: theme.seriesFuel, energy: theme.seriesEnergy, pits: theme.accent, stint: theme.seriesStint, refill: theme.seriesRefill,
                 tyres: page.tyreColor }[key] || theme.accent
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Calculator on / off, then while on: data source, live, undo & redo, race plan & data actions
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5

            RaceSwitch {
                objectName: "gameDataSwitch"
                Layout.fillWidth: false
                // Narrow page: label only while off (state easy to miss from the switch alone)
                text: page.compact && page.header.gameData ? "" : page.header.gameData ? i18n.tr("Enabled") : i18n.tr("Disabled")
                tip: i18n.tr("Race Calculator on or off")
                on: page.header.gameData
                onSwitched: function(on) { backend.setGameData(on) }
                Accessible.name: i18n.tr("Race Calculator on or off")
            }
            Item { Layout.fillWidth: true; visible: !page.header.gameData }
            RowLayout {
                Layout.fillWidth: true
                visible: page.header.gameData
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
                    TpPulseDot {
                        id: sourceDot
                        x: theme.em * 0.6
                        width: Math.round(theme.em * 0.55)
                        color: page.header.live ? theme.live : theme.accent
                        anchors.verticalCenter: parent.verticalCenter
                        pulsing: page.header.live && page.header.gameData  // no animation while hidden (off)
                        pulseDuration: 900
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
                    ToolTip.text: !sourceHover.hovered ? ""
                                  : page.header.live ? i18n.trm("Live Source: " + page.header.source)
                                  : i18n.trm("File Source: " + page.header.source)
                    ToolTip.delay: theme.tipDelay
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
                    visible: backend.liveStatus !== ""
                    implicitHeight: Math.round(theme.em * 1.6)
                    implicitWidth: liveText.implicitWidth + theme.em * 1.1
                    radius: height / 2
                    color: theme.hover
                    Text {
                        id: liveText
                        anchors.centerIn: parent
                        text: backend.liveStatus
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                    }
                    HoverHandler { id: liveHover }
                    ToolTip.visible: liveHover.hovered && backend.liveTip !== ""
                    ToolTip.text: backend.liveTip
                    ToolTip.delay: theme.tipDelay
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
                    tip: i18n.tr("Laps of current session and every followed value of the game (Live tab): race length, pit stop times, tyres...")
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
        }

        // Calculator off: nothing read from the game, nothing shown
        Card {
            objectName: "calculatorOff"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !page.header.gameData
            EmptyState {
                anchors.centerIn: parent
                width: Math.min(parent.width - theme.em * 2, theme.em * 34)
                glyph: ""  // calculator
                title: i18n.tr("Race Calculator is off")
                text: i18n.tr("The game is not asked anything and the calculator shows nothing. Inputs, tyre plan & race plan are kept. Turn it on to plan a race.")
                actionText: i18n.tr("Turn On Race Calculator")
                onAction: backend.setGameData(true)
            }
        }

        // Calculator on: race setup, key figures, strategy timeline, tabs
        ColumnLayout {
            objectName: "calculatorContent"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.header.gameData
            spacing: theme.em * 0.6

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
                    model: page.tiles.length  // tiles kept when values change: color animations
                    RaceTile {
                        required property int index
                        readonly property var figure: page.tiles[index] || ({})
                        visible: figure.visible === true
                        title: figure.title || ""
                        value: figure.value !== undefined ? figure.value : "-"
                        detail: figure.detail || ""
                        tip: figure.tip || ""
                        warning: figure.warning === true
                        glyph: page.tileGlyph(figure.key)
                        tint: page.tileTint(figure.key)
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
                        { text: i18n.tr("Live"), glyph: "" },
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
                            radius: theme.radiusMd
                            color: tabButton.hovered && !tabButton.current ? theme.hover : "transparent"
                            Behavior on color { ColorAnimation { duration: theme.motionFast } }
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
                    // count read: itemAt alone is never evaluated again once tab buttons are made (null at start)
                    readonly property Item target: tabRepeater.count > page.header.tab ? tabRepeater.itemAt(page.header.tab) : null
                    x: target ? target.x : 0
                    width: target ? target.width : 0
                    height: 2
                    radius: 1
                    color: theme.accent
                    Behavior on x { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                    Behavior on width { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
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
                Loader {  // built when first shown (calculator on)
                    active: (page.header.tab === 2 && page.header.gameData) || item !== null
                    sourceComponent: RaceTeamTab {}
                }
                Loader {  // built when first shown (calculator on)
                    active: (page.header.tab === 3 && page.header.gameData) || item !== null
                    sourceComponent: RaceLiveTab {}
                }
            }
        }
    }
}
