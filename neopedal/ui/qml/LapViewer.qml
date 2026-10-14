import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Lap telemetry viewer page: lap list, channel charts (advanced view) or simple view over them, track map / G circle /
// corners / range statistics
TpPage {
    id: page

    property bool mapFocus: false  // large track map over laps & charts
    property alias traceChart: chart  // for components (map in focus mode): "chart" there is their own property

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

    // Math channels editor (Show menu), setup differences (lap chip menu)
    MathChannels { id: mathEditor; objectName: "mathEditor"; onClosed: chart.forceActiveFocus() }
    SetupDiff { id: setupDiff; objectName: "setupDiff"; onClosed: chart.forceActiveFocus() }

    // Keyboard & mouse help (? key on charts, help button)
    Popup {
        id: helpPopup
        anchors.centerIn: parent
        width: Math.min(page.width - theme.em * 4, theme.em * 52)
        height: Math.min(page.height - theme.em * 4, helpColumns.implicitHeight + theme.em * 3)
        padding: theme.em * 1.2
        modal: true
        dim: true
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }
        background: Rectangle {
            radius: theme.radiusXl
            color: theme.raised
            border.width: 1
            border.color: theme.border
        }
        contentItem: Flickable {
            clip: true
            contentHeight: helpColumns.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            RowLayout {
                id: helpColumns
                width: parent.width
                spacing: theme.em * 2
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
                            ["Ctrl+Z", i18n.tr("Restore deleted laps")],
                        ]],
                    ]
                    ColumnLayout {
                        Layout.alignment: Qt.AlignTop
                        Layout.fillWidth: true
                        spacing: theme.em * 0.3
                        Text { text: modelData[0]; color: theme.text; font.weight: Font.DemiBold; font.pointSize: theme.fontSubtitle }
                        Repeater {
                            model: modelData[1]
                            RowLayout {
                                spacing: theme.em * 0.6
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
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5

            ComboBox {
                id: trackBox
                objectName: "trackBox"
                focusPolicy: Qt.NoFocus  // arrows & Space stay for charts (else ↓ switched track)
                Layout.preferredWidth: theme.em * 20
                implicitHeight: Math.round(theme.em * 2.3)
                model: backend.tracks
                currentIndex: backend.tracks.indexOf(backend.currentTrack)
                onActivated: function(index) { backend.currentTrack = backend.tracks[index] }
                background: Rectangle {
                    radius: theme.radiusLg
                    color: trackBox.hovered ? theme.hover : theme.raised
                    border.width: 1
                    border.color: trackBox.popup.visible ? theme.accent : theme.border
                    Behavior on color { ColorAnimation { duration: theme.motionFast } }
                }
                contentItem: RowLayout {
                    spacing: theme.em * 0.5
                    GameLogo {  // circuit logo of game
                        id: trackLogo
                        source: backend.pictureVersion, backend.trackLogo(backend.currentTrack)
                        boxWidth: theme.em * 2.8
                        boxHeight: theme.em * 1.6
                        Layout.leftMargin: theme.em * 0.6
                    }
                    Icon {
                        visible: !trackLogo.shown; glyph:""; color: theme.accent; Layout.leftMargin: theme.em * 0.6 }  // map pin
                    Text {
                        // circuit of laps opened without track folder (another circuit, imported log)
                        text: trackBox.displayText || backend.trackLabel || i18n.tr("No recorded lap")
                        color: theme.text
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
                indicator: Icon {
                    glyph: ""  // chevron down
                    size: theme.em * 0.75
                    color: theme.dimText
                    x: trackBox.width - width - theme.em * 0.7
                    y: (trackBox.height - height) / 2
                }
                popup: Popup {
                    y: trackBox.height + 4
                    width: trackBox.width
                    padding: 4
                    implicitHeight: Math.min(contentItem.implicitHeight + 8, theme.em * 24)
                    onClosed: chart.forceActiveFocus()  // keys back to charts (popup gives them to window)
                    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast } }
                    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }
                    contentItem: ListView {
                        clip: true
                        implicitHeight: contentHeight
                        model: trackBox.popup.visible ? trackBox.delegateModel : null
                        ScrollBar.vertical: ScrollBar {}
                    }
                    background: Rectangle {
                        radius: theme.radiusLg
                        color: theme.raised
                        border.width: 1
                        border.color: theme.border
                    }
                }
                delegate: ItemDelegate {
                    id: trackItem
                    required property string modelData
                    required property int index
                    width: trackBox.width - 8
                    height: theme.em * 2.2
                    highlighted: trackBox.highlightedIndex === index
                    contentItem: RowLayout {
                        spacing: theme.em * 0.5
                        Item {  // circuit logo of game, same room on every row
                            implicitWidth: theme.em * 2.4
                            implicitHeight: theme.em * 1.3
                            GameLogo {
                                anchors.centerIn: parent
                                source: backend.pictureVersion, backend.trackLogo(trackItem.modelData)
                                boxWidth: theme.em * 2.4
                                boxHeight: theme.em * 1.3
                            }
                        }
                        Text {
                            text: trackItem.modelData
                            color: theme.text
                            font.weight: trackBox.currentIndex === trackItem.index ? Font.DemiBold : Font.Normal
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                    background: Rectangle {
                        radius: theme.radiusMd
                        color: trackItem.highlighted ? theme.hover : "transparent"
                    }
                }
            }
            TpButton { glyph: ""; tip: i18n.tr("Refresh"); onClicked: backend.refresh() }  // refresh
            TpButton { glyph: ""; text: i18n.tr("Add File..."); tip: i18n.tr("Add laps from another folder or track, or import a MoTeC log (.ld)"); onClicked: backend.exports.addFiles() }
            TpButton {
                glyph: ""  // folder
                text: i18n.tr("Imported Laps...")
                tip: i18n.tr("Laps imported from MoTeC logs: add to viewer, rename, delete")
                onClicked: backend.openLibrary()
            }
            TpButton {
                text: i18n.tr("Import Folder...")
                tip: i18n.tr("Import laps of this track & class from another folder (teammate, shared folder): marked as foreign")
                onClicked: backend.exports.importFolder()
            }
            TpButton {
                id: exportButton
                glyph: ""  // export
                text: i18n.tr("Export")
                tip: i18n.tr("Export laps to MoTeC i2 log files (.ld), displayed charts to CSV (Excel), or a picture of the page")
                checked: exportMenu.visible
                onClicked: exportMenu.visible ? exportMenu.close() : exportMenu.popup(exportButton, 0, exportButton.height + 4)
                TpMenu {
                    id: exportMenu
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
            }

            // Simple view (pedals, steering wheel & values at cursor) shown over charts, or advanced view (charts):
            // left of spacer, stays in place when chart buttons hide
            TpSegmented {
                id: viewMode
                objectName: "viewMode"
                Layout.leftMargin: theme.em * 0.5
                options: [i18n.tr("Simple View"), i18n.tr("Advanced View")]
                currentIndex: backend.simpleView ? 0 : 1
                onActivated: function(index) { backend.setSimpleView(index === 0) }
            }

            Item { Layout.fillWidth: true }

            TpButton {
                glyph: "\uE897"  // help
                flat: true
                tip: i18n.tr("Keyboard & mouse help") + " (?)"
                checked: helpPopup.visible
                onClicked: helpPopup.visible ? helpPopup.close() : helpPopup.open()
            }
            TpSwitch {
                text: i18n.tr("Live")
                tip: i18n.tr("New recorded laps listed at once, newest lap compared with best lap")
                checked: backend.liveMode
                onToggled: backend.setLiveMode(checked)
            }
            TpSwitch {
                visible: !backend.simpleView  // charts only
                text: i18n.tr("Time axis")
                tip: i18n.tr("Charts along lap time instead of lap distance")
                checked: backend.timeAxis
                onToggled: backend.setTimeAxis(checked)
            }
            // Channels shown on charts & in simple view, chart options
            TpButton {
                id: showButton
                objectName: "showButton"
                glyph: "\ue9e9"  // sliders
                text: i18n.tr("Show")
                checked: showPicker.visible
                tip: i18n.tr("Choose what is shown")
                onClicked: showPicker.visible ? showPicker.close() : showPicker.open()
                ShowPicker {
                    id: showPicker
                    objectName: "showPicker"
                    y: showButton.height + 6
                    x: showButton.width - width
                    height: Math.min(implicitHeight, page.height - theme.em * 6)
                    onClosed: chart.forceActiveFocus()  // keys back to charts
                    onMathRequested: mathEditor.open()
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
                        width: 3
                        height: theme.em * 2.5
                        radius: 1.5
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
                        anchors.margins: theme.em * 0.6
                        anchors.leftMargin: theme.em * 0.2
                        spacing: theme.em * 0.3
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
                                anchors.leftMargin: theme.em * 0.4
                                anchors.topMargin: chart.legendBottom + theme.em * 0.5
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
                        }
                        // Playback under charts & simple view: same place in both
                        PlaybackBar {
                            objectName: "playbackBar"
                            Layout.fillWidth: true
                            Layout.leftMargin: theme.em * 0.4
                            chart: page.traceChart
                        }
                    }
                }

                Card {
                    SplitView.preferredWidth: theme.em * 27
                    SplitView.minimumWidth: theme.em * 18
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: theme.em * 0.6
                        spacing: theme.em * 0.5
                        TpSegmented {
                            id: sideTabs
                            Layout.alignment: Qt.AlignHCenter
                            maxWidth: parent.width
                            options: [i18n.tr("Track Map"), i18n.tr("G Circle"), i18n.tr("Corners"), i18n.tr("Range"), i18n.tr("Session"), i18n.tr("XY")]
                            currentIndex: backend.sideTab
                            onActivated: function(index) { backend.setSideTab(index) }
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
                        anchors.margins: theme.em * 0.6
                        chart: page.traceChart
                        expanded: true
                        onExpandToggled: page.mapFocus = false  // keys back to charts (onMapFocusChanged)
                    }
                }
            }
        }

        // Status
        RowLayout {
            Layout.fillWidth: true
            visible: backend.status !== "" || backend.warning !== "" || backend.loading || backend.undoText !== ""
            spacing: theme.em * 0.5
            BusyIndicator {
                running: backend.loading && pageState.active
                visible: running
                implicitWidth: theme.em * 1.4
                implicitHeight: implicitWidth
            }
            Text { text: backend.status; color: theme.dimText; textFormat: Text.StyledText }
            TpButton {
                visible: backend.undoText !== ""
                glyph: "\uE7A7"  // undo
                text: backend.undoText
                flat: true
                implicitHeight: theme.em * 1.8
                tip: i18n.tr("Restore deleted laps from trash (Ctrl+Z)")
                onClicked: backend.undoDelete()
            }
            Text { text: backend.warning; color: theme.warning; Layout.fillWidth: true; elide: Text.ElideRight }
        }
    }
}
