import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"
import "../telemetry"

// Driver stats viewer page: track picker as title (vehicles, sessions, last driven), actions, key figures, tabs
// (Overview, Progression, Compare), table of vehicles (tracks for All Tracks) in every tab with the cards of the
// tab beside it (three at most; below the table on narrow pages).
// Track: Overview = lap time goal, stints & consistency; Progression = chart & sessions of selected vehicle
// below the table; Compare = lap time reference (level scale), friend & personal best codes.
// All Tracks: Overview = driver, progress of the week, official races to come; Progression = daily driving
// activity below the table, recent sessions; Compare = levels of all tracks, rivals, friend & codes.
// Cards are in Stats*Card.qml files; menus of the page stay here (toolbar actions, rows, official races & rivals).
// Keys: F5 reload, "/" find track, Alt+Left or Backspace (table) All Tracks, Delete (table) remove row.
TpPage {
    id: page

    readonly property var stints: backend.stints
    readonly property var info: backend.trackInfo
    readonly property var tiles: backend.tiles
    readonly property var goal: backend.goal  // lap time goal of selected vehicle
    // Selected vehicle has a personal best: shared as picture or code
    readonly property bool canShare: !allTracks && goal.visible === true && (goal.best || "—") !== "—"
    readonly property bool allTracks: backend.allTracks
    readonly property int tab: backend.statsTab  // 0 overview, 1 progression, 2 compare
    readonly property bool compact: width < theme.bpWide  // menu buttons as icons, 3 key figures a row
    readonly property bool narrow: width < theme.bpNarrow  // side cards below the table
    // Cards beside the table in this tab (none: the table & what goes below it take the whole width)
    readonly property bool sideShown: tab === 2
        || (tab === 0 && (allTracks || goal.visible === true || stints.visible === true))
        || (tab === 1 && allTracks && backend.recent.length > 0)
    // Progression tab of a track: table on top (every row when it fits), progression card below
    readonly property bool tableCompact: tab === 1 && !allTracks && backend.hasRows
    property var menuActions: []
    property string menuKey: ""
    property string menuColumn: ""
    property var comboEntries: []  // menu of an official race or a rival: entries & their track, vehicle, results
    property var comboTarget: ({ "track": "", "vehicle": "", "path": "" })

    function tone(name, fallback) { return name === "loss" || name === "gain" ? theme.tone(name) : fallback }
    function openRowMenu(key, column, item, x, y) {
        menuKey = key
        menuColumn = column
        menuActions = backend.rowActions(key, column)
        rowMenu.popup(item, x, y)
    }
    // Official race, class of an official race or rival clicked: stats, recorded laps, race calculator, results
    function openComboMenu(track, vehicle, path, button) {
        if (!(comboMenu.visible && comboMenu.toggleSource === button)) {
            comboTarget = { "track": track, "vehicle": vehicle, "path": path }
            comboEntries = backend.comboActions(track, vehicle, path)
        }
        popupBelow(comboMenu, button)
    }
    // Popup or menu closed: focus put back where it was, but left on the window (table keys lost): table
    // (a popup or field focused by the menu action keeps it)
    function refocusTable() {
        var current = Window.activeFocusItem
        if (!current || current === Window.contentItem)
            table.forceActiveFocus()
    }
    // Menu of a button opened below it (second click on the button closes it)
    function popupBelow(menu, button) {
        menu.toggleBelow(button)
    }

    // Keys not taken by table (focused): F5 reload, "/" find track, Alt+Left back to All Tracks
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_F5) backend.reload()
        else if (event.key === Qt.Key_Slash) picker.openSearch()
        else if (event.key === Qt.Key_Left && (event.modifiers & Qt.AltModifier) && !page.allTracks) backend.showAllTracks()
        else return
        event.accepted = true
    }
    Component.onCompleted: table.forceActiveFocus()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space5

        // Header: back to All Tracks, track picker & subtitle, actions
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TpButton {
                visible: !page.allTracks
                flat: true
                glyph: ""  // chevron left
                fallback: "‹"
                tip: i18n.tr("Back to All Tracks") + " (Alt+←)"
                Layout.alignment: Qt.AlignTop
                onClicked: backend.showAllTracks()
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 12
                TrackPicker {
                    id: picker
                    onClosed: page.refocusTable()
                    Layout.fillWidth: true
                    Layout.maximumWidth: Math.max(implicitWidth, theme.em * 14)
                }
                RowLayout {
                    spacing: theme.em * 0.5
                    Layout.leftMargin: theme.em * 0.6
                    Layout.fillWidth: true
                    Pill {  // track of game session: one Live color for every page
                        visible: page.info.live === true
                        text: i18n.tr("Live")
                        tint: theme.live
                        dot: true
                        pulsing: page.info.live === true
                        tip: i18n.tr("Track of the running game session")
                    }
                    Text {
                        text: page.info.subtitle || ""
                        textFormat: Text.PlainText
                        color: theme.dimText
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }
            // Actions fitted to the room left: every text, then the least important icon only, then in "⋯"
            TpToolbar {
                id: toolbar
                objectName: "statsToolbar"
                onMenuClosed: page.refocusTable()
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                TpAction {
                    name: "mapButton"
                    text: i18n.tr("View Map")
                    glyph: ""  // map
                    priority: 2
                    enabled: !page.allTracks
                    onTriggered: backend.openMap()
                }
                TpAction {
                    name: "telemetryButton"
                    text: i18n.tr("Telemetry")
                    glyph: ""  // area chart
                    tip: i18n.tr("Recorded laps of selected car class in Lap Telemetry Viewer")
                    priority: 1
                    enabled: backend.hasLaps
                    onTriggered: backend.openLapViewer()
                }
                TpAction {
                    name: "undoButton"
                    glyph: theme.glyphs.undo
                    fallback: "↶"
                    tip: i18n.tr("Undo (Ctrl+Z)")
                    flat: true
                    priority: 3
                    enabled: backend.canUndo && !backend.editing
                    onTriggered: backend.undo()
                }
                TpAction {
                    name: "redoButton"
                    glyph: ""  // redo
                    fallback: "↷"
                    tip: i18n.tr("Redo (Ctrl+Y)")
                    flat: true
                    priority: 3
                    enabled: backend.canRedo && !backend.editing
                    onTriggered: backend.redo()
                }
                TpAction {
                    name: "exportButton"
                    text: i18n.tr("Export")
                    glyph: theme.glyphs.export
                    tip: i18n.tr("Export table to CSV file")
                    priority: 4
                    enabled: backend.hasRows
                    checked: exportMenu.visible
                    onTriggered: function(source) { page.popupBelow(exportMenu, source) }
                }
                TpAction {
                    name: "shareButton"
                    text: i18n.tr("Share")
                    glyph: theme.glyphs.share
                    tip: i18n.tr("Personal best of selected car as a picture or a code, codes of other drivers compared")
                    priority: 4
                    checked: shareMenu.visible
                    onTriggered: function(source) { page.popupBelow(shareMenu, source) }
                }
                TpAction {
                    name: "viewButton"
                    text: i18n.tr("View")
                    glyph: ""  // view
                    tip: i18n.tr("Columns, sort & colors of the table")
                    priority: 4
                    checked: viewMenu.visible
                    onTriggered: function(source) { page.popupBelow(viewMenu, source) }
                }
                TpAction {
                    name: "referenceButton"
                    text: i18n.tr("Reference")
                    glyph: ""  // globe
                    tip: i18n.tr("Community lap times compared with your lap times")
                    priority: 4
                    checked: referenceMenu.visible
                    onTriggered: function(source) { page.popupBelow(referenceMenu, source) }
                }
                TpAction {  // reload, backups, delete: always a button of its own
                    name: "moreButton"
                    glyph: theme.glyphs.more
                    fallback: "⋯"
                    tip: i18n.tr("Reload, backups & delete")
                    flat: true
                    pinned: true
                    priority: 9
                    checked: moreMenu.visible
                    onTriggered: function(source) { page.popupBelow(moreMenu, source) }
                }
            }
        }

        // Key figures
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: false
            columns: page.compact ? 3 : 6
            columnSpacing: theme.space4
            rowSpacing: theme.space4
            Repeater {
                model: page.tiles.length  // tiles kept when values change: fade & color animations
                TpStatTile {  // backend tile dict: title, value, detail, color, tip, glyph, letter, ratio
                    required property int index
                    readonly property var figure: page.tiles[index] || ({})
                    title: figure.title || ""
                    value: figure.value || "—"
                    detail: figure.detail || ""
                    tip: figure.tip || ""
                    glyph: figure.glyph || ""
                    tint: figure.color ? figure.color : theme.accent
                    valueColor: figure.color ? figure.color : null
                    letter: figure.letter || ""  // level told without color
                    ratio: figure.ratio !== undefined ? figure.ratio : -1
                    barSpace: true  // same height for every tile
                    animateValue: true
                    Layout.fillHeight: true
                }
            }
        }

        // Tabs: what the cards beside (and below) the table show
        TpTabBar {
            objectName: "statsTabs"
            name: i18n.tr("Driver Stats")
            model: [{ "text": i18n.tr("Overview"), "glyph": "" },  // view
                    { "text": i18n.tr("Progression"), "glyph": "" },  // area chart
                    { "text": i18n.tr("Compare"), "glyph": "" }]  // people
            currentIndex: page.tab
            onActivated: function(index) { backend.setStatsTab(index) }
        }

        // Table & what goes below it, cards of the tab at the side; below on narrow pages
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.narrow || !page.sideShown ? 1 : 2
            columnSpacing: theme.space5
            rowSpacing: theme.space5

            // Table & what goes below it
            ColumnLayout {
                id: mainColumn
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: theme.space5

                TpSectionCard {
                    id: tableCard
                    title: backend.tableTitle
                    glyph: page.allTracks ? "" : ""  // map pin, car
                    count: backend.hasRows ? String(table.count) : ""
                    // Search by name, rows of one class (shown when the table has several classes)
                    actions: [
                        TpCombo {
                            id: classCombo
                            objectName: "statsClassFilter"
                            readonly property var classes: backend.tableClasses
                            readonly property var choices: [i18n.tr("All Classes")].concat(classes)  // made when classes change
                            visible: classes.length > 1 || backend.classFilter !== ""
                            tip: i18n.tr("Rows of one class only")
                            implicitWidth: theme.em * 12
                            model: choices
                            currentIndex: Math.max(0, classes.indexOf(backend.classFilter) + 1)
                            onActivated: function(index) {
                                backend.setClassFilter(index > 0 ? classes[index - 1] : "")
                                page.refocusTable()
                            }
                        },
                        TpSearchField {
                            id: tableSearch
                            objectName: "statsSearch"
                            implicitWidth: theme.em * 11.5
                            placeholderText: page.allTracks ? i18n.tr("Find track") : i18n.tr("Find car")
                            onSearchChanged: function(text) { backend.setSearch(text) }
                            onExitField: table.forceActiveFocus()
                        }
                    ]
                    Layout.fillHeight: !page.tableCompact
                    // Every row when it fits in about half of the room under key figures & tabs (page height: no layout loop)
                    Layout.preferredHeight: !page.tableCompact ? -1
                        : Math.min(table.neededHeight + theme.em * 4.3, Math.max(theme.em * 9, (page.height - theme.em * 17.5) * 0.5))
                    Layout.minimumHeight: theme.em * 9
                    StatsTable {
                        id: table
                        focus: true
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: backend.hasRows
                        onCellMenu: function(key, column, x, y) { page.openRowMenu(key, column, table, x, y) }
                        onHeaderMenu: function(x, y) { headerMenu.popup(table, x, y) }
                    }
                    Item {  // stats files read in background (page opened, big session history), else why empty
                        visible: !backend.hasRows || backend.loading
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        TpStateView {
                            anchors.centerIn: parent
                            loading: backend.loading  // never "no stats" while still reading
                            empty: !backend.hasRows
                            glyph: ""  // car
                            title: backend.emptyText
                            text: i18n.tr("Stats are recorded by the Stats module while you drive.")
                        }
                    }
                }

                // Progression tab: daily activity (All Tracks), progression & sessions of selected vehicle: each made
                // when first shown, then kept (switching tabs or between All Tracks and a track only hides one)
                Loader {
                    Layout.fillWidth: true
                    Layout.preferredHeight: item ? item.implicitHeight : -1
                    visible: page.tab === 1 && page.allTracks
                    active: page.tab === 1 && page.allTracks
                    onLoaded: active = true  // kept once made
                    sourceComponent: StatsActivityCard {}
                }
                Loader {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: theme.em * 15
                    visible: page.tableCompact
                    active: page.tab === 1 && !page.allTracks
                    onLoaded: active = true  // kept once made
                    sourceComponent: StatsProgressionCard {
                        filtersOpen: filtersMenu.visible
                        onFiltersRequested: function(button) { page.popupBelow(filtersMenu, button) }
                    }
                }
            }

            // Side: cards of the tab (three at most), each set made when first shown, then kept
            Flickable {
                id: side
                objectName: "statsSide"
                visible: page.sideShown
                // Side column at the right; narrow page: below the table, full width, a third of the height
                Layout.preferredWidth: page.narrow ? -1 : page.compact ? theme.em * 23
                                       : Math.max(theme.em * 27, Math.min(theme.em * 34, page.width * 0.2))
                Layout.fillWidth: page.narrow
                Layout.fillHeight: !page.narrow
                Layout.preferredHeight: page.narrow ? Math.min(sideColumn.implicitHeight, page.height * 0.35) : -1
                contentHeight: sideColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    id: sideColumn
                    width: side.width - (side.contentHeight > side.height ? theme.space5 : 0)
                    spacing: theme.space5
                    Loader {  // Overview of a track: lap time goal, stints & consistency
                        Layout.fillWidth: true
                        visible: page.tab === 0 && !page.allTracks
                        active: page.tab === 0 && !page.allTracks
                        onLoaded: active = true
                        sourceComponent: ColumnLayout {
                            spacing: theme.space5
                            StatsGoalCard {}
                            // Stints & consistency of selected vehicle (recorded laps): pace & degradation by tyre compound,
                            // coefficient of variation of clean laps in each session & on this track
                            TpSectionCard {
                                visible: page.stints.visible === true
                                busy: page.stints.busy === true  // laps read in background: spinner in the header
                                title: i18n.tr("Stints & Consistency")
                                glyph: ""  // pulse
                                Text {
                                    visible: (page.stints.note || "") !== ""
                                    Layout.fillWidth: true
                                    text: page.stints.note || ""
                                    textFormat: Text.PlainText
                                    color: theme.dimText
                                    wrapMode: Text.WordWrap
                                }
                                RowLayout {
                                    visible: (page.stints.index || "") !== ""
                                    Layout.fillWidth: true
                                    spacing: theme.em * 0.5
                                    Text {
                                        text: page.stints.index || ""
                                        textFormat: Text.PlainText
                                        color: theme.accent
                                        font.pointSize: theme.fontLarge
                                        font.weight: Font.DemiBold
                                        font.features: { "tnum": 1 }
                                    }
                                    ColumnLayout {
                                        spacing: 0
                                        Layout.fillWidth: true
                                        Text {
                                            text: i18n.tr("Consistency index")
                                            color: theme.text
                                            font.weight: Font.DemiBold
                                            HoverHandler { id: indexHover }
                                            ToolTip.visible: indexHover.hovered
                                            ToolTip.delay: theme.tipDelay
                                            ToolTip.text: i18n.tr("Coefficient of variation of clean laps (lap time spread in percent of average lap time, traffic & mistakes left out): lower is more consistent")
                                        }
                                        Text { text: page.stints.indexInfo || ""; color: theme.dimText; font.pointSize: theme.fontSmall; elide: Text.ElideRight; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    }
                                }
                                // Tyre compounds: stints, clean laps, average pace, lap time change per lap (degradation)
                                StatsLabel {
                                    visible: (page.stints.compounds || []).length > 0
                                    text: i18n.tr("By tyre compound")
                                    HoverHandler { id: compoundHover }
                                    ToolTip.visible: compoundHover.hovered
                                    ToolTip.delay: theme.tipDelay
                                    ToolTip.text: i18n.tr("Average clean lap & lap time change per lap of stints (positive: tyres wear, slower each lap)")
                                }
                                Repeater {
                                    model: page.stints.compounds || []
                                    RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: theme.em * 0.4
                                        Repeater {  // compound badges (as overlays): front, rear if another
                                            model: modelData.names || []
                                            TpCompound { required property string modelData; name: modelData }
                                        }
                                        Text { text: modelData.compound; color: theme.text; elide: Text.ElideRight; Layout.fillWidth: true; textFormat: Text.PlainText }
                                        Text { text: modelData.stints + " × " + modelData.laps; color: theme.dimText; font.features: { "tnum": 1 }; textFormat: Text.PlainText }
                                        Text { text: modelData.pace; color: theme.text; font.features: { "tnum": 1 }; textFormat: Text.PlainText }
                                        Text {
                                            text: modelData.slope
                                            textFormat: Text.PlainText
                                            color: page.tone(modelData.slopeColor, theme.dimText)
                                            font.features: { "tnum": 1 }
                                            Layout.preferredWidth: theme.em * 6
                                            horizontalAlignment: Text.AlignRight
                                        }
                                    }
                                }
                                // Stints, newest first
                                StatsLabel { visible: (page.stints.stints || []).length > 0; text: i18n.tr("Stints") }
                                Repeater {
                                    model: page.stints.stints || []
                                    RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: theme.em * 0.4
                                        ToolTip.visible: stintHover.hovered
                                        ToolTip.delay: theme.tipDelay
                                        ToolTip.text: modelData.session + " · " + modelData.compound + " · " + i18n.tr("clean laps") + " " + modelData.laps
                                        HoverHandler { id: stintHover }
                                        Text { text: modelData.date; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5.6; textFormat: Text.PlainText }
                                        Text { text: modelData.laps; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 2.6; textFormat: Text.PlainText }
                                        Text { text: modelData.pace; color: theme.text; font.features: { "tnum": 1 }; horizontalAlignment: Text.AlignRight; Layout.fillWidth: true; textFormat: Text.PlainText }
                                        Text {
                                            text: modelData.slope
                                            textFormat: Text.PlainText
                                            color: page.tone(modelData.slopeColor, theme.dimText)
                                            font.features: { "tnum": 1 }
                                            Layout.preferredWidth: theme.em * 6
                                            horizontalAlignment: Text.AlignRight
                                        }
                                    }
                                }
                                // Consistency of each session, newest first
                                StatsLabel { visible: (page.stints.sessions || []).length > 0; text: i18n.tr("Consistency by session") }
                                Repeater {
                                    model: page.stints.sessions || []
                                    RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: theme.em * 0.4
                                        Text { text: modelData.date; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5.6; textFormat: Text.PlainText }
                                        Text { text: modelData.session; color: theme.text; elide: Text.ElideRight; Layout.fillWidth: true; textFormat: Text.PlainText }
                                        Text { text: modelData.pace; color: theme.dimText; font.features: { "tnum": 1 }; textFormat: Text.PlainText }
                                        Text {
                                            text: modelData.index
                                            textFormat: Text.PlainText
                                            color: theme.text
                                            font.features: { "tnum": 1 }
                                            Layout.preferredWidth: theme.em * 4
                                            horizontalAlignment: Text.AlignRight
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Loader {  // Overview of All Tracks: driver, progress of the week, official races to come
                        Layout.fillWidth: true
                        visible: page.tab === 0 && page.allTracks
                        active: page.tab === 0 && page.allTracks
                        onLoaded: active = true
                        sourceComponent: ColumnLayout {
                            spacing: theme.space5
                            StatsDriverCard {}
                            StatsWeekCard {}
                            StatsUpcomingCard {
                                onRaceClicked: function(track, vehicle, button) { page.openComboMenu(track, vehicle, "", button) }
                            }
                        }
                    }
                    Loader {  // Progression of All Tracks: recent sessions
                        Layout.fillWidth: true
                        visible: page.tab === 1 && page.allTracks
                        active: page.tab === 1 && page.allTracks
                        onLoaded: active = true
                        sourceComponent: StatsRecentCard {}
                    }
                    Loader {  // Compare of a track: lap time reference, friend & personal best codes
                        Layout.fillWidth: true
                        visible: page.tab === 2 && !page.allTracks
                        active: page.tab === 2 && !page.allTracks
                        onLoaded: active = true
                        sourceComponent: ColumnLayout {
                            spacing: theme.space5
                            StatsReferenceCard {}
                            StatsCompareCard { canShare: page.canShare }
                        }
                    }
                    Loader {  // Compare of All Tracks: levels, rivals, friend & personal best codes
                        Layout.fillWidth: true
                        visible: page.tab === 2 && page.allTracks
                        active: page.tab === 2 && page.allTracks
                        onLoaded: active = true
                        sourceComponent: ColumnLayout {
                            spacing: theme.space5
                            StatsLevelsCard {}
                            StatsRivalsCard {
                                onRivalClicked: function(track, vehicle, path, button) { page.openComboMenu(track, vehicle, path, button) }
                            }
                            StatsCompareCard { canShare: false }
                        }
                    }
                }
            }
        }

        // Footer: hint, lap time reference source
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em
            Icon { glyph: ""; size: theme.iconSm; color: theme.dimText }  // info
            Text {
                text: backend.hint
                textFormat: Text.PlainText
                color: theme.dimText
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Text {
                id: sourceText
                text: backend.referenceText
                textFormat: Text.StyledText
                color: theme.dimText
                linkColor: theme.accent
                onLinkActivated: function(link) { backend.openLink(link) }  // https only (text of a downloaded sheet)
                HoverHandler { cursorShape: sourceText.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
            }
        }
    }

    // Menus of the toolbar actions (opened next to their button, or next to "⋯" when the action is in it)
    TpMenu {
        id: shareMenu
        onClosed: page.refocusTable()
        Action { text: i18n.tr("Copy Personal Best Card"); enabled: page.canShare; onTriggered: backend.copyPbCard() }
        Action { text: i18n.tr("Save Personal Best Card…"); enabled: page.canShare; onTriggered: backend.exportPbCard() }
        Action { text: i18n.tr("Copy Personal Best Code"); enabled: page.canShare; onTriggered: backend.copyPbCode() }
        MenuSeparator {}
        Action { text: i18n.tr("Compare a Personal Best Code…"); onTriggered: backend.pastePbCode() }
    }
    TpMenu {
        id: filtersMenu
        onClosed: page.refocusTable()
        TpMenu {
            id: conditionMenu
            title: i18n.tr("Road")
            Instantiator {
                model: backend.conditionFilters
                delegate: Action {
                    required property var modelData
                    required property int index
                    text: modelData
                    checkable: true
                    checked: backend.conditionFilter === index
                    onTriggered: backend.setConditionFilter(index)
                }
                onObjectAdded: function(index, object) { conditionMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { conditionMenu.removeAction(object) }
            }
        }
        TpMenu {
            id: onlineMenu
            title: i18n.tr("Server")
            Instantiator {
                model: backend.onlineFilters
                delegate: Action {
                    required property var modelData
                    required property int index
                    text: modelData
                    checkable: true
                    checked: backend.onlineFilter === index
                    onTriggered: backend.setOnlineFilter(index)
                }
                onObjectAdded: function(index, object) { onlineMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { onlineMenu.removeAction(object) }
            }
        }
        TpMenu {
            id: versionMenu
            title: i18n.tr("Game Version")
            Instantiator {
                model: backend.versionChoices
                delegate: Action {
                    required property var modelData
                    required property int index
                    text: modelData.text
                    checkable: true
                    checked: backend.versionIndex === index
                    onTriggered: backend.setVersionFilter(index)
                }
                onObjectAdded: function(index, object) { versionMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { versionMenu.removeAction(object) }
            }
        }
        MenuSeparator {}
        Action { text: i18n.tr("Clear Filters"); enabled: backend.filtered; onTriggered: backend.clearFilters() }
    }
    TpMenu {
        id: exportMenu
        onClosed: page.refocusTable()
        Action { text: i18n.tr("Export CSV…"); onTriggered: backend.exportCsv(false) }
        Action { text: i18n.tr("Export Raw Values (CSV)…"); onTriggered: backend.exportCsv(true) }
        MenuSeparator {}
        Action { text: i18n.tr("Session History (CSV)…"); onTriggered: backend.exportHistory("csv") }
        Action { text: i18n.tr("Session History for a Friend (JSON)…"); onTriggered: backend.exportHistory("json") }
    }
    TpMenu {
        id: viewMenu
        onClosed: page.refocusTable()
        TpMenu {
            id: columnsMenu
            title: i18n.tr("Columns")
            Instantiator {
                model: backend.columnMenu
                delegate: Action {
                    required property var modelData
                    text: modelData.label
                    checkable: true
                    checked: modelData.visible
                    onTriggered: backend.setColumnVisible(modelData.key, checked)
                }
                onObjectAdded: function(index, object) { columnsMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { columnsMenu.removeAction(object) }
            }
        }
        Action { text: i18n.tr("Reset Column Widths"); onTriggered: backend.resetColumnWidths() }
        MenuSeparator {}
        Action {
            text: i18n.tr("Sort Tracks by Last Driven")
            checkable: true
            checked: backend.sortRecent
            onTriggered: backend.setSortRecent(checked)
        }
        Action {
            text: i18n.tr("Colorblind Colors")
            checkable: true
            checked: backend.colorblind
            onTriggered: backend.setColorblind(checked)
        }
        Action {
            text: i18n.tr("Group Cars by Class")
            checkable: true
            checked: backend.groupByClass
            onTriggered: backend.setGroupByClass(checked)
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("Official Races to Come (RaceControl)")
            checkable: true
            checked: backend.upcomingEnabled
            onTriggered: backend.setUpcomingEnabled(checked)
        }
    }
    TpMenu {
        id: referenceMenu
        onClosed: page.refocusTable()
        Action { text: i18n.tr("Update Reference"); enabled: !backend.downloading; onTriggered: backend.updateReference() }
        Action { text: i18n.tr("Change Sheet Address…"); onTriggered: backend.changeSheetUrl() }
        Action {
            text: i18n.tr("Compare With Community Lap Times")
            checkable: true
            checked: backend.compare
            onTriggered: backend.setCompare(checked)
        }
        MenuSeparator {}
        Action { text: i18n.tr("Compare With a Friend's Stats…"); onTriggered: backend.importFriend() }
        Action { text: i18n.tr("Stop Comparing With Friend"); enabled: backend.friend.visible === true; onTriggered: backend.clearFriend() }
    }
    TpMenu {
        id: moreMenu
        onClosed: page.refocusTable()
        Action { text: i18n.tr("Reload") + "\tF5"; onTriggered: backend.reload() }
        TpMenu {
            id: backupMenu
            title: i18n.tr("Restore Backup")
            Instantiator {
                model: backend.backups.length ? backend.backups : [{ "name": "", "date": i18n.tr("No backup yet") }]
                delegate: Action {
                    required property var modelData
                    text: modelData.date
                    enabled: modelData.name !== "" && !backend.editing
                    onTriggered: backend.restoreBackup(modelData.name)
                }
                onObjectAdded: function(index, object) { backupMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { backupMenu.removeAction(object) }
            }
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("Delete All Stats of This Track")
            enabled: backend.canDelete && !backend.editing
            onTriggered: backend.deleteTrack("")
        }
    }

    // Right click menus: row actions, columns shown
    TpMenu {
        id: rowMenu
        onClosed: page.refocusTable()
        Instantiator {
            model: page.menuActions
            delegate: Action {
                required property var modelData
                text: modelData.text
                enabled: modelData.enabled
                onTriggered: backend.runAction(modelData.id, page.menuKey, page.menuColumn)
            }
            onObjectAdded: function(index, object) { rowMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { rowMenu.removeAction(object) }
        }
    }
    TpMenu {
        id: headerMenu
        onClosed: page.refocusTable()
        Instantiator {
            model: backend.columnMenu
            delegate: Action {
                required property var modelData
                text: modelData.label
                checkable: true
                checked: modelData.visible
                onTriggered: backend.setColumnVisible(modelData.key, checked)
            }
            onObjectAdded: function(index, object) { headerMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { headerMenu.removeAction(object) }
        }
        MenuSeparator {}
        Action { text: i18n.tr("Reset Column Widths"); onTriggered: backend.resetColumnWidths() }
    }
    // Menu of an official race, a class of it or a rival (last race together)
    TpMenu {
        id: comboMenu
        objectName: "statsComboMenu"
        onClosed: page.refocusTable()
        Instantiator {
            model: page.comboEntries
            delegate: Action {
                required property var modelData
                text: modelData.text
                enabled: modelData.enabled
                onTriggered: backend.runComboAction(modelData.id, page.comboTarget.track, page.comboTarget.vehicle,
                                                    page.comboTarget.path)
            }
            onObjectAdded: function(index, object) { comboMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { comboMenu.removeAction(object) }
        }
    }

    // Dialogs & toasts asked by the backend (errors, confirmations, inputs, toasts)
    TpDialogHost {}
}
