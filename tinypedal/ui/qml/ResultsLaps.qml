import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Laps of car picked: car picker, driver & team, best / average / consistency of clean laps, theoretical best,
// top speed; then every lap: place, time (session best purple, own best green), gap to own best, sectors (same
// colors), top speed, tyre compound, pit lane, energy (or fuel) used & tyre wear (own car only).
Item {
    id: laps

    readonly property var info: backend.driverInfo
    readonly property bool usage: backend.lapColumns.usage === true
    readonly property bool wear: backend.lapColumns.wear === true
    readonly property real pad: theme.em * 0.6
    readonly property real scrollWidth: list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0
    readonly property real wLap: theme.em * 3.0
    readonly property real wPos: theme.em * 3.0
    readonly property real wTime: theme.em * 6.4
    readonly property real wDelta: theme.em * 5.6
    readonly property real wSector: theme.em * 5.0
    readonly property real wSpeed: theme.em * 4.6
    readonly property real wTyre: theme.em * 5.6
    readonly property real wPit: theme.em * 3.0
    readonly property real wUsage: usage ? theme.em * 5.0 : 0
    readonly property real wWear: wear ? theme.em * 4.6 : 0

    component HeaderText: Text {
        property real cellWidth: 0
        width: cellWidth
        visible: cellWidth > 0
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.8
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.3
        horizontalAlignment: Text.AlignRight
        rightPadding: theme.em * 0.6
        elide: Text.ElideRight
    }
    component Cell: Text {
        property real cellWidth: 0
        property string tone: ""
        width: cellWidth
        visible: cellWidth > 0
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
        color: tone === "purple" ? theme.purple : tone === "gain" ? theme.gain : tone === "dim" ? theme.dimText : theme.text
        font.weight: tone === "purple" || tone === "gain" ? Font.DemiBold : Font.Normal
        font.features: { "tnum": 1 }
        horizontalAlignment: Text.AlignRight
        rightPadding: theme.em * 0.6
        elide: Text.ElideRight
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: theme.em * 0.6
        spacing: theme.em * 0.5

        // Car picked
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: laps.pad
            Layout.rightMargin: laps.pad
            spacing: theme.em * 0.6
            TpCombo {
                Layout.preferredWidth: theme.em * 16
                model: backend.driverOptions.map(function(option) { return option.text })
                currentIndex: backend.driverIndex
                tip: i18n.tr("Car")
                onActivated: function(index) { backend.selectEntry(backend.driverOptions[index].key) }
            }
            Rectangle {
                visible: laps.info.color !== undefined
                implicitWidth: Math.round(theme.em * 0.7)
                implicitHeight: implicitWidth
                radius: width / 2
                color: laps.info.color || "transparent"
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
            spacing: theme.em * 1.4
            Repeater {
                model: backend.lapSummary
                Column {
                    required property var modelData
                    Text {
                        text: modelData.label
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.78
                        font.capitalization: Font.AllUppercase
                        font.letterSpacing: 0.3
                    }
                    Text {
                        text: modelData.value
                        color: theme.text
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontPoint * 1.08
                        font.features: { "tnum": 1 }
                    }
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
                        Layout.bottomMargin: theme.em * 0.35
                        HeaderText { cellWidth: laps.wLap; text: i18n.tr("Lap") }
                        HeaderText { cellWidth: laps.wPos; text: i18n.tr("Pos") }
                        HeaderText { cellWidth: laps.wTime; text: i18n.tr("Time") }
                        HeaderText { cellWidth: laps.wDelta; text: i18n.tr("Gap") }
                        HeaderText { cellWidth: laps.wSector; text: "S1" }
                        HeaderText { cellWidth: laps.wSector; text: "S2" }
                        HeaderText { cellWidth: laps.wSector; text: "S3" }
                        HeaderText { cellWidth: laps.wSpeed; text: backend.speedUnit }
                        HeaderText { cellWidth: laps.wTyre; text: i18n.tr("Tyre") }
                        HeaderText { cellWidth: laps.wPit; text: i18n.tr("Pit") }
                        HeaderText { cellWidth: laps.wUsage; text: i18n.tr("Used") }
                        HeaderText { cellWidth: laps.wWear; text: i18n.tr("Tread") }
                    }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border; opacity: 0.6 }

                    ListView {
                        id: list
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: laps.pad + laps.wLap + laps.wPos + laps.wTime + laps.wDelta + laps.wSector * 3
                                               + laps.wSpeed + laps.wTyre + laps.wPit + laps.wUsage + laps.wWear + laps.scrollWidth
                        clip: true
                        model: backend.lapModel
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Rectangle {
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

                            width: ListView.view.width - laps.scrollWidth
                            height: Math.round(theme.em * 2.2)
                            color: index % 2 ? Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.025 : 0.03) : "transparent"

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: laps.pad
                                Cell { cellWidth: laps.wLap; text: row.lap; tone: "dim" }
                                Cell { cellWidth: laps.wPos; text: row.posText }
                                Cell { cellWidth: laps.wTime; text: row.timeText; tone: row.timeTone }
                                Cell { cellWidth: laps.wDelta; text: row.deltaText; tone: "dim" }
                                Cell { cellWidth: laps.wSector; text: row.s1; tone: row.s1Tone }
                                Cell { cellWidth: laps.wSector; text: row.s2; tone: row.s2Tone }
                                Cell { cellWidth: laps.wSector; text: row.s3; tone: row.s3Tone }
                                Cell { cellWidth: laps.wSpeed; text: row.speedText }
                                Cell { cellWidth: laps.wTyre; text: row.compound; tone: "dim" }
                                Item {
                                    width: laps.wPit
                                    height: parent.height
                                    Rectangle {
                                        visible: row.pit
                                        anchors.right: parent.right
                                        anchors.rightMargin: theme.em * 0.6
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: pitText.implicitWidth + theme.em * 0.7
                                        height: Math.round(theme.em * 1.4)
                                        radius: theme.em * 0.3
                                        color: Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.18)
                                        Text {
                                            id: pitText
                                            anchors.centerIn: parent
                                            text: i18n.tr("PIT")
                                            color: theme.warning
                                            font.pointSize: theme.fontPoint * 0.72
                                            font.weight: Font.Bold
                                        }
                                    }
                                }
                                Cell { cellWidth: laps.wUsage; text: row.usageText }
                                Cell { cellWidth: laps.wWear; text: row.wearText }
                            }
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: list.count === 0
                text: i18n.tr("No lap completed")
                color: theme.dimText
            }
        }
    }
}
