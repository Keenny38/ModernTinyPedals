import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Sheet of the car picked in the car list: place, intervals ahead & behind, laps, pit stops, stint, contacts,
// penalties, commentator note (kept between sessions, by driver). Camera button: cut to car.
Rectangle {
    id: sheetCard
    readonly property var car: backend.sheetCar  // driver, car, note, history: seldom changes
    readonly property var live: backend.sheetLive  // places, intervals, laps, sectors: most answers

    implicitHeight: sheetColumn.implicitHeight + theme.em * 1.1
    radius: theme.radiusLg
    color: theme.raised
    border.width: 1
    border.color: live.onAir ? theme.loss : theme.border

    component Stat: ColumnLayout {
        id: stat
        property string label: ""
        property string value: ""
        property color valueColor: theme.text
        property var badges: []  // compound names: badges instead of value text
        Layout.fillWidth: true
        Layout.preferredWidth: 1  // stats share the row evenly
        spacing: 0
        Text {
            Layout.fillWidth: true
            text: parent.label
            color: theme.dimText
            font.pointSize: theme.fontCaption
            elide: Text.ElideRight
        }
        Row {
            visible: stat.badges.length > 0
            spacing: theme.em * 0.2
            Repeater {
                model: stat.badges
                delegate: TpCompound { required property string modelData; name: modelData }
            }
        }
        Text {
            visible: stat.badges.length === 0
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
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: theme.em * 0.6 }
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
                    font.pointSize: theme.fontSubtitle
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    text: [sheetCard.car.team, sheetCard.car.vehicle].filter(function(part) { return part }).join(" · ")
                    color: theme.dimText
                    font.pointSize: theme.fontCaption
                    elide: Text.ElideRight
                }
            }
            Pill {
                visible: (sheetCard.live.status || "") !== ""
                text: sheetCard.live.status || ""
                tint: sheetCard.live.statusTone === "loss" ? theme.loss : sheetCard.live.statusTone === "gain" ? theme.gain : theme.warning
            }
            TpButton {
                glyph: ""  // camera
                accent: sheetCard.live.onAir === true
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
                value: sheetCard.live.classPosition ? "P" + sheetCard.live.classPosition + " " + sheetCard.car.carClass
                       + (sheetCard.live.gained > 0 ? "  ▲" + sheetCard.live.gained : sheetCard.live.gained < 0 ? "  ▼" + (-sheetCard.live.gained) : "")
                       : ""
            }
            Stat { label: i18n.tr("Overall"); value: sheetCard.live.position ? "P" + sheetCard.live.position : "" }
            Stat { label: i18n.tr("Laps"); value: sheetCard.live.laps !== undefined ? String(sheetCard.live.laps) : "" }
            Stat { label: i18n.tr("Current stint"); value: sheetCard.live.stint >= 0 ? i18n.tr("%1 laps").arg(sheetCard.live.stint) : "" }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Stat { label: i18n.tr("Ahead"); value: sheetCard.live.intervalAhead || ""; valueColor: theme.text }
            Stat { label: i18n.tr("Behind"); value: sheetCard.live.intervalBehind ? sheetCard.live.intervalBehind.replace("+", "-") : "" }
            Stat { label: i18n.tr("Best"); value: sheetCard.live.best || "" }
            Stat { label: i18n.tr("Last"); value: sheetCard.live.last || "" }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Stat { label: i18n.tr("Pit Stops"); value: sheetCard.live.pits !== undefined ? String(sheetCard.live.pits) : "" }
            Stat {
                label: i18n.tr("Contacts")
                value: sheetCard.live.incidents !== undefined ? String(sheetCard.live.incidents) : ""
                valueColor: sheetCard.live.incidents > 0 ? theme.warning : theme.text
            }
            Stat {
                label: i18n.tr("Penalties")
                value: sheetCard.live.penalties !== undefined ? String(sheetCard.live.penalties) : ""
                valueColor: sheetCard.live.penalties > 0 ? theme.loss : theme.text
            }
            Stat {
                label: i18n.tr("Tyres")
                value: sheetCard.live.tyres || ""
                badges: value !== "" ? value.split("/") : []
            }
        }
        // Sectors of the lap (as they complete, else last lap): purple best of class, green personal best
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Repeater {
                model: 3  // cells kept, texts & colors change as sectors complete
                delegate: Stat {
                    required property int index
                    readonly property var sector: (sheetCard.live.sectors || [])[index]
                    visible: sector !== undefined
                    label: "S" + (index + 1)
                    value: sector !== undefined ? sector.text : ""
                    valueColor: sector === undefined ? theme.text : sector.tone === "fastest" ? theme.purple
                              : sector.tone === "gain" ? theme.gain : sector.tone === "yellow" ? theme.gold : theme.text
                }
            }
            TpButton {
                objectName: "lapHistoryButton"
                glyph: ""  // stopwatch
                text: i18n.tr("Laps") + (sheetCard.live.lapCount ? " " + sheetCard.live.lapCount : "")
                tip: i18n.tr("Lap History")
                onClicked: backend.showLaps(sheetCard.car.slot)
            }
        }
        Text {  // energy (else fuel) left, used per lap, laps left
            Layout.fillWidth: true
            visible: (sheetCard.live.energy || "") !== ""
            text: i18n.tr("Energy") + "  " + (sheetCard.live.energy || "")
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
        }
        Text {  // races of the driver (race results files), races with the cars ahead & behind
            objectName: "driverHistory"
            Layout.fillWidth: true
            visible: (sheetCard.car.history || "") !== ""
            text: i18n.tr("History") + "  " + (sheetCard.car.history || "")
            color: theme.dimText
            font.pointSize: theme.fontSmall
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: (sheetCard.car.headToHead || "") !== ""
            text: i18n.tr("Head to head") + "  " + (sheetCard.car.headToHead || "")
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
        }
        TpTextField {
            id: noteField
            objectName: "noteField"
            // while edited: text not fed by the sheet, saved for the driver shown when the edit began
            property bool editing: false
            property string editDriver: ""
            Layout.fillWidth: true
            placeholderText: i18n.tr("Commentator note on this driver")
            function begin() {
                if (editing)
                    return
                editDriver = sheetCard.car.driver || ""
                editing = true
            }
            function commit() {
                if (!editing)
                    return
                const note = text
                editing = false  // binding below shows the saved note again
                backend.setDriverNote(editDriver, note)
            }
            onActiveFocusChanged: if (activeFocus) begin()
            onTextEdited: begin()
            onEditingFinished: commit()
            onEscaped: editing = false  // note of sheet put back, focus dropped next: nothing saved
            Binding {
                target: noteField
                property: "text"
                value: sheetCard.car.note || ""
                when: !noteField.editing
                restoreMode: Binding.RestoreNone  // editing starts from the note shown
            }
        }
        Connections {  // other car picked while a note is typed: note saved for its driver first
            target: sheetCard
            function onCarChanged() {
                if (noteField.editing && (sheetCard.car.driver || "") !== noteField.editDriver) {
                    noteField.commit()
                    noteField.focus = false
                }
            }
        }
    }
}
