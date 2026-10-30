import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Session recorder page: record the game's shared memory, list of recordings, replay one through every overlay
// (playback bar of the lap viewer: one transport look), go to a lap or an incident, save a section to a new file.
// Keys: Space play / pause, Left / Right 5 s, Shift + Left / Right one frame, , . speed, L loop.
TpPage {
    id: page
    objectName: "sessionRecorder"

    // Page area minimum (host page_minimum_size): replay rows at their full width
    readonly property real minimumWidth: Math.max(jumpRow.implicitWidth, sectionRow.implicitWidth, theme.em * 34)
                                         + theme.padPage * 2 + theme.padCard * 2
    focus: true

    function changeSpeed(direction) {
        var speeds = backend.speeds
        var index = speeds.indexOf(backend.speed)
        backend.setSpeed(speeds[Math.max(0, Math.min(speeds.length - 1, (index < 0 ? speeds.indexOf(1) : index) + direction))])
    }
    Keys.onPressed: function(event) {
        var shift = (event.modifiers & Qt.ShiftModifier) !== 0
        if (!backend.active) return
        if (event.key === Qt.Key_Space) backend.togglePause()
        else if (event.key === Qt.Key_Left && shift) backend.step(-1)
        else if (event.key === Qt.Key_Right && shift) backend.step(1)
        else if (event.key === Qt.Key_Left) backend.seekRelative(-5)
        else if (event.key === Qt.Key_Right) backend.seekRelative(5)
        else if (event.key === Qt.Key_Comma) page.changeSpeed(-1)
        else if (event.key === Qt.Key_Period) page.changeSpeed(1)
        else if (event.key === Qt.Key_L) backend.setLoop(!backend.loop)
        else return
        event.accepted = true
    }


    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Game data API without shared memory replay: recording & replay off, told why
        TpNotice {
            objectName: "apiNotice"
            visible: !backend.apiSupported
            text: backend.apiHint
        }

        // Recording: start / stop, frames recorded and file, or why the last recording stopped
        TpSectionCard {
            title: i18n.tr("Recording")
            glyph: ""  // video
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space4
                TpButton {
                    objectName: "recordButton"
                    text: backend.recording ? i18n.tr("Stop Recording") : i18n.tr("Start Recording")
                    accent: !backend.recording
                    danger: backend.recording
                    enabled: backend.canRecord
                    tip: i18n.tr("Record Le Mans Ultimate shared memory while driving.")
                    onClicked: backend.toggleRecording()
                }
                TpPulseDot {
                    visible: backend.recording
                    pulsing: backend.recording && pageState.active
                    color: theme.loss
                }
                Icon {  // recording stopped by itself: icon with its color (never color alone)
                    visible: backend.recordError
                    glyph: ""  // warning
                    fallback: "!"
                    color: theme.warning
                }
                Text {
                    objectName: "recordText"
                    Layout.fillWidth: true
                    text: backend.recordText !== "" ? backend.recordText
                                                    : i18n.tr("Record Le Mans Ultimate shared memory while driving.")
                    textFormat: Text.PlainText
                    color: backend.recordError ? theme.warning : backend.recording ? theme.text : theme.dimText
                    elide: Text.ElideMiddle
                }
            }
        }

        // Recordings of telemetry folder, newest first: double-click, Enter or Play replays one
        TpSectionCard {
            id: listCard
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 10
            title: i18n.tr("Replays")
            glyph: ""  // list
            count: backend.replays.length > 0 ? String(backend.replays.length) : ""
            busy: backend.listing
            actions: [
                TpButton {
                    objectName: "openButton"
                    text: i18n.tr("Open Replay…")
                    glyph: theme.glyphs.openFile
                    fallback: "+"
                    size: "sm"
                    enabled: backend.apiSupported
                    tip: i18n.tr("Play a replay file from another folder")
                    onClicked: backend.openReplay()
                },
                TpButton {
                    glyph: theme.glyphs.refresh
                    fallback: "⟳"
                    flat: true
                    size: "sm"
                    tip: i18n.tr("Refresh")
                    onClicked: backend.refreshList()
                },
                TpButton {
                    glyph: theme.glyphs.openFolder
                    fallback: "…"
                    flat: true
                    size: "sm"
                    tip: i18n.tr("Open Folder")
                    onClicked: backend.openFolder()
                }
            ]
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                visible: list.count > 0
                TpHeaderCell { text: i18n.tr("Date"); Layout.preferredWidth: theme.em * 8 }
                TpHeaderCell { text: i18n.tr("Track"); Layout.fillWidth: true; Layout.preferredWidth: theme.em * 8 }
                TpHeaderCell { text: i18n.tr("Car"); Layout.fillWidth: true; Layout.preferredWidth: theme.em * 8 }
                TpHeaderCell { text: i18n.tr("Session"); Layout.preferredWidth: theme.em * 6 }
                TpHeaderCell { text: i18n.tr("Duration"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 4 }
                TpHeaderCell { text: i18n.tr("Size"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 4.5 }
                Item { Layout.preferredWidth: playWidth.width }
            }
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ListView {
                    id: list
                    objectName: "replayList"
                    anchors.fill: parent
                    clip: true
                    model: backend.replays
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    activeFocusOnTab: true
                    keyNavigationEnabled: true
                    Keys.onReturnPressed: if (currentItem) backend.openFile(currentItem.modelData.file)
                    Keys.onEnterPressed: if (currentItem) backend.openFile(currentItem.modelData.file)
                    delegate: TpListRow {
                        id: row
                        required property var modelData
                        required property int index
                        readonly property bool played: backend.filePath !== "" && modelData.file === backend.filePath
                        readonly property bool loadingRow: backend.loadingFile !== "" && modelData.file === backend.loadingFile
                        width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                        height: Math.round(theme.row)
                        hovered: rowArea.containsMouse
                        selected: ListView.isCurrentItem
                        emphasized: played
                        striped: index % 2 === 1
                        Accessible.role: Accessible.ListItem
                        Accessible.name: modelData.date + " " + modelData.track + " " + modelData.vehicle
                        FocusRing { visible: row.ListView.isCurrentItem && list.activeFocus }
                        MouseArea {
                            id: rowArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: { list.currentIndex = row.index; list.forceActiveFocus() }
                            onDoubleClicked: backend.openFile(row.modelData.file)
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: theme.space2
                            spacing: theme.space3
                            Text {
                                Layout.preferredWidth: theme.em * 8
                                text: (row.played ? "▶ " : "") + row.modelData.date
                                textFormat: Text.PlainText
                                color: theme.dimOn(row.color)
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.preferredWidth: theme.em * 8
                                text: row.modelData.track
                                textFormat: Text.PlainText
                                color: theme.text
                                font.weight: row.played ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.preferredWidth: theme.em * 8
                                text: row.modelData.vehicle
                                textFormat: Text.PlainText
                                color: theme.text
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: theme.em * 6
                                text: row.modelData.session
                                textFormat: Text.PlainText
                                color: theme.dimOn(row.color)
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: theme.em * 4
                                horizontalAlignment: Text.AlignRight
                                text: row.modelData.duration
                                textFormat: Text.PlainText
                                color: theme.text
                                font.features: { "tnum": 1 }
                            }
                            Text {
                                Layout.preferredWidth: theme.em * 4.5
                                horizontalAlignment: Text.AlignRight
                                text: row.modelData.size
                                textFormat: Text.PlainText
                                color: theme.dimOn(row.color)
                                font.features: { "tnum": 1 }
                            }
                            // Row action, room kept (no column jump on hover)
                            Item {
                                Layout.preferredWidth: playWidth.width
                                Layout.fillHeight: true
                                TpSpinner {
                                    anchors.centerIn: parent
                                    visible: row.loadingRow
                                }
                                TpButton {
                                    anchors.centerIn: parent
                                    visible: !row.loadingRow && !row.played
                                             && (rowArea.containsMouse || row.ListView.isCurrentItem || activeFocus)
                                    text: i18n.tr("Play")
                                    glyph: ""  // play
                                    fallback: "▶"
                                    size: "xs"
                                    enabled: backend.apiSupported
                                    tip: i18n.tr("Play this replay through every overlay")
                                    onClicked: backend.openFile(row.modelData.file)
                                }
                            }
                        }
                    }
                }
                // Widest row action (room of the action column, measured hidden)
                TpButton {
                    id: playWidth
                    visible: false
                    text: i18n.tr("Play")
                    glyph: ""
                    fallback: "▶"
                    size: "xs"
                }
                TpStateView {
                    anchors.centerIn: parent
                    loading: backend.listing && list.count === 0
                    empty: !backend.listing && list.count === 0
                    glyph: ""  // video
                    title: i18n.tr("No recording yet")
                    text: i18n.tr("Start Recording while driving, or open a replay file.")
                }
            }
        }

        // Replay played: file, playback, go to a lap or an incident, section saved to a new file
        TpSectionCard {
            title: i18n.tr("Replay")
            glyph: ""  // play
            busy: backend.loading
            actions: [
                TpButton {
                    objectName: "backToGameButton"
                    text: i18n.tr("Back to Game")
                    size: "sm"
                    enabled: backend.active || backend.loading
                    tip: i18n.tr("Stop replay: overlays read the game again")
                    onClicked: backend.backToGame()
                }
            ]
            Text {
                objectName: "fileText"
                Layout.fillWidth: true
                text: backend.loading ? backend.loadText
                      : backend.active ? backend.fileName : i18n.tr("Not replaying, reading from game.")
                textFormat: Text.PlainText
                color: backend.active || backend.loading ? theme.text : theme.dimText
                font.weight: backend.active ? Font.DemiBold : Font.Normal
                elide: Text.ElideMiddle
            }
            PlaybackBar {
                id: transport
                objectName: "recorderPlayback"
                Layout.fillWidth: true
                visible: true
                enabled: backend.active
                canPlay: backend.active
                playing: backend.active && !backend.paused
                speeds: backend.speeds
                speed: backend.speed
                loopShown: true
                loop: backend.loop
                skipStep: 5
                duration: backend.duration
                hasPosition: backend.active
                position: backend.position
                positionText: backend.positionText
                frameButtons: true
                laps: backend.laps
                incidents: backend.incidents
                sectionStart: backend.sectionStart
                sectionEnd: backend.sectionEnd
                playTip: i18n.tr("Play / pause") + " (" + i18n.tr("Space") + ")"
                loopTip: i18n.tr("Loop") + " (L)"
                scrubTip: i18n.tr("Drag to move in replay")
                backTip: i18n.tr("5 s back (Left, hold: rewind)")
                forwardTip: i18n.tr("5 s forward (Right, hold: fast forward)")
                onPlayToggled: backend.togglePause()
                onSkipped: function(seconds) { backend.seekRelative(seconds) }
                onFrameStepped: function(frames) { backend.step(frames) }
                onLoopToggled: backend.setLoop(!backend.loop)
                onSpeedPicked: function(speed) { backend.setSpeed(speed) }
                onSeeked: function(position) { backend.seek(position) }
            }
            // Laps (marks on top of position slider) & incidents (marks below)
            RowLayout {
                id: jumpRow
                Layout.fillWidth: true
                spacing: theme.space3
                Text {
                    text: i18n.tr("Go to lap")
                    textFormat: Text.PlainText
                    color: theme.dimText
                }
                TpCombo {
                    id: lapCombo
                    objectName: "lapCombo"
                    Layout.fillWidth: true
                    Layout.minimumWidth: theme.em * 9
                    Layout.maximumWidth: theme.em * 18
                    enabled: backend.active && backend.lapItems.length > 0
                    tip: i18n.tr("Go to lap")
                    model: backend.lapItems
                    textRole: "text"
                    currentIndex: -1
                    onModelChanged: currentIndex = -1  // laps of another replay: none picked
                    onActivated: function(index) { backend.gotoLap(index) }
                }
                TpButton {
                    objectName: "previousIncidentButton"
                    text: i18n.tr("◀ Incident")
                    size: "sm"
                    enabled: backend.active && backend.incidents.length > 0
                    tip: i18n.tr("Previous incident")
                    onClicked: backend.gotoIncident(-1)
                }
                TpButton {
                    objectName: "nextIncidentButton"
                    text: i18n.tr("Incident ▶")
                    size: "sm"
                    enabled: backend.active && backend.incidents.length > 0
                    tip: i18n.tr("Next incident")
                    onClicked: backend.gotoIncident(1)
                }
                Item { Layout.fillWidth: true }
            }
            // Section between start & end (shaded on position slider) saved to a new file
            RowLayout {
                id: sectionRow
                Layout.fillWidth: true
                spacing: theme.space3
                TpButton {
                    objectName: "sectionStartButton"
                    text: i18n.tr("Set Start")
                    size: "sm"
                    enabled: backend.active
                    tip: i18n.tr("Section starts at current position")
                    onClicked: backend.setSection(0)
                }
                TpButton {
                    objectName: "sectionEndButton"
                    text: i18n.tr("Set End")
                    size: "sm"
                    enabled: backend.active
                    tip: i18n.tr("Section ends at current position")
                    onClicked: backend.setSection(1)
                }
                TpButton {
                    objectName: "saveSectionButton"
                    text: i18n.tr("Save Section…")
                    size: "sm"
                    enabled: backend.canSave
                    tip: i18n.tr("Save part of replay between start & end to a new file")
                    onClicked: backend.saveSection()
                }
                TpSpinner { visible: backend.saving }
                Text {
                    objectName: "sectionText"
                    Layout.fillWidth: true
                    text: backend.sectionText
                    textFormat: Text.PlainText
                    color: theme.dimText
                    elide: Text.ElideMiddle
                }
            }
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Space: play/pause, Left/Right: 5 s, Shift+Left/Right: one frame.")
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.WordWrap
            }
        }
    }

    TpDialogHost {}  // toasts of the backend (errors, section saved)
}
