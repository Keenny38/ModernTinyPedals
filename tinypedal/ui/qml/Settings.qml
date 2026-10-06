import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Settings page: global options (config.json) by category. Navigation & search on the left (a choice
// list on narrow pages), options of the category in group cards, status cards (web dashboard address,
// remote control, settings file). Edits stay pending until applied: bar at the bottom with Undo, Redo,
// Discard & Apply (Ctrl+S). A search ("/") looks through every category.
TpPage {
    id: page

    readonly property bool narrow: width < theme.em * 52  // navigation as a choice list
    readonly property var info: backend.categoryInfo
    readonly property var web: backend.webDashboard
    readonly property var remote: backend.remoteControl
    readonly property var previews: backend.previews

    function scrollToKey(key) {
        for (var i = 0; i < rows.count; i++) {
            var item = rows.itemAt(i)
            if (item && item.key === key) {
                var y = item.mapToItem(optionsColumn, 0, 0).y
                flick.contentY = Math.max(0, Math.min(y - theme.em * 2, flick.contentHeight - flick.height))
                item.flash()
                return
            }
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
        function onCategoryChanged() { flick.contentY = 0 }
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
                anchors.margins: theme.em * 0.6
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
                    model: backend.categories
                    activeFocusOnTab: true
                    currentIndex: -1
                    Keys.onUpPressed: navStep(-1)
                    Keys.onDownPressed: navStep(1)
                    function navStep(offset) {
                        var keys = backend.categories.map(function(entry) { return entry.key })
                        var index = keys.indexOf(backend.category)
                        backend.selectCategory(keys[Math.max(0, Math.min(keys.length - 1, index + offset))])
                    }
                    delegate: Rectangle {
                        id: entry
                        required property var modelData
                        readonly property bool selected: !backend.searching && backend.category === modelData.key
                        readonly property bool dimmed: backend.searching && modelData.matches === 0
                        width: ListView.view.width
                        height: Math.round(theme.em * 2.4)
                        radius: theme.em * 0.5
                        color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.2 : 0.13)
                             : entryArea.containsMouse ? theme.hover : "transparent"
                        opacity: dimmed ? 0.45 : 1
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Behavior on opacity { NumberAnimation { duration: 150 } }
                        Accessible.role: Accessible.PageTab
                        Accessible.name: modelData.label
                        Accessible.selected: selected

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
                            glyph: entry.modelData.glyph
                            color: entry.selected ? theme.accent : theme.dimText
                            size: theme.em * 1.0
                        }
                        Text {
                            anchors.left: entryIcon.visible ? entryIcon.right : parent.left
                            anchors.leftMargin: entryIcon.visible ? theme.em * 0.6 : theme.em * 0.8
                            anchors.right: badge.left
                            anchors.rightMargin: theme.em * 0.3
                            anchors.verticalCenter: parent.verticalCenter
                            text: entry.modelData.label
                            color: theme.text
                            font.weight: entry.selected ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            id: badge
                            readonly property int count: backend.searching ? entry.modelData.matches : entry.modelData.changed
                            visible: count > 0
                            anchors.right: parent.right
                            anchors.rightMargin: theme.em * 0.5
                            anchors.verticalCenter: parent.verticalCenter
                            height: Math.round(theme.em * 1.3)
                            width: Math.max(height, badgeText.implicitWidth + theme.em * 0.6)
                            radius: height / 2
                            color: entry.modelData.errors > 0 && !backend.searching ? theme.loss
                                 : backend.searching ? theme.hover : theme.accent
                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: badge.count
                                color: backend.searching ? theme.text : "white"
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
                                backend.selectCategory(entry.modelData.key)
                                search.clear()
                            }
                        }
                    }
                }

                // Settings kept in the loaded preset
                Text {
                    Layout.fillWidth: true
                    Layout.topMargin: theme.em * 0.3
                    text: i18n.tr("In the loaded preset")
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.8
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
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
                        implicitHeight: Math.round(theme.em * 2.1)
                        radius: theme.em * 0.5
                        color: linkArea.containsMouse ? theme.hover : "transparent"
                        Accessible.role: Accessible.Link
                        Accessible.name: modelData.text
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
                Layout.margins: theme.em * 0.8
                Layout.bottomMargin: 0
                spacing: theme.em * 0.5
                TpCombo {
                    Layout.preferredWidth: theme.em * 13
                    model: backend.categories.map(function(entry) { return entry.label })
                    currentIndex: backend.categories.map(function(entry) { return entry.key }).indexOf(backend.category)
                    onActivated: function(index) { backend.selectCategory(backend.categories[index].key) }
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
                    text: theme.iconFont === "" ? "..." : ""
                    tip: i18n.tr("In the loaded preset")
                    checked: presetLinks.visible
                    onClicked: presetLinks.visible ? presetLinks.close() : presetLinks.popup(presetLinksButton, 0, presetLinksButton.height + 4)
                    TpMenu {
                        id: presetLinks
                        Action { text: i18n.tr("Units"); onTriggered: backend.openLink("units") }
                        Action { text: i18n.tr("Global Font Override"); onTriggered: backend.openLink("font") }
                        Action { text: i18n.tr("API Options"); onTriggered: backend.openLink("api") }
                    }
                }
            }

            // Header
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 1.0
                Layout.rightMargin: theme.em * 1.0
                Layout.topMargin: theme.em * 0.8
                Layout.bottomMargin: theme.em * 0.4
                spacing: theme.em * 0.7
                Rectangle {
                    Layout.preferredWidth: Math.round(theme.em * 2.6)
                    Layout.preferredHeight: Layout.preferredWidth
                    radius: theme.em * 0.6
                    color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.18 : 0.12)
                    Icon {
                        anchors.centerIn: parent
                        glyph: backend.searching ? "" : page.info.glyph  // search
                        color: theme.accent
                        size: theme.em * 1.3
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Text {
                        Layout.fillWidth: true
                        text: backend.searching ? i18n.tr("Search results") : page.info.label
                        color: theme.text
                        font.pointSize: theme.fontPoint * 1.45
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
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

            // Options
            Flickable {
                id: flick
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: width
                contentHeight: optionsColumn.implicitHeight + theme.em * 1.2
                boundsBehavior: Flickable.StopAtBounds
                activeFocusOnTab: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                Keys.onUpPressed: flick.contentY = Math.max(0, flick.contentY - theme.em * 3)
                Keys.onDownPressed: flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, flick.contentY + theme.em * 3))

                Column {
                    id: optionsColumn
                    x: theme.em * 1.0
                    width: flick.width - theme.em * 2.0
                    spacing: 0

                    // Web dashboard: addresses & access code
                    Card {
                        width: parent.width
                        visible: !backend.searching && backend.category === "web_dashboard"
                        height: visible ? webColumn.implicitHeight + theme.em * 1.4 : 0
                        ColumnLayout {
                            id: webColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: theme.em * 0.7
                            spacing: theme.em * 0.4
                            RowLayout {
                                spacing: theme.em * 0.45
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
                                        Layout.fillWidth: true
                                        text: modelData
                                        color: theme.accent
                                        font.underline: linkArea.containsMouse
                                        elide: Text.ElideMiddle
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
                                        text: i18n.tr("Copy")
                                        implicitHeight: Math.round(theme.em * 1.9)
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
                                    font.pointSize: theme.fontPoint * 1.2
                                    font.weight: Font.DemiBold
                                    font.letterSpacing: 2
                                    font.features: { "tnum": 1 }
                                }
                                TpButton {
                                    flat: true
                                    text: i18n.tr("Copy")
                                    implicitHeight: Math.round(theme.em * 1.9)
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
                                font.family: "Consolas"
                                font.pointSize: theme.fontPoint * 0.85
                            }
                        }
                    }

                    // Remote control: address
                    Card {
                        width: parent.width
                        visible: !backend.searching && backend.category === "remote_control"
                        height: visible ? remoteColumn.implicitHeight + theme.em * 1.4 : 0
                        ColumnLayout {
                            id: remoteColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: theme.em * 0.7
                            spacing: theme.em * 0.3
                            RowLayout {
                                spacing: theme.em * 0.45
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
                                model: [
                                    { "text": page.remote.command || "", "tip": i18n.tr("Command, with its required header") },
                                    { "text": page.remote.commands || "", "tip": i18n.tr("List of commands (JSON)") },
                                    { "text": page.remote.stream || "", "tip": i18n.tr("Live telemetry (WebSocket)") },
                                ]
                                RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: theme.em * 0.4
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.text
                                        color: theme.text
                                        font.family: "Consolas"
                                        font.pointSize: theme.fontPoint * 0.9
                                        elide: Text.ElideMiddle
                                        MouseArea { id: codeArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                                        ToolTip.visible: codeArea.containsMouse
                                        ToolTip.text: modelData.tip
                                        ToolTip.delay: 400
                                    }
                                    TpButton {
                                        flat: true
                                        text: i18n.tr("Copy")
                                        implicitHeight: Math.round(theme.em * 1.9)
                                        onClicked: backend.copyText(modelData.text)
                                    }
                                }
                            }
                        }
                    }

                    Item { width: 1; height: theme.em * 0.2; visible: !backend.searching && (backend.category === "web_dashboard" || backend.category === "remote_control") }

                    Repeater {
                        id: rows
                        model: backend.options
                        SettingRow {
                            width: optionsColumn.width
                            preview: backend.category === "notification" && !backend.searching ? (page.previews[group] || null) : null
                        }
                    }

                    EmptyState {
                        visible: rows.count === 0
                        width: optionsColumn.width
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
                                font.pointSize: theme.fontPoint * 0.85
                                elide: Text.ElideMiddle
                            }
                            TpButton {
                                flat: true
                                glyph: ""  // open folder
                                text: i18n.tr("Open Folder")
                                implicitHeight: Math.round(theme.em * 1.9)
                                onClicked: backend.openConfigFolder()
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
                        color: backend.errorCount > 0 ? theme.loss : theme.text
                        elide: Text.ElideRight
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
