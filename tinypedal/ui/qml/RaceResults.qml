import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race results page: sessions written by the game (results files) on the left, session picked on the right:
// header, key figures of player, then classification, positions lap by lap (races), laps of a car and
// session events. Click a car: its laps, highlighted on positions chart. F5: read files again.
TpPage {
    id: page

    readonly property bool wide: width > theme.em * 70
    readonly property var header: backend.sessionHeader
    // Tabs shown: positions only for races (tab keys of backend: 0 classification, 1 positions, 2 laps, 3 events)
    readonly property var tabKeys: backend.isRace ? [0, 1, 2, 3] : [0, 2, 3]
    readonly property var tabTexts: backend.isRace
        ? [i18n.tr("Classification"), i18n.tr("Positions"), i18n.tr("Laps"), i18n.tr("Events")]
        : [i18n.tr("Classification"), i18n.tr("Laps"), i18n.tr("Events")]
    readonly property int tab: tabKeys.indexOf(backend.tabIndex) >= 0 ? backend.tabIndex : 0

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

        // Sessions of results files
        Card {
            Layout.fillHeight: page.wide
            Layout.fillWidth: !page.wide
            Layout.preferredWidth: page.wide ? Math.min(Math.max(page.width * 0.3, theme.em * 24), theme.em * 34) : -1
            Layout.preferredHeight: page.wide ? -1 : page.height * 0.34
            ResultsSessionList { anchors.fill: parent }
        }

        // Session picked (or why there is none)
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                spacing: theme.em * 0.6
                visible: backend.hasSession

                // Header: kind, track, date, settings
                RowLayout {
                    Layout.fillWidth: true
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
                                font.pointSize: theme.fontPoint * 1.3
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
                                ToolTip.delay: 400
                                MouseArea { id: partialArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                                Text {
                                    id: partialText
                                    anchors.centerIn: parent
                                    text: i18n.tr("Unfinished")
                                    color: theme.warning
                                    font.pointSize: theme.fontPoint * 0.85
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
                            font.pointSize: theme.fontPoint * 0.92
                            elide: Text.ElideRight
                            ToolTip.visible: headerArea.containsMouse
                            ToolTip.text: (page.header.file || "") + (page.header.game ? "  (" + page.header.game + ")" : "")
                            ToolTip.delay: 700
                            MouseArea { id: headerArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                    GamePicture {  // circuit picture of game
                        source: page.header.trackPicture || ""
                        boxHeight: theme.em * 3.0
                    }
                }

                // Key figures of player (winner & fastest lap if player not in session)
                Flow {
                    Layout.fillWidth: true
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
                            radius: theme.em * 0.6
                            color: toned ? Qt.rgba(tone.r, tone.g, tone.b, theme.dark ? 0.1 : 0.08) : theme.base
                            border.width: 1
                            border.color: toned ? Qt.rgba(tone.r, tone.g, tone.b, 0.35)
                                                : (theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border)
                            Behavior on color { ColorAnimation { duration: 200 } }
                            Column {
                                id: tileColumn
                                anchors.left: parent.left
                                anchors.leftMargin: theme.em * 0.8
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 0
                                Text {
                                    text: tileBox.modelData.label
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.78
                                    font.capitalization: Font.AllUppercase
                                    font.letterSpacing: 0.4
                                }
                                Text {
                                    text: tileBox.modelData.value
                                    color: tileBox.modelData.tone !== "" ? tileBox.tone : theme.text
                                    font.weight: Font.Bold
                                    font.pointSize: theme.fontPoint * 1.25
                                    font.features: { "tnum": 1 }
                                    width: Math.min(implicitWidth, theme.em * 14)
                                    elide: Text.ElideRight
                                }
                                Text {
                                    visible: tileBox.modelData.detail !== ""
                                    text: tileBox.modelData.detail
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.85
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
                        options: page.tabTexts
                        currentIndex: Math.max(page.tabKeys.indexOf(page.tab), 0)
                        maxWidth: page.wide ? page.width * 0.4 : page.width * 0.6
                        onActivated: function(index) { backend.setTab(page.tabKeys[index]) }
                    }
                    Flickable {
                        Layout.fillWidth: true
                        implicitHeight: classRow.implicitHeight
                        contentWidth: classRow.implicitWidth
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        interactive: contentWidth > width
                        Row {
                            id: classRow
                            spacing: theme.em * 0.35
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
                                        Behavior on color { ColorAnimation { duration: 120 } }
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
                                                font.pointSize: theme.fontPoint * 0.85
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
                        ResultsTable {
                            onLapsWanted: function(key) {
                                backend.selectEntry(key)
                                backend.setTab(2)
                            }
                        }
                        ResultsPositions { active: page.tab === 1 && backend.isRace }
                        ResultsLaps {}
                        ResultsEvents {}
                    }
                }
            }

            // Nothing to show: reading, no results found, or no session matching filters
            Column {
                visible: !backend.hasSession
                anchors.centerIn: parent
                width: Math.min(parent.width - theme.em * 2, theme.em * 30)
                spacing: theme.em * 0.6
                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    glyph: backend.busy ? "" : ""  // stopwatch, flag
                    size: theme.em * 2.6
                    color: theme.dimText
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: backend.busy && !backend.loaded ? i18n.tr("Reading results files...")
                        : backend.folderText === "" ? i18n.tr("No results folder found")
                        : backend.sessionCount === 0 ? i18n.tr("No session results yet")
                        : i18n.tr("No session matches the filters")
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontPoint * 1.1
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
}
