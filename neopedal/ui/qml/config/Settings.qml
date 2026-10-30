import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Settings page: global options (config.json) by category. Navigation & search on the left (a choice
// list on narrow pages), options of the category in group cards, status cards (web dashboard address,
// remote control, settings file). Edits stay pending until applied: unsaved changes bar at the bottom
// (TpPendingBar, as on Overlay Options) with Undo, Redo, Discard & Apply (Ctrl+S). A search ("/") or
// "Changed Only" looks through every category. Rows: more actions with "⋯", right click or Menu key.
TpPage {
    id: page

    readonly property bool narrow: width < theme.em * 52  // content-tuned: 15.5 em navigation + 36 em option rows, else a choice list
    readonly property var info: backend.categoryInfo
    readonly property var web: backend.webDashboard
    readonly property var remote: backend.remoteControl
    readonly property var previews: backend.previews
    readonly property var categories: backend.categories  // read once per change (navigation, choice list)
    readonly property var section: backend.sectionState  // category kept in the loaded preset: preset, lock, on / off
    readonly property var fontPreview: backend.fontPreview
    property var menuData: null  // option row of the more actions menu

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
    // Sample text of the global font override preview: font & weight chosen, pixel size of an overlay font
    component SampleText: Text {
        property real size: 1
        text: "Aa 0123  " + size + " px"
        textFormat: Text.PlainText
        color: theme.text
        font.family: page.fontPreview.family !== "" ? page.fontPreview.family : Qt.application.font.family
        font.weight: page.fontPreview.weightValue > 0 ? page.fontPreview.weightValue : Font.Normal
        font.pixelSize: Math.max(1, size)
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

    // Ctrl+F or "/": search of this page (Ctrl+Shift+F finds any option of the app)
    Shortcut {
        sequences: [StandardKey.Find]
        enabled: pageState.active && !backend.singleCategory
        onActivated: page.focusSearch()
    }
    Keys.onPressed: function(event) {
        if (event.text === "/" && !backend.singleCategory) {
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

    // More actions of an option row (same menu as Overlay Options & Find Option)
    TpMenu {
        id: rowMenu
        objectName: "settingMenu"
        TpMenuItem {
            text: i18n.tr("Reset to Default")
            enabled: page.menuData !== null && page.menuData.modified
            onTriggered: backend.resetOption(page.menuData.key)
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
        onClosed: flick.forceActiveFocus()
    }
    function openRowMenu(data, anchor, x, y) {
        page.menuData = data
        if (x < 0)
            rowMenu.toggleBelow(anchor, true)  // right aligned under the button or row
        else
            rowMenu.popup(anchor, x, y)
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Navigation
        Rectangle {
            visible: !page.narrow && !backend.singleCategory
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(theme.em * 15.5)
            color: theme.surfaceSunken

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: theme.padCard
                spacing: theme.em * 0.5

                TpSearchField {
                    id: search
                    Layout.fillWidth: true
                    placeholderText: i18n.tr("Search settings") + "   Ctrl+F"
                    onSearchChanged: function(text) { backend.setSearch(text) }
                    onExitField: flick.forceActiveFocus()
                }
                TpSwitch {
                    objectName: "changedOnlySwitch"
                    checkable: false  // follows backend
                    checked: backend.changedOnly
                    text: i18n.tr("Changed Only")
                    tip: i18n.tr("Only options set apart from their default value or not applied yet, in every category")
                    onClicked: backend.setChangedOnly(!backend.changedOnly)
                    Accessible.role: Accessible.CheckBox
                    Accessible.name: i18n.tr("Changed Only")
                    Accessible.checked: backend.changedOnly
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
                    // Category, with the heading "In the loaded preset" above the first one kept in the preset
                    delegate: Item {
                        id: entry
                        required property int index
                        readonly property var info: page.categories[index] || ({})
                        readonly property bool selected: !backend.searching && backend.category === entry.info.key
                        readonly property bool dimmed: backend.searching && entry.info.matches === 0
                        width: ListView.view.width
                        height: entryHeading.height + entryBox.height
                        TpSectionLabel {
                            id: entryHeading
                            width: parent.width
                            height: entry.info.heading ? implicitHeight + theme.space2 : 0
                            visible: entry.info.heading !== ""
                            leftPadding: theme.space2
                            topPadding: theme.space4
                            text: entry.info.heading || ""
                        }
                        Rectangle {
                            id: entryBox
                            y: entryHeading.height
                            width: parent.width
                            height: Math.round(theme.em * 2.4)
                            radius: theme.radiusMd
                            color: theme.rowColor(entryArea.containsMouse, entry.selected)
                            Behavior on color { ColorAnimation { duration: theme.motionFast } }
                            Accessible.role: Accessible.PageTab
                            Accessible.name: entry.info.label
                            Accessible.description: entry.info.errors > 0 && !backend.searching
                                ? i18n.tr("%1 invalid value(s)").arg(entry.info.errors) : ""
                            Accessible.selected: entry.selected
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
                                size: theme.iconMd
                            }
                            Text {
                                anchors.left: entryIcon.visible ? entryIcon.right : parent.left
                                anchors.leftMargin: entryIcon.visible ? theme.em * 0.6 : theme.em * 0.8
                                anchors.right: badge.left
                                anchors.rightMargin: theme.space2
                                anchors.verticalCenter: parent.verticalCenter
                                text: entry.info.label
                                textFormat: Text.PlainText
                                color: entry.dimmed ? theme.dimOn(entryBox.color) : theme.text  // no match in search
                                font.weight: entry.selected ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                            TpCountBadge {  // changed options (search: matches), invalid values: error tone with "!"
                                id: badge
                                readonly property int count: backend.searching ? entry.info.matches : entry.info.changed
                                visible: count > 0
                                anchors.right: parent.right
                                anchors.rightMargin: theme.space3
                                anchors.verticalCenter: parent.verticalCenter
                                size: "sm"
                                text: count
                                tone: entry.info.errors > 0 && !backend.searching ? "error" : backend.searching ? "neutral" : "accent"
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
                }
            }
        }
        Rectangle {
            visible: !page.narrow && !backend.singleCategory
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: theme.strokeSubtle
        }

        // Content
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Narrow page: category choice & search
            RowLayout {
                visible: page.narrow && !backend.singleCategory
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
                    placeholderText: i18n.tr("Search settings") + "   Ctrl+F"
                    onSearchChanged: function(text) { backend.setSearch(text) }
                    onExitField: flick.forceActiveFocus()
                }
                TpSwitch {
                    checkable: false  // follows backend
                    checked: backend.changedOnly
                    text: i18n.tr("Changed Only")
                    tip: i18n.tr("Only options set apart from their default value or not applied yet, in every category")
                    onClicked: backend.setChangedOnly(!backend.changedOnly)
                    Accessible.role: Accessible.CheckBox
                    Accessible.name: i18n.tr("Changed Only")
                    Accessible.checked: backend.changedOnly
                }
            }

            // Header: icon tile, title (TpText title role, as TpPageHeader), description & preset pills, actions. Own
            // row: TpPageHeader has no leading icon nor pills under its subtitle
            RowLayout {
                id: header
                // Header actions as icons (names in tooltips) when the title would be cut
                readonly property bool tight: width < theme.em * 50  // content-tuned: title & 3 named actions in French
                Layout.fillWidth: true
                Layout.leftMargin: theme.padPage
                Layout.rightMargin: theme.padPage
                Layout.topMargin: theme.padPage
                Layout.bottomMargin: theme.space3
                spacing: theme.em * 0.7
                TpIconTile {
                    size: Math.round(theme.iconHero)  // page badge
                    Layout.preferredWidth: size  // TpIconTile sets width only (no implicit size)
                    Layout.preferredHeight: size
                    glyph: backend.searching ? "" : page.info.glyph  // search
                    fallbackText: !backend.searching ? page.info.label
                                : backend.searchText === "" ? i18n.tr("Modified options") : i18n.tr("Search results")
                }
                // Page title: same look as TpPageHeader (title role), description under it on 2 lines
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    TpText {
                        Layout.fillWidth: true
                        role: "title"
                        text: !backend.searching ? page.info.label
                            : backend.searchText === "" ? i18n.tr("Modified options") : i18n.tr("Search results")
                    }
                    TpText {
                        Layout.fillWidth: true
                        role: "caption"
                        text: backend.searching ? i18n.trm("Found: " + backend.matchCount) : page.info.description
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                    }
                    // Category kept in the loaded preset: which preset, locked (changes not saved)
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: theme.space1
                        visible: !backend.searching && page.info.preset === true
                        spacing: theme.space2
                        Pill {
                            glyph: ""  // library
                            text: page.section.preset || ""
                            maximumTextWidth: theme.em * 14
                            tint: theme.dimText
                            tip: i18n.tr("Saved in the loaded preset")
                        }
                        Pill {
                            visible: page.section.locked === true
                            glyph: theme.glyphs.lock
                            fallback: "!"
                            text: i18n.tr("Locked")
                            tint: theme.warning
                            tip: i18n.tr("Locked: changes are not saved")
                        }
                    }
                }
                // On / off of the section (module, pace notes playback): at once, like the Modules page
                TpSwitch {
                    objectName: "sectionSwitch"
                    visible: !backend.searching && page.section.switchable === true
                    checkable: false  // follows backend
                    checked: page.section.enabled === true
                    text: checked ? i18n.tr("Enabled") : i18n.tr("Disabled")
                    tip: i18n.tr("Turned on or off at once")
                    onClicked: backend.setSectionEnabled(!(page.section.enabled === true))
                    Accessible.role: Accessible.CheckBox
                    Accessible.name: page.info.label
                    Accessible.checked: checked
                }
                TpButton {
                    objectName: "testSound"
                    visible: !backend.searching && page.info.paceNotes === true
                    flat: true
                    glyph: ""  // volume
                    fallback: i18n.tr("Test Sound")
                    text: header.tight ? "" : i18n.tr("Test Sound")
                    tip: i18n.tr("Play a sound of the sound folder with the volume shown")
                    onClicked: backend.testSound()
                }
                TpButton {
                    visible: !backend.searching
                    flat: true
                    glyph: theme.glyphs.reset
                    fallback: i18n.tr("Reset Section")
                    text: header.tight ? "" : i18n.tr("Reset Section")
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
                            spacing: theme.space3
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
                                        : i18n.tr("Web dashboard is off: turn on its first option")
                                    textFormat: Text.PlainText
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
                                    spacing: theme.space3
                                    Text {
                                        id: urlText
                                        Layout.fillWidth: true
                                        text: modelData
                                        textFormat: Text.PlainText
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
                                    textFormat: Text.PlainText
                                    color: theme.text
                                    font.pointSize: theme.fontHeading
                                    font.weight: Font.DemiBold
                                    font.letterSpacing: theme.letterSpacingCode  // access code read out digit by digit
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

                    // Global font override: font sizes of the overlays now & once applied, sample text in the font chosen
                    TpSectionCard {
                        objectName: "fontPreview"
                        width: parent.width
                        visible: !backend.searching && page.info.font === true
                        height: visible ? implicitHeight : 0
                        fillContent: false
                        title: i18n.tr("Preview")
                        glyph: "\ue8d2"  // font
                        fallback: "A"
                        TpText {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: page.fontPreview.neutral
                                ? i18n.tr("Font sizes now: %1 to %2 px. Choose a change below, its result shows here before Apply.")
                                    .arg(page.fontPreview.sizeNow[0]).arg(page.fontPreview.sizeNow[1])
                                : i18n.tr("Font sizes: %1 to %2 px now, %3 to %4 px after Apply.")
                                    .arg(page.fontPreview.sizeNow[0]).arg(page.fontPreview.sizeNow[1])
                                    .arg(page.fontPreview.sizeAfter[0]).arg(page.fontPreview.sizeAfter[1])
                        }
                        TpText {
                            Layout.fillWidth: true
                            visible: !page.fontPreview.neutral
                            role: "caption"
                            wrapMode: Text.WordWrap
                            text: i18n.tr("Overlays and modules changed: %1 (%2 options). Undo is offered once applied.")
                                .arg(page.fontPreview.sections).arg(page.fontPreview.options)
                        }
                        // Smallest & largest font size once applied, in the font & weight chosen
                        Flow {
                            Layout.fillWidth: true
                            visible: !page.fontPreview.neutral
                            spacing: theme.space5
                            SampleText { size: page.fontPreview.sampleSmall }
                            SampleText { size: page.fontPreview.sampleLarge }
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
                            spacing: theme.space2
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
                                        : i18n.tr("Remote control is off: turn on its first option")
                                    textFormat: Text.PlainText
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
                                    spacing: theme.space3
                                    Text {
                                        Layout.fillWidth: true
                                        text: parent.code
                                        textFormat: Text.PlainText
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
                    onMenuRequested: function(data, anchor, x, y) { page.openRowMenu(data, anchor, x, y) }
                }

                footer: Column {
                    x: theme.padPage
                    width: flick.width - theme.padPage * 2
                    spacing: 0

                    TpStateView {
                        empty: flick.count === 0
                        width: parent.width
                        topPadding: theme.em * 3
                        glyph: ""  // search
                        title: backend.changedOnly && backend.searchText === "" ? i18n.tr("Every option has its default value")
                             : i18n.tr("No setting found")
                        text: backend.changedOnly && backend.searchText === "" ? ""
                            : i18n.tr("Search looks through every category. Check spelling, or try other words.")
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
                            TpText {
                                Layout.fillWidth: true
                                role: "caption"
                                text: i18n.trm("Settings file: " + backend.configFile)
                                elide: Text.ElideMiddle
                            }
                            TpButton {
                                flat: true
                                glyph: theme.glyphs.openFolder
                                size: "sm"
                                text: i18n.tr("Open Folder")
                                onClicked: backend.openConfigFolder()
                            }
                        }
                    }
                    Item { width: 1; height: theme.em * 1.2 }  // room below last row
                }
            }

            // Unsaved changes (after Discard: "Changes discarded" & Undo kept a few seconds)
            TpPendingBar {
                objectName: "pendingBar"
                pendingCount: backend.pendingCount
                errorCount: backend.errorCount
                firstError: backend.firstError
                canUndo: backend.canUndo
                canRedo: backend.canRedo
                onShowErrorRequested: backend.showFirstError()
                onUndoRequested: {
                    page.commitEdits()  // field being edited left first: shows undone value, never sent again
                    backend.undo()
                }
                onRedoRequested: {
                    page.commitEdits()
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

    // Dialogs & toasts asked by the backend (ui/quick/dialogs.py, ui/toast.show_toast)
    TpDialogHost {}
}
