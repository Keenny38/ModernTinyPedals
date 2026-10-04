import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import TinyPedal

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

    function step(count) { backend.setPosition(Math.max(0, Math.min(backend.position + count * settings.step, backend.length))) }
    function centerOnPosition(animated) {
        if (!loaded || current.x === undefined) return
        var scale = canvas.baseScale * Math.max(canvas.zoom, 4)
        canvas.setView(Math.max(canvas.zoom, 4), (canvas.centerX - current.x) * scale,
                       canvas.ySign * (canvas.centerY - current.y) * scale, animated)
    }
    function number(value, decimals) { return value === undefined ? "—" : Number(value).toFixed(decimals) }

    onFollowChanged: if (follow) centerOnPosition(true); else canvas.reset(true)
    Connections {
        target: backend
        function onPositionChanged() { if (page.follow) page.centerOnPosition(false) }
        function onMapChanged() { page.playing = false; canvas.reset(false) }
    }
    Timer {
        interval: 16
        repeat: true
        running: page.playing && page.loaded
        property double last: 0
        onRunningChanged: last = Date.now()
        onTriggered: {
            var now = Date.now()
            var next = backend.position + page.playSpeed * (now - last) / 1000
            last = now
            backend.setPosition(next >= backend.length ? 0 : next)
        }
    }
    focus: true
    Keys.onLeftPressed: step(-1)
    Keys.onRightPressed: step(1)
    Keys.onSpacePressed: playing = !playing

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TpButton { glyph: ""; text: i18n.tr("Load Map"); accent: !page.loaded; onClicked: backend.openMap() }  // open file
            Rectangle {
                visible: page.loaded
                implicitHeight: Math.round(theme.em * 2.3)
                implicitWidth: nameRow.implicitWidth + theme.em * 1.4
                radius: theme.em * 0.55
                color: theme.raised
                border.width: 1
                border.color: theme.border
                Row {
                    id: nameRow
                    anchors.centerIn: parent
                    spacing: theme.em * 0.5
                    Icon { glyph: ""; color: theme.accent; anchors.verticalCenter: parent.verticalCenter }  // map pin
                    Text { text: backend.mapName; color: theme.text; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                }
            }
            Repeater {
                model: page.loaded && page.overlays.show_map_info
                       ? [backend.length.toFixed(0) + " m", backend.nodes + " " + i18n.tr("nodes")] : []
                Rectangle {
                    implicitHeight: theme.em * 1.8
                    implicitWidth: chipText.implicitWidth + theme.em * 1.1
                    radius: height / 2
                    color: theme.hover
                    Text { id: chipText; anchors.centerIn: parent; text: modelData; color: theme.dimText; font.features: { "tnum": 1 } }
                }
            }
            Item { Layout.fillWidth: true }
            TpSwitch {
                text: i18n.tr("Follow position")
                tip: i18n.tr("Map zoomed & centered on position")
                checked: page.follow
                enabled: page.loaded
                onToggled: page.follow = checked
            }
            TpButton {
                id: overlayButton
                glyph: ""  // view
                text: i18n.tr("Show")
                checked: overlayMenu.visible
                onClicked: overlayMenu.visible ? overlayMenu.close() : overlayMenu.popup(overlayButton, 0, overlayButton.height + 4)
                TpMenu {
                    id: overlayMenu
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
            TpButton { glyph: ""; text: i18n.tr("Config"); onClicked: backend.openConfig() }  // settings
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: theme.em * 0.6

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
                    minX: page.view.minX || 0
                    minY: page.view.minY || 0
                    maxX: page.view.maxX || 1
                    maxY: page.view.maxY || 1
                    onSettled: if (page.loaded) backend.setScale(canvas.metersPerPixel)
                    onClicked: function(x, y) {
                        var distance = backend.pick(x, y, theme.em * 1.5 * canvas.metersPerPixel)
                        if (distance >= 0) backend.setPosition(distance)
                    }

                    GpuShape {
                        key: page.view.edge || ""
                        color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.18 : 0.25)
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                    GpuShape {
                        key: page.view.road || ""
                        color: theme.dark ? Qt.lighter(theme.base, 1.5) : Qt.darker(theme.base, 1.08)
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                    GpuShape {
                        key: page.view.sectors || ""
                        opacity: 0.85
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                    GpuShape {
                        key: page.view.start || ""
                        color: page.colors.start_line_color || "#FF4400"
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                    GpuShape {
                        key: page.view.sectorLines || ""
                        color: page.colors.sector_line_color || "#00AAFF"
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }

                    // Curve at position
                    GpuShape {
                        key: page.view.circle || ""
                        visible: page.overlays.show_osculating_circle
                        color: page.colors.osculating_circle_color || "#00AAFF"
                        opacity: 0.8
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                    GpuShape {
                        key: page.view.radius || ""
                        visible: page.overlays.show_osculating_circle
                        color: page.colors.osculating_circle_color || "#00AAFF"
                        opacity: 0.6
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
                    }
                    GpuShape {
                        key: page.view.section || ""
                        visible: page.overlays.show_curve_section
                        color: page.colors.curve_section_color || "#FF4400"
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: canvas.matrix }
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
                        Rectangle { x: -parent.size; y: -0.5; width: parent.size * 2; height: 1; color: page.colors.center_mark_color || "#808080"; opacity: 0.6 }
                        Rectangle { x: -0.5; y: -parent.size; width: 1; height: parent.size * 2; color: page.colors.center_mark_color || "#808080"; opacity: 0.6 }
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
                            color: current ? theme.accent : cornerArea.containsMouse ? theme.raised
                                 : Qt.rgba(theme.window.r, theme.window.g, theme.window.b, 0.85)
                            border.width: 1
                            border.color: cornerArea.containsMouse ? theme.accent : Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.15)
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Text {
                                id: cornerText
                                anchors.centerIn: parent
                                text: modelData.label
                                color: parent.current ? "white" : theme.text
                                font.pointSize: theme.fontPoint * 0.78
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
                        radius: theme.em * 0.2
                        rotation: page.current.yaw || 0
                        color: "transparent"
                        border.width: 3
                        border.color: page.colors.highlighted_coordinates_color || "#22DD00"
                    }

                    // Empty map
                    Column {
                        anchors.centerIn: parent
                        visible: !page.loaded
                        spacing: theme.em * 0.8
                        Icon { anchors.horizontalCenter: parent.horizontalCenter; glyph: ""; size: theme.em * 3; color: theme.dimText }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: i18n.tr("Load a track map recorded by the Mapping module.")
                            color: theme.dimText
                        }
                    }
                }

                // Sector legend
                Row {
                    visible: page.loaded
                    anchors { left: parent.left; top: parent.top; margins: theme.em * 0.6 }
                    spacing: theme.em * 0.6
                    Repeater {
                        model: page.loaded ? page.view.sectorLengths : []
                        Row {
                            spacing: theme.em * 0.3
                            opacity: page.current.sector === index + 1 ? 1 : 0.6
                            Rectangle { width: theme.em * 0.7; height: theme.em * 0.3; radius: height / 2; color: page.view.sectorColors[index]; anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                text: "S" + (index + 1) + "  " + modelData.toFixed(0) + " m"
                                color: theme.text
                                font.pointSize: theme.fontPoint * 0.85
                                font.weight: page.current.sector === index + 1 ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                }
            }

            // Info at position
            ColumnLayout {
                Layout.preferredWidth: theme.em * 17
                Layout.maximumWidth: theme.em * 17
                Layout.fillWidth: false
                Layout.fillHeight: true
                spacing: theme.em * 0.6
                visible: page.loaded

                InfoCard {
                    visible: page.overlays.show_position_info
                    title: i18n.tr("Position")
                    value: page.number(page.current.distance, 1) + " m"
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
                    accentColor: page.current.direction > 0 ? "#38BDF8" : page.current.direction < 0 ? "#F472B6" : theme.text
                    lines: [
                        i18n.tr("Radius") + " " + page.number(page.current.radius, 1) + " m",
                        i18n.tr("Length") + " " + page.number(page.current.curveLength, 1) + " m (" + (page.current.lengthDesc || "") + ")",
                        i18n.tr("Angle") + " " + page.number(page.current.angle, 1) + "°",
                    ]
                }
                InfoCard {
                    visible: page.overlays.show_slope_info
                    title: i18n.tr("Slope")
                    value: (page.current.slope > 0 ? "+" : "") + page.number(page.current.slope, 2) + " %"
                    accentColor: page.current.slope > 0.5 ? "#F97316" : page.current.slope < -0.5 ? "#22C55E" : theme.text
                    lines: [
                        page.current.slopeDesc || "",
                        i18n.tr("Angle") + " " + page.number(page.current.slopeAngle, 2) + "°",
                        i18n.tr("Delta") + " " + page.number(page.current.slopeDelta, 2) + " m",
                    ]
                }
                Card {
                    Layout.fillWidth: true
                    implicitHeight: nodesColumn.implicitHeight + theme.em * 1.2
                    ColumnLayout {
                        id: nodesColumn
                        anchors.fill: parent
                        anchors.margins: theme.em * 0.6
                        spacing: 0
                        RowLayout {
                            Text { text: i18n.tr("Section nodes"); color: theme.dimText; Layout.fillWidth: true }
                            Text { text: backend.curveNodes; color: theme.text; font.weight: Font.DemiBold; font.features: { "tnum": 1 } }
                        }
                        Slider {
                            Layout.fillWidth: true
                            from: 3; to: 80; stepSize: 1
                            value: backend.curveNodes
                            onMoved: backend.setCurveNodes(value)
                            ToolTip.visible: hovered
                            ToolTip.text: i18n.tr("Map nodes measured from position: more nodes, longer curve section")
                        }
                    }
                }
                Item { Layout.fillHeight: true }
            }
        }

        // Elevation profile & position
        Card {
            Layout.fillWidth: true
            implicitHeight: bottomColumn.implicitHeight + theme.em * 1.0
            visible: page.loaded
            ColumnLayout {
                id: bottomColumn
                anchors.fill: parent
                anchors.margins: theme.em * 0.5
                spacing: theme.em * 0.3

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
                    GpuShape {
                        key: page.view.elevation || ""
                        color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.18)
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: Qt.matrix4x4(profile.sx, 0, 0, 0, 0, -profile.sy, 0, profile.height - 3 + profile.minZ * profile.sy, 0, 0, 1, 0, 0, 0, 0, 1) }
                    }
                    GpuShape {
                        key: page.view.elevationLine || ""
                        color: theme.accent
                        revision: backend.revision
                        transform: Matrix4x4 { matrix: Qt.matrix4x4(profile.sx, 0, 0, 0, 0, -profile.sy, 0, profile.height - 3 + profile.minZ * profile.sy, 0, 0, 1, 0, 0, 0, 0, 1) }
                    }
                    Text { x: 4; y: 2; text: page.number(profile.maxZ, 1) + " m"; color: theme.dimText; font.pointSize: theme.fontPoint * 0.75 }
                    Text { x: 4; anchors.bottom: parent.bottom; text: page.number(profile.minZ, 1) + " m"; color: theme.dimText; font.pointSize: theme.fontPoint * 0.75 }
                    Rectangle {  // position
                        x: backend.position * profile.sx
                        width: 2
                        height: profile.height
                        color: page.colors.highlighted_coordinates_color || "#22DD00"
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onPressed: function(mouse) { backend.setPosition(mouse.x / profile.sx) }
                        onPositionChanged: function(mouse) { if (pressed) backend.setPosition(mouse.x / profile.sx) }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.5
                    TpButton {
                        glyph: page.playing ? "" : ""  // pause, play
                        tip: i18n.tr("Drive around the track")
                        onClicked: page.playing = !page.playing
                    }
                    TpButton { glyph: ""; flat: true; onClicked: page.step(-1) }  // chevron left
                    Slider {
                        Layout.fillWidth: true
                        from: 0
                        to: Math.max(backend.length, 1)
                        stepSize: page.settings.step || 5
                        value: backend.position
                        onMoved: backend.setPosition(value)
                    }
                    TpButton { glyph: ""; flat: true; onClicked: page.step(1) }  // chevron right
                    Text {
                        text: backend.position.toFixed(0) + " / " + backend.length.toFixed(0) + " m"
                        color: theme.text
                        font.features: { "tnum": 1 }
                        Layout.preferredWidth: theme.em * 7
                        horizontalAlignment: Text.AlignRight
                    }
                }
            }
        }
    }
}
