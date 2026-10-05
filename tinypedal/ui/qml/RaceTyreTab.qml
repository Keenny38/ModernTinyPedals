import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQml.Models

// Race calculator tyre tab: tyre wear, tyre life & tyre rules (left), tyre plan with one row per stint
// once the strategy is ready (tyre change time added to the stop), tyre stock (drag a tyre onto a wheel)
Item {
    id: tab
    property var store  // page: inputs, specs, header
    readonly property var plan: backend.tyrePlan
    readonly property var rule: plan.rule || ({})
    readonly property var life: backend.tyreLife
    readonly property var status: plan.status || ({})
    readonly property real leftWidth: theme.em * 21
    readonly property var wheels: [i18n.tr("Front Left"), i18n.tr("Front Right"), i18n.tr("Rear Left"), i18n.tr("Rear Right")]

    function compoundColor(name) {
        var key = String(name).split("#")[0].trim().replace(/^Q-/, "")
        return {
            Ultrasoft: "#C084FC", Supersoft: "#F43F5E", Soft: "#EF4444", Medium: "#FACC15", Hard: "#E5E7EB",
            Intermediate: "#22C55E", Wet: "#3B82F6"
        }[key] || theme.dimText
    }

    component StatusChip: Rectangle {
        property string text: ""
        property bool warning: false
        implicitHeight: Math.round(theme.em * 1.6)
        implicitWidth: chipText.implicitWidth + theme.em * 1.1
        radius: height / 2
        color: warning ? Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.16) : theme.hover
        Text {
            id: chipText
            anchors.centerIn: parent
            text: parent.text
            color: parent.warning ? theme.loss : theme.text
            font.pointSize: theme.fontPoint * 0.85
            font.features: { "tnum": 1 }
        }
    }

    // Tyre of stock picked for a wheel (menu of the wheel clicked)
    TpMenu {
        id: wheelMenu
        property int row: -1
        property int corner: -1
        property string current: ""
        property Item wheel: null
        function openFor(cell) {
            row = cell.row
            corner = cell.corner
            current = cell.info.name || ""
            wheel = cell
            popup(cell, 0, cell.height + 2)
        }
        onClosed: { var cell = wheel; if (cell) Qt.callLater(function() { cell.forceActiveFocus() }) }  // Delete: tyre off
        Instantiator {
            model: tab.plan.stock || []
            delegate: MenuItem {
                required property var modelData
                text: modelData.name + (modelData.stints ? "  ·  " + i18n.trm("Stints: " + modelData.stints) : "")
                checkable: true
                checked: modelData.name === wheelMenu.current
                onTriggered: backend.assignTyre(wheelMenu.row, wheelMenu.corner, modelData.name)
            }
            onObjectAdded: function(index, object) { wheelMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { wheelMenu.removeItem(object) }
        }
        MenuSeparator {}
        MenuItem {
            text: (tab.plan.stock || []).length ? i18n.tr("Remove Tyre") : i18n.tr("No tyre in stock: add tyres to the stock first")
            enabled: wheelMenu.current !== ""
            onTriggered: backend.clearTyre(wheelMenu.row, wheelMenu.corner)
        }
    }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.topMargin: theme.em * 0.4
        contentHeight: grid.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        GridLayout {
            id: grid
            width: flick.width - theme.em * 0.8
            columns: width >= theme.em * 72 ? 3 : width >= theme.em * 46 ? 2 : 1
            columnSpacing: theme.em * 0.6
            rowSpacing: theme.em * 0.6

            // Tyre wear, life & rules
            ColumnLayout {
                Layout.preferredWidth: grid.columns > 1 ? tab.leftWidth : grid.width
                Layout.maximumWidth: grid.columns > 1 ? tab.leftWidth : grid.width
                Layout.alignment: Qt.AlignTop
                spacing: theme.em * 0.5

                RaceSection {
                    store: tab.store
                    name: "tyre_wear"
                    title: i18n.tr("Tyre Wear")
                    glyph: ""  // ring
                    RaceNumber { store: tab.store; key: "input_tread_start"; label: i18n.tr("Starting Tread") }
                    RaceNumber { store: tab.store; key: "input_wear_per_lap"; label: i18n.tr("Wear per Lap") }
                    RaceNumber {
                        store: tab.store; key: "input_minimum_tread"; label: i18n.tr("Minimum Tread")
                        tip: i18n.tr("Tyres changed at the stop before tread would go below")
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.em * 0.5
                        Text { text: i18n.tr("Measured Compound"); color: theme.text; elide: Text.ElideRight; Layout.fillWidth: true }
                        TpCombo {
                            id: measured
                            Layout.preferredWidth: theme.em * 8.5
                            model: backend.measuredCompounds
                            currentIndex: Number(tab.store.inputs.input_measured_compound)
                            dotColor: tab.compoundColor
                            tip: i18n.tr("Compound of measured wear per lap: wear of other compounds scaled by their wear per stint")
                            onActivated: function(index) {
                                backend.setInput("input_measured_compound", index)
                                currentIndex = Qt.binding(function() { return Number(tab.store.inputs.input_measured_compound) })
                            }
                        }
                    }
                    RaceNumber {
                        store: tab.store; key: "input_tyre_set_laps"; label: i18n.tr("Laps per Tyre Set")
                        tip: i18n.tr("Tyre life: stints never longer than a set of tyres lasts, tyres changed when needed, 0 = none")
                    }
                    RaceSwitch {
                        store: tab.store; key: "enable_tyre_life_stints"
                        text: i18n.tr("Stints Cut by Tyre Life")
                        tip: i18n.tr("Stints never wear tyres below the minimum tread (wear per lap): tyres changed at the stop before, shorter stints when needed")
                    }
                }

                RaceSection {
                    store: tab.store
                    name: "tyre_life"
                    title: i18n.tr("Tyre Life")
                    glyph: ""  // stopwatch
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: theme.em * 0.6
                        rowSpacing: theme.em * 0.3
                        Repeater {
                            model: [
                                { label: i18n.tr("Laps"), value: tab.life.laps, warning: false, tip: "" },
                                { label: i18n.tr("Minutes"), value: tab.life.minutes, warning: false, tip: "" },
                                { label: i18n.tr("Stints"), value: tab.life.stints, warning: tab.life.stintsWarning === true,
                                  tip: i18n.tr("Longest stints a set of tyres lasts") },
                                { label: i18n.tr("Wear per Stint"), value: tab.life.wearStint, warning: tab.life.wearWarning === true,
                                  tip: i18n.tr("Tread used over the longest stint") },
                            ]
                            Column {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 1
                                Text {
                                    text: parent.modelData.label
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.85
                                    HoverHandler { id: lifeHover; enabled: parent.parent.modelData.tip !== "" }
                                    ToolTip.visible: lifeHover.hovered
                                    ToolTip.text: parent.modelData.tip
                                    ToolTip.delay: 500
                                }
                                Text {
                                    text: parent.modelData.value || "-"
                                    color: parent.modelData.warning ? theme.loss : theme.text
                                    font.pointSize: theme.fontPoint * 1.15
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                        }
                    }
                }

                RaceSection {
                    store: tab.store
                    name: "tyre_rules"
                    title: i18n.tr("Tyre Rules")
                    glyph: ""  // document
                    RaceNumber {
                        label: i18n.tr("Maximum Tyres")
                        tip: i18n.tr("Tyres allowed for the race (limited stock compounds)")
                        spec: ({ min: 0, max: 999, decimals: 0, step: 1, suffix: "" })
                        value: Number(tab.rule.maximum_tyre || 0)
                        onEdited: function(number) { backend.setTyreRule("maximum_tyre", number) }
                    }
                    TpButton {
                        Layout.fillWidth: true
                        enabled: !backend.askingGame
                        glyph: ""  // game
                        text: backend.askingGame ? i18n.tr("Asking game...") : i18n.tr("From Game")
                        tip: i18n.tr("Tyres allowed by the session in the game (LMU)")
                        onClicked: backend.tyreAllocationFromGame()
                    }
                    Text {
                        text: i18n.tr("Change Time")
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.88
                        HoverHandler { id: changeHover }
                        ToolTip.visible: changeHover.hovered
                        ToolTip.text: i18n.tr("Time added to the stop, by number of tyres changed")
                        ToolTip.delay: 500
                    }
                    Repeater {
                        model: 4
                        RaceNumber {
                            required property int index
                            label: i18n.trm((index + 1) + " tyre(s)")
                            spec: ({ min: 0, max: 99, decimals: 1, step: 0.1, suffix: "s" })
                            value: Number(tab.rule["tyre_change_time_" + (index + 1)] || 0)
                            onEdited: function(number) { backend.setTyreRule("tyre_change_time_" + (index + 1), number) }
                        }
                    }
                    RaceSwitch {
                        text: i18n.tr("Restrict Allocation")
                        tip: i18n.tr("A used tyre stays on the same wheel")
                        on: tab.rule.enable_restricted_allocation === true
                        onSwitched: function(on) { backend.setTyreRule("enable_restricted_allocation", on) }
                    }
                    RaceSwitch {
                        text: i18n.tr("Highlight New Tyre")
                        tip: i18n.tr("Tyres used before shown dimmed")
                        on: tab.plan.highlightNew === true
                        onSwitched: function(on) { backend.setHighlightNew(on) }
                    }
                }
                Item { Layout.fillHeight: true }
            }

            // Tyre plan
            RaceCard {
                id: planCard
                Layout.alignment: Qt.AlignTop
                Layout.minimumWidth: theme.em * 24
                title: i18n.tr("Tyre Plan")
                glyph: ""  // ring
                actions: [
                    TpButton {
                        id: fileButton
                        flat: true
                        glyph: ""  // folder
                        text: i18n.tr("File")
                        onClicked: fileMenu.popup(fileButton, 0, fileButton.height + 4)
                        TpMenu {
                            id: fileMenu
                            MenuItem { text: i18n.tr("New File"); onTriggered: backend.newTyrePlan() }
                            MenuSeparator {}
                            MenuItem { text: i18n.tr("Open File"); onTriggered: backend.openTyrePlan() }
                            MenuSeparator {}
                            MenuItem { text: i18n.tr("Save As..."); onTriggered: backend.saveTyrePlan() }
                            MenuItem { text: i18n.tr("Export As..."); onTriggered: backend.exportTyrePlanCsv() }
                        }
                    },
                    TpButton {
                        accent: true
                        glyph: ""  // lightning
                        text: i18n.tr("Propose Changes")
                        tip: i18n.tr("New tyres at the start and at the stops the strategy proposes (minimum tread), compound selected in tyre stock")
                        onClicked: backend.proposeChanges()
                    }
                ]

                TextField {
                    id: planName
                    Layout.fillWidth: true
                    implicitHeight: Math.round(theme.em * 2.05)
                    text: tab.plan.name || ""
                    color: theme.text
                    selectByMouse: true
                    selectionColor: theme.accent
                    selectedTextColor: "white"
                    leftPadding: theme.em * 0.6
                    placeholderText: i18n.tr("Untitled plan")
                    placeholderTextColor: theme.dimText
                    validator: RegularExpressionValidator { regularExpression: /[^\\/:*?"<>|]*/ }
                    Accessible.name: i18n.tr("Plan name")
                    background: Rectangle {
                        radius: theme.em * 0.4
                        color: theme.dark ? Qt.darker(theme.base, 1.3) : Qt.darker(theme.base, 1.03)
                        border.width: planName.activeFocus ? 1.5 : 1
                        border.color: planName.activeFocus ? theme.accent : theme.border
                    }
                    onEditingFinished: backend.setPlanName(text)
                    Connections {
                        target: backend
                        function onTyresChanged() {
                            if (!planName.activeFocus)
                                planName.text = tab.plan.name
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: tab.plan.linked
                          ? i18n.tr("One row per stint of the strategy: tyre change time added to the stop, wear = wear per lap x stint laps (compound wear per stint without wear per lap).")
                          : i18n.tr("Drag a tyre onto a wheel of the plan.")
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.88
                    wrapMode: Text.Wrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: tab.plan.proposal || ""
                    color: theme.loss
                    wrapMode: Text.Wrap
                }

                // Rows: stint, 4 wheels, change time
                GridLayout {
                    id: planGrid
                    Layout.fillWidth: true
                    columns: 7
                    columnSpacing: theme.em * 0.35
                    rowSpacing: theme.em * 0.35
                    Repeater {
                        model: [i18n.tr("Stint")].concat(tab.wheels).concat([i18n.tr("Change"), ""])
                        Text {
                            required property var modelData
                            required property int index
                            text: modelData
                            color: theme.dimText
                            font.weight: Font.DemiBold
                            font.pointSize: theme.fontPoint * 0.85
                            horizontalAlignment: index > 0 && index < 6 ? Text.AlignHCenter : Text.AlignLeft
                            elide: Text.ElideRight
                            Layout.fillWidth: index > 0 && index < 5
                            Layout.preferredWidth: index > 0 && index < 5 ? theme.em * 5 : -1
                        }
                    }
                    Repeater {
                        model: (tab.plan.rows || []).length * 7
                        Loader {
                            id: slot
                            required property int index
                            readonly property int row: Math.floor(index / 7)
                            readonly property int column: index % 7
                            readonly property var rowData: tab.plan.rows[row]
                            Layout.fillWidth: column > 0 && column < 5
                            Layout.preferredWidth: column > 0 && column < 5 ? theme.em * 5 : -1
                            sourceComponent: column === 0 ? stintLabel : column < 5 ? wheelCell : column === 5 ? changeText : rowMenu
                            Component {
                                id: stintLabel
                                Text {
                                    text: slot.rowData ? slot.rowData.label : ""
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                            Component {
                                id: wheelCell
                                RaceTyreCell {
                                    row: slot.row
                                    corner: slot.column - 1
                                    info: slot.rowData ? slot.rowData.cells[slot.column - 1] : ({})
                                    menu: wheelMenu
                                    compoundColor: tab.compoundColor
                                }
                            }
                            Component {
                                id: changeText
                                Text {
                                    text: slot.rowData ? slot.rowData.change : ""
                                    color: slot.rowData && slot.rowData.changes > 0 ? "#F5B342" : theme.dimText
                                    font.features: { "tnum": 1 }
                                    horizontalAlignment: Text.AlignHCenter
                                    width: theme.em * 3.6
                                }
                            }
                            Component {
                                id: rowMenu
                                TpButton {
                                    id: rowButton
                                    flat: true
                                    glyph: ""  // more
                                    text: theme.iconFont === "" ? "..." : ""
                                    implicitHeight: Math.round(theme.em * 1.8)
                                    tip: i18n.tr("Row")
                                    onClicked: menu.popup(rowButton, 0, rowButton.height + 2)
                                    TpMenu {
                                        id: menu
                                        MenuItem { text: i18n.tr("Clear Row"); onTriggered: backend.clearRow(slot.row) }
                                        MenuSeparator { visible: !tab.plan.linked }
                                        MenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Duplicate Row"); onTriggered: backend.duplicateRow(slot.row) }
                                        MenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Insert Row Above"); onTriggered: backend.insertRow(slot.row, true) }
                                        MenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Insert Row Below"); onTriggered: backend.insertRow(slot.row, false) }
                                        MenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Delete Row"); onTriggered: backend.deleteRow(slot.row) }
                                    }
                                }
                            }
                        }
                    }
                }
                TpButton {
                    visible: !tab.plan.linked
                    flat: true
                    glyph: ""  // add
                    text: i18n.tr("New Row")
                    onClicked: backend.addRow()
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.35
                    StatusChip {
                        text: i18n.trm("Stock: " + tab.status.stock + " / " + tab.status.maximum + (tab.status.stock > tab.status.maximum ? " (" + i18n.tr("invalid") + ")" : ""))
                        warning: tab.status.stock > tab.status.maximum
                    }
                    StatusChip { text: i18n.trm("Used: " + tab.status.used) }
                    StatusChip { text: i18n.trm("Stints: " + tab.status.stints) }
                    StatusChip { text: i18n.trm("Pits: " + tab.status.pits) }
                    StatusChip { text: i18n.trm("Changes: " + tab.status.changes) }
                    StatusChip { text: i18n.trm("Time: " + (tab.status.time >= 0 ? "+" : "") + Number(tab.status.time || 0).toFixed(2) + "s") }
                }
            }

            // Tyre stock
            RaceCard {
                id: stockCard
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: grid.columns === 3 ? theme.em * 19 : -1
                Layout.maximumWidth: grid.columns === 3 ? theme.em * 19 : -1
                Layout.fillWidth: grid.columns !== 3
                title: i18n.tr("Tyre Stock")
                glyph: ""  // folder
                actions: [
                    TpButton {
                        id: sortButton
                        flat: true
                        glyph: ""  // sort
                        text: theme.iconFont === "" ? i18n.tr("Sort By") : ""
                        tip: i18n.tr("Sort By")
                        onClicked: sortMenu.popup(sortButton, 0, sortButton.height + 4)
                        Accessible.name: i18n.tr("Sort By")
                        TpMenu {
                            id: sortMenu
                            MenuItem { text: i18n.tr("Compound Type"); onTriggered: backend.sortStock(false) }
                            MenuItem { text: i18n.tr("Number of Stints"); onTriggered: backend.sortStock(true) }
                        }
                    },
                    TpButton {
                        id: stockMore
                        flat: true
                        glyph: ""  // more
                        text: theme.iconFont === "" ? "..." : ""
                        tip: i18n.tr("Remove")
                        onClicked: stockMenu.popup(stockMore, 0, stockMore.height + 4)
                        TpMenu {
                            id: stockMenu
                            MenuItem { text: i18n.tr("Remove Unused"); onTriggered: backend.removeUnusedTyres() }
                            MenuItem { text: i18n.tr("Clear All"); onTriggered: backend.clearTyres() }
                        }
                    }
                ]
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.3
                    TpCombo {
                        id: compoundBox
                        Layout.fillWidth: true
                        model: tab.plan.compounds || []
                        currentIndex: (tab.plan.compounds || []).indexOf(tab.plan.compound)
                        dotColor: tab.compoundColor
                        tip: i18n.tr("Compound added to stock, and of proposed tyre changes")
                        onActivated: function(index) {
                            backend.setStockCompound(tab.plan.compounds[index])
                            currentIndex = Qt.binding(function() { return (tab.plan.compounds || []).indexOf(tab.plan.compound) })
                        }
                    }
                    TpButton {
                        glyph: ""  // add
                        text: theme.iconFont === "" ? i18n.tr("Add") : ""
                        tip: i18n.tr("Add")
                        onClicked: backend.addTyre()
                        Accessible.name: i18n.tr("Add")
                    }
                    TpButton {
                        glyph: ""  // settings
                        text: theme.iconFont === "" ? i18n.tr("Config") : ""
                        tip: i18n.tr("Starting tread & wear per stint of compound")
                        onClicked: backend.configureCompound()
                        Accessible.name: i18n.tr("Config")
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: (tab.plan.stock || []).length ? i18n.tr("Drag a tyre onto a wheel of the plan.") : i18n.tr("No tyre in stock: add tyres to the stock first")
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.88
                    wrapMode: Text.Wrap
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.3
                    Repeater {
                        model: tab.plan.stock || []
                        Rectangle {
                            id: chip
                            required property var modelData
                            readonly property string tyreName: modelData.name
                            implicitHeight: Math.round(theme.em * 1.9)
                            implicitWidth: chipRow.implicitWidth + theme.em * 0.9 + (removeButton.visible ? removeButton.width : 0)
                            radius: theme.em * 0.4
                            color: chipArea.containsMouse ? theme.hover : theme.raised
                            border.width: 1
                            border.color: modelData.stints > 0 ? Qt.rgba(0.96, 0.7, 0.26, 0.7) : theme.border
                            Row {
                                id: chipRow
                                x: theme.em * 0.45
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: theme.em * 0.3
                                Rectangle {
                                    width: Math.round(theme.em * 0.55); height: width; radius: width / 2
                                    color: tab.compoundColor(chip.tyreName)
                                    border.width: 1
                                    border.color: Qt.rgba(0, 0, 0, 0.25)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text { text: chip.tyreName; color: theme.text; font.pointSize: theme.fontPoint * 0.9 }
                                Rectangle {
                                    visible: chip.modelData.stints > 0
                                    implicitWidth: stintsText.implicitWidth + theme.em * 0.6
                                    implicitHeight: theme.em * 1.2
                                    radius: height / 2
                                    color: Qt.rgba(0.96, 0.7, 0.26, 0.25)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        id: stintsText
                                        anchors.centerIn: parent
                                        text: chip.modelData.stints
                                        color: theme.text
                                        font.pointSize: theme.fontPoint * 0.78
                                    }
                                }
                            }
                            MouseArea {
                                id: chipArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: drag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                drag.target: ghost
                                onReleased: {
                                    if (ghost.Drag.target !== null)
                                        ghost.Drag.drop()
                                    ghost.x = 0
                                    ghost.y = 0
                                }
                            }
                            TpButton {
                                id: removeButton
                                visible: chipArea.containsMouse || hovered
                                flat: true
                                glyph: ""  // cancel
                                text: theme.iconFont === "" ? "x" : ""
                                implicitHeight: Math.round(theme.em * 1.5)
                                anchors.right: parent.right
                                anchors.rightMargin: 2
                                anchors.verticalCenter: parent.verticalCenter
                                tip: i18n.tr("Remove Selected")
                                onClicked: backend.removeTyre(chip.tyreName)
                            }
                            Rectangle {  // dragged copy
                                id: ghost
                                readonly property string tyreName: chip.tyreName
                                visible: chipArea.drag.active
                                width: chip.width
                                height: chip.height
                                radius: chip.radius
                                color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.85)
                                z: 100
                                Drag.active: chipArea.drag.active
                                Drag.keys: ["tyre"]
                                Drag.source: ghost
                                Drag.hotSpot.x: width / 2
                                Drag.hotSpot.y: height / 2
                                Text { anchors.centerIn: parent; text: chip.tyreName; color: "white"; font.weight: Font.DemiBold }
                            }
                        }
                    }
                }
            }
        }
    }
}
