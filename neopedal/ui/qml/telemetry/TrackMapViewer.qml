import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import NeoPedal
import "../components"

// Track map viewer page: map with position along track, curve section & osculating circle at position,
// curve, slope & position info, elevation profile. Click map or profile: move position, play: drive around.
TpPage {
    id: page

    readonly property var view: backend.view
    readonly property var current: backend.current
    readonly property var overlays: backend.overlays
    readonly property var colors: backend.colors
    readonly property var settings: backend.settings
    readonly property bool loaded: backend.loaded
    property bool follow: false
    property bool playing: false
    property real playSpeed: 60  // meters per second
    // Narrow window: info cards under the map (two per row)
    readonly property bool narrow: width < theme.bpNarrow

    function step(count) { backend.setPosition(Math.max(0, Math.min(backend.position + count * settings.step, backend.length))) }
    function centerOnPosition(animated) {
        if (!loaded || current.x === undefined) return
        var scale = canvas.baseScale * Math.max(canvas.zoom, 4)
        canvas.setView(Math.max(canvas.zoom, 4), (canvas.centerX - current.x) * scale,
                       canvas.ySign * (canvas.centerY - current.y) * scale, animated)
    }
    // Numbers with decimal separator of app language, distances in user unit (m or ft)
    function number(value, decimals) { return value === undefined ? "—" : Number(value).toFixed(decimals).replace(".", theme.decimalPoint) }
    function distance(meters, decimals) { return meters === undefined ? "—" : number(meters * backend.distanceScale, decimals) + " " + backend.distanceUnit }

    onFollowChanged: if (follow) centerOnPosition(true); else canvas.reset(true)
    Connections {
        target: backend
        function onCurrentChanged() { if (page.follow) page.centerOnPosition(false) }
        function onMapChanged() { page.playing = false; canvas.reset(false) }
    }
    Timer {  // play: about 30 steps a second (not every vsync), moved by wall clock time, none while page hidden
        property double lastTick: 0  // Date.now() of last step, 0: first step
        interval: 33
        repeat: true
        running: page.playing && page.loaded && pageState.active
        onRunningChanged: lastTick = running ? Date.now() : 0
        onTriggered: {
            var now = Date.now()
            var elapsed = lastTick > 0 ? (now - lastTick) / 1000 : 0
            lastTick = now
            var next = backend.position + page.playSpeed * Math.min(elapsed, 0.1)
            backend.setPosition(next >= backend.length ? 0 : next)
        }
    }
    focus: true
    // + / - zoom, up & down move map, Shift+left / right move map (left / right alone: position)
    // (no onLeftPressed / onRightPressed: they run first and would take Shift+left / right too)
    Keys.onPressed: function(event) {
        var sideways = event.key === Qt.Key_Left || event.key === Qt.Key_Right
        if (sideways && !(event.modifiers & Qt.ShiftModifier)) {
            step(event.key === Qt.Key_Left ? -1 : 1)
            event.accepted = true
        } else if (canvas.handleKey(event.key)) event.accepted = true
    }
    Keys.onSpacePressed: playing = !playing

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TrackPicker {  // track maps recorded by Mapping module, with search
                id: picker
                busy: backend.tracksLoading
                emptyText: i18n.tr("No track map recorded yet")
                onOpened: backend.refreshTracks()
                onClosed: page.forceActiveFocus()  // left / right keys back to position
                Layout.minimumWidth: theme.em * 9
                Layout.maximumWidth: Math.min(implicitWidth, theme.em * 20)
                Layout.fillWidth: true
            }
            Repeater {
                model: page.loaded && page.overlays.show_map_info
                       ? [page.distance(backend.length, 0), backend.nodes + " " + i18n.tr("nodes")] : []
                Pill {
                    required property var modelData
                    visible: !page.narrow
                    tint: theme.dimText
                    text: modelData
                }
            }
            // Actions fitted to what is left: texts, then icons only, then "⋯" menu
            TpToolbar {
                objectName: "mapToolbar"
                Layout.fillWidth: true
                TpAction {
                    name: "openMapButton"
                    text: i18n.tr("Open File")
                    glyph: theme.glyphs.openFile
                    fallback: "+"
                    tip: i18n.tr("Open a track map from another folder")
                    priority: 2
                    onTriggered: backend.openMap()
                }
                TpAction {
                    name: "followButton"
                    text: i18n.tr("Follow Position")
                    tip: i18n.tr("Map zoomed & centered on position")
                    priority: 3
                    checkable: true
                    checked: page.follow
                    enabled: page.loaded
                    onTriggered: page.follow = !page.follow
                }
                TpAction {
                    name: "overlayButton"
                    text: i18n.tr("Show")
                    glyph: ""  // view
                    fallback: "👁"
                    tip: i18n.tr("Choose what is shown")
                    priority: 5
                    pinned: true
                    checked: overlayMenu.visible
                    onTriggered: function(source) { overlayMenu.toggleBelow(source) }
                }
                TpAction {
                    name: "configButton"
                    text: i18n.tr("Config")
                    glyph: ""  // settings
                    fallback: "⚙"
                    priority: 1
                    onTriggered: backend.openConfig()
                }
            }
            TpMenu {
                id: overlayMenu
                onClosed: page.forceActiveFocus()
                Instantiator {
                    model: backend.overlayMenu
                    delegate: Action {
                        text: modelData.text
                        checkable: true
                        checked: modelData.checked
                        onTriggered: backend.setOverlay(modelData.key, checked)
                    }
                    onObjectAdded: function(index, object) { overlayMenu.insertAction(index, object) }
                    onObjectRemoved: function(index, object) { overlayMenu.removeAction(object) }
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.narrow ? 1 : 2
            columnSpacing: theme.space4
            rowSpacing: theme.space4

            // Map
            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                MapCanvas {
                    id: canvas
                    anchors.fill: parent
                    anchors.margins: 1
                    flipY: false  // track map file: y down
                    maxZoom: 200
                    feet: backend.distanceUnit === "ft"
                    minX: page.view.minX || 0
                    minY: page.view.minY || 0
                    maxX: page.view.maxX || 1
                    maxY: page.view.maxY || 1
                    onSettled: if (page.loaded) backend.setScale(canvas.metersPerPixel)
                    onClicked: function(x, y) {
                        var distance = backend.pick(x, y, theme.em * 1.5 * canvas.metersPerPixel)
                        if (distance >= 0) backend.setPosition(distance)
                    }

                    // Map shapes in a multisampled layer while shown (smooth edges, window without MSAA): position
                    // markers & labels outside
                    Item {
                        objectName: "mapLines"
                        anchors.fill: parent
                        layer.enabled: pageState.active && page.loaded
                        layer.samples: 4
                        // Map shapes: one transform for all of them (one update per zoom or move frame, not one per shape)
                        Item {
                            transform: Matrix4x4 { matrix: canvas.matrix }
                            GpuShape {
                                key: page.view.edge || ""
                                color: theme.tint(theme.text, "selected")
                            }
                            GpuShape {
                                key: page.view.road || ""
                                color: theme.mapRoad
                            }
                            GpuShape {
                                key: page.view.sectors || ""
                                opacity: 0.85
                            }
                            GpuShape {
                                key: page.view.start || ""
                                color: page.colors.start_line_color || "#FF4400"
                            }
                            GpuShape {
                                key: page.view.sectorLines || ""
                                color: page.colors.sector_line_color || "#00AAFF"
                            }

                            // Curve at position
                            GpuShape {
                                key: page.view.circle || ""
                                visible: page.overlays.show_osculating_circle
                                color: page.colors.osculating_circle_color || "#00AAFF"
                                opacity: 0.8
                            }
                            GpuShape {
                                key: page.view.radius || ""
                                visible: page.overlays.show_osculating_circle
                                color: page.colors.osculating_circle_color || "#00AAFF"
                                opacity: 0.6
                            }
                            GpuShape {
                                key: page.view.section || ""
                                visible: page.overlays.show_curve_section
                                color: page.colors.curve_section_color || "#FF4400"
                            }
                        }
                    }

                    // Distance circles around position (meters)
                    Repeater {
                        model: page.loaded && page.overlays.show_distance_circle ? page.settings.circles : []
                        Rectangle {
                            readonly property real size: modelData * 2 * canvas.mapScale
                            x: canvas.screenX(page.current.x || 0) - size / 2
                            y: canvas.screenY(page.current.y || 0) - size / 2
                            width: size
                            height: size
                            radius: size / 2
                            color: "transparent"
                            border.width: 1
                            border.color: page.colors.distance_circle_color || "#808080"
                            opacity: 0.7
                        }
                    }

                    // Center mark: cross along driving direction (pixels)
                    Item {
                        visible: page.loaded && page.overlays.show_center_mark
                        x: canvas.screenX(page.current.x || 0)
                        y: canvas.screenY(page.current.y || 0)
                        rotation: page.current.yaw || 0
                        readonly property real size: page.settings.centerMark || 1000
                        Rectangle { x: -parent.size; y: -0.5; width: parent.size * 2; height: 1; color: page.colors.center_mark_color || "#808080"; opacity: 0.6; antialiasing: true }
                        Rectangle { x: -0.5; y: -parent.size; width: 1; height: parent.size * 2; color: page.colors.center_mark_color || "#808080"; opacity: 0.6; antialiasing: true }
                    }

                    // Official corners: click to move position there
                    Repeater {
                        model: page.loaded ? (page.view.corners || []) : []
                        Rectangle {
                            readonly property real anchorX: canvas.screenX(modelData.x)
                            x: anchorX + 6 + width <= canvas.width ? anchorX + 6 : anchorX - 6 - width  // kept inside map
                            y: canvas.screenY(modelData.y) - height - 4
                            width: cornerText.implicitWidth + theme.em * 0.7
                            height: cornerText.implicitHeight + 4
                            radius: height / 2
                            readonly property bool current: page.current.corner === modelData.label
                            color: current ? theme.accentFill : cornerArea.containsMouse ? theme.hover
                                 : theme.surfaceFlyout
                            border.width: 1
                            border.color: cornerArea.containsMouse ? theme.strokeStrong : theme.tint(theme.text, "selected")
                            Behavior on color { ColorAnimation { duration: theme.motionBase } }
                            Text {
                                id: cornerText
                                anchors.centerIn: parent
                                text: modelData.label
                                textFormat: Text.PlainText
                                color: parent.current ? theme.inkOn(theme.accentFill) : theme.text
                                font.pointSize: theme.fontCaption
                                font.weight: Font.Bold
                            }
                            MouseArea {
                                id: cornerArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: backend.setPosition(modelData.distance)
                            }
                        }
                    }

                    // Position
                    Rectangle {
                        visible: page.loaded && page.overlays.show_highlighted_coordinates
                        readonly property real size: Math.max(theme.em * 0.9, (page.settings.marker || 15) * canvas.mapScale)
                        x: canvas.screenX(page.current.x || 0) - size / 2
                        y: canvas.screenY(page.current.y || 0) - size / 2
                        width: size
                        height: size
                        radius: theme.radiusXs
                        rotation: page.current.yaw || 0
                        color: "transparent"
                        border.width: 3
                        border.color: page.colors.highlighted_coordinates_color || "#22DD00"
                    }

                    // No map yet (what to do), or map file read in background (first map, or other one replacing
                    // map shown): spinner wins, never "load a map" while reading
                    TpStateView {
                        objectName: "mapState"
                        anchors.centerIn: parent
                        loading: backend.loading
                        empty: !page.loaded && !dropArea.containsDrag
                        loadingText: i18n.tr("Reading track map…")
                        glyph: "\uE707"  // map pin
                        title: i18n.tr("Load a track map recorded by the Mapping module.")
                        text: i18n.tr("Or drop a track map file (.svg) here.")
                        actionText: i18n.tr("Choose a track map")
                        onAction: picker.openSearch()
                    }
                }

                // Sector legend
                Row {
                    visible: page.loaded
                    anchors { left: parent.left; top: parent.top; margins: theme.space4 }
                    spacing: theme.space4
                    Repeater {
                        model: page.loaded ? page.view.sectorLengths : []
                        Row {
                            spacing: theme.space2
                            Rectangle { width: theme.em * 0.7; height: theme.em * 0.3; radius: height / 2; color: page.view.sectorColors[index]; anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                text: "S" + (index + 1) + "  " + page.distance(modelData, 0)
                                textFormat: Text.PlainText
                                color: page.current.sector === index + 1 ? theme.text : theme.dimText  // current: text & bold
                                font.pointSize: theme.fontSmall
                                font.weight: page.current.sector === index + 1 ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                }
            }

            // Info at position
            GridLayout {
                Layout.preferredWidth: page.narrow ? -1 : theme.em * 17
                Layout.maximumWidth: page.narrow ? Number.POSITIVE_INFINITY : theme.em * 17
                Layout.fillWidth: page.narrow
                Layout.fillHeight: !page.narrow
                columns: page.narrow ? 2 : 1
                columnSpacing: theme.space4
                rowSpacing: theme.space4
                visible: page.loaded

                InfoCard {
                    visible: page.overlays.show_position_info
                    title: i18n.tr("Position")
                    value: page.distance(page.current.distance, 1)
                    lines: [
                        (page.current.corner ? page.current.corner + " · " : "")
                            + i18n.tr("Node") + " " + (page.current.node || "—") + " · S" + (page.current.sector || "—"),
                        "x " + page.number(page.current.x, 1) + "  y " + page.number(page.current.y, 1)
                            + "  z " + page.number(page.current.z, 1),
                    ]
                }
                InfoCard {
                    visible: page.overlays.show_curve_info
                    title: i18n.tr("Curve")
                    value: page.current.radiusDesc || "—"
                    accentColor: page.current.direction > 0 ? theme.seriesFuel : page.current.direction < 0 ? theme.seriesWear : theme.text  // not purple (best)
                    lines: [
                        i18n.tr("Radius") + " " + page.distance(page.current.radius, 1),
                        i18n.tr("Length") + " " + page.distance(page.current.curveLength, 1) + " (" + (page.current.lengthDesc || "") + ")",
                        i18n.tr("Angle") + " " + page.number(page.current.angle, 1) + "°",
                    ]
                }
                InfoCard {
                    visible: page.overlays.show_slope_info
                    title: i18n.tr("Slope")
                    value: (page.current.slope > 0 ? "+" : "") + page.number(page.current.slope, 2) + " %"
                    accentColor: page.current.slope > 0.5 ? theme.warning : page.current.slope < -0.5 ? theme.gain : theme.text
                    lines: [
                        page.current.slopeDesc || "",
                        i18n.tr("Angle") + " " + page.number(page.current.slopeAngle, 2) + "°",
                        i18n.tr("Delta") + " " + page.distance(page.current.slopeDelta, 2),
                    ]
                }
                Card {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    implicitHeight: nodesColumn.implicitHeight + theme.padCard * 2
                    ColumnLayout {
                        id: nodesColumn
                        anchors.fill: parent
                        anchors.margins: theme.padCard
                        spacing: 0
                        RowLayout {
                            Text { text: i18n.tr("Section nodes"); color: theme.dimText; Layout.fillWidth: true; elide: Text.ElideRight }
                            Text { text: backend.curveNodes; color: theme.text; font.weight: Font.DemiBold; font.features: { "tnum": 1 }; textFormat: Text.PlainText }
                        }
                        TpSlider {  // Tab reaches it (arrows then move it); a click leaves left / right keys to position
                            Layout.fillWidth: true
                            from: 3; to: 80; stepSize: 1
                            value: backend.curveNodes
                            onMoved: backend.setCurveNodes(value)
                            tip: i18n.tr("Map nodes measured from position: more nodes, longer curve section")
                        }
                    }
                }
                Item { Layout.fillHeight: true; visible: !page.narrow }
            }
        }

        // Elevation profile & position
        Card {
            Layout.fillWidth: true
            implicitHeight: bottomColumn.implicitHeight + theme.padCard * 2
            visible: page.loaded
            ColumnLayout {
                id: bottomColumn
                anchors.fill: parent
                anchors.margins: theme.padCard
                spacing: theme.space2

                Item {
                    id: profile
                    visible: page.overlays.show_elevation_profile
                    Layout.fillWidth: true
                    Layout.preferredHeight: theme.em * 5
                    readonly property real minZ: page.view.minZ || 0
                    readonly property real maxZ: Math.max(page.view.maxZ || 1, minZ + 1)
                    readonly property real sx: width / Math.max(backend.length, 1)
                    readonly property real sy: (height - 6) / (maxZ - minZ)
                    clip: true

                    Repeater {  // sector bands
                        model: page.loaded ? page.view.sectorStarts : []
                        Rectangle {
                            x: modelData * profile.sx
                            width: (page.view.sectorLengths[index] || 0) * profile.sx
                            height: profile.height
                            color: page.view.sectorColors[index]
                            opacity: 0.06
                        }
                    }
                    Item {  // multisampled layer while shown (smooth line, window without MSAA), position marker outside
                        width: profile.width
                        height: profile.height
                        layer.enabled: pageState.active && profile.visible && page.loaded
                        layer.samples: 4
                        Item {  // elevation area & line: one transform
                            transform: Matrix4x4 { matrix: Qt.matrix4x4(profile.sx, 0, 0, 0, 0, -profile.sy, 0, profile.height - 3 + profile.minZ * profile.sy, 0, 0, 1, 0, 0, 0, 0, 1) }
                            GpuShape {
                                key: page.view.elevation || ""
                                color: theme.tint(theme.accent, "selected")
                            }
                            GpuShape {
                                key: page.view.elevationLine || ""
                                color: theme.accent
                            }
                        }
                    }
                    TpText { x: theme.space1; y: 2; role: "caption"; text: page.distance(profile.maxZ, 1) }
                    TpText { x: theme.space1; anchors.bottom: parent.bottom; role: "caption"; text: page.distance(profile.minZ, 1) }
                    Rectangle {  // position
                        x: backend.position * profile.sx
                        width: 2
                        height: profile.height
                        color: page.colors.highlighted_coordinates_color || "#22DD00"
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: pressed ? Qt.SizeHorCursor : Qt.PointingHandCursor
                        onPressed: function(mouse) { backend.setPosition(mouse.x / profile.sx) }
                        onPositionChanged: function(mouse) { if (pressed) backend.setPosition(mouse.x / profile.sx) }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.space3
                    TpButton {
                        glyph: page.playing ? "" : ""  // pause, play
                        fallback: page.playing ? "❚❚" : "▶"
                        tip: i18n.tr("Drive around the track") + " (Space)"
                        onClicked: page.playing = !page.playing
                    }
                    TpButton { glyph: ""; fallback: "‹"; tip: i18n.tr("Previous node") + " (←)"; flat: true; onClicked: page.step(-1) }  // chevron left
                    TpSlider {  // a click leaves left / right keys to the page (position), Tab reaches it
                        Layout.fillWidth: true
                        from: 0
                        to: Math.max(backend.length, 1)
                        stepSize: page.settings.step || 5
                        value: backend.position
                        tip: i18n.tr("Position along track")
                        onMoved: backend.setPosition(value)
                    }
                    TpButton { glyph: ""; fallback: "›"; tip: i18n.tr("Next node") + " (→)"; flat: true; onClicked: page.step(1) }  // chevron right
                    Text {
                        text: page.number(backend.position * backend.distanceScale, 0) + " / " + page.distance(backend.length, 0)
                        textFormat: Text.PlainText
                        color: theme.text
                        font.features: { "tnum": 1 }
                        Layout.preferredWidth: theme.em * 7
                        horizontalAlignment: Text.AlignRight
                    }
                }
            }
        }
    }

    // Track map file (.svg) dropped on page: loaded like one opened, other files refused
    TpDropZone {
        id: dropArea
        anchors.fill: parent
        text: i18n.tr("Drop a track map (.svg) to open it")
        accepts: function(urls) { return backend.droppedMap(urls) !== "" }
        onFilesDropped: function(urls) { backend.openDropped(urls) }
    }

    TpDialogHost {}  // dialogs of the backend (map missing or unreadable)
}
