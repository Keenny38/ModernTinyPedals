import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import NeoPedal
import "../components"

// Track & pace notes editor page: notes table (distance, note, comment, tags) edited in place, track map with the
// place of every note (map, position, curve & slope as Track Map Viewer). Changes not saved: unsaved changes bar at
// the bottom (TpPendingBar, as on Settings): Apply (Ctrl+S) saves to the open file (a new file asked for new notes),
// Discard reads the file again (Undo); Save As writes another file. Undo & redo: Ctrl+Z, Ctrl+Y (page shortcuts,
// track_notes_editor.py).
TpPage {
    id: page

    readonly property QtObject trackMap: backend.trackMap
    readonly property var view: trackMap.view
    readonly property var current: trackMap.current
    readonly property var overlays: trackMap.overlays
    readonly property var colors: trackMap.colors
    readonly property var settings: trackMap.settings
    readonly property bool mapLoaded: trackMap.loaded
    readonly property var labels: backend.columnLabels
    // Narrow window: map above notes
    readonly property bool narrow: width < theme.bpNarrow
    readonly property real numberWidth: theme.em * 2.6
    readonly property real distanceWidth: theme.em * 7.5
    readonly property real tagsWidth: theme.em * 4

    // Numbers with decimal separator of app language, distances in user unit (m or ft)
    function number(value, decimals) { return value === undefined ? "—" : Number(value).toFixed(decimals).replace(".", theme.decimalPoint) }
    function distance(meters, decimals) { return meters === undefined ? "—" : number(meters * trackMap.distanceScale, decimals) + " " + trackMap.distanceUnit }
    function step(count) { trackMap.setPosition(Math.max(0, Math.min(trackMap.position + count * (settings.step || 5), trackMap.length))) }
    function toggleMenu(menu, source) { menu.toggleBelow(source) }
    // Row menu: clicked row selected first (actions work on selected notes)
    function openRowMenu(key, selected, item, x, y) {
        if (!selected) backend.select(key, 0)
        rowMenu.popup(item, x, y)
    }

    Connections {
        target: page.trackMap
        function onMapChanged() { canvas.reset(false) }
    }

    // File menus
    TpMenu {
        id: newMenu
        Action { text: i18n.tr("New Pace Notes"); onTriggered: backend.newNotes("Pace Notes") }
        Action { text: i18n.tr("New Track Notes"); onTriggered: backend.newNotes("Track Notes") }
    }
    TpMenu {
        id: openMenu
        Action { text: i18n.tr("Open Pace Notes"); onTriggered: backend.openNotes("Pace Notes") }
        Action { text: i18n.tr("Open Track Notes"); onTriggered: backend.openNotes("Track Notes") }
    }
    // Notes menus (toolbar & row menu)
    TpMenu {
        id: positionMenu
        Action { text: i18n.tr("From Map"); enabled: page.mapLoaded && backend.selectedCount === 1; onTriggered: backend.setPositionFromMap() }
        Action { text: i18n.tr("From Telemetry"); enabled: backend.selectedCount === 1; onTriggered: backend.setPositionFromTelemetry() }
    }
    TpMenu {
        id: tagMenu
        Action { text: i18n.tr("Pit"); enabled: backend.selectedCount > 0; onTriggered: backend.addTag("#pit") }
        Action { text: i18n.tr("Clear Tag"); enabled: backend.selectedCount > 0; onTriggered: backend.clearTags() }
    }
    TpMenu {
        id: rowMenu
        onClosed: notesList.forceActiveFocus()
        Action { text: i18n.tr("Highlight on Map"); enabled: page.mapLoaded && backend.currentIndex >= 0; onTriggered: backend.showOnMap() }
        MenuSeparator {}
        TpMenu {
            title: i18n.tr("Add Tag")
            Action { text: i18n.tr("Pit"); onTriggered: backend.addTag("#pit") }
        }
        Action { text: i18n.tr("Clear Tag"); onTriggered: backend.clearTags() }
        MenuSeparator {}
        Action { text: i18n.tr("Set from Map"); enabled: page.mapLoaded && backend.selectedCount === 1; onTriggered: backend.setPositionFromMap() }
        Action { text: i18n.tr("Set from Telemetry"); enabled: backend.selectedCount === 1; onTriggered: backend.setPositionFromTelemetry() }
        MenuSeparator {}
        Action { text: i18n.tr("Insert Row Above"); onTriggered: backend.insertRow(0) }
        Action { text: i18n.tr("Insert Row Below"); onTriggered: backend.insertRow(1) }
        Action { text: i18n.tr("Delete Rows"); onTriggered: backend.deleteSelected() }
    }
    // Map overlays (as Track Map Viewer) & notes places
    TpMenu {
        id: overlayMenu
        onClosed: mapArea.forceActiveFocus()
        Action {
            text: i18n.tr("Marked Coordinates")
            checkable: true
            checked: backend.marksShown
            onTriggered: backend.setMarksShown(checked)
        }
        MenuSeparator {}
        Instantiator {
            model: page.trackMap.overlayMenu
            delegate: Action {
                text: modelData.text
                checkable: true
                checked: modelData.checked
                onTriggered: page.trackMap.setOverlay(modelData.key, checked)
            }
            onObjectAdded: function(index, object) { overlayMenu.insertAction(index + 2, object) }
            onObjectRemoved: function(index, object) { overlayMenu.removeAction(object) }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: theme.padPage
            spacing: theme.space4

            // File: name, then actions fitted to what is left (texts, then icons only, then "⋯")
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                TpTextField {
                    id: nameField
                    objectName: "nameField"
                    readonly property string value: backend.fileName
                    onValueChanged: if (!activeFocus) text = value
                    Component.onCompleted: text = value
                    placeholderText: backend.namePlaceholder
                    tip: i18n.tr("File name: Apply writes this file in the folder of the open file")
                    maximumLength: 120
                    validator: RegularExpressionValidator { regularExpression: /[^\\/:*?"<>|]*/ }  // file name characters
                    onEditingFinished: backend.setFileName(text)
                    onEscaped: text = value
                    Layout.minimumWidth: theme.em * 9
                    Layout.maximumWidth: theme.em * 22
                    Layout.fillWidth: true
                }
                TpToolbar {
                    objectName: "fileToolbar"
                    Layout.fillWidth: true
                    TpAction {
                        name: "newButton"
                        text: i18n.tr("New")
                        glyph: theme.glyphs.add
                        fallback: "+"
                        tip: i18n.tr("New pace or track notes")
                        priority: 4
                        checked: newMenu.visible
                        onTriggered: function(source) { page.toggleMenu(newMenu, source) }
                    }
                    TpAction {
                        name: "openButton"
                        text: i18n.tr("Open")
                        glyph: theme.glyphs.openFile
                        fallback: "…"
                        tip: i18n.tr("Open a pace or track notes file")
                        priority: 4
                        checked: openMenu.visible
                        onTriggered: function(source) { page.toggleMenu(openMenu, source) }
                    }
                    TpAction {
                        name: "saveAsButton"
                        text: i18n.tr("Save As…")
                        tip: i18n.tr("Save to another file or format")
                        priority: 2
                        onTriggered: backend.saveAs()
                    }
                    TpAction {
                        name: "infoButton"
                        text: i18n.tr("Info")
                        glyph: ""  // info
                        fallback: "i"
                        tip: i18n.tr("Metadata Info")
                        priority: 1
                        onTriggered: metaDialog.open()
                    }
                    TpAction {
                        name: "mapButton"
                        text: i18n.tr("Map")
                        glyph: ""  // map
                        fallback: "▦"
                        tip: backend.mapShown ? i18n.tr("Hide Map") : i18n.tr("Show Map")
                        priority: 3
                        checkable: true
                        checked: backend.mapShown
                        onTriggered: backend.toggleMap()
                    }
                    TpAction {
                        name: "undoButton"
                        text: i18n.tr("Undo")
                        glyph: theme.glyphs.undo
                        fallback: "↶"
                        tip: i18n.tr("Undo (Ctrl+Z)")
                        priority: 3
                        enabled: backend.canUndo
                        onTriggered: backend.undo()
                    }
                    TpAction {
                        name: "redoButton"
                        text: i18n.tr("Redo")
                        glyph: ""  // redo
                        fallback: "↷"
                        tip: i18n.tr("Redo (Ctrl+Y)")
                        priority: 2
                        enabled: backend.canRedo
                        onTriggered: backend.redo()
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                columns: page.narrow || !backend.mapShown ? 1 : 2
                columnSpacing: theme.space4
                rowSpacing: theme.space4

                // Track map: map file, notes places, position along track (Set from Map), curve & slope there
                Card {
                    id: mapCard
                    visible: backend.mapShown
                    Layout.fillWidth: page.narrow
                    Layout.fillHeight: true
                    Layout.preferredWidth: page.narrow ? -1 : page.width * 0.42
                    Layout.minimumWidth: page.narrow ? 0 : theme.em * 22
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: theme.padCard
                        spacing: theme.space3

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.space3
                            TrackPicker {  // track maps recorded by Mapping module, with search
                                id: picker
                                tracks: page.trackMap.tracks
                                currentKey: page.trackMap.currentTrack
                                currentLabel: page.trackMap.currentLabel
                                currentLogo: page.trackMap.currentLogo
                                allTracks: false
                                selectTrack: function(key) { page.trackMap.selectTrack(key) }
                                busy: page.trackMap.tracksLoading
                                emptyText: i18n.tr("No track map recorded yet")
                                onOpened: page.trackMap.refreshTracks()
                                Layout.minimumWidth: theme.em * 8
                                Layout.maximumWidth: Math.min(implicitWidth, theme.em * 18)
                                Layout.fillWidth: true
                            }
                            TpToolbar {
                                objectName: "mapToolbar"
                                size: "sm"
                                Layout.fillWidth: true
                                TpAction {
                                    name: "openMapButton"
                                    text: i18n.tr("Open File")
                                    glyph: theme.glyphs.openFile
                                    fallback: "+"
                                    tip: i18n.tr("Open a track map from another folder")
                                    priority: 1
                                    onTriggered: page.trackMap.openMap()
                                }
                                TpAction {
                                    name: "overlayButton"
                                    text: i18n.tr("Show")
                                    glyph: ""  // view
                                    fallback: "👁"
                                    tip: i18n.tr("Choose what is shown")
                                    priority: 3
                                    pinned: true
                                    checked: overlayMenu.visible
                                    onTriggered: function(source) { page.toggleMenu(overlayMenu, source) }
                                }
                                TpAction {
                                    name: "mapConfigButton"
                                    text: i18n.tr("Config")
                                    glyph: ""  // settings
                                    fallback: "⚙"
                                    tip: i18n.tr("Track map colors, widths & grades")
                                    priority: 0
                                    onTriggered: page.trackMap.openConfig()
                                }
                            }
                        }

                        // Map: + / - zoom, arrows move zoomed map, left / right position (map clicked first)
                        FocusScope {
                            id: mapArea
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Keys.onPressed: function(event) {
                                var sideways = event.key === Qt.Key_Left || event.key === Qt.Key_Right
                                if (sideways && !(event.modifiers & Qt.ShiftModifier)) {
                                    page.step(event.key === Qt.Key_Left ? -1 : 1)
                                    event.accepted = true
                                } else if (canvas.handleKey(event.key)) event.accepted = true
                            }
                            Rectangle {
                                anchors.fill: parent
                                radius: theme.radiusMd
                                color: theme.plotBase
                                border.width: mapArea.activeFocus ? 2 : 1
                                border.color: mapArea.activeFocus ? theme.accent : theme.plotBorder
                            }
                            MapCanvas {
                                id: canvas
                                objectName: "notesMap"
                                anchors.fill: parent
                                anchors.margins: 1
                                flipY: false  // track map file: y down
                                maxZoom: 200
                                feet: page.trackMap.distanceUnit === "ft"
                                minX: page.view.minX || 0
                                minY: page.view.minY || 0
                                maxX: page.view.maxX || 1
                                maxY: page.view.maxY || 1
                                onSettled: if (page.mapLoaded) page.trackMap.setScale(canvas.metersPerPixel)
                                onClicked: function(x, y) {
                                    mapArea.forceActiveFocus()
                                    var distance = page.trackMap.pick(x, y, theme.em * 1.5 * canvas.metersPerPixel)
                                    if (distance >= 0) page.trackMap.setPosition(distance)
                                }

                                // Map shapes in a multisampled layer while shown (smooth edges, window without MSAA)
                                Item {
                                    anchors.fill: parent
                                    layer.enabled: pageState.active && page.mapLoaded
                                    layer.samples: 4
                                    Item {
                                        transform: Matrix4x4 { matrix: canvas.matrix }
                                        GpuShape { key: page.view.edge || ""; color: theme.tint(theme.text, "strong") }
                                        GpuShape {
                                            key: page.view.road || ""
                                            color: theme.mapRoad
                                        }
                                        GpuShape { key: page.view.sectors || ""; opacity: 0.85 }
                                        GpuShape { key: page.view.start || ""; color: page.colors.start_line_color || theme.loss }
                                        GpuShape { key: page.view.sectorLines || ""; color: page.colors.sector_line_color || theme.accent }
                                        GpuShape {
                                            key: page.view.circle || ""
                                            visible: page.overlays.show_osculating_circle
                                            color: page.colors.osculating_circle_color || theme.accent
                                            opacity: 0.8
                                        }
                                        GpuShape {
                                            key: page.view.radius || ""
                                            visible: page.overlays.show_osculating_circle
                                            color: page.colors.osculating_circle_color || theme.accent
                                            opacity: 0.6
                                        }
                                        GpuShape {
                                            key: page.view.section || ""
                                            visible: page.overlays.show_curve_section
                                            color: page.colors.curve_section_color || theme.loss
                                        }
                                    }
                                }

                                // Distance circles around position (meters)
                                Repeater {
                                    model: page.mapLoaded && page.overlays.show_distance_circle ? page.settings.circles : []
                                    Rectangle {
                                        readonly property real size: modelData * 2 * canvas.mapScale
                                        x: canvas.screenX(page.current.x || 0) - size / 2
                                        y: canvas.screenY(page.current.y || 0) - size / 2
                                        width: size
                                        height: size
                                        radius: size / 2
                                        color: "transparent"
                                        border.width: 1
                                        border.color: page.colors.distance_circle_color || theme.dimText
                                        opacity: 0.7
                                    }
                                }

                                // Center mark: cross along driving direction (pixels)
                                Item {
                                    visible: page.mapLoaded && page.overlays.show_center_mark
                                    x: canvas.screenX(page.current.x || 0)
                                    y: canvas.screenY(page.current.y || 0)
                                    rotation: page.current.yaw || 0
                                    readonly property real size: page.settings.centerMark || 1000
                                    Rectangle { x: -parent.size; y: -0.5; width: parent.size * 2; height: 1; color: page.colors.center_mark_color || theme.dimText; opacity: 0.6; antialiasing: true }
                                    Rectangle { x: -0.5; y: -parent.size; width: 1; height: parent.size * 2; color: page.colors.center_mark_color || theme.dimText; opacity: 0.6; antialiasing: true }
                                }

                                // Notes: click selects the note (current one ringed)
                                Repeater {
                                    model: page.mapLoaded ? backend.marks : []
                                    Rectangle {
                                        readonly property real size: Math.round(modelData.current ? theme.em * 0.95 : theme.em * 0.7)
                                        x: canvas.screenX(modelData.x) - size / 2
                                        y: canvas.screenY(modelData.y) - size / 2
                                        width: size
                                        height: size
                                        radius: size / 2
                                        color: backend.marksColor || theme.dimText
                                        border.width: modelData.current ? 2 : 1
                                        border.color: modelData.current ? theme.accent : theme.window
                                        TpToolTip {
                                            visible: markArea.containsMouse && modelData.text !== ""
                                            text: modelData.text
                                        }
                                        MouseArea {
                                            id: markArea
                                            anchors.fill: parent
                                            anchors.margins: -theme.space1
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                backend.select(modelData.key, 0)
                                                notesList.positionViewAtIndex(backend.currentIndex, ListView.Contain)
                                            }
                                        }
                                    }
                                }

                                // Position
                                Rectangle {
                                    visible: page.mapLoaded && page.overlays.show_highlighted_coordinates
                                    readonly property real size: Math.max(theme.em * 0.9, (page.settings.marker || 15) * canvas.mapScale)
                                    x: canvas.screenX(page.current.x || 0) - size / 2
                                    y: canvas.screenY(page.current.y || 0) - size / 2
                                    width: size
                                    height: size
                                    radius: theme.radiusXs
                                    rotation: page.current.yaw || 0
                                    color: "transparent"
                                    border.width: 3
                                    border.color: page.colors.highlighted_coordinates_color || theme.gain
                                }

                                TpStateView {
                                    objectName: "emptyMap"
                                    anchors.centerIn: parent
                                    compact: true
                                    loading: page.trackMap.loading
                                    empty: !page.mapLoaded
                                    loadingText: i18n.tr("Reading track map…")
                                    glyph: ""  // map pin
                                    title: i18n.tr("Load a track map recorded by the Mapping module.")
                                    actionText: i18n.tr("Choose a track map")
                                    onAction: picker.openSearch()
                                }
                            }
                        }

                        // Position along track: Set from Map uses it
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.space2
                            enabled: page.mapLoaded
                            TpButton { glyph: ""; fallback: "‹"; tip: i18n.tr("Previous node") + " (←)"; flat: true; size: "sm"; onClicked: page.step(-1) }
                            TpSlider {
                                Layout.fillWidth: true
                                from: 0
                                to: Math.max(page.trackMap.length, 1)
                                stepSize: page.settings.step || 5
                                value: page.trackMap.position
                                tip: i18n.tr("Position along track")
                                onMoved: page.trackMap.setPosition(value)
                            }
                            TpButton { glyph: ""; fallback: "›"; tip: i18n.tr("Next node") + " (→)"; flat: true; size: "sm"; onClicked: page.step(1) }
                            Text {
                                text: page.distance(page.trackMap.position, 1)
                                textFormat: Text.PlainText
                                color: theme.text
                                font.features: { "tnum": 1 }
                            }
                        }
                        // Curve section nodes, position / curve / slope info (Show menu)
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.space3
                            visible: page.mapLoaded
                            Text { text: i18n.tr("Section nodes"); color: theme.dimText; textFormat: Text.PlainText }
                            TpSlider {
                                Layout.fillWidth: true
                                from: 3; to: 80; stepSize: 1
                                value: page.trackMap.curveNodes
                                onMoved: page.trackMap.setCurveNodes(value)
                                tip: i18n.tr("Map nodes measured from position: more nodes, longer curve section")
                            }
                            Text { text: page.trackMap.curveNodes; color: theme.text; font.features: { "tnum": 1 }; textFormat: Text.PlainText }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: page.mapLoaded && (page.overlays.show_position_info || page.overlays.show_curve_info
                                                        || page.overlays.show_slope_info || page.overlays.show_map_info)
                            textFormat: Text.PlainText
                            color: theme.dimText
                            font.pointSize: theme.fontCaption
                            font.features: { "tnum": 1 }
                            wrapMode: Text.WordWrap
                            text: {
                                var lines = []
                                var at = page.current
                                if (page.overlays.show_position_info)
                                    lines.push(i18n.tr("Position") + " " + page.distance(at.distance, 1) + " · " + i18n.tr("Node") + " "
                                               + (at.node || "—") + " · S" + (at.sector || "—") + (at.corner ? " · " + at.corner : ""))
                                if (page.overlays.show_curve_info)
                                    lines.push(i18n.tr("Curve") + " " + (at.radiusDesc || "—") + " · " + i18n.tr("Radius") + " "
                                               + page.distance(at.radius, 1) + " · " + i18n.tr("Length") + " " + page.distance(at.curveLength, 1)
                                               + " (" + (at.lengthDesc || "") + ") · " + i18n.tr("Angle") + " " + page.number(at.angle, 1) + "°")
                                if (page.overlays.show_slope_info)
                                    lines.push(i18n.tr("Slope") + " " + (at.slope > 0 ? "+" : "") + page.number(at.slope, 2) + " % ("
                                               + (at.slopeDesc || "") + ") · " + i18n.tr("Angle") + " " + page.number(at.slopeAngle, 2) + "°")
                                if (page.overlays.show_map_info)
                                    lines.push(page.distance(page.trackMap.length, 0) + " · " + page.trackMap.nodes + " " + i18n.tr("nodes"))
                                return lines.join("\n")
                            }
                        }
                    }
                }

                // Notes
                Card {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: theme.em * 30
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: theme.padCard
                        spacing: theme.space3

                        TpToolbar {
                            objectName: "notesToolbar"
                            size: "sm"
                            alignRight: false
                            Layout.fillWidth: true
                            TpAction {
                                name: "addButton"
                                text: i18n.tr("Add")
                                glyph: theme.glyphs.add
                                fallback: "+"
                                tip: i18n.tr("New note at the end")
                                priority: 6
                                onTriggered: backend.addRow()
                            }
                            TpAction {
                                name: "insertButton"
                                text: i18n.tr("Insert")
                                tip: i18n.tr("New note above the current one")
                                priority: 4
                                onTriggered: backend.insertRow(0)
                            }
                            TpAction {
                                name: "positionButton"
                                text: i18n.tr("Set Pos")
                                glyph: ""  // map pin
                                fallback: "⌖"
                                tip: i18n.tr("Distance of the selected note: map position or car position in game")
                                priority: 5
                                enabled: backend.selectedCount === 1
                                checked: positionMenu.visible
                                onTriggered: function(source) { page.toggleMenu(positionMenu, source) }
                            }
                            TpAction {
                                name: "deleteButton"
                                text: i18n.tr("Delete")
                                tip: i18n.tr("Delete selected notes (Undo puts them back)")
                                priority: 5
                                enabled: backend.selectedCount > 0
                                onTriggered: backend.deleteSelected()
                            }
                            TpAction {
                                name: "tagButton"
                                text: i18n.tr("Tags")
                                tip: i18n.tr("Pit lane tag of selected notes")
                                priority: 2
                                enabled: backend.selectedCount > 0
                                checked: tagMenu.visible
                                onTriggered: function(source) { page.toggleMenu(tagMenu, source) }
                            }
                            TpAction {
                                name: "sortButton"
                                text: i18n.tr("Sort")
                                glyph: ""  // sort
                                fallback: "↕"
                                tip: i18n.tr("Notes by increasing distance")
                                priority: 1
                                onTriggered: backend.sortRows()
                            }
                            TpAction {
                                name: "replaceButton"
                                text: i18n.tr("Replace")
                                tip: i18n.tr("Batch Replace")
                                priority: 0
                                enabled: backend.rowCount > 0
                                onTriggered: replaceDialog.open()
                            }
                            TpAction {
                                name: "offsetButton"
                                text: i18n.tr("Offset")
                                tip: i18n.tr("Move or scale distances of selected notes")
                                priority: 0
                                enabled: backend.selectedCount > 0
                                onTriggered: offsetDialog.open()
                            }
                        }

                        // Column headers: distance sorts the notes
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.space2
                            TpHeaderCell { text: "#"; Layout.preferredWidth: page.numberWidth; align: Qt.AlignRight }
                            TpHeaderCell {
                                text: (page.labels[0] || "") + " (m)"
                                Layout.preferredWidth: page.distanceWidth
                                align: Qt.AlignRight
                                sortable: true
                                tip: i18n.tr("Notes by increasing distance")
                                onSortRequested: backend.sortRows()
                            }
                            TpHeaderCell { text: page.labels[1] || ""; Layout.fillWidth: true }
                            TpHeaderCell { text: page.labels[2] || ""; Layout.fillWidth: true }
                            TpHeaderCell { text: page.labels[3] || ""; Layout.preferredWidth: page.tagsWidth }
                        }

                        ListView {
                            id: notesList
                            objectName: "notesList"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: backend.notes
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar {}
                            Accessible.role: Accessible.Table
                            Accessible.name: i18n.tr("Notes")
                            Keys.onDeletePressed: backend.deleteSelected()
                            Keys.onPressed: function(event) {
                                if (event.key === Qt.Key_A && (event.modifiers & Qt.ControlModifier)) {
                                    backend.selectAll()
                                    event.accepted = true
                                }
                            }
                            // Esc leaves the selection, never closes the page
                            Keys.onEscapePressed: function(event) { backend.clearSelection(); event.accepted = true }

                            delegate: Rectangle {
                                id: rowItem
                                required property int index
                                required property var model
                                width: ListView.view.width
                                height: Math.round(theme.fieldHeight) + theme.space2
                                radius: theme.radiusSm
                                color: theme.rowColor(rowHover.hovered, rowItem.model.selected)
                                HoverHandler { id: rowHover }
                                // Right-click beside the fields: row menu
                                TapHandler {
                                    acceptedButtons: Qt.RightButton
                                    onTapped: function(point) {
                                        page.openRowMenu(rowItem.model.key, rowItem.model.selected, rowItem,
                                                         point.position.x, point.position.y)
                                    }
                                }
                                // Current note: accent bar (not color alone: selected rows are tinted too)
                                Rectangle {
                                    visible: rowItem.model.current
                                    width: theme.space1
                                    height: parent.height - theme.space2
                                    anchors.verticalCenter: parent.verticalCenter
                                    radius: width / 2
                                    color: theme.accent
                                }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: theme.space1
                                    spacing: theme.space2
                                    // Row number: click selects (Ctrl: adds, Shift: range), right-click: menu
                                    Text {
                                        Layout.preferredWidth: page.numberWidth
                                        Layout.fillHeight: true
                                        horizontalAlignment: Text.AlignRight
                                        verticalAlignment: Text.AlignVCenter
                                        text: (rowItem.model.selected ? "● " : "") + (rowItem.index + 1)
                                        textFormat: Text.PlainText
                                        color: rowItem.model.selected ? theme.accent : theme.dimText
                                        font.features: { "tnum": 1 }
                                        MouseArea {
                                            anchors.fill: parent
                                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: function(mouse) {
                                                notesList.forceActiveFocus()
                                                if (mouse.button === Qt.RightButton)
                                                    page.openRowMenu(rowItem.model.key, rowItem.model.selected, rowItem, mouse.x, mouse.y)
                                                else
                                                    backend.select(rowItem.model.key, mouse.modifiers)
                                            }
                                        }
                                    }
                                    NumberField {
                                        Layout.preferredWidth: page.distanceWidth
                                        value: rowItem.model.distance
                                        decimals: 2
                                        step: 1
                                        minimum: -99999
                                        maximum: 99999
                                        tip: page.labels[0] || ""
                                        onEdited: function(number) { backend.setValue(rowItem.model.key, "distance", String(number)) }
                                        onActiveFocusChanged: if (activeFocus) backend.focusRow(rowItem.model.key)
                                    }
                                    Repeater {
                                        model: ["note", "comment"]
                                        TpTextField {
                                            required property string modelData
                                            required property int index
                                            readonly property string value: rowItem.model[modelData] || ""
                                            onValueChanged: if (!activeFocus) text = value
                                            Component.onCompleted: text = value
                                            Layout.fillWidth: true
                                            implicitWidth: theme.em * 6
                                            tip: page.labels[index + 1] || ""
                                            onEditingFinished: backend.setValue(rowItem.model.key, modelData, text)
                                            onEscaped: text = value
                                            onActiveFocusChanged: if (activeFocus) backend.focusRow(rowItem.model.key)
                                        }
                                    }
                                    Item {
                                        Layout.preferredWidth: page.tagsWidth
                                        Layout.fillHeight: true
                                        Pill {
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: rowItem.model.tags !== ""
                                            size: "sm"
                                            tint: rowItem.model.pit ? theme.warning : theme.dimText
                                            text: rowItem.model.tags || ""
                                            maximumTextWidth: page.tagsWidth - theme.em
                                        }
                                    }
                                }
                            }

                            TpStateView {
                                anchors.centerIn: parent
                                empty: notesList.count === 0
                                glyph: ""  // list
                                title: i18n.tr("No notes")
                                text: i18n.tr("Add a note, then set its place from the map or from the car in game.")
                                actionText: i18n.tr("Add")
                                onAction: backend.addRow()
                            }
                        }
                    }
                }
            }

            // Status: notes type & open file, warning when another editor changed it
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.round(theme.controlHeightSm)
                spacing: theme.space3
                Text {
                    text: backend.statusText
                    textFormat: Text.PlainText
                    color: theme.dimText
                    elide: Text.ElideMiddle
                    Layout.fillWidth: !backend.diskChangedWarning
                    Layout.maximumWidth: page.width * 0.5
                }
                Icon {  // warning: icon with its color (never color alone)
                    visible: backend.diskChangedWarning
                    glyph: ""
                    fallback: "!"
                    color: theme.warning
                }
                Text {
                    objectName: "diskWarning"
                    visible: backend.diskChangedWarning
                    text: i18n.tr("Changed by another editor since read: saving asks before replacing it")
                    textFormat: Text.PlainText
                    color: theme.warning
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }

        // Unsaved changes: Apply saves to the open file (Ctrl+S), Discard reads it again (Undo kept a few seconds)
        TpPendingBar {
            objectName: "pendingBar"
            pending: backend.modified
            historyButtons: false  // Undo & Redo in the notes toolbar
            canUndo: backend.canUndo
            canRedo: backend.canRedo
            applyTip: backend.filePath !== "" ? i18n.tr("Save to the open file (Ctrl+S)") : i18n.tr("Save to a new file (Ctrl+S)")
            onUndoRequested: backend.undo()
            onDiscardRequested: backend.discard()
            onApplyRequested: backend.save()
        }
    }

    // Metadata of notes file
    TpDialog {
        id: metaDialog
        objectName: "metaDialog"
        title: i18n.tr("Metadata Info")
        acceptText: i18n.tr("Apply")
        dismissOnOutside: false  // typed text kept: only Esc or Cancel close it
        width: Math.min(parent ? parent.width - theme.em * 2 : theme.em * 34, theme.em * 34)
        onAboutToShow: {
            for (var i = 0; i < metaFields.count; i++) metaFields.itemAt(i).reset()
        }
        onAccepted: {
            var values = {}
            for (var i = 0; i < metaFields.count; i++) values[metaFields.itemAt(i).key] = metaFields.itemAt(i).value
            backend.setMetadata(values)
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: theme.space3
            rowSpacing: theme.space2
            Repeater {
                id: metaFields
                model: backend.metadataFields
                // Label & field of one metadata value (two grid cells)
                Item {
                    readonly property string key: modelData.key
                    readonly property string value: metaField.text
                    function reset() { metaField.text = modelData.value }
                    Layout.columnSpan: 2
                    Layout.fillWidth: true
                    implicitHeight: metaField.implicitHeight
                    RowLayout {
                        anchors.fill: parent
                        spacing: theme.space3
                        Text { text: modelData.label; color: theme.text; textFormat: Text.PlainText; Layout.preferredWidth: theme.em * 7 }
                        TpTextField {
                            id: metaField
                            Layout.fillWidth: true
                            onAccepted: metaDialog.accept()
                            onEscaped: metaDialog.close()
                        }
                    }
                }
            }
        }
    }

    // Batch replace in a text column (one undo step)
    TpDialog {
        id: replaceDialog
        objectName: "replaceDialog"
        property var values: []  // texts of column (Find suggestions)
        property string result: ""
        readonly property string column: columnBox.currentIndex >= 0 && backend.textColumns[columnBox.currentIndex]
                                         ? backend.textColumns[columnBox.currentIndex].key : "note"
        title: i18n.tr("Batch Replace")
        acceptText: i18n.tr("Replace")
        cancelText: i18n.tr("Close")
        closeOnAccept: false
        acceptEnabled: findField.text !== ""
        dismissOnOutside: false
        onAboutToShow: { result = ""; values = backend.columnValues(column) }
        onColumnChanged: values = backend.columnValues(column)
        onAccepted: {
            var count = backend.replaceText(column, findField.text, replaceField.text, caseSwitch.checked, wordSwitch.checked)
            result = i18n.tr("Notes changed: %1").arg(count)
            values = backend.columnValues(column)
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: theme.space3
            rowSpacing: theme.space2
            Text { text: i18n.tr("Column:"); color: theme.text; textFormat: Text.PlainText }
            TpCombo {
                id: columnBox
                Layout.fillWidth: true
                model: backend.textColumns
                textRole: "label"
                tip: i18n.tr("Column:")
            }
            Text { text: i18n.tr("Find:"); color: theme.text; textFormat: Text.PlainText }
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space1
                TpTextField {
                    id: findField
                    objectName: "findField"
                    Layout.fillWidth: true
                    onAccepted: replaceDialog.accept()
                    onEscaped: replaceDialog.close()
                }
                TpButton {
                    id: valuesButton
                    glyph: ""  // chevron down
                    fallback: "▾"
                    tip: i18n.tr("Texts of this column")
                    flat: true
                    size: "sm"
                    enabled: replaceDialog.values.length > 0
                    onClicked: valuesMenu.toggleBelow(valuesButton)
                }
            }
            Text { text: i18n.tr("Replace:"); color: theme.text; textFormat: Text.PlainText }
            TpTextField {
                id: replaceField
                Layout.fillWidth: true
                onAccepted: replaceDialog.accept()
                onEscaped: replaceDialog.close()
            }
            Item { implicitWidth: 1 }
            TpSwitch { id: wordSwitch; text: i18n.tr("Match Whole Word") }
            Item { implicitWidth: 1 }
            TpSwitch { id: caseSwitch; text: i18n.tr("Match Case") }
        }
        Text {
            Layout.fillWidth: true
            visible: replaceDialog.result !== ""
            text: replaceDialog.result
            textFormat: Text.PlainText
            color: theme.dimText
        }
        TpMenu {
            id: valuesMenu
            Instantiator {
                model: replaceDialog.values
                delegate: Action { text: modelData; onTriggered: findField.text = modelData }
                onObjectAdded: function(index, object) { valuesMenu.insertAction(index, object) }
                onObjectRemoved: function(index, object) { valuesMenu.removeAction(object) }
            }
        }
    }

    // Offset (or scale) of selected notes distances, applied as often as wanted
    TpDialog {
        id: offsetDialog
        objectName: "offsetDialog"
        property real amount: 0
        property string last: "0"
        title: i18n.tr("Batch Offset")
        acceptText: i18n.tr("Apply")
        cancelText: i18n.tr("Close")
        closeOnAccept: false
        acceptEnabled: amount !== 0 && backend.selectedCount > 0
        dismissOnOutside: false
        onAboutToShow: { amount = 0; last = "0" }
        onAccepted: {
            backend.applyOffset(amount, scaleSwitch.checked)
            last = offsetField.format(amount)
            amount = 0
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: scaleSwitch.checked ? i18n.tr("Last Scale:") : i18n.tr("Last Offset:")
                color: theme.dimText
                textFormat: Text.PlainText
                Layout.fillWidth: true
            }
            Text { text: offsetDialog.last; color: theme.text; textFormat: Text.PlainText; font.features: { "tnum": 1 } }
        }
        NumberField {
            id: offsetField
            Layout.fillWidth: true
            value: offsetDialog.amount
            decimals: scaleSwitch.checked ? 6 : 2
            step: scaleSwitch.checked ? 0.01 : 0.1
            minimum: scaleSwitch.checked ? 0 : -99999
            maximum: scaleSwitch.checked ? 100 : 99999
            showRange: true
            onEdited: function(number) { offsetDialog.amount = number }
            onAccepted: { commit(); offsetDialog.accept() }  // typed value applied first
        }
        TpSwitch {
            id: scaleSwitch
            text: i18n.tr("Scale Mode")
            onToggled: { offsetDialog.amount = 0; offsetDialog.last = "0" }
        }
    }

    // Dialogs & toasts of the backend (messages with Undo: backend.toast, replace & error dialogs)
    TpDialogHost {}
}
