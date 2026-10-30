import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Classification of session picked (class picked only): position (and places gained from grid in races),
// class, number, driver & team, car, laps, race time or gap (best lap gap in practice & qualifying), best lap
// (fastest in purple & ◆ mark), pit stops, contacts. Player row tinted, car picked outlined.
// Click (or Tab then Up / Down): pick car (its laps, highlighted on positions chart), double click or Enter: show
// its laps. Narrow page: the table scrolls sideways (driver column keeps 8 em at least).
Item {
    id: table

    signal lapsWanted(string key)

    readonly property bool race: backend.isRace
    readonly property bool multiclass: backend.classChips.length > 0 && backend.classFilter === ""
    readonly property bool showCar: width > theme.bpNarrow
    readonly property real pad: theme.space4
    readonly property real wPos: theme.em * 2.6
    readonly property real wDelta: race ? theme.em * 2.6 : 0
    readonly property real wClass: multiclass ? theme.em * 6.6 : 0
    readonly property real wNum: theme.em * 3.0
    readonly property real wLogo: theme.em * 2.6  // car brand logo of game
    readonly property real wCar: showCar ? theme.em * 10.5 : 0
    readonly property real wLaps: theme.em * 3.2
    readonly property real wGap: theme.em * 7.4
    readonly property real wBest: theme.em * 6.6
    readonly property real wPits: race ? theme.em * 4.6 : 0
    readonly property real wInc: theme.em * 3.4
    readonly property real fixedWidth: wPos + wDelta + wClass + wNum + wLogo + wCar + wLaps + wGap + wBest + wPits + wInc
    readonly property real wDriver: Math.max(scroll.width - pad * 2 - scrollWidth - fixedWidth, theme.em * 8)
    readonly property real rowWidth: pad * 2 + fixedWidth + wDriver
    readonly property real scrollWidth: list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0

    component Cell: Text {
        textFormat: Text.PlainText  // text of each use: names & values, never markup
        property real cellWidth: 0
        property bool alignRight: false
        width: cellWidth
        visible: cellWidth > 0
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
        color: theme.text
        font.features: { "tnum": 1 }
        horizontalAlignment: alignRight ? Text.AlignRight : Text.AlignLeft
        rightPadding: alignRight ? theme.em * 0.5 : 0
        elide: Text.ElideRight
    }
    TpLapTime { id: markProbe; visible: false }  // room of record mark: header lines up with times

    component Header: TpHeaderCell {
        property real cellWidth: 0
        width: cellWidth
        visible: cellWidth > 0
    }

    Flickable {  // wide table scrolls sideways on narrow pages
        id: scroll
        anchors.fill: parent
        contentWidth: Math.max(width, table.rowWidth + table.scrollWidth)
        contentHeight: height
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.HorizontalFlick
        interactive: contentWidth > width
        clip: true
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            width: scroll.contentWidth
            height: scroll.height
            spacing: 0

            // Column titles
            Row {
                Layout.leftMargin: table.pad
                Layout.topMargin: theme.space4
                Layout.bottomMargin: theme.space2
                Header { cellWidth: table.wPos; text: i18n.tr("Pos") }
                Header { cellWidth: table.wDelta; text: ""; tip: i18n.tr("Places gained from the grid") }
                Header { cellWidth: table.wClass; text: i18n.tr("Class") }
                Header { cellWidth: table.wNum; text: "#" }
                Header { cellWidth: table.wLogo; text: "" }
                Header { cellWidth: table.wDriver; text: i18n.tr("Driver") }
                Header { cellWidth: table.wCar; text: i18n.tr("Car") }
                Header { cellWidth: table.wLaps; text: i18n.tr("Laps"); align: Qt.AlignRight }
                Header { cellWidth: table.wGap; text: table.race ? i18n.tr("Time / Gap") : i18n.tr("Gap"); align: Qt.AlignRight }
                Header { cellWidth: table.wBest; text: i18n.tr("Best Lap"); align: Qt.AlignRight
                         rightPadding: markProbe.markRoom }
                Header { cellWidth: table.wPits; text: i18n.tr("Pit Stops"); align: Qt.AlignRight }
                Header { cellWidth: table.wInc; text: i18n.tr("Inc."); tip: i18n.tr("Contacts"); align: Qt.AlignRight }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border }

            ListView {
                id: list
                objectName: "classification"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: backend.classificationModel
                reuseItems: true  // rows scrolled out fed again with other cars (see delegate onPooled)
                boundsBehavior: Flickable.StopAtBounds
                activeFocusOnTab: true
                currentIndex: -1
                highlightFollowsCurrentItem: false
                Accessible.role: Accessible.Table
                Accessible.name: i18n.tr("Classification")
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }
                // Keyboard: Up / Down pick the car above / below, Enter shows its laps
                function pick(index) {
                    if (index < 0 || index >= count) return
                    currentIndex = index
                    positionViewAtIndex(index, ListView.Contain)
                    if (currentItem) backend.selectEntry(currentItem.key)
                }
                Keys.onUpPressed: pick(Math.max(0, currentIndex - 1))
                Keys.onDownPressed: pick(Math.min(count - 1, currentIndex + 1))
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_Home) pick(0)
                    else if (event.key === Qt.Key_End) pick(count - 1)
                    else return
                    event.accepted = true
                }
                Keys.onReturnPressed: if (currentItem) table.lapsWanted(currentItem.key)
                Keys.onEnterPressed: if (currentItem) table.lapsWanted(currentItem.key)

                delegate: Item {
                    id: row
                    required property int index
                    required property string key
                    required property string posText
                    required property int gridDelta
                    required property string classText
                    required property string classPosText
                    required property string classColor
                    required property string classAlias
                    required property string number
                    required property string driver
                    required property string team
                    required property string drivers
                    required property string car
                    required property int laps
                    required property string gapText
                    required property string gapTone
                    required property string reasonText
                    required property string bestText
                    required property string bestTone
                    required property int pits
                    required property int contacts
                    required property int penalties
                    required property bool player
                    required property bool selected
                    required property string brandLogo
                    required property string accessibleText  // position, driver, team, gap & best lap (backend)
                    // Reused row: fed other car values at once (index may come after selected), no color animation
                    property bool live: true
                    ListView.onPooled: { live = false; opacity = 1 }  // add transition may have been running
                    ListView.onReused: {
                        live = true
                        if (selected) list.currentIndex = index
                    }

                    width: table.rowWidth
                    height: Math.round(theme.row)
                    onSelectedChanged: if (selected && live) list.currentIndex = index  // keyboard goes on from here
                    Component.onCompleted: if (selected) list.currentIndex = index
                    Accessible.role: Accessible.Row
                    Accessible.name: row.accessibleText
                    Accessible.selected: selected
                    ToolTip.visible: row.live && rowArea.containsMouse && (row.drivers !== "" || row.penalties > 0)  // pooled: hidden
                    ToolTip.text: !rowArea.containsMouse ? ""
                                  : [row.drivers !== "" ? i18n.tr("Drivers") + ": " + row.drivers : "",
                                     row.penalties > 0 ? i18n.tr("Penalties") + ": " + row.penalties : ""]
                                    .filter(function(part) { return part !== "" }).join("\n")
                    ToolTip.delay: theme.tipDelay

                    TpListRow {  // player: own tint & accent bar; car picked: selected tint & outline
                        id: surface
                        anchors.fill: parent
                        animate: row.live
                        radius: theme.radiusSm
                        hovered: rowArea.containsMouse
                        selected: row.selected
                        emphasized: row.player
                        striped: row.index % 2 === 1
                        border.width: row.selected ? 1.5 : 0
                        border.color: theme.accent
                    }
                    FocusRing {
                        target: surface
                        anchors.margins: 0
                        visible: list.activeFocus && row.ListView.isCurrentItem
                    }
                    MouseArea {
                        id: rowArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            list.forceActiveFocus()
                            list.currentIndex = row.index
                            backend.selectEntry(row.key)
                        }
                        onDoubleClicked: table.lapsWanted(row.key)
                    }
                    Rectangle {  // player: accent bar
                        visible: row.player
                        width: Math.round(theme.em * 0.22)
                        height: parent.height
                        color: theme.accent
                    }

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: table.pad
                        Cell {
                            cellWidth: table.wPos
                            text: row.posText
                            font.weight: Font.Bold
                            font.pointSize: theme.fontSubtitle
                        }
                        Cell {  // places gained or lost: arrow & number, color only adds to them
                            cellWidth: table.wDelta
                            text: row.gridDelta > 0 ? "▲" + row.gridDelta : row.gridDelta < 0 ? "▼" + (-row.gridDelta) : ""
                            color: row.gridDelta > 0 ? theme.gain : theme.loss
                            font.pointSize: theme.fontSmall
                        }
                        Item {
                            width: table.wClass
                            height: parent.height
                            visible: width > 0
                            TpClassBadge {  // as overlays: alias on class color, position in class
                                visible: row.classText !== ""
                                anchors.verticalCenter: parent.verticalCenter
                                label: row.classText !== "" ? row.classAlias : ""
                                fullName: row.classText
                                fill: row.classColor
                                position: row.classPosText
                            }
                        }
                        Cell {
                            cellWidth: table.wNum
                            text: row.number !== "" ? "#" + row.number : ""
                            color: theme.dimOn(surface.color)
                        }
                        Item {  // car brand logo of game
                            width: table.wLogo
                            height: parent.height
                            GameLogo {
                                anchors.verticalCenter: parent.verticalCenter
                                source: row.brandLogo
                                boxWidth: theme.em * 2.1
                                boxHeight: theme.em * 1.35
                            }
                        }
                        Column {
                            width: table.wDriver
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                width: parent.width - theme.em * 0.5
                                text: row.driver
                                textFormat: Text.PlainText
                                color: theme.text
                                font.weight: row.player ? Font.Bold : Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width - theme.em * 0.5
                                text: row.team
                                textFormat: Text.PlainText
                                color: theme.dimOn(surface.color)
                                font.pointSize: theme.fontSmall
                                elide: Text.ElideRight
                            }
                        }
                        Cell {
                            cellWidth: table.wCar
                            text: row.car
                            color: theme.dimOn(surface.color)
                            font.pointSize: theme.fontLabel
                        }
                        Cell {
                            cellWidth: table.wLaps
                            alignRight: true
                            text: row.laps
                        }
                        Column {
                            width: table.wGap
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                width: parent.width
                                rightPadding: theme.em * 0.5
                                horizontalAlignment: Text.AlignRight
                                text: row.gapText
                                textFormat: Text.PlainText
                                color: row.gapTone === "loss" ? theme.loss : row.gapTone === "dim" ? theme.dimOn(surface.color) : theme.text
                                font.weight: row.index === 0 ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                            }
                            Text {
                                visible: row.reasonText !== ""
                                width: parent.width
                                rightPadding: theme.em * 0.5
                                horizontalAlignment: Text.AlignRight
                                text: row.reasonText
                                textFormat: Text.PlainText
                                color: theme.dimOn(surface.color)
                                font.pointSize: theme.fontCaption
                                elide: Text.ElideRight
                            }
                        }
                        TpLapTime {  // fastest lap of the session: purple & ◆ mark (shared record mark)
                            width: table.wBest
                            height: implicitHeight
                            anchors.verticalCenter: parent ? parent.verticalCenter : undefined
                            text: row.bestText
                            record: row.bestTone === "purple" ? "session" : ""
                        }
                        Cell {
                            cellWidth: table.wPits
                            alignRight: true
                            text: row.pits
                            color: row.pits > 0 ? theme.text : theme.dimOn(surface.color)
                        }
                        Item {
                            width: table.wInc
                            height: parent.height
                            Row {
                                anchors.right: parent.right
                                anchors.rightMargin: theme.em * 0.5
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: theme.space2
                                Icon {
                                    visible: row.penalties > 0
                                    glyph: ""  // warning
                                    fallback: "!"
                                    size: theme.iconSm
                                    color: theme.warning
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: row.contacts
                                    textFormat: Text.PlainText
                                    color: row.contacts > 0 ? theme.text : theme.dimOn(surface.color)
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
}
