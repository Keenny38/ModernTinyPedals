import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Presets page: loaded preset card with auto load, presets with tags & content (search, sort by last
// change or name), details of selected preset on wide pages, actions in menus. New, duplicate & rename
// ask the name in a box checked while typing. Keys: type to search, "/" search, arrows move, Enter
// loads, F2 renames, Delete deletes, Ctrl+N new preset, Ctrl+Z undoes last delete, Menu key for more.
TpPage {
    id: page

    readonly property bool wide: width >= theme.em * 62  // details panel shown
    readonly property bool roomy: width >= theme.em * 50  // auto load next to loaded preset
    readonly property var loadedInfo: backend.loaded
    readonly property var selectedInfo: backend.selected
    property string menuKey: ""
    property var menuInfo: ({})

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
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
    function popupBelow(menu, button) {
        menu.visible ? menu.close() : menu.popup(button, 0, button.height + 4)
    }

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_N && (event.modifiers & Qt.ControlModifier)) {
            page.openName("", "")
            event.accepted = true
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.8
        anchors.bottomMargin: theme.em * 0.6
        spacing: theme.em * 0.6

        // Title & create
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            Text {
                text: i18n.tr("Preset")
                color: theme.text
                font.pointSize: theme.fontPoint * 1.5
                font.weight: Font.DemiBold
            }
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                implicitHeight: Math.round(theme.em * 1.6)
                implicitWidth: countText.implicitWidth + theme.em * 1.1
                radius: height / 2
                color: theme.hover
                Text {
                    id: countText
                    anchors.centerIn: parent
                    text: backend.presetCount
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.9
                    font.weight: Font.DemiBold
                    font.features: { "tnum": 1 }
                }
            }
            Item { Layout.fillWidth: true }
            TpButton {
                id: importButton
                glyph: ""  // import
                text: i18n.tr("Import")
                tip: i18n.tr("Import preset package (.zip) or share code")
                checked: importMenu.visible
                onClicked: page.popupBelow(importMenu, importButton)
                TpMenu {
                    id: importMenu
                    Action { text: i18n.tr("Preset Package (.zip)..."); onTriggered: backend.importPackage() }
                    Action { text: i18n.tr("Share Code..."); onTriggered: backend.importShareCode() }
                }
            }
            TpButton {
                accent: true
                glyph: ""  // add
                text: i18n.tr("New")
                tip: i18n.tr("New preset with default options") + "  Ctrl+N"
                onClicked: page.openName("", "")
            }
        }

        // Loaded preset & auto load
        Card {
            Layout.fillWidth: true
            implicitHeight: loadedRow.implicitHeight + theme.em * 1.4
            GridLayout {
                id: loadedRow
                anchors.fill: parent
                anchors.margins: theme.em * 0.7
                columns: page.roomy ? 3 : 2
                columnSpacing: theme.em * 0.8
                rowSpacing: theme.em * 0.5
                Rectangle {
                    Layout.preferredWidth: Math.round(theme.em * 2.8)
                    Layout.preferredHeight: Layout.preferredWidth
                    Layout.alignment: Qt.AlignVCenter
                    radius: theme.em * 0.7
                    color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.2 : 0.13)
                    Icon {
                        anchors.centerIn: parent
                        glyph: ""  // library
                        size: theme.em * 1.3
                        color: theme.accent
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        text: i18n.tr("Loaded preset")
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.85
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.em * 0.4
                        Text {
                            Layout.maximumWidth: implicitWidth
                            Layout.fillWidth: true
                            text: page.loadedInfo.name || ""
                            color: theme.text
                            font.pointSize: theme.fontPoint * 1.35
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Pill {
                            visible: page.loadedInfo.locked === true
                            glyph: ""  // lock
                            text: i18n.tr("Locked")
                            tint: theme.warning
                            tip: i18n.tr("Locked: changes are not saved")
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: page.loadedInfo.found === true
                        text: (page.loadedInfo.changedText || "") + "  ·  " + i18n.trm((page.loadedInfo.overlays || 0) + " overlays")
                              + "  ·  " + i18n.trm((page.loadedInfo.modules || 0) + " modules")
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.85
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
                        font.pointSize: theme.fontPoint * 0.8
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        // Search & sort
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            TpSearchField {
                id: search
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                placeholderText: i18n.tr("Search presets, classes, tracks") + "   /"
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: presets.forceActiveFocus()
                Keys.onReturnPressed: presets.forceActiveFocus()
                Keys.onEnterPressed: presets.forceActiveFocus()
            }
            TpSegmented {
                options: [i18n.tr("Recent"), i18n.tr("Name")]
                currentIndex: backend.sortMode
                onActivated: function(index) { backend.setSortMode(index) }
            }
        }

        // Presets & details
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: theme.em * 0.6

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ListView {
                    id: presets
                    anchors.fill: parent
                    clip: true
                    model: backend.presets
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
                        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 }
                        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 160; easing.type: Easing.OutCubic }
                    }
                    remove: Transition {
                        NumberAnimation { property: "opacity"; to: 0; duration: 130 }
                    }
                    displaced: Transition {
                        NumberAnimation { properties: "y"; duration: 220; easing.type: Easing.OutCubic }
                        NumberAnimation { property: "opacity"; to: 1; duration: 220 }
                        NumberAnimation { property: "scale"; to: 1; duration: 220 }
                    }
                    move: Transition {
                        NumberAnimation { properties: "y"; duration: 240; easing.type: Easing.OutCubic }
                    }

                    Keys.onReturnPressed: if (currentItem) backend.load(currentItem.key)
                    Keys.onEnterPressed: if (currentItem) backend.load(currentItem.key)
                    Keys.onDeletePressed: if (currentItem) backend.remove(currentItem.key)
                    Keys.onMenuPressed: if (currentItem) page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem.key)
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_F2 && currentItem && !currentItem.locked) {
                            page.openName("rename", currentItem.key)
                            event.accepted = true
                            return
                        }
                        // Type to search
                        var code = event.text.length === 1 ? event.text.charCodeAt(0) : 0
                        if (event.text === "/" || (code > 32 && code !== 127
                                && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)))) {
                            search.forceActiveFocus()
                            if (event.text !== "/") {
                                search.insert(search.length, event.text)
                                backend.setSearch(search.text)
                            } else {
                                search.selectAll()
                            }
                            event.accepted = true
                        }
                    }
                    onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
                }

                EmptyState {
                    anchors.centerIn: parent
                    visible: presets.count === 0
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
                    classMenu.popup(item, 0, item.height + 4)
                }
                onTrackMenuRequested: function(item) {
                    page.menuKey = page.selectedInfo.key
                    page.menuInfo = page.selectedInfo
                    trackMenu.popup(item, 0, item.height + 4)
                }
            }
        }

        // Count & other pages
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            Text {
                text: backend.filtered
                    ? i18n.trm(backend.shownCount + " of " + backend.presetCount + " presets shown")
                    : i18n.trm(backend.presetCount + " presets")
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            TpButton {
                visible: backend.canUndoDelete
                flat: true
                glyph: ""  // undo
                text: i18n.tr("Undo Delete")
                tip: i18n.tr("Undo (Ctrl+Z)")
                onClicked: backend.undoDelete()
            }
            Item { Layout.fillWidth: true }
            TpButton {
                flat: true
                glyph: ""  // switch
                text: page.wide || theme.iconFont === "" ? i18n.tr("Transfer") : ""
                tip: i18n.tr("Copy settings of the loaded preset to other presets")
                onClicked: backend.openPage("transfer")
            }
            TpButton {
                flat: true
                glyph: ""  // history
                text: page.wide || theme.iconFont === "" ? i18n.tr("Restore Backup") : ""
                tip: i18n.tr("Restore an automatic or manual backup")
                onClicked: backend.openPage("restore")
            }
            TpButton {
                flat: true
                glyph: ""  // delete
                text: (page.wide || theme.iconFont === "" ? i18n.tr("Trash") : "") + (backend.trashCount > 0 ? "  " + backend.trashCount : "")
                tip: i18n.tr("Deleted presets: restore or delete permanently")
                onClicked: backend.openPage("trash")
            }
            TpButton {
                flat: true
                glyph: ""  // open folder
                text: theme.iconFont === "" ? i18n.tr("Open Folder") : ""
                tip: i18n.tr("Open Folder")
                onClicked: backend.openPage("folder")
            }
        }
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
        Action { text: i18n.tr("Duplicate") + "..."; onTriggered: page.openName("duplicate", page.menuKey) }
        Action {
            text: i18n.tr("Rename") + "...\tF2"
            enabled: page.menuInfo.locked !== true
            onTriggered: page.openName("rename", page.menuKey)
        }
        Action {
            text: page.menuInfo.locked ? i18n.tr("Unlock Preset") : i18n.tr("Lock Preset")
            onTriggered: backend.toggleLock(page.menuKey)
        }
        Action { text: i18n.tr("Backup Preset"); onTriggered: backend.backup(page.menuKey) }
        MenuSeparator {}
        Action { text: i18n.tr("Export Package..."); onTriggered: backend.exportPackage(page.menuKey) }
        Action { text: i18n.tr("Copy Share Code"); onTriggered: backend.copyShareCode(page.menuKey) }
        Action {
            text: i18n.tr("Compare with Loaded Preset")
            enabled: page.menuInfo.loaded !== true
            onTriggered: backend.compare(page.menuKey)
        }
        MenuSeparator {}
        TpMenu {
            id: rowClassMenu
            title: i18n.tr("Set Primary for Class")
            enabled: (page.menuInfo.classChoices || []).length > 0
            Instantiator {
                model: page.menuInfo.classChoices || []
                delegate: Action {
                    required property string modelData
                    text: modelData
                    onTriggered: backend.setPrimaryClass(page.menuKey, modelData)
                }
                onObjectAdded: function(index, object) { rowClassMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { rowClassMenu.removeAction(object) }
            }
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
        Action {
            text: i18n.tr("Delete") + "\tDel"
            enabled: page.menuInfo.loaded !== true && page.menuInfo.locked !== true
            onTriggered: backend.remove(page.menuKey)
        }
        onClosed: presets.forceActiveFocus()
    }
    TpMenu {
        id: classMenu
        Instantiator {
            model: page.menuInfo.classChoices || []
            delegate: Action {
                required property string modelData
                text: modelData
                onTriggered: backend.setPrimaryClass(page.menuKey, modelData)
            }
            onObjectAdded: function(index, object) { classMenu.insertAction(index, object) }
            onObjectRemoved: function(index, object) { classMenu.removeAction(object) }
        }
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
        title: mode === "duplicate" ? i18n.tr("Duplicate Preset")
             : mode === "rename" ? i18n.tr("Rename Preset") : i18n.tr("Create new default preset")
        acceptText: mode === "duplicate" ? i18n.tr("Duplicate") : mode === "rename" ? i18n.tr("Rename") : i18n.tr("Create")
        acceptEnabled: nameField.text.trim() !== "" && error === "" && !unchanged
        onAccepted: {
            var result = backend.applyName(mode, source, nameField.text)
            if (result === "")
                done()
            else
                error = result
        }
        onClosed: presets.forceActiveFocus()

        Text {
            Layout.fillWidth: true
            text: nameDialog.mode === "duplicate" ? i18n.trm("Copy of " + nameDialog.sourceName + ", with all its options")
                : nameDialog.mode === "rename" ? i18n.tr("Backups, layout profiles, primary tags & hotkeys follow the new name")
                : i18n.tr("Every overlay & module with its default options")
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
    }
}
