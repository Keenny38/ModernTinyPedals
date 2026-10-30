import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Screen view of Overlays page: one screen at a time (main screen first, a choice per screen, or all screens),
// running overlays (those the search & chips show) at their place with their preview, smaller ones over bigger
// ones, optional screenshot of the game under them. Drag one to move it (snapped to other overlays & screen
// edges with guides, as in game edit mode: its Snap, snap distance & guides options, Ctrl inverts snapping), or
// Tab to it then arrows (Shift: 10 px); click or Enter opens its options. Moves
// are saved & undoable (page toast), never while overlays are locked (as in game). Overlays covering another one
// are outlined in warning color.
Item {
    id: view
    objectName: "screenView"

    readonly property var screenData: backend.screenLayout
    readonly property var screens: screenData.screens || []
    readonly property var bounds: screenData.bounds || ({ x: 0, y: 0, w: 1920, h: 1080 })
    readonly property bool locked: backend.positionsLocked
    property string screenName: ""  // screen shown, "" before the first layout (then main screen)
    property bool allScreens: false
    readonly property int screenIndex: {
        for (var i = 0; i < screens.length; ++i)
            if (screens[i].name === screenName)
                return i
        return -1
    }
    // Desktop part shown: chosen screen, or every screen
    readonly property var area: !allScreens && screenIndex >= 0 ? screens[screenIndex] : bounds
    readonly property real zoom: Math.max(0.01, Math.min(stage.width / Math.max(area.w, 1), stage.height / Math.max(area.h, 1)))
    // Edit mode options (application): magnetic snap (Snap switch here & in game), distance, guides shown
    property var snapping: ({ magnetic: true, distance: 10, guides: true })
    property var shownOverlays: []  // kept while dragging: delegates never made again under the pointer
    property bool dragging: false
    property string refocusName: ""  // frame focused by keyboard when frames were made again: focused again
    property var guides: ({ x: [], y: [] })  // alignment lines of dragged overlay (desktop coordinates)

    function readSnapping() {
        snapping = backend.snapSettings()
    }
    function follow() {
        // Hidden (cards or list view shown, page hidden): frames & pictures kept as they are, keyboard focus of the
        // other view left alone; followed once shown again (onVisibleChanged)
        if (dragging || !view.visible)
            return
        readSnapping()  // switched in game meanwhile (edit mode toolbar)
        var focused = view.Window.activeFocusItem
        refocusName = focused && focused.objectName === "screenFrame" ? focused.overlayName : ""
        shownOverlays = backend.screenLayout.overlays || []
        if (screenIndex < 0) {  // first layout or chosen screen unplugged: main screen
            var main = ""
            for (var i = 0; i < screens.length; ++i)
                if (screens[i].primary || main === "")
                    main = screens[i].name
            screenName = main
        }
    }
    function screenLabel(index) {
        var screen = screens[index]
        return (index + 1) + "  ·  " + screen.w + " × " + screen.h
    }
    function shownScreen() {
        return screenIndex >= 0 ? screens[screenIndex].name : ""
    }
    Component.onCompleted: follow()
    onDraggingChanged: follow()
    onVisibleChanged: if (visible) follow()
    Connections {
        target: backend
        function onScreenChanged() { view.follow() }
    }

    Accessible.role: Accessible.Pane
    Accessible.name: i18n.tr("Running overlays at their place on your screens")

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.space3

        // Screen choice, snapping & screenshot under the overlays
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpSegmented {
                objectName: "screenChoice"
                visible: view.screens.length > 1
                name: i18n.tr("Screen")
                maxWidth: Math.max(0, parent.width * 0.6)
                options: {
                    var texts = []
                    for (var i = 0; i < view.screens.length; ++i)
                        texts.push(view.screenLabel(i))
                    texts.push(i18n.tr("All Screens"))
                    return texts
                }
                currentIndex: view.allScreens ? view.screens.length : Math.max(view.screenIndex, 0)
                onActivated: function(index) {
                    view.allScreens = index >= view.screens.length
                    if (!view.allScreens)
                        view.screenName = view.screens[index].name
                }
            }
            TpText {
                Layout.fillWidth: true
                role: "caption"
                text: view.screenIndex >= 0 && view.screens[view.screenIndex].primary && !view.allScreens
                      ? i18n.tr("Main screen") : ""
            }
            TpSwitch {
                objectName: "snapSwitch"
                text: i18n.tr("Snap")
                tip: i18n.tr("Magnetic snap, as in game edit mode: a dragged overlay lines up with the edges & centers of other overlays and screens (Ctrl: the other way)")
                checkable: false  // follows the option
                checked: view.snapping.magnetic === true
                enabled: !view.locked
                onClicked: {
                    backend.setMagneticSnap(!view.snapping.magnetic)
                    view.readSnapping()
                }
            }
            TpButton {
                id: backgroundButton
                objectName: "backgroundButton"
                flat: true
                glyph: "\uE8B9"  // picture
                fallback: i18n.tr("Background")
                text: parent.width > theme.bpCompact ? i18n.tr("Background") : ""
                tip: i18n.tr("Show a picture of the game under the overlays, to place them over it")
                checked: backend.background.url !== undefined
                onClicked: backgroundMenu.toggleBelow(backgroundButton)
            }
        }

        // Locks, overlaps & overlays not running
        Flow {
            id: notices
            Layout.fillWidth: true
            spacing: theme.space3
            Pill {
                objectName: "positionsLockedPill"
                visible: view.locked
                glyph: "\uE72E"  // lock
                tint: theme.warning
                text: i18n.tr("Overlays locked")
                tip: i18n.tr("Locked overlays cannot be moved, here as in game")
            }
            TpButton {
                objectName: "unlockPositionsButton"
                visible: view.locked
                size: "sm"
                text: i18n.tr("Unlock Overlay")
                tip: i18n.tr("Overlays can be moved again, here and on screen (edit mode in game)")
                onClicked: backend.unlockPositions()
            }
            Pill {
                objectName: "presetLockedPill"
                visible: backend.presetLocked
                glyph: "\uE72E"  // lock
                tint: theme.warning
                text: i18n.tr("Preset Locked")
                tip: i18n.tr("Moves are not saved in a locked preset: they last until the app is closed")
            }
            TpButton {
                objectName: "unlockPresetButton"
                visible: backend.presetLocked
                size: "sm"
                text: i18n.tr("Unlock Preset")
                onClicked: backend.unlockPreset()
            }
            Pill {
                visible: (view.screenData.overlaps || 0) > 0
                glyph: "\uE7BA"  // warning
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

        // Desktop: screens, screenshot, overlays, then alignment lines while dragging
        Item {
            id: stage
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            Item {
                id: desktop
                width: Math.round(view.bounds.w * view.zoom)
                height: Math.round(view.bounds.h * view.zoom)
                // Part shown centered in the stage, the rest of the desktop cut
                x: Math.round((stage.width - view.area.w * view.zoom) / 2 - (view.area.x - view.bounds.x) * view.zoom)
                y: Math.round((stage.height - view.area.h * view.zoom) / 2 - (view.area.y - view.bounds.y) * view.zoom)

                Repeater {
                    model: view.screens
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
                        TpText {
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            anchors.margins: theme.space3
                            width: parent.width - theme.space3 * 2
                            role: "caption"
                            text: (modelData.primary ? i18n.tr("Main screen") + "  ·  " : "")
                                  + modelData.w + " × " + modelData.h
                            color: theme.stageText
                        }
                    }
                }

                Image {
                    objectName: "screenBackground"
                    readonly property var shot: backend.background
                    // Texture released while the view is hidden (loaded again, from the store, once shown)
                    readonly property bool shown: view.visible && shot.url !== undefined
                    visible: shown
                    x: shown ? Math.round((shot.x - view.bounds.x) * view.zoom) : 0
                    y: shown ? Math.round((shot.y - view.bounds.y) * view.zoom) : 0
                    width: shown ? Math.round(shot.w * view.zoom) : 0
                    height: shown ? Math.round(shot.h * view.zoom) : 0
                    source: shown ? shot.url : ""
                    fillMode: Image.Stretch
                    asynchronous: true
                    cache: false
                    sourceSize.width: Math.ceil(width * Screen.devicePixelRatio / 32) * 32
                    smooth: true
                }

                Repeater {
                    model: view.shownOverlays
                    Rectangle {
                        id: box
                        required property var modelData
                        readonly property string overlayName: modelData.name
                        readonly property bool hovered: area.containsMouse || moving
                        property bool moving: false
                        property int dragX: modelData.x  // desktop place while dragged
                        property int dragY: modelData.y
                        objectName: "screenFrame"
                        x: Math.round(((moving ? dragX : modelData.x) - view.bounds.x) * view.zoom)
                        y: Math.round(((moving ? dragY : modelData.y) - view.bounds.y) * view.zoom)
                        width: Math.max(4, Math.round(modelData.w * view.zoom))
                        height: Math.max(4, Math.round(modelData.h * view.zoom))
                        z: moving ? 2 : hovered || activeFocus ? 1 : 0
                        color: "transparent"
                        border.width: modelData.overlap || hovered ? 2 : 1
                        border.color: modelData.overlap ? theme.warning : hovered ? theme.strokeStrong : modelData.color
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.label + (modelData.overlap ? ", " + i18n.tr("Overlaps another overlay") : "")
                                         + (view.locked ? ", " + i18n.tr("Overlays locked") : "")
                        Accessible.description: i18n.tr("Arrows move it (Shift: 10 px), Enter opens its options")
                        Accessible.onPressAction: backend.openConfig(box.overlayName)
                        Component.onCompleted: {
                            if (view.refocusName === overlayName) {
                                view.refocusName = ""
                                forceActiveFocus()
                            }
                        }

                        // Arrows move it, Enter opens its options: taken before page shortcuts
                        function keyStep(event) {
                            var step = event.modifiers & Qt.ShiftModifier ? 10 : 1
                            return event.key === Qt.Key_Left ? [-step, 0] : event.key === Qt.Key_Right ? [step, 0]
                                 : event.key === Qt.Key_Up ? [0, -step] : event.key === Qt.Key_Down ? [0, step] : null
                        }
                        Keys.onShortcutOverride: function(event) {
                            if (keyStep(event) !== null || event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                                event.accepted = true
                        }
                        Keys.onPressed: function(event) {
                            var step = keyStep(event)
                            if (step !== null) {
                                event.accepted = true
                                if (!view.locked)
                                    backend.nudgeOverlay(box.overlayName, step[0], step[1])
                            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                event.accepted = true
                                backend.openConfig(box.overlayName)
                            }
                        }

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
                        Icon {  // locked: never moved (shown when the frame has room)
                            visible: view.locked && box.width > theme.em * 2 && box.height > theme.em * 1.4  // content-tuned: room for the icon
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: theme.space1
                            glyph: "\uE72E"  // lock
                            fallback: ""
                            size: theme.iconSm
                            color: theme.stageText
                        }
                        FocusRing { visible: box.activeFocus }
                        MouseArea {
                            id: area
                            property real grabX: 0  // pointer on desktop item when pressed
                            property real grabY: 0
                            property bool moved: false
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: box.moving ? Qt.ClosedHandCursor : Qt.PointingHandCursor
                            onPressed: function(mouse) {
                                var point = area.mapToItem(desktop, mouse.x, mouse.y)
                                grabX = point.x
                                grabY = point.y
                                moved = false
                            }
                            onPositionChanged: function(mouse) {
                                if (!pressed || view.locked)
                                    return
                                var point = area.mapToItem(desktop, mouse.x, mouse.y)
                                if (!box.moving && Math.abs(point.x - grabX) + Math.abs(point.y - grabY) < theme.space2)
                                    return  // a click, not a drag
                                if (!box.moving) {
                                    box.dragX = box.modelData.x
                                    box.dragY = box.modelData.y
                                    box.moving = true
                                    view.dragging = true
                                }
                                moved = true
                                // Snap distance of the option (desktop pixels), at least a few page pixels at any zoom
                                // (scaled down screens); Ctrl inverts magnetic snapping, as in game
                                var place = backend.snapOverlay(
                                    box.overlayName,
                                    Math.round(box.modelData.x + (point.x - grabX) / view.zoom),
                                    Math.round(box.modelData.y + (point.y - grabY) / view.zoom),
                                    Math.max(1, view.snapping.distance, Math.round(theme.space3 / view.zoom)),
                                    (view.snapping.magnetic === true) !== ((mouse.modifiers & Qt.ControlModifier) !== 0))
                                box.dragX = place.x
                                box.dragY = place.y
                                view.guides = view.snapping.guides === true ? { x: place.linesX, y: place.linesY } : { x: [], y: [] }
                            }
                            onReleased: {
                                if (!box.moving)
                                    return
                                view.guides = { x: [], y: [] }
                                backend.moveOverlay(box.overlayName, box.dragX, box.dragY)
                                box.moving = false
                                view.dragging = false
                            }
                            onCanceled: {
                                view.guides = { x: [], y: [] }
                                box.moving = false
                                view.dragging = false
                            }
                            onClicked: if (!moved) backend.openConfig(box.overlayName)
                        }
                        ToolTip.visible: area.containsMouse && !box.moving
                        ToolTip.text: box.modelData.label + "  ·  " + box.modelData.x + ", " + box.modelData.y
                                      + (box.modelData.overlap ? "\n" + i18n.tr("Overlaps another overlay") : "")
                                      + (view.locked ? "\n" + i18n.tr("Overlays locked: unlock them to move one") : "")
                        ToolTip.delay: theme.tipDelay
                    }
                }

                // Alignment lines of the dragged overlay
                Repeater {
                    model: view.guides.x
                    Rectangle {
                        required property int modelData
                        x: Math.round((modelData - view.bounds.x) * view.zoom)
                        y: 0
                        z: 3
                        width: 1
                        height: desktop.height
                        color: theme.accent
                    }
                }
                Repeater {
                    model: view.guides.y
                    Rectangle {
                        required property int modelData
                        x: 0
                        y: Math.round((modelData - view.bounds.y) * view.zoom)
                        z: 3
                        width: desktop.width
                        height: 1
                        color: theme.accent
                    }
                }
            }

            TpStateView {
                anchors.centerIn: parent
                empty: view.shownOverlays.length === 0
                glyph: "\uE7F4"  // monitor
                title: backend.filtered ? i18n.tr("No running overlay matches the filters")
                                        : i18n.tr("No overlay running")
                text: backend.filtered ? "" : i18n.tr("Enable overlays to see them here at their place on your screens.")
                actionText: backend.filtered ? i18n.tr("Clear Filters") : ""
                onAction: backend.clearFilters()
            }
        }
    }

    TpMenu {
        id: backgroundMenu
        TpMenuItem {
            text: i18n.tr("Capture Screen")
            onTriggered: backend.captureBackground(view.shownScreen() || (view.screens.length > 0 ? view.screens[0].name : ""))
        }
        TpMenuItem {
            text: i18n.tr("Load Screenshot…")
            onTriggered: backend.loadBackground()
        }
        MenuSeparator {}
        TpMenuItem {
            text: i18n.tr("Remove Background")
            enabled: backend.background.url !== undefined
            onTriggered: backend.clearBackground()
        }
    }
}
