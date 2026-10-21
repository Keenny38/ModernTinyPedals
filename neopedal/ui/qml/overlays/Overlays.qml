import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Overlays page: title & counts, loaded preset, search, All / Active / Inactive, chips (favorites, recently edited,
// categories), overlays as cards with preview (grid), compact rows (list) or at their place on the screens
// (screen view), enable / disable all shown overlays. Rows animate in & out; a hovered card plays its overlay.
// Keys: type to search, "/" search, arrows move, Space switches, Enter opens settings, Menu key the menu.
TpPage {
    id: page

    readonly property int view: backend.viewMode  // 0 cards, 1 list, 2 screen
    readonly property bool grid: view === 0
    readonly property real cardMinWidth: theme.em * 14.5
    readonly property var categoryCounts: backend.categoryCounts
    readonly property var stateCounts: backend.stateCounts
    property var presetList: []  // presets of header menu, read when it opens

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }
    function openMenu(item, x, y, entry) {
        cardMenu.name = entry.name
        cardMenu.active = entry.active
        cardMenu.favorite = entry.favorite
        cardMenu.category = entry.category
        cardMenu.categoryLabel = entry.categoryLabel
        cardMenu.popup(item, x, y)
    }
    function stateText(index, text) {
        return stateCounts.length > index ? text + "  " + stateCounts[index] : text
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        anchors.bottomMargin: theme.space4
        spacing: theme.space4

        // Title, counts, preset & view
        TpPageHeader {
            title: i18n.tr("Overlays")
            count: i18n.trm(backend.activeCount + " / " + backend.totalCount + " enabled")
            countActive: backend.activeCount > 0
            TpButton {
                id: presetButton
                flat: true
                glyph: backend.presetLocked ? "" : ""  // lock : library
                text: backend.presetName
                Layout.maximumWidth: theme.em * 13
                tip: (backend.presetLocked ? i18n.tr("Loaded preset (locked)") : i18n.tr("Loaded preset"))
                     + ": " + backend.presetName + "\n" + i18n.tr("Click to load another preset")
                onClicked: presetMenu.popup(presetButton, 0, presetButton.height)
            }
            TpButton {
                id: shareButton
                flat: true
                glyph: ""  // export
                text: i18n.tr("Share")
                tip: i18n.tr("Export or import overlay settings as a file")
                onClicked: shareMenu.popup(shareButton, 0, shareButton.height)
            }
            TpButton {
                id: sortButton
                flat: true
                visible: page.view !== 2
                glyph: ""  // sort
                fallback: "⇅"
                tip: i18n.tr("Sort overlays")
                onClicked: sortMenu.popup(sortButton, 0, sortButton.height)
            }
            // Cards / list / screen switch
            Rectangle {
                implicitHeight: theme.controlHeight
                implicitWidth: viewRow.implicitWidth + theme.space2 * 2
                radius: theme.radiusLg
                color: theme.dark ? Qt.darker(theme.base, 1.25) : Qt.darker(theme.window, 1.04)
                border.width: 1
                border.color: theme.border
                Row {
                    id: viewRow
                    anchors.centerIn: parent
                    spacing: theme.space1
                    TpButton {
                        flat: true
                        size: "sm"
                        checked: page.view === 0
                        glyph: ""  // grid view
                        fallback: i18n.tr("Cards")
                        tip: i18n.tr("Cards with preview")
                        onClicked: backend.setViewMode(0)
                    }
                    TpButton {
                        flat: true
                        size: "sm"
                        checked: page.view === 1
                        glyph: ""  // bulleted list
                        fallback: i18n.tr("List")
                        tip: i18n.tr("Compact list")
                        onClicked: backend.setViewMode(1)
                    }
                    TpButton {
                        flat: true
                        size: "sm"
                        checked: page.view === 2
                        glyph: ""  // monitor
                        fallback: i18n.tr("Screen")
                        tip: i18n.tr("Running overlays at their place on your screens")
                        onClicked: backend.setViewMode(2)
                    }
                }
            }
        }

        // Search & state filter
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space4
            TpSearchField {
                id: search
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                focus: true
                searchDelay: 0  // overlay list filtered at once
                placeholderText: i18n.tr("Search overlays") + "   /"
                Accessible.name: i18n.tr("Search overlays")
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: page.view === 2 && screenLoader.item ? screenLoader.item.forceActiveFocus() : overlays.forceActiveFocus()
                Keys.onReturnPressed: overlays.forceActiveFocus()
                Keys.onEnterPressed: overlays.forceActiveFocus()
                Connections {
                    target: backend
                    function onFilterChanged() {
                        if (search.text !== backend.searchText)
                            search.text = backend.searchText
                    }
                }
            }
            TpSegmented {
                name: i18n.tr("Overlay state")
                visible: page.view !== 2  // screen view: running overlays only
                options: [page.stateText(0, i18n.tr("All")), page.stateText(1, i18n.tr("Active")),
                          page.stateText(2, i18n.tr("Inactive"))]
                currentIndex: backend.stateFilter
                onActivated: function(index) { backend.setStateFilter(index) }
            }
        }

        // Favorites, recently edited & category chips
        Flow {
            Layout.fillWidth: true
            spacing: theme.space3
            Repeater {
                model: backend.categories
                TpChip {
                    required property var modelData
                    text: modelData.label
                    glyph: modelData.glyph
                    showDot: modelData.color !== ""
                    dotColor: modelData.color !== "" ? modelData.color : "transparent"
                    count: page.categoryCounts[modelData.key] || 0
                    selected: backend.category === modelData.key
                    tip: modelData.key === "#favorites" ? i18n.tr("Overlays marked with a star (every preset)")
                       : modelData.key === "#recent" ? i18n.tr("Overlays whose options you saved last, last first")
                       : ""
                    onClicked: backend.setCategory(selected && modelData.key !== "" ? "" : modelData.key)
                }
            }
        }

        // Safe mode & start errors
        TpNotice {
            visible: backend.safeMode || backend.failedCount > 0
            text: backend.safeMode
                ? i18n.tr("Safe mode: overlays are not started. Restart normally to show them.")
                : backend.failedCount === 1 ? i18n.tr("1 overlay could not start, see log.")
                : i18n.trm(backend.failedCount + " overlays could not start, see log.")
            actionText: backend.safeMode ? "" : i18n.tr("Show Log")
            onAction: backend.showLog()
        }

        // Overlays
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            GridView {
                id: overlays
                anchors.fill: parent
                anchors.leftMargin: -theme.space2  // card margins aligned with header
                anchors.rightMargin: -theme.space2
                visible: page.view !== 2
                clip: true
                model: backend.model
                readonly property int columns: page.grid ? Math.max(1, Math.floor(width / page.cardMinWidth)) : 1
                cellWidth: Math.floor((width - theme.em * 0.7) / columns)  // room for scroll bar
                cellHeight: page.grid ? Math.round(cellWidth * 0.52 + theme.em * 3.4) : Math.round(theme.row)
                cacheBuffer: Math.max(0, cellHeight * 2)
                reuseItems: true  // delegates reset their transient state when pooled (see OverlayCard)
                boundsBehavior: Flickable.StopAtBounds
                highlightFollowsCurrentItem: false
                keyNavigationEnabled: true
                activeFocusOnTab: visible
                delegate: page.grid ? cardDelegate : rowDelegate
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                // Rows on screen told to backend (previews of these rendered first), after scrolling settles
                function reportVisible() {
                    if (count === 0 || cellHeight <= 0)
                        return
                    var top = Math.max(0, contentY - originY)
                    var first = Math.floor(top / cellHeight) * columns
                    var last = Math.ceil((top + height) / cellHeight) * columns - 1
                    backend.setVisibleRows(first, Math.min(last, count - 1))
                }
                Timer {
                    id: visibleTimer
                    interval: 80
                    onTriggered: overlays.reportVisible()
                }
                onContentYChanged: visibleTimer.restart()
                onHeightChanged: visibleTimer.restart()
                onCountChanged: visibleTimer.restart()
                onCellHeightChanged: visibleTimer.restart()
                onColumnsChanged: visibleTimer.restart()
                Component.onCompleted: visibleTimer.restart()
                Connections {
                    target: backend
                    function onFilterChanged() { visibleTimer.restart() }  // other rows, maybe same count
                }

                add: Transition {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase }
                    NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: theme.motionBase; easing.type: Easing.OutCubic }
                }
                remove: Transition {
                    NumberAnimation { property: "opacity"; to: 0; duration: theme.motionFast }
                    NumberAnimation { property: "scale"; to: 0.94; duration: theme.motionFast }
                }
                move: Transition {  // sorted again
                    NumberAnimation { properties: "x,y"; duration: theme.motionSlow; easing.type: Easing.OutCubic }
                }
                displaced: Transition {
                    NumberAnimation { properties: "x,y"; duration: theme.motionSlow; easing.type: Easing.OutCubic }
                    NumberAnimation { property: "opacity"; to: 1; duration: theme.motionSlow }  // add interrupted: never left faded
                    NumberAnimation { property: "scale"; to: 1; duration: theme.motionSlow }
                }

                Keys.onSpacePressed: if (currentItem) backend.toggle(currentItem.name)
                Keys.onReturnPressed: if (currentItem) backend.openConfig(currentItem.name)
                Keys.onEnterPressed: if (currentItem) backend.openConfig(currentItem.name)
                Keys.onMenuPressed: if (currentItem) page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem)
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_F && (event.modifiers & Qt.ControlModifier) && currentItem) {
                        backend.toggleFavorite(currentItem.name)  // Ctrl+F: favorite
                        event.accepted = true
                    } else if (search.routeTyped(event)) {  // type to search
                        event.accepted = true
                    }
                }
                onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
            }

            Component {
                id: cardDelegate
                OverlayCard {
                    id: cardItem
                    onMenuRequested: function(item, x, y) { page.openMenu(item, x, y, cardItem) }
                }
            }
            Component {
                id: rowDelegate
                OverlayListRow {
                    id: rowItem
                    menuOpen: cardMenu.visible
                    onMenuRequested: function(item, x, y) { page.openMenu(item, x, y, rowItem) }
                }
            }

            // Screen view: created when first shown
            Loader {
                id: screenLoader
                anchors.fill: parent
                active: page.view === 2 || item !== null
                visible: page.view === 2
                sourceComponent: OverlayScreenView {}
            }

            // Nothing shown
            EmptyState {
                anchors.centerIn: parent
                visible: page.view !== 2 && overlays.count === 0
                glyph: ""  // search
                title: backend.category === "#favorites" && !backend.searchText && backend.stateFilter === 0
                       ? i18n.tr("No favorite overlay yet: click the star of a card")
                       : i18n.tr("No overlay matches the filters")
                actionText: backend.filtered ? i18n.tr("Clear Filters") : ""
                onAction: { backend.clearFilters(); page.focusSearch() }
            }
        }

        // Shown count & batch actions on shown overlays
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Text {
                Layout.fillWidth: true
                elide: Text.ElideRight
                color: theme.dimText
                text: page.view === 2
                    ? i18n.tr("Drag an overlay to move it, click to open its settings")
                    : (backend.filtered
                        ? i18n.trm(backend.shownCount + " of " + backend.totalCount + " overlays shown")
                        : i18n.trm(backend.totalCount + " overlays"))
                      + (page.grid ? "  ·  " + i18n.tr("Previews show simulated race values") : "")
            }
            TpButton {
                visible: page.view === 2
                flat: true
                text: i18n.tr("Layout Editor")
                tip: i18n.tr("Place overlays on a game screenshot, with alignment guides")
                onClicked: backend.openLayoutEditor()
            }
            TpButton {
                visible: page.view !== 2
                text: backend.filtered ? i18n.tr("Enable Shown") : i18n.tr("Enable All")
                enabled: backend.shownCount > 0
                onClicked: backend.enableShown()
            }
            TpButton {
                visible: page.view !== 2
                text: backend.filtered ? i18n.tr("Disable Shown") : i18n.tr("Disable All")
                enabled: backend.shownCount > 0
                onClicked: backend.disableShown()
            }
        }
    }

    TextMetrics { id: menuMetrics; text: showOnlyAction.text }
    TpMenu {
        id: cardMenu
        width: Math.max(theme.em * 13, menuMetrics.advanceWidth + theme.em * 3.8)  // longest item never cut
        property string name: ""
        property bool active: false
        property bool favorite: false
        property string category: ""
        property string categoryLabel: ""
        Action { text: i18n.tr("Config") + "..."; onTriggered: backend.openConfig(cardMenu.name) }
        Action {
            text: cardMenu.active ? i18n.tr("Disable") : i18n.tr("Enable")
            onTriggered: backend.toggle(cardMenu.name)
        }
        Action {
            text: cardMenu.favorite ? i18n.tr("Remove from Favorites") : i18n.tr("Add to Favorites")
            onTriggered: backend.toggleFavorite(cardMenu.name)
        }
        Action { text: i18n.tr("Export Settings..."); onTriggered: backend.exportSettings(cardMenu.name) }
        MenuSeparator {}
        Action {
            id: showOnlyAction
            text: i18n.trm("Show only " + cardMenu.categoryLabel)
            enabled: backend.category !== cardMenu.category
            onTriggered: backend.setCategory(cardMenu.category)
        }
        onClosed: overlays.forceActiveFocus()
    }
    TextMetrics { id: shareMetrics; text: i18n.tr("Import Overlay Settings...") }
    TpMenu {
        id: shareMenu
        width: Math.max(theme.em * 13, shareMetrics.advanceWidth + theme.em * 3.8)  // longest item never cut
        Action { text: i18n.tr("Export Overlay Settings..."); onTriggered: backend.exportSettings("") }
        Action { text: i18n.tr("Import Overlay Settings..."); onTriggered: backend.importSettings() }
        onClosed: overlays.forceActiveFocus()
    }
    TpMenu {
        id: sortMenu
        TpMenuItem { text: i18n.tr("Sort by Name"); checkable: true; checked: backend.sortMode === 0; onTriggered: backend.setSortMode(0) }
        TpMenuItem { text: i18n.tr("Enabled First"); checkable: true; checked: backend.sortMode === 1; onTriggered: backend.setSortMode(1) }
        TpMenuItem { text: i18n.tr("Sort by Category"); checkable: true; checked: backend.sortMode === 2; onTriggered: backend.setSortMode(2) }
        onClosed: overlays.forceActiveFocus()
    }
    TpMenu {
        id: presetMenu
        onAboutToShow: page.presetList = backend.presetChoices()
        Instantiator {
            model: page.presetList
            delegate: TpMenuItem {
                required property var modelData
                text: modelData.name
                checkable: true
                checked: modelData.loaded
                onTriggered: backend.loadPreset(modelData.name)
            }
            onObjectAdded: function(index, object) { presetMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { presetMenu.removeItem(object) }
        }
        MenuSeparator {}
        Action { text: i18n.tr("Manage Presets..."); onTriggered: backend.openPresets() }
        onClosed: overlays.forceActiveFocus()
    }

    // Overlay moved from screen view: undo for a few seconds
    TpToast {
        id: movedToast
        actionText: i18n.tr("Undo")
        onAction: backend.undoMove()
        Connections {
            target: backend
            function onOverlayMoved(label) {
                movedToast.text = i18n.trm("Overlay moved: " + label)
                movedToast.show()
            }
        }
    }
}
