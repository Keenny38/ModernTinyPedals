import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Hotkeys page: global hotkey switch, key bindings by section (General, Spectate, Broadcast Director, Preset,
// Overlays, Module: folded with a click), search & "assigned only" filter, actions sharing a key marked. A key
// button opens the capture dialog (keyboard, mouse & game controller buttons). Clearing (a row or all) is undone
// from the toast. Keys: type to search, Ctrl+F or "/" search, arrows move, Enter / Space capture (header: fold),
// Delete clears, Ctrl+Z undoes the last clear.
TpPage {
    id: page

    readonly property bool compact: width < theme.bpCompact

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }
    function openCapture(name) {
        if (!backend.enabled)
            return
        backend.startCapture(name)
        if (backend.captureKey === name)
            capture.open()
    }
    function activate(item) {
        if (!item)
            return
        if (item.header)
            backend.toggleSection(item.section)
        else
            page.openCapture(item.key)
    }

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_F && (event.modifiers & Qt.ControlModifier)) {
            page.focusSearch()
            event.accepted = true
        } else if (event.key === Qt.Key_Z && (event.modifiers & Qt.ControlModifier) && backend.canUndo) {
            backend.undo()
            event.accepted = true
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Title & global hotkey switch
        TpPageHeader {
            title: i18n.tr("Hotkeys")
            count: i18n.trm(backend.assignedCount + " / " + backend.totalCount + " assigned")
            countActive: backend.enabled && backend.assignedCount > 0
            TpSwitch {
                checkable: false  // follows backend
                checked: backend.enabled
                text: backend.enabled ? i18n.tr("Enabled") : i18n.tr("Disabled")
                tip: i18n.tr("Global hotkeys")
                onClicked: backend.setEnabled(!backend.enabled)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Global hotkeys")
                Accessible.checked: backend.enabled
            }
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: theme.dimText
            lineHeight: 1.1
            text: i18n.tr("Keys, mouse buttons and game controller buttons (wheel, button box) that run an action, also while the game has focus.")
        }

        TpNotice {
            Layout.fillWidth: true
            visible: !backend.enabled
            tone: theme.accent
            text: i18n.tr("Global hotkeys are off: turn them on to use and change key bindings.")
            actionText: i18n.tr("Turn On")
            onAction: backend.setEnabled(true)
        }
        TpNotice {
            Layout.fillWidth: true
            visible: backend.enabled && backend.conflictCount > 0
            text: i18n.trm(backend.conflictCount + " actions share a key with another action")
        }

        // Search, filter & clear all
        Flow {
            Layout.fillWidth: true
            spacing: theme.space3
            TpSearchField {
                id: search
                width: page.compact ? parent.width : Math.max(theme.em * 12, parent.width - filterChip.width - clearAll.width - theme.space3 * 2)
                placeholderText: i18n.tr("Search hotkeys") + "   Ctrl+F"
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: list.forceActiveFocus()
                Keys.onReturnPressed: list.forceActiveFocus()
                Keys.onEnterPressed: list.forceActiveFocus()
            }
            TpChip {
                id: filterChip
                text: i18n.tr("Assigned only")
                count: backend.assignedCount
                selected: backend.assignedOnly
                multi: true
                tip: i18n.tr("Show only actions with a key")
                onClicked: backend.setAssignedOnly(!backend.assignedOnly)
            }
            TpButton {
                id: clearAll
                flat: true
                glyph: theme.glyphs.remove
                text: i18n.tr("Clear All")
                tip: i18n.tr("Clear every key binding (undo from the notice)")
                enabled: backend.enabled && backend.assignedCount > 0
                onClicked: backend.clearAll()
            }
        }

        // Bindings
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: list
                objectName: "hotkeyList"
                anchors.fill: parent
                clip: true
                model: backend.rows
                boundsBehavior: Flickable.StopAtBounds
                highlightFollowsCurrentItem: false
                keyNavigationEnabled: true
                activeFocusOnTab: true
                reuseItems: true
                cacheBuffer: Math.round(theme.em * 30)
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: HotkeyRow {
                    id: rowItem
                    width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                    current: ListView.isCurrentItem
                    editable: backend.enabled
                    onToggleRequested: { list.currentIndex = rowItem.index; backend.toggleSection(rowItem.section) }
                    onCaptureRequested: { list.currentIndex = rowItem.index; page.openCapture(rowItem.key) }
                    onClearRequested: backend.clear(rowItem.key)
                }

                Keys.onReturnPressed: page.activate(currentItem)
                Keys.onEnterPressed: page.activate(currentItem)
                Keys.onSpacePressed: page.activate(currentItem)
                Keys.onDeletePressed: if (currentItem && !currentItem.header) backend.clear(currentItem.key)
                Keys.onPressed: function(event) {
                    if (search.routeTyped(event))  // type to search, "/" search
                        event.accepted = true
                }
                onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
            }

            TpStateView {
                anchors.centerIn: parent
                empty: list.count === 0
                glyph: ""  // search
                title: i18n.tr("No hotkey matches the search")
                actionText: i18n.tr("Clear Filters")
                onAction: { backend.clearFilters(); search.clearSearch(); page.focusSearch() }
            }
        }

        Text {
            Layout.fillWidth: true
            elide: Text.ElideRight
            color: theme.dimText
            font.features: { "tnum": 1 }
            text: backend.filtered
                ? i18n.trm(backend.shownCount + " of " + backend.totalCount + " hotkeys shown")
                : i18n.trm(backend.totalCount + " hotkeys")
            textFormat: Text.PlainText
        }
    }

    HotkeyCaptureDialog {
        id: capture
        onClosed: list.forceActiveFocus()  // popups give focus back to the window
    }

    Connections {
        target: backend
        function onFilterChanged() {
            if (search.text !== backend.searchText)
                search.text = backend.searchText
        }
        function onCaptureChanged() {
            if (backend.captureKey === "" && capture.opened)
                capture.close()  // capture ended by the page (closed, released)
        }
    }

    // Toasts of the page (Undo of a clear), dialogs asked by the backend
    TpDialogHost {}
}
