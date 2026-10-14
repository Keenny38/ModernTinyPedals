import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Results & replays page: on the left, sessions written by the game (results files) or replays saved by the game
// (LMU); on the right, session picked: header, key figures of player, then classification, positions lap by lap
// (races), laps of a car, session events, and the replay tab (game replay or live session: playback, camera,
// incidents, standings, map). Session with a replay: watch it, or an event or a lap of it, in the game.
// Replay picked: results of its session shown. F5: read files & ask game again.
TpPage {
    id: page

    readonly property bool wide: width > theme.bpWide
    readonly property var header: backend.sessionHeader
    readonly property int replayTab: 4
    // Tabs shown: positions only for races, replay always (tab keys of backend: 0 classification, 1 positions,
    // 2 laps, 3 events, 4 replay); no session: replay tab only
    readonly property var tabKeys: !backend.hasSession ? [4] : backend.isRace ? [0, 1, 2, 3, 4] : [0, 2, 3, 4]
    readonly property var tabTexts: !backend.hasSession ? [i18n.tr("Replay")] : backend.isRace
        ? [i18n.tr("Classification"), i18n.tr("Positions"), i18n.tr("Laps"), i18n.tr("Events"), i18n.tr("Replay")]
        : [i18n.tr("Classification"), i18n.tr("Laps"), i18n.tr("Events"), i18n.tr("Replay")]
    // No session: replay tab if chosen (or replays listed), else why there is no session (-1)
    readonly property int tab: !backend.hasSession
        ? (backend.tabIndex === replayTab || backend.listMode === 1 ? replayTab : -1)
        : tabKeys.indexOf(backend.tabIndex) >= 0 ? backend.tabIndex : 0

    function toneColor(tone) {
        return tone === "gold" ? theme.gold : tone === "gain" ? theme.gain : tone === "loss" ? theme.loss
             : tone === "purple" ? theme.purple : tone === "warning" ? theme.warning
             : tone === "dim" ? theme.dimText : theme.text
    }

    GridLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        columns: page.wide ? 2 : 1
        columnSpacing: theme.em * 0.6
        rowSpacing: theme.em * 0.6

        // Sessions of results files, or replays saved by the game
        Card {
            Layout.fillHeight: page.wide
            Layout.fillWidth: !page.wide
            Layout.preferredWidth: page.wide ? Math.min(Math.max(page.width * 0.3, theme.em * 24), theme.em * 34) : -1
            Layout.preferredHeight: page.wide ? -1 : page.height * 0.34
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                TpSegmented {
                    objectName: "listMode"
                    Layout.topMargin: theme.em * 0.6
                    Layout.leftMargin: theme.em * 0.6
                    Layout.rightMargin: theme.em * 0.6
                    options: [i18n.tr("Sessions") + (backend.sessionCount > 0 ? "  " + backend.sessionCount : ""),
                              i18n.tr("Replays") + (replays.replayCount > 0 ? "  " + replays.replayCount : "")]
                    currentIndex: backend.listMode
                    onActivated: function(index) { backend.setListMode(index) }
                }
                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: backend.listMode
                    ResultsSessionList {}
                    Loader {  // built when first shown, then kept
                        active: backend.listMode === 1 || item !== null
                        sourceComponent: ReplayList {}
                    }
                }
            }
        }

        // Session picked (or why there is none), or replay of game
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                spacing: theme.em * 0.6
                visible: backend.hasSession || page.tab === page.replayTab

                // Header: kind, track, date, settings
                RowLayout {
                    Layout.fillWidth: true
                    visible: backend.hasSession
                    spacing: theme.em * 0.7
                    ResultsBadge {
                        code: page.header.code || ""
                        implicitWidth: Math.round(theme.em * 2.6)
                    }
                    GameLogo {  // circuit logo of game
                        source: page.header.trackLogo || ""
                        boxWidth: theme.em * 3.4
                        boxHeight: theme.em * 2.3
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.5
                            Text {
                                Layout.fillWidth: true
                                Layout.maximumWidth: implicitWidth
                                text: page.header.title || ""
                                color: theme.text
                                font.weight: Font.DemiBold
                                font.pointSize: theme.fontHeading
                                elide: Text.ElideRight
                            }
                            Text {
                                text: page.header.kindText || ""
                                color: theme.dimText
                                font.weight: Font.DemiBold
                            }
                            Rectangle {  // race left before its end: classification of that moment
                                visible: page.header.partial === true
                                implicitHeight: partialText.implicitHeight + theme.em * 0.3
                                implicitWidth: partialText.implicitWidth + theme.em * 1.0
                                radius: height / 2
                                color: Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.16)
                                ToolTip.visible: partialArea.containsMouse
                                ToolTip.text: i18n.tr("No car had finished when this file was written (race left before its end): classification and gaps of that moment.")
                                ToolTip.delay: theme.tipDelay
                                MouseArea { id: partialArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                                Text {
                                    id: partialText
                                    anchors.centerIn: parent
                                    text: i18n.tr("Unfinished")
                                    color: theme.warning
                                    font.pointSize: theme.fontSmall
                                    font.weight: Font.DemiBold
                                }
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: page.header.when || ""
                                color: theme.dimText
                                font.features: { "tnum": 1 }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: [page.header.subtitle || "", page.header.details || ""]
                                  .filter(function(part) { return part !== "" }).join(" · ")
                            color: theme.dimText
                            font.pointSize: theme.fontLabel
                            elide: Text.ElideRight
                            ToolTip.visible: headerArea.containsMouse
                            ToolTip.text: (page.header.file || "") + (page.header.game ? "  (" + page.header.game + ")" : "")
                            ToolTip.delay: theme.tipDelay
                            MouseArea { id: headerArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                    TpButton {  // replay saved by game for this session (LMU)
                        visible: (page.header.replay || "") !== ""
                        accent: true
                        glyph: "\uE768"  // play
                        text: i18n.tr("Watch Replay")
                        tip: i18n.tr("Open the replay of this session in the game") + "\n" + (page.header.replay || "")
                        onClicked: backend.watchReplay()
                    }
                    GamePicture {  // circuit picture of game
                        source: page.header.trackPicture || ""
                        boxHeight: theme.em * 3.0
                    }
                }

                // Key figures of player (winner & fastest lap if player not in session)
                Flow {
                    Layout.fillWidth: true
                    visible: backend.hasSession && page.tab !== page.replayTab
                    spacing: theme.em * 0.5
                    Repeater {
                        model: backend.summaryTiles
                        Rectangle {
                            id: tileBox
                            required property var modelData
                            readonly property bool toned: modelData.tone !== "" && modelData.tone !== "dim"
                            readonly property color tone: page.toneColor(modelData.tone)
                            width: Math.max(tileColumn.implicitWidth + theme.em * 1.6, theme.em * 7.5)
                            height: tileColumn.implicitHeight + theme.em * 0.9
                            radius: theme.radiusLg
                            color: toned ? Qt.rgba(tone.r, tone.g, tone.b, theme.dark ? 0.1 : 0.08) : theme.base
                            border.width: 1
                            border.color: toned ? Qt.rgba(tone.r, tone.g, tone.b, 0.35)
                                                : (theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border)
                            Behavior on color { ColorAnimation { duration: theme.motionBase } }
                            Column {
                                id: tileColumn
                                anchors.left: parent.left
                                anchors.leftMargin: theme.em * 0.8
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 0
                                Text {
                                    text: tileBox.modelData.label
                                    color: theme.dimText
                                    font.pointSize: theme.fontCaption
                                    font.capitalization: Font.AllUppercase
                                    font.letterSpacing: 0.4
                                }
                                Text {
                                    text: tileBox.modelData.value
                                    color: tileBox.modelData.tone !== "" ? tileBox.tone : theme.text
                                    font.weight: Font.Bold
                                    font.pointSize: theme.fontHeading
                                    font.features: { "tnum": 1 }
                                    width: Math.min(implicitWidth, theme.em * 14)
                                    elide: Text.ElideRight
                                }
                                Text {
                                    visible: tileBox.modelData.detail !== ""
                                    text: tileBox.modelData.detail
                                    color: theme.dimText
                                    font.pointSize: theme.fontSmall
                                    font.features: { "tnum": 1 }
                                    width: Math.min(implicitWidth, theme.em * 14)
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }

                // Tabs & car classes
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.6
                    TpSegmented {
                        objectName: "resultTabs"
                        options: page.tabTexts
                        currentIndex: page.tabKeys.indexOf(page.tab)
                        maxWidth: page.wide ? page.width * 0.45 : page.width * 0.7
                        onActivated: function(index) { backend.setTab(page.tabKeys[index]) }
                    }
                    Flickable {
                        Layout.fillWidth: true
                        visible: page.tab !== page.replayTab
                        implicitHeight: classRow.implicitHeight
                        contentWidth: classRow.implicitWidth
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        interactive: contentWidth > width
                        Row {
                            id: classRow
                            spacing: theme.em * 0.4
                            Repeater {
                                model: backend.classChips.length > 0
                                       ? [{ "name": "", "color": "", "count": 0 }].concat(backend.classChips) : []
                                AbstractButton {
                                    id: chip
                                    required property var modelData
                                    readonly property bool current: backend.classFilter === modelData.name
                                    hoverEnabled: true
                                    focusPolicy: Qt.NoFocus
                                    implicitHeight: Math.round(theme.em * 2.1)
                                    implicitWidth: chipRow.implicitWidth + theme.em * 1.3
                                    Accessible.role: Accessible.Button
                                    Accessible.name: chipText.text
                                    onClicked: backend.setClassFilter(modelData.name)
                                    background: Rectangle {
                                        radius: height / 2
                                        color: chip.current ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.18)
                                             : chip.hovered ? theme.hover : "transparent"
                                        border.width: chip.current ? 0 : 1
                                        border.color: theme.border
                                        Behavior on color { ColorAnimation { duration: theme.motionFast } }
                                    }
                                    contentItem: Item {
                                        Row {
                                            id: chipRow
                                            anchors.centerIn: parent
                                            spacing: theme.em * 0.4
                                            Rectangle {
                                                visible: chip.modelData.name !== ""
                                                width: Math.round(theme.em * 0.6)
                                                height: width
                                                radius: width / 2
                                                color: chip.modelData.color || "transparent"
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                            Text {
                                                id: chipText
                                                text: chip.modelData.name !== "" ? chip.modelData.name : i18n.tr("All Classes")
                                                color: chip.current ? theme.accent : theme.text
                                                font.weight: chip.current ? Font.DemiBold : Font.Normal
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                            Text {
                                                visible: chip.modelData.count > 0
                                                text: chip.modelData.count
                                                color: theme.dimText
                                                font.pointSize: theme.fontSmall
                                                font.features: { "tnum": 1 }
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    StackLayout {
                        anchors.fill: parent
                        anchors.margins: 1
                        currentIndex: page.tab
                        // Tabs built when first shown, then kept
                        Loader {
                            active: page.tab === 0 || item !== null
                            sourceComponent: ResultsTable {
                                onLapsWanted: function(key) {
                                    backend.selectEntry(key)
                                    backend.setTab(2)
                                }
                            }
                        }
                        Loader {
                            active: page.tab === 1 || item !== null
                            sourceComponent: ResultsPositions { active: page.tab === 1 && backend.isRace }
                        }
                        Loader {
                            active: page.tab === 2 || item !== null
                            sourceComponent: ResultsLaps {}
                        }
                        Loader {
                            active: page.tab === 3 || item !== null
                            sourceComponent: ResultsEvents {}
                        }
                        Loader {
                            active: page.tab === page.replayTab || item !== null
                            sourceComponent: ReplayView {}
                        }
                    }
                }
            }

            // Nothing to show: reading, no results found, or no session matching filters
            TpLoadingState {
                visible: !backend.hasSession && page.tab !== page.replayTab && backend.busy && !backend.loaded
                anchors.centerIn: parent
                text: i18n.tr("Reading results files...")
            }
            Column {
                visible: !backend.hasSession && page.tab !== page.replayTab && !(backend.busy && !backend.loaded)
                anchors.centerIn: parent
                width: Math.min(parent.width - theme.em * 2, theme.em * 30)
                spacing: theme.em * 0.6
                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    glyph: ""  // flag
                    size: theme.em * 2.6
                    color: theme.dimText
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: backend.folderText === "" ? i18n.tr("No results folder found")
                        : backend.sessionCount === 0 ? i18n.tr("No session results yet")
                        : i18n.tr("No session matches the filters")
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontSubtitle
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    visible: backend.loaded && backend.sessionCount === 0
                    text: backend.folderText === ""
                          ? i18n.tr("Results are written by Le Mans Ultimate (or rFactor 2) in UserData/Log/Results at the end of each session. Choose that folder if the game is not installed with Steam.")
                          : i18n.tr("The game writes a results file at the end of each session (practice, qualifying, race).")
                    color: theme.dimText
                }
                TpButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: backend.loaded && backend.folderText === ""
                    glyph: ""  // folder open
                    text: i18n.tr("Choose Folder...")
                    onClicked: backend.chooseFolder()
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
            replays.addFiles(drop.urls)
            drop.acceptProposedAction()
        }
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: theme.em * 0.4
        visible: dropArea.containsDrag
        radius: theme.radiusXl
        color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.12)
        border.width: 2
        border.color: theme.accent
        Column {
            anchors.centerIn: parent
            spacing: theme.em * 0.6
            Icon { anchors.horizontalCenter: parent.horizontalCenter; glyph: "\uE896"; size: theme.em * 3; color: theme.accent }  // download
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: i18n.tr("Drop replays (.Vcr) to add them to the game")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontHeading
            }
        }
    }

    // Message of last replay file operation or refused game command, a few seconds
    TpToast {
        id: toast
        text: replays.noticeText
        error: replays.noticeError
        duration: 6000
        Connections {
            target: replays
            function onNoticeChanged() { toast.show() }
        }
    }
}
