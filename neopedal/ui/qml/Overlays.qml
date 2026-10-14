import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Overlays page: title & counts, search, All / Active / Inactive, category chips, overlays as cards with
// preview (grid) or compact rows (list), enable / disable all shown overlays. Rows animate in & out.
// Keys: type to search, "/" search, arrows move, Space switches, Enter opens settings, Menu key the menu.
TpPage {
    id: page

    readonly property bool grid: backend.gridView
    readonly property real cardMinWidth: theme.em * 14.5
    readonly property var categoryCounts: backend.categoryCounts

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }
    function openMenu(item, x, y, entry) {
        cardMenu.name = entry.name
        cardMenu.active = entry.active
        cardMenu.category = entry.category
        cardMenu.categoryLabel = entry.categoryLabel
        cardMenu.popup(item, x, y)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.8
        anchors.bottomMargin: theme.em * 0.6
        spacing: theme.em * 0.6

        // Title, counts & view
        TpPageHeader {
            title: i18n.tr("Overlays")
            count: i18n.trm(backend.activeCount + " / " + backend.totalCount + " enabled")
            countActive: backend.activeCount > 0
            TpButton {
                id: shareButton
                flat: true
                glyph: ""  // export
                text: i18n.tr("Share")
                tip: i18n.tr("Export or import overlay settings as a file")
                onClicked: shareMenu.popup(shareButton, 0, shareButton.height)
            }
            // Grid / list switch
            Rectangle {
                implicitHeight: Math.round(theme.em * 2.3)
                implicitWidth: viewRow.implicitWidth + 6
                radius: theme.radiusLg
                color: theme.dark ? Qt.darker(theme.base, 1.25) : Qt.darker(theme.window, 1.04)
                border.width: 1
                border.color: theme.border
                Row {
                    id: viewRow
                    anchors.centerIn: parent
                    spacing: 2
                    TpButton {
                        flat: true
                        checked: page.grid
                        glyph: ""  // grid view
                        text: theme.iconFont === "" ? i18n.tr("Cards") : ""
                        tip: i18n.tr("Cards with preview")
                        implicitHeight: Math.round(theme.em * 2.3) - 6
                        onClicked: backend.setGridView(true)
                        Accessible.name: i18n.tr("Cards with preview")
                    }
                    TpButton {
                        flat: true
                        checked: !page.grid
                        glyph: ""  // bulleted list
                        text: theme.iconFont === "" ? i18n.tr("List") : ""
                        tip: i18n.tr("Compact list")
                        implicitHeight: Math.round(theme.em * 2.3) - 6
                        onClicked: backend.setGridView(false)
                        Accessible.name: i18n.tr("Compact list")
                    }
                }
            }
        }

        // Search & state filter
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            TpSearchField {
                id: search
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                focus: true
                searchDelay: 0  // overlay list filtered at once
                placeholderText: i18n.tr("Search overlays") + "   /"
                Accessible.name: i18n.tr("Search overlays")
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: overlays.forceActiveFocus()
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
                options: [i18n.tr("All"), i18n.tr("Active"), i18n.tr("Inactive")]
                currentIndex: backend.stateFilter
                onActivated: function(index) { backend.setStateFilter(index) }
            }
        }

        // Category chips
        Flow {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            Repeater {
                model: backend.categories
                OverlayChip {
                    required property var modelData
                    text: modelData.label
                    showDot: modelData.key !== ""
                    dotColor: modelData.color !== "" ? modelData.color : "transparent"
                    count: page.categoryCounts[modelData.key] || 0
                    selected: backend.category === modelData.key
                    onClicked: backend.setCategory(selected && modelData.key !== "" ? "" : modelData.key)
                }
            }
        }

        // Safe mode & start errors
        Rectangle {
            Layout.fillWidth: true
            visible: backend.safeMode || backend.failedCount > 0
            implicitHeight: noticeRow.implicitHeight + theme.em * 0.9
            radius: theme.radiusLg
            color: Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.12)
            border.width: 1
            border.color: Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.6)
            RowLayout {
                id: noticeRow
                anchors.fill: parent
                anchors.leftMargin: theme.em * 0.7
                anchors.rightMargin: theme.em * 0.4
                spacing: theme.em * 0.5
                Icon { glyph: ""; color: theme.warning }  // warning
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: theme.text
                    text: backend.safeMode
                        ? i18n.tr("Safe mode: overlays are not started. Restart normally to show them.")
                        : backend.failedCount === 1 ? i18n.tr("1 overlay could not start, see log.")
                        : i18n.trm(backend.failedCount + " overlays could not start, see log.")
                }
                TpButton {
                    visible: !backend.safeMode
                    flat: true
                    text: i18n.tr("Show Log")
                    onClicked: backend.showLog()
                }
            }
        }

        // Overlays
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            GridView {
                id: overlays
                anchors.fill: parent
                anchors.leftMargin: -Math.round(theme.em * 0.3)  // card margins aligned with header
                anchors.rightMargin: -Math.round(theme.em * 0.3)
                clip: true
                model: backend.model
                readonly property int columns: page.grid ? Math.max(1, Math.floor(width / page.cardMinWidth)) : 1
                cellWidth: Math.floor((width - theme.em * 0.7) / columns)  // room for scroll bar
                cellHeight: page.grid ? Math.round(cellWidth * 0.52 + theme.em * 3.4) : Math.round(theme.em * 2.8)
                cacheBuffer: Math.max(0, cellHeight * 2)
                reuseItems: true  // delegates reset their transient state when pooled (see OverlayCard)
                boundsBehavior: Flickable.StopAtBounds
                highlightFollowsCurrentItem: false
                keyNavigationEnabled: true
                activeFocusOnTab: true
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

            // Nothing shown
            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width - theme.em * 2, theme.em * 24)
                spacing: theme.em * 0.6
                visible: overlays.count === 0
                opacity: visible ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    glyph: ""  // search
                    size: theme.em * 2.6
                    color: theme.dimText
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: i18n.tr("No overlay matches the filters")
                    color: theme.text
                    font.pointSize: theme.fontSubtitle
                    font.weight: Font.DemiBold
                }
                TpButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: backend.filtered
                    text: i18n.tr("Clear Filters")
                    onClicked: { backend.clearFilters(); page.focusSearch() }
                }
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
                text: (backend.filtered
                    ? i18n.trm(backend.shownCount + " of " + backend.totalCount + " overlays shown")
                    : i18n.trm(backend.totalCount + " overlays"))
                    + (backend.gridView ? "  ·  " + i18n.tr("Previews show simulated race values") : "")
            }
            TpButton {
                text: backend.filtered ? i18n.tr("Enable Shown") : i18n.tr("Enable All")
                enabled: backend.shownCount > 0
                onClicked: backend.enableShown()
            }
            TpButton {
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
        property string category: ""
        property string categoryLabel: ""
        Action { text: i18n.tr("Config") + "..."; onTriggered: backend.openConfig(cardMenu.name) }
        Action {
            text: cardMenu.active ? i18n.tr("Disable") : i18n.tr("Enable")
            onTriggered: backend.toggle(cardMenu.name)
        }
        Action { text: i18n.tr("Export Settings..."); onTriggered: backend.exportSettings(cardMenu.name) }
        MenuSeparator {}
        Action {
            id: showOnlyAction
            text: i18n.trm("Show only " + cardMenu.categoryLabel)
            enabled: backend.category !== cardMenu.category
            onTriggered: backend.setCategory(cardMenu.category)
        }
    }
    TextMetrics { id: shareMetrics; text: i18n.tr("Import Overlay Settings...") }
    TpMenu {
        id: shareMenu
        width: Math.max(theme.em * 13, shareMetrics.advanceWidth + theme.em * 3.8)  // longest item never cut
        Action { text: i18n.tr("Export Overlay Settings..."); onTriggered: backend.exportSettings("") }
        Action { text: i18n.tr("Import Overlay Settings..."); onTriggered: backend.importSettings() }
        onClosed: overlays.forceActiveFocus()
    }
}
