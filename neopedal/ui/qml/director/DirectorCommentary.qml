import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Commentator screen: race events (click: camera on the car, replay goes there), battles with gap & trend,
// class leaders & best laps, pit stops & stints, sheet of the car picked in the car list (notes kept).
// Lists: Up / Down move, Enter acts on the row (event: camera there, battle: cut, pit stop: car sheet).
Item {
    id: root

    property int tab: 0

    component SmallText: Text {
        color: theme.dimText
        font.pointSize: theme.fontCaption
        elide: Text.ElideRight
    }
    // Lists of this screen: keyboard reachable, Enter kept by the list (not the page's "take best")
    component KeyList: ListView {
        activeFocusOnTab: true
        keyNavigationEnabled: true
        highlightFollowsCurrentItem: false
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        Keys.onShortcutOverride: function(event) {
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                event.accepted = true
        }
        onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.em * 0.5

        TpSegmented {
            objectName: "commentaryTabs"
            Layout.fillWidth: true
            maxWidth: parent.width
            name: i18n.tr("Commentary")
            options: [i18n.tr("Events") + (backend.unseenCount > 0 ? "  " + backend.unseenCount : ""),
                      i18n.tr("Battles") + (backend.battleCount > 0 ? "  " + backend.battleCount : ""),
                      i18n.tr("Classes"), i18n.tr("Pit Stops")]
            currentIndex: root.tab
            onActivated: function(index) { backend.setCommentaryTab(index); root.tab = index }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.tab

            // Events
            ColumnLayout {
                spacing: theme.space3
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.space2
                    TpSegmented {
                        name: i18n.tr("Events")
                        options: [i18n.tr("All"), i18n.tr("Incidents"), i18n.tr("Positions"), i18n.tr("Pit")]
                        maxWidth: parent.width - theme.em * 5
                        currentIndex: backend.feedFilter
                        onActivated: function(index) { backend.setFeedFilter(index) }
                    }
                    Item { Layout.fillWidth: true }
                    TpButton {
                        objectName: "markSeenButton"
                        flat: true
                        size: "sm"
                        glyph: ""  // check
                        fallback: "✓"
                        enabled: backend.unseenCount > 0
                        tip: i18n.tr("Mark every incident as seen")
                        onClicked: backend.markAllSeen()
                    }
                    TpButton {
                        objectName: "exportButton"
                        flat: true
                        size: "sm"
                        glyph: ""  // export
                        fallback: "CSV"
                        enabled: feed.count > 0
                        tip: i18n.tr("Export Events") + " (CSV)"
                        onClicked: backend.log.exportEvents()
                    }
                }
                KeyList {
                    id: feed
                    objectName: "feedList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: backend.feedRows
                    reuseItems: true
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
                    Keys.onReturnPressed: if (currentItem) backend.showEvent(currentItem.key)
                    Keys.onEnterPressed: if (currentItem) backend.showEvent(currentItem.key)
                    delegate: Item {
                        id: entry
                        required property int index
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
                        readonly property bool current: ListView.isCurrentItem && feed.activeFocus
                        readonly property bool showReplay: entryArea.containsMouse || replayButton.hovered || entry.current
                        width: ListView.view.width - (feed.ScrollBar.vertical.visible ? feed.ScrollBar.vertical.width : 0)
                        height: Math.round(theme.row)
                        Accessible.role: Accessible.ListItem
                        Accessible.name: entry.timeText + ", " + entry.title + ", " + entry.kindText
                                         + (entry.unseen ? ", " + i18n.tr("Unseen") : "")
                        TpListRow {
                            id: entryBack
                            anchors.fill: parent
                            hovered: entryArea.containsMouse
                        }
                        FocusRing { target: entryBack; visible: entry.current }
                        MouseArea {
                            id: entryArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: { feed.currentIndex = entry.index; backend.showEvent(entry.key) }
                        }
                        ToolTip.visible: entryArea.containsMouse
                        ToolTip.text: backend.replayActive ? i18n.tr("Replay goes to this moment, camera on the car")
                                                           : i18n.tr("Camera on the car")
                        ToolTip.delay: theme.tipDelay
                        RowLayout {
                            anchors.fill: parent
                            anchors.rightMargin: theme.space2
                            spacing: theme.em * 0.5
                            TpClassStrip { tint: entry.classColor }
                            Text {
                                Layout.preferredWidth: theme.em * 3.6
                                text: entry.timeText
                                color: theme.dimOn(entryBack.color)
                                font.pointSize: theme.fontSmall
                                font.features: { "tnum": 1 }
                            }
                            Icon { glyph: entry.glyph; color: theme.tone(entry.tone); size: theme.em * 0.95 }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Text {
                                    Layout.fillWidth: true
                                    text: entry.title
                                    // Event of the past (replay): dim text, never faded
                                    color: entry.live ? theme.text : theme.dimOn(entryBack.color)
                                    font.weight: entry.unseen ? Font.Bold : Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                SmallText {
                                    Layout.fillWidth: true
                                    color: theme.dimOn(entryBack.color)
                                    text: entry.kindText + (entry.detail !== "" ? "  ·  " + entry.detail : "")
                                }
                            }
                            Rectangle {  // incident nobody looked at yet (title in bold too)
                                visible: entry.unseen
                                width: theme.em * 0.5
                                height: width
                                radius: width / 2
                                color: theme.accent
                            }
                            TpButton {  // instant replay (live), replay goes there (replay): room kept, shown on hover
                                id: replayButton
                                visible: entry.canReplay && backend.inSession
                                enabled: entry.showReplay
                                opacity: entry.showReplay ? 1 : 0
                                Layout.preferredWidth: Math.round(theme.em * 2.0)
                                Layout.preferredHeight: Math.round(theme.em * 2.0)
                                flat: true
                                glyph: ""  // video
                                fallback: "▶"
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
                        compact: true
                        glyph: ""  // history
                        title: i18n.tr("No events yet")
                        text: i18n.tr("Contacts, overtakes, pit stops and fastest laps are listed as the race goes on.")
                    }
                }
            }

            // Battles
            KeyList {
                id: battles
                objectName: "battleList"
                model: root.tab === 1 ? backend.battleRows : null  // hidden tab: no delegate kept up to date
                spacing: theme.space2
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
                Keys.onReturnPressed: if (currentItem) backend.cutToCar(currentItem.behindSlot)
                Keys.onEnterPressed: if (currentItem) backend.cutToCar(currentItem.behindSlot)
                delegate: Item {
                    id: fight
                    required property int index
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
                    readonly property bool current: ListView.isCurrentItem && battles.activeFocus
                    width: ListView.view.width - (battles.ScrollBar.vertical.visible ? battles.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.em * 3.6)
                    Accessible.role: Accessible.ListItem
                    Accessible.name: "P" + fight.position + ", " + fight.ahead + ", " + fight.behind + ", " + fight.gap
                                     + (fight.onAir ? ", " + i18n.tr("On Air") : "")
                    Rectangle {  // card; on air: loss tint & thicker frame, both kept while hovered
                        id: fightBack
                        anchors.fill: parent
                        radius: theme.radiusMd
                        color: fight.onAir ? Qt.tint(theme.raised, theme.tint(theme.loss, fightArea.containsMouse ? "selected" : theme.tintSubtle * 1.4))
                             : fightArea.containsMouse ? theme.hover : theme.raised
                        border.width: fight.onAir ? 2 : 1
                        border.color: fight.onAir ? theme.loss : theme.border
                        Behavior on color { ColorAnimation { duration: theme.motionFast } }
                    }
                    FocusRing { target: fightBack; visible: fight.current }
                    MouseArea {
                        id: fightArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { battles.currentIndex = fight.index; backend.cutToCar(fight.behindSlot) }
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.rightMargin: theme.em * 0.5
                        spacing: theme.em * 0.5
                        TpClassStrip { tint: fight.classColor }
                        ColumnLayout {
                            Layout.preferredWidth: theme.em * 3.2
                            spacing: 0
                            Text {
                                text: "P" + fight.position
                                color: theme.text
                                font.weight: Font.Bold
                                font.pointSize: theme.fontSubtitle
                            }
                            SmallText { Layout.fillWidth: true; text: fight.carClass; color: theme.dimOn(fightBack.color) }
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
                                spacing: theme.space2
                                Icon {  // closing: chevron down, opening: up (arrow without icon font)
                                    visible: fight.trend !== 0
                                    glyph: fight.trend < 0 ? "" : ""
                                    fallback: fight.trend < 0 ? "▼" : "▲"
                                    size: theme.em * 0.75
                                    color: fight.trend < 0 ? theme.loss : theme.gain
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: fight.gap
                                    color: fight.gapTone !== "" ? theme.tone(fight.gapTone) : theme.text
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                            SmallText {
                                Layout.alignment: Qt.AlignRight
                                color: theme.dimOn(fightBack.color)
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
                    compact: true
                    glyph: ""  // pulse
                    title: i18n.tr("No battle right now")
                    text: i18n.tr("Two cars of a class within the battle gap (races only).")
                }
            }

            // Classes
            ListView {
                id: classList
                clip: true
                model: root.tab === 2 ? backend.classRows : null
                spacing: theme.space2
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
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
                    width: ListView.view.width - (classList.ScrollBar.vertical.visible ? classList.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.em * 3.6)
                    radius: theme.radiusMd
                    border.width: 1
                    border.color: theme.border
                    color: theme.raised
                    RowLayout {
                        anchors.fill: parent
                        anchors.rightMargin: theme.em * 0.5
                        spacing: theme.em * 0.5
                        TpClassStrip { tint: classRow.classColor }
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
                            glyph: ""  // pulse
                            text: classRow.battles
                            tint: theme.accent
                            tip: i18n.tr("Battles")
                        }
                    }
                }
                EmptyState {
                    parent: classList
                    anchors.centerIn: parent
                    visible: classList.count === 0
                    compact: true
                    glyph: ""  // car
                    title: i18n.tr("No driver in session")
                }
            }

            // Pit stops & stints
            KeyList {
                id: pitList
                objectName: "pitList"
                model: root.tab === 3 ? backend.pitRows : null
                reuseItems: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                Keys.onReturnPressed: if (currentItem) backend.selectCar(currentItem.slot)
                Keys.onEnterPressed: if (currentItem) backend.selectCar(currentItem.slot)
                delegate: Item {
                    id: pitRow
                    required property int index
                    required property int slot
                    required property string number
                    required property string driver
                    required property string classColor
                    required property int stops
                    required property string lastStop
                    required property int stint
                    required property bool inPit
                    required property string status
                    readonly property bool current: ListView.isCurrentItem && pitList.activeFocus
                    property bool live: true  // recycled row: tint of other car shown at once (no fade)
                    width: ListView.view.width - (pitList.ScrollBar.vertical.visible ? pitList.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.row)
                    Accessible.role: Accessible.ListItem
                    Accessible.name: pitRow.driver + ", " + i18n.tr("%1 stops").arg(pitRow.stops) + (pitRow.inPit ? ", " + pitRow.status : "")
                    ListView.onPooled: live = false
                    ListView.onReused: live = true
                    TpListRow {  // in the pit lane: warning tint, status in bold
                        id: pitBack
                        anchors.fill: parent
                        animate: pitRow.live
                        hovered: pitArea.containsMouse
                        emphasized: pitRow.inPit
                        tint: theme.warning
                    }
                    FocusRing { target: pitBack; visible: pitRow.current }
                    MouseArea {
                        id: pitArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { pitList.currentIndex = pitRow.index; backend.selectCar(pitRow.slot) }
                        onDoubleClicked: backend.cutToCar(pitRow.slot)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.rightMargin: theme.space3
                        spacing: theme.em * 0.5
                        TpClassStrip { tint: pitRow.classColor }
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
                                color: pitRow.inPit ? theme.text : theme.dimOn(pitBack.color)
                                font.weight: pitRow.inPit ? Font.DemiBold : Font.Normal
                            }
                        }
                        ColumnLayout {
                            spacing: 0
                            Text {
                                Layout.alignment: Qt.AlignRight
                                text: i18n.tr("%1 stops").arg(pitRow.stops)
                                color: theme.text
                                font.pointSize: theme.fontSmall
                                font.features: { "tnum": 1 }
                            }
                            SmallText {
                                Layout.alignment: Qt.AlignRight
                                color: theme.dimOn(pitBack.color)
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
                    compact: true
                    glyph: ""  // car
                    title: i18n.tr("No pit stop yet")
                    text: i18n.tr("Pit stops seen during the race, with time in the pit lane and laps since.")
                }
            }
        }

        // Sheet of car picked in car list: at most 45 % of the screen (scrolls inside), collapsible
        DirectorSheet {
            Layout.fillWidth: true
            visible: backend.sheetCar.slot !== undefined
            maximumHeight: root.height * 0.45
        }
    }
}
