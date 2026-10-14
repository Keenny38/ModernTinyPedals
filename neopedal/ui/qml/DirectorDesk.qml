import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Camera desk: car on air (why, how long, director held after an operator cut), cameras of the game, replay
// transport, stories worth showing (assisted: take one; automatic: what the director cuts to next).
ColumnLayout {
    id: desk
    spacing: theme.em * 0.6

    readonly property var onAir: backend.onAir
    readonly property bool hasCar: onAir.slot !== undefined
    readonly property string mode: backend.modeName

    function tone(name) {
        return name === "loss" ? theme.loss : name === "gain" ? theme.gain : name === "warning" ? theme.warning
             : name === "accent" ? theme.accent : name === "fastest" ? theme.purple : name === "yellow" ? theme.gold : theme.dimText
    }
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

    // Camera button of desk: highlighted while it is the camera of the game
    component CameraButton: AbstractButton {
        id: control
        property string key: ""
        readonly property bool current: backend.camera.cameraKey === key
        objectName: "camera_" + key
        hoverEnabled: true
        focusPolicy: Qt.NoFocus
        implicitHeight: Math.round(theme.em * 2.1)
        implicitWidth: Math.max(label.implicitWidth + theme.em * 1.0, theme.em * 3.2)
        Layout.fillWidth: true
        onClicked: backend.camera.selectCamera(key)
        ToolTip.visible: hovered && label.truncated
        ToolTip.text: text
        background: Rectangle {
            radius: theme.radiusMd
            color: control.current ? theme.lossFill
                 : control.down ? theme.border : control.hovered ? theme.hover : theme.raised
            border.width: control.current ? 0 : 1
            border.color: theme.border
            Behavior on color { ColorAnimation { duration: theme.motionFast } }
        }
        contentItem: Text {
            id: label
            text: control.text
            color: control.current ? "white" : theme.text
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
        border.color: desk.hasCar ? Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.6) : theme.border
        ColumnLayout {
            id: airColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.7 }
            spacing: theme.em * 0.4

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                Rectangle {  // on air light
                    implicitHeight: Math.round(theme.em * 1.6)
                    implicitWidth: airText.implicitWidth + theme.em * 1.2
                    radius: theme.radiusSm
                    color: desk.hasCar ? theme.lossFill : theme.raised
                    Text {
                        id: airText
                        anchors.centerIn: parent
                        text: i18n.tr("On Air").toUpperCase()
                        color: desk.hasCar ? "white" : theme.dimText
                        font.weight: Font.Bold
                        font.pointSize: theme.fontCaption
                        font.letterSpacing: 1
                    }
                }
                Pill {
                    visible: desk.hasCar
                    text: desk.onAir.kindText || ""
                    glyph: desk.onAir.glyph || ""
                    tint: desk.tone(desk.onAir.tone || "")
                }
                Item { Layout.fillWidth: true }
                TpButton {  // car kept on air: director does not cut
                    objectName: "lockButton"
                    visible: desk.hasCar
                    implicitHeight: Math.round(theme.em * 1.8)
                    flat: !backend.carLocked
                    checked: backend.carLocked
                    glyph: backend.carLocked ? "" : ""  // lock, unlock
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
                spacing: theme.em * 0.6
                Rectangle {
                    visible: desk.hasCar
                    implicitWidth: Math.round(theme.em * 0.35)
                    implicitHeight: Math.round(theme.em * 2.6)
                    radius: width / 2
                    color: desk.onAir.classColor || theme.border
                }
                GameLogo { source: desk.onAir.brandLogo || ""; boxWidth: theme.em * 2.4; boxHeight: theme.em * 1.6 }
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
            // Pit radar: cars near the car on air in the pit lane (alongside in red)
            Flow {
                Layout.fillWidth: true
                visible: backend.pitRadarCount > 0
                spacing: theme.em * 0.3
                Repeater {
                    model: backend.pitRadarRows  // own model: distances change in place, card bindings untouched
                    delegate: Pill {
                        required property string number
                        required property string distance
                        required property bool alongside
                        required property bool ahead
                        text: "#" + number + "  " + (alongside ? i18n.tr("Alongside") : (ahead ? "\u25b2 " : "\u25bc ") + distance)
                        tint: alongside ? theme.loss : theme.warning
                        solid: alongside
                    }
                }
            }
            // Automatic mode: shortest shot going by (director may cut once full)
            Rectangle {
                id: shotBar
                property real now: Date.now()
                readonly property real length: desk.onAir.minShotMs || 0
                readonly property real done: length > 0 ? Math.min((now - (desk.onAir.startMs || now)) / length, 1) : 0
                Layout.fillWidth: true
                visible: desk.mode === "auto" && desk.hasCar && length > 0 && !backend.carLocked
                implicitHeight: Math.max(2, Math.round(theme.em * 0.18))
                radius: height / 2
                color: theme.border
                Rectangle {
                    width: parent.width * shotBar.done
                    height: parent.height
                    radius: height / 2
                    color: shotBar.done >= 1 ? theme.gain : theme.loss
                }
                Timer {
                    interval: 200
                    repeat: true
                    running: shotBar.visible && shotBar.done < 1 && pageState.active
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
        implicitHeight: cameraColumn.implicitHeight + theme.em * 1.2
        ColumnLayout {
            id: cameraColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.6 }
            spacing: theme.em * 0.4
            Repeater {
                model: ["Driving", "Onboard", "Trackside"]
                delegate: ColumnLayout {
                    id: group
                    required property string modelData
                    Layout.fillWidth: true
                    spacing: theme.em * 0.3
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: i18n.tr(group.modelData).toUpperCase()
                            color: theme.dimText
                            font.pointSize: theme.fontCaption
                            font.weight: Font.DemiBold
                            font.letterSpacing: 0.5
                        }
                        TpButton {
                            flat: true
                            implicitHeight: Math.round(theme.em * 1.6)
                            glyph: ""
                            tip: i18n.tr("Previous camera angle")
                            onClicked: backend.camera.stepCamera(group.modelData, -1)
                        }
                        TpButton {
                            flat: true
                            implicitHeight: Math.round(theme.em * 1.6)
                            glyph: ""
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
                Layout.topMargin: theme.em * 0.2
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Game HUD").toUpperCase()
                    color: theme.dimText
                    font.pointSize: theme.fontCaption
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.5
                }
                TpButton {
                    id: hudButton
                    objectName: "hudButton"
                    flat: true
                    implicitHeight: Math.round(theme.em * 1.6)
                    glyph: ""  // view
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
                    }
                }
            }
            // Replay transport
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: theme.em * 0.2
                visible: backend.replayActive
                spacing: theme.em * 0.3
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Replay").toUpperCase()
                    color: theme.dimText
                    font.pointSize: theme.fontCaption
                    font.weight: Font.DemiBold
                }
                TpButton { glyph: ""; text: "10 s"; flat: true; tip: i18n.tr("Back 10 seconds"); onClicked: backend.camera.jump(-10) }  // rewind
                TpButton {
                    readonly property bool moving: backend.camera.lastCommand !== "" && backend.camera.lastCommand !== "VCRCOMMAND_STOP"
                    accent: true
                    glyph: moving ? "" : ""  // pause, play
                    tip: (moving ? i18n.tr("Pause replay") : i18n.tr("Play replay")) + " (" + i18n.tr("Space") + ")"
                    onClicked: backend.camera.togglePlay()
                }
                TpButton {
                    glyph: ""  // slow
                    flat: true
                    checked: backend.camera.lastCommand === "VCRCOMMAND_SLOW"
                    tip: i18n.tr("Play slowly")
                    onClicked: backend.camera.playback("VCRCOMMAND_SLOW")
                }
                TpButton { glyph: ""; text: "10 s"; flat: true; tip: i18n.tr("Forward 10 seconds"); onClicked: backend.camera.jump(10) }  // fast forward
            }
        }
    }

    // Stories worth showing
    Card {
        Layout.fillWidth: true
        Layout.fillHeight: true
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: theme.em * 0.6
            spacing: theme.em * 0.4
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.em * 0.4
                Icon { glyph: desk.mode === "auto" ? "" : ""; color: theme.accent }  // lightning, list
                Text {
                    Layout.fillWidth: true
                    text: desk.mode === "auto" ? i18n.tr("Director Queue") : i18n.tr("Suggestions")
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontSubtitle
                    elide: Text.ElideRight
                }
                TpButton {
                    objectName: "takeBestButton"
                    visible: desk.mode !== "manual"
                    accent: desk.mode === "assist"
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
                spacing: theme.em * 0.3
                model: backend.suggestionRows
                boundsBehavior: Flickable.StopAtBounds
                displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
                delegate: Rectangle {
                    id: story
                    required property string key
                    required property string kindText
                    required property string glyph
                    required property string tone
                    required property string title
                    required property string detail
                    required property string classColor
                    required property int score
                    required property bool best
                    readonly property color tint: desk.tone(tone)
                    width: ListView.view.width
                    height: Math.round(theme.em * 3.0)
                    radius: theme.radiusMd
                    color: storyArea.containsMouse ? theme.hover : best ? Qt.rgba(tint.r, tint.g, tint.b, 0.1) : "transparent"
                    border.width: 1
                    border.color: best ? Qt.rgba(tint.r, tint.g, tint.b, 0.45) : theme.border
                    MouseArea {
                        id: storyArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: backend.takeSuggestion(story.key)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.em * 0.5
                        anchors.rightMargin: theme.em * 0.5
                        spacing: theme.em * 0.5
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
                                color: theme.dimText
                                font.pointSize: theme.fontCaption
                                elide: Text.ElideRight
                            }
                        }
                        Rectangle {  // score
                            Layout.preferredWidth: theme.em * 2.6
                            Layout.preferredHeight: Math.round(theme.em * 0.4)
                            radius: height / 2
                            color: theme.raised
                            Rectangle {
                                width: parent.width * Math.min(story.score, 100) / 100
                                height: parent.height
                                radius: height / 2
                                color: story.tint
                            }
                        }
                        Icon { glyph: ""; color: storyArea.containsMouse ? theme.accent : theme.dimText; size: theme.em * 0.9 }  // camera
                    }
                }
            }
                EmptyState {
                    anchors.centerIn: parent
                    width: parent.width - theme.em * 2
                    visible: suggestions.count === 0
                    glyph: ""  // pulse
                    title: i18n.tr("Quiet on track")
                    text: i18n.tr("Battles, overtakes, contacts and pit stops show up here as they happen.")
                }
            }
        }
    }
}
