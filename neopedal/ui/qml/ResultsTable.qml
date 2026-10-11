import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Classification of session picked (class picked only): position (and places gained from grid in races),
// class, number, driver & team, car, laps, race time or gap (best lap gap in practice & qualifying), best lap
// (fastest in purple), pit stops, contacts. Player row tinted, car picked outlined.
// Click: pick car (its laps, highlighted on positions chart), double click: show its laps.
Item {
    id: table

    signal lapsWanted(string key)

    readonly property bool race: backend.isRace
    readonly property bool multiclass: backend.classChips.length > 0 && backend.classFilter === ""
    readonly property bool showCar: width > theme.em * 56
    readonly property real pad: theme.em * 0.6
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
    readonly property real wDriver: Math.max(width - pad * 2 - scrollWidth - wPos - wDelta - wClass - wNum - wLogo - wCar
                                             - wLaps - wGap - wBest - wPits - wInc, theme.em * 8)
    readonly property real scrollWidth: list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0

    component HeaderText: Text {
        property real cellWidth: 0
        property bool alignRight: false
        width: cellWidth
        visible: cellWidth > 0
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.8
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.3
        horizontalAlignment: alignRight ? Text.AlignRight : Text.AlignLeft
        rightPadding: alignRight ? theme.em * 0.5 : 0
        elide: Text.ElideRight
    }
    component Cell: Text {
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

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Column titles
        Row {
            Layout.fillWidth: true
            Layout.leftMargin: table.pad
            Layout.topMargin: theme.em * 0.6
            Layout.bottomMargin: theme.em * 0.35
            HeaderText { cellWidth: table.wPos; text: i18n.tr("Pos") }
            HeaderText { cellWidth: table.wDelta; text: "" }
            HeaderText { cellWidth: table.wClass; text: i18n.tr("Class") }
            HeaderText { cellWidth: table.wNum; text: "#" }
            HeaderText { cellWidth: table.wLogo; text: "" }
            HeaderText { cellWidth: table.wDriver; text: i18n.tr("Driver") }
            HeaderText { cellWidth: table.wCar; text: i18n.tr("Car") }
            HeaderText { cellWidth: table.wLaps; text: i18n.tr("Laps"); alignRight: true }
            HeaderText { cellWidth: table.wGap; text: table.race ? i18n.tr("Time / Gap") : i18n.tr("Gap"); alignRight: true }
            HeaderText { cellWidth: table.wBest; text: i18n.tr("Best Lap"); alignRight: true }
            HeaderText { cellWidth: table.wPits; text: i18n.tr("Pit Stops"); alignRight: true }
            HeaderText { cellWidth: table.wInc; text: i18n.tr("Inc."); alignRight: true }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border; opacity: 0.6 }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.classificationModel
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 } }

            delegate: Rectangle {
                id: row
                required property int index
                required property string key
                required property string posText
                required property int gridDelta
                required property string classText
                required property string classPosText
                required property string classColor
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

                width: ListView.view.width - table.scrollWidth
                height: Math.round(theme.em * 3.0)
                color: rowArea.containsMouse ? theme.hover
                     : player ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.13 : 0.1)
                     : index % 2 ? Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.025 : 0.03) : "transparent"
                border.width: selected ? 1.5 : 0
                border.color: theme.accent
                Behavior on color { ColorAnimation { duration: 100 } }
                ToolTip.visible: rowArea.containsMouse && (row.drivers !== "" || row.penalties > 0)
                ToolTip.text: [row.drivers !== "" ? i18n.tr("Drivers") + ": " + row.drivers : "",
                               row.penalties > 0 ? i18n.tr("Penalties") + ": " + row.penalties : ""]
                              .filter(function(part) { return part !== "" }).join("\n")
                ToolTip.delay: 600

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: backend.selectEntry(row.key)
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
                        font.pointSize: theme.fontPoint * 1.05
                    }
                    Cell {
                        cellWidth: table.wDelta
                        text: row.gridDelta > 0 ? "▲" + row.gridDelta : row.gridDelta < 0 ? "▼" + (-row.gridDelta) : ""
                        color: row.gridDelta > 0 ? theme.gain : theme.loss
                        font.pointSize: theme.fontPoint * 0.82
                    }
                    Item {
                        width: table.wClass
                        height: parent.height
                        visible: width > 0
                        Rectangle {
                            visible: row.classText !== ""
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(classLabel.implicitWidth + theme.em * 0.9, parent.width - theme.em * 0.5)
                            height: Math.round(theme.em * 1.55)
                            radius: theme.em * 0.35
                            color: Qt.rgba(Qt.color(row.classColor).r, Qt.color(row.classColor).g, Qt.color(row.classColor).b, 0.22)
                            border.width: 1
                            border.color: row.classColor
                            Text {
                                id: classLabel
                                anchors.centerIn: parent
                                width: Math.min(implicitWidth, parent.width - theme.em * 0.6)
                                text: row.classText + (row.classPosText !== "" ? " " + row.classPosText : "")
                                color: theme.text
                                font.pointSize: theme.fontPoint * 0.78
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                            }
                        }
                    }
                    Cell {
                        cellWidth: table.wNum
                        text: row.number !== "" ? "#" + row.number : ""
                        color: theme.dimText
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
                            color: theme.text
                            font.weight: row.player ? Font.Bold : Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            width: parent.width - theme.em * 0.5
                            text: row.team
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.82
                            elide: Text.ElideRight
                        }
                    }
                    Cell {
                        cellWidth: table.wCar
                        text: row.car
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.9
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
                            color: row.gapTone === "loss" ? theme.loss : row.gapTone === "dim" ? theme.dimText : theme.text
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
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                            elide: Text.ElideRight
                        }
                    }
                    Cell {
                        cellWidth: table.wBest
                        alignRight: true
                        text: row.bestText
                        color: row.bestTone === "purple" ? theme.purple : theme.text
                        font.weight: row.bestTone === "purple" ? Font.Bold : Font.Normal
                    }
                    Cell {
                        cellWidth: table.wPits
                        alignRight: true
                        text: row.pits
                        color: row.pits > 0 ? theme.text : theme.dimText
                    }
                    Item {
                        width: table.wInc
                        height: parent.height
                        Row {
                            anchors.right: parent.right
                            anchors.rightMargin: theme.em * 0.5
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: theme.em * 0.25
                            Icon {
                                visible: row.penalties > 0
                                glyph: ""  // warning
                                size: theme.em * 0.8
                                color: theme.warning
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: row.contacts
                                color: row.contacts > 0 ? theme.text : theme.dimText
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
