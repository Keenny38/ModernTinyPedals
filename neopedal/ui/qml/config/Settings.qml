import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Settings page: global options (config.json) by category. Navigation & search on the left (a choice
// list on narrow pages), options of the category in group cards, status cards (web dashboard address,
// remote control, settings file). Edits stay pending until applied: bar at the bottom with Undo, Redo,
// Discard & Apply (Ctrl+S). A search ("/") looks through every category.
TpPage {
    id: page

    readonly property bool narrow: width < theme.em * 52  // content-tuned: 15.5 em navigation + 36 em option rows, else a choice list
    readonly property var info: backend.categoryInfo
    readonly property var web: backend.webDashboard
    readonly property var remote: backend.remoteControl
    readonly property var previews: backend.previews
    readonly property var categories: backend.categories  // read once per change (navigation, choice list)

    function scrollToKey(key) {
        var index = backend.optionIndex(key)
        if (index < 0)
            return
        flick.positionViewAtIndex(index, ListView.Beginning)  // row created if it was not
        var item = flick.itemAtIndex(index)
        if (item) {
            flick.contentY = Math.max(flick.originY, Math.min(item.y - theme.em * 2,
                                                              flick.originY + flick.contentHeight - flick.height))
            item.flash()
        }
    }
    // Field being edited committed (Apply, Ctrl+S: buttons & shortcuts take no focus): focus left
    function commitEdits() {
        flick.forceActiveFocus()
    }
    function focusSearch() {
        var field = page.narrow ? narrowSearch : search
        field.forceActiveFocus()
        field.selectAll()
    }

    Keys.onPressed: function(event) {
        if (event.text === "/") {  // Ctrl+F is Find Option (every option of the app)
            page.focusSearch()
            event.accepted = true
        }
    }

    Connections {
        target: backend
        function onHighlightChanged() {
            if (backend.highlightKey !== "")
                highlightTimer.restart()  // rows of new category laid out first
        }
        function onCategoryChanged() { flick.positionViewAtBeginning() }
        function onFilterChanged() {
            if (search.text !== backend.searchText)
                search.text = backend.searchText
            if (narrowSearch.text !== backend.searchText)
                narrowSearch.text = backend.searchText
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

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Navigation
        Rectangle {
            visible: !page.narrow
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(theme.em * 15.5)
            color: theme.dark ? Qt.darker(theme.window, 1.12) : Qt.darker(theme.window, 1.025)

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: theme.padCard
                spacing: theme.em * 0.5

                TpSearchField {
                    id: search
                    Layout.fillWidth: true
                    placeholderText: i18n.tr("Search settings")
                    onSearchChanged: function(text) { backend.setSearch(text) }
                    onExitField: flick.forceActiveFocus()
                }

                ListView {
                    id: nav
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    interactive: contentHeight > height
                    boundsBehavior: Flickable.StopAtBounds
                    // Count, not the list: a new list comes at each edit (key typed), the view would be reset & scrolled up
                    model: page.categories.length
                    activeFocusOnTab: true
                    currentIndex: -1
                    Keys.onUpPressed: navStep(-1)
                    Keys.onDownPressed: navStep(1)
                    function navStep(offset) {
                        var keys = page.categories.map(function(entry) { return entry.key })
                        var index = keys.indexOf(backend.category)
                        backend.selectCategory(keys[Math.max(0, Math.min(keys.length - 1, index + offset))])
                    }
                    delegate: Rectangle {
                        id: entry
                        required property int index
                        readonly property var info: page.categories[index] || ({})
                        readonly property bool selected: !backend.searching && backend.category === entry.info.key
                        readonly property bool dimmed: backend.searching && entry.info.matches === 0
                        width: ListView.view.width
                        height: Math.round(theme.em * 2.4)
                        radius: theme.radiusMd
                        color: theme.rowColor(entryArea.containsMouse, selected)
                        Behavior on color { ColorAnimation { duration: theme.motionFast } }
                        Accessible.role: Accessible.PageTab
                        Accessible.name: entry.info.label
                        Accessible.description: entry.info.errors > 0 && !backend.searching
                            ? i18n.tr("%1 invalid value(s)").arg(entry.info.errors) : ""
                        Accessible.selected: selected
                        // Keyboard focus on the navigation (Up / Down choose): ring on the shown category
                        FocusRing { anchors.margins: gap; visible: nav.activeFocus && backend.category === entry.info.key }  // inside: list clips

                        Rectangle {
                            visible: entry.selected
                            width: Math.round(theme.em * 0.22)
                            height: parent.height * 0.5
                            radius: width / 2
                            anchors.verticalCenter: parent.verticalCenter
                            color: theme.accent
                        }
                        Icon {
                            id: entryIcon
                            x: theme.em * 0.7
                            anchors.verticalCenter: parent.verticalCenter
                            glyph: entry.info.glyph
                            color: entry.selected ? theme.accent : theme.dimText
                            size: theme.em * 1.0
                        }
                        Text {
                            anchors.left: entryIcon.visible ? entryIcon.right : parent.left
                            anchors.leftMargin: entryIcon.visible ? theme.em * 0.6 : theme.em * 0.8
                            anchors.right: badge.left
                            anchors.rightMargin: theme.em * 0.3
                            anchors.verticalCenter: parent.verticalCenter
                            text: entry.info.label
                            color: entry.dimmed ? theme.dimOn(entry.color) : theme.text  // no match in search
                            font.weight: entry.selected ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            id: badge
                            readonly property int count: backend.searching ? entry.info.matches : entry.info.changed
                            readonly property bool errors: entry.info.errors > 0 && !backend.searching
                            visible: count > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.em * 0.5
                            anchors.verticalCenter: parent.verticalCenter
                            height: Math.round(theme.em * 1.3)
                            width: Math.max(height, badgeText.implicitWidth + theme.em * 0.6)
                            radius: height / 2
                            color: badge.errors ? theme.lossFill
                                 : backend.searching ? theme.hover : theme.accentFill
                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: badge.errors ? "! " + badge.count : badge.count  // invalid values: mark, not only red
                                color: backend.searching ? theme.text : "white"
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
                                backend.selectCategory(entry.info.key)
                                search.clear()
                            }
                        }
                    }
                }

                // Settings kept in the loaded preset
                TpSectionLabel {
                    Layout.fillWidth: true
                    Layout.topMargin: theme.space2
                    text: i18n.tr("In the loaded preset")
                }
                Repeater {
                    model: [
                        { "name": "units", "text": i18n.tr("Units"), "glyph": "" },  // sliders
                        { "name": "font", "text": i18n.tr("Global Font Override"), "glyph": "" },  // font
                        { "name": "api", "text": i18n.tr("API Options"), "glyph": "" },  // network
                    ]
                    Rectangle {
                        id: link
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: Math.round(theme.rowCompact)
                        radius: theme.radiusMd
                        color: linkArea.containsMouse ? theme.hover : "transparent"
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Link
                        Accessible.name: modelData.text
                        Keys.onReturnPressed: backend.openLink(link.modelData.name)
                        Keys.onEnterPressed: backend.openLink(link.modelData.name)
                        Keys.onSpacePressed: backend.openLink(link.modelData.name)
                        FocusRing { visible: link.activeFocus }
                        Icon {
                            id: linkIcon
                            x: theme.em * 0.7
                            anchors.verticalCenter: parent.verticalCenter
                            glyph: link.modelData.glyph
                            color: theme.dimText
                            size: theme.em * 0.95
                        }
                        Text {
                            anchors.left: linkIcon.visible ? linkIcon.right : parent.left
                            anchors.leftMargin: linkIcon.visible ? theme.em * 0.6 : theme.em * 0.8
                            anchors.right: linkArrow.left
                            anchors.verticalCenter: parent.verticalCenter
                            text: link.modelData.text
                            color: theme.text
                            elide: Text.ElideRight
                        }
                        Icon {
                            id: linkArrow
                            fallback: "›"
                            anchors.right: parent.right
                            anchors.rightMargin: theme.em * 0.6
                            anchors.verticalCenter: parent.verticalCenter
                            glyph: ""  // chevron right
                            size: theme.em * 0.7
                            color: theme.dimText
                        }
                        MouseArea {
                            id: linkArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.openLink(link.modelData.name)
                        }
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

        // Content
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Narrow page: category choice & search
            RowLayout {
                visible: page.narrow
                Layout.fillWidth: true
                Layout.margins: theme.padPage
                Layout.bottomMargin: 0
                spacing: theme.em * 0.5
                TpCombo {
                    Layout.preferredWidth: theme.em * 13
                    Layout.preferredHeight: Math.round(theme.controlHeight)  // as tall as the search field beside
                    tip: i18n.tr("Category")
                    model: page.categories
                    textRole: "label"
                    currentIndex: page.categories.findIndex(function(entry) { return entry.key === backend.category })
                    onActivated: function(index) { backend.selectCategory(page.categories[index].key) }
                }
                TpSearchField {
                    id: narrowSearch
                    Layout.fillWidth: true
                    placeholderText: i18n.tr("Search settings")
                    onSearchChanged: function(text) { backend.setSearch(text) }
                    onExitField: flick.forceActiveFocus()
                }
                TpButton {
                    id: presetLinksButton
                    flat: true
                    glyph: ""  // more
                    fallback: "..."
                    tip: i18n.tr("In the loaded preset")
                    checked: presetLinks.visible
                    onClicked: presetLinks.visible ? presetLinks.close() : presetLinks.popup(presetLinksButton, 0, presetLinksButton.height + 4)
                    TpMenu {
                        id: presetLinks
                        onClosed: presetLinksButton.forceActiveFocus()  // menus give focus back to the window
                        Action { text: i18n.tr("Units"); onTriggered: backend.openLink("units") }
                        Action { text: i18n.tr("Global Font Override"); onTriggered: backend.openLink("font") }
                        Action { text: i18n.tr("API Options"); onTriggered: backend.openLink("api") }
                    }
                }
            }

            // Header
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: theme.padPage
                Layout.rightMargin: theme.padPage
                Layout.topMargin: theme.padPage
                Layout.bottomMargin: theme.space3
                spacing: theme.em * 0.7
                TpIconTile {
                    size: Math.round(theme.em * 2.6)
                    Layout.preferredWidth: size  // TpIconTile sets width only (no implicit size)
                    Layout.preferredHeight: size
                    glyph: backend.searching ? "" : page.info.glyph  // search
                    fallbackText: backend.searching ? i18n.tr("Search results") : page.info.label
                }
                // Page title: same look as TpPageHeader (fontTitle), description under it on 2 lines
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Text {
                        Layout.fillWidth: true
                        text: backend.searching ? i18n.tr("Search results") : page.info.label
                        color: theme.text
                        font.pointSize: theme.fontTitle
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Accessible.role: Accessible.Heading
                        Accessible.name: text
                    }
                    Text {
                        Layout.fillWidth: true
                        text: backend.searching ? i18n.trm("Found: " + backend.matchCount) : page.info.description
                        color: theme.dimText
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                }
                TpButton {
                    visible: !backend.searching
                    flat: true
                    glyph: ""  // undo
                    text: i18n.tr("Reset Section")
                    tip: i18n.tr("Every option of this section back to default (saved with Apply)")
                    onClicked: backend.resetCategory()
                }
            }

            // Options: rows made for the part shown, pooled & fed again when category or search changes
            // (no row of every option kept), status cards above the rows, settings file below
            ListView {
                id: flick
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                activeFocusOnTab: true
                keyNavigationEnabled: false  // Up & Down scroll (no current row)
                reuseItems: true
                cacheBuffer: Math.round(theme.em * 40)
                model: backend.options
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                readonly property real lastY: originY + contentHeight - height
                Keys.onUpPressed: flick.contentY = Math.max(flick.originY, flick.contentY - theme.em * 3)
                Keys.onDownPressed: flick.contentY = Math.max(flick.originY, Math.min(flick.lastY, flick.contentY + theme.em * 3))
                // Keyboard focus on the list (Up / Down scroll): ring inside its edges (list clips)
                FocusRing {
                    parent: flick
                    target: flick
                    anchors.margins: gap
                    z: 2
                    visible: flick.activeFocus && (flick.focusReason === Qt.TabFocusReason || flick.focusReason === Qt.BacktabFocusReason)
                }

                header: Column {
                    x: theme.padPage
                    width: flick.width - theme.padPage * 2
                    spacing: 0

                    // Web dashboard: addresses & access code
                    Card {
                        width: parent.width
                        visible: !backend.searching && backend.category === "web_dashboard"
                        height: visible ? webColumn.implicitHeight + theme.padCard * 2 : 0
                        ColumnLayout {
                            id: webColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: theme.padCard
                            spacing: theme.em * 0.4
                            RowLayout {
                                spacing: theme.em * 0.5
                                Rectangle {
                                    width: Math.round(theme.em * 0.6)
                                    height: width
                                    radius: width / 2
                                    color: page.web.running ? theme.gain : theme.dimText
                                }
                                Text {
                                    text: page.web.running ? i18n.tr("Web dashboard is running")
                                        : page.web.enabled ? i18n.tr("Web dashboard is not running (port in use?), see log")
                                        : i18n.tr("Web dashboard is off: turn on its first option, then Apply")
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Text {
                                visible: page.web.enabled
                                text: i18n.tr("Open one of these addresses in a browser:")
                                color: theme.dimText
                            }
                            Repeater {
                                model: page.web.enabled ? page.web.urls : []
                                RowLayout {
                                    required property string modelData
                                    Layout.fillWidth: true
                                    spacing: theme.em * 0.4
                                    Text {
                                        id: urlText
                                        Layout.fillWidth: true
                                        text: modelData
                                        color: theme.accent
                                        font.underline: linkArea.containsMouse || activeFocus
                                        elide: Text.ElideMiddle
                                        activeFocusOnTab: true  // Enter opens it in the browser
                                        Accessible.role: Accessible.Link
                                        Accessible.name: modelData
                                        Keys.onReturnPressed: Qt.openUrlExternally(modelData)
                                        Keys.onEnterPressed: Qt.openUrlExternally(modelData)
                                        FocusRing { visible: urlText.activeFocus }
                                        MouseArea {
                                            id: linkArea
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: Qt.openUrlExternally(modelData)
                                        }
                                    }
                                    TpButton {
                                        flat: true
                                        size: "sm"
                                        text: i18n.tr("Copy")
                                        onClicked: backend.copyText(modelData)
                                    }
                                }
                            }
                            RowLayout {
                                visible: page.web.enabled
                                spacing: theme.em * 0.5
                                Text { text: i18n.tr("Access code"); color: theme.dimText }
                                Text {
                                    text: page.web.code || ""
                                    color: theme.text
                                    font.pointSize: theme.fontHeading
                                    font.weight: Font.DemiBold
                                    font.letterSpacing: 2
                                    font.features: { "tnum": 1 }
                                }
                                TpButton {
                                    flat: true
                                    size: "sm"
                                    text: i18n.tr("Copy")
                                    onClicked: backend.copyText(page.web.code)
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: (page.web.fingerprint || "") !== ""
                                text: i18n.tr("The browser warns once about this self-signed certificate. Accept it only if its SHA-256 fingerprint is:")
                                color: theme.dimText
                                wrapMode: Text.WordWrap
                            }
                            TextEdit {
                                Layout.fillWidth: true
                                visible: (page.web.fingerprint || "") !== ""
                                text: page.web.fingerprint || ""
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextEdit.WrapAnywhere
                                color: theme.text
                                font.family: theme.monoFont
                                font.pointSize: theme.fontSmall
                            }
                        }
                    }

                    // Remote control: address
                    Card {
                        width: parent.width
                        visible: !backend.searching && backend.category === "remote_control"
                        height: visible ? remoteColumn.implicitHeight + theme.padCard * 2 : 0
                        ColumnLayout {
                            id: remoteColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: theme.padCard
                            spacing: theme.em * 0.3
                            RowLayout {
                                spacing: theme.em * 0.5
                                Rectangle {
                                    width: Math.round(theme.em * 0.6)
                                    height: width
                                    radius: width / 2
                                    color: page.remote.running ? theme.gain : theme.dimText
                                }
                                Text {
                                    text: page.remote.running ? i18n.tr("Remote control is listening")
                                        : page.remote.enabled ? i18n.tr("Remote control is not running (port in use?), see log")
                                        : i18n.tr("Remote control is off: turn on its first option, then Apply")
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: i18n.tr("Run hotkey commands from this computer (Stream Deck, Companion, SimHub, scripts). Example:")
                                color: theme.dimText
                                wrapMode: Text.WordWrap
                            }
                            Repeater {
                                // Texts read from page.remote by key: rows kept when the addresses change
                                model: [
                                    { "key": "command", "tip": i18n.tr("Command, with its required header") },
                                    { "key": "commands", "tip": i18n.tr("List of commands (JSON)") },
                                    { "key": "stream", "tip": i18n.tr("Live telemetry (WebSocket)") },
                                ]
                                RowLayout {
                                    required property var modelData
                                    readonly property string code: page.remote[modelData.key] || ""
                                    Layout.fillWidth: true
                                    spacing: theme.em * 0.4
                                    Text {
                                        Layout.fillWidth: true
                                        text: parent.code
                                        color: theme.text
                                        font.family: theme.monoFont
                                        font.pointSize: theme.fontLabel
                                        elide: Text.ElideMiddle
                                        MouseArea { id: codeArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                                        ToolTip.visible: codeArea.containsMouse
                                        ToolTip.text: modelData.tip
                                        ToolTip.delay: theme.tipDelay
                                    }
                                    TpButton {
                                        flat: true
                                        size: "sm"
                                        text: i18n.tr("Copy")
                                        onClicked: backend.copyText(parent.code)
                                    }
                                }
                            }
                        }
                    }

                    Item { width: 1; height: theme.em * 0.2; visible: !backend.searching && (backend.category === "web_dashboard" || backend.category === "remote_control") }
                }

                delegate: SettingRow {
                    x: theme.padPage
                    width: flick.width - theme.padPage * 2
                    preview: backend.category === "notification" && !backend.searching ? (page.previews[group] || null) : null
                }

                footer: Column {
                    x: theme.padPage
                    width: flick.width - theme.padPage * 2
                    spacing: 0

                    EmptyState {
                        visible: flick.count === 0
                        width: parent.width
                        topPadding: theme.em * 3
                        glyph: ""  // search
                        title: i18n.tr("No setting found")
                        text: i18n.tr("Search looks through every category. Check spelling, or try other words.")
                    }

                    // Settings file
                    Item {
                        width: parent.width
                        height: fileRow.implicitHeight + theme.em * 1.6
                        visible: !backend.searching && (backend.category === "application" || backend.category === "user_path")
                        RowLayout {
                            id: fileRow
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            spacing: theme.em * 0.5
                            Text {
                                Layout.fillWidth: true
                                text: i18n.trm("Settings file: " + backend.configFile)
                                color: theme.dimText
                                font.pointSize: theme.fontSmall
                                elide: Text.ElideMiddle
                            }
                            TpButton {
                                flat: true
                                glyph: ""  // open folder
                                size: "sm"
                                text: i18n.tr("Open Folder")
                                onClicked: backend.openConfigFolder()
                            }
                        }
                    }
                    Item { width: 1; height: theme.em * 1.2 }  // room below last row
                }
            }

            // Pending changes (Discard: "Changes discarded" & Undo kept a few seconds). Hidden bar: out of the
            // Tab order (not only folded), its buttons never take focus unseen
            Rectangle {
                id: bar
                objectName: "pendingBar"
                readonly property bool discarded: undoGrace.running && backend.pendingCount === 0
                readonly property bool shown: backend.pendingCount > 0 || discarded
                visible: shown || heightAnimation.running
                enabled: shown
                Layout.fillWidth: true
                Layout.preferredHeight: shown ? barRow.implicitHeight + theme.em * 1.0 : 0
                clip: true
                color: theme.dark ? Qt.lighter(theme.window, 1.1) : Qt.darker(theme.window, 1.04)
                Behavior on Layout.preferredHeight {
                    NumberAnimation { id: heightAnimation; duration: theme.motionBase; easing.type: Easing.OutCubic }
                }
                Rectangle { width: parent.width; height: 1; color: theme.border }
                Timer { id: undoGrace; interval: 6000 }
                Connections {
                    target: backend
                    function onStateChanged() {
                        if (backend.pendingCount > 0)
                            undoGrace.stop()  // edited or undone meanwhile: the usual bar
                    }
                }

                RowLayout {
                    id: barRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: theme.em * 0.5
                    anchors.leftMargin: theme.padPage
                    anchors.rightMargin: theme.padPage
                    spacing: theme.em * 0.5
                    Icon {
                        visible: bar.discarded
                        glyph: ""  // check
                        fallback: "✓"
                        color: theme.gain
                    }
                    Icon {
                        visible: !bar.discarded
                        fallback: backend.errorCount > 0 ? "!" : ""
                        glyph: backend.errorCount > 0 ? "" : ""  // warning, edit
                        color: backend.errorCount > 0 ? theme.loss : theme.accent
                    }
                    Text {
                        Layout.fillWidth: true
                        text: bar.discarded ? i18n.tr("Changes discarded")
                            : backend.errorCount > 0
                              ? i18n.trm("Fix " + backend.errorCount + " invalid value(s) to save") + "  ·  " + backend.firstError
                              : i18n.trm("Unsaved changes: " + backend.pendingCount)
                        color: backend.errorCount > 0 && !bar.discarded ? theme.loss : theme.text
                        elide: Text.ElideRight
                    }
                    TpButton {
                        flat: true
                        glyph: ""  // undo
                        objectName: "pendingUndo"
                        text: bar.discarded ? i18n.tr("Undo") : ""  // after Discard: told in words
                        fallback: i18n.tr("Undo")
                        tip: i18n.tr("Undo (Ctrl+Z)")
                        enabled: backend.canUndo
                        onClicked: backend.undo()
                    }
                    TpButton {
                        flat: true
                        glyph: ""  // redo
                        visible: !bar.discarded
                        fallback: i18n.tr("Redo")
                        tip: i18n.tr("Redo (Ctrl+Y)")
                        enabled: backend.canRedo
                        onClicked: backend.redo()
                    }
                    TpButton {
                        objectName: "pendingDiscard"
                        visible: !bar.discarded
                        text: i18n.tr("Discard")
                        tip: i18n.tr("Drop every unsaved change")
                        onClicked: {
                            undoGrace.restart()  // bar kept with Undo for a moment
                            backend.discard()
                        }
                    }
                    TpButton {
                        visible: !bar.discarded
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
