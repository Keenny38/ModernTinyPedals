import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQml.Models
import "../components"

// Recorded laps grouped by session: click to compare (Shift+click: every lap between), flag (or double-click)
// to set reference lap, click a sector time: zoom charts on sector, search by vehicle, session, conditions, note.
// Right-click a lap or a session header: keep, note, move to trash, delta best... Keys (wherever focus is on the page,
// text fields keep them): "/" search, Delete moves the highlighted lap (legend chip) or the checked laps to trash.
// Header: "Compare Laps ▾" (compare presets, guided analysis), "⋯" (actions on checked laps, trash).
Card {
    id: root

    property var chart  // TraceChart
    property string menuPath: ""
    property bool menuKept: false
    property bool menuShown: false  // lap right-clicked is shown & not reference lap (setup differences)
    property string anchorPath: ""  // last clicked lap (Shift+click range start)
    property string menuSession: ""  // session header right-clicked
    property bool menuFromList: false  // menu opened from the focused list (keys): focus back to it once closed

    // Keys back to charts (lap clicked, search left): space, arrows, A/B work again without clicking charts
    function keysToChart() { if (root.chart) root.chart.forceActiveFocus() }
    // Menu closed: keys back where they were (focused list, else charts)
    function menuClosed() {
        if (root.menuFromList) list.forceActiveFocus()
        else root.keysToChart()
        root.menuFromList = false
    }
    // Lap highlighted by clicking its legend chip (kept, never a chip only hovered) moved to trash, else checked laps
    // (confirmed if several); the page names the lap in a toast with Undo
    function deleteLaps() {
        var key = root.chart ? root.chart.pinnedKey : ""
        if (key !== "" && backend.lapActions(key).recorded) backend.deleteLap(key)
        else backend.deleteChecked()
    }

    Shortcut {
        sequence: "/"
        enabled: pageState.active && root.visible
        onActivated: { searchField.forceActiveFocus(); searchField.selectAll() }
    }
    Shortcut {
        sequences: [StandardKey.Delete]
        enabled: pageState.active && root.visible
        onActivated: root.deleteLaps()
    }

    // Right-click on lap: recorded laps of track can also be kept, noted & deleted
    function openLapMenu(path, item, x, y) {
        var actions = backend.lapActions(path)
        menuPath = path
        menuKept = actions.kept
        menuShown = backend.isCompared(path)
        menuFromList = list.activeFocus
        if (actions.recorded) recordedMenu.popup(item, x, y)
        else addedMenu.popup(item, x, y)
    }

    TpMenu {
        id: recordedMenu
        onClosed: root.menuClosed()
        Action { text: i18n.tr("Set as Reference"); onTriggered: backend.setReference(root.menuPath) }
        Action { text: i18n.tr("Export MoTeC…"); onTriggered: backend.exports.exportMotec(root.menuPath) }
        Action { text: i18n.tr("Share Lap…"); onTriggered: backend.exports.shareLap(root.menuPath) }
        MenuSeparator {}
        Action {
            text: i18n.tr("Keep Lap")
            checkable: true
            checked: root.menuKept
            onTriggered: backend.keepLap(root.menuPath, checked)
        }
        Action { text: i18n.tr("Note…"); onTriggered: backend.editNote(root.menuPath) }
        Action { text: i18n.tr("Use as Delta Best…"); onTriggered: backend.exports.exportDeltaBest(root.menuPath) }
        Action {
            text: i18n.tr("Setup Differences with Reference…")
            enabled: root.menuShown
            onTriggered: setupDiff.show(root.menuPath)
        }
        MenuSeparator {}
        Action { text: i18n.tr("Move to Trash"); onTriggered: backend.deleteLap(root.menuPath) }
    }
    TpMenu {
        id: sessionMenu
        onClosed: root.menuClosed()
        Action { text: i18n.tr("Show Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "show") }
        Action { text: i18n.tr("Hide Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "hide") }
        MenuSeparator {}
        Action { text: i18n.tr("Keep Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "keep") }
        Action { text: i18n.tr("Stop Keeping Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "unkeep") }
        MenuSeparator {}
        Action { text: i18n.tr("Move Session Laps to Trash…"); onTriggered: backend.sessionAction(root.menuSession, "delete") }
    }
    TpMenu {
        id: addedMenu
        onClosed: root.menuClosed()
        Action { text: i18n.tr("Set as Reference"); onTriggered: backend.setReference(root.menuPath) }
        Action { text: i18n.tr("Export MoTeC…"); onTriggered: backend.exports.exportMotec(root.menuPath) }
        Action { text: i18n.tr("Share Lap…"); onTriggered: backend.exports.shareLap(root.menuPath) }
    }
    // Setup differences of a shown lap with reference lap (lap list menu)
    CarSetupDiff { id: setupDiff }
    // Compare presets (Compare ▾): laps checked for one look, reference set
    TpMenu {
        id: compareMenu
        objectName: "compareMenu"
        onClosed: root.keysToChart()
        Action { text: i18n.tr("Best vs Last Lap"); onTriggered: backend.compareBestLast() }
        Action { text: i18n.tr("3 Best Laps"); onTriggered: backend.compareBest(3) }
        Action { text: i18n.tr("5 Best Laps"); onTriggered: backend.compareBest(5) }
        // Lap looked at (first compared lap, else newest) against fastest lap driven in similar conditions
        Action { text: i18n.tr("Best Lap in Similar Conditions"); onTriggered: backend.conditions.compareSimilarConditions() }
        TpMenu {
            id: toleranceMenu
            title: i18n.tr("Similar Track Temperature")
            Instantiator {
                model: backend.conditions.similarTolerances
                delegate: Action {
                    required property var modelData
                    text: modelData.text
                    checkable: true
                    checked: backend.conditions.similarTolerance === modelData.value
                    onTriggered: backend.conditions.setSimilarTolerance(modelData.value)
                }
                onObjectAdded: function(index, object) { toleranceMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { toleranceMenu.removeAction(object) }
            }
        }
        MenuSeparator {}
        // Guided analysis: best vs last lap, Corners tool on the corner where most time is lost
        Action { text: i18n.tr("Analyze My Last Lap"); onTriggered: backend.analyzeLastLap() }
        MenuSeparator {}
        Action { text: i18n.tr("Uncheck All"); onTriggered: backend.clearSelection() }
    }
    // Actions on checked laps (⋯), trash
    TpMenu {
        id: bulkMenu
        objectName: "bulkMenu"
        onClosed: root.keysToChart()
        Action { text: i18n.tr("Keep Checked Laps"); onTriggered: backend.keepChecked(true) }
        Action { text: i18n.tr("Stop Keeping Checked Laps"); onTriggered: backend.keepChecked(false) }
        Action { text: i18n.tr("Export Checked Laps (MoTeC)…"); onTriggered: backend.exports.exportMotecMany(false) }
        MenuSeparator {}
        Action { text: i18n.tr("Move Checked Laps to Trash…"); onTriggered: backend.deleteChecked() }
        Action { text: i18n.tr("Recently Deleted Laps…"); onTriggered: recentlyDeleted.open() }
    }
    // Sessions listed (practice, qualifying, race) & order of sessions and laps (filter button beside search)
    TpMenu {
        id: viewMenu
        objectName: "viewMenu"
        onClosed: root.keysToChart()
        Action {
            text: i18n.tr("Practice") + "  (" + (backend.sessionCounts.practice || 0) + ")"
            checkable: true
            checked: backend.sessionKinds.indexOf("practice") >= 0
            onTriggered: backend.setSessionShown("practice", checked)
        }
        Action {
            // Session header name (French: Qualifications, not Qualif)
            text: i18n.tr("Qualify") + "  (" + (backend.sessionCounts.qualify || 0) + ")"
            checkable: true
            checked: backend.sessionKinds.indexOf("qualify") >= 0
            onTriggered: backend.setSessionShown("qualify", checked)
        }
        Action {
            text: i18n.tr("Race") + "  (" + (backend.sessionCounts.race || 0) + ")"
            checkable: true
            checked: backend.sessionKinds.indexOf("race") >= 0
            onTriggered: backend.setSessionShown("race", checked)
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("Newest Sessions First")
            checkable: true
            checked: backend.sessionOrder === "newest"
            onTriggered: backend.setSessionOrder("newest")
        }
        Action {
            text: i18n.tr("Oldest Sessions First")
            checkable: true
            checked: backend.sessionOrder === "oldest"
            onTriggered: backend.setSessionOrder("oldest")
        }
        Action {
            text: i18n.tr("Fastest Sessions First")
            checkable: true
            checked: backend.sessionOrder === "fastest"
            onTriggered: backend.setSessionOrder("fastest")
        }
        MenuSeparator {}
        Action {
            text: i18n.tr("Laps in Driving Order")
            checkable: true
            checked: backend.lapOrder === "driven"
            onTriggered: backend.setLapOrder("driven")
        }
        Action {
            text: i18n.tr("Fastest Laps First")
            checkable: true
            checked: backend.lapOrder === "fastest"
            onTriggered: backend.setLapOrder("fastest")
        }
    }
    // Laps of trash folder, restored one by one (quick selection menu)
    RecentlyDeleted { id: recentlyDeleted; objectName: "recentlyDeleted"; onClosed: root.keysToChart() }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.space3

        TpCardHeader {
            Layout.leftMargin: theme.space2
            title: i18n.tr("Laps")
            busy: backend.loading
            TpButton {
                id: compareButton
                objectName: "compareButton"
                text: i18n.tr("Compare Laps") + " ▾"
                flat: true
                size: "sm"
                tip: i18n.tr("Quick selection: best vs last lap, best laps, uncheck all")
                checked: compareMenu.visible
                onClicked: compareMenu.toggleBelow(compareButton)
                // Narrow list: label cut before the switch is (full text in tooltip)
                Layout.maximumWidth: implicitWidth
                Layout.minimumWidth: Math.min(implicitWidth, theme.controlHeightSm * 2.5)
                Layout.fillWidth: true
            }
            TpButton {
                id: bulkButton
                objectName: "bulkButton"
                glyph: theme.glyphs.more
                fallback: "⋯"
                flat: true
                size: "sm"
                tip: i18n.tr("Checked laps: keep, export, move to trash, recently deleted")
                checked: bulkMenu.visible
                onClicked: bulkMenu.toggleBelow(bulkButton, true)
            }
        }

        // Search: every word found in lap name, time, session, vehicle, conditions, note or setup; clean laps
        // switch beside it (header kept for title & menus: narrow list, French)
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3

            TpSearchField {
                id: searchField
                Layout.fillWidth: true
                Layout.minimumWidth: theme.controlHeight * 3
                implicitHeight: Math.round(theme.fieldHeight)
                searchDelay: 250
                placeholderText: i18n.tr("Search laps: car, session, note…")
                Component.onCompleted: text = backend.filterText  // not bound: search stripped by backend, typed text kept
                onSearchChanged: function(text) { backend.setFilter(text) }
                onExitField: root.keysToChart()
                Keys.onEscapePressed: { clearSearch(); root.keysToChart() }
                Keys.onReturnPressed: root.keysToChart()
                Keys.onEnterPressed: root.keysToChart()
                Keys.onDownPressed: { list.forceActiveFocus(); list.currentIndex = Math.max(list.currentIndex, 0) }  // into the list
            }
            TpButton {
                id: viewButton
                objectName: "viewButton"
                // Highlighted while sessions are left out or listed in another order
                readonly property bool changed: backend.sessionKinds.length < 3 || backend.sessionOrder !== "newest"
                                                || backend.lapOrder !== "driven"
                glyph: ""  // filter
                fallback: "≡"
                flat: !changed
                size: "sm"
                tip: i18n.tr("Sessions shown (practice, qualifying, race) and sort order")
                checked: viewMenu.visible
                onClicked: viewMenu.toggleBelow(viewButton)
            }
            TpSwitch {
                objectName: "cleanOnlySwitch"
                text: i18n.tr("Clean only")
                tip: i18n.tr("Hide invalid, out & in laps")
                Layout.maximumWidth: implicitWidth
                checkable: false  // follows the backend (never unbound by a click)
                checked: backend.hideUnclean
                onClicked: backend.setHideUnclean(!backend.hideUnclean)
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.laps  // lap rows of expanded sessions only, rows changed in place (scroll position kept)
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true  // rows scrolled out fed again with other laps (see delegate onPooled)
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            objectName: "lapRows"
            activeFocusOnTab: true
            keyNavigationEnabled: true
            Accessible.role: Accessible.List
            Accessible.name: i18n.tr("Laps")
            // Row under keyboard: lap row actions (Space, Enter, menu key)
            function act(kind) {
                var item = currentItem
                if (!item) return
                if (item.kind === "session") {
                    if (kind === "menu") { root.menuSession = item.session; root.menuFromList = true; sessionMenu.popup(item, theme.em, item.height) }
                    else backend.toggleSession(item.session)
                    return
                }
                if (kind === "toggle") { backend.toggleLap(item.path); root.anchorPath = item.path }
                else if (kind === "reference") backend.setReference(item.path)
                else root.openLapMenu(item.path, item, theme.em, item.height)
            }
            Keys.onSpacePressed: act("toggle")
            Keys.onReturnPressed: act("reference")
            Keys.onEnterPressed: act("reference")
            Keys.onEscapePressed: root.keysToChart()
            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
                    act("menu")
                    event.accepted = true
                } else if (searchField.routeTyped(event)) {
                    event.accepted = true
                }
            }
            Keys.onShortcutOverride: function(event) {  // focused list takes its keys (charts shortcuts wait)
                if ([Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End,
                     Qt.Key_PageUp, Qt.Key_PageDown].indexOf(event.key) >= 0)
                    event.accepted = true
            }

            // Session laps fade in & out as session is expanded or collapsed, rows below slide
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }
            remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: theme.motionFast } }
            displaced: Transition {
                NumberAnimation { property: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic }
                NumberAnimation { property: "opacity"; to: 1; duration: theme.motionBase }  // fade in cut short: row shown anyway
            }

            // Search or clean only leaves no lap: say so, with a way back (checked laps stay listed above)
            footer: Item {
                width: list.width
                height: backend.noMatch ? noMatch.height + theme.em * 2.5 : 0
                TpStateView {
                    id: noMatch
                    readonly property bool searching: backend.filterText !== ""
                    readonly property bool sessionsLeft: !searching && backend.sessionKinds.length < 3  // sessions filtered
                    y: theme.space6
                    anchors.horizontalCenter: parent.horizontalCenter
                    empty: backend.noMatch
                    glyph: searching ? "" : ""  // search, filter
                    title: searching ? i18n.tr("No lap matches the search")
                         : sessionsLeft ? i18n.tr("No lap in the sessions shown") : i18n.tr("No clean lap")
                    text: searching ? i18n.tr("Search looks in lap number, time, session, car, conditions, note and setup.")
                        : sessionsLeft ? i18n.tr("Practice, qualifying or race sessions are left out (filter beside the search).")
                        : i18n.tr("Every lap is invalid, an out lap or an in lap.")
                    actionText: searching ? i18n.tr("Clear Search")
                              : sessionsLeft ? i18n.tr("Show All Sessions") : i18n.tr("Show All Laps")
                    onAction: {
                        if (searching) {
                            searchField.clearSearch()
                        } else if (sessionsLeft) {
                            backend.showAllSessions()
                        } else {
                            backend.setHideUnclean(false)
                        }
                    }
                }
            }

            // One delegate per row type (session header, lap): a row only builds the items it shows
            delegate: DelegateChooser {
                role: "kind"
                DelegateChoice {  // Session header
                    roleValue: "session"
                    Item {
                        id: row
                        required property int index
                        required property string kind
                        required property string session
                        required property string path
                        required property string title
                        required property string time
                        required property string info
                        required property int count
                        required property bool open  // session expanded
                        required property string logo  // car brand logo of game
                        // Reused row (ListView.reuseItems, one pool per row type): fed other values at once, no animation
                        property bool live: true
                        ListView.onPooled: { live = false; opacity = 1 }  // remove transition may have faded it out
                        ListView.onReused: live = true
                        width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                        height: Math.round(theme.row)
                        Accessible.role: Accessible.ListItem
                        Accessible.name: row.title + (row.open ? "" : ", " + row.count)

                        Rectangle {
                            id: headerSurface
                            anchors.fill: parent
                            anchors.topMargin: row.index > 0 ? theme.space3 : 0
                            radius: theme.radiusMd
                            color: headerArea.pressed ? theme.surfaceSunken : theme.rowColor(headerArea.containsMouse, false)
                            Behavior on color { enabled: row.live; ColorAnimation { duration: theme.motionFast } }
                            FocusRing { visible: row.ListView.isCurrentItem && list.activeFocus }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: theme.space2
                                anchors.rightMargin: theme.space3
                                spacing: theme.space3
                                Icon {
                                    glyph: ""  // chevron right
                                    fallback: "›"
                                    size: theme.iconXs
                                    color: theme.dimText
                                    rotation: row.open ? 90 : 0
                                    Behavior on rotation { enabled: row.live; NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutCubic } }
                                }
                                Text {
                                    text: row.title
                                    textFormat: Text.PlainText
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                    Layout.preferredWidth: implicitWidth
                                    Layout.minimumWidth: Math.min(implicitWidth, theme.em * 4)
                                }
                                GameLogo {  // car brand logo of game
                                    source: row.logo
                                    boxWidth: theme.em * 2.0
                                    boxHeight: theme.em * 1.1
                                }
                                Text {
                                    text: row.info
                                    textFormat: Text.PlainText
                                    visible: text !== ""
                                    color: theme.dimText
                                    font.pointSize: theme.fontSmall
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                TpCountBadge { text: row.count }
                                Text {
                                    text: row.time
                                    textFormat: Text.PlainText
                                    color: theme.dimText
                                    font.features: { "tnum": 1 }
                                }
                            }
                            MouseArea {
                                id: headerArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                onClicked: function(mouse) {
                                    if (mouse.button === Qt.RightButton) {
                                        root.menuSession = row.session
                                        sessionMenu.popup(headerArea, mouse.x, mouse.y)
                                    } else {
                                        list.currentIndex = row.index
                                        backend.toggleSession(row.session)
                                        root.keysToChart()
                                    }
                                }
                            }
                        }
                    }
                }
                DelegateChoice {  // Lap
                    Item {
                        id: row
                        required property int index
                        required property string kind
                        required property string session
                        required property string path
                        required property string title
                        required property string time
                        required property string s1
                        required property string s2
                        required property string s3
                        required property bool best1
                        required property bool best2
                        required property bool best3
                        required property string info
                        required property string note
                        required property bool checked
                        required property bool reference
                        required property string color
                        required property bool dim
                        required property bool fastest
                        required property bool personalBest
                        required property bool error
                        required property string gap
                        required property string tip
                        required property string hint  // lap of another circuit than reference lap: never compared
                        required property string compound  // tyre compound of lap ("" not recorded, session rows)
                        // Reused row (ListView.reuseItems, one pool per row type): fed other values at once, no animation
                        property bool live: true
                        ListView.onPooled: { live = false; opacity = 1 }  // remove transition may have faded it out
                        ListView.onReused: live = true
                        width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                        height: Math.round(theme.rowTall)
                        Accessible.role: Accessible.ListItem
                        Accessible.name: row.title + " " + row.time + (row.reference ? ", " + i18n.tr("Reference") : "")
                        Accessible.checkable: true
                        Accessible.checked: row.checked

                        // Row look of TpListRow (theme.rowColor), color animation off while the row is fed again
                        Rectangle {
                            anchors.fill: parent
                            anchors.topMargin: 1
                            anchors.bottomMargin: 1
                            radius: theme.radiusMd
                            color: lapArea.pressed && !row.checked ? theme.border : theme.rowColor(lapArea.containsMouse, row.checked)
                            Behavior on color { enabled: row.live; ColorAnimation { duration: theme.motionFast } }
                            FocusRing { visible: row.ListView.isCurrentItem && list.activeFocus }
                            ToolTip.visible: lapArea.containsMouse && (row.tip !== "" || row.hint !== "" || row.error)
                            ToolTip.text: !lapArea.containsMouse ? ""  // text made when hovered only
                                : row.error ? i18n.tr("Unable to read this lap file") : [row.hint, row.tip].filter(Boolean).join("\n")
                            ToolTip.delay: theme.tipDelay

                            // Lap color bar when shown in charts
                            Rectangle {
                                width: 3
                                radius: 1.5
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                anchors.margins: theme.space3
                                color: row.color || "transparent"
                                scale: row.color ? 1 : 0
                                Behavior on scale { enabled: row.live; NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutBack } }
                            }

                            MouseArea {
                                id: lapArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                onClicked: function(mouse) {
                                    if (mouse.button === Qt.RightButton) {
                                        root.openLapMenu(row.path, lapArea, mouse.x, mouse.y)
                                    } else if ((mouse.modifiers & Qt.ShiftModifier) && root.anchorPath !== "") {
                                        list.currentIndex = row.index
                                        backend.selectRange(root.anchorPath, row.path, !row.checked)
                                        root.keysToChart()
                                    } else {
                                        list.currentIndex = row.index
                                        backend.toggleLap(row.path)
                                        root.anchorPath = row.path
                                        root.keysToChart()
                                    }
                                }
                                onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.setReference(row.path) }
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: theme.padPopup
                                anchors.rightMargin: theme.space3
                                spacing: theme.space3
                                id: lapContent
                                readonly property bool other: row.hint !== ""  // other circuit: dim italic texts (tooltip tells)

                                // Check box (warning if lap file unreadable)
                                Rectangle {
                                    implicitWidth: theme.em * 1.15
                                    implicitHeight: implicitWidth
                                    radius: theme.radiusSm
                                    color: row.error ? theme.warning : row.checked ? (row.color || theme.accentFill) : "transparent"
                                    border.width: row.checked || row.error ? 0 : 1.5
                                    border.color: theme.dimText
                                    Behavior on color { enabled: row.live; ColorAnimation { duration: theme.motionBase } }
                                    Icon {
                                        anchors.centerIn: parent
                                        glyph: row.error ? "" : ""  // warning, check mark
                                        fallback: row.error ? "!" : "✓"
                                        size: theme.iconXs
                                        color: theme.inkOn(row.error ? theme.warning : (row.color || theme.accentFill))
                                        opacity: row.checked || row.error ? 1 : 0
                                        Behavior on opacity { enabled: row.live; NumberAnimation { duration: theme.motionFast } }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    RowLayout {
                                        spacing: theme.space3
                                        Text {
                                            text: row.title
                                            textFormat: Text.PlainText
                                            color: lapContent.other ? theme.dimText : theme.text
                                            font.weight: row.reference ? Font.Bold : Font.Normal
                                            font.italic: lapContent.other
                                        }
                                        Rectangle {
                                            visible: row.reference
                                            radius: theme.radiusSm
                                            color: theme.accentFill
                                            implicitWidth: refText.implicitWidth + theme.em * 0.6
                                            implicitHeight: refText.implicitHeight + 2
                                            Text {
                                                id: refText
                                                anchors.centerIn: parent
                                                text: i18n.tr("REF")
                                                color: theme.accentInk
                                                font.pointSize: theme.fontCaption
                                                font.weight: Font.Bold
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            visible: row.gap !== ""
                                            text: row.gap
                                            textFormat: Text.PlainText
                                            color: theme.dimText
                                            font.pointSize: theme.fontCaption
                                            font.features: { "tnum": 1 }
                                        }
                                        TpCompound {  // tyre compound badge, as Results, Stats & Calculator
                                            visible: row.compound !== ""
                                            name: row.compound.split("/")[0]  // front compound when they differ
                                            HoverHandler { id: compoundHover }
                                            ToolTip.visible: compoundHover.hovered
                                            ToolTip.text: row.compound
                                            ToolTip.delay: theme.tipDelay
                                        }
                                        // Session fastest lap: ◆ purple, personal best of track: ● green (shared mark)
                                        TpLapTime {
                                            text: row.time
                                            record: lapContent.other ? "" : row.fastest ? "session" : row.personalBest ? "personal" : ""
                                            textColor: row.dim || lapContent.other ? theme.dimText : theme.text
                                            strong: true
                                            reserveMark: false
                                        }
                                    }
                                    RowLayout {
                                        spacing: theme.space4
                                        // Three sectors: fixed texts (no array & Repeater per row)
                                        SectorText { value: row.s1; best: row.best1; sector: 1; chart: root.chart }
                                        SectorText { value: row.s2; best: row.best2; sector: 2; chart: root.chart }
                                        SectorText { value: row.s3; best: row.best3; sector: 3; chart: root.chart }
                                        Text {
                                            text: row.note === "" ? row.info
                                                : (row.info !== "" ? row.info + " · " : "") + "“" + row.note + "”"
                                            textFormat: Text.PlainText
                                            color: theme.dimText
                                            font.pointSize: theme.fontSmall
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                    }
                                }

                                // Set as reference
                                TpButton {
                                    glyph: ""  // flag
                                    fallback: "⚑"
                                    flat: true
                                    size: "sm"
                                    focusPolicy: Qt.NoFocus  // keys: Enter on the lap row sets reference (no hidden focus stop)
                                    tip: i18n.tr("Set as Reference")
                                    opacity: row.reference || lapArea.containsMouse || hovered ? 1 : 0  // revealed: hover, reference
                                    checked: row.reference
                                    Behavior on opacity { enabled: row.live; NumberAnimation { duration: theme.motionFast } }
                                    onClicked: backend.setReference(row.path)
                                }
                            }
                        }
                    }
                }
            }
        }

        Text {
            visible: text !== ""
            text: backend.bestText
            textFormat: Text.PlainText
            color: theme.purple
            font.weight: Font.DemiBold
            Layout.leftMargin: theme.space2
        }
    }

    // No lap on this track yet, or laps being read (list empty meanwhile): centered over the list
    TpStateView {
        objectName: "lapListState"
        anchors.centerIn: parent
        anchors.verticalCenterOffset: theme.em * 2
        compact: true
        loading: backend.loading && list.count === 0
        empty: !backend.loading && list.count === 0 && !backend.noMatch
        loadingText: i18n.tr("Reading laps…")
        glyph: "\uE81C"  // history
        title: i18n.tr("No recorded lap")
        text: i18n.tr("Laps driven on this track are listed here once recorded. Laps from elsewhere: Import.")
        actionText: i18n.tr("Add File…")
        onAction: backend.exports.addFiles()
    }

    // Sector time of a lap row: best sector in purple, click zooms charts on the sector
    component SectorText: Text {
        id: sectorText
        property string value
        property bool best
        property int sector
        property var chart
        text: value
        textFormat: Text.PlainText
        color: sectorArea.containsMouse ? theme.accent : best ? theme.purple : theme.dimText
        font.pointSize: theme.fontSmall
        font.features: { "tnum": 1 }
        font.weight: best ? Font.DemiBold : Font.Normal
        MouseArea {
            id: sectorArea
            anchors.fill: parent
            enabled: sectorText.value !== "—" && sectorText.value !== "" && sectorText.chart !== undefined
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: sectorText.chart.zoomSector(sectorText.sector)
            ToolTip.visible: containsMouse
            ToolTip.text: containsMouse ? i18n.tr("Zoom charts on this sector") : ""  // made when hovered only
            ToolTip.delay: theme.tipDelay
        }
    }
}
