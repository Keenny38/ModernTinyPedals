import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Commentator screen: race events (click: camera on the car, replay goes there), battles with gap & trend,
// class leaders & best laps, pit stops & stints, sheet of the car picked in the car list (notes kept).
Item {
    id: root

    function tone(name) {
        return name === "loss" ? theme.loss : name === "gain" ? theme.gain : name === "warning" ? theme.warning
             : name === "accent" ? theme.accent : name === "fastest" ? theme.purple : name === "yellow" ? theme.gold : theme.dimText
    }
    property int tab: 0

    component SmallText: Text {
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.8
        elide: Text.ElideRight
    }
    component ClassBar: Rectangle {
        property string tint: ""
        Layout.preferredWidth: Math.round(theme.em * 0.28)
        Layout.fillHeight: true
        Layout.topMargin: theme.em * 0.35
        Layout.bottomMargin: theme.em * 0.35
        radius: width / 2
        color: tint !== "" ? tint : theme.border
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.6
        spacing: theme.em * 0.45

        TpSegmented {
            objectName: "commentaryTabs"
            Layout.fillWidth: true
            maxWidth: parent.width
            options: [i18n.tr("Events") + (backend.unseenCount > 0 ? "  " + backend.unseenCount : ""),
                      i18n.tr("Battles") + (backend.battleCount > 0 ? "  " + backend.battleCount : ""),
                      i18n.tr("Classes"), i18n.tr("Pit Stops")]
            currentIndex: root.tab
            onActivated: function(index) { root.tab = index }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.tab

            // Events
            ColumnLayout {
                spacing: theme.em * 0.4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.3
                    TpSegmented {
                        options: [i18n.tr("All"), i18n.tr("Incidents"), i18n.tr("Positions"), i18n.tr("Pit")]
                        maxWidth: parent.width - theme.em * 5
                        currentIndex: backend.feedFilter
                        onActivated: function(index) { backend.setFeedFilter(index) }
                    }
                    Item { Layout.fillWidth: true }
                    TpButton {
                        objectName: "markSeenButton"
                        flat: true
                        glyph: ""  // check
                        enabled: backend.unseenCount > 0
                        tip: i18n.tr("Mark every incident as seen")
                        onClicked: backend.markAllSeen()
                    }
                    TpButton {
                        objectName: "exportButton"
                        flat: true
                        glyph: ""  // export
                        enabled: feed.count > 0
                        tip: i18n.tr("Export Events") + " (CSV)"
                        onClicked: backend.exportEvents()
                    }
                }
                ListView {
                    id: feed
                    objectName: "feedList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: backend.feedRows
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    displaced: Transition { NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic } }
                    delegate: Rectangle {
                        id: entry
                        required property string key
                        required property string timeText
                        required property string kindText
                        required property string glyph
                        required property string tone
                        required property string title
                        required property string detail
                        required property bool live
                        required property string classColor
                        required property bool unseen
                        required property bool canReplay
                        width: ListView.view.width - (feed.ScrollBar.vertical.visible ? feed.ScrollBar.vertical.width : 0)
                        height: Math.round(theme.em * 2.8)
                        radius: theme.em * 0.4
                        color: entryArea.containsMouse ? theme.hover : "transparent"
                        opacity: live ? 1 : 0.6
                        MouseArea {
                            id: entryArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: backend.showEvent(entry.key)
                        }
                        ToolTip.visible: entryArea.containsMouse
                        ToolTip.text: backend.replayActive ? i18n.tr("Replay goes to this moment, camera on the car")
                                                           : i18n.tr("Camera on the car")
                        ToolTip.delay: 900
                        RowLayout {
                            anchors.fill: parent
                            anchors.rightMargin: theme.em * 0.3
                            spacing: theme.em * 0.45
                            ClassBar { tint: entry.classColor }
                            Text {
                                Layout.preferredWidth: theme.em * 3.6
                                text: entry.timeText
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.82
                                font.features: { "tnum": 1 }
                            }
                            Icon { glyph: entry.glyph; color: root.tone(entry.tone); size: theme.em * 0.95 }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Text {
                                    Layout.fillWidth: true
                                    text: entry.title
                                    color: theme.text
                                    font.weight: entry.unseen ? Font.Bold : Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                SmallText {
                                    Layout.fillWidth: true
                                    text: entry.kindText + (entry.detail !== "" ? "  ·  " + entry.detail : "")
                                }
                            }
                            Rectangle {  // incident nobody looked at yet
                                visible: entry.unseen
                                width: theme.em * 0.5
                                height: width
                                radius: width / 2
                                color: theme.accent
                            }
                            TpButton {  // instant replay (live), replay goes there (replay)
                                visible: entry.canReplay && backend.inSession && (entryArea.containsMouse || hovered)
                                Layout.preferredWidth: Math.round(theme.em * 2.0)
                                Layout.preferredHeight: Math.round(theme.em * 2.0)
                                flat: true
                                glyph: ""  // video
                                tip: backend.replayActive ? i18n.tr("Replay goes to this moment, camera on the car")
                                                          : i18n.tr("Instant replay: the game replays this moment, then back to live")
                                onClicked: backend.replayEvent(entry.key)
                            }
                        }
                    }
                    EmptyState {
                        parent: feed
                        anchors.centerIn: parent
                        visible: feed.count === 0
                        glyph: ""  // history
                        title: i18n.tr("No events yet")
                        text: i18n.tr("Contacts, overtakes, pit stops and fastest laps are listed as the race goes on.")
                    }
                }
            }

            // Battles
            ListView {
                id: battles
                objectName: "battleList"
                clip: true
                model: backend.battleRows
                spacing: theme.em * 0.3
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                displaced: Transition { NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic } }
                delegate: Rectangle {
                    id: fight
                    required property string key
                    required property int behindSlot
                    required property string carClass
                    required property string classColor
                    required property int position
                    required property string ahead
                    required property string behind
                    required property string gap
                    required property int trend
                    required property string duration
                    required property bool onAir
                    required property string gapTone
                    required property string trendText
                    width: ListView.view.width - (battles.ScrollBar.vertical.visible ? battles.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.em * 3.6)
                    radius: theme.em * 0.45
                    color: fightArea.containsMouse ? theme.hover : onAir ? Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.12) : theme.raised
                    border.width: 1
                    border.color: onAir ? theme.loss : theme.border
                    MouseArea {
                        id: fightArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: backend.cutToCar(fight.behindSlot)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.rightMargin: theme.em * 0.5
                        spacing: theme.em * 0.5
                        ClassBar { tint: fight.classColor }
                        ColumnLayout {
                            Layout.preferredWidth: theme.em * 3.2
                            spacing: 0
                            Text {
                                text: "P" + fight.position
                                color: theme.text
                                font.weight: Font.Bold
                                font.pointSize: theme.fontPoint * 1.1
                            }
                            SmallText { Layout.fillWidth: true; text: fight.carClass }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text { Layout.fillWidth: true; text: fight.ahead; color: theme.text; elide: Text.ElideRight }
                            Text { Layout.fillWidth: true; text: fight.behind; color: theme.text; font.weight: Font.DemiBold; elide: Text.ElideRight }
                        }
                        ColumnLayout {
                            spacing: 0
                            Row {
                                Layout.alignment: Qt.AlignRight
                                spacing: theme.em * 0.25
                                Icon {
                                    visible: fight.trend !== 0
                                    glyph: fight.trend < 0 ? "" : ""  // closing: chevron down, opening: up
                                    size: theme.em * 0.75
                                    color: fight.trend < 0 ? theme.loss : theme.gain
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: fight.gap
                                    color: fight.gapTone !== "" ? root.tone(fight.gapTone) : theme.text
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                            SmallText {
                                Layout.alignment: Qt.AlignRight
                                text: (fight.trendText !== "" ? fight.trendText + "  ·  " : "") + fight.duration
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                }
                EmptyState {
                    parent: battles
                    anchors.centerIn: parent
                    visible: battles.count === 0
                    glyph: ""  // pulse
                    title: i18n.tr("No battle right now")
                    text: i18n.tr("Two cars of a class within the battle gap (races only).")
                }
            }

            // Classes
            ListView {
                id: classList
                clip: true
                model: backend.classRows
                spacing: theme.em * 0.3
                boundsBehavior: Flickable.StopAtBounds
                delegate: Rectangle {
                    id: classRow
                    required property string name
                    required property string classColor
                    required property int count
                    required property string leader
                    required property string leaderNumber
                    required property string bestLap
                    required property string bestDriver
                    required property int battles
                    width: ListView.view.width
                    height: Math.round(theme.em * 3.6)
                    radius: theme.em * 0.45
                    border.width: 1
                    border.color: theme.border
                    color: theme.raised
                    RowLayout {
                        anchors.fill: parent
                        anchors.rightMargin: theme.em * 0.5
                        spacing: theme.em * 0.5
                        ClassBar { tint: classRow.classColor }
                        ColumnLayout {
                            Layout.preferredWidth: theme.em * 5
                            spacing: 0
                            Text { Layout.fillWidth: true; text: classRow.name; color: theme.text; font.weight: Font.Bold; elide: Text.ElideRight }
                            SmallText { Layout.fillWidth: true; text: i18n.tr("%1 cars").arg(classRow.count) }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: (classRow.leaderNumber !== "" ? "#" + classRow.leaderNumber + " " : "") + classRow.leader
                                color: theme.text
                                elide: Text.ElideRight
                            }
                            SmallText {
                                Layout.fillWidth: true
                                text: i18n.tr("Best Lap") + " " + classRow.bestLap + (classRow.bestDriver !== "" ? " · " + classRow.bestDriver : "")
                            }
                        }
                        Pill {
                            visible: classRow.battles > 0
                            glyph: ""
                            text: classRow.battles
                            tint: theme.accent
                            tip: i18n.tr("Battles")
                        }
                    }
                }
            }

            // Pit stops & stints
            ListView {
                id: pitList
                objectName: "pitList"
                clip: true
                model: backend.pitRows
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: pitRow
                    required property int slot
                    required property string number
                    required property string driver
                    required property string classColor
                    required property int stops
                    required property string lastStop
                    required property int stint
                    required property bool inPit
                    required property string status
                    width: ListView.view.width - (pitList.ScrollBar.vertical.visible ? pitList.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.em * 2.7)
                    radius: theme.em * 0.4
                    color: pitArea.containsMouse ? theme.hover : inPit ? Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.12) : "transparent"
                    MouseArea {
                        id: pitArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: backend.selectCar(pitRow.slot)
                        onDoubleClicked: backend.cutToCar(pitRow.slot)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.rightMargin: theme.em * 0.4
                        spacing: theme.em * 0.45
                        ClassBar { tint: pitRow.classColor }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: (pitRow.number !== "" ? "#" + pitRow.number + " " : "") + pitRow.driver
                                color: theme.text
                                elide: Text.ElideRight
                            }
                            SmallText {
                                Layout.fillWidth: true
                                text: pitRow.inPit ? pitRow.status : pitRow.lastStop
                                color: pitRow.inPit ? theme.warning : theme.dimText
                            }
                        }
                        ColumnLayout {
                            spacing: 0
                            Text {
                                Layout.alignment: Qt.AlignRight
                                text: i18n.tr("%1 stops").arg(pitRow.stops)
                                color: theme.text
                                font.pointSize: theme.fontPoint * 0.88
                                font.features: { "tnum": 1 }
                            }
                            SmallText {
                                Layout.alignment: Qt.AlignRight
                                text: pitRow.stint >= 0 ? i18n.tr("Stint %1 laps").arg(pitRow.stint) : ""
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                }
                EmptyState {
                    parent: pitList
                    anchors.centerIn: parent
                    visible: pitList.count === 0
                    glyph: ""  // car
                    title: i18n.tr("No pit stop yet")
                    text: i18n.tr("Pit stops seen during the race, with time in the pit lane and laps since.")
                }
            }
        }

        // Sheet of car picked in car list
        DirectorSheet {
            Layout.fillWidth: true
            visible: backend.sheet.slot !== undefined
        }
    }
}
