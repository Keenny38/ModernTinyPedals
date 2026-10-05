import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Game replays page (LMU): replays saved by the game (watch one in game), playback of the replay open in game,
// incidents of the session on a timeline & in a list (jump to one: replay goes there, camera on a car).
// Space: play / pause, F5: ask game again.
TpPage {
    id: page

    readonly property string gameState: backend.gameState
    readonly property bool wide: width > theme.em * 64

    function stateColor(name) {
        return name === "replay" ? theme.accent : name === "session" ? theme.gain : name === "menu" ? theme.warning : theme.loss
    }
    function clock(seconds) {
        var total = Math.max(Math.floor(seconds), 0)
        var hours = Math.floor(total / 3600), minutes = Math.floor(total / 60) % 60, rest = total % 60
        return hours + ":" + (minutes < 10 ? "0" : "") + minutes + ":" + (rest < 10 ? "0" : "") + rest
    }

    // Text being typed (search, seconds before): Space is a character, not play / pause
    readonly property bool typing: Window.activeFocusItem !== null && Window.activeFocusItem.cursorPosition !== undefined
    Shortcut {
        sequence: "Space"
        enabled: backend.replayActive && !page.typing
        onActivated: backend.togglePlay()
    }
    Shortcut { sequences: [StandardKey.Refresh]; onActivated: backend.refresh() }

    // Camera menu as in game: section titles (groups) then cameras of group (list constant: built once)
    readonly property var cameraEntries: {
        var result = [], group = "", cameras = backend.cameras
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
        enabled: backend.hudState[key] !== undefined
        onTriggered: backend.toggleHudComponent(key)
        Binding on checked { value: backend.hudState[key] === true }
    }

    // Round transport button: glyph (rotated for backwards), highlighted while its command is the last sent
    component TransportButton: AbstractButton {
        id: control
        property string glyph: ""
        property real glyphRotation: 0
        property bool primary: false
        property string command: ""
        property string tip: ""
        property string caption: ""  // speed shown on glyph (slow: ½)
        readonly property bool current: command !== "" && backend.lastCommand === command
        Accessible.role: Accessible.Button
        Accessible.name: tip
        hoverEnabled: true
        focusPolicy: Qt.NoFocus
        implicitWidth: Math.round(theme.em * (primary ? 3.3 : 2.6))
        implicitHeight: implicitWidth
        opacity: enabled ? 1 : 0.4
        scale: down ? 0.92 : 1
        Behavior on scale { NumberAnimation { duration: 90 } }
        Behavior on opacity { NumberAnimation { duration: 150 } }
        onClicked: if (command !== "") backend.playback(command)
        ToolTip.visible: tip !== "" && hovered
        ToolTip.text: tip
        ToolTip.delay: 600
        background: Rectangle {
            radius: width / 2
            color: control.primary ? (control.down ? Qt.darker(theme.accent, 1.15) : control.hovered ? Qt.lighter(theme.accent, 1.08) : theme.accent)
                 : control.current ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.18)
                 : control.down ? theme.border : control.hovered ? theme.hover : "transparent"
            border.width: control.primary || control.current ? 0 : 1
            border.color: theme.border
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        contentItem: Item {
            Icon {
                anchors.centerIn: parent
                glyph: control.glyph
                rotation: control.glyphRotation
                size: theme.em * (control.primary ? 1.35 : 1.0)
                color: control.primary ? "white" : control.current ? theme.accent : theme.text
            }
            Text {
                visible: control.caption !== ""
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.rightMargin: theme.em * 0.12
                text: control.caption
                color: control.current ? theme.accent : theme.dimText
                font.pointSize: theme.fontPoint * 0.72
                font.weight: Font.Bold
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Header: game state, last answer, actions
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            Rectangle {
                id: statePill
                readonly property color tone: page.stateColor(page.gameState)
                Layout.maximumWidth: page.width * 0.6
                implicitHeight: Math.round(theme.em * 2.3)
                implicitWidth: stateText.implicitWidth + theme.em * 2.6
                radius: height / 2
                color: Qt.rgba(tone.r, tone.g, tone.b, 0.12)
                border.width: 1
                border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.4)
                Behavior on color { ColorAnimation { duration: 250 } }
                ToolTip.visible: stateArea.containsMouse && stateText.truncated
                ToolTip.text: backend.statusText
                MouseArea { id: stateArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                Rectangle {
                    id: stateDot
                    x: theme.em * 0.8
                    anchors.verticalCenter: parent.verticalCenter
                    width: theme.em * 0.6
                    height: width
                    radius: width / 2
                    color: statePill.tone
                    SequentialAnimation on opacity {  // replay open: pulse
                        running: page.gameState === "replay"
                        loops: Animation.Infinite
                        onRunningChanged: if (!running) stateDot.opacity = 1
                        NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    id: stateText
                    anchors.left: stateDot.right
                    anchors.leftMargin: theme.em * 0.5
                    anchors.right: parent.right
                    anchors.rightMargin: theme.em * 0.7
                    anchors.verticalCenter: parent.verticalCenter
                    text: backend.statusText
                    color: theme.text
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
            }
            Text {
                Layout.fillWidth: true
                text: backend.updatedText
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.9
                elide: Text.ElideRight
            }
            TpButton {
                glyph: ""  // open folder
                text: page.wide ? i18n.tr("Open Folder") : ""
                tip: backend.folder !== "" ? backend.folder : i18n.tr("Replay folder of the game, known once the game lists its replays")
                enabled: backend.folder !== ""
                onClicked: backend.openFolder()
            }
            TpButton {
                glyph: ""  // refresh
                text: page.wide ? i18n.tr("Refresh") : ""
                tip: i18n.tr("Ask game again (F5)")
                onClicked: backend.refresh()
            }
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.wide ? 2 : 1
            columnSpacing: theme.em * 0.6
            rowSpacing: theme.em * 0.6

            // Replays saved by the game
            Card {
                Layout.fillWidth: true
                Layout.fillHeight: page.wide  // narrow: one column, incidents below get the rest
                Layout.preferredWidth: page.wide ? page.width * 0.55 : -1
                Layout.preferredHeight: page.wide ? -1 : page.height * 0.38
                ReplayList { id: replayList; anchors.fill: parent }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: page.wide ? page.width * 0.45 : -1
                Layout.minimumWidth: page.wide ? theme.em * 26 : 0
                spacing: theme.em * 0.6

                // Playback of the replay open in game
                Card {
                    Layout.fillWidth: true
                    implicitHeight: playbackColumn.implicitHeight + theme.em * 1.4
                    ColumnLayout {
                        id: playbackColumn
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.7 }
                        spacing: theme.em * 0.5

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.5
                            Icon { glyph: ""; color: theme.accent }  // play
                            Text {
                                text: i18n.tr("Replay Playback")
                                color: theme.text
                                font.weight: Font.DemiBold
                                font.pointSize: theme.fontPoint * 1.1
                            }
                            Item { Layout.fillWidth: true }
                            Rectangle {  // replay speed measured between game answers (game shows 1x, 2x...)
                                visible: replayClock.visible && Math.abs(backend.replayRate) > 0.02
                                implicitHeight: speedText.implicitHeight + 4
                                implicitWidth: speedText.implicitWidth + theme.em * 0.8
                                radius: height / 2
                                color: theme.hover
                                Text {
                                    id: speedText
                                    anchors.centerIn: parent
                                    readonly property real rate: backend.replayRate
                                    text: (rate < 0 ? "-" : "") + (Math.abs(rate) >= 1.5 ? Math.round(Math.abs(rate))
                                          : (Math.round(Math.abs(rate) * 4) / 4).toString().replace(".", theme.decimalPoint)) + "x"
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.85
                                    font.features: { "tnum": 1 }
                                }
                            }
                            Row {  // live session: session time (as game shows "EN DIRECT")
                                id: liveClock
                                visible: backend.inSession && !backend.replayActive && backend.liveTime >= 0
                                spacing: theme.em * 0.4
                                property real now: backend.liveTime
                                Rectangle {
                                    width: theme.em * 0.55
                                    height: width
                                    radius: width / 2
                                    color: theme.loss
                                    anchors.verticalCenter: parent.verticalCenter
                                    SequentialAnimation on opacity {
                                        running: liveClock.visible
                                        loops: Animation.Infinite
                                        NumberAnimation { to: 0.3; duration: 800 }
                                        NumberAnimation { to: 1; duration: 800 }
                                    }
                                }
                                Text {
                                    text: i18n.tr("Live").toUpperCase()
                                    color: theme.loss
                                    font.weight: Font.Bold
                                    font.pointSize: theme.fontPoint * 0.85
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: page.clock(liveClock.now)
                                    color: theme.text
                                    font.pointSize: theme.fontPoint * 1.25
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Timer {
                                    interval: 500
                                    repeat: true
                                    running: liveClock.visible
                                    onTriggered: liveClock.now = backend.liveTime
                                                 + Math.min(Math.max((Date.now() - backend.timeReceived) / 1000, 0), 10)
                                }
                                Connections {
                                    target: backend
                                    function onReplayTimeChanged() { liveClock.now = backend.liveTime }
                                }
                            }
                            Text {  // replay time, moves between game answers at measured rate
                                id: replayClock
                                visible: backend.replayActive && backend.replayTime >= 0
                                property real now: backend.replayTime
                                text: page.clock(now)
                                color: theme.accent
                                font.pointSize: theme.fontPoint * 1.25
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                                Timer {
                                    interval: 250
                                    repeat: true
                                    running: replayClock.visible && backend.replayRate !== 0
                                    onTriggered: replayClock.now = backend.replayTime + backend.replayRate
                                                 * Math.min(Math.max((Date.now() - backend.timeReceived) / 1000, 0), 3)
                                }
                                Connections {
                                    target: backend
                                    function onReplayTimeChanged() { replayClock.now = backend.replayTime }
                                }
                            }
                        }

                        // Transport: rewind, backwards, play / pause, slow, fast forward, other speeds
                        Row {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: theme.em * 0.5
                            enabled: backend.replayActive
                            TransportButton {
                                anchors.verticalCenter: parent.verticalCenter
                                glyph: ""; command: "VCRCOMMAND_REVERSESCAN"; tip: i18n.tr("Rewind")
                            }
                            TransportButton {
                                anchors.verticalCenter: parent.verticalCenter
                                glyph: ""; glyphRotation: 180; command: "VCRCOMMAND_PLAYBACKWARDS"; tip: i18n.tr("Play backwards")
                            }
                            TransportButton {
                                readonly property bool moving: backend.lastCommand !== "" && backend.lastCommand !== "VCRCOMMAND_STOP"
                                anchors.verticalCenter: parent.verticalCenter
                                primary: true
                                glyph: moving ? "" : ""  // pause, play
                                tip: (moving ? i18n.tr("Pause replay") : i18n.tr("Play replay")) + " (" + i18n.tr("Space") + ")"
                                onClicked: backend.togglePlay()
                            }
                            TransportButton {
                                anchors.verticalCenter: parent.verticalCenter
                                glyph: ""; caption: "½"; command: "VCRCOMMAND_SLOW"; tip: i18n.tr("Play slowly")
                            }
                            TransportButton {
                                anchors.verticalCenter: parent.verticalCenter
                                glyph: ""; command: "VCRCOMMAND_FORWARDSCAN"; tip: i18n.tr("Play fast")
                            }
                            TransportButton {
                                id: speedsButton
                                anchors.verticalCenter: parent.verticalCenter
                                glyph: ""  // more
                                tip: i18n.tr("Other speeds")
                                onClicked: speedsMenu.visible ? speedsMenu.close() : speedsMenu.popup(speedsButton, 0, speedsButton.height + 4)
                                TpMenu {
                                    id: speedsMenu
                                    Instantiator {
                                        model: backend.playbackModes
                                        delegate: Action {
                                            required property var modelData
                                            text: modelData.text
                                            checkable: true
                                            checked: backend.lastCommand === modelData.command
                                            onTriggered: backend.playback(modelData.command)
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
                                visible: backend.replayActive && backend.cameraLap > 0
                                spacing: theme.em * 0.2
                                anchors.verticalCenter: parent.verticalCenter
                                TpButton {
                                    glyph: ""  // chevron left
                                    flat: true
                                    implicitHeight: Math.round(theme.em * 2.0)
                                    tip: i18n.tr("Previous lap of the car followed by the camera")
                                    enabled: backend.cameraLap > 1
                                    onClicked: backend.stepLap(-1)
                                }
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    implicitHeight: Math.round(theme.em * 2.0)
                                    implicitWidth: lapText.implicitWidth + theme.em * 1.4
                                    radius: theme.em * 0.45
                                    color: "transparent"
                                    border.width: 1
                                    border.color: theme.border
                                    Text {
                                        id: lapText
                                        anchors.centerIn: parent
                                        text: i18n.tr("Lap") + " " + backend.cameraLap
                                        color: theme.text
                                        font.weight: Font.DemiBold
                                        font.features: { "tnum": 1 }
                                    }
                                }
                                TpButton {
                                    glyph: ""  // chevron right
                                    flat: true
                                    implicitHeight: Math.round(theme.em * 2.0)
                                    tip: i18n.tr("Next lap of the car followed by the camera")
                                    onClicked: backend.stepLap(1)
                                }
                            }
                            TpButton {  // replay of live session opened from page
                                id: liveButton
                                anchors.verticalCenter: parent.verticalCenter
                                visible: backend.canGoLive
                                accent: true
                                text: i18n.tr("Back to Live")
                                tip: i18n.tr("Leave the replay of this session, back to the live session")
                                onClicked: backend.backToLive()
                            }
                        }

                        // Car followed by camera (session or replay)
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.4
                            enabled: backend.inSession
                            opacity: enabled ? 1 : 0.45
                            TpButton { glyph: ""; flat: true; tip: i18n.tr("Camera on previous car"); onClicked: backend.focusCar(-1) }  // chevron left
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: Math.round(theme.em * 2.1)
                                radius: theme.em * 0.5
                                color: theme.dark ? Qt.darker(theme.base, 1.2) : Qt.darker(theme.window, 1.03)
                                border.width: 1
                                border.color: theme.border
                                Row {
                                    anchors.centerIn: parent
                                    width: Math.min(implicitWidth, parent.width - theme.em)
                                    spacing: theme.em * 0.45
                                    Icon { glyph: ""; color: theme.dimText; size: theme.em * 0.9; anchors.verticalCenter: parent.verticalCenter }  // camera
                                    Text {
                                        width: Math.min(implicitWidth, parent.parent.width - theme.em * 2.6)
                                        text: backend.focusedDriver !== "" ? backend.focusedDriver : i18n.tr("Camera car")
                                        color: backend.focusedDriver !== "" ? theme.text : theme.dimText
                                        font.weight: backend.focusedDriver !== "" ? Font.DemiBold : Font.Normal
                                        elide: Text.ElideRight
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                }
                            }
                            TpButton { glyph: ""; flat: true; tip: i18n.tr("Camera on next car"); onClicked: backend.focusCar(1) }  // chevron right
                        }

                        // Camera of game: menu of game cameras, previous / next angle of group shown
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.4
                            enabled: backend.inSession
                            opacity: enabled ? 1 : 0.45
                            readonly property string group: backend.cameraGroup !== "" ? backend.cameraGroup : "Driving"
                            TpButton {
                                glyph: ""  // chevron left
                                flat: true
                                tip: i18n.tr("Previous camera angle")
                                onClicked: backend.setCamera(parent.group, -1)
                            }
                            TpButton {  // camera menu of game: driving, onboard & trackside cameras
                                id: cameraButton
                                objectName: "cameraButton"
                                Layout.fillWidth: true
                                glyph: ""  // camera
                                text: backend.cameraLabel !== "" ? backend.cameraLabel : i18n.tr("Change Camera")
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
                                            onTriggered: backend.selectCamera(modelData.key)
                                            Binding on checked { value: backend.cameraKey === modelData.key && modelData.key !== "" }
                                        }
                                        onObjectAdded: function(index, object) { cameraMenu.insertAction(index, object) }
                                        onObjectRemoved: function(index, object) { cameraMenu.removeAction(object) }
                                    }
                                }
                            }
                            TpButton {
                                glyph: ""  // chevron right
                                flat: true
                                tip: i18n.tr("Next camera angle")
                                onClicked: backend.setCamera(parent.group, 1)
                            }
                            TpButton {  // HUD of game: all or each part, clean pictures & videos
                                id: hudButton
                                objectName: "hudButton"
                                glyph: ""  // view
                                tip: i18n.tr("Game HUD")
                                checked: hudMenu.visible
                                // Menu right aligned on button (page edge): never cut by window
                                onClicked: hudMenu.visible ? hudMenu.close()
                                                           : hudMenu.popup(hudButton, hudButton.width - hudMenu.width, hudButton.height + 4)
                                TpMenu {
                                    id: hudMenu
                                    width: Math.max(implicitWidth, theme.em * 20)
                                    // As a middle click in game: its web panels too (no Rest API command for them)
                                    Action { text: i18n.tr("Show / Hide Game UI (middle click)"); onTriggered: backend.toggleGameUi() }
                                    MenuSeparator {}
                                    Action { text: i18n.tr("Show HUD"); onTriggered: backend.setHudShown(true) }
                                    Action { text: i18n.tr("Hide HUD"); onTriggered: backend.setHudShown(false) }
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
                            visible: !backend.replayActive
                            text: page.gameState === "offline" ? i18n.tr("Start LMU: replays, playback & incidents come from the game.")
                                : page.gameState === "menu" ? i18n.tr("Watch a replay from the list to control it from here.")
                                : i18n.tr("Open the replay of this session in the game, or watch one from the list.")
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.9
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
                        spacing: theme.em * 0.5
                        TpSegmented {
                            Layout.topMargin: theme.em * 0.7
                            Layout.leftMargin: theme.em * 0.7
                            options: [i18n.tr("Incidents") + (backend.incidentCount > 0 ? "  " + backend.incidentCount : ""),
                                      i18n.tr("Drivers") + (backend.carCount > 0 ? "  " + backend.carCount : ""),
                                      i18n.tr("Map")]
                            currentIndex: backend.panelIndex
                            onActivated: function(index) { backend.setPanel(index) }
                        }
                        StackLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            currentIndex: backend.panelIndex
                            IncidentPanel {}
                            StandingsPanel {}
                            MapPanel {}
                        }
                    }
                }
            }
        }
    }

    // Replay files dropped on page: copied to replay folder of game
    DropArea {
        id: dropArea
        anchors.fill: parent
        onEntered: function(drag) { drag.accepted = drag.hasUrls }
        onDropped: function(drop) {
            if (!drop.hasUrls) return
            backend.addFiles(drop.urls)
            drop.acceptProposedAction()
        }
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: theme.em * 0.4
        visible: dropArea.containsDrag
        radius: theme.em * 0.8
        color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.12)
        border.width: 2
        border.color: theme.accent
        Column {
            anchors.centerIn: parent
            spacing: theme.em * 0.6
            Icon { anchors.horizontalCenter: parent.horizontalCenter; glyph: ""; size: theme.em * 3; color: theme.accent }  // download
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: i18n.tr("Drop replays (.Vcr) to add them to the game")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontPoint * 1.2
            }
        }
    }

    // Message of last file operation or refused command, a few seconds
    Rectangle {
        id: toast
        property bool shown: false
        anchors.horizontalCenter: parent.horizontalCenter
        y: shown ? parent.height - height - theme.em * 1.2 : parent.height + theme.em
        width: Math.min(toastRow.implicitWidth + theme.em * 2.4, page.width - theme.em * 4)
        height: toastRow.implicitHeight + theme.em * 1.1
        radius: theme.em * 0.8
        color: theme.raised
        border.width: 1
        border.color: backend.noticeError ? theme.loss : theme.border
        opacity: shown ? 1 : 0
        visible: opacity > 0
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Timer { id: toastTimer; interval: 6000; onTriggered: toast.shown = false }
        Connections {
            target: backend
            function onNoticeChanged() { toast.shown = true; toastTimer.restart() }
        }
        MouseArea { anchors.fill: parent; onClicked: toast.shown = false }
        Row {
            id: toastRow
            anchors.centerIn: parent
            spacing: theme.em * 0.6
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                glyph: backend.noticeError ? "" : ""  // warning, check
                color: backend.noticeError ? theme.loss : theme.gain
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, page.width - theme.em * 7)
                text: backend.noticeText
                color: theme.text
                wrapMode: Text.WordWrap
            }
        }
    }
}
