import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Presets page: loaded preset card with auto load, presets with tags & content (search, sort by last
// change or name), details of selected preset on wide pages, actions in menus. New, duplicate & rename
// ask the name in a box checked while typing. Compare, transfer, restore backup & recently deleted presets are
// panels of the page. Keys: type to search, "/" or Ctrl+F search, arrows move, Enter loads, F2 renames, Delete
// deletes (toast with Undo), Ctrl+N new preset, Ctrl+Z undoes last delete, Menu key for more.
TpPage {
    id: page

    readonly property bool wide: width >= theme.em * 62  // content-tuned: 24 em details panel beside a 36 em list
    readonly property bool roomy: width >= theme.em * 50  // content-tuned: auto load switch beside the loaded preset name
    readonly property var loadedInfo: backend.loaded
    readonly property var selectedInfo: backend.selected
    property string menuKey: ""
    property var menuInfo: ({})

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }
    function openCompare(key) {
        comparePanel.openFor(key)
    }
    function openPanel(name, key) {
        if (name === "compare")
            page.openCompare(key)
        else if (name === "transfer")
            transferPanel.open()
        else if (name === "restore")
            backupsPanel.open()
        else if (name === "trash")
            deletedPanel.open()
    }
    function openName(mode, key) {
        nameDialog.mode = mode
        nameDialog.source = key
        nameDialog.error = ""
        nameField.text = backend.suggestName(mode, key)
        nameDialog.open()
        nameField.forceActiveFocus()
        nameField.selectAll()
    }
    function openMenu(item, x, y, key) {
        backend.select(key)
        page.menuKey = key
        page.menuInfo = backend.selected
        rowMenu.popup(item, x, y)
    }

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_N && (event.modifiers & Qt.ControlModifier)) {
            page.openName("", "")
            event.accepted = true
        } else if (event.key === Qt.Key_F && (event.modifiers & Qt.ControlModifier)) {
            page.focusSearch()
            event.accepted = true
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Title & create
        TpPageHeader {
            title: i18n.tr("Presets")
            count: "" + backend.presetCount
            TpButton {
                glyph: theme.glyphs["import"]
                text: i18n.tr("Import")
                tip: i18n.tr("Import preset package (.zip)")
                onClicked: backend.importPackage()
            }
            TpButton {
                accent: true
                glyph: theme.glyphs.add
                text: i18n.tr("New")
                tip: i18n.tr("New preset with default options") + "  Ctrl+N"
                onClicked: page.openName("", "")
            }
        }

        // Loaded preset & auto load
        Card {
            Layout.fillWidth: true
            implicitHeight: loadedRow.implicitHeight + theme.padCard * 2
            GridLayout {
                id: loadedRow
                anchors.fill: parent
                anchors.margins: theme.padCard
                columns: page.roomy ? 3 : 2
                columnSpacing: theme.em * 0.8
                rowSpacing: theme.em * 0.5
                TpIconTile {
                    Layout.alignment: Qt.AlignVCenter
                    size: Math.round(theme.iconHero)  // page badge
                    Layout.preferredWidth: size  // TpIconTile sets width only (no implicit size)
                    Layout.preferredHeight: size
                    fallbackText: page.loadedInfo.name || ""
                    glyph: ""  // library
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        text: i18n.tr("Loaded preset")
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Text {
                            Layout.maximumWidth: implicitWidth
                            Layout.fillWidth: true
                            text: page.loadedInfo.name || ""
                            textFormat: Text.PlainText
                            color: theme.text
                            font.pointSize: theme.fontLarge
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Pill {
                            visible: page.loadedInfo.locked === true
                            glyph: theme.glyphs.lock
                            text: i18n.tr("Locked")
                            tint: theme.warning
                            tip: i18n.tr("Locked: changes are not saved")
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: page.loadedInfo.found === true
                        text: page.loadedInfo.pending === true ? (page.loadedInfo.changedText || "")  // content read meanwhile
                            : (page.loadedInfo.changedText || "") + "  ·  " + i18n.trm((page.loadedInfo.overlays || 0) + " overlays")
                              + "  ·  " + i18n.trm((page.loadedInfo.modules || 0) + " modules")
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        elide: Text.ElideRight
                    }
                }
                ColumnLayout {
                    Layout.columnSpan: page.roomy ? 1 : 2
                    Layout.alignment: page.roomy ? Qt.AlignRight | Qt.AlignVCenter : Qt.AlignLeft
                    Layout.maximumWidth: page.roomy ? theme.em * 28 : -1
                    spacing: 2
                    TpSwitch {
                        Layout.alignment: page.roomy ? Qt.AlignRight : Qt.AlignLeft
                        Layout.maximumWidth: page.roomy ? theme.em * 28 : -1
                        checkable: false
                        checked: backend.autoLoad
                        text: i18n.tr("Auto Load Primary Preset")
                        onClicked: backend.setAutoLoad(!backend.autoLoad)
                        Accessible.role: Accessible.CheckBox
                        Accessible.name: text
                        Accessible.checked: backend.autoLoad
                    }
                    Text {
                        Layout.fillWidth: true
                        horizontalAlignment: page.roomy ? Text.AlignRight : Text.AlignLeft
                        text: i18n.tr("On track: primary preset of the track, else of the car class")
                        color: theme.dimText
                        font.pointSize: theme.fontCaption
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        // Search & sort
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space4
            TpSearchField {
                id: search
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                placeholderText: i18n.tr("Search presets, classes, tracks") + "   Ctrl+F"
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: presets.forceActiveFocus()
                Keys.onReturnPressed: presets.forceActiveFocus()
                Keys.onEnterPressed: presets.forceActiveFocus()
            }
            TpSegmented {
                name: i18n.tr("Sort")
                options: [i18n.tr("Recent"), i18n.tr("Name")]
                currentIndex: backend.sortMode
                onActivated: function(index) { backend.setSortMode(index) }
            }
        }

        // Presets & details
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: theme.space4

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ListView {
                    id: presets
                    objectName: "presetList"
                    anchors.fill: parent
                    clip: true
                    model: backend.presets
                    reuseItems: true  // rows reset their transient state when pooled (see PresetRow)
                    boundsBehavior: Flickable.StopAtBounds
                    highlightFollowsCurrentItem: false
                    keyNavigationEnabled: true
                    activeFocusOnTab: true
                    cacheBuffer: theme.em * 30
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: PresetRow {
                        id: presetRow
                        selected: backend.selectedKey === key
                        onClicked: backend.select(key)
                        onLoadRequested: backend.load(key)
                        onMenuRequested: function(item, x, y) { page.openMenu(item, x, y, presetRow.key) }
                    }
                    onCurrentItemChanged: if (currentItem && activeFocus) backend.select(currentItem.key)

                    add: Transition {
                        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase }
                        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: theme.motionBase; easing.type: Easing.OutCubic }
                    }
                    remove: Transition {
                        NumberAnimation { property: "opacity"; to: 0; duration: theme.motionFast }
                    }
                    displaced: Transition {
                        NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic }
                        NumberAnimation { property: "opacity"; to: 1; duration: theme.motionSlow }
                        NumberAnimation { property: "scale"; to: 1; duration: theme.motionSlow }
                    }
                    move: Transition {
                        NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic }
                    }

                    Keys.onReturnPressed: if (currentItem) backend.load(currentItem.key)
                    Keys.onEnterPressed: if (currentItem) backend.load(currentItem.key)
                    // Loaded & locked presets cannot be deleted (as the menu): no error box for a key press
                    Keys.onDeletePressed: if (currentItem && !currentItem.loaded && !currentItem.locked) backend.remove(currentItem.key)
                    Keys.onMenuPressed: if (currentItem) page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem.key)
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_F10 && event.modifiers === Qt.ShiftModifier && currentItem) {
                            page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem.key)  // Shift+F10: as the Menu key
                            event.accepted = true
                            return
                        }
                        if (event.key === Qt.Key_F2 && currentItem && !currentItem.locked) {
                            page.openName("rename", currentItem.key)
                            event.accepted = true
                            return
                        }
                        if (search.routeTyped(event))  // type to search, "/" search
                            event.accepted = true
                    }
                    onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
                }

                TpStateView {
                    anchors.centerIn: parent
                    empty: presets.count === 0
                    glyph: backend.filtered ? "" : ""  // search, library
                    title: backend.filtered ? i18n.tr("No preset matches the search") : i18n.tr("No preset yet")
                    actionText: backend.filtered ? i18n.tr("Clear Search") : i18n.tr("New")
                    onAction: {
                        if (backend.filtered) {
                            search.clearSearch()
                            page.focusSearch()
                        } else {
                            page.openName("", "")
                        }
                    }
                }
            }

            PresetDetails {
                visible: page.wide
                Layout.preferredWidth: Math.round(Math.min(theme.em * 24, page.width * 0.38))
                Layout.fillHeight: true
                info: page.selectedInfo
                onNameRequested: function(mode) { page.openName(mode, page.selectedInfo.key) }
                onClassMenuRequested: function(item) {
                    page.menuKey = page.selectedInfo.key
                    page.menuInfo = page.selectedInfo
                    classMenu.toggleBelow(item)
                }
                onTrackMenuRequested: function(item) {
                    page.menuKey = page.selectedInfo.key
                    page.menuInfo = page.selectedInfo
                    trackMenu.toggleBelow(item)
                }
                onCompareRequested: page.openCompare(page.selectedInfo.key)
            }
        }

        // Count & other pages
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            Text {
                Layout.fillWidth: true
                Layout.maximumWidth: implicitWidth
                text: backend.filtered
                    ? i18n.trm(backend.shownCount + " of " + backend.presetCount + " presets shown")
                    : i18n.trm(backend.presetCount + " presets")
                textFormat: Text.PlainText
                color: theme.dimText
                font.features: { "tnum": 1 }
                elide: Text.ElideRight  // narrow page: cut, buttons kept in view
            }
            TpButton {
                visible: backend.canUndoDelete
                flat: true
                glyph: theme.glyphs.undo
                text: i18n.tr("Undo Delete")
                tip: i18n.tr("Undo (Ctrl+Z)")
                onClicked: backend.undoDelete()
            }
            Item { Layout.fillWidth: true }
            TpButton {
                flat: true
                glyph: ""  // switch
                text: page.wide ? i18n.tr("Transfer") : ""
                fallback: i18n.tr("Transfer")
                tip: i18n.tr("Copy settings of the loaded preset to other presets")
                onClicked: transferPanel.open()
            }
            TpButton {
                flat: true
                glyph: ""  // history
                text: page.wide ? i18n.tr("Restore Backup") : ""
                fallback: i18n.tr("Restore Backup")
                tip: i18n.tr("Restore an automatic or manual backup")
                onClicked: backupsPanel.open()
            }
            TpButton {
                flat: true
                glyph: theme.glyphs.delete
                // Icon only on narrow pages (named without icon font), deleted presets counted either way
                readonly property bool named: page.wide || theme.iconFont === ""
                text: (named ? i18n.tr("Trash") : "") + (backend.trashCount > 0 ? "  " + backend.trashCount : "")
                tip: i18n.tr("Recently Deleted Presets")
                onClicked: deletedPanel.open()
            }
            TpButton {
                flat: true
                glyph: theme.glyphs.openFolder
                fallback: i18n.tr("Open Folder")
                tip: i18n.tr("Open Folder")
                onClicked: backend.openPage("folder")
            }
        }
    }

    // Classes of preset menu for a session ("" every session, else "practice", "qualify", "race"): primary preset
    // loaded for this class in this session (class preset of the session first, then track, then class preset)
    component ClassSessionMenu: TpMenu {
        id: sessionMenu
        property string session: ""
        readonly property var choices: (page.menuInfo.classChoices || {})[session] || []
        title: session === "practice" ? i18n.tr("Practice") : session === "qualify" ? i18n.tr("Qualify")
             : session === "race" ? i18n.tr("Race") : i18n.tr("Every session")
        enabled: choices.length > 0
        Instantiator {
            model: sessionMenu.choices
            delegate: Action {
                required property string modelData
                text: modelData
                onTriggered: backend.setPrimaryClassSession(page.menuKey, modelData, sessionMenu.session)
            }
            onObjectAdded: function(index, object) { sessionMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { sessionMenu.removeAction(object) }
        }
    }
    function hasClassChoices(info) {
        var choices = info.classChoices || {}
        for (var session in choices)
            if (choices[session].length > 0)
                return true
        return false
    }

    // Preset menu (right click, more button, Menu key)
    TpMenu {
        id: rowMenu
        Action {
            text: i18n.tr("Load")
            enabled: page.menuInfo.loaded !== true
            onTriggered: backend.load(page.menuKey)
        }
        MenuSeparator {}
        Action { text: i18n.tr("Duplicate") + "…"; onTriggered: page.openName("duplicate", page.menuKey) }
        TpMenuItem {  // key shown at the right: F2 on the list renames
            text: i18n.tr("Rename") + "…"
            shortcut: "F2"
            enabled: page.menuInfo.locked !== true
            onTriggered: page.openName("rename", page.menuKey)
        }
        Action {
            text: page.menuInfo.locked ? i18n.tr("Unlock Preset") : i18n.tr("Lock Preset")
            onTriggered: backend.toggleLock(page.menuKey)
        }
        Action { text: i18n.tr("Backup Preset"); onTriggered: backend.backup(page.menuKey) }
        Action { text: i18n.tr("Check Preset"); onTriggered: backend.checkPreset(page.menuKey) }
        MenuSeparator {}
        Action { text: i18n.tr("Export Package…"); onTriggered: backend.exportPackage(page.menuKey) }
        Action {
            text: i18n.tr("Compare with Loaded Preset")
            enabled: page.menuInfo.loaded !== true
            onTriggered: page.openCompare(page.menuKey)
        }
        MenuSeparator {}
        TpMenu {
            title: i18n.tr("Set Primary for Class")
            enabled: page.hasClassChoices(page.menuInfo)
            ClassSessionMenu { session: "" }
            MenuSeparator {}
            ClassSessionMenu { session: "practice" }
            ClassSessionMenu { session: "qualify" }
            ClassSessionMenu { session: "race" }
        }
        TpMenu {
            id: rowTrackMenu
            title: i18n.tr("Set Primary for Track")
            enabled: (page.menuInfo.trackChoices || []).length > 0
            Instantiator {
                model: page.menuInfo.trackChoices || []
                delegate: Action {
                    required property string modelData
                    text: modelData
                    onTriggered: backend.setPrimaryTrack(page.menuKey, modelData)
                }
                onObjectAdded: function(index, object) { rowTrackMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { rowTrackMenu.removeAction(object) }
            }
        }
        Action {
            text: i18n.tr("Clear Primary Tag")
            enabled: (page.menuInfo.classes || []).length > 0 || (page.menuInfo.tracks || []).length > 0
            onTriggered: backend.clearPrimary(page.menuKey)
        }
        MenuSeparator {}
        TpMenuItem {  // Delete key on the list does the same (undo toast, Ctrl+Z)
            text: i18n.tr("Delete")
            shortcut: i18n.tr("Del")
            enabled: page.menuInfo.loaded !== true && page.menuInfo.locked !== true
            onTriggered: backend.remove(page.menuKey)
        }
        // Closed after its exit transition: name dialog opened by Duplicate / Rename keeps focus (Enter there,
        // never loading the preset of the list)
        onClosed: if (!nameDialog.visible) presets.forceActiveFocus()
    }
    TpMenu {
        id: classMenu
        ClassSessionMenu { session: "" }
        MenuSeparator {}
        ClassSessionMenu { session: "practice" }
        ClassSessionMenu { session: "qualify" }
        ClassSessionMenu { session: "race" }
    }
    TpMenu {
        id: trackMenu
        Instantiator {
            model: page.menuInfo.trackChoices || []
            delegate: Action {
                required property string modelData
                text: modelData
                onTriggered: backend.setPrimaryTrack(page.menuKey, modelData)
            }
            onObjectAdded: function(index, object) { trackMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { trackMenu.removeAction(object) }
        }
    }

    // New, duplicate & rename: name checked while typing
    TpDialog {
        id: nameDialog
        property string mode: ""
        property string source: ""
        property string error: ""
        readonly property string sourceName: source.length > 5 ? source.substring(0, source.length - 5) : source
        readonly property bool unchanged: mode === "rename" && nameField.text.trim() === sourceName
        closeOnAccept: false
        title: mode === "duplicate" ? i18n.tr("Duplicate Preset") : mode === "rename" ? i18n.tr("Rename Preset")
             : mode === "restore" ? i18n.tr("Restore Backup") : i18n.tr("Create new default preset")
        acceptText: mode === "duplicate" ? i18n.tr("Duplicate") : mode === "rename" ? i18n.tr("Rename")
                  : mode === "restore" ? i18n.tr("Restore") : i18n.tr("Create")
        acceptEnabled: nameField.text.trim() !== "" && error === "" && !unchanged
        onAccepted: {
            var result = backend.applyName(mode, source, nameField.text)
            if (result === "")
                done()
            else
                error = result
        }
        dismissOnOutside: false  // typed name kept: only Esc or Cancel close it
        onClosed: mode === "restore" ? backupsPanel.open() : presets.forceActiveFocus()  // back to the backups

        Text {
            Layout.fillWidth: true
            text: nameDialog.mode === "duplicate" ? i18n.trm("Copy of " + nameDialog.sourceName + ", with all its options")
                : nameDialog.mode === "rename" ? i18n.tr("Backups, layout profiles, primary tags & hotkeys follow the new name")
                : nameDialog.mode === "restore" ? i18n.tr("New preset made from the backup %1").arg(nameDialog.source)
                : i18n.tr("Every overlay & module with its default options")
            textFormat: Text.PlainText
            color: theme.dimText
            wrapMode: Text.WordWrap
        }
        TpTextField {
            id: nameField
            Layout.fillWidth: true
            placeholderText: i18n.tr("Enter a new preset name")
            maximumLength: 40
            validator: RegularExpressionValidator { regularExpression: /[^\\/:*?"<>|]*/ }  // file name characters
            invalid: nameDialog.error !== ""
            onTextChanged: nameDialog.error = nameDialog.visible ? backend.nameError(nameDialog.mode, nameDialog.source, text) : ""
            onAccepted: nameDialog.accept()
            onEscaped: nameDialog.close()
        }
        Text {
            Layout.fillWidth: true
            visible: nameDialog.error !== ""
            text: "⚠ " + nameDialog.error.replace(/<br>/g, " ")
            textFormat: Text.PlainText
            color: theme.loss
            wrapMode: Text.WordWrap
        }
    }

    Connections {
        target: backend
        function onFilterChanged() {
            if (search.text !== backend.searchText)
                search.text = backend.searchText
        }
        function onPanelRequested(name, key) { page.openPanel(name, key) }
    }

    // Panels (over the page)
    PresetComparePanel { id: comparePanel; objectName: "comparePanel"; onDismissed: presets.forceActiveFocus() }
    PresetTransfer { id: transferPanel; objectName: "transferPanel"; onClosed: presets.forceActiveFocus() }
    PresetBackups {
        id: backupsPanel
        objectName: "backupsPanel"
        // Preset backup restored as a new preset: name asked (panel shown again once the name box closes)
        onRestoreAsPreset: function(name) {
            backupsPanel.close()
            page.openName("restore", name)
        }
        onClosed: if (!nameDialog.visible) presets.forceActiveFocus()
    }
    DeletedPresets { id: deletedPanel; objectName: "deletedPanel"; onClosed: presets.forceActiveFocus() }

    // Dialogs asked by the backend & toasts of the page and its panels (Undo after a delete)
    TpDialogHost {}
}
