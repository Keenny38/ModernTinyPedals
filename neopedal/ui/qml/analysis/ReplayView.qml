import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"
import "../director"
import "../telemetry"

// Game replay & live session (LMU), replay tab of results & replays page: game state, playback of the replay
// open in game, camera & HUD, incidents of the session on a timeline & in a list (jump to one: replay goes there,
// camera on a car), standings & track map. Space: play / pause. Game state & requests: "replays" context property.
// Transport buttons are reached with Tab (Space / Enter), shown as text without the icon font.
Item {
    id: page

    readonly property string gameState: replays.gameState
    // Replay clock of last game answer, read once per answer (clock timers tick between answers)
    readonly property real replayTime: replays.replayTime
    readonly property real replayRate: replays.replayRate
    readonly property real timeReceived: replays.timeReceived
    readonly property real liveTime: replays.liveTime

    // Game state: replay open (accent), live session (one Live color for every page), menu, offline
    function stateColor(name) {
        return name === "replay" ? theme.accent : name === "session" ? theme.live : name === "menu" ? theme.warning : theme.loss
    }

    // Text being typed (search, seconds before): Space is a character, not play / pause
    readonly property bool typing: Window.activeFocusItem !== null && Window.activeFocusItem.cursorPosition !== undefined
    Shortcut {
        sequence: "Space"
        enabled: pageState.active && page.visible && replays.replayActive && !page.typing  // hidden page: not its keys
        onActivated: replays.togglePlay()
    }

    // Camera menu as in game: section titles (groups) then cameras of group (list constant: built once)
    readonly property var cameraEntries: {
        var result = [], group = "", cameras = replays.cameras
        for (var i = 0; i < cameras.length; i++) {
            if (cameras[i].group !== group) {
                group = cameras[i].group
                result.push({ "header": true, "key": "", "text": i18n.tr(group) })
            }
            result.push({ "header": false, "key": cameras[i].key, "text": cameras[i].text })
        }
        return result
    }

    // HUD part of game shown or hidden: check follows game (menu item kept, not rebuilt while open)
    component HudAction: Action {
        property string key: ""
        objectName: "hud_" + key
        checkable: true
        enabled: replays.hudState[key] !== undefined
        checked: replays.hudState[key] === true
        onTriggered: {
            replays.toggleHudComponent(key)
            // click toggled checked by itself: state of game shown again (also when the toggle was refused)
            checked = Qt.binding(function() { return replays.hudState[key] === true })
        }
    }

    // Round transport button: glyph (rotated for backwards; fallback text without icon font), highlighted while
    // its command is the last sent. Tab reaches it, Space / Enter press it.
    component TransportButton: AbstractButton {
        id: control
        property string glyph: ""
        property string fallback: ""
        property real glyphRotation: 0
        property bool primary: false
        property string command: ""
        property string tip: ""
        property string caption: ""  // speed shown on glyph (slow: ½)
        readonly property bool current: command !== "" && replays.lastCommand === command
        Accessible.role: Accessible.Button
        Accessible.name: tip
        hoverEnabled: true
        focusPolicy: Qt.TabFocus
        implicitWidth: Math.round(theme.em * (primary ? 3.3 : 2.6))
        implicitHeight: implicitWidth
        opacity: enabled ? 1 : theme.disabledOpacity
        scale: down ? 0.92 : 1
        Behavior on scale { NumberAnimation { duration: theme.motionFast } }
        Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
        onClicked: if (command !== "") replays.playback(command)
        Keys.onReturnPressed: animateClick()
        Keys.onEnterPressed: animateClick()
        Keys.onShortcutOverride: function(event) {  // focused: Space presses it (not the page play / pause)
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
                event.accepted = true
        }
        ToolTip.visible: tip !== "" && (hovered || visualFocus)
        ToolTip.text: tip
        ToolTip.delay: theme.tipDelay
        background: Rectangle {
            radius: width / 2
            color: control.primary ? (control.down ? Qt.darker(theme.accentFill, 1.15) : control.hovered ? Qt.darker(theme.accentFill, 1.07) : theme.accentFill)
                 : control.current ? theme.tint(theme.accent, "selected")
                 : control.down ? theme.border : control.hovered ? theme.hover : "transparent"
            border.width: control.primary || control.current ? 0 : 1
            border.color: theme.border
            Behavior on color { ColorAnimation { duration: theme.motionFast } }
            FocusRing { visible: control.visualFocus }
        }
        contentItem: Item {
            Icon {
                anchors.centerIn: parent
                glyph: control.glyph
                fallback: control.fallback
                rotation: iconShown ? control.glyphRotation : 0
                size: theme.em * (control.primary ? 1.35 : 1.0)
                color: control.primary ? "white" : control.current ? theme.accent : theme.text
            }
            Text {
                visible: control.caption !== ""
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.rightMargin: theme.em * 0.1
                text: control.caption
                color: control.current ? theme.accent : theme.dimText
                font.pointSize: theme.fontTiny
                font.weight: Font.Bold
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.space4

        // Header: game state, last answer, actions
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space4
            Rectangle {
                id: statePill
                readonly property color tone: page.stateColor(page.gameState)
                Layout.maximumWidth: page.width * 0.6
                implicitHeight: Math.round(theme.controlHeight)
                implicitWidth: stateText.implicitWidth + theme.em * 2.6
                radius: height / 2
                color: theme.tint(tone, "subtle")
                border.width: 1
                border.color: theme.tint(tone, 0.4)
                Behavior on color { ColorAnimation { duration: theme.motionSlow } }
                Accessible.role: Accessible.StaticText
                Accessible.name: replays.statusText
                ToolTip.visible: stateArea.containsMouse && stateText.truncated
                ToolTip.text: replays.statusText
                ToolTip.delay: theme.tipDelay
                MouseArea { id: stateArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                TpPulseDot {
                    id: stateDot
                    x: theme.em * 0.8
                    anchors.verticalCenter: parent.verticalCenter
                    color: statePill.tone
                    pulsing: page.gameState === "replay"  // replay open: pulse
                }
                Text {
                    id: stateText
                    anchors.left: stateDot.right
                    anchors.leftMargin: theme.em * 0.5
                    anchors.right: parent.right
                    anchors.rightMargin: theme.padCard
                    anchors.verticalCenter: parent.verticalCenter
                    text: replays.statusText
                    color: theme.text
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.preferredWidth: implicitWidth
                Layout.minimumWidth: theme.em * 4
                text: replays.updatedText
                color: theme.dimText
                font.pointSize: theme.fontLabel
                elide: Text.ElideRight
            }
            TpToolbar {  // texts while they fit, then icons only, then "⋯"
                objectName: "replayToolbar"
                Layout.fillWidth: true
                TpAction {
                    name: "openFolderButton"
                    text: i18n.tr("Open Folder")
                    glyph: ""  // open folder
                    tip: replays.replayFolder !== "" ? replays.replayFolder : i18n.tr("Replay folder of the game, known once the game lists its replays")
                    priority: 1
                    enabled: replays.replayFolder !== ""
                    onTriggered: replays.openFolder()
                }
                TpAction {
                    name: "refreshButton"
                    text: i18n.tr("Refresh")
                    glyph: ""  // refresh
                    fallback: "⟳"
                    tip: i18n.tr("Ask game again (F5)")
                    priority: 2
                    pinned: true
                    onTriggered: replays.refresh()
                }
            }
        }

        // Playback of the replay open in game
        Card {
            Layout.fillWidth: true
            implicitHeight: playbackColumn.implicitHeight + theme.padCard * 2
            ColumnLayout {
                id: playbackColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.padCard }
                spacing: theme.space3

                TpCardHeader {
                    glyph: ""  // play
                    title: i18n.tr("Replay Playback")
                    Pill {  // replay speed measured between game answers (game shows 1x, 2x...)
                        readonly property real rate: replays.replayRate
                        visible: replayClock.visible && Math.abs(rate) > 0.02
                        tint: theme.dimText
                        text: (rate < 0 ? "-" : "") + (Math.abs(rate) >= 1.5 ? Math.round(Math.abs(rate))
                              : (Math.round(Math.abs(rate) * 4) / 4).toString().replace(".", theme.decimalPoint)) + "x"
                    }
                    Row {  // live session: session time (as game shows "EN DIRECT")
                        id: liveClock
                        visible: replays.inSession && !replays.replayActive && replays.liveTime >= 0
                        spacing: theme.space3
                        TpPulseDot {
                            id: liveClockDot
                            width: theme.em * 0.55
                            color: theme.live
                            anchors.verticalCenter: parent.verticalCenter
                            pulsing: liveClock.visible
                            low: 0.3
                            pulseDuration: 800
                            pulseEasing: Easing.Linear
                        }
                        Text {
                            text: i18n.tr("Live").toUpperCase()
                            color: theme.live
                            font.weight: Font.Bold
                            font.pointSize: theme.fontSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: liveTicker.format(liveTicker.now)
                            color: theme.text
                            font.pointSize: theme.fontHeading
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        LiveClock {
                            id: liveTicker
                            time: page.liveTime
                            received: page.timeReceived
                            maxGap: 10
                            interval: 500
                            triggeredOnStart: true
                            active: liveClock.visible && pageState.active  // stopped while page hidden
                        }
                    }
                    Text {  // replay time, moves between game answers at measured rate
                        id: replayClock
                        visible: replays.replayActive && replays.replayTime >= 0
                        text: replayTicker.format(replayTicker.now)
                        color: theme.accent
                        font.pointSize: theme.fontHeading
                        font.weight: Font.DemiBold
                        font.features: { "tnum": 1 }
                        LiveClock {
                            id: replayTicker
                            time: page.replayTime
                            received: page.timeReceived
                            rate: page.replayRate
                            triggeredOnStart: true
                            active: replayClock.visible && pageState.active
                        }
                    }
                }

                // Transport: rewind, backwards, play / pause, slow, fast forward, other speeds
                Row {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: theme.em * 0.5
                    enabled: replays.replayActive
                    TransportButton {
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: ""; fallback: "«"; command: "VCRCOMMAND_REVERSESCAN"; tip: i18n.tr("Rewind")
                    }
                    TransportButton {
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: ""; fallback: "◀"; glyphRotation: 180; command: "VCRCOMMAND_PLAYBACKWARDS"; tip: i18n.tr("Play backwards")
                    }
                    TransportButton {
                        readonly property bool moving: replays.lastCommand !== "" && replays.lastCommand !== "VCRCOMMAND_STOP"
                        anchors.verticalCenter: parent.verticalCenter
                        primary: true
                        glyph: moving ? "" : ""  // pause, play
                        fallback: moving ? "❚❚" : "▶"
                        tip: (moving ? i18n.tr("Pause replay") : i18n.tr("Play replay")) + " (" + i18n.tr("Space") + ")"
                        onClicked: replays.togglePlay()
                    }
                    TransportButton {
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: ""; fallback: "▷"; caption: "½"; command: "VCRCOMMAND_SLOW"; tip: i18n.tr("Play slowly")
                    }
                    TransportButton {
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: ""; fallback: "»"; command: "VCRCOMMAND_FORWARDSCAN"; tip: i18n.tr("Play fast")
                    }
                    TransportButton {
                        id: speedsButton
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: ""  // more
                        fallback: "⋯"
                        tip: i18n.tr("Other speeds")
                        onClicked: speedsMenu.visible ? speedsMenu.close() : speedsMenu.popup(speedsButton, 0, speedsButton.height + 4)
                        TpMenu {
                            id: speedsMenu
                            Instantiator {
                                model: replays.playbackModes
                                delegate: Action {
                                    required property var modelData
                                    text: modelData.text
                                    checkable: true
                                    checked: replays.lastCommand === modelData.command
                                    onTriggered: replays.playback(modelData.command)
                                }
                                onObjectAdded: function(index, object) { speedsMenu.insertAction(index, object) }
                                onObjectRemoved: function(index, object) { speedsMenu.removeAction(object) }
                            }
                        }
                    }
                }
                // Lap of car followed by camera (previous / next lap start), back to live
                Row {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: theme.em * 0.5
                    visible: lapNavigator.visible || liveButton.visible
                    Row {
                        id: lapNavigator
                        visible: replays.replayActive && replays.cameraLap > 0
                        spacing: theme.space1
                        anchors.verticalCenter: parent.verticalCenter
                        TpButton {
                            glyph: ""  // chevron left
                            fallback: "‹"
                            flat: true
                            size: "sm"
                            tip: i18n.tr("Previous lap of the car followed by the camera")
                            enabled: replays.cameraLap > 1
                            onClicked: replays.stepLap(-1)
                        }
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            implicitHeight: Math.round(theme.controlHeightSm)
                            implicitWidth: lapText.implicitWidth + theme.em * 1.4
                            radius: theme.radiusMd
                            color: "transparent"
                            border.width: 1
                            border.color: theme.border
                            Text {
                                id: lapText
                                anchors.centerIn: parent
                                text: i18n.tr("Lap") + " " + replays.cameraLap
                                color: theme.text
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                        }
                        TpButton {
                            glyph: ""  // chevron right
                            fallback: "›"
                            flat: true
                            size: "sm"
                            tip: i18n.tr("Next lap of the car followed by the camera")
                            onClicked: replays.stepLap(1)
                        }
                    }
                    TpButton {  // replay of live session opened from page
                        id: liveButton
                        anchors.verticalCenter: parent.verticalCenter
                        visible: replays.canGoLive
                        accent: true
                        text: i18n.tr("Back to Live")
                        tip: i18n.tr("Leave the replay of this session, back to the live session")
                        onClicked: replays.backToLive()
                    }
                }

                // Car followed by camera (session or replay)
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.space3
                    enabled: replays.inSession
                    TpButton { glyph: ""; fallback: "‹"; flat: true; tip: i18n.tr("Camera on previous car"); onClicked: replays.focusCar(-1) }  // chevron left
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Math.round(theme.em * 2.1)
                        radius: theme.radiusMd
                        color: theme.dark ? Qt.darker(theme.base, 1.2) : Qt.darker(theme.window, 1.03)
                        border.width: 1
                        border.color: theme.border
                        opacity: parent.enabled ? 1 : theme.disabledOpacity
                        Row {
                            anchors.centerIn: parent
                            width: Math.min(implicitWidth, parent.width - theme.em)
                            spacing: theme.em * 0.5
                            Icon { glyph: ""; color: theme.dimText; size: theme.em * 0.9; anchors.verticalCenter: parent.verticalCenter }  // camera
                            Text {
                                width: Math.min(implicitWidth, parent.parent.width - theme.em * 2.6)
                                text: replays.focusedDriver !== "" ? replays.focusedDriver : i18n.tr("Camera car")
                                color: replays.focusedDriver !== "" ? theme.text : theme.dimText
                                font.weight: replays.focusedDriver !== "" ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                    TpButton { glyph: ""; fallback: "›"; flat: true; tip: i18n.tr("Camera on next car"); onClicked: replays.focusCar(1) }  // chevron right
                }

                // Camera of game: menu of game cameras, previous / next angle of group shown
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.space3
                    enabled: replays.inSession
                    readonly property string group: replays.cameraGroup !== "" ? replays.cameraGroup : "Driving"
                    TpButton {
                        glyph: ""  // chevron left
                        fallback: "‹"
                        flat: true
                        tip: i18n.tr("Previous camera angle")
                        onClicked: replays.setCamera(parent.group, -1)
                    }
                    TpButton {  // camera menu of game: driving, onboard & trackside cameras
                        id: cameraButton
                        objectName: "cameraButton"
                        Layout.fillWidth: true
                        glyph: ""  // camera
                        text: replays.cameraLabel !== "" ? replays.cameraLabel : i18n.tr("Change Camera")
                        tip: i18n.tr("Change Camera")
                        checked: cameraMenu.visible
                        onClicked: cameraMenu.visible ? cameraMenu.close()
                                                      : cameraMenu.popup(cameraButton, 0, cameraButton.height + 4)
                        TpMenu {
                            id: cameraMenu
                            objectName: "cameraMenu"
                            width: Math.max(implicitWidth, cameraButton.width, theme.em * 16)
                            Instantiator {
                                model: page.cameraEntries
                                delegate: Action {
                                    required property var modelData
                                    objectName: modelData.header ? "" : "camera_" + modelData.key
                                    text: modelData.header ? modelData.text.toUpperCase() : modelData.text
                                    enabled: !modelData.header
                                    checkable: !modelData.header
                                    checked: replays.cameraKey === modelData.key && modelData.key !== ""
                                    onTriggered: {
                                        replays.selectCamera(modelData.key)
                                        // click toggled checked (current camera: unchecked): camera of game shown again
                                        checked = Qt.binding(function() {
                                            return replays.cameraKey === modelData.key && modelData.key !== ""
                                        })
                                    }
                                }
                                onObjectAdded: function(index, object) { cameraMenu.insertAction(index, object) }
                                onObjectRemoved: function(index, object) { cameraMenu.removeAction(object) }
                            }
                        }
                    }
                    TpButton {
                        glyph: ""  // chevron right
                        fallback: "›"
                        flat: true
                        tip: i18n.tr("Next camera angle")
                        onClicked: replays.setCamera(parent.group, 1)
                    }
                    TpButton {  // HUD of game: all or each part, clean pictures & videos
                        id: hudButton
                        objectName: "hudButton"
                        glyph: ""  // view
                        fallback: "HUD"
                        tip: i18n.tr("Game HUD")
                        checked: hudMenu.visible
                        // Menu right aligned on button (page edge): never cut by window
                        onClicked: hudMenu.visible ? hudMenu.close()
                                                   : hudMenu.popup(hudButton, hudButton.width - hudMenu.width, hudButton.height + 4)
                        TpMenu {
                            id: hudMenu
                            width: Math.max(implicitWidth, theme.em * 20)
                            // As a middle click in game: its web panels too (no Rest API command for them)
                            Action { text: i18n.tr("Show / Hide Game UI (middle click)"); onTriggered: replays.toggleGameUi() }
                            MenuSeparator {}
                            Action { text: i18n.tr("Show HUD"); onTriggered: replays.setHudShown(true) }
                            Action { text: i18n.tr("Hide HUD"); onTriggered: replays.setHudShown(false) }
                            MenuSeparator {}
                            HudAction { key: "chat"; text: i18n.tr("Chat") }
                            HudAction { key: "mfd"; text: i18n.tr("MFD") }
                            HudAction { key: "speedo"; text: i18n.tr("Car HUD") }
                            HudAction { key: "timing"; text: i18n.tr("Timing") }
                            HudAction { key: "trackMap"; text: i18n.tr("Track Map") }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: !replays.replayActive
                    text: page.gameState === "offline" ? i18n.tr("Start LMU: replays, playback & incidents come from the game.")
                        : page.gameState === "menu" ? i18n.tr("Watch a replay from the list to control it from here.")
                        : i18n.tr("Open the replay of this session in the game, or watch one from the list.")
                    color: theme.dimText
                    font.pointSize: theme.fontLabel
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        // Incidents or standings of the session
        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ColumnLayout {
                anchors.fill: parent
                spacing: theme.space3
                TpSegmented {
                    Layout.topMargin: theme.padCard
                    Layout.leftMargin: theme.padCard
                    name: i18n.tr("Replay")
                    options: [i18n.tr("Incidents") + (replays.incidentCount > 0 ? "  " + replays.incidentCount : ""),
                              i18n.tr("Drivers") + (replays.carCount > 0 ? "  " + replays.carCount : ""),
                              i18n.tr("Map")]
                    currentIndex: replays.panelIndex
                    onActivated: function(index) { replays.setPanel(index) }
                }
                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: replays.panelIndex
                    // Panels built when first shown, then kept
                    Loader {
                        active: replays.panelIndex === 0 || item !== null
                        sourceComponent: IncidentPanel {}
                    }
                    Loader {
                        active: replays.panelIndex === 1 || item !== null
                        sourceComponent: StandingsPanel {}
                    }
                    Loader {
                        active: replays.panelIndex === 2 || item !== null
                        sourceComponent: MapPanel {}
                    }
                }
            }
        }
    }
}
