import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Overlay Options page: options of every overlay. Overlays on the left (by category, with unsaved edits,
// errors & search matches; a choice list on narrow pages), options of the selected overlay in section
// cards, live preview on the right (wide pages). Search in this overlay or in every overlay, "Modified"
// filter. Edits of any overlay stay pending until applied: bar at the bottom with Undo, Redo, Discard &
// Apply (Ctrl+S).
TpPage {
    id: page

    readonly property bool narrow: width < theme.em * 56
    readonly property bool previewShown: width >= theme.em * 74
    readonly property var info: backend.overlayInfo
    property var menuData: null  // option row of the "more" menu

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
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

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_F && (event.modifiers & Qt.ControlModifier)) {
            page.focusSearch()
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
        MenuItem {
            text: i18n.tr("Reset to Default")
            enabled: page.menuData !== null && page.menuData.modified && !page.menuData.locked
            onTriggered: backend.resetOption(page.menuData.key)
        }
        MenuItem {
            text: page.menuData !== null ? i18n.trm("Apply to All Overlays (" + page.menuData.shared + ")") : ""
            enabled: page.menuData !== null && page.menuData.shared > 0 && page.menuData.error === ""
            onTriggered: backend.applyToAll(page.menuData.key)
        }
        MenuSeparator {}
        MenuItem {
            text: i18n.tr("Copy Option Name")
            onTriggered: backend.copyText(page.menuData.option)
        }
        onClosed: list.forceActiveFocus()
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Overlays
        Rectangle {
            visible: !page.narrow
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(theme.em * 15.5)
            color: theme.dark ? Qt.darker(theme.window, 1.12) : Qt.darker(theme.window, 1.025)

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: theme.em * 0.6
                spacing: theme.em * 0.5

                TpSearchField {
                    id: navSearch
                    Layout.fillWidth: true
                    placeholderText: i18n.tr("Find overlay")
                    onSearchChanged: function(text) { backend.setNavFilter(text) }
                    onExitField: nav.forceActiveFocus()
                }
                TpSegmented {
                    Layout.fillWidth: true
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
                        height: Math.round(theme.em * 1.9)
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: theme.em * 0.5
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: theme.em * 0.25
                            text: parent.section
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                            font.weight: Font.DemiBold
                        }
                    }
                    delegate: Rectangle {
                        id: entry
                        required property var model
                        readonly property bool selected: backend.overlay === model.key && !(backend.filtering && backend.scopeAll)
                        readonly property bool dimmed: backend.filtering && backend.scopeAll && model.matches === 0
                        readonly property int badgeCount: backend.filtering && backend.scopeAll ? model.matches : model.changed
                        width: ListView.view.width
                        height: Math.round(theme.em * 2.2)
                        radius: theme.em * 0.5
                        color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.2 : 0.13)
                             : entryArea.containsMouse ? theme.hover : "transparent"
                        opacity: dimmed ? 0.45 : 1
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Accessible.role: Accessible.PageTab
                        Accessible.name: model.label
                        Accessible.selected: selected

                        Rectangle {
                            visible: entry.selected
                            width: Math.round(theme.em * 0.22)
                            height: parent.height * 0.5
                            radius: width / 2
                            anchors.verticalCenter: parent.verticalCenter
                            color: theme.accent
                        }
                        Rectangle {  // state: filled while overlay is on
                            id: stateDot
                            x: theme.em * 0.7
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.round(theme.em * 0.55)
                            height: width
                            radius: width / 2
                            color: entry.model.enabled ? entry.model.color : "transparent"
                            border.width: entry.model.enabled ? 0 : 1
                            border.color: theme.dimText
                        }
                        Text {
                            anchors.left: stateDot.right
                            anchors.leftMargin: theme.em * 0.55
                            anchors.right: badge.visible ? badge.left : customized.left
                            anchors.rightMargin: theme.em * 0.3
                            anchors.verticalCenter: parent.verticalCenter
                            text: entry.model.label
                            color: theme.text
                            font.weight: entry.selected ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                        Text {  // options changed from default
                            id: customized
                            visible: !badge.visible && entry.model.customized > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.em * 0.6
                            anchors.verticalCenter: parent.verticalCenter
                            text: visible ? entry.model.customized : ""
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                            font.features: { "tnum": 1 }
                        }
                        Rectangle {
                            id: badge
                            visible: entry.badgeCount > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.em * 0.5
                            anchors.verticalCenter: parent.verticalCenter
                            height: Math.round(theme.em * 1.3)
                            width: Math.max(height, badgeText.implicitWidth + theme.em * 0.6)
                            radius: height / 2
                            color: entry.model.errors > 0 && !(backend.filtering && backend.scopeAll) ? theme.loss
                                 : backend.filtering && backend.scopeAll ? theme.hover : theme.accent
                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: entry.badgeCount
                                color: backend.filtering && backend.scopeAll ? theme.text : "white"
                                font.pointSize: theme.fontPoint * 0.75
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                        }
                        MouseArea {
                            id: entryArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                backend.selectOverlay(entry.model.key)
                                nav.forceActiveFocus()
                            }
                        }
                        ToolTip.visible: entryArea.containsMouse && entry.model.customized > 0
                        ToolTip.text: i18n.trm("Modified: " + entry.model.customized)
                        ToolTip.delay: 700
                    }
                }
            }
        }
        Rectangle {
            visible: !page.narrow
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: theme.dark ? Qt.lighter(theme.window, 1.25) : theme.border
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
                Layout.margins: theme.em * 0.8
                Layout.bottomMargin: 0
                readonly property var keys: backend.overlayKeys
                model: backend.overlayLabels
                currentIndex: keys.indexOf(backend.overlay)
                onActivated: function(index) { backend.selectOverlay(keys[index]) }
            }

            // Header
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 1.0
                Layout.rightMargin: theme.em * 1.0
                Layout.topMargin: theme.em * 0.8
                spacing: theme.em * 0.7
                Rectangle {
                    Layout.preferredWidth: Math.round(theme.em * 2.6)
                    Layout.preferredHeight: Layout.preferredWidth
                    radius: theme.em * 0.6
                    readonly property color tint: backend.filtering && backend.scopeAll || page.info.color === ""
                                                  ? theme.accent : page.info.color
                    color: Qt.rgba(tint.r, tint.g, tint.b, theme.dark ? 0.2 : 0.14)
                    Icon {
                        anchors.centerIn: parent
                        glyph: backend.filtering && backend.scopeAll ? "" : ""  // search, sliders
                        color: parent.tint
                        size: theme.em * 1.3
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Text {
                        Layout.fillWidth: true
                        text: backend.filtering && backend.scopeAll
                              ? (backend.searching ? i18n.tr("Search results") : i18n.tr("Modified options"))
                              : page.info.label
                        color: theme.text
                        font.pointSize: theme.fontPoint * 1.45
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: backend.filtering && backend.scopeAll
                              ? i18n.trm("Found: " + backend.matchCount) + "  ·  " + i18n.tr("Every overlay")
                              : [page.info.category, page.info.design, i18n.trm("Options: " + page.info.optionCount),
                                 page.info.customized > 0 ? i18n.trm("Modified: " + page.info.customized) : "",
                                 i18n.trm("Preset: " + page.info.preset)]
                                .filter(function(part) { return part !== "" }).join("  ·  ")
                        color: theme.dimText
                        elide: Text.ElideRight
                    }
                }
                Pill {
                    visible: !(backend.filtering && backend.scopeAll) && page.info.name !== ""
                    text: page.info.enabled ? i18n.tr("On") : i18n.tr("Off")
                    tint: page.info.enabled ? theme.gain : theme.dimText
                    solid: page.info.enabled
                    tip: i18n.tr("Overlay state (saved)")
                }
                TpButton {
                    visible: !backend.filtering
                    flat: true
                    glyph: ""  // chevron up
                    text: theme.iconFont === "" ? "▲" : ""
                    tip: i18n.tr("Collapse All")
                    onClicked: backend.setAllCollapsed(true)
                }
                TpButton {
                    visible: !backend.filtering
                    flat: true
                    glyph: ""  // chevron down
                    text: theme.iconFont === "" ? "▼" : ""
                    tip: i18n.tr("Expand All")
                    onClicked: backend.setAllCollapsed(false)
                }
                TpButton {
                    visible: !(backend.filtering && backend.scopeAll)
                    flat: true
                    glyph: ""  // undo
                    text: page.narrow ? "" : i18n.tr("Reset Overlay")
                    tip: i18n.tr("Every option of this overlay back to default (saved with Apply)")
                    onClicked: backend.resetOverlay()
                }
            }

            // Search & filters
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 1.0
                Layout.rightMargin: theme.em * 1.0
                Layout.topMargin: theme.em * 0.6
                Layout.bottomMargin: theme.em * 0.4
                spacing: theme.em * 0.5
                TpSearchField {
                    id: search
                    width: Math.max(theme.em * 12, Math.min(theme.em * 22, parent.width - scope.width - modifiedSwitch.width - theme.em * 1.5))
                    placeholderText: i18n.tr("Search options") + "   Ctrl+F"
                    onSearchChanged: function(text) { backend.setSearch(text) }
                    onExitField: list.forceActiveFocus()
                }
                TpSegmented {
                    id: scope
                    options: [i18n.tr("This overlay"), i18n.tr("Every overlay")]
                    currentIndex: backend.scopeAll ? 1 : 0
                    onActivated: function(index) { backend.setScopeAll(index === 1) }
                    ToolTip.visible: scopeArea.containsMouse
                    ToolTip.text: i18n.tr("Where search & filter look")
                    ToolTip.delay: 700
                    MouseArea { id: scopeArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
                TpSwitch {
                    id: modifiedSwitch
                    checkable: false
                    checked: backend.modifiedOnly
                    text: i18n.tr("Changed only")
                    tip: i18n.tr("Show only options changed from default")
                    onClicked: backend.setModifiedOnly(!backend.modifiedOnly)
                }
                TpSwitch {
                    visible: page.info.simpleMode && !(backend.filtering && backend.scopeAll)
                    checkable: false
                    checked: backend.advanced
                    text: i18n.tr("Advanced Options")
                    tip: i18n.tr("Show every option, including colors, thresholds and labels")
                    onClicked: backend.setAdvanced(!backend.advanced)
                }
                TpCombo {
                    visible: page.info.themes.length > 0 && !(backend.filtering && backend.scopeAll)
                    width: theme.em * 11
                    model: [i18n.tr("Color Theme...")].concat(page.info.themes.map(function(entry) { return entry.label }))
                    currentIndex: 0
                    tip: i18n.tr("Set every color to a theme (saved only with Apply or Save)")
                    onActivated: function(index) {
                        if (index > 0)
                            backend.applyColorTheme(page.info.themes[index - 1].name)
                        currentIndex = 0
                    }
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
                    cacheBuffer: Math.round(theme.em * 30)
                    leftMargin: theme.em * 1.0
                    rightMargin: theme.em * 1.0
                    bottomMargin: theme.em * 1.2
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    Keys.onUpPressed: contentY = Math.max(originY, contentY - theme.em * 3)
                    Keys.onDownPressed: contentY = Math.max(originY, Math.min(originY + contentHeight - height, contentY + theme.em * 3))
                    delegate: OverlayOptionRow {
                        width: list.width - list.leftMargin - list.rightMargin
                        onMenuRequested: function(data, anchor) {
                            page.menuData = data
                            var point = anchor.mapToItem(page, 0, anchor.height)
                            rowMenu.popup(page, point.x + anchor.width - rowMenu.implicitWidth, point.y)
                        }
                    }
                    footer: Item {
                        width: list.width - list.leftMargin - list.rightMargin
                        height: backend.truncatedCount > 0 ? Math.round(theme.em * 3) : 0
                        Text {
                            visible: backend.truncatedCount > 0
                            anchors.centerIn: parent
                            text: i18n.trm("More options found: " + backend.truncatedCount) + "  ·  " + i18n.tr("Type more words to narrow the search")
                            color: theme.dimText
                        }
                    }

                    EmptyState {
                        visible: list.count === 0
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

                // Live preview
                Rectangle {
                    visible: page.previewShown && !(backend.filtering && backend.scopeAll)
                    Layout.fillHeight: true
                    Layout.preferredWidth: Math.round(theme.em * 21)
                    Layout.bottomMargin: theme.em * 1.0
                    Layout.rightMargin: theme.em * 1.0
                    radius: theme.em * 0.7
                    color: theme.base
                    border.width: 1
                    border.color: theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: theme.em * 0.7
                        spacing: theme.em * 0.5
                        RowLayout {
                            Layout.fillWidth: true
                            Icon { glyph: ""; color: theme.dimText }  // view
                            Text {
                                Layout.fillWidth: true
                                text: i18n.tr("Live Preview")
                                color: theme.text
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            TpSwitch {
                                checkable: false
                                checked: backend.previewEnabled
                                tip: i18n.tr("Draw overlay with unsaved values")
                                onClicked: backend.setPreviewEnabled(!backend.previewEnabled)
                            }
                        }
                        Rectangle {  // dark backdrop: overlays are drawn for a game picture
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: theme.em * 0.5
                            color: "#1E1F22"
                            clip: true
                            Flickable {
                                id: previewFlick
                                anchors.fill: parent
                                anchors.margins: theme.em * 0.5
                                contentWidth: width
                                contentHeight: Math.max(height, previewImage.height)
                                boundsBehavior: Flickable.StopAtBounds
                                interactive: contentHeight > height
                                Image {
                                    id: previewImage
                                    visible: backend.previewState === 2 || backend.previewState === 4
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: Math.min(previewFlick.width, backend.previewWidth)
                                    height: backend.previewWidth > 0 ? width * backend.previewHeight / backend.previewWidth : 0
                                    source: backend.previewUrl
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    mipmap: true
                                    cache: false
                                    opacity: backend.previewState === 4 ? 0.4 : 1
                                    Behavior on opacity { NumberAnimation { duration: 150 } }
                                }
                            }
                            Text {
                                anchors.centerIn: parent
                                width: parent.width - theme.em * 2
                                visible: backend.previewState !== 2
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                                text: backend.previewState === 0 ? i18n.tr("Preview off")
                                    : backend.previewState === 1 ? i18n.tr("Drawing preview...")
                                    : backend.previewState === 3 ? i18n.tr("Preview not available for this overlay")
                                    : i18n.tr("Invalid value, preview not updated")
                                color: "#C8CACF"
                            }
                        }
                    }
                }
            }

            // Pending changes
            Rectangle {
                id: bar
                readonly property bool shown: backend.pendingCount > 0
                Layout.fillWidth: true
                Layout.preferredHeight: shown ? barRow.implicitHeight + theme.em * 1.0 : 0
                clip: true
                color: theme.dark ? Qt.lighter(theme.window, 1.1) : Qt.darker(theme.window, 1.04)
                Behavior on Layout.preferredHeight { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                Rectangle { width: parent.width; height: 1; color: theme.border }

                RowLayout {
                    id: barRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: theme.em * 0.5
                    anchors.leftMargin: theme.em * 1.0
                    anchors.rightMargin: theme.em * 1.0
                    spacing: theme.em * 0.5
                    Icon {
                        glyph: backend.errorCount > 0 ? "" : ""  // warning, edit
                        color: backend.errorCount > 0 ? theme.loss : theme.accent
                    }
                    Text {
                        Layout.fillWidth: true
                        text: backend.errorCount > 0
                              ? i18n.trm("Fix " + backend.errorCount + " invalid value(s) to save") + "  ·  " + backend.firstError
                              : i18n.trm("Unsaved changes: " + backend.pendingCount)
                                + (backend.pendingOverlays > 1 ? "  ·  " + i18n.trm("Overlays: " + backend.pendingOverlays) : "")
                        color: backend.errorCount > 0 ? theme.loss : theme.text
                        elide: Text.ElideRight
                        MouseArea {
                            anchors.fill: parent
                            enabled: backend.errorCount > 0
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: backend.showFirstError()
                        }
                    }
                    TpButton {
                        flat: true
                        glyph: ""  // undo
                        text: theme.iconFont === "" ? i18n.tr("Undo") : ""
                        tip: i18n.tr("Undo (Ctrl+Z)")
                        enabled: backend.canUndo
                        onClicked: backend.undo()
                    }
                    TpButton {
                        flat: true
                        glyph: ""  // redo
                        text: theme.iconFont === "" ? i18n.tr("Redo") : ""
                        tip: i18n.tr("Redo (Ctrl+Y)")
                        enabled: backend.canRedo
                        onClicked: backend.redo()
                    }
                    TpButton {
                        text: i18n.tr("Discard")
                        tip: i18n.tr("Drop every unsaved change")
                        onClicked: backend.discard()
                    }
                    TpButton {
                        accent: true
                        text: i18n.tr("Apply")
                        tip: i18n.tr("Save & apply (Ctrl+S)")
                        enabled: backend.errorCount === 0
                        onClicked: backend.apply()
                    }
                }
            }
        }
    }
}
