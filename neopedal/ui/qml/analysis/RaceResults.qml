import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Results & replays page: on the left, sessions written by the game (results files) or replays saved by the game
// (LMU); on the right, session picked: header, key figures of player, then classification, positions lap by lap
// (races), laps of a car, session events, and the replay tab (game replay or live session: playback, camera,
// incidents, standings, map). Session with a replay: watch it, or an event or a lap of it, in the game.
// Replay picked: results of its session shown. F5: read files & ask game again.
// The replay tab shows under a session only when the game saved its replay, and plays only that replay there
// (another replay or the live session: a button opens the session's replay instead). The replays list always
// has the player (game replay or live session).
TpPage {
    id: page

    readonly property bool wide: width > theme.bpWide
    readonly property var header: backend.sessionHeader
    readonly property int replayTab: 4
    // Tabs shown (backend: 0 classification, 1 positions, 2 laps, 3 events, 4 replay): positions for races, replay
    // for a session with its replay or in the replays list; tab shown (-1: no session, why shown instead)
    readonly property var tabNames: [i18n.tr("Classification"), i18n.tr("Positions"), i18n.tr("Laps"),
                                     i18n.tr("Events"), i18n.tr("Replay")]
    readonly property var tabKeys: backend.tabKeys
    readonly property var tabTexts: tabKeys.map(function(key) { return page.tabNames[key] })
    readonly property int tab: backend.shownTab
    // Replay saved by the game for the session shown, and whether the game plays it (opened from this page)
    readonly property string sessionReplay: header.replay || ""
    readonly property bool sessionReplayOpen: sessionReplay !== "" && replays.playingReplay === sessionReplay
    readonly property bool sessionReplayOpening: sessionReplay !== "" && replays.openingReplay === sessionReplay
    // Player shown: replays list (game replay or live session), or the session's own replay playing
    readonly property bool playerShown: backend.listMode === 1 || sessionReplayOpen
    // Replays list: the game plays another replay (or the live session) than the one picked: told above the player
    readonly property bool otherReplayShown: backend.listMode === 1 && replays.inSession && replays.selectedReplay !== ""
        && replays.playingReplay !== replays.selectedReplay && replays.openingReplay !== replays.selectedReplay

    function toneColor(tone) {
        return tone === "" || tone === "text" ? theme.text : theme.tone(tone)
    }

    GridLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        columns: page.wide ? 2 : 1
        columnSpacing: theme.space4
        rowSpacing: theme.space4

        // Sessions of results files, or replays saved by the game
        Card {
            Layout.fillHeight: page.wide
            Layout.fillWidth: !page.wide
            Layout.preferredWidth: page.wide ? Math.min(Math.max(page.width * 0.3, theme.em * 24), theme.em * 34) : -1
            Layout.preferredHeight: page.wide ? -1 : page.height * 0.34
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                TpSegmented {
                    objectName: "listMode"
                    name: i18n.tr("List")
                    Layout.topMargin: theme.padCard
                    Layout.leftMargin: theme.padCard
                    Layout.rightMargin: theme.padCard
                    options: [i18n.tr("Sessions") + (backend.sessionCount > 0 ? "  " + backend.sessionCount : ""),
                              i18n.tr("Replays") + (replays.replayCount > 0 ? "  " + replays.replayCount : "")]
                    currentIndex: backend.listMode
                    onActivated: function(index) { backend.setListMode(index) }
                }
                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: backend.listMode
                    ResultsSessionList { id: sessionList }
                    Loader {  // built when first shown, then kept
                        active: backend.listMode === 1 || item !== null
                        sourceComponent: ReplayList {}
                    }
                }
            }
        }

        // Session picked (or why there is none), or replay of game
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                spacing: theme.space4
                visible: backend.hasSession || page.tab === page.replayTab

                // Header: kind, track, date, settings
                RowLayout {
                    Layout.fillWidth: true
                    visible: backend.hasSession
                    spacing: theme.em * 0.7
                    ResultsBadge {
                        code: page.header.code || ""
                        implicitWidth: Math.round(theme.em * 2.6)
                    }
                    GameLogo {  // circuit logo of game
                        source: page.header.trackLogo || ""
                        boxWidth: theme.em * 3.4
                        boxHeight: theme.em * 2.3
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.5
                            Text {
                                Layout.fillWidth: true
                                Layout.maximumWidth: implicitWidth
                                text: page.header.title || ""
                                textFormat: Text.PlainText
                                color: theme.text
                                font.weight: Font.DemiBold
                                font.pointSize: theme.fontHeading
                                elide: Text.ElideRight
                                Accessible.role: Accessible.Heading
                                Accessible.name: text
                            }
                            Text {
                                text: page.header.kindText || ""
                                textFormat: Text.PlainText
                                color: theme.dimText
                                font.weight: Font.DemiBold
                            }
                            Pill {  // race left before its end: classification of that moment
                                visible: page.header.partial === true
                                text: i18n.tr("Unfinished")
                                glyph: ""  // warning
                                tint: theme.warning
                                tip: i18n.tr("No car had finished when this file was written (race left before its end): classification and gaps of that moment.")
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: page.header.when || ""
                                textFormat: Text.PlainText
                                color: theme.dimText
                                font.features: { "tnum": 1 }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: [page.header.subtitle || "", page.header.details || ""]
                                  .filter(function(part) { return part !== "" }).join(" · ")
                            textFormat: Text.PlainText
                            color: theme.dimText
                            font.pointSize: theme.fontLabel
                            elide: Text.ElideRight
                            ToolTip.visible: headerArea.containsMouse
                            ToolTip.text: (page.header.file || "") + (page.header.game ? "  (" + page.header.game + ")" : "")
                            ToolTip.delay: theme.tipDelay
                            MouseArea { id: headerArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                    TpToolbar {  // track stats, replay saved by game for this session (LMU): texts while they fit
                        objectName: "sessionToolbar"
                        Layout.fillWidth: true
                        Layout.maximumWidth: implicitWidth
                        TpAction {
                            name: "trackStatsButton"
                            text: i18n.tr("Track Stats")
                            glyph: ""  // chart
                            fallback: "≡"
                            tip: i18n.tr("Driver stats of this track, your car of this session picked")
                            priority: 1
                            onTriggered: backend.openTrackStats()
                        }
                        TpAction {
                            name: "watchReplayButton"
                            shown: page.sessionReplay !== ""
                            accent: true
                            pinned: true
                            priority: 2
                            text: i18n.tr("Watch Replay")
                            glyph: ""  // play
                            fallback: "▶"
                            tip: i18n.tr("Open the replay of this session in the game") + "\n" + page.sessionReplay
                            onTriggered: backend.watchReplay()
                        }
                    }
                    GamePicture {  // circuit picture of game
                        visible: page.wide  // narrow page: room for the title
                        source: page.header.trackPicture || ""
                        boxHeight: theme.em * 3.0
                    }
                }

                // Key figures of player (winner & fastest lap if player not in session)
                Flow {
                    Layout.fillWidth: true
                    visible: backend.hasSession && page.tab !== page.replayTab
                    spacing: theme.space3
                    Repeater {
                        model: backend.summaryTiles
                        TpStatTile {
                            required property var modelData
                            readonly property bool toned: modelData.tone !== "" && modelData.tone !== "dim"
                            width: theme.em * 10
                            title: modelData.label
                            value: modelData.value
                            detail: modelData.detail || ""
                            tint: toned ? page.toneColor(modelData.tone) : theme.border
                            valueColor: modelData.tone !== "" ? page.toneColor(modelData.tone) : null
                        }
                    }
                }

                // Comments on player's session: pace in class, lap 1, lap time trend of stints
                ResultsComments {
                    Layout.fillWidth: true
                    visible: backend.hasSession && page.tab !== page.replayTab && backend.sessionComments.length > 0
                }

                // Tabs & car classes
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.space4
                    TpSegmented {
                        objectName: "resultTabs"
                        name: i18n.tr("Results")
                        options: page.tabTexts
                        currentIndex: page.tabKeys.indexOf(page.tab)
                        maxWidth: page.wide ? page.width * 0.45 : page.width * 0.7
                        onActivated: function(index) { backend.setTab(page.tabKeys[index]) }
                    }
                    Flickable {  // class filter chips: Tab reaches each, Space / Enter picks
                        Layout.fillWidth: true
                        visible: page.tab !== page.replayTab
                        implicitHeight: classRow.implicitHeight
                        contentWidth: classRow.implicitWidth
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        interactive: contentWidth > width
                        Row {
                            id: classRow
                            spacing: theme.space3
                            Repeater {
                                model: backend.classChips.length > 0
                                       ? [{ "name": "", "color": "", "count": 0 }].concat(backend.classChips) : []
                                TpChip {
                                    required property var modelData
                                    text: modelData.name !== "" ? modelData.name : i18n.tr("All Classes")
                                    count: modelData.count > 0 ? modelData.count : -1
                                    showDot: modelData.name !== ""
                                    dotColor: modelData.color || "transparent"
                                    selected: backend.classFilter === modelData.name
                                    onClicked: backend.setClassFilter(modelData.name)
                                }
                            }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    StackLayout {
                        anchors.fill: parent
                        anchors.margins: 1
                        currentIndex: page.tab
                        // Tabs built when first shown, then kept
                        Loader {
                            active: page.tab === 0 || item !== null
                            sourceComponent: ResultsTable {
                                onLapsWanted: function(key) {
                                    backend.selectEntry(key)
                                    backend.setTab(2)
                                }
                            }
                        }
                        Loader {
                            active: page.tab === 1 || item !== null
                            sourceComponent: ResultsPositions { active: page.tab === 1 && backend.isRace }
                        }
                        Loader {
                            active: page.tab === 2 || item !== null
                            sourceComponent: ResultsLaps {}
                        }
                        Loader {
                            active: page.tab === 3 || item !== null
                            sourceComponent: ResultsEvents {}
                        }
                        Item {  // replay tab: player of the session's own replay, of the game in the replays list
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                visible: page.playerShown
                                TpNotice {  // replays list: replay picked not opened from the page (game tells no replay name)
                                    objectName: "otherReplayNotice"
                                    Layout.margins: theme.padCard
                                    Layout.bottomMargin: 0
                                    visible: page.otherReplayShown
                                    tone: theme.accent
                                    glyph: ""  // info
                                    fallback: "i"
                                    text: i18n.tr("The replay picked was not opened from this page: the player shows what the game has open.")
                                    actionText: i18n.tr("Watch Replay")
                                    onAction: replays.watchReplay(replays.selectedReplay)
                                }
                                Loader {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    active: (page.tab === page.replayTab && page.playerShown) || item !== null
                                    sourceComponent: ReplayView {}
                                }
                            }
                            // Session's replay not playing: opened from here, never another replay under the session
                            TpStateView {
                                objectName: "sessionReplayState"
                                anchors.centerIn: parent
                                loading: !page.playerShown && page.sessionReplayOpening
                                empty: !page.playerShown
                                loadingText: i18n.tr("Opening the replay in the game…")
                                glyph: ""  // play
                                title: i18n.tr("Replay of this session")
                                text: replays.gameState === "offline"
                                      ? i18n.tr("Start LMU to watch the replay of this session.")
                                      : i18n.tr("Open it in the game to control playback, cameras and incidents from here.")
                                actionText: replays.gameState === "offline" ? "" : i18n.tr("Watch Replay")
                                onAction: backend.watchReplay()
                            }
                        }
                    }
                }
            }

            // Nothing to show: reading, no results found, file picked unreadable, or no session matching filters
            TpStateView {
                id: sessionState
                objectName: "sessionState"
                // Session picked (row kept selected) whose file could not be read
                readonly property bool failed: backend.failedFile !== "" && backend.shownCount > 0
                readonly property bool noMatch: !failed && backend.folderText !== "" && backend.sessionCount > 0
                readonly property bool noFolder: backend.loaded && backend.folderText === ""
                anchors.centerIn: parent
                loading: !backend.hasSession && page.tab !== page.replayTab && backend.busy && !backend.loaded
                empty: !backend.hasSession && page.tab !== page.replayTab
                loadingText: i18n.tr("Reading results files…")
                glyph: failed ? "" : ""  // warning, flag
                title: failed ? i18n.tr("This results file can't be read")
                     : backend.folderText === "" ? i18n.tr("No results folder found")
                     : backend.sessionCount === 0 ? i18n.tr("No session results yet")
                     : i18n.tr("No session matches the filters")
                text: failed
                      ? backend.failedFile + "\n" + i18n.tr("The file may be damaged, still being written by the game, or not a results file. Pick the session again to read it again.")
                      : !backend.loaded || backend.sessionCount > 0 ? ""
                      : backend.folderText === ""
                      ? i18n.tr("Results are written by Le Mans Ultimate (or rFactor 2) in UserData/Log/Results at the end of each session. Choose that folder if the game is not installed with Steam.")
                      : i18n.tr("The game writes a results file at the end of each session (practice, qualifying, race).")
                actionText: noFolder ? i18n.tr("Choose Folder…") : backend.loaded && noMatch ? i18n.tr("Clear Filters") : ""
                onAction: {
                    if (noFolder) {
                        backend.chooseFolder()
                        return
                    }
                    sessionList.clearSearch()
                    backend.clearFilters()
                }
            }
        }
    }

    // Replay files dropped on page: copied to replay folder of game
    TpDropZone {
        id: dropArea
        anchors.fill: parent
        text: i18n.tr("Drop replays (.Vcr) to add them to the game")
        onFilesDropped: function(urls) { replays.addFiles(urls) }
    }

    // Dialogs & toasts asked by the backends (replay file operations, refused game commands, lap not recorded)
    TpDialogHost {}
}
