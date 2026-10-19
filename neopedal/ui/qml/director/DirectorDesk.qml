import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Camera desk: car on air (why, how long, director held after an operator cut), cameras of the game, replay
// transport, stories worth showing (assisted: take one; automatic: what the director cuts to next).
// Suggestions show their number: keys 1 to 6 take them. Cameras: Tab, Enter or Space.
ColumnLayout {
    id: desk
    spacing: theme.space4

    readonly property var onAir: backend.onAir
    readonly property bool hasCar: onAir.slot !== undefined
    readonly property string mode: backend.modeName

    function seconds(value) {
        var total = Math.max(Math.floor(value), 0)
        return Math.floor(total / 60) + ":" + (total % 60 < 10 ? "0" : "") + (total % 60)
    }

    // HUD part of the game in the HUD menu: checked while the game shows it
    component HudAction: Action {
        property string key: ""
        objectName: "hud_" + key
        checkable: true
        enabled: backend.camera.hudState[key] !== undefined
        checked: backend.camera.hudState[key] === true
        onTriggered: {
            backend.camera.toggleHudComponent(key)
            // click toggled checked by itself: state of game shown again (also when the toggle was refused)
            checked = Qt.binding(function() { return backend.camera.hudState[key] === true })
        }
    }

    // Camera button of desk: highlighted (red fill, dot & bold) while it is the camera of the game
    component CameraButton: AbstractButton {
        id: control
        property string key: ""
        readonly property bool current: backend.camera.cameraKey === key
        objectName: "camera_" + key
        hoverEnabled: true
        focusPolicy: Qt.TabFocus
        implicitHeight: Math.round(theme.rowCompact)
        implicitWidth: Math.max(label.implicitWidth + theme.em * 1.0, theme.em * 3.2)
        Layout.fillWidth: true
        onClicked: backend.camera.selectCamera(key)
        Keys.onReturnPressed: animateClick()
        Keys.onEnterPressed: animateClick()
        Keys.onShortcutOverride: function(event) {
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
                event.accepted = true
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        ToolTip.visible: (hovered || visualFocus) && label.truncated
        ToolTip.text: text
        ToolTip.delay: theme.tipDelay
        Accessible.role: Accessible.RadioButton
        Accessible.name: text
        Accessible.checked: current
        background: Rectangle {
            radius: theme.radiusMd
            color: control.current ? theme.lossFill
                 : control.down ? theme.border : control.hovered ? theme.hover : theme.raised
            border.width: control.current ? 0 : 1
            border.color: theme.border
            Behavior on color { ColorAnimation { duration: theme.motionFast } }
            FocusRing { visible: control.visualFocus }
        }
        contentItem: Text {
            id: label
            text: (control.current ? "● " : "") + control.text
            color: control.current ? theme.inkOn(theme.lossFill) : theme.text
            font.pointSize: theme.fontSmall
            font.weight: control.current ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    // On air
    Card {
        Layout.fillWidth: true
        implicitHeight: airColumn.implicitHeight + theme.em * 1.3
        border.color: desk.hasCar ? theme.loss : theme.cardBorder
        ColumnLayout {
            id: airColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.padCard }
            spacing: theme.space3

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                Rectangle {  // on air light
                    implicitHeight: Math.round(theme.em * 1.6)
                    implicitWidth: airText.implicitWidth + theme.space6
                    radius: theme.radiusSm
                    color: desk.hasCar ? theme.lossFill : theme.raised
                    Text {
                        id: airText
                        anchors.centerIn: parent
                        text: i18n.tr("On Air").toUpperCase()
                        color: desk.hasCar ? theme.inkOn(theme.lossFill) : theme.dimOn(theme.raised)
                        font.weight: Font.Bold
                        font.pointSize: theme.fontCaption
                        font.letterSpacing: 1
                    }
                }
                Pill {
                    visible: desk.hasCar
                    text: desk.onAir.kindText || ""
                    glyph: desk.onAir.glyph || ""
                    tint: theme.tone(desk.onAir.tone || "")
                }
                Item { Layout.fillWidth: true }
                TpButton {  // car kept on air: director does not cut
                    objectName: "lockButton"
                    visible: desk.hasCar
                    size: "sm"
                    flat: !backend.carLocked
                    checked: backend.carLocked
                    glyph: backend.carLocked ? "" : ""  // lock, unlock
                    fallback: i18n.tr("Locked")
                    text: backend.carLocked ? i18n.tr("Locked") : ""
                    tip: i18n.tr("Keep this car on air: the director does not cut until unlocked")
                    onClicked: backend.toggleLock()
                }
                Text {  // shot length
                    id: shotClock
                    visible: desk.hasCar
                    property real now: Date.now()
                    text: desk.seconds((now - (desk.onAir.startMs || now)) / 1000)
                    color: theme.dimText
                    font.features: { "tnum": 1 }
                    Timer {
                        interval: 500
                        repeat: true
                        running: shotClock.visible && pageState.active
                        triggeredOnStart: true
                        onTriggered: shotClock.now = Date.now()
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space4
                TpClassStrip {
                    visible: desk.hasCar
                    Layout.fillHeight: false
                    Layout.preferredWidth: Math.round(theme.em * 0.35)
                    Layout.preferredHeight: Math.round(theme.em * 2.6)
                    Layout.topMargin: 0
                    Layout.bottomMargin: 0
                    tint: desk.onAir.classColor || ""
                }
                Item {  // car brand logo: room kept (name does not move when it loads)
                    visible: desk.hasCar
                    Layout.preferredWidth: theme.em * 2.4
                    Layout.preferredHeight: theme.em * 1.6
                    GameLogo { anchors.centerIn: parent; source: desk.onAir.brandLogo || ""; boxWidth: theme.em * 2.4; boxHeight: theme.em * 1.6 }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Text {
                        Layout.fillWidth: true
                        text: desk.hasCar ? (desk.onAir.number !== "" ? "#" + desk.onAir.number + "  " : "") + desk.onAir.driver
                                          : i18n.tr("No car on air yet")
                        color: desk.hasCar ? theme.text : theme.dimText
                        font.pointSize: theme.fontLarge
                        font.weight: Font.Bold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: desk.hasCar ? "P" + desk.onAir.classPosition + " " + desk.onAir.carClass
                                            + (backend.camera.cameraLabel !== "" ? "  ·  " + backend.camera.cameraLabel : "")
                                          : i18n.tr("Pick a car, a camera or a suggestion; the automatic mode cuts by itself.")
                        color: theme.dimText
                        font.pointSize: theme.fontLabel
                        elide: Text.ElideRight
                        wrapMode: desk.hasCar ? Text.NoWrap : Text.WordWrap
                    }
                }
            }
            // Pit radar: cars near the car on air in the pit lane (alongside in red, filled)
            Flow {
                Layout.fillWidth: true
                visible: backend.pitRadarCount > 0
                spacing: theme.space2
                Repeater {
                    model: backend.pitRadarRows  // own model: distances change in place, card bindings untouched
                    delegate: Pill {
                        required property string number
                        required property string distance
                        required property bool alongside
                        required property bool ahead
                        text: "#" + number + "  " + (alongside ? i18n.tr("Alongside") : (ahead ? "▲ " : "▼ ") + distance)
                        tint: alongside ? theme.loss : theme.warning
                        solid: alongside
                    }
                }
            }
            // Automatic mode: shortest shot going by (director may cut once full)
            TpMeter {
                id: shotBar
                property real now: Date.now()
                readonly property real length: desk.onAir.minShotMs || 0
                Layout.fillWidth: true
                visible: desk.mode === "auto" && desk.hasCar && length > 0 && !backend.carLocked
                value: length > 0 ? Math.min((now - (desk.onAir.startMs || now)) / length, 1) : 0
                tint: value >= 1 ? theme.gain : theme.loss
                name: i18n.tr("Shortest shot")
                thickness: Math.max(2, Math.round(theme.em * 0.18))
                // Moved on in steps: an eased move restarted at every step never ends (page drawn at every frame
                // for the whole shot), a step is one frame. A step about every 2 px of bar, 5 a second at most.
                animated: false
                Timer {
                    interval: Math.max(200, Math.round(shotBar.length / Math.max(shotBar.width / 2, 1)))
                    repeat: true
                    running: shotBar.visible && shotBar.value < 1 && pageState.active
                    triggeredOnStart: true
                    onTriggered: shotBar.now = Date.now()
                }
            }
            // Automatic mode held after an operator cut
            Text {
                id: holdText
                property real now: Date.now()
                readonly property real remaining: ((desk.onAir.holdMs || 0) - now) / 1000
                Layout.fillWidth: true
                visible: desk.mode === "auto" && remaining > 0 && !backend.carLocked
                text: i18n.tr("Operator cut: director cuts again in %1 s").arg(Math.ceil(remaining))
                color: theme.warning
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
                Timer {
                    interval: 500
                    repeat: true
                    // stops once the hold ran out (a new hold time makes remaining positive again)
                    running: desk.mode === "auto" && holdText.remaining > 0 && pageState.active
                    triggeredOnStart: true
                    onTriggered: holdText.now = Date.now()
                }
            }
        }
    }

    // Cameras of the game, by group
    Card {
        Layout.fillWidth: true
        implicitHeight: cameraColumn.implicitHeight + theme.space6
        ColumnLayout {
            id: cameraColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.space4 }
            spacing: theme.space3
            Repeater {
                model: ["Driving", "Onboard", "Trackside"]
                delegate: ColumnLayout {
                    id: group
                    required property string modelData
                    Layout.fillWidth: true
                    spacing: theme.space2
                    RowLayout {
                        Layout.fillWidth: true
                        TpSectionLabel {
                            Layout.fillWidth: true
                            text: i18n.tr(group.modelData)
                        }
                        TpButton {
                            flat: true
                            size: "xs"
                            glyph: ""  // chevron left
                            fallback: "‹"
                            tip: i18n.tr("Previous camera angle")
                            onClicked: backend.camera.stepCamera(group.modelData, -1)
                        }
                        TpButton {
                            flat: true
                            size: "xs"
                            glyph: ""  // chevron right
                            fallback: "›"
                            tip: i18n.tr("Next camera angle")
                            onClicked: backend.camera.stepCamera(group.modelData, 1)
                        }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        // Width of the card column (same as this grid's): its own width would rearrange it again
                        columns: Math.max(2, Math.min(group.modelData === "Trackside" ? 5 : 4,
                                                      Math.floor(cameraColumn.width / (theme.em * 6.5))))
                        columnSpacing: theme.em * 0.25
                        rowSpacing: theme.em * 0.25
                        Repeater {
                            model: backend.camera.camerasByGroup[group.modelData] || []
                            delegate: CameraButton {
                                required property var modelData
                                key: modelData.key
                                text: modelData.text
                            }
                        }
                    }
                }
            }
            // HUD of the game (as the Game Replays page): all or each part, clean pictures for the stream
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: theme.space1
                TpSectionLabel {
                    Layout.fillWidth: true
                    text: i18n.tr("Game HUD")
                }
                TpButton {
                    id: hudButton
                    objectName: "hudButton"
                    flat: true
                    size: "xs"
                    glyph: ""  // view
                    fallback: "HUD"
                    tip: i18n.tr("Game HUD")
                    enabled: backend.inSession
                    checked: hudMenu.visible
                    // Menu right aligned on button (page edge): never cut by window
                    onClicked: {
                        if (hudMenu.visible) {
                            hudMenu.close()
                            return
                        }
                        backend.camera.refreshHud()  // parts shown asked again: checks follow the game
                        hudMenu.popup(hudButton, hudButton.width - hudMenu.width, hudButton.height + 4)
                    }
                    TpMenu {
                        id: hudMenu
                        width: Math.max(implicitWidth, theme.em * 20)
                        // As a middle click in game: its web panels too (no Rest API command for them)
                        Action { text: i18n.tr("Show / Hide Game UI (middle click)"); onTriggered: backend.camera.toggleGameUi() }
                        MenuSeparator {}
                        Action { text: i18n.tr("Show HUD"); onTriggered: backend.camera.setHudShown(true) }
                        Action { text: i18n.tr("Hide HUD"); onTriggered: backend.camera.setHudShown(false) }
                        MenuSeparator {}
                        HudAction { key: "chat"; text: i18n.tr("Chat") }
                        HudAction { key: "mfd"; text: i18n.tr("MFD") }
                        HudAction { key: "speedo"; text: i18n.tr("Car HUD") }
                        HudAction { key: "timing"; text: i18n.tr("Timing") }
                        HudAction { key: "trackMap"; text: i18n.tr("Track Map") }
                        onClosed: hudButton.forceActiveFocus()
                    }
                }
            }
            // Replay transport
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: theme.space1
                visible: backend.replayActive
                spacing: theme.space2
                TpSectionLabel {
                    Layout.fillWidth: true
                    text: i18n.tr("Replay")
                }
                TpButton { glyph: ""; fallback: "«"; text: "10 s"; flat: true; tip: i18n.tr("Back 10 seconds"); onClicked: backend.camera.jump(-10) }  // rewind
                TpButton {
                    readonly property bool moving: backend.camera.lastCommand !== "" && backend.camera.lastCommand !== "VCRCOMMAND_STOP"
                    accent: true
                    glyph: moving ? "" : ""  // pause, play
                    fallback: moving ? "II" : "▶"
                    tip: (moving ? i18n.tr("Pause replay") : i18n.tr("Play replay")) + " (" + i18n.tr("Space") + ")"
                    onClicked: backend.camera.togglePlay()
                }
                TpButton {
                    glyph: ""  // slow
                    fallback: "½×"
                    flat: true
                    checked: backend.camera.lastCommand === "VCRCOMMAND_SLOW"
                    tip: i18n.tr("Play slowly")
                    onClicked: backend.camera.playback("VCRCOMMAND_SLOW")
                }
                TpButton { glyph: ""; fallback: "»"; text: "10 s"; flat: true; tip: i18n.tr("Forward 10 seconds"); onClicked: backend.camera.jump(10) }  // fast forward
            }
        }
    }

    // Stories worth showing
    Card {
        Layout.fillWidth: true
        Layout.fillHeight: true
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: theme.space4
            spacing: theme.space3
            TpCardHeader {
                glyph: desk.mode === "auto" ? "" : ""  // lightning, list
                title: desk.mode === "auto" ? i18n.tr("Director Queue") : i18n.tr("Suggestions")
                tip: desk.mode !== "manual" ? i18n.tr("Keys 1 to 6 take the suggestion of that number") : ""
                TpButton {
                    objectName: "takeBestButton"
                    visible: desk.mode !== "manual"
                    accent: desk.mode === "assist"
                    size: "sm"
                    text: i18n.tr("Take Best")
                    tip: i18n.tr("Cut to the best story now (Enter)")
                    enabled: suggestions.count > 0
                    onClicked: backend.takeBest()
                }
            }
            Text {
                Layout.fillWidth: true
                visible: desk.mode === "manual"
                text: i18n.tr("Manual mode: you cut alone. Assisted mode lists stories worth showing, automatic mode cuts to them by itself.")
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.WordWrap
            }
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: desk.mode !== "manual"
                ListView {
                    id: suggestions
                    objectName: "suggestionList"
                    anchors.fill: parent
                    clip: true
                    spacing: theme.space2
                    model: backend.suggestionRows
                    boundsBehavior: Flickable.StopAtBounds
                    activeFocusOnTab: true
                    keyNavigationEnabled: true
                    highlightFollowsCurrentItem: false
                    displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
                    // Enter takes the suggestion of the list's current row (not the page's best one)
                    Keys.onShortcutOverride: function(event) {
                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                            event.accepted = true
                    }
                    Keys.onReturnPressed: if (currentItem) backend.takeSuggestion(currentItem.key)
                    Keys.onEnterPressed: if (currentItem) backend.takeSuggestion(currentItem.key)
                    onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
                    delegate: Item {
                        id: story
                        required property int index
                        required property string key
                        required property string kindText
                        required property string glyph
                        required property string tone
                        required property string title
                        required property string detail
                        required property string classColor
                        required property int score
                        required property bool best
                        readonly property color tint: theme.tone(tone)
                        readonly property bool current: ListView.isCurrentItem && suggestions.activeFocus
                        width: ListView.view.width
                        height: Math.round(theme.em * 3.0)
                        Accessible.role: Accessible.ListItem
                        Accessible.name: (story.index < 6 ? (story.index + 1) + ", " : "") + story.title + ", " + story.kindText
                        TpListRow {  // best story: own tint (the one Enter takes)
                            id: storyBack
                            anchors.fill: parent
                            hovered: storyArea.containsMouse
                            emphasized: story.best
                            tint: story.tint
                            border.width: 1
                            border.color: story.best ? story.tint : theme.border
                        }
                        FocusRing { target: storyBack; visible: story.current }
                        MouseArea {
                            id: storyArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.takeSuggestion(story.key)
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: theme.em * 0.5
                            anchors.rightMargin: theme.em * 0.5
                            spacing: theme.em * 0.5
                            Rectangle {  // key of this suggestion (1 to 6)
                                visible: story.index < 6
                                Layout.preferredWidth: Math.round(theme.em * 1.3)
                                Layout.preferredHeight: Layout.preferredWidth
                                radius: theme.radiusSm
                                color: "transparent"
                                border.width: 1
                                border.color: theme.border
                                Text {
                                    anchors.centerIn: parent
                                    text: story.index + 1
                                    color: theme.dimOn(storyBack.color)
                                    font.pointSize: theme.fontCaption
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                            Icon { glyph: story.glyph; color: story.tint }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Text {
                                    Layout.fillWidth: true
                                    text: story.title
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: story.kindText + (story.detail !== "" ? "  ·  " + story.detail : "")
                                    color: theme.dimOn(storyBack.color)
                                    font.pointSize: theme.fontCaption
                                    elide: Text.ElideRight
                                }
                            }
                            TpMeter {  // score
                                Layout.preferredWidth: theme.em * 2.6
                                value: Math.min(story.score, 100) / 100
                                tint: story.tint
                                thickness: Math.round(theme.em * 0.4)
                                name: i18n.tr("Score")
                            }
                            Icon { glyph: ""; fallback: "◎"; color: storyArea.containsMouse ? theme.accent : theme.dimOn(storyBack.color); size: theme.em * 0.9 }  // camera
                        }
                    }
                }
                EmptyState {
                    anchors.centerIn: parent
                    width: parent.width - theme.em * 2
                    visible: suggestions.count === 0
                    compact: true
                    glyph: ""  // pulse
                    title: i18n.tr("Quiet on track")
                    text: i18n.tr("Battles, overtakes, contacts and pit stops show up here as they happen.")
                }
            }
        }
    }
}
