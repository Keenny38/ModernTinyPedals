import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

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
    readonly property bool allTracks: backend.allTracks
    readonly property bool compact: width < theme.em * 80  // menu buttons as icons, 3 key figures a row
    property var menuActions: []
    property string menuKey: ""
    property string menuColumn: ""

    function tone(name, fallback) { return name === "loss" ? theme.loss : name === "gain" ? theme.gain : fallback }
    // Session filter colors: practice, qualifying, race
    function kindColor(kind) { return kind === 3 ? theme.accent : kind === 2 ? theme.purple : theme.dimText }
    function resultColor(result, podium) {
        if (result === "DNF" || result === "DQ") return theme.warning
        if (podium === 1) return theme.gold
        if (podium === 2) return theme.dark ? "#C3CAD4" : "#64748B"
        if (podium === 3) return theme.dark ? "#D99A62" : "#9A5B2C"
        return theme.text
    }
    function openRowMenu(key, column, item, x, y) {
        menuKey = key
        menuColumn = column
        menuActions = backend.rowActions(key, column)
        rowMenu.popup(item, x, y)
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

    // Small colored label: session type, race result
    component Chip: Rectangle {
        property string text: ""
        property color tint: theme.dimText
        property bool strong: false
        visible: text !== ""
        implicitHeight: Math.round(theme.em * 1.45)
        implicitWidth: chipText.implicitWidth + theme.em * 0.9
        radius: height / 2
        color: Qt.rgba(tint.r, tint.g, tint.b, theme.dark ? 0.16 : 0.12)
        Text {
            id: chipText
            anchors.centerIn: parent
            text: parent.text
            color: parent.tint
            font.pointSize: theme.fontPoint * 0.8
            font.weight: parent.strong ? Font.Bold : Font.DemiBold
            font.features: { "tnum": 1 }
        }
    }
    // Empty state: icon, message
    component EmptyState: ColumnLayout {
        property string glyph: ""
        property string text: ""
        property string detail: ""
        spacing: theme.em * 0.4
        Item { Layout.fillHeight: true }
        Icon {
            glyph: parent.glyph
            size: theme.em * 2.4
            color: theme.dimText
            opacity: 0.6
            Layout.alignment: Qt.AlignHCenter
        }
        Text {
            text: parent.text
            color: theme.text
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
        Text {
            visible: text !== ""
            text: parent.detail
            color: theme.dimText
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
        Item { Layout.fillHeight: true }
    }
    // Small section title inside a card
    component SectionLabel: Text {
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.85
        font.weight: Font.DemiBold
        Layout.topMargin: theme.em * 0.25
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.8
        anchors.bottomMargin: theme.em * 0.6
        spacing: theme.em * 0.65

        // Header: back to All Tracks, track picker & subtitle, actions
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TpButton {
                visible: !page.allTracks
                flat: true
                glyph: ""  // chevron left
                text: theme.iconFont === "" ? "<" : ""
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
                    Layout.fillWidth: true
                    Layout.maximumWidth: Math.max(implicitWidth, theme.em * 14)
                }
                RowLayout {
                    spacing: theme.em * 0.5
                    Layout.leftMargin: theme.em * 0.55
                    Layout.fillWidth: true
                    Rectangle {  // track of game session
                        visible: page.info.live === true
                        implicitHeight: Math.round(theme.em * 1.4)
                        implicitWidth: liveRow.implicitWidth + theme.em * 0.9
                        radius: height / 2
                        color: Qt.rgba(theme.gain.r, theme.gain.g, theme.gain.b, 0.14)
                        ToolTip.visible: liveHover.hovered
                        ToolTip.text: i18n.tr("Track of the running game session")
                        ToolTip.delay: 500
                        HoverHandler { id: liveHover }
                        Row {
                            id: liveRow
                            anchors.centerIn: parent
                            spacing: theme.em * 0.35
                            Rectangle {
                                id: liveDot
                                width: theme.em * 0.5
                                height: width
                                radius: width / 2
                                color: theme.gain
                                anchors.verticalCenter: parent.verticalCenter
                                SequentialAnimation on opacity {
                                    running: page.info.live === true && page.visible
                                    loops: Animation.Infinite
                                    onRunningChanged: if (!running) liveDot.opacity = 1
                                    NumberAnimation { to: 0.3; duration: 800; easing.type: Easing.InOutSine }
                                    NumberAnimation { to: 1; duration: 800; easing.type: Easing.InOutSine }
                                }
                            }
                            Text {
                                text: i18n.tr("Live")
                                color: theme.gain
                                font.pointSize: theme.fontPoint * 0.8
                                font.weight: Font.Bold
                            }
                        }
                    }
                    Text {
                        text: page.info.subtitle || ""
                        color: theme.dimText
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }
            RowLayout {
                spacing: theme.em * 0.35
                Layout.alignment: Qt.AlignTop
                TpButton {
                    glyph: ""  // map
                    text: i18n.tr("View Map")
                    enabled: !page.allTracks
                    onClicked: backend.openMap()
                }
                TpButton {
                    glyph: ""  // area chart
                    text: i18n.tr("Telemetry")
                    tip: i18n.tr("Recorded laps of selected vehicle class in Lap Telemetry Viewer")
                    enabled: backend.hasLaps
                    onClicked: backend.openLapViewer()
                }
                Rectangle { implicitWidth: 1; implicitHeight: theme.em * 1.4; color: theme.border; Layout.leftMargin: theme.em * 0.2; Layout.rightMargin: theme.em * 0.2 }
                TpButton { flat: true; glyph: ""; tip: i18n.tr("Undo (Ctrl+Z)"); enabled: backend.canUndo; onClicked: backend.undo() }
                TpButton { flat: true; glyph: ""; tip: i18n.tr("Redo (Ctrl+Y)"); enabled: backend.canRedo; onClicked: backend.redo() }
                TpButton {
                    id: exportButton
                    glyph: ""  // export
                    text: page.compact && theme.iconFont !== "" ? "" : i18n.tr("Export")
                    tip: i18n.tr("Export table to CSV file")
                    enabled: backend.hasRows
                    checked: exportMenu.visible
                    onClicked: page.popupBelow(exportMenu, exportButton)
                    TpMenu {
                        id: exportMenu
                        Action { text: i18n.tr("Export CSV..."); onTriggered: backend.exportCsv(false) }
                        Action { text: i18n.tr("Export Raw Values (CSV)..."); onTriggered: backend.exportCsv(true) }
                        MenuSeparator {}
                        Action { text: i18n.tr("Session History (CSV)..."); onTriggered: backend.exportHistory("csv") }
                        Action { text: i18n.tr("Session History for a Friend (JSON)..."); onTriggered: backend.exportHistory("json") }
                    }
                }
                TpButton {
                    id: viewButton
                    glyph: ""  // view
                    text: page.compact && theme.iconFont !== "" ? "" : i18n.tr("View")
                    tip: page.compact ? i18n.tr("View") : ""
                    checked: viewMenu.visible
                    onClicked: page.popupBelow(viewMenu, viewButton)
                    TpMenu {
                        id: viewMenu
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
                }
                TpButton {
                    id: referenceButton
                    glyph: ""  // globe
                    text: page.compact && theme.iconFont !== "" ? "" : i18n.tr("Reference")
                    tip: i18n.tr("Community lap times compared with your lap times")
                    checked: referenceMenu.visible
                    onClicked: page.popupBelow(referenceMenu, referenceButton)
                    TpMenu {
                        id: referenceMenu
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
                }
                TpButton {
                    id: moreButton
                    flat: true
                    glyph: ""  // more
                    text: theme.iconFont === "" ? "..." : ""
                    tip: i18n.tr("More actions")
                    checked: moreMenu.visible
                    onClicked: page.popupBelow(moreMenu, moreButton)
                    TpMenu {
                        id: moreMenu
                        Action { text: i18n.tr("Reload") + "\tF5"; onTriggered: backend.reload() }
                        TpMenu {
                            id: backupMenu
                            title: i18n.tr("Restore Backup")
                            Instantiator {
                                model: backend.backups.length ? backend.backups : [{ "name": "", "date": i18n.tr("No backup yet") }]
                                delegate: Action {
                                    required property var modelData
                                    text: modelData.date
                                    enabled: modelData.name !== ""
                                    onTriggered: backend.restoreBackup(modelData.name)
                                }
                                onObjectAdded: function(index, object) { backupMenu.insertAction(index, object) }
                                onObjectRemoved: function(index, object) { backupMenu.removeAction(object) }
                            }
                        }
                        MenuSeparator {}
                        Action {
                            text: i18n.tr("Delete all stats of this track")
                            enabled: backend.canDelete
                            onTriggered: backend.deleteTrack("")
                        }
                    }
                }
            }
        }

        // Key figures
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: false
            columns: page.compact ? 3 : 6
            columnSpacing: theme.em * 0.6
            rowSpacing: theme.em * 0.6
            Repeater {
                model: page.tiles.length  // tiles kept when values change: fade & color animations
                StatsTile {
                    required property int index
                    figure: page.tiles[index] || ({})
                    Layout.fillHeight: true
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: theme.em * 0.65

            // Table & what goes below it
            ColumnLayout {
                id: mainColumn
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: theme.em * 0.65

                StatsCard {
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
                    EmptyState {
                        visible: !backend.hasRows
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        glyph: ""  // car
                        text: backend.emptyText
                        detail: i18n.tr("Stats are recorded by the Stats module while you drive.")
                    }
                }

                Loader {  // progression & sessions of selected vehicle, or daily activity (All Tracks)
                    Layout.fillWidth: true
                    Layout.fillHeight: !page.allTracks
                    Layout.preferredHeight: page.allTracks && item ? item.implicitHeight : -1
                    Layout.minimumHeight: page.allTracks ? 0 : theme.em * 15
                    visible: page.allTracks || backend.hasRows
                    sourceComponent: page.allTracks ? activityCard : progressionCard
                }
            }

            // Side: selected vehicle (All Tracks: levels & recent sessions), friend
            Flickable {
                id: side
                Layout.preferredWidth: page.compact ? theme.em * 23 : theme.em * 27
                Layout.fillHeight: true
                contentHeight: sideColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    id: sideColumn
                    width: side.width - (side.contentHeight > side.height ? theme.em * 0.7 : 0)
                    spacing: theme.em * 0.65
                    Loader {
                        Layout.fillWidth: true
                        sourceComponent: page.allTracks ? allTracksSide : vehicleSide
                    }
                    StatsCard {  // friend's personal bests against own (exported session history of a friend)
                        visible: page.friend.visible === true
                        title: i18n.tr("Friend") + " · " + (page.friend.name || "")
                        glyph: ""  // people
                        actions: TpButton {
                            text: theme.iconFont === "" ? "×" : ""
                            glyph: ""  // cancel
                            flat: true
                            implicitHeight: theme.em * 1.7
                            tip: i18n.tr("Stop Comparing With Friend")
                            onClicked: backend.clearFriend()
                        }
                        Text { text: page.friend.summary || ""; color: theme.dimText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        RowLayout {
                            visible: (page.friend.rows || []).length > 0
                            Layout.fillWidth: true
                            spacing: theme.em * 0.4
                            Text { text: page.allTracks ? i18n.tr("Track") : i18n.tr("Class"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.85; Layout.fillWidth: true }
                            Text { text: i18n.tr("You"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.85; Layout.preferredWidth: theme.em * 5; horizontalAlignment: Text.AlignRight }
                            Text { text: page.friend.name || ""; color: theme.dimText; font.pointSize: theme.fontPoint * 0.85; elide: Text.ElideRight; Layout.preferredWidth: theme.em * 5; horizontalAlignment: Text.AlignRight }
                            Item { Layout.preferredWidth: theme.em * 4.4 }
                        }
                        Repeater {
                            model: page.friend.rows || []
                            RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: theme.em * 0.4
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
        StatsCard {
            id: progressionBox
            readonly property bool split: width > theme.em * 54
            property bool showSessions: false
            title: i18n.tr("Progression")
            glyph: ""  // area chart
            tip: i18n.tr("Best lap of each session & personal best so far, level limits of community lap times")
            actions: [
                TpSegmented {
                    options: backend.sessionFilters
                    currentIndex: backend.sessionFilter
                    onActivated: function(index) { backend.setSessionFilter(index) }
                },
                TpButton {
                    visible: !progressionBox.split
                    flat: true
                    checked: progressionBox.showSessions
                    glyph: ""  // list
                    text: theme.iconFont === "" ? i18n.tr("Sessions") : ""
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
                    EmptyState {
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
                        font.pointSize: theme.fontPoint * 0.9
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
                    Layout.preferredWidth: progressionBox.split ? Math.min(theme.em * 25, progressionBox.width * 0.45) : -1
                    Layout.fillHeight: true
                    spacing: theme.em * 0.2
                    RowLayout {
                        Layout.fillWidth: true
                        SectionLabel { text: i18n.tr("Sessions"); Layout.topMargin: 0 }
                        Text {
                            text: backend.sessions.length ? String(backend.sessions.length) : ""
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.85
                            font.features: { "tnum": 1 }
                        }
                        Item { Layout.fillWidth: true }
                    }
                    ListView {
                        id: sessionList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        reuseItems: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: backend.sessions
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Rectangle {
                            id: sessionItem
                            required property var modelData
                            required property int index
                            width: ListView.view.width
                            height: Math.round(theme.em * 2)
                            radius: theme.em * 0.35
                            color: sessionArea.containsMouse ? theme.hover : "transparent"
                            ToolTip.visible: sessionArea.containsMouse
                            ToolTip.text: modelData.tip
                            ToolTip.delay: 600
                            MouseArea { id: sessionArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: theme.em * 0.3
                                anchors.rightMargin: theme.em * 0.3
                                spacing: theme.em * 0.45
                                Text {
                                    text: sessionItem.modelData.date
                                    color: theme.dimText
                                    font.features: { "tnum": 1 }
                                    font.pointSize: theme.fontPoint * 0.9
                                    Layout.preferredWidth: theme.em * 5.6  // dd/mm/yyyy
                                }
                                Chip {
                                    text: sessionItem.modelData.session
                                    tint: page.kindColor(sessionItem.modelData.kind)
                                    Layout.maximumWidth: theme.em * 7
                                }
                                Item { Layout.fillWidth: true }
                                Icon {
                                    visible: sessionItem.modelData.pb === true
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
                                    font.pointSize: theme.fontPoint * 0.9
                                    Layout.preferredWidth: theme.em * 2.8
                                    horizontalAlignment: Text.AlignRight
                                }
                                Item {
                                    Layout.preferredWidth: theme.em * 2.6
                                    implicitHeight: resultChip.implicitHeight
                                    Chip {
                                        id: resultChip
                                        anchors.right: parent.right
                                        text: sessionItem.modelData.result
                                        tint: page.resultColor(sessionItem.modelData.result, sessionItem.modelData.podium)
                                        strong: true
                                    }
                                }
                            }
                        }
                        Text {
                            visible: sessionList.count === 0
                            anchors.centerIn: parent
                            width: parent.width
                            text: i18n.tr("No session recorded yet: history starts with your next session.")
                            color: theme.dimText
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
            }
        }
    }

    // Daily driving activity, all tracks
    Component {
        id: activityCard
        StatsCard {
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
            spacing: theme.em * 0.65
            Connections {  // other vehicle: contents fade in
                target: backend
                function onSelectionChanged() { selectionFade.restart() }
            }
            StatsCard {
                id: referenceCard
                title: i18n.tr("Lap Time Reference")
                glyph: ""  // globe
                tip: i18n.tr("Community lap times compared with your lap times")
                NumberAnimation { id: selectionFade; target: referenceCard; property: "opacity"; from: 0.4; to: 1; duration: 220 }
                RowLayout {  // vehicle & level of its personal best
                    visible: page.reference.vehicle !== undefined && page.reference.vehicle !== ""
                    Layout.fillWidth: true
                    spacing: theme.em * 0.45
                    Text {
                        text: page.reference.vehicle || ""
                        color: theme.text
                        font.pointSize: theme.fontPoint * 1.1
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
                    font.pointSize: theme.fontPoint * 0.9
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
                    Text { text: i18n.tr("Reference"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.9 }
                    Text {
                        text: page.reference.referenceTime || "-"
                        color: theme.text
                        font.features: { "tnum": 1 }
                        Layout.fillWidth: true
                    }
                    Text { visible: (page.reference.gapTime || "") !== ""; text: i18n.tr("Gap"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.9 }
                    Text {
                        visible: (page.reference.gapTime || "") !== ""
                        text: (page.reference.gapTime || "") + "  (" + (page.reference.percent || "") + ")"
                        color: theme.text
                        font.features: { "tnum": 1 }
                        Layout.fillWidth: true
                    }
                    Text { visible: (page.reference.next || "") !== ""; text: i18n.tr("Next level"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.9 }
                    RowLayout {
                        visible: (page.reference.next || "") !== ""
                        spacing: theme.em * 0.35
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
                            ToolTip.delay: 500
                        }
                    }
                }
                Text {
                    visible: page.reference.visible === true && (page.reference.fastest || "") !== ""
                    Layout.fillWidth: true
                    text: page.reference.fastest || ""
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.9
                    wrapMode: Text.WordWrap
                }
                // Lap time limit of each level, marks of personal, qualifying & race bests
                SectionLabel { visible: page.reference.visible === true; text: i18n.tr("Levels") }
                Repeater {
                    model: page.reference.visible ? page.reference.ladder : []
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: Math.round(theme.em * 1.75)
                        radius: theme.em * 0.35
                        color: modelData.active ? Qt.rgba(theme.hover.r, theme.hover.g, theme.hover.b, 0.9) : "transparent"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: theme.em * 0.35
                            anchors.rightMargin: theme.em * 0.35
                            spacing: theme.em * 0.4
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
                                font.pointSize: theme.fontPoint * 0.9
                                Layout.preferredWidth: theme.em * 5.2
                                horizontalAlignment: Text.AlignRight
                            }
                        }
                    }
                }
                RowLayout {  // no reference: reason
                    visible: page.reference.visible !== true && (page.reference.reason || "") !== ""
                    Layout.fillWidth: true
                    spacing: theme.em * 0.45
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
            StatsCard {
                visible: page.stints.visible === true
                title: i18n.tr("Stints & Consistency")
                glyph: ""  // pulse
                BusyIndicator {
                    visible: page.stints.busy === true
                    running: visible
                    implicitWidth: theme.em * 1.6
                    implicitHeight: implicitWidth
                    Layout.alignment: Qt.AlignHCenter
                }
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
                        font.pointSize: theme.fontPoint * 1.35
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
                            ToolTip.delay: 500
                            ToolTip.text: i18n.tr("Coefficient of variation of clean laps (lap time spread in percent of average lap time, traffic & mistakes left out): lower is more consistent")
                        }
                        Text { text: page.stints.indexInfo || ""; color: theme.dimText; font.pointSize: theme.fontPoint * 0.85; elide: Text.ElideRight; Layout.fillWidth: true }
                    }
                }
                // Tyre compounds: stints, clean laps, average pace, lap time change per lap (degradation)
                SectionLabel {
                    visible: (page.stints.compounds || []).length > 0
                    text: i18n.tr("By tyre compound")
                    HoverHandler { id: compoundHover }
                    ToolTip.visible: compoundHover.hovered
                    ToolTip.delay: 500
                    ToolTip.text: i18n.tr("Average clean lap & lap time change per lap of stints (positive: tyres wear, slower each lap)")
                }
                Repeater {
                    model: page.stints.compounds || []
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: theme.em * 0.4
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
                        ToolTip.delay: 600
                        ToolTip.text: modelData.session + " · " + modelData.compound + " · " + i18n.tr("clean laps") + " " + modelData.laps
                        HoverHandler { id: stintHover }
                        Text { text: modelData.date; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 5.6 }
                        Text { text: modelData.laps; color: theme.dimText; font.features: { "tnum": 1 }; Layout.preferredWidth: theme.em * 2.6 }
                        Text { text: modelData.pace; color: theme.text; font.features: { "tnum": 1 }; Layout.fillWidth: true }
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
            spacing: theme.em * 0.65
            StatsCard {
                title: i18n.tr("Levels, All Tracks")
                glyph: ""  // star
                tip: i18n.tr("Level of your best lap of each track & class on community lap times")
                Repeater {
                    model: backend.levels
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: theme.em * 0.45
                        Rectangle {
                            Layout.preferredWidth: theme.em * 1.3
                            Layout.preferredHeight: theme.em * 1.3
                            radius: width / 2
                            color: modelData.color
                            Text {
                                anchors.centerIn: parent
                                text: modelData.letter
                                color: "white"
                                font.pointSize: theme.fontPoint * 0.72
                                font.weight: Font.Bold
                            }
                        }
                        Text { text: modelData.name; color: theme.text; elide: Text.ElideRight; Layout.preferredWidth: theme.em * 8 }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: theme.em * 0.6
                            radius: height / 2
                            color: theme.hover
                            Rectangle {
                                width: Math.max(parent.width * modelData.ratio, modelData.count ? height : 0)
                                height: parent.height
                                radius: height / 2
                                color: modelData.color
                                Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                            }
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
                    font.pointSize: theme.fontPoint * 0.9
                    wrapMode: Text.WordWrap
                }
            }
            StatsCard {  // latest sessions: click to show track & vehicle
                visible: backend.recent.length > 0
                title: i18n.tr("Recent Sessions")
                glyph: ""  // history
                Repeater {
                    model: backend.recent
                    Rectangle {
                        id: recentItem
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: recentRow.implicitHeight + theme.em * 0.5
                        radius: theme.em * 0.4
                        color: recentArea.containsMouse ? theme.hover : "transparent"
                        Behavior on color { ColorAnimation { duration: 100 } }
                        MouseArea {
                            id: recentArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.openSession(recentItem.modelData.track, recentItem.modelData.vehicle)
                        }
                        ToolTip.visible: recentArea.containsMouse
                        ToolTip.text: i18n.tr("Show this track & vehicle")
                        ToolTip.delay: 700
                        RowLayout {
                            id: recentRow
                            anchors.verticalCenter: parent.verticalCenter
                            x: theme.em * 0.35
                            width: parent.width - theme.em * 0.7
                            spacing: theme.em * 0.45
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
                                    font.pointSize: theme.fontPoint * 0.85
                                    font.features: { "tnum": 1 }
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }
                            ColumnLayout {
                                spacing: 2
                                Row {
                                    Layout.alignment: Qt.AlignRight
                                    spacing: theme.em * 0.3
                                    Icon {
                                        visible: recentItem.modelData.pb === true
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
                                    spacing: theme.em * 0.25
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

    // Right click menus: row actions, columns shown
    TpMenu {
        id: rowMenu
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
