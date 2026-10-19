import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

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
    readonly property bool compact: width < theme.bpWide  // icon buttons, tiles on two rows
    // Header: button labels (0), icon buttons (1), switches without labels & no circuit logo (2), chosen from
    // header width at current level & label widths of hidden probes: fits in any language, no binding loop
    property int headerLevel: 0
    readonly property color tyreColor: theme.seriesTyre

    onWidthChanged: updateHeaderLevel()
    Component.onCompleted: updateHeaderLevel()

    function updateHeaderLevel() {
        const slack = Math.max(0, sourceChip.implicitWidth - theme.em * 8)  // source chip elided down to 8 em
        const full = headerRow.implicitWidth - slack + (headerLevel >= 1 ? labelProbes.buttons : 0)
                     + (headerLevel >= 2 ? labelProbes.switches : 0)
        const room = width - theme.padPage * 2  // page margins
        const level = !compact && full <= room ? 0 : full - labelProbes.buttons <= room ? 1 : 2
        if (level !== headerLevel)
            headerLevel = level
    }
    // File names & sources shown in rich text: never read as markup
    function esc(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }

    function tileGlyph(key) {
        return { fuel: "", energy: "", pits: "", stint: "", refill: "", tyres: "" }[key] || ""
    }
    function tileTint(key) {
        return { fuel: theme.seriesFuel, energy: theme.seriesEnergy, pits: theme.accent, stint: theme.seriesStint, refill: theme.seriesRefill,
                 tyres: page.tyreColor }[key] || theme.accent
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Calculator on / off, then while on: data source, live, undo & redo, race plan & data actions
        RowLayout {
            id: headerRow
            objectName: "headerRow"
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            onImplicitWidthChanged: page.updateHeaderLevel()

            RaceSwitch {
                objectName: "gameDataSwitch"
                Layout.fillWidth: false
                wrap: false
                // Narrow page: label only while off (state easy to miss from the switch alone)
                text: page.headerLevel >= 1 && page.header.gameData ? "" : page.header.gameData ? i18n.tr("Enabled") : i18n.tr("Disabled")
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
                GameLogo {  // circuit logo of game (no room taken while there is none)
                    id: trackLogo
                    visible: shown && page.headerLevel < 2
                    source: page.header.trackLogo || ""
                    boxWidth: theme.em * 3.0
                    boxHeight: theme.em * 1.8
                }
                Rectangle {  // source chip: live (pulsing dot) or file
                    id: sourceChip
                    readonly property color tone: page.header.live ? theme.live : theme.accent
                    implicitHeight: Math.round(theme.em * 2)
                    implicitWidth: Math.min(sourceDot.width + sourceText.implicitWidth + theme.em * 1.6, theme.em * 24)
                    Layout.minimumWidth: theme.em * 5
                    Layout.maximumWidth: theme.em * 24
                    Layout.fillWidth: false
                    radius: height / 2
                    color: theme.tint(tone, "subtle")
                    border.width: 1
                    border.color: theme.tint(tone, 0.5)
                    Accessible.role: Accessible.StaticText
                    Accessible.name: (page.header.live ? i18n.tr("Live") : i18n.tr("File")) + " · " + page.header.source
                    TpPulseDot {
                        id: sourceDot
                        x: theme.em * 0.6
                        width: Math.round(theme.em * 0.55)
                        color: sourceChip.tone
                        anchors.verticalCenter: parent.verticalCenter
                        pulsing: page.header.live && page.header.gameData  // no animation while hidden (off)
                        pulseDuration: 900
                    }
                    Text {
                        id: sourceText
                        x: sourceDot.x + sourceDot.width + theme.space3
                        width: parent.width - x - theme.em * 0.6
                        anchors.verticalCenter: parent.verticalCenter
                        text: "<b>" + (page.header.live ? i18n.tr("Live") : i18n.tr("File")) + "</b> · " + page.esc(page.header.source)
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
                    wrap: false
                    text: page.headerLevel >= 2 ? "" : i18n.tr("Follow Live")
                    tip: i18n.tr("Inputs follow each new lap of the live session")
                    Accessible.name: i18n.tr("Follow Live")
                    on: page.header.followLive
                    onSwitched: function(on) { backend.setFollowLive(on) }
                }
                RaceSwitch {
                    Layout.fillWidth: false
                    wrap: false
                    text: page.headerLevel >= 2 ? "" : i18n.tr("Live Race")
                    Accessible.name: i18n.tr("Live Race")
                    tip: i18n.tr("During a race: plan of the rest of the race from now (laps & time done, fuel, energy & tyres of the car, stops done)")
                    on: page.header.liveRace
                    onSwitched: function(on) { backend.setLiveRace(on) }
                }
                Pill {  // live race status
                    visible: backend.liveStatus !== ""
                    text: backend.liveStatus
                    tint: theme.dimText
                    maximumTextWidth: theme.em * 12
                    tip: backend.liveTip
                }
                Item { Layout.fillWidth: true }
                TpButton {
                    flat: true
                    glyph: ""  // undo
                    fallback: "↶"
                    tip: i18n.tr("Undo (Ctrl+Z)")
                    enabled: backend.canUndo
                    onClicked: backend.undo()
                    Accessible.name: i18n.tr("Undo")
                }
                TpButton {
                    flat: true
                    glyph: ""  // redo
                    fallback: "↷"
                    tip: i18n.tr("Redo (Ctrl+Y)")
                    enabled: backend.canRedo
                    onClicked: backend.redo()
                    Accessible.name: i18n.tr("Redo")
                }
                TpButton {
                    id: planButton
                    glyph: ""  // document
                    fallback: i18n.tr("Race Plan")
                    text: page.headerLevel >= 1 ? "" : i18n.tr("Race Plan")
                    tip: i18n.tr("Race setup, fuel & tyre plan in one file, to keep or share")
                    checked: planMenu.visible
                    onClicked: planMenu.popup(planButton, 0, planButton.height + 4)
                    Accessible.name: i18n.tr("Race Plan")
                    TpMenu {
                        id: planMenu
                        TpMenuItem { text: i18n.tr("Open Race Plan..."); onTriggered: backend.openRacePlan() }
                        RaceRecentMenu { kind: "race_plan" }
                        TpMenuItem { text: i18n.tr("Save Race Plan As..."); onTriggered: backend.saveRacePlan() }
                        MenuSeparator {}
                        TpMenuItem {
                            text: i18n.tr("Save for Current Car & Track")
                            enabled: page.header.combo !== ""
                            onTriggered: backend.saveComboPlan()
                        }
                        TpMenuItem {
                            text: i18n.tr("Open Plan of Car & Track Automatically")
                            checkable: true
                            checked: page.header.autoCombo
                            onTriggered: backend.setAutoComboPlan(checked)
                        }
                    }
                }
                TpButton {
                    id: loadLiveButton
                    glyph: ""  // refresh
                    fallback: i18n.tr("Load Live")
                    text: page.headerLevel >= 1 ? "" : i18n.tr("Load Live")
                    tip: i18n.tr("Laps of current session and every followed value of the game (Live tab): race length, pit stop times, tyres...")
                    onClicked: backend.loadLive()
                    Accessible.name: i18n.tr("Load Live")
                }
                TpButton {
                    id: loadFileButton
                    readonly property bool hasRecent: (backend.recentFiles.history || []).length > 0
                    glyph: ""  // folder open
                    fallback: i18n.tr("Load File")
                    text: page.headerLevel >= 1 ? "" : i18n.tr("Load File")
                    tip: i18n.tr("Consumption history file")
                    checked: loadFileMenu.visible
                    // Files loaded before: menu of the button (no room in the row for a drop-down of its own)
                    onClicked: hasRecent ? loadFileMenu.popup(loadFileButton, 0, loadFileButton.height + 4) : backend.loadFile()
                    Accessible.name: i18n.tr("Load File")
                    RaceRecentMenu {
                        id: loadFileMenu
                        objectName: "loadFileMenu"
                        kind: "history"
                        first: 2
                        TpMenuItem { text: i18n.tr("Load File") + "..."; onTriggered: backend.loadFile() }
                        MenuSeparator {}
                    }
                }
                TpButton {
                    id: resetButton
                    glyph: ""  // clear
                    fallback: i18n.tr("Reset to Zero")
                    text: page.headerLevel >= 1 ? "" : i18n.tr("Reset to Zero")
                    // Done at once, Undo in the toast (and Ctrl+Z)
                    tip: i18n.tr("Reset to Zero") + ": " + i18n.tr("Clear every input")
                    onClicked: backend.resetValues()
                    Accessible.name: i18n.tr("Reset to Zero")
                }
            }
        }

        Item {  // hidden probes: extra width of header labels in current language (see updateHeaderLevel)
            id: labelProbes
            visible: false
            readonly property real buttons: probePlan.implicitWidth + probeLive.implicitWidth + probeFile.implicitWidth
                                            + probeReset.implicitWidth - 4 * probeIcon.implicitWidth
                                            + (page.header.gameData ? probeEnabled.implicitWidth - probeBare.implicitWidth : 0)
            readonly property real switches: probeFollow.implicitWidth + probeLiveRace.implicitWidth
                                             - 2 * probeBare.implicitWidth
                                             + (trackLogo.shown ? trackLogo.fitWidth + theme.em * 0.5 : 0)  // + circuit logo & spacing
            onButtonsChanged: page.updateHeaderLevel()
            onSwitchesChanged: page.updateHeaderLevel()
            TpButton { id: probeIcon; glyph: planButton.glyph; fallback: planButton.fallback }
            TpButton { id: probePlan; glyph: planButton.glyph; text: i18n.tr("Race Plan") }
            TpButton { id: probeLive; glyph: loadLiveButton.glyph; text: i18n.tr("Load Live") }
            TpButton { id: probeFile; glyph: loadFileButton.glyph; text: i18n.tr("Load File") }
            TpButton { id: probeReset; glyph: resetButton.glyph; text: i18n.tr("Reset to Zero") }
            RaceSwitch { id: probeBare; wrap: false }
            RaceSwitch { id: probeEnabled; wrap: false; text: i18n.tr("Enabled") }
            RaceSwitch { id: probeFollow; wrap: false; text: i18n.tr("Follow Live") }
            RaceSwitch { id: probeLiveRace; wrap: false; text: i18n.tr("Live Race") }
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
            spacing: theme.space4

            // Race setup: race type & length, formation, pit stop time, safety margin
            RaceSetup {
                Layout.fillWidth: true
                store: page
            }

            // Key figures
            GridLayout {
                Layout.fillWidth: true
                columns: page.compact ? 3 : 6
                columnSpacing: theme.space4
                rowSpacing: theme.space4
                Repeater {
                    model: page.tiles.length  // tiles kept when values change: color animations
                    TpStatTile {
                        required property int index
                        readonly property var figure: page.tiles[index] || ({})
                        visible: figure.visible === true
                        title: figure.title || ""
                        value: figure.value !== undefined ? figure.value : "-"
                        detail: figure.detail || ""
                        tip: figure.tip || ""
                        warning: figure.warning === true  // out of range: loss color & warning icon
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

            // Tabs: Tab reaches them, Left / Right choose
            TpTabBar {
                objectName: "raceTabs"
                name: i18n.tr("Race Calculator")
                model: [
                    { text: i18n.tr("Fuel"), glyph: "" },
                    { text: i18n.tr("Tyres"), glyph: "" },
                    { text: i18n.tr("Team"), glyph: "" },
                    { text: i18n.tr("Live"), glyph: "" },
                ]
                currentIndex: page.header.tab
                onActivated: function(index) { backend.setTab(index) }
                TpButton {
                    visible: page.header.tab === 0
                    flat: true
                    size: "sm"
                    checked: page.header.showHistory
                    glyph: ""  // history
                    fallback: i18n.tr("History")
                    text: page.compact ? "" : i18n.tr("History")
                    tip: page.header.showHistory ? i18n.tr("Hide History") : i18n.tr("Show History")
                    onClicked: backend.setShowHistory(!page.header.showHistory)
                    Accessible.name: tip
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

    // Consumption history, race plan & tyre plan files dropped on page: opened like their Open action
    DropArea {
        id: dropArea
        objectName: "raceDropArea"
        anchors.fill: parent
        enabled: page.header.gameData
        onEntered: function(drag) { drag.accepted = drag.hasUrls && backend.canDrop(drag.urls) }
        onDropped: function(drop) {
            if (!drop.hasUrls) return
            drop.acceptProposedAction()
            var urls = drop.urls
            Qt.callLater(function() { backend.dropFiles(urls) })  // warnings shown once the drop is over
        }
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: theme.space3
        visible: dropArea.containsDrag
        radius: theme.radiusXl
        color: theme.tint(theme.accent, "subtle")
        border.width: 2
        border.color: theme.accent
        Column {
            anchors.centerIn: parent
            width: parent.width - theme.em * 2
            spacing: theme.space4
            Icon { anchors.horizontalCenter: parent.horizontalCenter; glyph: ""; size: theme.em * 3; color: theme.accent }  // download
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: i18n.tr("Drop consumption history, race plan or tyre plan files to open them")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontHeading
            }
        }
    }
}
