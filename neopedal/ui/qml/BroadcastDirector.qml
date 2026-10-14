import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Broadcast director (LMU): cars of the session, camera desk (car & camera on air, director suggestions or
// automatic cuts, replay transport) and commentator screen (events, battles, classes, pit stops, car sheet).
// Left / Right: previous / next car, Enter: take best suggestion, Space: play / pause replay, F5: ask game again.
TpPage {
    id: page

    readonly property string gameState: backend.gameState
    readonly property bool wide: width > theme.em * 92  // content-tuned: session strip & button texts of the three desks

    function stateColor(name) {
        return name === "replay" ? theme.accent : name === "session" ? theme.loss : name === "menu" ? theme.warning : theme.dimText
    }
    function tone(name) {
        return name === "loss" ? theme.loss : name === "gain" ? theme.gain : name === "warning" ? theme.warning
             : name === "accent" ? theme.accent : name === "fastest" ? theme.purple : name === "yellow" ? theme.gold : theme.dimText
    }

    // Text being typed (notes, settings): keys are characters, not commands
    readonly property bool typing: Window.activeFocusItem !== null && Window.activeFocusItem.cursorPosition !== undefined
    // Page keys only while shown: window shortcuts of a hidden page (other page shown) would fire too
    readonly property bool keys: pageState.active && !typing
    Shortcut { sequence: "Left"; enabled: page.keys && backend.inSession; onActivated: backend.stepCar(-1) }
    Shortcut { sequence: "Right"; enabled: page.keys && backend.inSession; onActivated: backend.stepCar(1) }
    Shortcut { sequences: ["Return", "Enter"]; enabled: page.keys && backend.inSession; onActivated: backend.takeBest() }
    Shortcut { sequence: "Space"; enabled: page.keys && backend.replayActive; onActivated: backend.camera.togglePlay() }
    Shortcut { sequences: [StandardKey.Refresh]; enabled: pageState.active && backend.enabled; onActivated: backend.game.refresh() }
    // 1 to 6: take that suggestion (assisted & automatic modes)
    Repeater {
        model: 6
        delegate: Item {
            required property int index
            Shortcut {
                sequence: String(index + 1)
                enabled: page.keys && backend.inSession && backend.modeName !== "manual"
                onActivated: backend.takeSuggestionAt(index)
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Header: director on / off, game state & session clock, mode, settings
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6

            TpSwitch {
                objectName: "enabledSwitch"
                checkable: false  // follows backend
                checked: backend.enabled
                // Narrow page: label only while off (state easy to miss from the switch alone)
                text: page.wide || !backend.enabled ? (backend.enabled ? i18n.tr("Enabled") : i18n.tr("Disabled")) : ""
                tip: i18n.tr("Broadcast Director on or off")
                onClicked: backend.setEnabled(!backend.enabled)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Broadcast Director on or off")
                Accessible.checked: backend.enabled
            }
            Rectangle {
                id: statePill
                visible: backend.enabled
                readonly property color tone: page.stateColor(page.gameState)
                implicitHeight: Math.round(theme.em * 2.3)
                implicitWidth: stateRow.implicitWidth + theme.em * 1.6
                Layout.maximumWidth: page.width * 0.45
                radius: height / 2
                color: Qt.rgba(tone.r, tone.g, tone.b, 0.12)
                border.width: 1
                border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.4)
                ToolTip.visible: stateArea.containsMouse
                ToolTip.text: backend.statusText
                ToolTip.delay: theme.tipDelay
                MouseArea { id: stateArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                Row {
                    id: stateRow
                    anchors.centerIn: parent
                    width: Math.min(implicitWidth, statePill.width - theme.em * 1.2)
                    spacing: theme.em * 0.5
                    TpPulseDot {
                        id: stateDot
                        color: statePill.tone
                        anchors.verticalCenter: parent.verticalCenter
                        pulsing: backend.inSession
                    }
                    Text {
                        text: page.gameState === "session" ? i18n.tr("Live").toUpperCase()
                            : page.gameState === "replay" ? i18n.tr("Replay").toUpperCase()
                            : backend.statusText
                        color: backend.inSession ? statePill.tone : theme.text
                        font.weight: Font.Bold
                        elide: Text.ElideRight
                        width: Math.min(implicitWidth, statePill.width - theme.em * 2.6)
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {  // session time, moves between game answers
                        id: sessionClock
                        visible: backend.inSession && backend.sessionTime >= 0
                        text: sessionTicker.format(sessionTicker.now)
                        color: theme.text
                        font.weight: Font.DemiBold
                        font.features: { "tnum": 1 }
                        anchors.verticalCenter: parent.verticalCenter
                        LiveClock {
                            id: sessionTicker
                            time: backend.sessionTime
                            received: backend.timeReceived
                            rate: backend.clockRate
                            active: sessionClock.visible && pageState.active
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 4
                text: backend.enabled ? backend.sessionText : ""
                color: theme.dimText
                elide: Text.ElideRight
            }
            // Full course yellow, temperatures, rain, wet track (click: forecast of the session)
            Item {
                id: weatherRow
                visible: backend.inSession && page.wide
                implicitWidth: weatherPills.implicitWidth
                implicitHeight: weatherPills.implicitHeight
                ToolTip.visible: weatherArea.containsMouse && backend.forecastNodes.length > 0
                ToolTip.text: i18n.tr("Weather Forecast")
                ToolTip.delay: theme.tipDelay
                MouseArea {
                    id: weatherArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: backend.forecastNodes.length > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: if (backend.forecastNodes.length > 0) forecastPopup.open()
                }
                Popup {
                    id: forecastPopup
                    y: weatherRow.height + 6
                    padding: theme.em * 0.8
                    background: Rectangle { radius: theme.radiusLg; color: theme.raised; border.width: 1; border.color: theme.border }
                    contentItem: ColumnLayout {
                        spacing: theme.em * 0.4
                        Text { text: i18n.tr("Weather Forecast"); color: theme.text; font.weight: Font.DemiBold }
                        Row {
                            spacing: theme.em * 0.4
                            Repeater {
                                model: backend.forecastNodes
                                delegate: Rectangle {
                                    required property var modelData
                                    width: theme.em * 6.2
                                    height: forecastColumn.implicitHeight + theme.em * 0.8
                                    radius: theme.radiusMd
                                    id: forecastCard
                                    readonly property color wetTone: theme.compound("Wet")
                                    color: modelData.wet ? Qt.rgba(wetTone.r, wetTone.g, wetTone.b, 0.16) : theme.base
                                    border.width: 1
                                    border.color: modelData.wet ? wetTone : theme.border
                                    Column {
                                        id: forecastColumn
                                        anchors.centerIn: parent
                                        width: parent.width - theme.em * 0.6
                                        spacing: 2
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: modelData.label === "Start" ? i18n.tr("Start") : modelData.label === "Finish" ? i18n.tr("Finish") : modelData.label; color: theme.dimText; font.pointSize: theme.fontCaption }
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: modelData.temperature; color: theme.text; font.weight: Font.DemiBold }
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: i18n.tr("Rain %1").replace("%1", modelData.rain); color: modelData.wet ? forecastCard.wetTone : theme.dimText; font.pointSize: theme.fontCaption }
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: modelData.sky; color: theme.dimText; font.pointSize: theme.fontTiny; wrapMode: Text.WordWrap }
                                    }
                                }
                            }
                        }
                    }
                }
                Row {
                    id: weatherPills
                    spacing: theme.em * 0.3
                    Repeater {
                        model: backend.weather
                        delegate: Pill {
                            required property string modelData
                            readonly property bool flag: modelData === i18n.tr("Full course yellow")
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData
                            glyph: flag ? "" : ""  // flag
                            solid: flag
                            tint: flag ? theme.gold : theme.dimText
                        }
                    }
                }
            }
            // Instant replay shown in the game: back to live at once
            Rectangle {
                visible: backend.instantReplay
                implicitHeight: Math.round(theme.em * 2.3)
                implicitWidth: replayRow.implicitWidth + theme.em * 1.2
                radius: height / 2
                color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.18)
                border.width: 1
                border.color: theme.accent
                Row {
                    id: replayRow
                    anchors.centerIn: parent
                    spacing: theme.em * 0.5
                    Icon { glyph: ""; color: theme.accent; anchors.verticalCenter: parent.verticalCenter }  // video
                    Text {
                        text: i18n.tr("Instant Replay").toUpperCase()
                        color: theme.accent
                        font.weight: Font.Bold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    TpButton {
                        objectName: "backToLiveButton"
                        anchors.verticalCenter: parent.verticalCenter
                        implicitHeight: Math.round(theme.em * 1.8)
                        accent: true
                        text: i18n.tr("Back to Live")
                        onClicked: backend.backToLive()
                    }
                }
            }
            // Mode: manual, assisted (suggestions), automatic (director cuts)
            TpSegmented {
                id: modeSwitch
                objectName: "modeSwitch"
                enabled: backend.enabled
                options: [i18n.tr("Manual"), i18n.tr("Assisted"), i18n.tr("Automatic")]
                currentIndex: backend.modeIndex
                onActivated: function(index) { backend.setMode(index) }
            }
            TpButton {  // broadcast graphics (browser source)
                id: graphicsButton
                objectName: "graphicsButton"
                glyph: ""  // streaming
                text: page.wide ? i18n.tr("Graphics") : ""
                tip: i18n.tr("Broadcast Graphics")
                checked: graphicsPopup.visible
                onClicked: graphicsPopup.visible ? graphicsPopup.close() : graphicsPopup.open()
                DirectorGraphics {
                    id: graphicsPopup
                    x: graphicsButton.width - width
                    y: graphicsButton.height + 4
                }
            }
            TpButton {
                id: settingsButton
                objectName: "settingsButton"
                glyph: ""  // sliders
                tip: i18n.tr("Director Settings")
                checked: settingsPopup.visible
                onClicked: settingsPopup.visible ? settingsPopup.close() : settingsPopup.open()
                DirectorSettings {
                    id: settingsPopup
                    x: settingsButton.width - width
                    y: settingsButton.height + 4
                }
            }
            TpButton {
                glyph: ""  // refresh
                tip: i18n.tr("Ask game again (F5)")
                enabled: backend.enabled
                onClicked: backend.game.refresh()
            }
        }

        // Director off, or game not in a session: what to do
        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !backend.inSession
            EmptyState {
                anchors.centerIn: parent
                width: Math.min(parent.width - theme.em * 2, theme.em * 34)
                glyph: ""  // video
                title: backend.enabled ? i18n.tr("Broadcast Director") : i18n.tr("Broadcast Director is off")
                text: !backend.enabled ? i18n.tr("The game is not asked anything: no camera cut and the broadcast graphics stay empty. Graphics and director settings can still be changed. Turn it on to direct a session or a replay.")
                    : page.gameState === "offline" ? i18n.tr("Start LMU: cars, cameras & race events come from the game.")
                    : i18n.tr("Join a session (driving or spectating) or open a replay in the game: the director follows it.")
                actionText: backend.enabled ? i18n.tr("Ask Game Again") : i18n.tr("Turn On Broadcast Director")
                onAction: backend.enabled ? backend.game.refresh() : backend.setEnabled(true)
            }
        }

        // Cars | camera desk | commentator screen
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: backend.inSession
            spacing: theme.em * 0.6

            Card {
                Layout.fillHeight: true
                Layout.preferredWidth: page.width * (page.wide ? 0.31 : 0.33)
                Layout.minimumWidth: theme.em * 22
                DirectorCars { anchors.fill: parent; onTimingRequested: timingTable.open() }
            }
            DirectorDesk {
                Layout.fillHeight: true
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 24
            }
            Card {
                Layout.fillHeight: true
                Layout.preferredWidth: page.width * (page.wide ? 0.33 : 0.31)
                Layout.minimumWidth: theme.em * 22
                DirectorCommentary { anchors.fill: parent }
            }
        }
    }

    DirectorLaps { id: lapHistory }
    DirectorTiming { id: timingTable }

    // Message of refused command, a few seconds
    TpToast {
        id: toast
        text: backend.noticeText
        error: backend.noticeError
        duration: 5000
        Connections {
            target: backend
            function onNoticeChanged() { toast.show() }
        }
    }
}
