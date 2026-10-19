import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"
import "../config"

// Lap telemetry viewer page: lap list, channel charts (advanced view) or simple view over them, track map / G circle /
// corners / range statistics
TpPage {
    id: page

    property bool mapFocus: false  // large track map over laps & charts
    property alias traceChart: chart  // for components (map in focus mode): "chart" there is their own property
    // Menu of a toolbar action, under its button (or under the toolbar's "⋯" button), closed by a second click
    function toggleMenu(menu, source) {
        if (menu.visible) menu.close()
        else menu.popup(source, 0, source.height + theme.space1)
    }
    // Laps moved to trash: lap named, undo at hand (Ctrl+Z also restores them)
    function showTrashed(count, label) {
        toast.text = count === 1 && label !== "" ? i18n.tr("%1 moved to trash").arg(label)
                                                 : i18n.tr("%1 laps moved to trash").arg(count)
        toast.show()
    }
    Connections {
        target: backend
        function onLapsTrashed(count, label) { page.showTrashed(count, label) }
    }

    // Page picture (laps, charts, map) saved to PNG or copied to clipboard
    function grabPicture(copy) {
        bodyArea.grabToImage(function(result) {
            if (copy) backend.exports.copyImage(result.image)
            else backend.exports.saveImage(result.image)
        })
    }
    // Charts & map zoomed on passage between markers A & B, picture taken once zoom settled
    function grabPassage() {
        chart.zoomRange([Math.min(chart.markerA, chart.markerB), Math.max(chart.markerA, chart.markerB)], 0.03)
        passageTimer.restart()
    }
    Timer { id: passageTimer; interval: 900; onTriggered: page.grabPicture(false) }

    Component.onCompleted: chart.forceActiveFocus()
    // Keys to charts: page shown (dialog first gives them to first control), map focus mode left.
    // Deleted laps restored with Ctrl+Z: shortcut of page dialog (lap_viewer.py), only while page is shown
    function focusCharts() { chart.forceActiveFocus() }
    onMapFocusChanged: if (!mapFocus) chart.forceActiveFocus()
    // Esc left by a control (map, slider...): keys back to charts, never closes viewer window or page
    Keys.onEscapePressed: function(event) {
        page.mapFocus = false
        chart.forceActiveFocus()
        event.accepted = true
    }

    // Toolbar menus & Show popup (opened under the action's button, see toolbar)
    TpMenu {
        id: importMenu
        onClosed: chart.forceActiveFocus()
        Action { text: i18n.tr("Add File..."); onTriggered: backend.exports.addFiles() }
        Action { text: i18n.tr("Imported Laps..."); onTriggered: backend.openLibrary() }
        Action { text: i18n.tr("Import Folder..."); onTriggered: backend.exports.importFolder() }
    }
    TpMenu {
        id: exportMenu
        onClosed: chart.forceActiveFocus()
        TpMenu {
            title: "MoTeC i2 (.ld)"
            Action { text: i18n.tr("Reference Lap..."); onTriggered: backend.exports.exportMotec("") }
            Action { text: i18n.tr("Displayed Laps..."); onTriggered: backend.exports.exportMotecMany(false) }
            Action { text: i18n.tr("All Laps of Track..."); onTriggered: backend.exports.exportMotecMany(true) }
        }
        Action { text: i18n.tr("Reference Lap as Delta Best..."); onTriggered: backend.exports.exportDeltaBest("") }
        MenuSeparator {}
        Action { text: i18n.tr("CSV, Displayed Laps..."); onTriggered: backend.exports.exportCsv() }
        Action { text: i18n.tr("CSV, Displayed Laps on Time Base..."); onTriggered: backend.exports.exportTimeCsv() }
        Action {
            text: i18n.tr("CSV, Passage A ↔ B...")
            enabled: chart.hasRange
            onTriggered: backend.exports.exportPassageCsv(chart.markerA, chart.markerB)
        }
        MenuSeparator {}
        Action { text: i18n.tr("Picture (PNG)..."); onTriggered: page.grabPicture(false) }
        Action { text: i18n.tr("Copy Picture"); onTriggered: page.grabPicture(true) }
        Action {
            text: i18n.tr("Picture of Passage A ↔ B...")
            enabled: chart.hasRange
            onTriggered: page.grabPassage()
        }
    }
    // Channels shown on charts & in simple view, chart options: right-aligned under the button it was opened from
    ShowPicker {
        id: showPicker
        objectName: "showPicker"
        y: parent ? parent.height + theme.space1 : 0
        x: parent ? parent.width - width : 0
        height: Math.min(implicitHeight, page.height - theme.em * 6)
        onClosed: chart.forceActiveFocus()  // keys back to charts
        onMathRequested: mathEditor.open()
    }

    // Math channels editor (Show menu), setup differences (lap chip menu)
    MathChannels { id: mathEditor; objectName: "mathEditor"; onClosed: chart.forceActiveFocus() }
    SetupDiff { id: setupDiff; objectName: "setupDiff"; onClosed: chart.forceActiveFocus() }

    // Keyboard & mouse help (? key on charts, help button)
    TpPopup {
        id: helpPopup
        anchors.centerIn: parent
        width: Math.min(page.width - theme.em * 4, theme.em * 52)
        height: Math.min(page.height - theme.em * 4, helpColumns.implicitHeight + theme.padPopup * 2 + theme.space2)
        modal: true
        onClosed: chart.forceActiveFocus()  // keys back to charts (popup gives them to window)
        contentItem: Flickable {
            clip: true
            contentHeight: helpColumns.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            GridLayout {
                id: helpColumns
                width: parent.width
                columns: helpPopup.width < theme.bpCompact ? 1 : 3  // narrow window: columns one under another
                columnSpacing: theme.em * 2
                rowSpacing: theme.space6
                Repeater {
                    model: [
                        [i18n.tr("Charts"), [
                            ["Wheel", i18n.tr("Zoom")], [i18n.tr("Drag"), i18n.tr("Move view")],
                            [i18n.tr("Click"), i18n.tr("Keep position")], [i18n.tr("Double-click"), i18n.tr("Whole lap")],
                            ["+ / −", i18n.tr("Zoom")], ["← →", i18n.tr("One recorded frame")],
                            ["Ctrl+← →", i18n.tr("Move cursor farther")], ["Shift+← →", i18n.tr("Move view")],
                            ["Alt+← →", i18n.tr("Previous / next zoom")], [i18n.tr("Home key") + " / 0", i18n.tr("Whole lap")],
                            ["[ ]", i18n.tr("Previous / next corner")], ["A / B", i18n.tr("Markers A & B at cursor")],
                            [i18n.tr("Esc"), i18n.tr("Clear markers, then kept position")],
                            ["R", i18n.tr("Highlighted lap as reference")], [i18n.tr("Space"), i18n.tr("Play / pause")],
                            ["L", i18n.tr("Loop passage A-B")], [", .", i18n.tr("Playback speed")],
                            [i18n.tr("While playing") + ": ← →", i18n.tr("2 s back / forward")],
                            ["?", i18n.tr("This help")],
                        ]],
                        [i18n.tr("Track Map"), [
                            ["F", i18n.tr("Fit whole circuit")], ["R", i18n.tr("Turn map")], ["1-9", i18n.tr("Line coloring")],
                            ["+ / −", i18n.tr("Zoom")], ["← ↑ → ↓", i18n.tr("Move map")],
                            ["B C S O", i18n.tr("Driving points")], ["L", i18n.tr("Lockups & wheelspin")],
                            ["G", i18n.tr("Off track")], ["X", i18n.tr("Track limits exceeded")],
                            ["Z", i18n.tr("Pedal zones")], ["T", i18n.tr("Cursor trail")], ["M", i18n.tr("Measure distance")],
                        ]],
                        [i18n.tr("Laps"), [
                            [i18n.tr("Click"), i18n.tr("Show or hide lap")], ["Shift+" + i18n.tr("Click"), i18n.tr("Every lap between")],
                            [i18n.tr("Double-click"), i18n.tr("Set as Reference")], [i18n.tr("Right-click"), i18n.tr("Lap or session menu")],
                            ["Ctrl+Z", i18n.tr("Restore deleted laps")], ["/", i18n.tr("Search laps")],
                            [i18n.tr("Delete"), i18n.tr("Move highlighted or checked laps to trash")],
                        ]],
                    ]
                    ColumnLayout {
                        Layout.alignment: Qt.AlignTop
                        Layout.fillWidth: true
                        spacing: theme.space2
                        Text { text: modelData[0]; color: theme.text; font.weight: Font.DemiBold; font.pointSize: theme.fontSubtitle }
                        Repeater {
                            model: modelData[1]
                            RowLayout {
                                spacing: theme.space4
                                Rectangle {
                                    Layout.preferredWidth: Math.max(keyText.implicitWidth + theme.em * 0.8, theme.em * 2.2)
                                    Layout.preferredHeight: keyText.implicitHeight + theme.em * 0.25
                                    radius: theme.radiusSm
                                    color: theme.hover
                                    border.width: 1
                                    border.color: theme.border
                                    Text { id: keyText; anchors.centerIn: parent; text: modelData[0] === "Wheel" ? i18n.tr("Wheel") : modelData[0]; color: theme.text; font.pointSize: theme.fontSmall }
                                }
                                Text { text: modelData[1]; color: theme.dimText; font.pointSize: theme.fontLabel; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            }
                        }
                    }
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Toolbar: track (page title), view, then actions fitted to what is left (texts, then icons only, then "⋯")
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3

            // Track of shown laps (page title), search in list. Click leaves keys to charts (Tab reaches it),
            // closed popup gives them back
            TrackPicker {
                id: trackBox
                objectName: "trackBox"
                trackModel: backend.trackModel  // tracks of telemetry folder (logos follow game pictures), searched there
                tracks: []  // list not read (rows from trackModel)
                currentKey: backend.currentTrack
                // circuit of laps opened without track folder (another circuit, imported log)
                currentLabel: backend.currentTrack || backend.trackLabel || i18n.tr("No recorded lap")
                currentLogo: backend.pictureVersion >= 0 ? backend.trackLogo(backend.currentTrack) : ""
                allTracks: false
                selectTrack: function(key) { backend.currentTrack = key }
                Layout.minimumWidth: theme.em * 9
                Layout.maximumWidth: Math.min(implicitWidth, theme.em * 24)
                Layout.fillWidth: true
                onClosed: chart.forceActiveFocus()  // keys back to charts (popup gives them to window)
            }

            // Simple view (pedals, steering wheel & values at cursor) shown over charts, or advanced view (charts)
            TpSegmented {
                id: viewMode
                objectName: "viewMode"
                name: i18n.tr("View")
                options: [i18n.tr("Simple View"), i18n.tr("Advanced View")]
                currentIndex: backend.simpleView ? 0 : 1
                onActivated: function(index) { backend.setSimpleView(index === 0) }
            }

            TpToolbar {
                id: toolbar
                objectName: "lapToolbar"
                onMenuClosed: chart.forceActiveFocus()  // keys back to charts
                Layout.fillWidth: true
                TpAction {
                    name: "refreshButton"
                    glyph: ""
                    fallback: "⟳"
                    tip: i18n.tr("Refresh")
                    priority: 1
                    onTriggered: backend.refresh()
                }
                // Laps from elsewhere: files & MoTeC logs, imported laps library, folder of a teammate
                TpAction {
                    name: "importButton"
                    text: i18n.tr("Import")
                    glyph: ""  // open file
                    fallback: "+"
                    tip: i18n.tr("Add laps from another folder or track, import a MoTeC log (.ld) or a teammate's folder")
                    priority: 2
                    checked: importMenu.visible
                    onTriggered: function(source) { page.toggleMenu(importMenu, source) }
                }
                TpAction {
                    name: "exportButton"
                    text: i18n.tr("Export")
                    glyph: ""  // export
                    fallback: "⇪"
                    tip: i18n.tr("Export laps to MoTeC i2 log files (.ld), displayed charts to CSV (Excel), or a picture of the page")
                    priority: 2
                    checked: exportMenu.visible
                    onTriggered: function(source) { page.toggleMenu(exportMenu, source) }
                }
                TpAction {
                    name: "helpButton"
                    glyph: ""  // help
                    fallback: "?"
                    flat: true
                    tip: i18n.tr("Keyboard & mouse help") + " (?)"
                    priority: 0
                    checked: helpPopup.visible
                    onTriggered: helpPopup.visible ? helpPopup.close() : helpPopup.open()
                }
                TpAction {
                    name: "liveButton"
                    text: i18n.tr("Live")
                    tip: i18n.tr("New recorded laps listed at once, newest lap compared with best lap")
                    priority: 3
                    checkable: true
                    checked: backend.liveMode
                    onTriggered: backend.setLiveMode(!backend.liveMode)
                }
                TpAction {
                    name: "timeAxisButton"
                    shown: !backend.simpleView  // charts only
                    text: i18n.tr("Time axis")
                    tip: i18n.tr("Charts along lap time instead of lap distance")
                    priority: 3
                    checkable: true
                    checked: backend.timeAxis
                    onTriggered: backend.setTimeAxis(!backend.timeAxis)
                }
                // Channels shown on charts & in simple view, chart options
                TpAction {
                    name: "showButton"
                    text: i18n.tr("Show")
                    glyph: ""  // sliders
                    fallback: "☰"
                    tip: i18n.tr("Choose what is shown")
                    priority: 5
                    pinned: true
                    checked: showPicker.visible
                    onTriggered: function(source) {
                        if (showPicker.visible) { showPicker.close(); return }
                        showPicker.parent = source  // under the button, or under "⋯"
                        showPicker.open()
                    }
                }
            }
        }

        // Laps | charts | map, G circle, corners & range
        Item {
            id: bodyArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            SplitView {
                id: body
                anchors.fill: parent
                orientation: Qt.Horizontal
                handle: Item {
                    implicitWidth: theme.em * 0.6
                    Rectangle {
                        anchors.centerIn: parent
                        width: Math.max(3, Math.round(theme.em * 0.2))
                        height: theme.em * 2.5
                        radius: width / 2
                        color: SplitHandle.pressed ? theme.accent : SplitHandle.hovered ? theme.dimText : theme.border
                        Behavior on color { ColorAnimation { duration: theme.motionFast } }
                    }
                }
                // Saved state (QByteArray) is an ArrayBuffer here: byteLength, not length
                Component.onCompleted: if (backend.layoutState.byteLength > 0) restoreState(backend.layoutState)
                onResizingChanged: if (!resizing) backend.setLayoutState(saveState())

                LapList {
                    objectName: "lapList"
                    chart: chart
                    SplitView.preferredWidth: theme.em * 21
                    SplitView.minimumWidth: theme.em * 14
                }

                Card {
                    SplitView.fillWidth: true
                    SplitView.minimumWidth: theme.em * 30
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: theme.padCard
                        anchors.leftMargin: theme.space1  // channel names column brings its own room
                        spacing: theme.space2
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            // Charts hidden under simple view, lap chips kept (same chips & place in both views), key
                            // focus & cursor kept (playback, map hover, simple view read it)
                            TraceChart {
                                id: chart
                                focus: true  // keys (?, space, arrows, A/B) work as soon as page opens
                                anchors.fill: parent
                                chartsShown: !backend.simpleView
                                onPictureRequested: function(copy) { page.grabPicture(copy) }
                                onRangeSet: backend.setSideTab(3)
                                onHelpRequested: helpPopup.open()
                                onSetupRequested: function(lapKey) { setupDiff.show(lapKey) }
                            }
                            // Simple view in place of charts, under lap chips: created when first shown, then kept (hidden:
                            // nothing read)
                            Item {
                                anchors.fill: parent
                                anchors.leftMargin: theme.space3
                                anchors.topMargin: chart.legendBottom + theme.space3
                                opacity: backend.simpleView && simpleLoader.status === Loader.Ready ? 1 : 0
                                visible: opacity > 0
                                Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                                Loader {
                                    id: simpleLoader
                                    objectName: "simpleView"
                                    readonly property bool shown: backend.simpleView
                                    property bool opened: shown
                                    onShownChanged: if (shown) opened = true
                                    anchors.fill: parent
                                    active: opened
                                    asynchronous: true
                                    sourceComponent: SimpleView { chart: page.traceChart }
                                }
                            }
                            // Simple view built over a few frames: spinner meanwhile
                            TpStateView {
                                anchors.centerIn: parent
                                compact: true
                                loading: backend.simpleView && simpleLoader.status !== Loader.Ready
                            }
                        }
                        // Playback under charts & simple view: same place in both
                        PlaybackBar {
                            objectName: "playbackBar"
                            Layout.fillWidth: true
                            Layout.leftMargin: theme.space3
                            chart: page.traceChart
                        }
                    }
                }

                Card {
                    // Ultrawide screens: map & tools get a share of the width, not a fixed strip beside huge charts
                    SplitView.preferredWidth: Math.max(theme.em * 27, body.width * 0.22)
                    SplitView.minimumWidth: theme.em * 18
                    ColumnLayout {
                        id: sideColumn
                        anchors.fill: parent
                        anchors.margins: theme.padCard
                        spacing: theme.space3
                        // Six tool names fit as tabs (squeezed to caption size at most), else a drop-down list. Set on width
                        // changes, not bound (switching control changes the layout, which would ask it again)
                        property bool tabsFit: true
                        function fitTabs() {
                            tabsFit = sideTabs.textsWidth * 0.75 + sideTabs.options.length * theme.em * 0.5 + theme.space4 <= width
                        }
                        onWidthChanged: fitTabs()
                        Component.onCompleted: fitTabs()
                        TpSegmented {
                            id: sideTabs
                            Layout.alignment: Qt.AlignHCenter
                            visible: sideColumn.tabsFit
                            maxWidth: parent.width
                            name: i18n.tr("Tools")
                            onTextsWidthChanged: sideColumn.fitTabs()
                            options: [i18n.tr("Track Map"), i18n.tr("G Circle"), i18n.tr("Corners"), i18n.tr("Range"), i18n.tr("Session"), i18n.tr("XY")]
                            currentIndex: backend.sideTab
                            onActivated: function(index) { backend.setSideTab(index) }
                        }
                        TpCombo {
                            id: sideCombo
                            objectName: "sideCombo"
                            visible: !sideColumn.tabsFit
                            Layout.fillWidth: true
                            tip: i18n.tr("Tools")
                            model: sideTabs.options
                            currentIndex: backend.sideTab
                            onActivated: function(index) { backend.setSideTab(index) }
                            Connections {  // keys back to charts (closed popup gives them to window)
                                target: sideCombo.popup
                                function onClosed() { chart.forceActiveFocus() }
                            }
                        }
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            // Keys the clicked map leaves (Space plays, A, [ ], arrows when whole map shown) go to
                            // charts, not page: forwarded by this parent (forwardTo on the map would run before its keys)
                            Item {
                                anchors.fill: parent
                                Keys.forwardTo: [chart]
                                TrackMap {
                                    anchors.fill: parent
                                    chart: chart
                                    opacity: sideTabs.currentIndex === 0 && !page.mapFocus ? 1 : 0
                                    visible: opacity > 0
                                    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                                    onExpandToggled: page.mapFocus = true
                                }
                            }
                            // Other tabs created on first show, then kept: showing one again costs nothing,
                            // hidden ones refresh only when shown again
                            Repeater {
                                model: [gCircleTab, cornersTab, rangeTab, sessionTab, xyTab]
                                Loader {
                                    required property var modelData
                                    required property int index
                                    readonly property bool shown: sideTabs.currentIndex === index + 1
                                    property bool opened: shown
                                    onShownChanged: if (shown) opened = true
                                    anchors.fill: parent
                                    opacity: shown && status === Loader.Ready ? 1 : 0
                                    visible: opacity > 0
                                    active: opened
                                    asynchronous: true  // tab built over a few frames: tab click never stalls the window
                                    sourceComponent: modelData
                                    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                                }
                            }
                            Component { id: gCircleTab; GCircle { chart: page.traceChart } }
                            Component { id: cornersTab; CornerList { chart: page.traceChart } }
                            Component { id: rangeTab; RangeStats { chart: page.traceChart } }
                            Component { id: sessionTab; SessionView { chart: page.traceChart } }
                            Component { id: xyTab; XYView { chart: page.traceChart } }
                        }
                    }
                }
            }

            // Focus mode: large track map over laps & charts (charts keep driving cursor & zoom),
            // created only while shown (a second map otherwise keeps all its shapes)
            // Keys to large map (F, R, 1-9, Esc leaves), keys it leaves to charts (Space plays, arrows, A, ?)
            Loader {
                anchors.fill: parent
                active: page.mapFocus
                asynchronous: true  // large map built over a few frames (fades in once ready)
                onLoaded: item.focusMap()
                Keys.forwardTo: [chart]
                sourceComponent: Card {
                    function focusMap() { largeMap.forceActiveFocus() }
                    opacity: 0
                    Component.onCompleted: opacity = 1
                    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
                    TrackMap {
                        id: largeMap
                        anchors.fill: parent
                        anchors.margins: theme.padCard
                        chart: page.traceChart
                        expanded: true
                        onExpandToggled: page.mapFocus = false  // keys back to charts (onMapFocusChanged)
                    }
                }
            }
        }

        // Status: room kept even when empty (charts & map never jump when a message comes or goes)
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.controlHeightSm)
            readonly property bool active: backend.status !== "" || backend.warning !== "" || backend.loading || backend.undoText !== ""
            opacity: active ? 1 : 0
            spacing: theme.space3
            BusyIndicator {
                running: backend.loading && pageState.active
                visible: running
                implicitWidth: theme.em * 1.4
                implicitHeight: implicitWidth
            }
            Text {
                id: statusText
                text: backend.status
                visible: text !== ""
                color: theme.dimText
                textFormat: Text.StyledText
                elide: Text.ElideRight
                Layout.maximumWidth: page.width * 0.5  // page width: never the row itself (rearranged again)
                HoverHandler { id: statusHover }
                ToolTip.visible: statusHover.hovered && statusText.truncated
                ToolTip.text: statusText.text
                ToolTip.delay: theme.tipDelay
            }
            TpButton {
                visible: backend.undoText !== ""
                glyph: ""  // undo
                fallback: "↶"
                text: backend.undoText
                flat: true
                size: "sm"
                tip: i18n.tr("Restore deleted laps from trash (Ctrl+Z)")
                onClicked: backend.undoDelete()
            }
            Icon {  // warning: icon with its color (never color alone)
                visible: backend.warning !== ""
                glyph: ""
                fallback: "!"
                color: theme.warning
            }
            Text {
                id: warningText
                text: backend.warning
                visible: text !== ""
                color: theme.warning
                Layout.fillWidth: true
                elide: Text.ElideRight
                HoverHandler { id: warningHover }
                ToolTip.visible: warningHover.hovered && warningText.truncated
                ToolTip.text: warningText.text
                ToolTip.delay: theme.tipDelay
            }
            Item { Layout.fillWidth: true; visible: backend.warning === "" }
        }
    }

    // Laps moved to trash (named), undo at hand
    TpToast {
        id: toast
        objectName: "lapToast"
        actionText: backend.undoText !== "" ? i18n.tr("Undo") : ""
        onAction: backend.undoDelete()
    }
}
