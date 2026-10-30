import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator page: data source (file or game session) & race plan actions, race setup, key figures &
// strategy timeline (shared by all tabs), then Fuel (inputs, pit stop plan, scenarios, consumption history), Tyres
// (tyre wear & rules, tyre plan, stock), Team (stints of the team car from the game) and Live (every input value
// the game gives & which ones inputs follow, race under way, tyres offered) tabs. First use: 3 questions first.
// Inputs are applied on Enter or leaving a field, Up / Down step them, Ctrl+Z / Ctrl+Y undo & redo.
TpPage {
    id: page

    readonly property var inputs: backend.inputs
    readonly property var specs: backend.specs
    readonly property var header: backend.header
    readonly property var calc: backend.calc
    readonly property var tiles: backend.tiles
    readonly property bool compact: width < theme.bpWide  // tiles on two rows, no circuit logo, no race status
    readonly property bool hasRecentFiles: (backend.recentFiles.history || []).length > 0
    readonly property color tyreColor: theme.seriesTyre

    // File names & sources shown in rich text: never read as markup
    function esc(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }
    // Source "File" chosen: files loaded before in a menu under the control, else the file dialog
    function chooseFile(source) {
        if (page.hasRecentFiles)
            loadFileMenu.toggleBelow(source)
        else
            backend.loadFile()
    }
    function chooseSource(index, source) {
        if (index === 1)
            backend.loadLive()  // also when already the source: laps & followed values filled in again
        else
            page.chooseFile(source)
    }

    function tileGlyph(key) {
        return { fuel: "", energy: "", pits: "", stint: "", refill: "",
                 tyres: "" }[key] || ""
    }
    function tileTint(key) {
        return { fuel: theme.seriesFuel, energy: theme.seriesEnergy, pits: theme.accent, stint: theme.seriesStint, refill: theme.seriesRefill,
                 tyres: page.tyreColor }[key] || theme.accent
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Data source (file or game session) & what it is, race status, then undo & redo, race plan, reset and
        // calculator on / off (toolbar: texts, then icons, then a "..." menu as room runs out)
        RowLayout {
            id: headerRow
            objectName: "headerRow"
            Layout.fillWidth: true
            spacing: theme.space4

            GameLogo {  // circuit logo of game (no room taken while there is none)
                id: trackLogo
                visible: shown && page.header.gameData && !page.compact
                source: page.header.trackLogo || ""
                boxWidth: theme.em * 3.0
                boxHeight: theme.em * 1.8
            }
            TpSegmented {
                id: sourceControl
                objectName: "sourceControl"
                visible: page.header.gameData
                name: i18n.tr("Data Source")
                options: [i18n.tr("File"), i18n.tr("Game Session")]
                currentIndex: page.header.live ? 1 : 0
                onActivated: function(index) { page.chooseSource(index, sourceControl) }
                HoverHandler { id: sourceControlHover }
                ToolTip.visible: sourceControlHover.hovered
                ToolTip.text: i18n.tr("File: laps of a consumption history file. Game Session: laps of the session driven, inputs filled in from them and from the game (Live tab: values followed, Follow Live). Choose it again to fill in again.")
                ToolTip.delay: theme.tipDelay
            }
            RowLayout {  // what the source is: track & class of the session (pulsing dot), or file name
                id: sourceInfo
                objectName: "sourceInfo"
                visible: page.header.gameData
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 4
                Layout.preferredWidth: theme.em * 4  // grows with the room left, never squeezes the actions
                Layout.maximumWidth: sourceDot.width + sourceText.implicitWidth + spacing
                spacing: theme.space3
                Accessible.role: Accessible.StaticText
                Accessible.name: sourceText.text
                TpPulseDot {
                    id: sourceDot
                    visible: page.header.live
                    width: Math.round(theme.em * 0.55)
                    color: theme.live
                    pulsing: page.header.live && page.header.gameData  // no animation while hidden (off)
                }
                Text {
                    id: sourceText
                    Layout.fillWidth: true
                    text: page.header.source
                    textFormat: Text.PlainText
                    color: theme.text
                    elide: Text.ElideRight
                    HoverHandler { id: sourceHover }
                    ToolTip.visible: sourceHover.hovered
                    ToolTip.text: !sourceHover.hovered ? ""
                                  : page.header.live ? i18n.trm("Live Source: " + page.header.source)
                                  : i18n.trm("File Source: " + page.header.source)
                    ToolTip.delay: theme.tipDelay
                }
            }
            Pill {  // live race status: plan of the rest of the race (values read in its tooltip)
                objectName: "liveRaceStatus"
                visible: page.header.gameData && backend.liveStatus !== "" && !page.compact
                text: backend.liveStatus
                tint: theme.live
                dot: true
                maximumTextWidth: theme.em * 12
                tip: backend.liveTip
            }
            TpToolbar {
                id: toolbar
                objectName: "headerToolbar"
                Layout.fillWidth: true
                onMenuClosed: page.forceActiveFocus()
                TpAction {
                    name: "undoButton"
                    shown: page.header.gameData
                    glyph: theme.glyphs.undo
                    fallback: "↶"
                    tip: i18n.tr("Undo (Ctrl+Z)")
                    flat: true
                    priority: 1
                    enabled: backend.canUndo
                    onTriggered: backend.undo()
                }
                TpAction {
                    name: "redoButton"
                    shown: page.header.gameData
                    glyph: ""  // redo
                    fallback: "↷"
                    tip: i18n.tr("Redo (Ctrl+Y)")
                    flat: true
                    enabled: backend.canRedo
                    onTriggered: backend.redo()
                }
                TpAction {
                    name: "planButton"
                    shown: page.header.gameData
                    text: i18n.tr("Race Plan")
                    glyph: ""  // document
                    fallback: i18n.tr("Race Plan")
                    tip: i18n.tr("Race setup, fuel & tyre plan in one file, to keep or share")
                    priority: 3
                    checked: planMenu.visible
                    onTriggered: function(source) { planMenu.toggleBelow(source) }
                }
                TpAction {
                    name: "resetButton"
                    shown: page.header.gameData
                    text: i18n.tr("Reset to Zero")
                    glyph: theme.glyphs.reset
                    fallback: i18n.tr("Reset to Zero")
                    // Done at once, Undo in the toast (and Ctrl+Z)
                    tip: i18n.tr("Reset to Zero") + ": " + i18n.tr("Clear every input")
                    priority: 2
                    onTriggered: backend.resetValues()
                }
                TpAction {  // calculator on / off: never in the "..." menu, its text kept longest
                    name: "gameDataSwitch"
                    text: page.header.gameData ? i18n.tr("Enabled") : i18n.tr("Disabled")
                    glyph: ""  // power
                    fallback: page.header.gameData ? i18n.tr("Enabled") : i18n.tr("Disabled")
                    tip: i18n.tr("Race Calculator on or off")
                    checkable: true
                    checked: page.header.gameData
                    pinned: true
                    priority: 4
                    onTriggered: backend.setGameData(!page.header.gameData)
                }
            }
        }
        // Menus of the header (outside the toolbar: shown under the button or "..." button they come from)
        TpMenu {
            id: planMenu
            objectName: "planMenu"
            onClosed: page.forceActiveFocus()
            TpMenuItem { text: i18n.tr("Open Race Plan…"); onTriggered: backend.openRacePlan() }
            RaceRecentMenu { kind: "race_plan" }
            TpMenuItem { text: i18n.tr("Save Race Plan As…"); onTriggered: backend.saveRacePlan() }
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
        // Source "File": files loaded before, then the file dialog
        RaceRecentMenu {
            id: loadFileMenu
            objectName: "loadFileMenu"
            kind: "history"
            first: 2
            onClosed: page.forceActiveFocus()
            TpMenuItem { text: i18n.tr("Load File") + "…"; onTriggered: backend.loadFile() }
            MenuSeparator {}
        }

        // Race of the game under way, plan not made from now: planning the rest of the race proposed (never forced)
        RowLayout {
            objectName: "liveRaceProposal"
            Layout.fillWidth: true
            visible: page.header.gameData && backend.raceProposal
            spacing: theme.space2
            TpNotice {
                tone: theme.live
                glyph: ""  // flag
                fallback: "⚑"
                text: i18n.tr("A race is running: plan the rest of the race from now (laps & time done, fuel, energy & tyres of the car, stops done)?")
                actionText: i18n.tr("Plan From Now")
                onAction: backend.setLiveRace(true)
            }
            TpButton {
                flat: true
                glyph: theme.glyphs.close
                fallback: "×"
                tip: i18n.tr("Not Now")
                onClicked: backend.dismissLiveRace()
                Accessible.name: i18n.tr("Not Now")
            }
        }

        // Calculator off: nothing read from the game, nothing shown
        Card {
            objectName: "calculatorOff"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !page.header.gameData
            TpStateView {
                anchors.centerIn: parent
                width: Math.min(parent.width - theme.em * 2, theme.em * 34)
                empty: true
                glyph: ""  // calculator
                title: i18n.tr("Race Calculator is off")
                text: i18n.tr("The game is not asked anything and the calculator shows nothing. Inputs, tyre plan & race plan are kept. Turn it on to plan a race.")
                actionText: i18n.tr("Turn On Race Calculator")
                onAction: backend.setGameData(true)
            }
        }

        // First use: race length, pit stop time & data source asked, then the whole page
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.header.gameData && page.header.quickSetup === true
            RaceQuickSetup {
                anchors.horizontalCenter: parent.horizontalCenter
                y: Math.max(0, (parent.height - height) / 3)
                width: Math.min(parent.width, theme.em * 40)
                store: page
            }
        }

        // Calculator on: race setup, key figures, strategy timeline, tabs
        ColumnLayout {
            objectName: "calculatorContent"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.header.gameData && page.header.quickSetup !== true
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
    TpDropZone {
        id: dropArea
        objectName: "raceDropArea"
        anchors.fill: parent
        enabled: page.header.gameData
        text: i18n.tr("Drop consumption history, race plan or tyre plan files to open them")
        accepts: function(urls) { return backend.canDrop(urls) }
        onFilesDropped: function(urls) { backend.dropFiles(urls) }  // warnings shown once the drop is over
    }

    // Dialogs & toasts asked by the backend (file errors, confirmations, toasts)
    TpDialogHost {}
}
