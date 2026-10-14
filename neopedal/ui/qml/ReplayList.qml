import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Replays saved by the game: search (every word in track, event, session), session filter, sort,
// sections by day (or track). Click: select (Ctrl: add to selection, Shift: range, Ctrl+A: all),
// double click or Enter: watch in game (after confirmation), Delete: move to recycle bin, right click: menu.
// Add: copy replay files to game folder (also by dropping them on the page).
Item {
    id: root

    readonly property bool searching: searchField.activeFocus
    readonly property var folderInfo: replays.folderInfo  // read once per change (sizes of every file)
    readonly property var sorts: [
        { "key": "date", "text": i18n.tr("Newest First") },
        { "key": "size", "text": i18n.tr("Largest First") },
        { "key": "track", "text": i18n.tr("By Track") },
    ]

    function sessionColor(session) {
        return session === "RACE" ? theme.warning : session === "QUALIFY" ? theme.purple
             : session === "PRACTICE" ? theme.accent : theme.dimText
    }
    function showSelected() {
        var index = replays.replayIndex(replays.selectedReplay)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }
    property string menuKey: ""
    property bool menuMany: false  // row menu on one of several selected replays
    property bool menuProtected: false

    TpMenu {
        id: rowMenu
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
            text: root.menuMany ? i18n.tr("Export %1 Replays...").arg(replays.checkedCount) : i18n.tr("Export Replay...")
            enabled: replays.replayFolder !== "" && !replays.copying
            onTriggered: replays.exportReplays(root.menuKey)
        }
        Action {
            text: i18n.tr("Rename Replay...")
            enabled: replays.replayFolder !== "" && !root.menuMany
            onTriggered: replays.renameReplay(root.menuKey)
        }
        Action {
            text: root.menuProtected ? i18n.tr("Unprotect") : i18n.tr("Protect From Deletion")
            onTriggered: replays.toggleProtected(root.menuKey)
        }
        MenuSeparator {}
        Action {
            text: root.menuMany ? i18n.tr("Delete %1 Replays...").arg(replays.checkedCount) : i18n.tr("Delete Replay...")
            enabled: replays.replayFolder !== "" && (root.menuMany || !root.menuProtected)
            onTriggered: replays.deleteReplays(root.menuKey)
        }
    }

    // Folder clean up & selected replays
    TpMenu {
        id: moreMenu
        Action {
            text: replays.checkedCount > 1 ? i18n.tr("Export %1 Replays...").arg(replays.checkedCount) : i18n.tr("Export Replay...")
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
            text: i18n.tr("Delete Replays Older Than...")
            enabled: replays.replayFolder !== "" && replays.replayCount > 0
            onTriggered: replays.deleteOlderThan()
        }
        Action {
            text: i18n.tr("Keep Only Latest Replays...")
            enabled: replays.replayFolder !== "" && replays.replayCount > 0
            onTriggered: replays.keepLatest()
        }
        Action {
            text: i18n.tr("Delete Temporary Files (%1, %2)").arg(root.folderInfo.temp).arg(root.folderInfo.tempSize)
            enabled: replays.replayFolder !== "" && root.folderInfo.temp > 0
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
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.5

        // Title, count & size, sort
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Icon { glyph: ""; color: theme.accent }  // video
            Text {
                text: i18n.tr("Replays")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontSubtitle
            }
            Rectangle {
                visible: replays.replayCount > 0
                implicitHeight: summaryText.implicitHeight + theme.em * 0.3
                implicitWidth: summaryText.implicitWidth + theme.em * 1.0
                radius: height / 2
                color: theme.hover
                Text {
                    id: summaryText
                    anchors.centerIn: parent
                    text: replays.replaysSummary
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                }
            }
            Item { Layout.fillWidth: true }
            TpButton {
                glyph: ""  // add
                text: root.width > theme.em * 36 ? i18n.tr("Add") : ""
                tip: replays.replayFolder !== "" ? i18n.tr("Add replay files (.Vcr) to the game replay folder, or drop them on the page")
                                                 : i18n.tr("Replay folder unknown: start LMU once so the page lists its replays.")
                enabled: replays.replayFolder !== "" && !replays.copying
                flat: true
                onClicked: replays.addReplays()
            }
            TpButton {
                glyph: ""  // delete
                tip: (replays.checkedCount > 1 ? i18n.tr("Move selected replays to the recycle bin")
                                               : i18n.tr("Move replay to the recycle bin")) + " (" + i18n.tr("Delete") + ")"
                enabled: replays.replayFolder !== "" && replays.selectedReplay !== ""
                flat: true
                onClicked: replays.deleteReplays(replays.selectedReplay)
            }
            TpButton {
                id: moreButton
                glyph: ""  // more
                tip: i18n.tr("Export, protect, clean up the replay folder")
                flat: true
                checked: moreMenu.visible
                onClicked: moreMenu.visible ? moreMenu.close() : moreMenu.popup(moreButton, 0, moreButton.height + 4)
            }
            TpButton {
                id: sortButton
                glyph: ""  // sort
                text: root.width > theme.em * 30 ? root.sorts.find(function(sort) { return sort.key === replays.sortKey }).text : ""
                tip: i18n.tr("Sort")
                flat: true
                checked: sortMenu.visible
                onClicked: sortMenu.visible ? sortMenu.close() : sortMenu.popup(sortButton, 0, sortButton.height + 4)
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

        // Replays being copied to game folder
        Rectangle {
            Layout.fillWidth: true
            visible: replays.copying
            implicitHeight: Math.round(theme.em * 2.0)
            radius: theme.radiusMd
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.1)
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: theme.em * 0.7
                anchors.rightMargin: theme.em * 0.7
                spacing: theme.em * 0.6
                Text { text: replays.copyKind === "export" ? i18n.tr("Exporting replays...") : i18n.tr("Copying replays..."); color: theme.text }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Math.round(theme.em * 0.35)
                    radius: height / 2
                    color: theme.hover
                    Rectangle {
                        width: parent.width * replays.copyProgress
                        height: parent.height
                        radius: parent.radius
                        color: theme.accent
                        Behavior on width { NumberAnimation { duration: theme.motionBase } }
                    }
                }
                Text {
                    text: Math.round(replays.copyProgress * 100) + " %"
                    color: theme.dimText
                    font.features: { "tnum": 1 }
                }
                TpButton {
                    text: i18n.tr("Stop Copy")
                    flat: true
                    implicitHeight: Math.round(theme.em * 1.7)
                    onClicked: replays.cancelCopy()
                }
            }
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
                placeholderText: i18n.tr("Search replays: track, event...")
                onSearchChanged: function(text) { replays.setSearch(text) }
                onExitField: list.forceActiveFocus()
                Keys.onEscapePressed: { clearSearch(); list.forceActiveFocus() }
                Keys.onReturnPressed: list.forceActiveFocus()
                Keys.onEnterPressed: list.forceActiveFocus()
            }
            TpSegmented {
                options: [i18n.tr("All"), i18n.tr("Practice"), i18n.tr("Qualify"), i18n.tr("Race")]
                currentIndex: replays.sessionFilter
                maxWidth: root.width * 0.58
                onActivated: function(index) { replays.setSessionFilter(index) }
            }
        }

        // Several replays selected
        Rectangle {
            Layout.fillWidth: true
            visible: replays.checkedCount > 1
            implicitHeight: Math.round(theme.em * 2.3)
            radius: theme.radiusMd
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.12)
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: theme.em * 0.7
                anchors.rightMargin: theme.em * 0.3
                spacing: theme.em * 0.4
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Selected") + "  " + replays.checkedSummary
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.features: { "tnum": 1 }
                    elide: Text.ElideRight
                }
                TpButton {
                    glyph: ""  // delete
                    text: i18n.tr("Delete")
                    flat: true
                    implicitHeight: Math.round(theme.em * 1.9)
                    onClicked: replays.deleteReplays(replays.selectedReplay)
                }
                TpButton {
                    glyph: ""  // cancel
                    flat: true
                    tip: i18n.tr("Clear selection (Escape)")
                    implicitHeight: Math.round(theme.em * 1.9)
                    onClicked: replays.selectReplay(replays.selectedReplay)
                }
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            focus: true
            activeFocusOnTab: true
            model: replays.replayRows
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true  // rows scrolled out fed again with other replays (see delegate onPooled)
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: { replays.moveReplaySelection(-1); root.showSelected() }
            Keys.onDownPressed: { replays.moveReplaySelection(1); root.showSelected() }
            Keys.onReturnPressed: replays.watchReplay(replays.selectedReplay)
            Keys.onEnterPressed: replays.watchReplay(replays.selectedReplay)
            Keys.onDeletePressed: replays.deleteReplays(replays.selectedReplay)
            Keys.onEscapePressed: replays.selectReplay(replays.selectedReplay)
            Keys.onPressed: function(event) {
                if (event.matches(StandardKey.SelectAll)) { replays.selectAllReplays(); event.accepted = true }
            }

            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }

            // Day (or track) sections, current one kept at top
            section.property: "section"
            section.labelPositioning: ViewSection.InlineLabels | ViewSection.CurrentLabelAtStart
            section.delegate: Rectangle {
                required property string section
                width: ListView.view.width
                height: section !== "" ? Math.round(theme.em * 2.1) : 0
                visible: section !== ""
                color: theme.base
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: theme.em * 0.3
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.section
                    color: theme.dimText
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontLabel
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: theme.border; opacity: 0.6 }
            }

            delegate: Rectangle {
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
                readonly property bool selected: key === replays.selectedReplay
                readonly property color tone: root.sessionColor(session)
                readonly property bool watchHovered: watchLoader.item !== null && watchLoader.item.hovered
                readonly property bool hot: (selected && replays.checkedCount <= 1) || rowArea.containsMouse || watchHovered
                // Reused row: fed other replay values at once, no color animation from the old replay
                property bool live: true
                ListView.onPooled: { live = false; opacity = 1 }  // add transition may have been running
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 3.4)
                radius: theme.radiusMd
                color: theme.rowColor(rowArea.containsMouse, checked)
                border.width: selected && replays.checkedCount > 1 ? 1 : 0
                border.color: theme.accent
                Behavior on color { enabled: row.live; ColorAnimation { duration: theme.motionFast } }
                ToolTip.visible: rowArea.containsMouse && !watchHovered && row.tip !== ""
                ToolTip.text: rowArea.containsMouse ? row.tip : ""
                ToolTip.delay: theme.tipDelay

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: function(mouse) {
                        list.forceActiveFocus()
                        if (mouse.button === Qt.LeftButton) replays.clickReplay(row.key, mouse.modifiers)
                        else if (!row.checked) replays.selectReplay(row.key)
                    }
                    onClicked: function(mouse) {
                        if (mouse.button !== Qt.RightButton) return
                        root.menuKey = row.key
                        root.menuProtected = row.isProtected
                        root.menuMany = row.checked && replays.checkedCount > 1
                        rowMenu.popup(rowArea, mouse.x, mouse.y)
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
                    spacing: theme.em * 0.6

                    // Protected from deletion: click to change
                    Item {
                        Layout.preferredWidth: theme.em * 1.2
                        Layout.preferredHeight: theme.em * 1.6
                        Icon {
                            anchors.centerIn: parent
                            visible: row.isProtected || starArea.containsMouse || (rowArea.containsMouse && theme.iconFont !== "")
                            glyph: row.isProtected ? "" : ""  // star
                            size: theme.em * 0.85
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
                    // Session of game name (P1, Q1, R1), session color
                    Rectangle {
                        Layout.preferredWidth: Math.round(theme.em * 2.6)
                        Layout.preferredHeight: Math.round(theme.em * 2.3)
                        radius: theme.radiusMd
                        color: Qt.rgba(row.tone.r, row.tone.g, row.tone.b, theme.dark ? 0.2 : 0.14)
                        Text {
                            anchors.centerIn: parent
                            text: row.code !== "" ? row.code.split(" ")[0] : (row.session.charAt(0) || "?")
                            color: row.tone
                            font.weight: Font.Bold
                            font.pointSize: theme.fontLabel
                        }
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
                            color: theme.text
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: [row.event, row.eventType, row.sessionLabel].filter(function(part) { return part !== "" }).join("  ·  ")
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            elide: Text.ElideRight
                        }
                    }
                    Icon {  // results file of this session found: shown on the right when picked
                        visible: row.hasResults
                        glyph: ""  // flag
                        size: theme.em * 0.85
                        color: theme.dimText
                        ToolTip.visible: resultsArea.containsMouse
                        ToolTip.text: i18n.tr("Results of this session found")
                        ToolTip.delay: theme.tipDelay
                        MouseArea { id: resultsArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                    ColumnLayout {
                        spacing: 1
                        visible: !watchLoader.active || root.width > theme.em * 34
                        Text {
                            Layout.alignment: Qt.AlignRight
                            text: row.date
                            color: theme.text
                            font.features: { "tnum": 1 }
                        }
                        Text {
                            Layout.alignment: Qt.AlignRight
                            text: row.size
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            font.features: { "tnum": 1 }
                        }
                    }
                    Loader {  // watch button made only for the selected or hovered row
                        id: watchLoader
                        active: row.hot
                        visible: active
                        sourceComponent: TpButton {
                            accent: true
                            glyph: ""  // play
                            text: root.width > theme.em * 30 ? i18n.tr("Watch") : ""
                            tip: hovered ? i18n.tr("Open replay in the game (double click)") : ""
                            enabled: replays.gameState !== "offline"
                            implicitHeight: Math.round(theme.em * 2.1)
                            onClicked: replays.watchReplay(row.key)
                        }
                    }
                }
            }

            // Empty list: game not answering, no replay saved, nothing matching filter
            Column {
                anchors.centerIn: parent
                width: parent.width - theme.em * 4
                visible: list.count === 0
                spacing: theme.em * 0.7
                Icon {
                    id: emptyIcon
                    anchors.horizontalCenter: parent.horizontalCenter
                    glyph: replays.loading ? "" : replays.replayCount > 0 ? "" : ""
                    size: theme.em * 2.6
                    color: theme.dimText
                    RotationAnimation on rotation {  // asking game: refresh icon turns
                        running: replays.loading && replays.replayCount === 0 && pageState.active && theme.animate
                        from: 0; to: 360; duration: 1000; loops: Animation.Infinite
                        onRunningChanged: if (!running) emptyIcon.rotation = 0
                    }
                }
                Text {
                    width: parent.width
                    text: replays.loading && replays.replayCount === 0 ? i18n.tr("Asking game...")
                        : replays.replayCount > 0 ? i18n.tr("No replay matches the search or filter.")
                        : replays.gameState === "offline" ? i18n.tr("Start LMU to list the replays it saved.")
                        : i18n.tr("No replay saved by the game yet.")
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
