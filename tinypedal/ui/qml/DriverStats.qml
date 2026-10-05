import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Driver stats viewer page: track selector & actions, key figures, table of vehicles (tracks for All Tracks),
// lap time reference, progression & sessions of selected vehicle (level distribution for All Tracks)
TpPage {
    id: page

    readonly property var reference: backend.reference
    readonly property var progression: backend.progression
    property var menuActions: []
    property string menuKey: ""
    property string menuColumn: ""

    function openRowMenu(key, column, item, x, y) {
        menuKey = key
        menuColumn = column
        menuActions = backend.rowActions(key, column)
        rowMenu.popup(item, x, y)
    }
    function popupBelow(menu, button) {
        menu.visible ? menu.close() : menu.popup(button, 0, button.height + 4)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TrackPicker {
                Layout.preferredWidth: theme.em * 22
                Layout.minimumWidth: theme.em * 12
                Layout.fillWidth: true
                Layout.maximumWidth: theme.em * 28
            }
            TpButton {
                glyph: ""  // map pin
                text: i18n.tr("View Map")
                enabled: !backend.allTracks
                onClicked: backend.openMap()
            }
            TpButton {
                glyph: ""  // area chart
                text: i18n.tr("Telemetry")
                tip: i18n.tr("Recorded laps of selected vehicle class in Lap Telemetry Viewer")
                enabled: backend.hasLaps
                onClicked: backend.openLapViewer()
            }
            TpButton { glyph: ""; tip: i18n.tr("Reload"); onClicked: backend.reload() }  // refresh
            TpButton {
                glyph: ""  // delete
                text: i18n.tr("Delete")
                tip: i18n.tr("Delete all stats of this track")
                enabled: backend.canDelete
                onClicked: backend.deleteTrack("")
            }
            Item { Layout.fillWidth: true }
            TpButton { glyph: ""; tip: i18n.tr("Undo (Ctrl+Z)"); enabled: backend.canUndo; onClicked: backend.undo() }
            TpButton { glyph: ""; tip: i18n.tr("Redo (Ctrl+Y)"); enabled: backend.canRedo; onClicked: backend.redo() }
            TpButton {
                id: exportButton
                glyph: ""  // export
                text: i18n.tr("Export")
                tip: i18n.tr("Export table to CSV file")
                enabled: backend.hasRows
                checked: exportMenu.visible
                onClicked: page.popupBelow(exportMenu, exportButton)
                TpMenu {
                    id: exportMenu
                    Action { text: i18n.tr("Export CSV..."); onTriggered: backend.exportCsv(false) }
                    Action { text: i18n.tr("Export Raw Values (CSV)..."); onTriggered: backend.exportCsv(true) }
                }
            }
            TpButton {
                id: viewButton
                glyph: ""  // view
                text: i18n.tr("View")
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
                    MenuSeparator {}
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
                }
            }
            TpButton {
                id: referenceButton
                glyph: ""  // globe
                text: i18n.tr("Reference")
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
                }
            }
        }

        // Key figures
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: false  // tiles fill row height only (else inherited from them)
            spacing: theme.em * 0.6
            Repeater {
                model: backend.tiles
                InfoCard {
                    id: tile
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true  // same height each, detail line or not
                    Layout.preferredWidth: 1  // same width each
                    title: modelData.title
                    value: modelData.value
                    accentColor: modelData.color ? modelData.color : theme.text
                    lines: [modelData.detail]
                    ToolTip.visible: tileArea.containsMouse && modelData.tip !== ""
                    ToolTip.text: modelData.tip
                    ToolTip.delay: 600
                    MouseArea { id: tileArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: theme.em * 0.6

            // Table
            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: theme.em * 0.6
                    spacing: theme.em * 0.4
                    Text {
                        text: backend.tableTitle
                        color: theme.text
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontPoint * 1.05
                    }
                    StatsTable {
                        id: table
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: backend.hasRows
                        onCellMenu: function(key, column, x, y) { page.openRowMenu(key, column, table, x, y) }
                        onHeaderMenu: function(x, y) { headerMenu.popup(table, x, y) }
                    }
                    Text {
                        visible: !backend.hasRows
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        text: backend.emptyText
                        color: theme.dimText
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            // Side: selected vehicle (level distribution for All Tracks)
            Flickable {
                id: side
                Layout.preferredWidth: theme.em * 25
                Layout.fillHeight: true
                contentHeight: sideColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    id: sideColumn
                    width: side.width
                    spacing: theme.em * 0.6

                    // Lap time reference: level ladder
                    Card {
                        visible: !backend.allTracks
                        Layout.fillWidth: true
                        implicitHeight: referenceColumn.implicitHeight + theme.em * 1.2
                        ColumnLayout {
                            id: referenceColumn
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.6 }
                            spacing: theme.em * 0.3
                            Text { text: i18n.tr("Lap Time Reference"); color: theme.text; font.weight: Font.DemiBold }
                            Text {
                                visible: page.reference.visible === true
                                Layout.fillWidth: true
                                text: "<b>" + (page.reference.vehicle || "") + "</b><br>" + (page.reference.detail || "")
                                textFormat: Text.StyledText
                                color: theme.text
                                wrapMode: Text.WordWrap
                            }
                            Repeater {
                                model: page.reference.visible ? page.reference.ladder : []
                                RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: theme.em * 0.4
                                    Rectangle {
                                        width: theme.em * 0.6
                                        height: width
                                        radius: width / 2
                                        color: modelData.color
                                    }
                                    Text {
                                        text: modelData.name
                                        color: theme.text
                                        font.weight: modelData.active ? Font.DemiBold : Font.Normal
                                        Layout.preferredWidth: theme.em * 8.5
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        text: modelData.limit
                                        color: theme.dimText
                                        font.features: { "tnum": 1 }
                                        Layout.preferredWidth: theme.em * 5.4
                                        horizontalAlignment: Text.AlignRight
                                    }
                                    Text {
                                        text: modelData.marks
                                        color: theme.accent
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }
                            }
                            Text {
                                visible: page.reference.visible === true
                                Layout.fillWidth: true
                                text: page.reference.gap || ""
                                color: theme.text
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                visible: page.reference.visible === true && (page.reference.next || "") !== ""
                                Layout.fillWidth: true
                                text: page.reference.next || ""
                                color: theme.accent
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                visible: page.reference.visible === true && (page.reference.fastest || "") !== ""
                                Layout.fillWidth: true
                                text: page.reference.fastest || ""
                                color: theme.dimText
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                visible: page.reference.visible !== true
                                Layout.fillWidth: true
                                text: page.reference.reason || ""
                                color: theme.dimText
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // Personal best progression
                    Card {
                        visible: !backend.allTracks
                        Layout.fillWidth: true
                        implicitHeight: progressionColumn.implicitHeight + theme.em * 1.2
                        ColumnLayout {
                            id: progressionColumn
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.6 }
                            spacing: theme.em * 0.4
                            Text { text: i18n.tr("Progression"); color: theme.text; font.weight: Font.DemiBold }
                            TpSegmented {
                                options: backend.sessionFilters
                                currentIndex: backend.sessionFilter
                                maxWidth: progressionColumn.width
                                onActivated: function(index) { backend.setSessionFilter(index) }
                            }
                            StatsChart {
                                visible: page.progression.visible === true
                                Layout.fillWidth: true
                                Layout.preferredHeight: theme.em * 11
                                chartData: page.progression
                            }
                            Text {
                                Layout.fillWidth: true
                                text: page.progression.info || ""
                                color: theme.dimText
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // Sessions of selected vehicle, newest first
                    Card {
                        visible: !backend.allTracks && backend.sessions.length > 0
                        Layout.fillWidth: true
                        implicitHeight: sessionsColumn.implicitHeight + theme.em * 1.2
                        ColumnLayout {
                            id: sessionsColumn
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.6 }
                            spacing: theme.em * 0.3
                            Text { text: i18n.tr("Sessions"); color: theme.text; font.weight: Font.DemiBold }
                            ListView {
                                id: sessionList
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.min(contentHeight, theme.em * 15)
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                model: backend.sessions
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                delegate: Item {
                                    id: sessionItem
                                    required property var modelData
                                    width: ListView.view.width
                                    height: theme.em * 1.8
                                    ToolTip.visible: sessionArea.containsMouse
                                    ToolTip.text: modelData.tip
                                    ToolTip.delay: 600
                                    MouseArea { id: sessionArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                                    RowLayout {
                                        anchors.fill: parent
                                        spacing: theme.em * 0.4
                                        Text {
                                            text: sessionItem.modelData.date
                                            color: theme.dimText
                                            font.features: { "tnum": 1 }
                                            Layout.preferredWidth: theme.em * 6.4  // dd/mm/yyyy
                                        }
                                        Text {
                                            text: sessionItem.modelData.session
                                            color: theme.text
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            text: sessionItem.modelData.best
                                            color: sessionItem.modelData.pb ? theme.accent : theme.text
                                            font.weight: sessionItem.modelData.pb ? Font.DemiBold : Font.Normal
                                            font.features: { "tnum": 1 }
                                        }
                                        Text {
                                            text: sessionItem.modelData.laps
                                            color: theme.dimText
                                            font.features: { "tnum": 1 }
                                            Layout.preferredWidth: theme.em * 2.8
                                            horizontalAlignment: Text.AlignRight
                                        }
                                        Text {
                                            text: sessionItem.modelData.result
                                            color: sessionItem.modelData.result === "DNF" || sessionItem.modelData.result === "DQ"
                                                   ? theme.warning : theme.text
                                            font.weight: Font.DemiBold
                                            Layout.preferredWidth: theme.em * 2.4
                                            horizontalAlignment: Text.AlignRight
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Levels of best laps, all tracks & classes
                    Card {
                        visible: backend.allTracks
                        Layout.fillWidth: true
                        implicitHeight: levelsColumn.implicitHeight + theme.em * 1.2
                        ColumnLayout {
                            id: levelsColumn
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.6 }
                            spacing: theme.em * 0.35
                            Text { text: i18n.tr("Levels, All Tracks"); color: theme.text; font.weight: Font.DemiBold }
                            Repeater {
                                model: backend.levels
                                RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: theme.em * 0.4
                                    Rectangle {
                                        width: theme.em * 1.25
                                        height: width
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
                                    Text { text: modelData.name; color: theme.text; Layout.preferredWidth: theme.em * 8 }
                                    Item {
                                        Layout.fillWidth: true
                                        height: theme.em * 0.7
                                        Rectangle {
                                            width: Math.max(parent.width * modelData.ratio, modelData.count ? height : 0)
                                            height: parent.height
                                            radius: height / 2
                                            color: modelData.color
                                            Behavior on width { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                                        }
                                    }
                                    Text {
                                        text: modelData.count
                                        color: theme.text
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
                                wrapMode: Text.WordWrap
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
