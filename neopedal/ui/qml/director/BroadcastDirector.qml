import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Broadcast director (LMU): cars of the session, camera desk (car & camera on air, director suggestions or
// automatic cuts, replay transport) and commentator screen (events, battles, classes, pit stops, car sheet).
// Under bpWide the three panels are stacked in tabs (Cars / Desk / Commentary).
// Left / Right: previous / next car, Enter: take best suggestion, Space: play / pause replay, F5: ask game again.
// A focused control (button, switch, segmented, list) keeps these keys (ShortcutOverride): page keys never
// fire for it.
TpPage {
    id: page

    readonly property string gameState: backend.gameState
    readonly property bool wide: width > theme.em * 92  // content-tuned: session strip & button texts of the three desks
    readonly property bool stacked: width < theme.bpWide  // three columns need 70.6 em: tabs below
    property int deskTab: 1  // stacked page: panel shown (0 cars, 1 desk, 2 commentary)

    function stateColor(name) {
        return name === "replay" ? theme.accent : name === "session" ? theme.loss : name === "menu" ? theme.warning : theme.dimText
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
    // 1 to 6: take that suggestion (assisted & automatic modes), numbers shown on the suggestions
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

    LiveClock {  // session time, moves between game answers
        id: sessionTicker
        time: backend.sessionTime
        received: backend.timeReceived
        rate: backend.clockRate
        active: backend.inSession && backend.sessionTime >= 0 && statePill.visible && pageState.active
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Header: director on / off, game state & session clock, mode, settings (page title: in the host's title bar)
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space4

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
            Pill {  // game state (live / replay / menus...) & session clock: dot & text, not color alone
                id: statePill
                visible: backend.enabled
                Layout.alignment: Qt.AlignVCenter
                tint: page.stateColor(page.gameState)
                dot: true
                pulsing: backend.inSession
                maximumTextWidth: page.width * 0.3
                tip: backend.statusText
                text: (page.gameState === "session" ? i18n.tr("Live").toUpperCase()
                       : page.gameState === "replay" ? i18n.tr("Replay").toUpperCase()
                       : backend.statusText)
                      + (backend.inSession && backend.sessionTime >= 0 ? "  " + sessionTicker.format(sessionTicker.now) : "")
            }
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 4
                text: backend.enabled ? backend.sessionText : ""
                color: theme.dimText
                elide: Text.ElideRight
            }
            // Full course yellow, temperatures, rain, wet track (click, Enter or Space: forecast of the session)
            AbstractButton {
                id: weatherRow
                visible: backend.inSession && page.wide
                readonly property bool hasForecast: backend.forecastNodes.length > 0
                enabled: hasForecast
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                implicitWidth: weatherPills.implicitWidth
                implicitHeight: weatherPills.implicitHeight
                opacity: 1  // pills show the weather even without forecast (button only disabled)
                onClicked: forecastPopup.opened ? forecastPopup.close() : forecastPopup.open()
                Keys.onReturnPressed: animateClick()
                Keys.onEnterPressed: animateClick()
                Keys.onShortcutOverride: function(event) {
                    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
                        event.accepted = true
                }
                HoverHandler { cursorShape: weatherRow.hasForecast ? Qt.PointingHandCursor : Qt.ArrowCursor }
                ToolTip.visible: (hovered || visualFocus) && hasForecast
                ToolTip.text: i18n.tr("Weather Forecast")
                ToolTip.delay: theme.tipDelay
                Accessible.role: Accessible.Button
                Accessible.name: i18n.tr("Weather Forecast")
                background: Item { FocusRing { visible: weatherRow.visualFocus; radius: height / 2 } }
                contentItem: Row {
                    id: weatherPills
                    spacing: theme.space2
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
                TpPopup {
                    id: forecastPopup
                    y: weatherRow.height + 6
                    padding: theme.padCard
                    contentItem: ColumnLayout {
                        spacing: theme.space3
                        TpCardHeader { title: i18n.tr("Weather Forecast") }
                        Row {
                            spacing: theme.space3
                            Repeater {
                                model: backend.forecastNodes
                                delegate: Rectangle {
                                    id: forecastCard
                                    required property var modelData
                                    readonly property color wetTone: theme.compound("Wet")
                                    width: theme.em * 6.2
                                    height: forecastColumn.implicitHeight + theme.space5
                                    radius: theme.radiusMd
                                    color: modelData.wet ? Qt.tint(theme.base, theme.tint(wetTone, "selected")) : theme.base
                                    border.width: modelData.wet ? 2 : 1  // wet: thicker frame too
                                    border.color: modelData.wet ? wetTone : theme.border
                                    Column {
                                        id: forecastColumn
                                        anchors.centerIn: parent
                                        width: parent.width - theme.space4
                                        spacing: 2
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: forecastCard.modelData.label === "Start" ? i18n.tr("Start") : forecastCard.modelData.label === "Finish" ? i18n.tr("Finish") : forecastCard.modelData.label; color: theme.dimOn(forecastCard.color); font.pointSize: theme.fontCaption }
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: forecastCard.modelData.temperature; color: theme.text; font.weight: Font.DemiBold }
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: i18n.tr("Rain %1").replace("%1", forecastCard.modelData.rain); color: theme.dimOn(forecastCard.color); font.pointSize: theme.fontCaption; font.weight: forecastCard.modelData.wet ? Font.DemiBold : Font.Normal }
                                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: forecastCard.modelData.sky; color: theme.dimOn(forecastCard.color); font.pointSize: theme.fontTiny; wrapMode: Text.WordWrap }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            // Instant replay shown in the game: back to live at once
            Rectangle {
                visible: backend.instantReplay
                implicitHeight: theme.controlHeight
                implicitWidth: replayRow.implicitWidth + theme.space6
                radius: height / 2
                color: theme.tint(theme.accent, "selected")
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
                        size: "sm"
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
                name: i18n.tr("Director mode")
                enabled: backend.enabled
                options: [i18n.tr("Manual"), i18n.tr("Assisted"), i18n.tr("Automatic")]
                currentIndex: backend.modeIndex
                onActivated: function(index) { backend.setMode(index) }
            }
            TpButton {  // broadcast graphics (browser source)
                id: graphicsButton
                objectName: "graphicsButton"
                glyph: ""  // streaming
                fallback: i18n.tr("Graphics")
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
                fallback: "⚙"
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
                fallback: "⟳"
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

        // Narrow page: one panel at a time
        TpSegmented {
            objectName: "deskTabs"
            Layout.fillWidth: true
            visible: backend.inSession && page.stacked
            name: i18n.tr("Broadcast Director")
            maxWidth: width
            options: [i18n.tr("Cars"), i18n.tr("Desk"), i18n.tr("Commentary")]
            currentIndex: page.deskTab
            onActivated: function(index) { page.deskTab = index }
        }

        // Cars | camera desk | commentator screen (stacked page: the panel of the tab, whole width)
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: backend.inSession
            spacing: theme.space4

            Card {
                visible: !page.stacked || page.deskTab === 0
                Layout.fillHeight: true
                Layout.fillWidth: page.stacked
                Layout.preferredWidth: page.stacked ? -1 : page.width * (page.wide ? 0.31 : 0.33)
                Layout.minimumWidth: page.stacked ? 0 : theme.em * 22
                DirectorCars { anchors.fill: parent; onTimingRequested: timingTable.open() }
            }
            DirectorDesk {
                visible: !page.stacked || page.deskTab === 1
                Layout.fillHeight: true
                Layout.fillWidth: true
                Layout.minimumWidth: page.stacked ? 0 : theme.em * 24
            }
            Card {
                visible: !page.stacked || page.deskTab === 2
                Layout.fillHeight: true
                Layout.fillWidth: page.stacked
                Layout.preferredWidth: page.stacked ? -1 : page.width * (page.wide ? 0.33 : 0.31)
                Layout.minimumWidth: page.stacked ? 0 : theme.em * 22
                DirectorCommentary { anchors.fill: parent }
            }
        }
    }

    DirectorLaps { id: lapHistory }
    DirectorTiming { id: timingTable }

    // Message of refused command (time from text length)
    TpToast {
        id: toast
        text: backend.noticeText
        error: backend.noticeError
        Connections {
            target: backend
            function onNoticeChanged() { toast.show() }
        }
    }
}
