import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Sheet of the car picked in the car list: place, intervals ahead & behind, laps, pit stops, stint, contacts,
// penalties, commentator note (kept between sessions, by driver). Camera button: cut to car.
// Collapsible (header only: the commentator lists keep their room), never taller than maximumHeight
// (content scrolls inside).
Rectangle {
    id: sheetCard
    readonly property var car: backend.sheetCar  // driver, car, note, history: seldom changes
    readonly property var live: backend.sheetLive  // places, intervals, laps, sectors: most answers
    property bool expanded: true
    property real maximumHeight: Infinity

    implicitHeight: Math.min(sheetColumn.implicitHeight + theme.space6, maximumHeight)
    radius: theme.radiusLg
    color: theme.raised
    border.width: live.onAir ? 2 : 1  // on air: thicker red frame
    border.color: live.onAir ? theme.loss : theme.border

    // Sector & lap marks besides colors (colorblind): ◆ best of class, ● personal best
    function mark(tone) { return tone === "fastest" ? "◆ " : tone === "gain" ? "● " : "" }

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
            spacing: theme.space1
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

    Flickable {
        id: sheetFlick
        anchors.fill: parent
        anchors.margins: theme.space4
        clip: true
        contentWidth: width
        contentHeight: sheetColumn.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: sheetColumn
            width: sheetFlick.width - (sheetFlick.ScrollBar.vertical.visible ? theme.space5 : 0)
            spacing: theme.space3

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                TpClassStrip {
                    Layout.fillHeight: false
                    Layout.preferredHeight: Math.round(theme.em * 2.4)
                    Layout.topMargin: 0
                    Layout.bottomMargin: 0
                    tint: sheetCard.car.classColor || ""
                }
                GamePicture {  // car picture of game
                    visible: shown && sheetCard.expanded
                    source: sheetCard.car.carPicture || ""
                    boxHeight: theme.em * 2.6
                    aspect: 1.6
                    crop: false
                }
                Item {  // car brand logo: room kept (name does not move when it loads)
                    Layout.preferredWidth: theme.em * 2.0
                    Layout.preferredHeight: theme.em * 1.3
                    GameLogo { anchors.centerIn: parent; source: sheetCard.car.brandLogo || ""; boxWidth: theme.em * 2.0; boxHeight: theme.em * 1.3 }
                }
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
                    fallback: "◎"
                    size: "sm"
                    accent: sheetCard.live.onAir === true
                    tip: i18n.tr("Cut to this car (double click)")
                    onClicked: backend.cutToCar(sheetCard.car.slot)
                }
                TpButton {
                    objectName: "sheetCollapseButton"
                    glyph: sheetCard.expanded ? "" : ""  // chevron up, down
                    fallback: sheetCard.expanded ? "▴" : "▾"
                    flat: true
                    size: "sm"
                    tip: sheetCard.expanded ? i18n.tr("Collapse Section") : i18n.tr("Expand Section")
                    onClicked: sheetCard.expanded = !sheetCard.expanded
                }
                TpButton {
                    glyph: ""  // close
                    fallback: "✕"
                    flat: true
                    size: "sm"
                    tip: i18n.tr("Close")
                    onClicked: backend.selectCar(sheetCard.car.slot)
                }
            }
            RowLayout {
                visible: sheetCard.expanded
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
                visible: sheetCard.expanded
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                Stat { label: i18n.tr("Ahead"); value: sheetCard.live.intervalAhead || ""; valueColor: theme.text }
                Stat { label: i18n.tr("Behind"); value: sheetCard.live.intervalBehind ? sheetCard.live.intervalBehind.replace("+", "-") : "" }
                Stat { label: i18n.tr("Best"); value: sheetCard.live.best || "" }
                Stat { label: i18n.tr("Last"); value: sheetCard.live.last || "" }
            }
            RowLayout {
                visible: sheetCard.expanded
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
            // Sectors of the lap (as they complete, else last lap): purple ◆ best of class, green ● personal best
            RowLayout {
                visible: sheetCard.expanded
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                Repeater {
                    model: 3  // cells kept, texts & colors change as sectors complete
                    delegate: Stat {
                        required property int index
                        readonly property var sector: (sheetCard.live.sectors || [])[index]
                        visible: sector !== undefined
                        label: "S" + (index + 1)
                        value: sector !== undefined ? sheetCard.mark(sector.tone) + sector.text : ""
                        valueColor: sector === undefined || sector.tone === "" ? theme.text : theme.tone(sector.tone)
                    }
                }
                TpButton {
                    objectName: "lapHistoryButton"
                    glyph: ""  // stopwatch
                    size: "sm"
                    text: i18n.tr("Laps") + (sheetCard.live.lapCount ? " " + sheetCard.live.lapCount : "")
                    tip: i18n.tr("Lap History")
                    onClicked: backend.showLaps(sheetCard.car.slot)
                }
            }
            Text {  // energy (else fuel) left, used per lap, laps left
                Layout.fillWidth: true
                visible: sheetCard.expanded && (sheetCard.live.energy || "") !== ""
                text: i18n.tr("Energy") + "  " + (sheetCard.live.energy || "")
                color: theme.dimText
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
            }
            Text {  // races of the driver (race results files), races with the cars ahead & behind
                objectName: "driverHistory"
                Layout.fillWidth: true
                visible: sheetCard.expanded && (sheetCard.car.history || "") !== ""
                text: i18n.tr("History") + "  " + (sheetCard.car.history || "")
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                visible: sheetCard.expanded && (sheetCard.car.headToHead || "") !== ""
                text: i18n.tr("Head to head") + "  " + (sheetCard.car.headToHead || "")
                color: theme.dimText
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
            }
            TpTextField {
                id: noteField
                objectName: "noteField"
                visible: sheetCard.expanded || editing  // collapsing while typing keeps the field
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
}
