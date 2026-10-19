import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"
import "../telemetry"

// Driver stats viewer page: track picker as title (vehicles, sessions, last driven), actions, key figures,
// table of vehicles (tracks for All Tracks).
// Track: progression chart & sessions of selected vehicle below the table, lap time reference (level scale),
// stints & consistency at the side. All Tracks: daily driving activity below, level distribution & recent
// sessions at the side. Friend's comparison at the side in both.
// Keys: F5 reload, "/" find track, Alt+Left or Backspace (table) All Tracks, Delete (table) remove row.
TpPage {
    id: page

    readonly property var reference: backend.reference
    readonly property var progression: backend.progression
    readonly property var stints: backend.stints
    readonly property var friend: backend.friend
    readonly property var info: backend.trackInfo
    readonly property var tiles: backend.tiles
    readonly property var driver: backend.driver  // driver card (All Tracks)
    readonly property var sessions: backend.sessions  // sessions of selected vehicle
    readonly property bool allTracks: backend.allTracks
    readonly property bool compact: width < theme.bpWide  // menu buttons as icons, 3 key figures a row
    readonly property bool narrow: width < theme.bpNarrow  // side cards below the table
    property var menuActions: []
    property string menuKey: ""
    property string menuColumn: ""

    function tone(name, fallback) { return name === "loss" || name === "gain" ? theme.tone(name) : fallback }
    // Session filter (1 practice, 2 qualifying, 3 race): one session color for every page (theme.sessionColor)
    function kindColor(kind) { return theme.sessionColor(kind === 3 ? "R" : kind === 2 ? "Q" : kind === 1 ? "P" : "") }
    function resultColor(result, podium) {
        if (result === "DNF" || result === "DQ") return theme.warning
        if (podium === 1) return theme.gold
        if (podium === 2) return theme.silver
        if (podium === 3) return theme.bronze
        return theme.text
    }
    function openRowMenu(key, column, item, x, y) {
        menuKey = key
        menuColumn = column
        menuActions = backend.rowActions(key, column)
        rowMenu.popup(item, x, y)
    }
    // Popup or menu closed: focus put back where it was, but left on the window (table keys lost): table
    // (a popup or field focused by the menu action keeps it)
    function refocusTable() {
        var current = Window.activeFocusItem
        if (!current || current === Window.contentItem)
            table.forceActiveFocus()
    }
    function popupBelow(menu, button) {
        menu.visible ? menu.close() : menu.popup(button, 0, button.height + 4)
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

    // Small colored label: session type, race result (shared Pill look, hidden without text)
    component Chip: Pill {
        property bool strong: false  // result: told by its text (P1, DNF), the tint only adds to it
        visible: text !== ""
    }
    // Empty state of a card part: centered message (shared TpStateView), fills the room it explains
    component StatsEmpty: Item {
        property string glyph: ""
        property string text: ""
        property string detail: ""
        implicitHeight: emptyView.implicitHeight
        TpStateView {
            id: emptyView
            anchors.centerIn: parent
            empty: true
            compact: true
            glyph: parent.glyph
            title: parent.text
            text: parent.detail
        }
    }
    // Small section title inside a card
    component SectionLabel: TpSectionLabel {
        Layout.topMargin: theme.space2
        Layout.fillWidth: true
    }

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
                    tip: i18n.tr("Recorded laps of selected vehicle class in Lap Telemetry Viewer")
                    priority: 1
                    enabled: backend.hasLaps
                    onTriggered: backend.openLapViewer()
                }
                TpAction {
                    name: "undoButton"
                    glyph: ""  // undo
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
                    glyph: ""  // export
                    tip: i18n.tr("Export table to CSV file")
                    priority: 4
                    enabled: backend.hasRows
                    checked: exportMenu.visible
                    onTriggered: function(source) { page.popupBelow(exportMenu, source) }
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
                    glyph: ""  // more
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
                    value: figure.value || "-"
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

        // Table & what goes below it, selected vehicle (or All Tracks) cards at the side; below on narrow pages
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.narrow ? 1 : 2
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
                    Layout.fillHeight: page.allTracks || !backend.hasRows
                    // Every row when it fits in about half of the room under key figures (page height: no layout loop)
                    Layout.preferredHeight: page.allTracks || !backend.hasRows ? -1
                        : Math.min(table.neededHeight + theme.em * 4.3, Math.max(theme.em * 9, (page.height - theme.em * 15) * 0.5))
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

                // Daily activity (All Tracks), progression & sessions of selected vehicle: each made when first
                // shown, then kept (switching between All Tracks and a track only hides one, nothing rebuilt)
                Loader {
                    Layout.fillWidth: true
                    Layout.preferredHeight: item ? item.implicitHeight : -1
                    visible: page.allTracks
                    active: page.allTracks
                    onLoaded: active = true  // kept once made
                    sourceComponent: activityCard
                }
                Loader {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: theme.em * 15
                    visible: !page.allTracks && backend.hasRows
                    active: !page.allTracks
                    onLoaded: active = true  // kept once made
                    sourceComponent: progressionCard
                }
            }

            // Side: selected vehicle (All Tracks: levels & recent sessions), friend
            Flickable {
                id: side
                // Side column at the right; narrow page: below the table, full width, a third of the height
                Layout.preferredWidth: page.narrow ? -1 : page.compact ? theme.em * 23 : theme.em * 27
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
                    Loader {  // All Tracks side (driver, levels, recent sessions): made when first shown, then kept
                        Layout.fillWidth: true
                        visible: page.allTracks
                        active: page.allTracks
                        onLoaded: active = true
                        sourceComponent: allTracksSide
                    }
                    Loader {  // selected vehicle side: made when first shown, then kept
                        Layout.fillWidth: true
                        visible: !page.allTracks
                        active: !page.allTracks
                        onLoaded: active = true
                        sourceComponent: vehicleSide
                    }
                    TpSectionCard {  // friend's personal bests against own (exported session history of a friend)
                        visible: page.friend.visible === true
                        title: i18n.tr("Friend") + " · " + (page.friend.name || "")
                        glyph: ""  // people
                        actions: TpButton {
                            fallback: "✕"
                            glyph: ""  // cancel
                            flat: true
                            size: "sm"
                            tip: i18n.tr("Stop Comparing With Friend")
                            onClicked: backend.clearFriend()
                        }
                        Text { text: page.friend.summary || ""; color: theme.dimText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        RowLayout {
                            visible: (page.friend.rows || []).length > 0
                            Layout.fillWidth: true
                            spacing: theme.space3
                            TpHeaderCell { text: page.allTracks ? i18n.tr("Track") : i18n.tr("Class"); Layout.fillWidth: true }
                            TpHeaderCell { text: i18n.tr("You"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 5 }
                            TpHeaderCell { text: page.friend.name || ""; align: Qt.AlignRight; Layout.preferredWidth: theme.em * 5 }
                            TpHeaderCell { text: i18n.tr("Gap"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 4.4 }
                        }
                        Repeater {
                            model: page.friend.rows || []
                            RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: theme.space3
                                Text {
                                    text: page.allTracks ? modelData.track + " · " + modelData.vehicleClass : modelData.vehicleClass
                                    color: theme.text
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Text { text: modelData.mine; color: theme.text; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5; horizontalAlignment: Text.AlignRight }
                                Text { text: modelData.friend; color: theme.text; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5; horizontalAlignment: Text.AlignRight }
                                Text {
                                    text: modelData.gap
                                    color: page.tone(modelData.gapColor, theme.dimText)
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                    Layout.preferredWidth: theme.em * 4.4
                                    horizontalAlignment: Text.AlignRight
                                }
                            }
                        }
                    }
                }
            }
        }

        // Footer: hint, lap time reference source
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em
            Icon { glyph: ""; size: theme.em * 0.85; color: theme.dimText }  // info
            Text {
                text: backend.hint
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
                onLinkActivated: function(link) { Qt.openUrlExternally(link) }
                HoverHandler { cursorShape: sourceText.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
            }
        }
    }

    // Progression chart & sessions of selected vehicle (side by side when wide enough, else one at a time)
    Component {
        id: progressionCard
        TpSectionCard {
            id: progressionBox
            readonly property bool split: width > theme.em * 54  // content-tuned: chart (25 em) & sessions list (29 em)
            property bool showSessions: false
            title: i18n.tr("Progression")
            glyph: ""  // area chart
            tip: i18n.tr("Best lap of each session & personal best so far, level limits of community lap times")
            actions: [
                TpSegmented {
                    name: i18n.tr("Sessions")
                    options: backend.sessionFilters
                    currentIndex: backend.sessionFilter
                    onActivated: function(index) { backend.setSessionFilter(index) }
                },
                TpButton {
                    visible: !progressionBox.split
                    flat: true
                    checked: progressionBox.showSessions
                    glyph: ""  // list
                    size: "sm"
                    fallback: i18n.tr("Sessions")
                    tip: i18n.tr("Sessions")
                    onClicked: progressionBox.showSessions = !progressionBox.showSessions
                }
            ]
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: theme.em * 0.8
                ColumnLayout {
                    visible: progressionBox.split || !progressionBox.showSessions
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: theme.em * 0.3
                    StatsChart {
                        visible: page.progression.visible === true
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: theme.em * 8
                        chartData: page.progression
                    }
                    StatsEmpty {
                        visible: page.progression.visible !== true
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        glyph: ""
                        text: i18n.tr("2 sessions with a lap time needed for a chart.")
                    }
                    Text {
                        Layout.fillWidth: true
                        text: page.progression.info || ""
                        color: theme.dimText
                        wrapMode: Text.WordWrap
                        font.pointSize: theme.fontLabel
                    }
                }
                Rectangle {
                    visible: progressionBox.split
                    Layout.fillHeight: true
                    implicitWidth: 1
                    color: theme.border
                    opacity: 0.6
                }
                ColumnLayout {  // sessions of selected vehicle, newest first
                    visible: progressionBox.split || progressionBox.showSessions
                    Layout.fillWidth: !progressionBox.split
                    Layout.preferredWidth: progressionBox.split ? Math.min(theme.em * 29, progressionBox.width * 0.5) : -1
                    Layout.fillHeight: true
                    spacing: theme.em * 0.2
                    RowLayout {
                        Layout.fillWidth: true
                        SectionLabel { text: i18n.tr("Sessions"); Layout.topMargin: 0 }
                        Text {
                            readonly property int total: page.progression.sessions || 0  // all, list shows newest
                            text: !page.sessions.length ? ""
                                  : total > page.sessions.length ? page.sessions.length + " / " + total
                                  : String(page.sessions.length)
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            font.features: { "tnum": 1 }
                        }
                        Item { Layout.fillWidth: true }
                    }
                    ListView {
                        id: sessionList
                        objectName: "sessionList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        reuseItems: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: page.sessions
                        // Keyboard: Tab, Up / Down, Enter shows the session in Results & Replays (results file)
                        activeFocusOnTab: count > 0
                        currentIndex: -1
                        keyNavigationEnabled: true
                        highlightFollowsCurrentItem: false
                        Accessible.role: Accessible.List
                        Accessible.name: i18n.tr("Sessions")
                        onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
                        Keys.onReturnPressed: if (currentItem && currentItem.modelData.results) backend.openResults(currentItem.modelData.results)
                        Keys.onEnterPressed: if (currentItem && currentItem.modelData.results) backend.openResults(currentItem.modelData.results)
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Item {
                            id: sessionItem
                            required property var modelData
                            required property int index
                            readonly property bool linked: (modelData.results || "") !== ""  // results file: opens it
                            width: ListView.view.width
                            height: Math.round(theme.rowCompact)
                            Accessible.role: Accessible.ListItem
                            Accessible.name: modelData.tip || ""
                            ToolTip.visible: sessionArea.containsMouse || (sessionList.activeFocus && ListView.isCurrentItem)
                            ToolTip.text: modelData.tip
                            ToolTip.delay: theme.tipDelay
                            TpListRow {  // hover only on sessions that open something
                                id: sessionSurface
                                anchors.fill: parent
                                anchors.margins: 1
                                radius: theme.radiusSm
                                hovered: sessionArea.containsMouse && sessionItem.linked
                            }
                            FocusRing {
                                target: sessionSurface
                                anchors.margins: 0
                                visible: sessionList.activeFocus && sessionItem.ListView.isCurrentItem
                            }
                            MouseArea {  // session of a results file: shown in race results page
                                id: sessionArea
                                anchors.fill: parent
                                hoverEnabled: true
                                acceptedButtons: sessionItem.linked ? Qt.LeftButton : Qt.NoButton
                                cursorShape: sessionItem.linked ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: backend.openResults(sessionItem.modelData.results)
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: theme.space2
                                anchors.rightMargin: theme.space2
                                spacing: theme.em * 0.5
                                Text {
                                    text: sessionItem.modelData.date
                                    color: theme.dimText
                                    font.features: { "tnum": 1 }
                                    font.pointSize: theme.fontLabel
                                    Layout.preferredWidth: theme.em * 5.6  // dd/mm/yyyy
                                }
                                Chip {
                                    text: sessionItem.modelData.session
                                    tint: page.kindColor(sessionItem.modelData.kind)
                                    Layout.maximumWidth: theme.em * 7
                                }
                                Text {  // game version when driven
                                    visible: text !== ""
                                    text: sessionItem.modelData.version ? "v" + sessionItem.modelData.version : ""
                                    color: theme.dimText
                                    font.pointSize: theme.fontCaption
                                    font.features: { "tnum": 1 }
                                }
                                Item { Layout.fillWidth: true }
                                Icon {  // contacts & penalties of session (results file)
                                    visible: sessionItem.modelData.incidents > 0
                                    glyph: "\uE945"  // lightning
                                    size: theme.em * 0.7
                                    color: theme.warning
                                }
                                Icon {  // personal best: star (★ without icon font) & accent color
                                    visible: sessionItem.modelData.pb === true
                                    fallback: "★"
                                    glyph: ""  // star
                                    size: theme.em * 0.75
                                    color: theme.accent
                                }
                                Text {
                                    text: sessionItem.modelData.best
                                    color: sessionItem.modelData.pb ? theme.accent : sessionItem.modelData.best === "-" ? theme.dimText : theme.text
                                    font.weight: sessionItem.modelData.pb ? Font.DemiBold : Font.Normal
                                    font.features: { "tnum": 1 }
                                }
                                Text {
                                    text: sessionItem.modelData.laps
                                    color: theme.dimText
                                    font.features: { "tnum": 1 }
                                    font.pointSize: theme.fontLabel
                                    Layout.preferredWidth: theme.em * 2.8
                                    horizontalAlignment: Text.AlignRight
                                }
                                Item {
                                    Layout.preferredWidth: theme.em * 3.6
                                    implicitHeight: resultChip.implicitHeight
                                    Chip {
                                        id: resultChip
                                        anchors.right: parent.right
                                        text: sessionItem.modelData.result || sessionItem.modelData.rank
                                        tint: sessionItem.modelData.result ? page.resultColor(sessionItem.modelData.result, sessionItem.modelData.podium)
                                                                           : theme.dimText
                                        strong: sessionItem.modelData.result !== ""
                                    }
                                }
                            }
                        }
                        TpStateView {
                            parent: sessionList  // over the list, not inside its scrolled content
                            anchors.centerIn: parent
                            empty: sessionList.count === 0
                            compact: true
                            text: i18n.tr("No session recorded yet: history starts with your next session.")
                        }
                    }
                }
            }
        }
    }

    // Daily driving activity, all tracks
    Component {
        id: activityCard
        TpSectionCard {
            title: i18n.tr("Activity")
            glyph: ""  // calendar
            tip: i18n.tr("Driving time of each day, all tracks")
            StatsActivity {
                Layout.fillWidth: true
                activityData: backend.activity
            }
        }
    }

    // Side of a track: lap time reference of selected vehicle (level scale), stints & consistency
    Component {
        id: vehicleSide
        ColumnLayout {
            spacing: theme.space5
            TpSectionCard {  // other vehicle: values change in place (no fade: keyboard browsing never flickers)
                id: referenceCard
                title: i18n.tr("Lap Time Reference")
                glyph: ""  // globe
                tip: i18n.tr("Community lap times compared with your lap times")
                RowLayout {  // vehicle & level of its personal best
                    visible: page.reference.vehicle !== undefined && page.reference.vehicle !== ""
                    Layout.fillWidth: true
                    spacing: theme.em * 0.5
                    Text {
                        text: page.reference.vehicle || ""
                        color: theme.text
                        font.pointSize: theme.fontSubtitle
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Chip {
                        text: page.reference.level || ""
                        tint: page.reference.levelColor || theme.dimText
                        strong: true
                    }
                }
                Text {
                    visible: page.reference.visible === true
                    Layout.fillWidth: true
                    text: page.reference.detail || ""
                    color: theme.dimText
                    font.pointSize: theme.fontLabel
                    wrapMode: Text.WordWrap
                }
                StatsGauge {
                    visible: page.reference.visible === true && (page.reference.gauge || {}).segments !== undefined
                    Layout.fillWidth: true
                    Layout.topMargin: theme.em * 0.3
                    scaleData: page.reference.gauge || ({})
                }
                GridLayout {  // personal best against reference, next level
                    visible: page.reference.visible === true
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: theme.em * 0.8
                    rowSpacing: theme.em * 0.15
                    Text { text: i18n.tr("Reference"); color: theme.dimText; font.pointSize: theme.fontLabel }
                    Text {
                        text: page.reference.referenceTime || "-"
                        color: theme.text
                        font.features: { "tnum": 1 }
                        Layout.fillWidth: true
                    }
                    Text { visible: (page.reference.gapTime || "") !== ""; text: i18n.tr("Gap"); color: theme.dimText; font.pointSize: theme.fontLabel }
                    Text {
                        visible: (page.reference.gapTime || "") !== ""
                        text: (page.reference.gapTime || "") + "  (" + (page.reference.percent || "") + ")"
                        color: theme.text
                        font.features: { "tnum": 1 }
                        Layout.fillWidth: true
                    }
                    Text { visible: (page.reference.next || "") !== ""; text: i18n.tr("Next level"); color: theme.dimText; font.pointSize: theme.fontLabel }
                    RowLayout {
                        visible: (page.reference.next || "") !== ""
                        spacing: theme.em * 0.4
                        Layout.fillWidth: true
                        Rectangle {
                            visible: (page.reference.nextLevel || {}).color !== undefined
                            implicitWidth: theme.em * 0.65
                            implicitHeight: implicitWidth
                            radius: width / 2
                            color: (page.reference.nextLevel || {}).color || "transparent"
                        }
                        Text {
                            text: (page.reference.nextLevel || {}).name !== undefined
                                  ? page.reference.nextLevel.name + "  " + page.reference.nextLevel.toFind
                                  : (page.reference.next || "")
                            color: theme.accent
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                            HoverHandler { id: nextHover }
                            ToolTip.visible: nextHover.hovered
                            ToolTip.text: page.reference.next || ""
                            ToolTip.delay: theme.tipDelay
                        }
                    }
                }
                Text {
                    visible: page.reference.visible === true && (page.reference.fastest || "") !== ""
                    Layout.fillWidth: true
                    text: page.reference.fastest || ""
                    color: theme.dimText
                    font.pointSize: theme.fontLabel
                    wrapMode: Text.WordWrap
                }
                // Lap time limit of each level, marks of personal, qualifying & race bests
                SectionLabel { visible: page.reference.visible === true; text: i18n.tr("Levels") }
                Repeater {
                    model: page.reference.visible ? page.reference.ladder : []
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
                                color: theme.text
                                font.weight: modelData.active ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Repeater {
                                model: modelData.pills || []
                                Chip {
                                    required property var modelData
                                    text: modelData
                                    tint: theme.accent
                                }
                            }
                            Text {
                                text: modelData.limit
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
                    visible: page.reference.visible !== true && (page.reference.reason || "") !== ""
                    Layout.fillWidth: true
                    spacing: theme.em * 0.5
                    Icon { glyph: ""; color: theme.dimText; size: theme.em * 0.95; Layout.alignment: Qt.AlignTop }  // info
                    Text {
                        Layout.fillWidth: true
                        text: page.reference.reason || ""
                        color: theme.dimText
                        wrapMode: Text.WordWrap
                    }
                }
            }

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
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                }
                RowLayout {
                    visible: (page.stints.index || "") !== ""
                    Layout.fillWidth: true
                    spacing: theme.em * 0.5
                    Text {
                        text: page.stints.index || ""
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
                        Text { text: page.stints.indexInfo || ""; color: theme.dimText; font.pointSize: theme.fontSmall; elide: Text.ElideRight; Layout.fillWidth: true }
                    }
                }
                // Tyre compounds: stints, clean laps, average pace, lap time change per lap (degradation)
                SectionLabel {
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
                        Text { text: modelData.compound; color: theme.text; elide: Text.ElideRight; Layout.fillWidth: true }
                        Text { text: modelData.stints + " × " + modelData.laps; color: theme.dimText; font.features: { "tnum": 1 } }
                        Text { text: modelData.pace; color: theme.text; font.features: { "tnum": 1 } }
                        Text {
                            text: modelData.slope
                            color: page.tone(modelData.slopeColor, theme.dimText)
                            font.features: { "tnum": 1 }
                            Layout.preferredWidth: theme.em * 6
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                }
                // Stints, newest first
                SectionLabel { visible: (page.stints.stints || []).length > 0; text: i18n.tr("Stints") }
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
                        Text { text: modelData.date; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5.6 }
                        Text { text: modelData.laps; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 2.6 }
                        Text { text: modelData.pace; color: theme.text; font.features: { "tnum": 1 }; horizontalAlignment: Text.AlignRight; Layout.fillWidth: true }
                        Text {
                            text: modelData.slope
                            color: page.tone(modelData.slopeColor, theme.dimText)
                            font.features: { "tnum": 1 }
                            Layout.preferredWidth: theme.em * 6
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                }
                // Consistency of each session, newest first
                SectionLabel { visible: (page.stints.sessions || []).length > 0; text: i18n.tr("Consistency by session") }
                Repeater {
                    model: page.stints.sessions || []
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: theme.em * 0.4
                        Text { text: modelData.date; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5.6 }
                        Text { text: modelData.session; color: theme.text; elide: Text.ElideRight; Layout.fillWidth: true }
                        Text { text: modelData.pace; color: theme.dimText; font.features: { "tnum": 1 } }
                        Text {
                            text: modelData.index
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

    // Side of All Tracks: levels of best laps, recent sessions
    Component {
        id: allTracksSide
        ColumnLayout {
            spacing: theme.space5
            TpSectionCard {  // driver: game profile, Steam picture, races of game results files
                visible: page.driver.visible === true
                title: i18n.tr("Driver")
                glyph: "\uE77B"  // contact
                tip: page.driver.info || ""
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
                            text: page.driver.initials || ""
                            color: theme.accent
                            font.pointSize: theme.fontHeading
                            font.weight: Font.Bold
                        }
                        Image {
                            id: avatar
                            anchors.fill: parent
                            anchors.margins: 1
                            source: page.driver.avatar || ""
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
                            text: page.driver.name || ""
                            color: theme.text
                            font.weight: Font.DemiBold
                            font.pointSize: theme.fontSubtitle
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text {
                            visible: text !== ""
                            text: page.driver.detail || ""
                            color: theme.dimText
                            font.pointSize: theme.fontLabel
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
                ColumnLayout {  // driver & safety ranks of game menu: rank in its color, progress to next tier; badge
                    visible: (page.driver.ranks || []).length > 0 || ((page.driver.badge || {}).name || "") !== ""
                    Layout.fillWidth: true
                    Layout.topMargin: theme.em * 0.3
                    spacing: theme.em * 0.4
                    Repeater {
                        model: page.driver.ranks || []
                        RowLayout {
                            required property var modelData
                            readonly property color rankColor: (theme.dark ? modelData.color : modelData.lightColor)
                                                               || theme.accent
                            Layout.fillWidth: true
                            spacing: theme.em * 0.5
                            Text {
                                text: modelData.label
                                color: theme.dimText
                                font.pointSize: theme.fontSmall
                                Layout.preferredWidth: theme.em * 6.5
                                elide: Text.ElideRight
                            }
                            Text {
                                text: modelData.value
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
                                color: theme.text
                                font.pointSize: theme.fontSmall
                                font.features: { "tnum": 1 }
                                horizontalAlignment: Text.AlignRight
                                Layout.preferredWidth: theme.em * 2.6
                            }
                            Text {  // change since previous rank
                                visible: modelData.change !== ""
                                text: (modelData.changeTone > 0 ? "\u25B2 " : "\u25BC ") + modelData.change
                                color: modelData.changeTone > 0 ? theme.gain : theme.loss
                                font.pointSize: theme.fontCaption
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                    RowLayout {  // badge of game menu: game icon, name in its color, description
                        readonly property var badge: page.driver.badge || {}
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
                                color: parent.parent.badgeColor
                                font.weight: Font.DemiBold
                                font.pointSize: theme.fontSubtitle
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Text {
                                visible: text !== ""
                                text: parent.parent.badge.description || ""
                                color: theme.dimText
                                font.pointSize: theme.fontCaption
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                    Text {
                        visible: text !== ""
                        text: page.driver.ranksInfo || ""
                        color: theme.dimText
                        font.pointSize: theme.fontCaption
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
                ColumnLayout {  // other game accounts of this computer: last ranks seen, badge, date
                    visible: (page.driver.otherAccounts || []).length > 0
                    Layout.fillWidth: true
                    Layout.topMargin: theme.em * 0.3
                    spacing: theme.em * 0.3
                    TpSectionLabel { text: i18n.tr("Other accounts"); Layout.fillWidth: true }
                    Repeater {
                        model: page.driver.otherAccounts || []
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
                                    color: (theme.dark ? modelData.color : modelData.lightColor) || theme.text
                                    font.weight: Font.DemiBold
                                    font.pointSize: theme.fontSmall
                                }
                            }
                            Text {
                                readonly property var badge: accountRow.modelData.badge || {}
                                visible: (badge.name || "") !== ""
                                text: badge.name || ""
                                color: (theme.dark ? badge.color : badge.lightColor) || theme.text
                                font.pointSize: theme.fontSmall
                            }
                            Text {  // when ranks were seen
                                text: accountRow.modelData.when
                                color: theme.dimText
                                font.pointSize: theme.fontCaption
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                }
                GridLayout {  // races of results files
                    visible: (page.driver.figures || []).length > 0
                    Layout.fillWidth: true
                    Layout.topMargin: theme.em * 0.3
                    columns: 3
                    columnSpacing: theme.em * 0.5
                    rowSpacing: theme.em * 0.4
                    Repeater {
                        model: page.driver.figures || []
                        TpKeyValue {  // label above the value, as every key figure
                            required property var modelData
                            layout: "stack"
                            large: true
                            label: modelData.label
                            value: modelData.value
                            Layout.preferredWidth: 1  // equal columns
                        }
                    }
                }
                Text {
                    visible: text !== ""
                    text: page.driver.info || ""
                    color: theme.dimText
                    font.pointSize: theme.fontCaption
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                RowLayout {  // lap times of stats missing or slower than in results files
                    visible: (page.driver.fixes || 0) > 0
                    Layout.fillWidth: true
                    Layout.topMargin: theme.em * 0.2
                    spacing: theme.em * 0.5
                    Icon { glyph: "\uE916"; size: theme.em * 0.9; color: theme.accent }  // stopwatch
                    Text {
                        text: page.driver.fixText || ""
                        color: theme.text
                        font.pointSize: theme.fontLabel
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    TpButton {
                        text: i18n.tr("Complete...")
                        tip: i18n.tr("Add lap times of race results missing from your stats, or faster than them")
                        enabled: !backend.editing
                        onClicked: backend.completeLapTimes()
                    }
                }
            }
            TpSectionCard {
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
                                color: theme.inkOn(modelData.color)  // readable on level color
                                font.pointSize: theme.fontTiny
                                font.weight: Font.Bold
                            }
                        }
                        Text { text: modelData.name; color: theme.text; elide: Text.ElideRight; Layout.preferredWidth: theme.em * 8 }
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
                    color: theme.dimText
                    font.pointSize: theme.fontLabel
                    wrapMode: Text.WordWrap
                }
            }
            TpSectionCard {  // latest sessions: click to show track & vehicle
                visible: backend.recent.length > 0
                title: i18n.tr("Recent Sessions")
                glyph: ""  // history
                Repeater {
                    model: backend.recent
                    AbstractButton {  // click, or Tab then Enter / Space: show this track & vehicle
                        id: recentItem
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: recentRow.implicitHeight + theme.em * 0.5
                        hoverEnabled: true
                        focusPolicy: Qt.TabFocus
                        onClicked: backend.openSession(recentItem.modelData.track, recentItem.modelData.vehicle)
                        Keys.onReturnPressed: animateClick()
                        Keys.onEnterPressed: animateClick()
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.track + ", " + modelData.vehicle + ", " + modelData.date
                        Accessible.description: i18n.tr("Show this track & vehicle")
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        ToolTip.visible: hovered || visualFocus
                        ToolTip.text: i18n.tr("Show this track & vehicle")
                        ToolTip.delay: theme.tipDelay
                        background: TpListRow {
                            hovered: recentItem.hovered
                            pressed: recentItem.down
                            FocusRing { visible: recentItem.visualFocus }
                        }
                        contentItem: Item {}
                        RowLayout {
                            id: recentRow
                            anchors.verticalCenter: parent.verticalCenter
                            x: theme.space2
                            width: parent.width - theme.space2 * 2
                            spacing: theme.em * 0.5
                            GameLogo {  // circuit logo of game
                                source: recentItem.modelData.trackLogo || ""
                                boxWidth: theme.em * 2.6
                                boxHeight: theme.em * 1.6
                            }
                            ColumnLayout {
                                spacing: 0
                                Layout.fillWidth: true
                                Text {
                                    text: recentItem.modelData.track
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Text {
                                    text: recentItem.modelData.date + " · " + recentItem.modelData.vehicle
                                    color: theme.dimText
                                    font.pointSize: theme.fontSmall
                                    font.features: { "tnum": 1 }
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }
                            ColumnLayout {
                                spacing: theme.space1
                                Row {
                                    Layout.alignment: Qt.AlignRight
                                    spacing: theme.space2
                                    Icon {  // personal best: star (★ without icon font) & accent color
                                        visible: recentItem.modelData.pb === true
                                        fallback: "★"
                                        glyph: ""  // star
                                        size: theme.em * 0.7
                                        color: theme.accent
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: recentItem.modelData.best
                                        color: recentItem.modelData.pb ? theme.accent : recentItem.modelData.best === "-" ? theme.dimText : theme.text
                                        font.weight: recentItem.modelData.pb ? Font.DemiBold : Font.Normal
                                        font.features: { "tnum": 1 }
                                    }
                                }
                                Row {
                                    Layout.alignment: Qt.AlignRight
                                    spacing: theme.em * 0.3
                                    Chip {
                                        text: recentItem.modelData.result
                                        tint: page.resultColor(recentItem.modelData.result, recentItem.modelData.podium)
                                        strong: true
                                    }
                                    Chip {
                                        text: recentItem.modelData.session
                                        tint: page.kindColor(recentItem.modelData.kind)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Menus of the toolbar actions (opened next to their button, or next to "⋯" when the action is in it)
    TpMenu {
        id: exportMenu
        onClosed: page.refocusTable()
        Action { text: i18n.tr("Export CSV..."); onTriggered: backend.exportCsv(false) }
        Action { text: i18n.tr("Export Raw Values (CSV)..."); onTriggered: backend.exportCsv(true) }
        MenuSeparator {}
        Action { text: i18n.tr("Session History (CSV)..."); onTriggered: backend.exportHistory("csv") }
        Action { text: i18n.tr("Session History for a Friend (JSON)..."); onTriggered: backend.exportHistory("json") }
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
            text: i18n.tr("Colorblind colors")
            checkable: true
            checked: backend.colorblind
            onTriggered: backend.setColorblind(checked)
        }
    }
    TpMenu {
        id: referenceMenu
        onClosed: page.refocusTable()
        Action { text: i18n.tr("Update Reference"); enabled: !backend.downloading; onTriggered: backend.updateReference() }
        Action { text: i18n.tr("Change Sheet Address..."); onTriggered: backend.changeSheetUrl() }
        Action {
            text: i18n.tr("Compare With Community Lap Times")
            checkable: true
            checked: backend.compare
            onTriggered: backend.setCompare(checked)
        }
        MenuSeparator {}
        Action { text: i18n.tr("Compare With a Friend's Stats..."); onTriggered: backend.importFriend() }
        Action { text: i18n.tr("Stop Comparing With Friend"); enabled: page.friend.visible === true; onTriggered: backend.clearFriend() }
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
            text: i18n.tr("Delete all stats of this track")
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
}
