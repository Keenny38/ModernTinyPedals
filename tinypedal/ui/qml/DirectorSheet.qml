import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Sheet of the car picked in the car list: place, intervals ahead & behind, laps, pit stops, stint, contacts,
// penalties, commentator note (kept between sessions, by driver). Camera button: cut to car.
Rectangle {
    id: sheetCard
    readonly property var car: backend.sheet

    implicitHeight: sheetColumn.implicitHeight + theme.em * 1.1
    radius: theme.em * 0.55
    color: theme.raised
    border.width: 1
    border.color: car.onAir ? theme.loss : theme.border

    component Stat: ColumnLayout {
        property string label: ""
        property string value: ""
        property color valueColor: theme.text
        Layout.fillWidth: true
        Layout.preferredWidth: 1  // stats share the row evenly
        spacing: 0
        Text {
            Layout.fillWidth: true
            text: parent.label
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.75
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: parent.value !== "" ? parent.value : "-"
            color: parent.valueColor
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
        }
    }

    ColumnLayout {
        id: sheetColumn
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.55 }
        spacing: theme.em * 0.4

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Rectangle {
                implicitWidth: Math.round(theme.em * 0.32)
                implicitHeight: Math.round(theme.em * 2.4)
                radius: width / 2
                color: sheetCard.car.classColor || theme.border
            }
            GamePicture {  // car picture of game
                source: sheetCard.car.carPicture || ""
                boxHeight: theme.em * 2.6
                aspect: 1.6
                crop: false
            }
            GameLogo { source: sheetCard.car.brandLogo || ""; boxWidth: theme.em * 2.0; boxHeight: theme.em * 1.3 }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Text {
                    Layout.fillWidth: true
                    text: (sheetCard.car.number ? "#" + sheetCard.car.number + "  " : "") + (sheetCard.car.driver || "")
                    color: theme.text
                    font.weight: Font.Bold
                    font.pointSize: theme.fontPoint * 1.1
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    text: [sheetCard.car.team, sheetCard.car.vehicle].filter(function(part) { return part }).join(" · ")
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.8
                    elide: Text.ElideRight
                }
            }
            Pill {
                visible: (sheetCard.car.status || "") !== ""
                text: sheetCard.car.status || ""
                tint: sheetCard.car.statusTone === "loss" ? theme.loss : sheetCard.car.statusTone === "gain" ? theme.gain : theme.warning
            }
            TpButton {
                glyph: ""  // camera
                accent: sheetCard.car.onAir === true
                tip: i18n.tr("Cut to this car (double click)")
                onClicked: backend.cutToCar(sheetCard.car.slot)
            }
            TpButton {
                glyph: ""  // close
                flat: true
                tip: i18n.tr("Close")
                onClicked: backend.selectCar(sheetCard.car.slot)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Stat {
                label: i18n.tr("Class")
                value: sheetCard.car.classPosition ? "P" + sheetCard.car.classPosition + " " + sheetCard.car.carClass
                       + (sheetCard.car.gained > 0 ? "  ▲" + sheetCard.car.gained : sheetCard.car.gained < 0 ? "  ▼" + (-sheetCard.car.gained) : "")
                       : ""
            }
            Stat { label: i18n.tr("Overall"); value: sheetCard.car.position ? "P" + sheetCard.car.position : "" }
            Stat { label: i18n.tr("Laps"); value: sheetCard.car.laps !== undefined ? String(sheetCard.car.laps) : "" }
            Stat { label: i18n.tr("Current stint"); value: sheetCard.car.stint >= 0 ? i18n.tr("%1 laps").arg(sheetCard.car.stint) : "" }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Stat { label: i18n.tr("Ahead"); value: sheetCard.car.intervalAhead || ""; valueColor: theme.text }
            Stat { label: i18n.tr("Behind"); value: sheetCard.car.intervalBehind ? sheetCard.car.intervalBehind.replace("+", "-") : "" }
            Stat { label: i18n.tr("Best"); value: sheetCard.car.best || "" }
            Stat { label: i18n.tr("Last"); value: sheetCard.car.last || "" }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Stat { label: i18n.tr("Pit Stops"); value: sheetCard.car.pits !== undefined ? String(sheetCard.car.pits) : "" }
            Stat {
                label: i18n.tr("Contacts")
                value: sheetCard.car.incidents !== undefined ? String(sheetCard.car.incidents) : ""
                valueColor: sheetCard.car.incidents > 0 ? theme.warning : theme.text
            }
            Stat {
                label: i18n.tr("Penalties")
                value: sheetCard.car.penalties !== undefined ? String(sheetCard.car.penalties) : ""
                valueColor: sheetCard.car.penalties > 0 ? theme.loss : theme.text
            }
            Stat { label: i18n.tr("Tyres"); value: sheetCard.car.tyres || "" }
        }
        // Sectors of the lap (as they complete, else last lap): purple best of class, green personal best
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Repeater {
                model: sheetCard.car.sectors || []
                delegate: Stat {
                    required property var modelData
                    required property int index
                    label: "S" + (index + 1)
                    value: modelData.text
                    valueColor: modelData.tone === "fastest" ? theme.purple : modelData.tone === "gain" ? theme.gain
                              : modelData.tone === "yellow" ? theme.gold : theme.text
                }
            }
            TpButton {
                objectName: "lapHistoryButton"
                glyph: ""  // stopwatch
                text: i18n.tr("Laps") + (sheetCard.car.lapCount ? " " + sheetCard.car.lapCount : "")
                tip: i18n.tr("Lap History")
                onClicked: backend.showLaps(sheetCard.car.slot)
            }
        }
        Text {  // energy (else fuel) left, used per lap, laps left
            Layout.fillWidth: true
            visible: (sheetCard.car.energy || "") !== ""
            text: i18n.tr("Energy") + "  " + (sheetCard.car.energy || "")
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.85
            elide: Text.ElideRight
        }
        Text {  // races of the driver (race results files), races with the cars ahead & behind
            objectName: "driverHistory"
            Layout.fillWidth: true
            visible: (sheetCard.car.history || "") !== ""
            text: i18n.tr("History") + "  " + (sheetCard.car.history || "")
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.85
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: (sheetCard.car.headToHead || "") !== ""
            text: i18n.tr("Head to head") + "  " + (sheetCard.car.headToHead || "")
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.85
            elide: Text.ElideRight
        }
        TpTextField {
            id: noteField
            objectName: "noteField"
            Layout.fillWidth: true
            placeholderText: i18n.tr("Commentator note on this driver")
            text: sheetCard.car.note || ""
            onEditingFinished: backend.setNote(text)
            onEscaped: text = sheetCard.car.note || ""
        }
    }
}
