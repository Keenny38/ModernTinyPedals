import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Camera desk: car on air (why, how long, director held after an operator cut), cameras of the game, replay
// transport, stories worth showing (assisted: take one; automatic: what the director cuts to next).
// Suggestions show their number: keys 1 to 6 take them; a number stays on its story while it is listed, and the
// rows keep their place while the pointer is over the list (or it has focus) and a second after. Cameras: Tab,
// Enter or Space. The on air card keeps its height: shortest shot bar, operator hold & pit radar share one line.
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
    // Hotkey of a director command (keyboard shortcut settings) after a tooltip, "" if none
    function hotkeyTip(name) {
        var key = backend.keyLabels[name] || ""
        return key !== "" ? "  ·  " + i18n.tr("Hotkey %1").arg(key) : ""
    }

    // HUD part of the game in the HUD menu: checked while the game shows it
    component HudAction: TpHudAction {
        hudState: backend.camera.hudState
        onToggleRequested: function(key) { backend.camera.toggleHudComponent(key) }
    }

    // Camera button of desk: highlighted (red fill, dot & bold) while it is the camera of the game
    component CameraButton: AbstractButton {
        id: control
        property string key: ""
        readonly property bool current: backend.camera.cameraKey === key
        objectName: "camera_" + key
        hoverEnabled: true
        focusPolicy: Qt.TabFocus
        implicitHeight: theme.controlHeight
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
            radius: theme.radiusSm
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
            textFormat: Text.PlainText
            color: control.current ? theme.inkOn(theme.lossFill) : theme.text
            font.weight: control.current ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    // On air
    Card {
        objectName: "onAirCard"
        Layout.fillWidth: true
        implicitHeight: airColumn.implicitHeight + theme.padCard * 2
        border.color: desk.hasCar ? theme.loss : theme.cardBorder
        ColumnLayout {
            id: airColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.padCard }
            spacing: theme.space3

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                TpTally {  // on air light
                    objectName: "onAirTally"
                    live: desk.hasCar
                    text: i18n.tr("On Air")
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
                    glyph: backend.carLocked ? theme.glyphs.lock : theme.glyphs.unlock
                    fallback: i18n.tr("Locked")
                    text: backend.carLocked ? i18n.tr("Locked") : ""
                    tip: i18n.tr("Keep this car on air: the director does not cut until unlocked") + desk.hotkeyTip("director_lock")
                    onClicked: backend.toggleLock()
                }
                Text {  // shot length
                    id: shotClock
                    visible: desk.hasCar
                    property real now: Date.now()
                    text: desk.seconds((now - (desk.onAir.startMs || now)) / 1000)
                    textFormat: Text.PlainText
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
                // Height of the class strip kept with or without a car (cameras below never move)
                Layout.minimumHeight: Math.round(theme.em * 2.6)
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
                        textFormat: Text.PlainText
                        color: desk.hasCar ? theme.text : theme.dimText
                        font.pointSize: theme.fontLarge
                        font.weight: Font.Bold
                        elide: Text.ElideRight
                    }
                    Text {  // one line with or without a car: the card keeps its height
                        id: airDetail
                        Layout.fillWidth: true
                        text: desk.hasCar ? "P" + desk.onAir.classPosition + " " + desk.onAir.carClass
                                            + (backend.camera.cameraLabel !== "" ? "  ·  " + backend.camera.cameraLabel : "")
                                          : i18n.tr("Pick a car, a camera or a suggestion; the automatic mode cuts by itself.")
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontLabel
                        elide: Text.ElideRight
                        HoverHandler { id: detailHover }
                        ToolTip.visible: detailHover.hovered && airDetail.truncated
                        ToolTip.text: airDetail.text
                        ToolTip.delay: theme.tipDelay
                    }
                }
            }
            // Status line, height reserved: automatic mode's shortest shot going by (director may cut once full)
            // or operator hold countdown; pit radar on its right (cars near the car on air in the pit lane)
            Item {
                id: statusLine
                objectName: "airStatusLine"
                Layout.fillWidth: true
                Layout.preferredHeight: theme.controlHeightSm
                readonly property bool held: desk.mode === "auto" && holdText.remaining > 0 && !backend.carLocked
                readonly property real barWidth: width - (radar.visible ? radar.width + theme.space3 : 0)

                TpMeter {
                    id: shotBar
                    property real now: Date.now()
                    readonly property real length: desk.onAir.minShotMs || 0
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(statusLine.barWidth, 0)
                    visible: desk.mode === "auto" && desk.hasCar && length > 0 && !backend.carLocked && !statusLine.held
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
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(statusLine.barWidth, 0)
                    visible: statusLine.held
                    text: i18n.tr("Operator cut: director cuts again in %1 s").arg(Math.ceil(remaining))
                    textFormat: Text.PlainText
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
                Row {  // pit radar over the line's right end (alongside in red, filled)
                    id: radar
                    objectName: "pitRadar"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, statusLine.width)
                    visible: backend.pitRadarCount > 0
                    clip: true
                    spacing: theme.space2
                    layoutDirection: Qt.RightToLeft
                    Repeater {
                        model: backend.pitRadarRows  // own model: distances change in place, card bindings untouched
                        delegate: Pill {
                            required property string number
                            required property string distance
                            required property bool alongside
                            required property bool ahead
                            anchors.verticalCenter: parent.verticalCenter
                            text: "#" + number + "  " + (alongside ? i18n.tr("Alongside") : (ahead ? "▲ " : "▼ ") + distance)
                            tint: alongside ? theme.loss : theme.warning
                            solid: alongside
                        }
                    }
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
                        columnSpacing: theme.space1
                        rowSpacing: theme.space1
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
                    // Menu right aligned on button (page edge): never cut by window; second click closes it
                    onClicked: {
                        if (!hudMenu.visible)
                            backend.camera.refreshHud()  // parts shown asked again: checks follow the game
                        hudMenu.toggleBelow(hudButton, true)
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
                Layout.topMargin: theme.space1
                visible: backend.replayActive
                spacing: theme.space2
                TpSectionLabel {
                    Layout.fillWidth: true
                    text: i18n.tr("Replay")
                }
                TpTransportButton {
                    glyph: ""  // rewind
                    fallback: "«"
                    caption: "10"
                    tip: i18n.tr("Back 10 seconds")
                    onClicked: backend.camera.jump(-10)
                }
                TpTransportButton {
                    readonly property bool moving: backend.camera.lastCommand !== "" && backend.camera.lastCommand !== "VCRCOMMAND_STOP"
                    objectName: "playButton"
                    primary: true
                    glyph: moving ? "" : ""  // pause, play
                    fallback: moving ? "II" : "▶"
                    tip: (moving ? i18n.tr("Pause replay") : i18n.tr("Play replay")) + " (" + i18n.tr("Space") + ")"
                    onClicked: backend.camera.togglePlay()
                }
                TpTransportButton {
                    glyph: ""  // slow
                    fallback: "½×"
                    caption: "½"
                    current: backend.camera.lastCommand === "VCRCOMMAND_SLOW"
                    tip: i18n.tr("Play slowly")
                    onClicked: backend.camera.playback("VCRCOMMAND_SLOW")
                }
                TpTransportButton {
                    glyph: ""  // fast forward
                    fallback: "»"
                    caption: "10"
                    tip: i18n.tr("Forward 10 seconds")
                    onClicked: backend.camera.jump(10)
                }
            }
        }
    }

    // Stories worth showing
    TpSectionCard {
        Layout.fillWidth: true
        Layout.fillHeight: true
        glyph: desk.mode === "auto" ? "" : ""  // lightning, list
        title: desk.mode === "auto" ? i18n.tr("Director Queue") : i18n.tr("Suggestions")
        tip: desk.mode !== "manual" ? i18n.tr("Keys 1 to 6 take the suggestion of that number") : ""
        spacing: theme.space3
        actions: [
            TpButton {
                objectName: "takeBestButton"
                visible: desk.mode !== "manual"
                accent: desk.mode === "assist"
                size: "sm"
                text: i18n.tr("Take Best")
                tip: i18n.tr("Cut to the best story now (Enter)") + desk.hotkeyTip("director_take_best")
                enabled: suggestions.count > 0
                onClicked: backend.takeBest()
            }
        ]

        Text {
            Layout.fillWidth: true
            visible: desk.mode === "manual"
            text: i18n.tr("Manual mode: you cut alone. Assisted mode lists stories worth showing, automatic mode cuts to them by itself.")
            color: theme.dimText
            font.pointSize: theme.fontSmall
            wrapMode: Text.WordWrap
        }
        Item {
            id: storyArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: desk.mode !== "manual"
            // Operator aiming (pointer over the list, or list focused): rows keep their place, then a second more
            readonly property bool aiming: visible && pageState.active && (listHover.hovered || suggestions.activeFocus)
            onAimingChanged: {
                if (aiming) {
                    releaseTimer.stop()
                    backend.holdSuggestions(true)
                } else {
                    releaseTimer.restart()
                }
            }
            HoverHandler { id: listHover }
            Timer {
                id: releaseTimer
                interval: 1000
                onTriggered: backend.holdSuggestions(false)
            }
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
                    required property int hotkey
                    readonly property color tint: theme.tone(tone)
                    readonly property bool current: ListView.isCurrentItem && suggestions.activeFocus
                    width: ListView.view.width
                    height: theme.rowTall
                    Accessible.role: Accessible.ListItem
                    Accessible.name: (story.hotkey > 0 ? story.hotkey + ", " : "") + story.title + ", " + story.kindText
                    TpListRow {  // best story: own tint (the one Enter takes)
                        id: storyBack
                        anchors.fill: parent
                        hovered: rowArea.containsMouse
                        emphasized: story.best
                        tint: story.tint
                        border.width: 1
                        border.color: story.best ? story.tint : theme.border
                    }
                    FocusRing { target: storyBack; visible: story.current }
                    MouseArea {
                        id: rowArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: backend.takeSuggestion(story.key)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.space3
                        anchors.rightMargin: theme.space3
                        spacing: theme.space3
                        Rectangle {  // key of this suggestion (1 to 6), kept while the story is listed
                            objectName: "storyKey"
                            visible: story.hotkey > 0
                            Layout.preferredWidth: Math.round(theme.em * 1.5)
                            Layout.preferredHeight: Layout.preferredWidth
                            radius: theme.radiusSm
                            color: "transparent"
                            border.width: 1
                            border.color: theme.border
                            Text {
                                anchors.centerIn: parent
                                text: story.hotkey
                                textFormat: Text.PlainText
                                color: theme.dimOn(storyBack.color)
                                font.pointSize: theme.fontSmall
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
                                textFormat: Text.PlainText
                                color: theme.text
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: story.kindText + (story.detail !== "" ? "  ·  " + story.detail : "")
                                textFormat: Text.PlainText
                                color: theme.dimOn(storyBack.color)
                                font.pointSize: theme.fontSmall
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
                        Icon { glyph: ""; fallback: "◎"; color: rowArea.containsMouse ? theme.accent : theme.dimOn(storyBack.color); size: theme.iconSm }  // camera
                    }
                }
            }
            TpStateView {
                anchors.centerIn: parent
                width: parent.width - theme.em * 2
                empty: suggestions.count === 0
                compact: true
                glyph: ""  // pulse
                title: i18n.tr("Quiet on track")
                text: i18n.tr("Battles, overtakes, contacts and pit stops show up here as they happen.")
            }
        }
    }
}
