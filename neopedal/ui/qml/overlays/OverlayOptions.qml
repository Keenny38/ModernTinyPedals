import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Overlay Options page: options of every overlay. Overlays on the left (by category, with unsaved edits,
// errors & search matches; a choice list on narrow pages), options of the selected overlay in section
// cards, live preview on the right (wide pages; a drawer opened by "Preview" on narrower ones). Search in this
// overlay or in every overlay (Ctrl+F), filters menu (changed only, used only, advanced options). The overlay
// switch of the header turns it on or off at once (as on the Overlays page); edits of options stay pending
// until applied: unsaved changes bar at the bottom (TpPendingBar, as on Settings) with Undo, Redo, Discard &
// Apply (Ctrl+S). After Discard the bar stays a few seconds with Undo. Rows: more actions with "⋯", right click
// or Menu key.
TpPage {
    id: page

    readonly property bool narrow: width < theme.bpNarrow
    readonly property bool previewShown: width >= theme.em * 74  // content-tuned: navigation + options + 21 em preview
    readonly property var info: backend.overlayInfo
    readonly property bool everyOverlay: backend.filtering && backend.scopeAll  // results of every overlay shown
    readonly property int filterCount: (backend.modifiedOnly ? 1 : 0) + (backend.usedOnly ? 1 : 0)
    property bool previewOpen: false  // preview drawer (pages too narrow for the preview panel)
    property var menuData: null  // option row of the more actions menu

    function openRowMenu(data, anchor, x, y) {
        page.menuData = data
        if (x < 0)
            rowMenu.toggleBelow(anchor, true)  // right aligned under the row's "⋯" button (or the row)
        else
            rowMenu.popup(anchor, x, y)
    }

    // Field being edited committed (Apply, Ctrl+S: buttons & shortcuts take no focus): focus left
    function commitEdits() {
        page.forceActiveFocus()
    }
    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }
    function isFind(event) {
        return event.key === Qt.Key_F && event.modifiers === Qt.ControlModifier
    }
    function drawerOpen() {
        return previewOpen && !previewShown
    }
    function showSelectedOverlay() {
        var index = backend.navIndex(backend.overlay)
        if (index >= 0)
            nav.positionViewAtIndex(index, ListView.Contain)
    }
    function scrollToKey(key) {
        var index = backend.rowIndex(key)
        if (index < 0)
            return
        list.positionViewAtIndex(index, ListView.Center)
        var item = list.itemAtIndex(index)
        if (item)
            item.flash()
    }

    Component.onCompleted: Qt.callLater(page.showSelectedOverlay)

    // Ctrl+F searches this page (taken before the app's own Ctrl+F shortcut), Esc closes the preview drawer first
    Keys.onShortcutOverride: function(event) {
        if (isFind(event) || (event.key === Qt.Key_Escape && drawerOpen()))
            event.accepted = true
    }
    Keys.onPressed: function(event) {
        if (isFind(event)) {
            page.focusSearch()
            event.accepted = true
        } else if (event.key === Qt.Key_Escape && drawerOpen()) {
            page.previewOpen = false
            event.accepted = true
        }
    }

    Connections {
        target: backend
        function onHighlightChanged() {
            if (backend.highlightKey !== "")
                highlightTimer.restart()  // rows of new overlay laid out first
        }
        function onOverlayChanged() {
            if (backend.overlay !== list.shownOverlay) {
                list.shownOverlay = backend.overlay
                list.positionViewAtBeginning()
            }
            page.showSelectedOverlay()
        }
        function onFilterChanged() {
            if (search.text !== backend.searchText)
                search.text = backend.searchText
            if (navSearch.text !== backend.navFilter)
                navSearch.text = backend.navFilter
        }
    }
    Timer {
        id: highlightTimer
        interval: 60
        onTriggered: {
            page.scrollToKey(backend.highlightKey)
            backend.clearHighlight()
        }
    }

    TpMenu {
        id: rowMenu
        objectName: "optionMenu"
        TpMenuItem {
            text: i18n.tr("Reset to Default")
            enabled: page.menuData !== null && page.menuData.modified && !page.menuData.locked
            onTriggered: backend.resetOption(page.menuData.key)
        }
        TpMenuItem {
            text: page.menuData !== null ? i18n.trm("Apply to All Overlays (" + page.menuData.shared + ")") : ""
            enabled: page.menuData !== null && page.menuData.shared > 0 && page.menuData.error === ""
            onTriggered: backend.applyToAll(page.menuData.key)
        }
        TpMenuItem {
            readonly property bool shown: page.menuData !== null && page.menuData.kind === "path"
            visible: shown
            height: shown ? implicitHeight : 0
            text: i18n.tr("Open Folder")
            onTriggered: backend.openFolder(page.menuData.key)
        }
        MenuSeparator {}
        TpMenuItem {
            text: i18n.tr("Copy Option Key")
            onTriggered: backend.copyText(page.menuData.option)
        }
        onClosed: list.forceActiveFocus()
    }
    TpMenu {
        id: shareMenu
        TpMenuItem {
            text: i18n.tr("Export Overlay Settings…")
            onTriggered: backend.exportOverlays()
        }
        TpMenuItem {
            text: i18n.tr("Import Overlay Settings…")
            onTriggered: backend.importOverlays()
        }
        onClosed: list.forceActiveFocus()
    }
    // Filters of the options list: checked entries follow the backend (binding put back after each click)
    TpMenu {
        id: filtersMenu
        objectName: "filtersMenu"
        TpMenuItem {
            objectName: "changedOnlyItem"
            text: i18n.tr("Changed Only")
            checkable: true
            checked: backend.modifiedOnly
            onTriggered: {
                backend.setModifiedOnly(!backend.modifiedOnly)
                checked = Qt.binding(function() { return backend.modifiedOnly })
            }
        }
        TpMenuItem {
            objectName: "usedOnlyItem"
            text: i18n.tr("Used Only")
            checkable: true
            checked: backend.usedOnly
            onTriggered: {
                backend.setUsedOnly(!backend.usedOnly)
                checked = Qt.binding(function() { return backend.usedOnly })
            }
        }
        TpMenuItem {  // simple mode overlays: every option, including colors, thresholds and labels
            objectName: "advancedItem"
            readonly property bool shown: page.info.simpleMode === true && !page.everyOverlay
            visible: shown
            height: shown ? implicitHeight : 0
            text: i18n.tr("Advanced Options")
            checkable: true
            checked: backend.advanced
            onTriggered: {
                backend.setAdvanced(!backend.advanced)
                checked = Qt.binding(function() { return backend.advanced })
            }
        }
    }
    // Display profiles of the overlay: shown items saved as one (then picked in Display Profile)
    TpMenu {
        id: profileMenu
        objectName: "profileMenu"
        TpMenuItem {
            text: i18n.tr("Save shown items as:")
            enabled: false
        }
        Instantiator {
            model: page.info.userProfiles || []
            delegate: TpMenuItem {
                required property var modelData
                text: modelData.label
                onTriggered: backend.saveUserProfile(modelData.name)
            }
            onObjectAdded: function(index, object) { profileMenu.insertItem(index + 1, object) }
            onObjectRemoved: function(index, object) { profileMenu.removeItem(object) }
        }
    }
    // Color themes: every color of the overlay set to one (pending edits)
    TpMenu {
        id: themeMenu
        objectName: "themeMenu"
        Instantiator {
            model: page.info.themes || []
            delegate: TpMenuItem {
                required property var modelData
                text: modelData.label
                onTriggered: backend.applyColorTheme(modelData.name)
            }
            onObjectAdded: function(index, object) { themeMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { themeMenu.removeItem(object) }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Overlays
        Rectangle {
            visible: !page.narrow
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(theme.em * 15.5)
            color: theme.surfaceSunken  // overlay list: below the options

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: theme.space4
                spacing: theme.space3

                TpSearchField {
                    id: navSearch
                    Layout.fillWidth: true
                    placeholderText: i18n.tr("Find overlay")
                    onSearchChanged: function(text) { backend.setNavFilter(text) }
                    onExitField: nav.forceActiveFocus()
                }
                TpSegmented {
                    Layout.fillWidth: true
                    name: i18n.tr("Overlay state")
                    options: [i18n.tr("All"), i18n.tr("Active")]
                    currentIndex: backend.activeOnly ? 1 : 0
                    maxWidth: width
                    onActivated: function(index) { backend.setActiveOnly(index === 1) }
                }

                ListView {
                    id: nav
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 1
                    boundsBehavior: Flickable.StopAtBounds
                    model: backend.overlays
                    activeFocusOnTab: true
                    currentIndex: -1
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    Keys.onUpPressed: backend.stepOverlay(-1)
                    Keys.onDownPressed: backend.stepOverlay(1)
                    section.property: "categoryLabel"
                    section.delegate: Item {
                        required property string section
                        width: ListView.view.width
                        height: Math.round(theme.headerHeight)
                        TpSectionLabel {
                            anchors.left: parent.left
                            anchors.leftMargin: theme.space3
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: theme.space2
                            text: parent.section
                        }
                    }
                    delegate: Rectangle {
                        id: entry
                        required property var model
                        // Roles read by bindings: fed once (and again on change) instead of a model read per evaluation
                        required property string key
                        required property string label
                        required property int changed
                        required property int errors
                        required property int matches
                        required property int customized
                        readonly property bool overlayOn: model.enabled  // "enabled" & "color" roles: Item names
                        readonly property bool selected: backend.overlay === key && !(backend.filtering && backend.scopeAll)
                        // Searching every overlay: overlays without match in dim text (not faded: still readable)
                        readonly property bool dimmed: backend.filtering && backend.scopeAll && matches === 0
                        readonly property int badgeCount: backend.filtering && backend.scopeAll ? matches : changed
                        width: ListView.view.width
                        height: Math.round(theme.em * 2.2)
                        radius: theme.radiusMd
                        color: theme.rowColor(entryArea.containsMouse, selected)
                        Behavior on color { ColorAnimation { duration: theme.motionFast } }
                        Accessible.role: Accessible.PageTab
                        Accessible.name: label
                        Accessible.selected: selected

                        Rectangle {
                            visible: entry.selected
                            width: Math.round(theme.em * 0.22)
                            height: parent.height * 0.5
                            radius: width / 2
                            anchors.verticalCenter: parent.verticalCenter
                            color: theme.accent
                        }
                        Rectangle {  // state: filled while overlay is on, ring while off
                            id: stateDot
                            x: theme.padCard
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.round(theme.em * 0.55)
                            height: width
                            radius: width / 2
                            color: entry.overlayOn ? entry.model.color : "transparent"
                            border.width: entry.overlayOn ? 0 : 1
                            border.color: theme.dimText
                        }
                        Text {
                            anchors.left: stateDot.right
                            anchors.leftMargin: theme.space4
                            anchors.right: badge.visible ? badge.left : customized.left
                            anchors.rightMargin: theme.space2
                            anchors.verticalCenter: parent.verticalCenter
                            text: entry.label
                            textFormat: Text.PlainText
                            color: entry.dimmed ? theme.dimOn(entry.color) : theme.text
                            font.weight: entry.selected ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                        TpText {  // options changed from default
                            id: customized
                            role: "caption"
                            tabular: true
                            elide: Text.ElideNone
                            visible: !badge.visible && entry.customized > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.space4
                            anchors.verticalCenter: parent.verticalCenter
                            text: visible ? entry.customized : ""
                            color: theme.dimOn(entry.color)
                        }
                        TpCountBadge {  // same badge as the Settings sections: invalid values in error tone with "!"
                            id: badge
                            visible: entry.badgeCount > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.space3
                            anchors.verticalCenter: parent.verticalCenter
                            size: "sm"
                            text: entry.badgeCount
                            tone: entry.errors > 0 && !(backend.filtering && backend.scopeAll) ? "error"
                                : backend.filtering && backend.scopeAll ? "neutral" : "accent"
                        }
                        MouseArea {
                            id: entryArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                backend.selectOverlay(entry.key)
                                nav.forceActiveFocus()
                            }
                        }
                        ToolTip.visible: entryArea.containsMouse && entry.customized > 0
                        ToolTip.text: ToolTip.visible ? i18n.trm("Modified: " + entry.customized) : ""
                        ToolTip.delay: theme.tipDelay
                    }
                }
            }
        }
        Rectangle {
            visible: !page.narrow
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: theme.strokeSubtle
        }

        // Options
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Narrow page: overlay choice
            TpCombo {
                id: overlayChoice
                visible: page.narrow
                Layout.fillWidth: true
                Layout.margins: theme.padPage
                Layout.bottomMargin: 0
                readonly property var keys: backend.overlayKeys
                model: backend.overlayLabels
                currentIndex: keys.indexOf(backend.overlay)
                tip: i18n.tr("Find overlay")
                onActivated: function(index) { backend.selectOverlay(keys[index]) }
            }

            // Header: icon tile, title (TpText title role, as TpPageHeader), details, switch & actions toolbar. Own
            // row: TpPageHeader has no leading icon nor shrinking toolbar
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: theme.padPopup
                Layout.rightMargin: theme.padPopup
                Layout.topMargin: theme.padPage
                spacing: theme.padCard
                TpIconTile {
                    Layout.preferredWidth: size
                    Layout.preferredHeight: size
                    size: Math.round(theme.iconHero)  // page badge
                    tint: backend.filtering && backend.scopeAll || page.info.color === "" ? theme.accent : page.info.color
                    glyph: backend.filtering && backend.scopeAll ? "" : ""  // search, sliders
                    fallbackText: page.info.label || ""
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: theme.em * 12  // room shared with the header actions (texts cut first)
                    Layout.minimumWidth: theme.em * 6
                    spacing: 0
                    TpText {
                        Layout.fillWidth: true
                        role: "title"
                        text: backend.filtering && backend.scopeAll
                              ? (backend.searching ? i18n.tr("Search results") : i18n.tr("Modified options"))
                              : page.info.label
                    }
                    TpText {
                        Layout.fillWidth: true
                        color: theme.dimText
                        text: backend.filtering && backend.scopeAll
                              ? i18n.trm("Found: " + backend.matchCount) + "  ·  " + i18n.tr("Every overlay")
                              : [page.info.category, page.info.design, i18n.trm("Options: " + page.info.optionCount),
                                 page.info.customized > 0 ? i18n.trm("Modified: " + page.info.customized) : "",
                                 i18n.trm("Preset: " + page.info.preset)]
                                .filter(function(part) { return part !== "" }).join("  ·  ")
                    }
                }
                TpButton {  // display profile set: some options follow it (click: show the option)
                    visible: !(backend.filtering && backend.scopeAll) && page.info.profile !== ""
                    flat: true
                    size: "sm"
                    glyph: ""  // filter
                    text: page.info.profile
                    tip: i18n.tr("Options set by this profile show its value: changing one switches to Custom. Click to show the option.")
                    onClicked: backend.showOption(page.info.profileOption)
                }
                // On or off at once (as on the Overlays page), never a pending edit
                TpSwitch {
                    objectName: "overlayEnabledSwitch"
                    visible: !page.everyOverlay && page.info.name !== ""
                    checkable: false  // follows backend
                    checked: page.info.enabled === true
                    text: page.info.enabled ? i18n.tr("Enabled") : i18n.tr("Disabled")
                    tip: i18n.tr("Turn this overlay on or off now (not a pending change)")
                    onClicked: backend.setOverlayEnabled(!page.info.enabled)
                }
                // Header actions: texts, then icons only, then a "⋯" menu as room runs out
                TpToolbar {
                    objectName: "headerToolbar"
                    Layout.fillWidth: true
                    TpAction {
                        name: "testOnScreenButton"
                        text: backend.testing ? i18n.tr("Stop Test") : i18n.tr("Test on Screen")
                        glyph: ""  // monitor
                        fallback: "▶"
                        tip: i18n.tr("Overlays on screen show the race situation chosen under the preview for a few seconds (saved values)")
                        priority: 4
                        flat: true
                        checked: backend.testing
                        onTriggered: backend.testOnScreen()
                    }
                    TpAction {
                        name: "previewDrawerButton"
                        shown: !page.previewShown && !page.everyOverlay
                        text: i18n.tr("Preview")
                        glyph: ""  // view
                        fallback: "◧"
                        tip: i18n.tr("Show or hide the live preview")
                        priority: 3
                        flat: true
                        checked: page.previewOpen
                        onTriggered: {
                            page.previewOpen = !page.previewOpen
                            page.forceActiveFocus()  // Esc reaches the page: closes the preview, never the page
                        }
                    }
                    TpAction {
                        shown: !page.everyOverlay
                        text: i18n.tr("Reset Overlay")
                        glyph: theme.glyphs.reset
                        fallback: "↺"
                        tip: i18n.tr("Every option of this overlay back to default (saved with Apply)")
                        priority: 2
                        flat: true
                        onTriggered: backend.resetOverlay()
                    }
                    TpAction {
                        text: i18n.tr("Share")
                        glyph: theme.glyphs.share
                        fallback: "⇪"
                        tip: i18n.tr("Export or import overlay settings as a file")
                        priority: 1
                        flat: true
                        onTriggered: function(source) { shareMenu.toggleBelow(source) }
                    }
                    TpAction {
                        shown: !backend.filtering
                        glyph: ""  // chevron up
                        fallback: "▲"
                        tip: i18n.tr("Collapse All")
                        flat: true
                        onTriggered: backend.setAllCollapsed(true)
                    }
                    TpAction {
                        shown: !backend.filtering
                        glyph: ""  // chevron down
                        fallback: "▼"
                        tip: i18n.tr("Expand All")
                        flat: true
                        onTriggered: backend.setAllCollapsed(false)
                    }
                    onMenuClosed: list.forceActiveFocus()
                }
            }

            // Search & filters
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: theme.padPopup
                Layout.rightMargin: theme.padPopup
                Layout.topMargin: theme.space4
                Layout.bottomMargin: theme.space3
                spacing: theme.space3
                TpSearchField {
                    id: search
                    objectName: "optionSearch"
                    width: Math.max(theme.em * 12, Math.min(theme.em * 22, parent.width - scope.width - filtersButton.width - theme.em * 1.5))
                    placeholderText: i18n.tr("Search options") + "   Ctrl+F"
                    onSearchChanged: function(text) { backend.setSearch(text) }
                    onExitField: list.forceActiveFocus()
                }
                TpSegmented {
                    id: scope
                    name: i18n.tr("Where search & filter look")
                    options: [i18n.tr("This overlay"), i18n.tr("Every overlay")]
                    currentIndex: backend.scopeAll ? 1 : 0
                    onActivated: function(index) { backend.setScopeAll(index === 1) }
                    ToolTip.visible: scopeArea.containsMouse
                    ToolTip.text: i18n.tr("Where search & filter look")
                    ToolTip.delay: theme.tipDelay
                    MouseArea { id: scopeArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
                // Filters, display profiles & color themes: buttons opening a menu (never a list whose arrows
                // would apply an entry)
                TpButton {
                    id: filtersButton
                    objectName: "filtersButton"
                    flat: true
                    glyph: ""  // filter
                    fallback: "▾"
                    text: i18n.tr("Filters") + (page.filterCount > 0 ? " (" + page.filterCount + ")" : "") + " ▾"
                    tip: i18n.tr("Changed Only: options changed from default. Used Only: hides options doing nothing with current values.")
                    checked: page.filterCount > 0 || filtersMenu.visible
                    onClicked: filtersMenu.toggleBelow(filtersButton)
                }
                TpButton {
                    id: profileButton
                    objectName: "profileButton"
                    visible: (page.info.userProfiles || []).length > 0 && !page.everyOverlay
                    flat: true
                    text: i18n.tr("Profile") + " ▾"
                    tip: i18n.tr("Save shown items as a display profile, then pick it in Display Profile (saved with Apply or Save)")
                    checked: profileMenu.visible
                    onClicked: profileMenu.toggleBelow(profileButton)
                }
                TpButton {
                    id: themeButton
                    objectName: "themeButton"
                    visible: (page.info.themes || []).length > 0 && !page.everyOverlay
                    flat: true
                    text: i18n.tr("Theme") + " ▾"
                    tip: i18n.tr("Set every color to a theme (saved only with Apply or Save)")
                    checked: themeMenu.visible
                    onClicked: themeMenu.toggleBelow(themeButton)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                ListView {
                    id: list
                    property string shownOverlay: backend.overlay
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: backend.options
                    activeFocusOnTab: true
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true  // rows of other options & overlays reuse delegates (see OverlayOptionRow)
                    cacheBuffer: Math.round(theme.em * 30)
                    leftMargin: theme.padPopup
                    rightMargin: theme.padPopup
                    bottomMargin: theme.space6
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    Keys.onUpPressed: contentY = Math.max(originY, contentY - theme.em * 3)
                    Keys.onDownPressed: contentY = Math.max(originY, Math.min(originY + contentHeight - height, contentY + theme.em * 3))
                    delegate: OverlayOptionRow {
                        width: list.width - list.leftMargin - list.rightMargin
                        onMenuRequested: function(data, anchor, x, y) { page.openRowMenu(data, anchor, x, y) }
                    }
                    footer: Item {
                        width: list.width - list.leftMargin - list.rightMargin
                        height: backend.truncatedCount > 0 ? moreText.implicitHeight + theme.space6 * 2 : 0
                        Text {
                            id: moreText
                            visible: backend.truncatedCount > 0
                            anchors.centerIn: parent
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            text: i18n.trm("More options found: " + backend.truncatedCount) + "  ·  " + i18n.tr("Type more words to narrow the search")
                            textFormat: Text.PlainText
                            color: theme.dimText
                        }
                    }

                    TpStateView {
                        empty: list.count === 0
                        width: list.width - list.leftMargin - list.rightMargin
                        topPadding: theme.em * 3
                        glyph: backend.searching ? "" : ""  // search, check
                        title: backend.searching ? i18n.tr("No option found")
                             : backend.modifiedOnly ? i18n.tr("Every option has its default value") : ""
                        text: backend.searching
                              ? (backend.scopeAll ? i18n.tr("Search looks through every overlay. Check spelling, or try other words.")
                                                  : i18n.tr("Try searching every overlay, or other words."))
                              : ""
                        actionText: backend.searching && !backend.scopeAll ? i18n.tr("Search Every Overlay") : ""
                        onAction: backend.setScopeAll(true)
                    }
                }

                // Live preview on simulated race values: fit to panel or zoomed (Ctrl+wheel, double click),
                // panel widened on demand. Zoomed overlay drawn bigger (sharp), see backend.setPreviewScale
                Rectangle {
                    id: previewPanel
                    objectName: "previewPanel"
                    property real zoom: 0  // 0: fit to panel, else size relative to overlay
                    property bool expanded: false
                    readonly property var zoomSteps: [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3]
                    readonly property real baseWidth: backend.previewScale > 0 ? backend.previewWidth / backend.previewScale : 0
                    readonly property real baseHeight: backend.previewScale > 0 ? backend.previewHeight / backend.previewScale : 0
                    readonly property real fitZoom: baseWidth > 0 && baseHeight > 0 && previewFlick.width > 0
                        ? Math.max(0.1, Math.min(previewFlick.width / baseWidth, previewFlick.height / baseHeight, 3)) : 1
                    readonly property real shownZoom: zoom > 0 ? zoom : fitZoom

                    function zoomStep(direction) {
                        var current = shownZoom
                        var steps = zoomSteps
                        if (direction > 0) {
                            for (var i = 0; i < steps.length; i++) {
                                if (steps[i] > current + 0.01) {
                                    zoom = steps[i]
                                    return
                                }
                            }
                        } else {
                            for (var j = steps.length - 1; j >= 0; j--) {
                                if (steps[j] < current - 0.01) {
                                    zoom = steps[j]
                                    return
                                }
                            }
                        }
                    }

                    visible: (page.previewShown || page.previewOpen) && !page.everyOverlay
                    Layout.fillHeight: true
                    Layout.preferredWidth: Math.min(expanded ? Math.max(Math.round(theme.em * 21), Math.round(parent.width * 0.5))
                                                             : Math.round(theme.em * 21),
                                                    page.previewShown ? parent.width : Math.round(parent.width * 0.5))
                    Behavior on Layout.preferredWidth { NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutCubic } }
                    Layout.bottomMargin: theme.padPopup
                    Layout.rightMargin: theme.padPopup
                    radius: theme.radiusLg
                    color: theme.surfaceCard
                    border.width: 1
                    border.color: theme.cardBorder

                    onShownZoomChanged: scaleTimer.restart()
                    // hidden (narrow page, search of every overlay): edits not drawn for nothing
                    onVisibleChanged: backend.setPreviewVisible(visible)
                    Component.onCompleted: {
                        backend.setPreviewVisible(visible)
                        scaleTimer.restart()
                    }
                    Timer {  // drawn again at new size once zoom & panel width settle
                        id: scaleTimer
                        interval: 200
                        onTriggered: backend.setPreviewScale(previewPanel.shownZoom)
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: theme.padCard
                        spacing: theme.space3
                        RowLayout {
                            Layout.fillWidth: true
                            Icon { glyph: ""; color: theme.dimText }  // view
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Text {
                                    Layout.fillWidth: true
                                    text: i18n.tr("Live Preview")
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: backend.previewCompare && page.info.canCompare
                                          ? page.info.otherDesign + " · " + page.info.designOptions
                                          : i18n.tr("Simulated race values")
                                    textFormat: Text.PlainText
                                    color: theme.dimText
                                    font.pointSize: theme.fontSmall
                                    elide: Text.ElideRight
                                }
                            }
                            TpSwitch {
                                checkable: false
                                checked: backend.previewEnabled
                                tip: i18n.tr("Draw overlay with unsaved values")
                                onClicked: backend.setPreviewEnabled(!backend.previewEnabled)
                            }
                            TpButton {  // opened by the header's Preview button: closed here (or Esc)
                                objectName: "closePreviewButton"
                                visible: !page.previewShown
                                flat: true
                                size: "sm"
                                glyph: "\uE711"  // cancel
                                fallback: "✕"
                                tip: i18n.tr("Close Preview")
                                onClicked: page.previewOpen = false
                            }
                        }
                        Rectangle {  // dark stage: overlays are drawn for a game picture
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: theme.radiusMd
                            gradient: Gradient {
                                GradientStop { position: 0; color: theme.stageTop }
                                GradientStop { position: 1; color: theme.stageBottom }
                            }
                            clip: true
                            Flickable {
                                id: previewFlick
                                anchors.fill: parent
                                anchors.margins: theme.space3
                                contentWidth: Math.max(width, previewImage.width)
                                contentHeight: Math.max(height, previewImage.height)
                                boundsBehavior: Flickable.StopAtBounds
                                interactive: contentWidth > width || contentHeight > height
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                                Image {
                                    id: previewImage
                                    visible: backend.previewState === 2 || backend.previewState === 4
                                    x: Math.max(0, (previewFlick.contentWidth - width) / 2)
                                    y: Math.max(0, (previewFlick.contentHeight - height) / 2)
                                    width: Math.round(previewPanel.baseWidth * previewPanel.shownZoom)
                                    height: Math.round(previewPanel.baseHeight * previewPanel.shownZoom)
                                    // Played on a moving simulated race, else the still picture
                                    source: backend.liveUrl !== "" && backend.previewState === 2 ? backend.liveUrl
                                                                                               : backend.previewUrl
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    mipmap: false  // decoded at shown size (sourceSize below): no mipmaps
                                    // Old picture kept while the new one decodes off the UI thread
                                    asynchronous: true
                                    retainWhileLoading: true
                                    cache: false  // one picture per edit: never shown again
                                    sourceSize.width: Math.ceil(width * Screen.devicePixelRatio / 32) * 32
                                    opacity: backend.previewState === 4 ? 0.4 : 1  // picture only: invalid value, old picture
                                    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                                    // Overlays with parts (black box): click a part to show its options
                                    HoverHandler {
                                        enabled: page.info.previewParts === true
                                        cursorShape: Qt.PointingHandCursor
                                    }
                                    TapHandler {
                                        enabled: page.info.previewParts === true
                                        onSingleTapped: function(eventPoint) {
                                            var left = (previewImage.width - previewImage.paintedWidth) / 2
                                            var top = (previewImage.height - previewImage.paintedHeight) / 2
                                            backend.previewClicked((eventPoint.position.x - left) / previewImage.paintedWidth,
                                                                   (eventPoint.position.y - top) / previewImage.paintedHeight)
                                        }
                                    }
                                }
                                TapHandler {
                                    onDoubleTapped: previewPanel.zoom = previewPanel.zoom > 0 ? 0 : 1
                                }
                                WheelHandler {
                                    acceptedModifiers: Qt.ControlModifier
                                    onWheel: function(event) {
                                        previewPanel.zoomStep(event.angleDelta.y > 0 ? 1 : -1)
                                    }
                                }
                            }
                            Text {
                                anchors.centerIn: parent
                                width: parent.width - theme.em * 2
                                visible: backend.previewState !== 2
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                                text: backend.previewState === 0 ? i18n.tr("Preview off")
                                    : backend.previewState === 1 ? i18n.tr("Drawing preview…")
                                    : backend.previewState === 3 ? i18n.tr("Preview not available for this overlay")
                                    : i18n.tr("Invalid value, preview not updated")
                                textFormat: Text.PlainText
                                color: theme.stageText
                            }
                        }
                        // Zoom & panel size, then compare, race situation & test: wraps on two lines in the
                        // narrow panel (21 em) instead of squeezing the buttons
                        Flow {
                            Layout.fillWidth: true
                            spacing: theme.space3
                            enabled: backend.previewEnabled
                            Row {
                                spacing: theme.space1
                                TpButton {
                                    flat: true
                                    checked: backend.previewPlaying && backend.previewAnimated
                                    enabled: backend.previewAnimated
                                    glyph: backend.previewPlaying ? "" : ""  // pause, play
                                    fallback: backend.previewPlaying ? "II" : "\u25b6"
                                    tip: !backend.previewAnimated
                                         ? i18n.tr("This overlay shows a fixed sample: it is not played")
                                         : backend.previewPlaying ? i18n.tr("Pause: still picture of the simulated race")
                                         : i18n.tr("Play: overlay on a simulated race driving a corner in a loop")
                                    onClicked: backend.setPreviewPlaying(!backend.previewPlaying)
                                }
                                TpButton {
                                    flat: true
                                    glyph: ""  // zoom out
                                    fallback: "−"
                                    tip: i18n.tr("Zoom Out (Ctrl+Wheel)")
                                    enabled: previewPanel.shownZoom > previewPanel.zoomSteps[0] + 0.01
                                    onClicked: previewPanel.zoomStep(-1)
                                }
                                TpButton {
                                    flat: true
                                    width: Math.max(implicitWidth, theme.em * 4.5)
                                    text: previewPanel.zoom > 0 ? Math.round(previewPanel.zoom * 100) + " %" : i18n.tr("Fit")
                                    tip: previewPanel.zoom > 0 ? i18n.tr("Fit to Panel (double click)")
                                                               : i18n.tr("Actual Size (double click)")
                                    onClicked: previewPanel.zoom = previewPanel.zoom > 0 ? 0 : 1
                                }
                                TpButton {
                                    flat: true
                                    glyph: ""  // zoom in
                                    fallback: "+"
                                    tip: i18n.tr("Zoom In (Ctrl+Wheel)")
                                    enabled: previewPanel.shownZoom < previewPanel.zoomSteps[previewPanel.zoomSteps.length - 1] - 0.01
                                    onClicked: previewPanel.zoomStep(1)
                                }
                                TpButton {
                                    flat: true
                                    checked: previewPanel.expanded
                                    glyph: previewPanel.expanded ? "" : ""  // shrink, enlarge
                                    fallback: previewPanel.expanded ? i18n.tr("Shrink") : i18n.tr("Enlarge")
                                    tip: previewPanel.expanded ? i18n.tr("Shrink Preview Panel") : i18n.tr("Enlarge Preview Panel")
                                    onClicked: previewPanel.expanded = !previewPanel.expanded
                                }
                            }
                            TpButton {
                                flat: true
                                visible: page.info.canCompare === true
                                checked: backend.previewCompare
                                text: i18n.tr("Other Design")
                                tip: page.info.canCompare ? i18n.tr("Compare: same values drawn by the other design") + "\n"
                                                            + page.info.otherDesign + " · " + page.info.designOptions : ""
                                onClicked: backend.setPreviewCompare(!backend.previewCompare)
                            }
                            TpCombo {
                                width: Math.min(theme.em * 10, parent.width)
                                model: backend.scenarioNames
                                currentIndex: backend.previewScenario
                                tip: i18n.tr("Race situation of preview: shows what overlays draw only then")
                                onActivated: function(index) { backend.setPreviewScenario(index) }
                            }
                        }
                    }
                }
            }

            // Unsaved changes. After Discard the bar stays a few seconds with Undo (Ctrl+Z works too)
            TpPendingBar {
                objectName: "pendingBar"
                pendingCount: backend.pendingCount
                errorCount: backend.errorCount
                firstError: backend.firstError
                detail: backend.pendingOverlays > 1 ? i18n.trm("Overlays: " + backend.pendingOverlays) : ""
                canUndo: backend.canUndo
                canRedo: backend.canRedo
                onShowErrorRequested: backend.showFirstError()
                onUndoRequested: {
                    page.commitEdits()  // field being edited left first: shows undone value, never sent again
                    backend.undo()
                }
                onRedoRequested: {
                    page.commitEdits()  // field being edited left first: shows redone value, never sent again
                    backend.redo()
                }
                onDiscardRequested: {
                    page.commitEdits()  // focus left: typed value dropped too, field shows saved value
                    backend.discard()
                }
                onApplyRequested: {
                    page.commitEdits()
                    backend.apply()
                }
            }
        }
    }
    // Dialogs & toasts asked by the backend (confirmations, alerts, messages with Undo)
    TpDialogHost {}
}
