import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Laps of car picked: car picker, driver & team, best / average / consistency of clean laps, theoretical best,
// top speed; then every lap: place, time (session best purple ◆, own best green ●: marks too, never color
// alone), gap to own best, sectors (same colors & marks), top speed, tyre compound, pit lane, energy (or fuel)
// used & tyre wear (own car only). Session replay: Tab to the laps, Up / Down & Enter watch a lap.
Item {
    id: laps

    readonly property var info: backend.driverInfo
    readonly property bool usage: backend.lapColumns.usage === true
    readonly property bool wear: backend.lapColumns.wear === true
    readonly property real pad: theme.space4
    readonly property real scrollWidth: list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0
    readonly property real wLap: theme.em * 3.0
    readonly property real wPos: theme.em * 3.0
    readonly property real wTime: theme.em * 7.0
    readonly property real wDelta: theme.em * 5.6
    readonly property real wSector: theme.em * 5.6
    readonly property real wSpeed: theme.em * 4.6
    readonly property real wTyre: theme.em * 5.6
    readonly property real wPit: theme.em * 3.0
    readonly property real wUsage: usage ? theme.em * 5.0 : 0
    readonly property real wWear: wear ? theme.em * 4.6 : 0
    readonly property bool replay: (backend.sessionHeader.replay || "") !== ""  // session replay (LMU)
    readonly property real wWatch: replay ? theme.em * 2.6 : 0
    readonly property real markRoom: theme.em * 1.1  // record mark after the time (◆ ●), kept on every row

    component Header: TpHeaderCell {
        property real cellWidth: 0
        width: cellWidth
        visible: cellWidth > 0
        align: Qt.AlignRight
    }
    component Cell: Text {
        property real cellWidth: 0
        property string tone: ""
        property bool marked: false  // column with record marks (times & sectors)
        width: cellWidth
        visible: cellWidth > 0
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
        color: tone === "purple" ? theme.purple : tone === "gain" ? theme.gain : tone === "dim" ? theme.dimText : theme.text
        font.weight: tone === "purple" || tone === "gain" ? Font.DemiBold : Font.Normal
        font.features: { "tnum": 1 }
        horizontalAlignment: Text.AlignRight
        rightPadding: marked ? laps.markRoom : theme.em * 0.6
        elide: Text.ElideRight
        Text {  // session best ◆, own best ●
            visible: parent.marked && (parent.tone === "purple" || parent.tone === "gain")
            anchors.right: parent.right
            anchors.rightMargin: theme.space2
            anchors.verticalCenter: parent.verticalCenter
            text: parent.tone === "purple" ? "◆" : "●"
            color: parent.color
            font.pointSize: theme.fontMicro
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: theme.space4
        spacing: theme.space3

        // Car picked
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: laps.pad
            Layout.rightMargin: laps.pad
            spacing: theme.space4
            TpCombo {
                Layout.preferredWidth: theme.em * 16
                model: backend.driverOptions
                textRole: "text"
                currentIndex: backend.driverIndex
                tip: i18n.tr("Car")
                Accessible.name: i18n.tr("Car")
                onActivated: function(index) { backend.selectEntryAt(index) }  // list not read again
            }
            ColorDot {
                visible: laps.info.color !== undefined
                color: laps.info.color || "transparent"
                size: Math.round(theme.em * 0.7)
            }
            GameLogo {  // car brand logo of game
                source: laps.info.brandLogo || ""
                boxWidth: theme.em * 2.4
                boxHeight: theme.em * 1.4
            }
            Text {
                Layout.fillWidth: true
                text: [laps.info.team || "", laps.info.car || "", laps.info.drivers ? i18n.tr("Drivers") + ": " + laps.info.drivers : ""]
                      .filter(function(part) { return part !== "" }).join(" · ")
                color: theme.dimText
                elide: Text.ElideRight
            }
            GamePicture {  // car picture of game
                source: laps.info.carPicture || ""
                boxHeight: theme.em * 2.4
                aspect: 1.6
                crop: false
            }
        }

        // Lap figures
        Flow {
            Layout.fillWidth: true
            Layout.leftMargin: laps.pad
            Layout.rightMargin: laps.pad
            spacing: theme.space6
            Repeater {
                model: backend.lapSummary
                TpKeyValue {
                    required property var modelData
                    layout: "stack"
                    large: true
                    label: modelData.label
                    value: modelData.value
                    Layout.fillWidth: false
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            Flickable {  // wide table scrolls sideways on narrow pages
                anchors.fill: parent
                contentWidth: Math.max(width, tableColumn.implicitWidth)
                contentHeight: height
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.HorizontalFlick
                interactive: contentWidth > width
                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    id: tableColumn
                    width: Math.max(parent.width, implicitWidth)
                    height: parent.height
                    spacing: 0

                    Row {
                        Layout.leftMargin: laps.pad
                        Layout.bottomMargin: theme.space2
                        Header { cellWidth: laps.wLap; text: i18n.tr("Lap") }
                        Header { cellWidth: laps.wPos; text: i18n.tr("Pos") }
                        Header { cellWidth: laps.wTime; text: i18n.tr("Time"); rightPadding: laps.markRoom - theme.space1 }
                        Header { cellWidth: laps.wDelta; text: i18n.tr("Gap") }
                        Header { cellWidth: laps.wSector; text: "S1"; rightPadding: laps.markRoom - theme.space1 }
                        Header { cellWidth: laps.wSector; text: "S2"; rightPadding: laps.markRoom - theme.space1 }
                        Header { cellWidth: laps.wSector; text: "S3"; rightPadding: laps.markRoom - theme.space1 }
                        Header { cellWidth: laps.wSpeed; text: backend.speedUnit }
                        Header { cellWidth: laps.wTyre; text: i18n.tr("Tyre") }
                        Header { cellWidth: laps.wPit; text: i18n.tr("Pit") }
                        Header { cellWidth: laps.wUsage; text: i18n.tr("Used") }
                        Header { cellWidth: laps.wWear; text: i18n.tr("Tread") }
                        Header { cellWidth: laps.wWatch; text: "" }
                    }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border }

                    ListView {
                        id: list
                        objectName: "lapList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: laps.pad + laps.wLap + laps.wPos + laps.wTime + laps.wDelta + laps.wSector * 3
                                               + laps.wSpeed + laps.wTyre + laps.wPit + laps.wUsage + laps.wWear + laps.wWatch
                                               + laps.scrollWidth
                        clip: true
                        model: backend.lapModel
                        reuseItems: true  // rows scrolled out fed again with other laps (see delegate onPooled)
                        boundsBehavior: Flickable.StopAtBounds
                        activeFocusOnTab: count > 0
                        currentIndex: -1
                        keyNavigationEnabled: true
                        highlightFollowsCurrentItem: false
                        Accessible.role: Accessible.Table
                        Accessible.name: i18n.tr("Laps")
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
                        Keys.onReturnPressed: if (laps.replay && currentItem) backend.watchLap(currentItem.lap)
                        Keys.onEnterPressed: if (laps.replay && currentItem) backend.watchLap(currentItem.lap)

                        delegate: Item {
                            id: row
                            required property int index
                            required property int lap
                            required property string posText
                            required property string timeText
                            required property string timeTone
                            required property string deltaText
                            required property string s1
                            required property string s2
                            required property string s3
                            required property string s1Tone
                            required property string s2Tone
                            required property string s3Tone
                            required property string speedText
                            required property string compound
                            required property bool pit
                            required property string usageText
                            required property string wearText
                            required property string accessibleText  // lap, time, record & pit (backend)
                            // Reused row: fed other lap values at once, no color animation from the old lap
                            property bool live: true
                            ListView.onPooled: live = false
                            ListView.onReused: live = true

                            width: ListView.view.width - laps.scrollWidth
                            height: Math.round(theme.rowCompact)
                            Accessible.role: Accessible.Row
                            Accessible.name: row.accessibleText

                            TpListRow {
                                id: surface
                                anchors.fill: parent
                                animate: row.live
                                radius: theme.radiusSm
                                hovered: rowHover.hovered
                                striped: row.index % 2 === 1
                            }
                            HoverHandler { id: rowHover }
                            FocusRing {
                                target: surface
                                anchors.margins: 0
                                visible: list.activeFocus && row.ListView.isCurrentItem
                            }
                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: laps.pad
                                Cell { cellWidth: laps.wLap; text: row.lap; tone: "dim" }
                                Cell { cellWidth: laps.wPos; text: row.posText }
                                Cell { cellWidth: laps.wTime; text: row.timeText; tone: row.timeTone; marked: true }
                                Cell { cellWidth: laps.wDelta; text: row.deltaText; tone: "dim" }
                                Cell { cellWidth: laps.wSector; text: row.s1; tone: row.s1Tone; marked: true }
                                Cell { cellWidth: laps.wSector; text: row.s2; tone: row.s2Tone; marked: true }
                                Cell { cellWidth: laps.wSector; text: row.s3; tone: row.s3Tone; marked: true }
                                Cell { cellWidth: laps.wSpeed; text: row.speedText }
                                Item {  // compound badge (as overlays) & name, right aligned
                                    width: laps.wTyre
                                    height: parent.height
                                    Row {
                                        anchors.right: parent.right
                                        anchors.rightMargin: theme.em * 0.6
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: theme.space2
                                        TpCompound { name: row.compound; anchors.verticalCenter: parent.verticalCenter }
                                        Text {
                                            text: row.compound
                                            color: theme.dimOn(surface.color)
                                            width: Math.min(implicitWidth, laps.wTyre - theme.em * 2)
                                            elide: Text.ElideRight
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                    }
                                }
                                Item {
                                    width: laps.wPit
                                    height: parent.height
                                    Pill {
                                        visible: row.pit
                                        anchors.right: parent.right
                                        anchors.rightMargin: theme.em * 0.6
                                        anchors.verticalCenter: parent.verticalCenter
                                        size: "sm"
                                        text: i18n.tr("PIT")
                                        tint: theme.warning
                                    }
                                }
                                Cell { cellWidth: laps.wUsage; text: row.usageText }
                                Cell { cellWidth: laps.wWear; text: row.wearText }
                                Item {
                                    width: laps.wWatch
                                    height: parent.height
                                    visible: laps.replay
                                    TpButton {  // replay of session at start of this lap, camera on car
                                        anchors.centerIn: parent
                                        flat: true
                                        size: "sm"
                                        glyph: ""  // play
                                        fallback: "▶"
                                        tip: i18n.tr("Watch lap in replay")
                                        onClicked: backend.watchLap(row.lap)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            TpStateView {
                anchors.centerIn: parent
                empty: list.count === 0
                compact: true
                glyph: ""  // stopwatch
                title: i18n.tr("No lap completed")
            }
        }
    }
}
