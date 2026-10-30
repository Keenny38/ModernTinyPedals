import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Imported laps library of the lap viewer (backend.library): laps imported from MoTeC logs & other drivers'
// folders, grouped by log. Search every word (log, lap, time, track, vehicle, driver, import date), select
// (Ctrl / Shift+click, Ctrl+A), add to viewer (double-click, Enter), import MoTeC logs, rename a log, move laps
// to the lap viewer trash (same undo & Recently Deleted as recorded laps).
// Keys: arrows move, Space selects, Ctrl+Space adds to selection, ← → collapse / expand a log, Enter adds to
// viewer, F2 renames, Delete moves to trash, Esc closes (Ctrl+Z restores: page shortcut, lap_viewer.py).
TpPopup {
    id: popup

    readonly property var library: backend.library
    readonly property bool wide: width >= theme.em * 48  // content-tuned: vehicle, driver & date columns
    signal keysBack()  // closed: keys back to the page

    // Detail column of a row (width in em)
    component LibraryCell: Text {
        property real columns: 8
        Layout.preferredWidth: theme.em * columns
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontSmall
        elide: Text.ElideRight
    }

    parent: Overlay.overlay  // centered on page, wherever it is declared
    modal: true
    dismissOnOutside: false  // search text kept: only Esc or the close button close it
    width: Math.min((parent ? parent.width : theme.em * 60) - theme.em * 4, theme.em * 64)
    height: Math.min((parent ? parent.height : theme.em * 40) - theme.em * 4, theme.em * 36)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    onAboutToShow: library.open()
    onOpened: list.forceActiveFocus()
    onClosed: { library.closed(); keysBack() }

    Connections {
        target: popup.library
        function onOpenRequested() { popup.open() }
        function onSearchReset() { search.text = "" }
    }
    Connections {  // laps of the library moved to trash: named, undo at hand (page toast is under the scrim)
        target: backend
        enabled: popup.visible
        function onLapsTrashed(count, label) {
            toast.text = count === 1 && label !== "" ? i18n.tr("%1 moved to trash").arg(label)
                                                     : i18n.tr("%1 laps moved to trash").arg(count)
            toast.show()
        }
    }

    function addAndClose() {
        if (library.selectedCount === 0) return
        library.addSelected()
        close()
    }
    function startRename() {
        if (library.renameTarget === "" || library.writing) return
        renameDialog.source = library.renameTarget
        nameField.text = renameDialog.source
        renameDialog.error = ""
        renameDialog.open()
        nameField.selectAll()
        nameField.forceActiveFocus()
    }
    function selectRow(rowId, modifiers) {
        library.select(rowId, (modifiers & Qt.ShiftModifier) ? "range" : (modifiers & Qt.ControlModifier) ? "toggle" : "set")
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.space3

        TpCardHeader {
            level: "popup"
            glyph: theme.glyphs["import"]
            fallback: "+"
            title: i18n.tr("Imported Laps")
            tip: i18n.tr("Laps imported from MoTeC logs: add to viewer, rename, delete")
            busy: popup.library.loading || popup.library.writing || popup.library.importing
            closable: true
            onClosed: popup.close()
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpSearchField {
                id: search
                objectName: "librarySearch"
                Layout.fillWidth: true
                placeholderText: i18n.tr("Search track, car, driver or log…")
                onSearchChanged: function(text) { popup.library.setSearch(text) }
                onExitField: list.forceActiveFocus()
            }
            TpButton {
                objectName: "libraryImport"
                glyph: theme.glyphs["import"]
                fallback: "+"
                text: popup.library.importing ? i18n.tr("Importing…") : i18n.tr("Import MoTeC…")
                tip: i18n.tr("Import complete laps of MoTeC logs (.ld), also by dropping them on the app")
                enabled: !popup.library.importing
                onClicked: popup.library.importLogs()
            }
        }

        // Last error (import, rename, delete): kept until dismissed
        TpNotice {
            objectName: "libraryProblem"
            Layout.fillWidth: true
            visible: popup.library.problem !== ""
            tone: theme.loss
            text: popup.library.problem
            actionText: i18n.tr("Close")
            onAction: popup.library.clearProblem()
        }

        // Column titles
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: theme.space4
            Layout.rightMargin: theme.space4
            spacing: theme.space4
            Repeater {
                model: [[i18n.tr("Name"), 0], [i18n.tr("Time"), 5.5], [i18n.tr("Track"), 8], [i18n.tr("Car"), 9],
                        [i18n.tr("Driver"), 7], [i18n.tr("Imported"), 8.5]]
                Text {
                    required property var modelData
                    required property int index
                    visible: index < 3 || popup.wide
                    text: modelData[0]
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    Layout.fillWidth: modelData[1] === 0
                    Layout.preferredWidth: modelData[1] === 0 ? -1 : theme.em * modelData[1]
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ListView {
                id: list
                objectName: "libraryList"
                anchors.fill: parent
                clip: true
                model: popup.library.model
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                activeFocusOnTab: true
                keyNavigationEnabled: true
                highlightMoveDuration: 0
                Keys.onPressed: function(event) {
                    var row = list.currentItem
                    var control = (event.modifiers & Qt.ControlModifier) !== 0
                    if (event.key === Qt.Key_A && control) popup.library.selectAll()
                    else if (event.key === Qt.Key_Delete) popup.library.deleteSelected()
                    else if (event.key === Qt.Key_F2) popup.startRename()
                    else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                        if (popup.library.selectedCount === 0 && row) popup.library.select(row.rowId, "set")
                        popup.addAndClose()
                    } else if (event.key === Qt.Key_Space && row) popup.library.select(row.rowId, control ? "toggle" : "set")
                    else if ((event.key === Qt.Key_Left || event.key === Qt.Key_Right) && row && row.isGroup
                             && row.opened !== (event.key === Qt.Key_Right)) popup.library.toggleGroup(row.group)
                    else return
                    event.accepted = true
                }
                delegate: Item {
                    id: row
                    required property int index
                    required property string key
                    required property string kind
                    required property string group
                    required property string title
                    required property string time
                    required property bool best
                    required property string track
                    required property string vehicle
                    required property string driver
                    required property string imported
                    required property int count
                    required property bool open
                    required property bool selected
                    readonly property string rowId: key
                    readonly property bool isGroup: kind === "group"
                    readonly property bool opened: open
                    width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.rowTall)
                    Accessible.role: Accessible.ListItem
                    Accessible.name: title + " " + time
                    Accessible.selectable: true
                    Accessible.selected: selected

                    TpListRow {
                        anchors.fill: parent
                        anchors.topMargin: 1
                        anchors.bottomMargin: 1
                        hovered: rowArea.containsMouse
                        pressed: rowArea.pressed
                        selected: row.selected
                        FocusRing { visible: row.ListView.isCurrentItem && list.activeFocus }
                    }
                    MouseArea {
                        id: rowArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        // Narrow panel: columns left out told by the tooltip
                        ToolTip.visible: containsMouse && !popup.wide && ToolTip.text !== ""
                        ToolTip.text: !popup.wide && containsMouse
                                      ? [row.vehicle, row.driver, row.imported].filter(Boolean).join(" · ") : ""
                        ToolTip.delay: theme.tipDelay
                        onClicked: function(mouse) {
                            list.currentIndex = row.index
                            list.forceActiveFocus()
                            if (mouse.button === Qt.RightButton) {
                                if (!row.selected) popup.library.select(row.rowId, "set")
                                rowMenu.popup(rowArea, mouse.x, mouse.y)
                            } else {
                                popup.selectRow(row.rowId, mouse.modifiers)
                            }
                        }
                        onDoubleClicked: function(mouse) {
                            if (mouse.button !== Qt.LeftButton) return
                            popup.library.addRow(row.rowId)
                            popup.close()
                        }
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.space4
                        anchors.rightMargin: theme.space4
                        spacing: theme.space4
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.space2
                            // Log: chevron (click expands or collapses), lap: indented under its log
                            TpButton {
                                visible: row.isGroup
                                glyph: ""  // chevron right
                                fallback: row.open ? "▾" : "›"
                                flat: true
                                size: "xs"
                                tip: row.open ? i18n.tr("Collapse") : i18n.tr("Expand")
                                rotation: row.open && theme.iconFont !== "" ? 90 : 0
                                onClicked: popup.library.toggleGroup(row.group)
                            }
                            Item { visible: !row.isGroup; implicitWidth: theme.controlHeightXs }
                            Text {
                                text: row.title
                                textFormat: Text.PlainText
                                color: theme.text
                                font.weight: row.isGroup ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            TpCountBadge {  // laps of log
                                visible: row.isGroup
                                text: row.count
                            }
                        }
                        // Best lap of its log: ◆ purple right of the time (shared record mark, never color alone)
                        TpLapTime {
                            Layout.preferredWidth: theme.em * 5.5
                            Layout.preferredHeight: implicitHeight
                            text: row.time
                            record: row.best ? "session" : ""
                            textColor: row.isGroup ? theme.dimText : theme.text
                            horizontalAlignment: Text.AlignLeft
                        }
                        // Track, then vehicle, driver & import date when wide enough (searched, row tooltip else)
                        LibraryCell { columns: 8; text: row.track }
                        LibraryCell { columns: 9; text: row.vehicle; visible: popup.wide }
                        LibraryCell { columns: 7; text: row.driver; visible: popup.wide }
                        LibraryCell { columns: 8.5; text: row.imported; visible: popup.wide }
                    }
                }
            }
            TpStateView {
                objectName: "libraryState"
                anchors.centerIn: parent
                loading: popup.library.loading && list.count === 0
                empty: !popup.library.loading && (popup.library.empty || popup.library.noMatch)
                loadingText: i18n.tr("Reading laps…")
                glyph: theme.glyphs.openFile
                title: popup.library.noMatch ? i18n.tr("No lap matches the search") : i18n.tr("No imported lap")
                text: popup.library.noMatch ? ""
                    : i18n.tr("Import a MoTeC log (.ld), or drop it on the app.")
                actionText: popup.library.noMatch ? i18n.tr("Clear Search") : i18n.tr("Import MoTeC…")
                onAction: popup.library.noMatch ? search.clearSearch() : popup.library.importLogs()
            }
        }

        // Actions on selection, trash (same as lap list: undo, recently deleted laps)
        Flow {
            Layout.fillWidth: true
            spacing: theme.space3
            TpButton {
                objectName: "libraryAdd"
                accent: true
                text: i18n.tr("Add to Viewer")
                tip: i18n.tr("Show selected laps in lap viewer (double-click also)")
                enabled: popup.library.selectedCount > 0
                onClicked: popup.addAndClose()
            }
            TpButton {
                objectName: "libraryRename"
                text: i18n.tr("Rename…")
                tip: i18n.tr("Rename selected imported log") + " (F2)"
                enabled: popup.library.renameTarget !== "" && !popup.library.writing
                onClicked: popup.startRename()
            }
            TpButton {
                objectName: "libraryDelete"
                glyph: theme.glyphs.delete
                fallback: "✕"
                text: i18n.tr("Move to Trash")
                tip: i18n.tr("Move selected laps to trash") + " (" + i18n.tr("Delete") + ")"
                enabled: popup.library.selectedCount > 0 && !popup.library.writing
                onClicked: popup.library.deleteSelected()
            }
            TpButton {
                objectName: "libraryUndo"
                visible: backend.undoText !== ""
                glyph: theme.glyphs.undo
                fallback: "↶"
                text: backend.undoText
                flat: true
                tip: i18n.tr("Restore deleted laps from trash (Ctrl+Z)")
                onClicked: backend.undoDelete()
            }
            TpButton {
                objectName: "libraryTrash"
                glyph: ""  // history
                fallback: "↺"
                text: i18n.tr("Recently Deleted Laps…")
                flat: true
                tip: i18n.tr("Laps moved to trash, restored one by one")
                onClicked: recentlyDeleted.open()
            }
        }
    }

    TpMenu {
        id: rowMenu
        onClosed: list.forceActiveFocus()
        Action { text: i18n.tr("Add to Viewer"); onTriggered: popup.addAndClose() }
        Action { text: i18n.tr("Rename…"); enabled: !popup.library.writing; onTriggered: popup.startRename() }
        MenuSeparator {}
        Action { text: i18n.tr("Move to Trash"); enabled: !popup.library.writing; onTriggered: popup.library.deleteSelected() }
    }

    // Lap viewer trash: recorded & imported laps, restored one by one
    RecentlyDeleted { id: recentlyDeleted; onClosed: list.forceActiveFocus() }

    // New name of a log: checked while typed (taken, characters a file name can not hold)
    TpDialog {
        id: renameDialog
        objectName: "libraryRenameDialog"
        property string source: ""
        property string error: ""
        title: i18n.tr("Rename")
        acceptText: i18n.tr("Rename")
        closeOnAccept: false
        dismissOnOutside: false  // typed name kept: only Esc or Cancel close it
        acceptEnabled: nameField.text.trim() !== "" && error === "" && !popup.library.writing
        onAccepted: if (popup.library.rename(source, nameField.text)) done()
        onClosed: list.forceActiveFocus()
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Imported log name:")
            textFormat: Text.PlainText
            color: theme.dimText
            wrapMode: Text.WordWrap
        }
        TpTextField {
            id: nameField
            Layout.fillWidth: true
            invalid: renameDialog.error !== ""
            onTextChanged: renameDialog.error = renameDialog.visible ? popup.library.nameError(renameDialog.source, text) : ""
            onAccepted: renameDialog.accept()
            onEscaped: renameDialog.close()
        }
        Text {
            Layout.fillWidth: true
            visible: renameDialog.error !== ""
            text: "⚠ " + renameDialog.error
            textFormat: Text.PlainText
            color: theme.loss
            wrapMode: Text.WordWrap
        }
    }

    TpToast {
        id: toast
        objectName: "libraryToast"
        actionText: backend.undoText !== "" ? i18n.tr("Undo") : ""
        onAction: backend.undoDelete()
    }
}
