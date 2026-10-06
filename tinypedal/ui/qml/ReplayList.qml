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
        var index = backend.replayIndex(backend.selectedReplay)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }
    property string menuKey: ""
    property bool menuMany: false  // row menu on one of several selected replays
    property bool menuProtected: false

    TpMenu {
        id: rowMenu
        Action {
            text: i18n.tr("Watch in Game")
            enabled: backend.gameState !== "offline" && !root.menuMany
            onTriggered: backend.watchReplay(root.menuKey)
        }
        Action {
            text: i18n.tr("Show in Folder")
            enabled: backend.replayFolder !== "" && !root.menuMany
            onTriggered: backend.showInFolder(root.menuKey)
        }
        Action {
            text: root.menuMany ? i18n.tr("Export %1 Replays...").arg(backend.checkedCount) : i18n.tr("Export Replay...")
            enabled: backend.replayFolder !== "" && !backend.copying
            onTriggered: backend.exportReplays(root.menuKey)
        }
        Action {
            text: i18n.tr("Rename Replay...")
            enabled: backend.replayFolder !== "" && !root.menuMany
            onTriggered: backend.renameReplay(root.menuKey)
        }
        Action {
            text: root.menuProtected ? i18n.tr("Unprotect") : i18n.tr("Protect From Deletion")
            onTriggered: backend.toggleProtected(root.menuKey)
        }
        MenuSeparator {}
        Action {
            text: root.menuMany ? i18n.tr("Delete %1 Replays...").arg(backend.checkedCount) : i18n.tr("Delete Replay...")
            enabled: backend.replayFolder !== "" && (root.menuMany || !root.menuProtected)
            onTriggered: backend.deleteReplays(root.menuKey)
        }
    }

    // Folder clean up & selected replays
    TpMenu {
        id: moreMenu
        Action {
            text: backend.checkedCount > 1 ? i18n.tr("Export %1 Replays...").arg(backend.checkedCount) : i18n.tr("Export Replay...")
            enabled: backend.replayFolder !== "" && backend.selectedReplay !== "" && !backend.copying
            onTriggered: backend.exportReplays(backend.selectedReplay)
        }
        Action {
            text: backend.selectedProtected ? i18n.tr("Unprotect") : i18n.tr("Protect From Deletion")
            enabled: backend.selectedReplay !== ""
            onTriggered: backend.toggleProtected(backend.selectedReplay)
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("Delete Replays Older Than...")
            enabled: backend.replayFolder !== "" && backend.replayCount > 0
            onTriggered: backend.deleteOlderThan()
        }
        Action {
            text: i18n.tr("Keep Only Latest Replays...")
            enabled: backend.replayFolder !== "" && backend.replayCount > 0
            onTriggered: backend.keepLatest()
        }
        Action {
            text: i18n.tr("Delete Temporary Files (%1, %2)").arg(backend.folderInfo.temp).arg(backend.folderInfo.tempSize)
            enabled: backend.replayFolder !== "" && backend.folderInfo.temp > 0
            onTriggered: backend.deleteTempFiles()
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("%1 replays, %2, %3 protected").arg(backend.folderInfo.replays).arg(backend.folderInfo.size)
                  .arg(backend.folderInfo.protected)
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
                font.pointSize: theme.fontPoint * 1.1
            }
            Rectangle {
                visible: backend.replayCount > 0
                implicitHeight: summaryText.implicitHeight + theme.em * 0.3
                implicitWidth: summaryText.implicitWidth + theme.em * 1.0
                radius: height / 2
                color: theme.hover
                Text {
                    id: summaryText
                    anchors.centerIn: parent
                    text: backend.replaysSummary
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.85
                    font.features: { "tnum": 1 }
                }
            }
            Item { Layout.fillWidth: true }
            TpButton {
                glyph: ""  // add
                text: root.width > theme.em * 36 ? i18n.tr("Add") : ""
                tip: backend.replayFolder !== "" ? i18n.tr("Add replay files (.Vcr) to the game replay folder, or drop them on the page")
                                                 : i18n.tr("Replay folder unknown: start LMU once so the page lists its replays.")
                enabled: backend.replayFolder !== "" && !backend.copying
                flat: true
                onClicked: backend.addReplays()
            }
            TpButton {
                glyph: ""  // delete
                tip: (backend.checkedCount > 1 ? i18n.tr("Move selected replays to the recycle bin")
                                               : i18n.tr("Move replay to the recycle bin")) + " (" + i18n.tr("Delete") + ")"
                enabled: backend.replayFolder !== "" && backend.selectedReplay !== ""
                flat: true
                onClicked: backend.deleteReplays(backend.selectedReplay)
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
                text: root.width > theme.em * 30 ? root.sorts.find(function(sort) { return sort.key === backend.sortKey }).text : ""
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
                            checked: backend.sortKey === modelData.key
                            onTriggered: backend.setSort(modelData.key)
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
            visible: backend.copying
            implicitHeight: Math.round(theme.em * 2.0)
            radius: theme.em * 0.5
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.1)
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: theme.em * 0.7
                anchors.rightMargin: theme.em * 0.7
                spacing: theme.em * 0.6
                Text { text: backend.copyKind === "export" ? i18n.tr("Exporting replays...") : i18n.tr("Copying replays..."); color: theme.text }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Math.round(theme.em * 0.35)
                    radius: height / 2
                    color: theme.hover
                    Rectangle {
                        width: parent.width * backend.copyProgress
                        height: parent.height
                        radius: parent.radius
                        color: theme.accent
                        Behavior on width { NumberAnimation { duration: 150 } }
                    }
                }
                Text {
                    text: Math.round(backend.copyProgress * 100) + " %"
                    color: theme.dimText
                    font.features: { "tnum": 1 }
                }
                TpButton {
                    text: i18n.tr("Stop Copy")
                    flat: true
                    implicitHeight: Math.round(theme.em * 1.7)
                    onClicked: backend.cancelCopy()
                }
            }
        }

        // Search & session filter
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TextField {
                id: searchField
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                implicitHeight: Math.round(theme.em * 2.3)
                leftPadding: theme.em * 2
                rightPadding: theme.em * 2
                placeholderText: i18n.tr("Search replays: track, event...")
                color: theme.text
                placeholderTextColor: theme.dimText
                onTextEdited: searchTimer.restart()
                Keys.onEscapePressed: { text = ""; backend.setSearch(""); list.forceActiveFocus() }
                Keys.onReturnPressed: { backend.setSearch(text); list.forceActiveFocus() }
                Keys.onEnterPressed: { backend.setSearch(text); list.forceActiveFocus() }
                Keys.onDownPressed: list.forceActiveFocus()
                Timer { id: searchTimer; interval: 200; onTriggered: backend.setSearch(searchField.text) }
                background: Rectangle {
                    radius: theme.em * 0.5
                    color: theme.base
                    border.width: 1
                    border.color: searchField.activeFocus ? theme.accent : theme.border
                    Behavior on border.color { ColorAnimation { duration: 120 } }
                }
                Icon {
                    anchors.left: parent.left
                    anchors.leftMargin: theme.em * 0.65
                    anchors.verticalCenter: parent.verticalCenter
                    glyph: ""  // search
                    size: theme.em * 0.85
                    color: theme.dimText
                }
                Text {
                    visible: searchField.text !== ""
                    anchors.right: parent.right
                    anchors.rightMargin: theme.em * 0.7
                    anchors.verticalCenter: parent.verticalCenter
                    text: "×"
                    color: clearArea.containsMouse ? theme.text : theme.dimText
                    font.weight: Font.Bold
                    MouseArea {
                        id: clearArea
                        anchors.fill: parent
                        anchors.margins: -4
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { searchField.text = ""; backend.setSearch("") }
                    }
                }
            }
            TpSegmented {
                options: [i18n.tr("All"), i18n.tr("Practice"), i18n.tr("Qualify"), i18n.tr("Race")]
                currentIndex: backend.sessionFilter
                maxWidth: root.width * 0.58
                onActivated: function(index) { backend.setSessionFilter(index) }
            }
        }

        // Several replays selected
        Rectangle {
            Layout.fillWidth: true
            visible: backend.checkedCount > 1
            implicitHeight: Math.round(theme.em * 2.3)
            radius: theme.em * 0.5
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.12)
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: theme.em * 0.7
                anchors.rightMargin: theme.em * 0.3
                spacing: theme.em * 0.4
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Selected") + "  " + backend.checkedSummary
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
                    onClicked: backend.deleteReplays(backend.selectedReplay)
                }
                TpButton {
                    glyph: ""  // cancel
                    flat: true
                    tip: i18n.tr("Clear selection (Escape)")
                    implicitHeight: Math.round(theme.em * 1.9)
                    onClicked: backend.selectReplay(backend.selectedReplay)
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
            model: backend.replayRows
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: { backend.moveReplaySelection(-1); root.showSelected() }
            Keys.onDownPressed: { backend.moveReplaySelection(1); root.showSelected() }
            Keys.onReturnPressed: backend.watchReplay(backend.selectedReplay)
            Keys.onEnterPressed: backend.watchReplay(backend.selectedReplay)
            Keys.onDeletePressed: backend.deleteReplays(backend.selectedReplay)
            Keys.onEscapePressed: backend.selectReplay(backend.selectedReplay)
            Keys.onPressed: function(event) {
                if (event.matches(StandardKey.SelectAll)) { backend.selectAllReplays(); event.accepted = true }
            }

            displaced: Transition { NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic } }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 180 } }

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
                    font.pointSize: theme.fontPoint * 0.9
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
                readonly property bool selected: key === backend.selectedReplay
                readonly property color tone: root.sessionColor(session)
                readonly property bool hot: (selected && backend.checkedCount <= 1) || rowArea.containsMouse || watchButton.hovered

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 3.4)
                radius: theme.em * 0.5
                color: checked ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, rowArea.containsMouse ? 0.22 : 0.15)
                     : rowArea.containsMouse ? theme.hover : "transparent"
                border.width: selected && backend.checkedCount > 1 ? 1 : 0
                border.color: theme.accent
                Behavior on color { ColorAnimation { duration: 110 } }
                ToolTip.visible: rowArea.containsMouse && !watchButton.hovered && row.tip !== ""
                ToolTip.text: row.tip
                ToolTip.delay: 900

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: function(mouse) {
                        list.forceActiveFocus()
                        if (mouse.button === Qt.LeftButton) backend.clickReplay(row.key, mouse.modifiers)
                        else if (!row.checked) backend.selectReplay(row.key)
                    }
                    onClicked: function(mouse) {
                        if (mouse.button !== Qt.RightButton) return
                        root.menuKey = row.key
                        root.menuProtected = row.isProtected
                        root.menuMany = row.checked && backend.checkedCount > 1
                        rowMenu.popup(rowArea, mouse.x, mouse.y)
                    }
                    onDoubleClicked: function(mouse) {
                        if (mouse.button === Qt.LeftButton && !(mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)))
                            backend.watchReplay(row.key)
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.45
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
                            onClicked: backend.toggleProtected(row.key)
                            ToolTip.visible: containsMouse
                            ToolTip.text: row.isProtected ? i18n.tr("Protected from deletion & clean up (click: unprotect)")
                                                        : i18n.tr("Protect From Deletion")
                            ToolTip.delay: 500
                        }
                    }
                    // Session of game name (P1, Q1, R1), session color
                    Rectangle {
                        Layout.preferredWidth: Math.round(theme.em * 2.6)
                        Layout.preferredHeight: Math.round(theme.em * 2.3)
                        radius: theme.em * 0.45
                        color: Qt.rgba(row.tone.r, row.tone.g, row.tone.b, theme.dark ? 0.2 : 0.14)
                        Text {
                            anchors.centerIn: parent
                            text: row.code !== "" ? row.code.split(" ")[0] : (row.session.charAt(0) || "?")
                            color: row.tone
                            font.weight: Font.Bold
                            font.pointSize: theme.fontPoint * 0.95
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
                            font.pointSize: theme.fontPoint * 0.88
                            elide: Text.ElideRight
                        }
                    }
                    ColumnLayout {
                        spacing: 1
                        visible: !watchButton.visible || root.width > theme.em * 34
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
                            font.pointSize: theme.fontPoint * 0.88
                            font.features: { "tnum": 1 }
                        }
                    }
                    TpButton {
                        id: watchButton
                        visible: row.hot
                        accent: true
                        glyph: ""  // play
                        text: root.width > theme.em * 30 ? i18n.tr("Watch") : ""
                        tip: i18n.tr("Open replay in the game (double click)")
                        enabled: backend.gameState !== "offline"
                        implicitHeight: Math.round(theme.em * 2.1)
                        onClicked: backend.watchReplay(row.key)
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
                    glyph: backend.loading ? "" : backend.replayCount > 0 ? "" : ""
                    size: theme.em * 2.6
                    color: theme.dimText
                    RotationAnimation on rotation {  // asking game: refresh icon turns
                        running: backend.loading && backend.replayCount === 0
                        from: 0; to: 360; duration: 1000; loops: Animation.Infinite
                        onRunningChanged: if (!running) emptyIcon.rotation = 0
                    }
                }
                Text {
                    width: parent.width
                    text: backend.loading && backend.replayCount === 0 ? i18n.tr("Asking game...")
                        : backend.replayCount > 0 ? i18n.tr("No replay matches the search or filter.")
                        : backend.gameState === "offline" ? i18n.tr("Start LMU to list the replays it saved.")
                        : i18n.tr("No replay saved by the game yet.")
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
