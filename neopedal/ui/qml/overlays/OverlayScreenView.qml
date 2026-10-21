import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Screen view of Overlays page: screens of the desktop scaled into the page, running overlays (those the search &
// chips show) at their place with their preview, smaller ones over bigger ones. Drag one to move it (saved, undo in
// the page toast), click opens its settings. Overlays covering another one are outlined in warning color.
Item {
    id: view

    readonly property var screenData: backend.screenLayout
    readonly property var bounds: screenData.bounds || ({ x: 0, y: 0, w: 1920, h: 1080 })
    readonly property real zoom: Math.max(0.01, Math.min((width - theme.space4 * 2) / Math.max(bounds.w, 1),
                                                         (height - notices.height - theme.space4 * 3) / Math.max(bounds.h, 1)))
    property var shownOverlays: []  // kept while dragging: delegates never made again under the pointer
    property bool dragging: false

    function follow() {
        if (!dragging)
            shownOverlays = backend.screenLayout.overlays || []
    }
    Component.onCompleted: follow()
    onDraggingChanged: follow()
    Connections {
        target: backend
        function onScreenChanged() { view.follow() }
    }

    Accessible.role: Accessible.Pane
    Accessible.name: i18n.tr("Running overlays at their place on your screens")

    // Overlaps & overlays not running
    Row {
        id: notices
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: theme.space3
        height: implicitHeight
        Pill {
            visible: (view.screenData.overlaps || 0) > 0
            glyph: ""  // warning
            tint: theme.warning
            text: i18n.trm((view.screenData.overlaps || 0) + " overlays overlap")
            tip: i18n.tr("Outlined overlays cover part of another one")
        }
        Pill {
            visible: (view.screenData.notRunning || 0) > 0
            tint: theme.dimText
            text: i18n.trm((view.screenData.notRunning || 0) + " enabled overlays not running")
            tip: i18n.tr("Enabled overlays that could not start are not shown here")
        }
    }

    // Desktop: screens, then overlays
    Item {
        id: desktop
        width: Math.round(view.bounds.w * view.zoom)
        height: Math.round(view.bounds.h * view.zoom)
        x: Math.round((view.width - width) / 2)
        y: Math.round(notices.height + theme.space4 + (view.height - notices.height - theme.space4 - height) / 2)

        Repeater {
            model: view.screenData.screens || []
            Rectangle {
                required property var modelData
                x: Math.round((modelData.x - view.bounds.x) * view.zoom)
                y: Math.round((modelData.y - view.bounds.y) * view.zoom)
                width: Math.round(modelData.w * view.zoom)
                height: Math.round(modelData.h * view.zoom)
                radius: theme.radiusMd
                border.width: 1
                border.color: theme.border
                gradient: Gradient {
                    GradientStop { position: 0; color: theme.stageTop }
                    GradientStop { position: 1; color: theme.stageBottom }
                }
                Text {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: theme.space3
                    width: parent.width - theme.space3 * 2
                    elide: Text.ElideRight
                    text: (modelData.primary ? i18n.tr("Main screen") + "  ·  " : "")
                          + modelData.w + " × " + modelData.h
                    color: theme.stageText
                    font.pointSize: theme.fontCaption
                }
            }
        }

        Repeater {
            model: view.shownOverlays
            Rectangle {
                id: box
                required property var modelData
                readonly property bool hovered: area.containsMouse || area.drag.active
                x: Math.round((modelData.x - view.bounds.x) * view.zoom)
                y: Math.round((modelData.y - view.bounds.y) * view.zoom)
                width: Math.max(4, Math.round(modelData.w * view.zoom))
                height: Math.max(4, Math.round(modelData.h * view.zoom))
                z: area.drag.active ? 2 : hovered ? 1 : 0
                color: "transparent"
                border.width: modelData.overlap || hovered ? 2 : 1
                border.color: modelData.overlap ? theme.warning : hovered ? theme.accent : modelData.color
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label + (modelData.overlap ? ", " + i18n.tr("Overlaps another overlay") : "")

                Image {
                    anchors.fill: parent
                    anchors.margins: box.border.width
                    source: box.modelData.preview
                    fillMode: Image.PreserveAspectFit  // same ratio as the overlay (picture scaled down if big)
                    asynchronous: true
                    cache: true
                    sourceSize.width: Math.ceil(width * Screen.devicePixelRatio / 32) * 32
                    smooth: true
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: drag.active ? Qt.ClosedHandCursor : Qt.PointingHandCursor
                    drag.target: box
                    drag.threshold: 4
                    drag.minimumX: 0
                    drag.minimumY: 0
                    drag.maximumX: Math.max(0, desktop.width - box.width)
                    drag.maximumY: Math.max(0, desktop.height - box.height)
                    drag.onActiveChanged: if (drag.active) view.dragging = true
                    onReleased: {
                        if (!view.dragging)
                            return
                        backend.moveOverlay(box.modelData.name, Math.round(box.x / view.zoom + view.bounds.x),
                                            Math.round(box.y / view.zoom + view.bounds.y))
                        view.dragging = false
                    }
                    onClicked: backend.openConfig(box.modelData.name)
                }
                ToolTip.visible: area.containsMouse && !area.drag.active
                ToolTip.text: box.modelData.label + "  ·  " + box.modelData.x + ", " + box.modelData.y
                              + (box.modelData.overlap ? "\n" + i18n.tr("Overlaps another overlay") : "")
                ToolTip.delay: theme.tipDelay
            }
        }
    }

    EmptyState {
        anchors.centerIn: parent
        visible: view.shownOverlays.length === 0
        glyph: ""  // monitor
        title: backend.filtered ? i18n.tr("No running overlay matches the filters")
                                : i18n.tr("No overlay running")
        text: backend.filtered ? "" : i18n.tr("Enable overlays to see them here at their place on your screens.")
        actionText: backend.filtered ? i18n.tr("Clear Filters") : ""
        onAction: backend.clearFilters()
    }
}
