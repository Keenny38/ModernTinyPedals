import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Replays saved by the game: search (every word in track, event, session), session filter, sort,
// sections by day (or track). Click: select (Ctrl: add to selection, Shift: range, Ctrl+A: all),
// double click or Enter: watch in game (after confirmation), Delete: move to recycle bin, right click or Menu
// key: menu. Add: copy replay files to game folder (also by dropping them on the page). "/": search field.
Item {
    id: root

    // Wherever focus is on the page (text fields keep the key)
    Shortcut {
        sequence: "/"
        enabled: pageState.active && root.visible
        onActivated: { searchField.forceActiveFocus(); searchField.selectAll() }
    }

    readonly property bool searching: searchField.activeFocus
    readonly property var folderInfo: replays.folderInfo  // read once per change (sizes of every file)
    readonly property var sorts: [
        { "key": "date", "text": i18n.tr("Newest First") },
        { "key": "size", "text": i18n.tr("Largest First") },
        { "key": "track", "text": i18n.tr("By Track") },
    ]
    readonly property bool roomy: width > theme.em * 36  // content-tuned: button texts next to the title
    readonly property bool roomyRow: width > theme.em * 34  // content-tuned: date & size next to the Watch button
    // Read once here: rows bind to these (one evaluation per change), not to the backend
    readonly property bool many: replays.checkedCount > 1  // several replays selected
    readonly property bool gameOnline: replays.gameState !== "offline"

    function showSelected() {
        var index = replays.replayIndex(replays.selectedReplay)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }
    function openRowMenu(key, isProtected, many, item, x, y) {
        menuKey = key
        menuProtected = isProtected
        menuMany = many
        rowMenu.popup(item, x, y)
    }
    property string menuKey: ""
    property bool menuMany: false  // row menu on one of several selected replays
    property bool menuProtected: false

    TpMenu {
        id: rowMenu
        onClosed: if (!Window.activeFocusItem || Window.activeFocusItem === Window.contentItem) list.forceActiveFocus()
        Action {
            text: i18n.tr("Watch in Game")
            enabled: replays.gameState !== "offline" && !root.menuMany
            onTriggered: replays.watchReplay(root.menuKey)
        }
        Action {  // results file of replay's session (results & replays page)
            text: i18n.tr("Show Results")
            enabled: !root.menuMany && replays.resultsOf(root.menuKey) !== ""
            onTriggered: backend.showResults(replays.resultsOf(root.menuKey))
        }
        Action {
            text: i18n.tr("Show in Folder")
            enabled: replays.replayFolder !== "" && !root.menuMany
            onTriggered: replays.showInFolder(root.menuKey)
        }
        Action {
            text: root.menuMany ? i18n.tr("Export %1 Replays…").arg(replays.checkedCount) : i18n.tr("Export Replay…")
            enabled: replays.replayFolder !== "" && !replays.copying
            onTriggered: replays.exportReplays(root.menuKey)
        }
        Action {
            text: i18n.tr("Rename Replay…")
            enabled: replays.replayFolder !== "" && !root.menuMany
            onTriggered: replays.renameReplay(root.menuKey)
        }
        Action {
            text: root.menuProtected ? i18n.tr("Unprotect") : i18n.tr("Protect From Deletion")
            onTriggered: replays.toggleProtected(root.menuKey)
        }
        MenuSeparator {}
        TpMenuItem {  // Delete key on the list does the same
            text: root.menuMany ? i18n.tr("Delete %1 Replays…").arg(replays.checkedCount) : i18n.tr("Delete Replay…")
            shortcut: i18n.tr("Del")
            enabled: replays.replayFolder !== "" && (root.menuMany || !root.menuProtected) && !replays.trashing
            onTriggered: replays.deleteReplays(root.menuKey)
        }
    }

    // Folder clean up & selected replays
    TpMenu {
        id: moreMenu
        Action {
            text: replays.checkedCount > 1 ? i18n.tr("Export %1 Replays…").arg(replays.checkedCount) : i18n.tr("Export Replay…")
            enabled: replays.replayFolder !== "" && replays.selectedReplay !== "" && !replays.copying
            onTriggered: replays.exportReplays(replays.selectedReplay)
        }
        Action {
            text: replays.selectedProtected ? i18n.tr("Unprotect") : i18n.tr("Protect From Deletion")
            enabled: replays.selectedReplay !== ""
            onTriggered: replays.toggleProtected(replays.selectedReplay)
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("Delete Replays Older Than…")
            enabled: replays.replayFolder !== "" && replays.replayCount > 0 && !replays.trashing
            onTriggered: replays.deleteOlderThan()
        }
        Action {
            text: i18n.tr("Keep Only Latest Replays…")
            enabled: replays.replayFolder !== "" && replays.replayCount > 0 && !replays.trashing
            onTriggered: replays.keepLatest()
        }
        Action {
            text: i18n.tr("Delete Temporary Files (%1, %2)").arg(root.folderInfo.temp).arg(root.folderInfo.tempSize)
            enabled: replays.replayFolder !== "" && root.folderInfo.temp > 0 && !replays.trashing
            onTriggered: replays.deleteTempFiles()
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("%1 replays, %2, %3 protected").arg(root.folderInfo.replays).arg(root.folderInfo.size)
                  .arg(root.folderInfo.protected)
            enabled: false
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.space3

        // Title, count & size, sort
        TpCardHeader {
            glyph: ""  // video
            title: i18n.tr("Replays")
            count: replays.replayCount > 0 ? replays.replaysSummary : ""
            busy: replays.loading
            TpButton {
                glyph: theme.glyphs.add
                fallback: "+"
                text: root.roomy ? i18n.tr("Add") : ""
                tip: replays.replayFolder !== "" ? i18n.tr("Add replay files (.Vcr) to the game replay folder, or drop them on the page")
                                                 : i18n.tr("Replay folder unknown: start LMU once so the page lists its replays")
                enabled: replays.replayFolder !== "" && !replays.copying
                flat: true
                size: "sm"
                onClicked: replays.addReplays()
                Accessible.name: i18n.tr("Add")
            }
            TpButton {
                glyph: theme.glyphs.delete
                fallback: "✕"
                tip: (replays.checkedCount > 1 ? i18n.tr("Move selected replays to the recycle bin")
                                               : i18n.tr("Move replay to the recycle bin")) + " (" + i18n.tr("Delete") + ")"
                enabled: replays.replayFolder !== "" && replays.selectedReplay !== "" && !replays.trashing
                flat: true
                size: "sm"
                onClicked: replays.deleteReplays(replays.selectedReplay)
            }
            TpButton {
                id: moreButton
                glyph: theme.glyphs.more
                fallback: "⋯"
                tip: i18n.tr("Export, protect, clean up the replay folder")
                flat: true
                size: "sm"
                checked: moreMenu.visible
                onClicked: moreMenu.toggleBelow(moreButton)
            }
            TpButton {
                id: sortButton
                glyph: ""  // sort
                fallback: "⇅"
                text: root.width > theme.em * 30 ? root.sorts.find(function(sort) { return sort.key === replays.sortKey }).text : ""  // content-tuned
                tip: i18n.tr("Sort")
                flat: true
                size: "sm"
                checked: sortMenu.visible
                onClicked: sortMenu.toggleBelow(sortButton)
                TpMenu {
                    id: sortMenu
                    Instantiator {
                        model: root.sorts
                        delegate: Action {
                            required property var modelData
                            text: modelData.text
                            checkable: true
                            checked: replays.sortKey === modelData.key
                            onTriggered: replays.setSort(modelData.key)
                        }
                        onObjectAdded: function(index, object) { sortMenu.insertAction(index, object) }
                        onObjectRemoved: function(index, object) { sortMenu.removeAction(object) }
                    }
                }
            }
        }

        // Replays being copied to game folder, files being moved to the recycle bin
        FileProgress {
            visible: replays.copying
            text: replays.copyKind === "export" ? i18n.tr("Exporting replays…") : i18n.tr("Copying replays…")
            progress: replays.copyProgress
            stopText: i18n.tr("Stop Copy")
            onStopped: replays.cancelCopy()
        }
        FileProgress {
            objectName: "trashProgress"
            visible: replays.trashing
            text: i18n.tr("Moving to the recycle bin…")
            progress: replays.trashProgress
            stopText: i18n.tr("Stop")
            onStopped: replays.cancelTrash()
        }

        // Search & session filter
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TpSearchField {
                id: searchField
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                searchDelay: 200
                placeholderText: i18n.tr("Search replays: track, event…") + "   /"
                onSearchChanged: function(text) { replays.setSearch(text) }
                onExitField: list.forceActiveFocus()
                Keys.onEscapePressed: { clearSearch(); list.forceActiveFocus() }
                Keys.onReturnPressed: list.forceActiveFocus()
                Keys.onEnterPressed: list.forceActiveFocus()
            }
            TpSegmented {
                name: i18n.tr("Session")
                options: [i18n.tr("All"), i18n.tr("Practice"), i18n.tr("Qualifying"), i18n.tr("Race")]  // SESSION_FILTER_LABELS
                currentIndex: replays.sessionFilter
                maxWidth: root.width * 0.58
                onActivated: function(index) { replays.setSessionFilter(index) }
            }
        }

        // Several replays selected
        Rectangle {
            Layout.fillWidth: true
            visible: replays.checkedCount > 1
            implicitHeight: Math.round(theme.controlHeight)
            radius: theme.radiusMd
            color: theme.tint(theme.accent, "subtle")
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: theme.padCard
                anchors.rightMargin: theme.space2
                spacing: theme.space3
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Selected") + "  " + replays.checkedSummary
                    textFormat: Text.PlainText
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.features: { "tnum": 1 }
                    elide: Text.ElideRight
                }
                TpButton {
                    glyph: theme.glyphs.delete
                    text: i18n.tr("Delete")
                    flat: true
                    size: "sm"
                    onClicked: replays.deleteReplays(replays.selectedReplay)
                }
                TpButton {
                    glyph: theme.glyphs.remove
                    fallback: "✕"
                    flat: true
                    size: "sm"
                    tip: i18n.tr("Clear selection (Escape)")
                    onClicked: replays.selectReplay(replays.selectedReplay)
                }
            }
        }

        ListView {
            id: list
            objectName: "replayList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            focus: true
            activeFocusOnTab: true
            model: replays.replayRows
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true  // rows scrolled out fed again with other replays (see delegate onPooled)
            Accessible.role: Accessible.List
            Accessible.name: i18n.tr("Replays")
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: { replays.moveReplaySelection(-1); root.showSelected() }
            Keys.onDownPressed: { replays.moveReplaySelection(1); root.showSelected() }
            Keys.onReturnPressed: replays.watchReplay(replays.selectedReplay)
            Keys.onEnterPressed: replays.watchReplay(replays.selectedReplay)
            Keys.onDeletePressed: replays.deleteReplays(replays.selectedReplay)
            Keys.onEscapePressed: replays.selectReplay(replays.selectedReplay)
            Keys.onPressed: function(event) {
                if (event.matches(StandardKey.SelectAll)) { replays.selectAllReplays(); event.accepted = true }
                else if ((event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && event.modifiers === Qt.ShiftModifier))
                         && replays.selectedReplay !== "") {  // menu of the selected replay (Menu key, Shift+F10)
                    var index = replays.replayIndex(replays.selectedReplay)
                    var item = index >= 0 ? list.itemAtIndex(index) : null
                    if (item) root.openRowMenu(item.key, item.isProtected, item.checked && replays.checkedCount > 1,
                                               item, theme.em * 2, item.height * 0.8)
                    event.accepted = true
                }
            }

            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }

            // Day (or track) sections, current one kept at top
            section.property: "section"
            section.labelPositioning: ViewSection.InlineLabels | ViewSection.CurrentLabelAtStart
            section.delegate: Rectangle {
                required property string section
                width: ListView.view.width
                height: section !== "" ? Math.round(theme.rowCompact) : 0
                visible: section !== ""
                color: theme.surfaceCard  // sticky over the rows: the card surface they scroll on
                TpSectionLabel {
                    anchors.left: parent.left
                    anchors.leftMargin: theme.space2
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.section
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: theme.border }
            }

            delegate: Item {
                id: row
                required property int index
                required property string key
                required property string track
                required property string code
                required property string session
                required property string sessionLabel
                required property string event
                required property string eventType
                required property string date
                required property string size
                required property string tip
                required property bool checked
                required property bool isProtected
                required property string trackLogo
                required property bool hasResults
                required property bool selected  // role changed for two rows on selection, no binding per row
                readonly property bool watchHovered: watchButton.hovered
                readonly property bool hot: (selected && !root.many) || rowArea.containsMouse || watchHovered
                // Reused row: fed other replay values at once, no color animation from the old replay
                property bool live: true
                ListView.onPooled: { opacity = 1; live = false }  // add transition may have been running
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.rowTall)
                Accessible.role: Accessible.ListItem
                Accessible.name: [row.track, row.sessionLabel, row.date, row.size,
                                  row.isProtected ? i18n.tr("Protected from deletion") : ""]
                                 .filter(function(part) { return part !== "" }).join(", ")
                Accessible.selected: row.checked
                ToolTip.visible: rowArea.containsMouse && !watchHovered && row.tip !== ""
                ToolTip.text: rowArea.containsMouse ? row.tip : ""
                ToolTip.delay: theme.tipDelay

                TpListRow {
                    id: surface
                    anchors.fill: parent
                    animate: row.live
                    hovered: rowArea.containsMouse
                    selected: row.checked
                    border.width: row.selected && root.many ? 1 : 0
                    border.color: theme.accent
                }
                FocusRing {  // keyboard: replay moved to with Up / Down
                    target: surface
                    anchors.margins: 0
                    visible: row.selected && list.activeFocus
                }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: function(mouse) {
                        list.forceActiveFocus()
                        if (mouse.button === Qt.LeftButton) replays.clickReplay(row.key, mouse.modifiers)
                        else if (!row.checked) replays.selectReplay(row.key)
                    }
                    onClicked: function(mouse) {
                        if (mouse.button !== Qt.RightButton) return
                        root.openRowMenu(row.key, row.isProtected, row.checked && root.many, rowArea, mouse.x, mouse.y)
                    }
                    onDoubleClicked: function(mouse) {
                        if (mouse.button === Qt.LeftButton && !(mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)))
                            replays.watchReplay(row.key)
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.5
                    anchors.rightMargin: theme.em * 0.5
                    spacing: theme.space4

                    // Protected from deletion (filled star, gold): click to change (keyboard: row menu)
                    Item {
                        Layout.preferredWidth: theme.em * 1.2
                        Layout.preferredHeight: theme.em * 1.6
                        Icon {
                            anchors.centerIn: parent
                            visible: row.isProtected || starArea.containsMouse || rowArea.containsMouse
                            glyph: row.isProtected ? "" : ""  // star
                            fallback: row.isProtected ? "★" : "☆"
                            size: theme.iconSm
                            color: row.isProtected ? theme.gold : starArea.containsMouse ? theme.text : theme.dimText
                        }
                        MouseArea {
                            id: starArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: replays.toggleProtected(row.key)
                            ToolTip.visible: containsMouse
                            ToolTip.text: !containsMouse ? ""
                                : row.isProtected ? i18n.tr("Protected from deletion & clean up (click: unprotect)")
                                : i18n.tr("Protect From Deletion")
                            ToolTip.delay: theme.tipDelay
                        }
                    }
                    // Session of game name (P1, Q1, R1): one session color for every page
                    ResultsBadge {
                        code: row.code !== "" ? row.code.split(" ")[0] : (row.session.charAt(0) || "?")
                        implicitWidth: Math.round(theme.em * 2.6)
                        implicitHeight: Math.round(theme.controlHeight)
                    }
                    GameLogo {  // circuit logo of game
                        source: row.trackLogo
                        boxWidth: theme.em * 2.6
                        boxHeight: theme.em * 1.7
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            Layout.fillWidth: true
                            text: row.track
                            textFormat: Text.PlainText
                            color: theme.text
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: [row.event, row.eventType, row.sessionLabel].filter(function(part) { return part !== "" }).join("  ·  ")
                            textFormat: Text.PlainText
                            color: theme.dimOn(surface.color)
                            font.pointSize: theme.fontSmall
                            elide: Text.ElideRight
                        }
                    }
                    Icon {  // results file of this session found: shown on the right when picked
                        visible: row.hasResults
                        glyph: ""  // flag
                        fallback: "⚑"
                        size: theme.iconSm
                        color: theme.dimOn(surface.color)
                        ToolTip.visible: resultsArea.containsMouse
                        ToolTip.text: i18n.tr("Results of this session found")
                        ToolTip.delay: theme.tipDelay
                        MouseArea { id: resultsArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                    ColumnLayout {
                        spacing: 1
                        visible: !row.hot || root.roomyRow
                        Text {
                            Layout.alignment: Qt.AlignRight
                            text: row.date
                            textFormat: Text.PlainText
                            color: theme.text
                            font.features: { "tnum": 1 }
                        }
                        Text {
                            Layout.alignment: Qt.AlignRight
                            text: row.size
                            textFormat: Text.PlainText
                            color: theme.dimOn(surface.color)
                            font.pointSize: theme.fontSmall
                            font.features: { "tnum": 1 }
                        }
                    }
                    TpButton {  // watch button shown on the selected or hovered row (kept by pooled rows)
                        id: watchButton
                        visible: row.hot
                        accent: true
                        size: "sm"
                        glyph: ""  // play
                        fallback: "▶"
                        text: root.width > theme.em * 30 ? i18n.tr("Watch") : ""  // content-tuned
                        tip: hovered ? i18n.tr("Open replay in the game (double click)") : ""
                        enabled: root.gameOnline
                        onClicked: replays.watchReplay(row.key)
                        Accessible.name: i18n.tr("Watch")
                    }
                }
            }

            // Empty list: game not answering, no replay saved, nothing matching filter (centered over the list)
            TpStateView {
                id: replayState
                objectName: "replayListState"
                parent: list
                anchors.centerIn: parent
                loading: replays.loading && replays.replayCount === 0  // asking game: never "no replay" while waiting
                empty: list.count === 0
                loadingText: i18n.tr("Asking game…")
                glyph: replays.replayCount > 0 ? "" : ""  // search, video
                title: replays.replayCount > 0 ? i18n.tr("No replay matches the search or filter.")
                     : replays.gameState === "offline" ? i18n.tr("Start LMU to list the replays it saved.")
                     : i18n.tr("No replay saved by the game yet.")
                actionText: replays.replayCount > 0 ? i18n.tr("Clear Filters") : ""
                onAction: {
                    searchField.clearSearch()
                    replays.clearFilters()
                    list.forceActiveFocus()
                }
            }
        }
    }

    // Progress of a file operation: text, bar, percent & stop button
    component FileProgress: Rectangle {
        id: bar
        property string text: ""
        property real progress: 0
        property string stopText: ""
        signal stopped()
        Layout.fillWidth: true
        implicitHeight: Math.round(theme.em * 2.0)
        radius: theme.radiusMd
        color: theme.tint(theme.accent, "subtle")
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: theme.padCard
            anchors.rightMargin: theme.padCard
            spacing: theme.space4
            Text {
                text: bar.text
                textFormat: Text.PlainText
                color: theme.text
                elide: Text.ElideRight
                Layout.maximumWidth: bar.width * 0.45  // bar always shown
            }
            TpMeter {
                Layout.fillWidth: true
                animated: false  // progress steps come faster than the animation
                value: bar.progress
                name: bar.text
            }
            Text {
                text: Math.round(bar.progress * 100) + " %"
                textFormat: Text.PlainText
                color: theme.dimOn(bar.color)
                font.features: { "tnum": 1 }
            }
            TpButton {
                text: bar.stopText
                flat: true
                size: "sm"
                onClicked: bar.stopped()
            }
        }
    }
}
