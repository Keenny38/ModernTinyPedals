import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Overlay Options page: options of every overlay. Overlays on the left (by category, with unsaved edits,
// errors & search matches; a choice list on narrow pages), options of the selected overlay in section
// cards, live preview on the right (wide pages). Search in this overlay or in every overlay, "Modified"
// filter. Edits of any overlay stay pending until applied: bar at the bottom with Undo, Redo, Discard &
// Apply (Ctrl+S). After Discard the bar stays a few seconds with Undo.
TpPage {
    id: page

    readonly property bool narrow: width < theme.bpNarrow
    readonly property bool previewShown: width >= theme.em * 74  // content-tuned: navigation + options + 21 em preview
    readonly property var info: backend.overlayInfo
    property var menuData: null  // option row of the "more" menu

    // Field being edited committed (Apply, Ctrl+S: buttons & shortcuts take no focus): focus left
    function commitEdits() {
        page.forceActiveFocus()
    }
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
        MenuSeparator {}
        TpMenuItem {
            text: i18n.tr("Copy Option Name")
            onTriggered: backend.copyText(page.menuData.option)
        }
        onClosed: list.forceActiveFocus()
    }
    TextMetrics { id: shareMetrics; text: i18n.tr("Import Overlay Settings...") }
    TpMenu {
        id: shareMenu
        width: Math.max(theme.em * 13, shareMetrics.advanceWidth + theme.em * 3.8)  // longest item never cut
        TpMenuItem {
            text: i18n.tr("Export Overlay Settings...")
            onTriggered: backend.exportOverlays()
        }
        TpMenuItem {
            text: i18n.tr("Import Overlay Settings...")
            onTriggered: backend.importOverlays()
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
                anchors.margins: theme.space4
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
                        height: Math.round(theme.em * 1.9)
                        TpSectionLabel {
                            anchors.left: parent.left
                            anchors.leftMargin: theme.em * 0.5
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
                            color: entry.dimmed ? theme.dimOn(entry.color) : theme.text
                            font.weight: entry.selected ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                        Text {  // options changed from default
                            id: customized
                            visible: !badge.visible && entry.customized > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.space4
                            anchors.verticalCenter: parent.verticalCenter
                            text: visible ? entry.customized : ""
                            color: theme.dimOn(entry.color)
                            font.pointSize: theme.fontCaption
                            font.features: { "tnum": 1 }
                        }
                        Rectangle {
                            id: badge
                            visible: entry.badgeCount > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.em * 0.5
                            anchors.verticalCenter: parent.verticalCenter
                            height: Math.round(theme.em * 1.3)
                            width: Math.max(height, badgeText.implicitWidth + theme.space4)
                            radius: height / 2
                            color: entry.errors > 0 && !(backend.filtering && backend.scopeAll) ? theme.lossFill
                                 : backend.filtering && backend.scopeAll ? theme.hover : theme.accentFill
                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: entry.badgeCount
                                color: backend.filtering && backend.scopeAll ? theme.text : theme.inkOn(badge.color)
                                font.pointSize: theme.fontCaption
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
                Layout.margins: theme.padPage
                Layout.bottomMargin: 0
                readonly property var keys: backend.overlayKeys
                model: backend.overlayLabels
                currentIndex: keys.indexOf(backend.overlay)
                tip: i18n.tr("Find overlay")
                onActivated: function(index) { backend.selectOverlay(keys[index]) }
            }

            // Header
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 1.0
                Layout.rightMargin: theme.em * 1.0
                Layout.topMargin: theme.padPage
                spacing: theme.padCard
                TpIconTile {
                    Layout.preferredWidth: size
                    Layout.preferredHeight: size
                    size: Math.round(theme.em * 2.6)
                    tint: backend.filtering && backend.scopeAll || page.info.color === "" ? theme.accent : page.info.color
                    glyph: backend.filtering && backend.scopeAll ? "" : ""  // search, sliders
                    fallbackText: page.info.label || ""
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
                        font.pointSize: theme.fontTitle
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Accessible.role: Accessible.Heading
                        Accessible.name: text
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
                TpButton {  // display profile set: some options follow it (click: show the option)
                    visible: !(backend.filtering && backend.scopeAll) && page.info.profile !== ""
                    flat: true
                    size: "sm"
                    glyph: ""  // filter
                    text: page.info.profile
                    tip: i18n.tr("Options set by this profile show its value: changing one switches to Custom. Click to show the option.")
                    onClicked: backend.showOption(page.info.profileOption)
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
                    fallback: "▲"
                    tip: i18n.tr("Collapse All")
                    onClicked: backend.setAllCollapsed(true)
                }
                TpButton {
                    visible: !backend.filtering
                    flat: true
                    glyph: ""  // chevron down
                    fallback: "▼"
                    tip: i18n.tr("Expand All")
                    onClicked: backend.setAllCollapsed(false)
                }
                TpButton {
                    visible: !(backend.filtering && backend.scopeAll)
                    flat: true
                    glyph: ""  // undo
                    fallback: "↺"
                    text: page.narrow ? "" : i18n.tr("Reset Overlay")
                    tip: i18n.tr("Every option of this overlay back to default (saved with Apply)")
                    onClicked: backend.resetOverlay()
                }
                TpButton {
                    id: shareButton
                    flat: true
                    glyph: ""  // export
                    fallback: "⇪"
                    text: page.narrow ? "" : i18n.tr("Share")
                    tip: i18n.tr("Export or import overlay settings as a file")
                    onClicked: shareMenu.popup(shareButton, 0, shareButton.height)
                }
            }

            // Search & filters
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 1.0
                Layout.rightMargin: theme.em * 1.0
                Layout.topMargin: theme.space4
                Layout.bottomMargin: theme.space3
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
                    name: i18n.tr("Where search & filter look")
                    options: [i18n.tr("This overlay"), i18n.tr("Every overlay")]
                    currentIndex: backend.scopeAll ? 1 : 0
                    onActivated: function(index) { backend.setScopeAll(index === 1) }
                    ToolTip.visible: scopeArea.containsMouse
                    ToolTip.text: i18n.tr("Where search & filter look")
                    ToolTip.delay: theme.tipDelay
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
                    checkable: false
                    checked: backend.usedOnly
                    text: i18n.tr("Used only")
                    tip: i18n.tr("Hide options doing nothing with current values (greyed out)")
                    onClicked: backend.setUsedOnly(!backend.usedOnly)
                }
                TpSwitch {
                    visible: page.info.simpleMode && !(backend.filtering && backend.scopeAll)
                    checkable: false
                    checked: backend.advanced
                    text: i18n.tr("Advanced Options")
                    tip: i18n.tr("Show every option, including colors, thresholds and labels")
                    onClicked: backend.setAdvanced(!backend.advanced)
                }
                TpCombo {  // user display profiles: current display saved as one
                    visible: page.info.userProfiles.length > 0 && !(backend.filtering && backend.scopeAll)
                    width: theme.em * 11
                    model: [{ label: i18n.tr("Save as Profile...") }].concat(page.info.userProfiles)
                    textRole: "label"
                    currentIndex: 0
                    tip: i18n.tr("Save shown items as a display profile, then pick it in Display Profile (saved with Apply or Save)")
                    onActivated: function(index) {
                        if (index > 0)
                            backend.saveUserProfile(page.info.userProfiles[index - 1].name)
                        currentIndex = 0
                    }
                }
                TpCombo {
                    visible: page.info.themes.length > 0 && !(backend.filtering && backend.scopeAll)
                    width: theme.em * 11
                    model: [{ label: i18n.tr("Color Theme...") }].concat(page.info.themes)
                    textRole: "label"
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
                    reuseItems: true  // rows of other options & overlays reuse delegates (see OverlayOptionRow)
                    cacheBuffer: Math.round(theme.em * 30)
                    leftMargin: theme.em * 1.0
                    rightMargin: theme.em * 1.0
                    bottomMargin: theme.space6
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
                        height: backend.truncatedCount > 0 ? moreText.implicitHeight + theme.space6 * 2 : 0
                        Text {
                            id: moreText
                            visible: backend.truncatedCount > 0
                            anchors.centerIn: parent
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
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

                    visible: page.previewShown && !(backend.filtering && backend.scopeAll)
                    Layout.fillHeight: true
                    Layout.preferredWidth: expanded ? Math.max(Math.round(theme.em * 21), Math.round(parent.width * 0.5))
                                                    : Math.round(theme.em * 21)
                    Behavior on Layout.preferredWidth { NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutCubic } }
                    Layout.bottomMargin: theme.em * 1.0
                    Layout.rightMargin: theme.em * 1.0
                    radius: theme.radiusXl
                    color: theme.base
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
                        spacing: theme.em * 0.5
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
                                anchors.margins: theme.em * 0.5
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
                                    : backend.previewState === 1 ? i18n.tr("Drawing preview...")
                                    : backend.previewState === 3 ? i18n.tr("Preview not available for this overlay")
                                    : i18n.tr("Invalid value, preview not updated")
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
                            TpButton {
                                flat: true
                                checked: backend.testing
                                text: backend.testing ? i18n.tr("Stop Test") : i18n.tr("Test on Screen")
                                tip: i18n.tr("Overlays on screen show this race situation for a few seconds (saved values)")
                                onClicked: backend.testOnScreen()
                            }
                        }
                    }
                }
            }

            // Pending changes. After Discard the bar stays a few seconds with Undo (Ctrl+Z works too)
            Rectangle {
                id: bar
                readonly property bool pending: backend.pendingCount > 0
                readonly property bool shown: pending || undoGrace.running
                visible: shown || heightAnim.running  // no hidden buttons in Tab order
                enabled: shown
                Layout.fillWidth: true
                Layout.preferredHeight: shown ? barRow.implicitHeight + theme.em * 1.0 : 0
                clip: true
                color: theme.dark ? Qt.lighter(theme.window, 1.1) : Qt.darker(theme.window, 1.04)
                Behavior on Layout.preferredHeight { NumberAnimation { id: heightAnim; duration: theme.motionBase; easing.type: Easing.OutCubic } }
                Rectangle { width: parent.width; height: 1; color: theme.border }
                Timer { id: undoGrace; interval: 6000 }  // restarted by Discard
                onPendingChanged: if (pending) undoGrace.stop()  // undone: normal bar again

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
                        glyph: backend.errorCount > 0 ? "" : bar.pending ? "" : ""  // warning, edit, check
                        fallback: backend.errorCount > 0 ? "!" : ""
                        color: backend.errorCount > 0 ? theme.loss : theme.accent
                    }
                    Text {
                        Layout.fillWidth: true
                        text: !bar.pending ? i18n.tr("Changes discarded")
                              : backend.errorCount > 0
                              ? i18n.trm("Fix " + backend.errorCount + " invalid value(s) to save") + "  ·  " + backend.firstError
                              : i18n.trm("Unsaved changes: " + backend.pendingCount)
                                + (backend.pendingOverlays > 1 ? "  ·  " + i18n.trm("Overlays: " + backend.pendingOverlays) : "")
                        color: backend.errorCount > 0 ? theme.loss : theme.text
                        elide: Text.ElideRight
                        Accessible.role: Accessible.AlertMessage
                        Accessible.name: text
                    }
                    TpButton {  // invalid value: show it (keyboard reachable, was a click on the text)
                        visible: backend.errorCount > 0
                        flat: true
                        text: i18n.tr("Show")
                        tip: backend.firstError
                        onClicked: backend.showFirstError()
                    }
                    TpButton {
                        flat: true
                        glyph: ""  // undo
                        fallback: i18n.tr("Undo")
                        text: bar.pending ? "" : i18n.tr("Undo")
                        tip: i18n.tr("Undo (Ctrl+Z)")
                        enabled: backend.canUndo
                        onClicked: {
                            page.commitEdits()  // field being edited left first: shows undone value, never sent again
                            backend.undo()
                        }
                    }
                    TpButton {
                        visible: bar.pending
                        flat: true
                        glyph: ""  // redo
                        fallback: i18n.tr("Redo")
                        tip: i18n.tr("Redo (Ctrl+Y)")
                        enabled: backend.canRedo
                        onClicked: {
                            page.commitEdits()  // field being edited left first: shows redone value, never sent again
                            backend.redo()
                        }
                    }
                    TpButton {
                        visible: bar.pending
                        text: i18n.tr("Discard")
                        tip: i18n.tr("Drop every unsaved change")
                        onClicked: {
                            page.commitEdits()  // focus left: typed value dropped too, field shows saved value
                            backend.discard()
                            undoGrace.restart()
                        }
                    }
                    TpButton {
                        visible: bar.pending
                        accent: true
                        text: i18n.tr("Apply")
                        tip: i18n.tr("Save & apply (Ctrl+S)")
                        enabled: backend.errorCount === 0
                        onClicked: {
                            page.commitEdits()
                            backend.apply()
                        }
                    }
                }
            }
        }
    }
}
