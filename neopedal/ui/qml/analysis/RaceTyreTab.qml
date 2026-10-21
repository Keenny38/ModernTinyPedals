import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQml.Models
import "../components"

// Race calculator tyre tab: tyre wear, tyre life & tyre rules (left), tyre plan with one row per stint
// once the strategy is ready (tyre change time added to the stop), tyre stock (drag a tyre onto a wheel, or
// Tab to a wheel then Space: pick a tyre; Tab to a stock tyre then Delete: remove it)
Item {
    id: tab
    property var store  // page: inputs, specs, header
    readonly property var plan: backend.tyrePlan
    readonly property var rule: plan.rule || ({})
    readonly property var life: backend.tyreLife
    readonly property var status: plan.status || ({})
    // Status figures as numbers: chip texts (translated by rules, a slot call each) built again only on change
    readonly property int stockCount: status.stock || 0
    readonly property int maximumCount: status.maximum || 0
    readonly property int usedCount: status.used || 0
    readonly property int stintCount: status.stints || 0
    readonly property int pitCount: status.pits || 0
    readonly property int changeCount: status.changes || 0
    readonly property real changeTime: status.time || 0
    readonly property real leftWidth: theme.em * 21
    readonly property var wheels: [i18n.tr("Front Left"), i18n.tr("Front Right"), i18n.tr("Rear Left"), i18n.tr("Rear Right")]
    readonly property color usedColor: theme.seriesTyre  // stock tyre already fitted in the plan

    // Tyre of stock picked for a wheel (menu of the wheel clicked)
    TpMenu {
        id: wheelMenu
        property int row: -1
        property int corner: -1
        property string current: ""
        property Item wheel: null
        property bool listing: false  // tyres of stock as items: only from opening to closed (not at each plan change)
        function openFor(cell) {
            row = cell.row
            corner = cell.corner
            current = cell.info.name || ""
            wheel = cell
            listing = true  // items made before it opens: size & place right at once
            popup(cell, 0, cell.height + 2)
        }
        onAboutToShow: listing = true  // opened again while closing: closed may have come in between
        onClosed: {
            listing = false
            var cell = wheel
            if (cell)
                Qt.callLater(function() { cell.forceActiveFocus() })  // Delete: tyre off
        }
        Instantiator {
            model: wheelMenu.listing ? (tab.plan.stock || []) : []
            delegate: TpMenuItem {
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
        TpMenuItem {
            text: (tab.plan.stock || []).length ? i18n.tr("Remove Tyre") : i18n.tr("No tyre in stock: add tyres to the stock first")
            enabled: wheelMenu.current !== ""
            onTriggered: backend.clearTyre(wheelMenu.row, wheelMenu.corner)
        }
    }

    // Actions of a plan row (menu of the row "⋯" button clicked): one menu for every row
    TpMenu {
        id: planRowMenu
        property int row: -1
        property Item button: null
        property bool refocus: false  // opened with the keyboard: focus back on its button once closed
        function openFor(source, index) {
            row = index
            button = source
            refocus = source.activeFocus
            popup(source, 0, source.height + 2)
        }
        onClosed: {
            var source = button
            if (refocus && source)
                Qt.callLater(function() { source.forceActiveFocus() })
        }
        TpMenuItem { text: i18n.tr("Clear Row"); onTriggered: backend.clearRow(planRowMenu.row) }  // undo toast
        MenuSeparator { visible: !tab.plan.linked }
        TpMenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Duplicate Row"); onTriggered: backend.duplicateRow(planRowMenu.row) }
        TpMenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Insert Row Above"); onTriggered: backend.insertRow(planRowMenu.row, true) }
        TpMenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Insert Row Below"); onTriggered: backend.insertRow(planRowMenu.row, false) }
        TpMenuItem { visible: !tab.plan.linked; height: visible ? implicitHeight : 0; text: i18n.tr("Delete Row"); onTriggered: backend.deleteRow(planRowMenu.row) }
    }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.topMargin: theme.space3
        contentHeight: grid.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        GridLayout {
            id: grid
            width: flick.width - theme.space5
            // content-tuned: inputs (21 em) + plan (24 em min) + stock (19 em)
            columns: width >= theme.em * 72 ? 3 : width >= theme.em * 46 ? 2 : 1  // content-tuned (above)
            columnSpacing: theme.space4
            rowSpacing: theme.space4

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
                    RaceNumber {
                        store: tab.store; key: "input_tyre_deg"; label: i18n.tr("Used Tyre Pace Loss")
                        tip: i18n.tr("Lap time lost per 10% of tread used before the stint (tyres kept for one more stint, used tyres). Tyres proposed for a change when it costs less than the time lost, 0 = none")
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
                            compounds: true
                            tip: i18n.tr("Compound of measured wear per lap: wear of other compounds scaled by their wear per stint")
                            Accessible.name: i18n.tr("Measured Compound")
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
                        columnSpacing: theme.space4
                        rowSpacing: theme.space2
                        Repeater {
                            // Values read from tab.life by key: tiles kept when the values change
                            model: [
                                { label: i18n.tr("Laps"), key: "laps", warn: "", tip: "" },
                                { label: i18n.tr("Minutes"), key: "minutes", warn: "", tip: "" },
                                { label: i18n.tr("Stints"), key: "stints", warn: "stintsWarning",
                                  tip: i18n.tr("Longest stints a set of tyres lasts") },
                                { label: i18n.tr("Wear per Stint"), key: "wearStint", warn: "wearWarning",
                                  tip: i18n.tr("Tread used over the longest stint") },
                            ]
                            TpKeyValue {  // warning: loss color & warning mark
                                required property var modelData
                                layout: "stack"
                                large: true
                                label: modelData.label
                                tip: modelData.tip
                                value: tab.life[modelData.key] || "-"
                                warning: modelData.warn !== "" && tab.life[modelData.warn] === true
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
                        BusyIndicator {  // waiting for the game
                            visible: backend.askingGame
                            running: visible && pageState.active
                            width: Math.round(theme.em * 1.3)
                            height: width
                            anchors.right: parent.right
                            anchors.rightMargin: theme.space3
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Text {
                        text: i18n.tr("Change Time")
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        HoverHandler { id: changeHover }
                        ToolTip.visible: changeHover.hovered
                        ToolTip.text: i18n.tr("Time added to the stop, by number of tyres changed")
                        ToolTip.delay: theme.tipDelay
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
            TpSectionCard {
                id: planCard
                Layout.alignment: Qt.AlignTop
                Layout.minimumWidth: theme.em * 24
                title: i18n.tr("Tyre Plan")
                glyph: ""  // ring
                actions: [
                    TpButton {
                        id: fileButton
                        flat: true
                        size: "sm"
                        glyph: ""  // folder
                        text: i18n.tr("File")
                        checked: fileMenu.visible
                        onClicked: fileMenu.popup(fileButton, 0, fileButton.height + 4)
                        TpMenu {
                            id: fileMenu
                            TpMenuItem { text: i18n.tr("New File"); onTriggered: backend.newTyrePlan() }
                            MenuSeparator {}
                            TpMenuItem { text: i18n.tr("Open File"); onTriggered: backend.openTyrePlan() }
                            RaceRecentMenu { kind: "tyre_plan" }
                            MenuSeparator {}
                            TpMenuItem { text: i18n.tr("Save As..."); onTriggered: backend.saveTyrePlan() }
                            TpMenuItem { text: i18n.tr("Export As..."); onTriggered: backend.exportTyrePlanCsv() }
                        }
                    },
                    TpButton {
                        accent: true
                        size: "sm"
                        glyph: ""  // lightning
                        text: i18n.tr("Propose Changes")
                        tip: i18n.tr("New tyres at the start and at the stops the strategy proposes (minimum tread), compound selected in tyre stock")
                        onClicked: backend.proposeChanges()
                    }
                ]

                TpTextField {
                    id: planName
                    objectName: "tyrePlanName"
                    Layout.fillWidth: true
                    text: tab.plan.name || ""
                    placeholderText: i18n.tr("Untitled plan")
                    tip: i18n.tr("Plan name")
                    validator: RegularExpressionValidator { regularExpression: /[^\\/:*?"<>|]*/ }
                    Accessible.name: i18n.tr("Plan name")
                    onEditingFinished: backend.setPlanName(text)
                    onEscaped: text = tab.plan.name || ""  // typed name dropped
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
                    font.pointSize: theme.fontSmall
                    wrapMode: Text.Wrap
                }
                TpNotice {
                    Layout.fillWidth: true
                    visible: text !== ""
                    tone: theme.loss
                    text: tab.plan.proposal || ""
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
                        TpHeaderCell {
                            required property var modelData
                            required property int index
                            text: modelData
                            align: index > 0 && index < 5 ? Qt.AlignHCenter : index === 5 ? Qt.AlignRight : Qt.AlignLeft
                            Layout.fillWidth: index > 0 && index < 5
                            Layout.preferredWidth: index > 0 && index < 5 ? theme.em * 5 : index === 5 ? theme.em * 4 : -1
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
                            Layout.preferredWidth: column > 0 && column < 5 ? theme.em * 5 : column === 5 ? theme.em * 4 : -1
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
                                }
                            }
                            Component {
                                id: changeText
                                Text {  // tyres changed at this stop: tyre color & ◆ mark (as the strategy)
                                    readonly property bool changed: slot.rowData !== undefined && slot.rowData.changes > 0
                                    text: (slot.rowData ? slot.rowData.change : "") + (changed ? " ◆" : "")
                                    color: changed ? theme.seriesTyre : theme.dimText
                                    font.features: { "tnum": 1 }
                                    horizontalAlignment: Text.AlignRight
                                    width: theme.em * 4
                                }
                            }
                            Component {
                                id: rowMenu
                                TpButton {
                                    id: rowButton
                                    flat: true
                                    size: "sm"
                                    glyph: ""  // more
                                    fallback: "⋯"
                                    tip: i18n.tr("Row")
                                    checked: planRowMenu.visible && planRowMenu.button === rowButton
                                    onClicked: planRowMenu.openFor(rowButton, slot.row)
                                }
                            }
                        }
                    }
                }
                TpButton {
                    visible: !tab.plan.linked
                    flat: true
                    size: "sm"
                    glyph: ""  // add
                    text: i18n.tr("New Row")
                    onClicked: backend.addRow()
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: theme.space3
                    Pill {
                        readonly property bool invalid: tab.stockCount > tab.maximumCount
                        text: i18n.trm("Stock: " + tab.stockCount + " / " + tab.maximumCount + (invalid ? " (" + i18n.tr("invalid") + ")" : ""))
                        tint: invalid ? theme.loss : theme.dimText
                        glyph: invalid ? "" : ""  // warning: shape too
                    }
                    Pill { text: i18n.trm("Used: " + tab.usedCount); tint: theme.dimText }
                    Pill { text: i18n.trm("Stints: " + tab.stintCount); tint: theme.dimText }
                    Pill { text: i18n.trm("Pits: " + tab.pitCount); tint: theme.dimText }
                    Pill { text: i18n.trm("Changes: " + tab.changeCount); tint: theme.dimText }
                    Pill { text: i18n.trm("Time: " + (tab.changeTime >= 0 ? "+" : "") + tab.changeTime.toFixed(2).replace(".", theme.decimalPoint) + "s"); tint: theme.dimText }
                }
            }

            // Tyre stock
            TpSectionCard {
                id: stockCard
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: grid.columns === 3 ? theme.em * 19 : -1
                Layout.maximumWidth: grid.columns === 3 ? theme.em * 19 : -1
                Layout.fillWidth: grid.columns !== 3
                title: i18n.tr("Tyre Stock")
                glyph: ""  // folder
                count: (tab.plan.stock || []).length > 0 ? String((tab.plan.stock || []).length) : ""
                actions: [
                    TpButton {
                        id: sortButton
                        flat: true
                        size: "sm"
                        glyph: ""  // sort
                        fallback: "⇅"
                        tip: i18n.tr("Sort By")
                        checked: sortMenu.visible
                        onClicked: sortMenu.popup(sortButton, 0, sortButton.height + 4)
                        TpMenu {
                            id: sortMenu
                            TpMenuItem { text: i18n.tr("Compound Type"); onTriggered: backend.sortStock(false) }
                            TpMenuItem { text: i18n.tr("Number of Stints"); onTriggered: backend.sortStock(true) }
                        }
                    },
                    TpButton {
                        id: stockMore
                        flat: true
                        size: "sm"
                        glyph: ""  // more
                        fallback: "⋯"
                        tip: i18n.tr("Clean Up Stock")
                        checked: stockMenu.visible
                        onClicked: stockMenu.popup(stockMore, 0, stockMore.height + 4)
                        TpMenu {
                            id: stockMenu
                            TpMenuItem { text: i18n.tr("Remove Unused"); onTriggered: backend.removeUnusedTyres() }  // undo toast
                            TpMenuItem { text: i18n.tr("Clear All"); onTriggered: backend.clearTyres() }  // confirmed
                        }
                    }
                ]
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.space2
                    TpCombo {
                        id: compoundBox
                        Layout.fillWidth: true
                        model: tab.plan.compounds || []
                        currentIndex: (tab.plan.compounds || []).indexOf(tab.plan.compound)
                        compounds: true
                        tip: i18n.tr("Compound added to stock, and of proposed tyre changes")
                        Accessible.name: i18n.tr("Compound added to stock, and of proposed tyre changes")
                        onActivated: function(index) {
                            backend.setStockCompound(tab.plan.compounds[index])
                            currentIndex = Qt.binding(function() { return (tab.plan.compounds || []).indexOf(tab.plan.compound) })
                        }
                    }
                    TpButton {
                        glyph: ""  // add
                        fallback: "+"
                        tip: i18n.tr("Add")
                        onClicked: backend.addTyre()
                    }
                    TpButton {
                        glyph: ""  // settings
                        fallback: "⚙"
                        tip: i18n.tr("Starting tread & wear per stint of compound")
                        onClicked: backend.configureCompound()
                        Accessible.name: i18n.tr("Config")
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: (tab.plan.stock || []).length ? i18n.tr("Drag a tyre onto a wheel of the plan.") : i18n.tr("No tyre in stock: add tyres to the stock first")
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    wrapMode: Text.Wrap
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: theme.space2
                    Repeater {
                        model: tab.plan.stock || []
                        Rectangle {
                            id: chip
                            required property var modelData
                            readonly property string tyreName: modelData.name
                            readonly property bool used: modelData.stints > 0
                            readonly property bool showRemove: chipArea.containsMouse || removeButton.hovered || chip.activeFocus
                            implicitHeight: Math.round(theme.em * 1.9)
                            implicitWidth: chipRow.implicitWidth + theme.em * 0.9 + removeButton.width
                            radius: theme.radiusMd
                            color: chipArea.containsMouse || activeFocus ? theme.hover : theme.raised
                            border.width: 1
                            border.color: used ? tab.usedColor : theme.border  // fitted in the plan: stints badge too
                            // Keyboard: Tab reaches each tyre, Delete removes it (after confirmation)
                            activeFocusOnTab: true
                            Accessible.role: Accessible.ListItem
                            Accessible.name: tyreName + (modelData.tread ? " " + modelData.tread : "")
                                             + (used ? ", " + i18n.trm("Stints: " + modelData.stints) : "")
                            Accessible.description: i18n.tr("Delete: remove from stock")
                            Keys.onDeletePressed: backend.removeTyre(chip.tyreName)
                            FocusRing { visible: chip.activeFocus }
                            Row {
                                id: chipRow
                                x: theme.em * 0.45
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: theme.space2
                                TpCompound {
                                    name: chip.tyreName
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text { text: chip.tyreName; color: theme.text; font.pointSize: theme.fontLabel; anchors.verticalCenter: parent.verticalCenter }
                                Text {  // used tyre of the game: tread left
                                    visible: (chip.modelData.tread || "") !== ""
                                    text: chip.modelData.tread || ""
                                    color: theme.dimText
                                    font.pointSize: theme.fontCaption
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Rectangle {
                                    visible: chip.used
                                    implicitWidth: stintsText.implicitWidth + theme.em * 0.6
                                    implicitHeight: theme.em * 1.2
                                    radius: height / 2
                                    color: theme.tint(tab.usedColor, "strong")
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        id: stintsText
                                        anchors.centerIn: parent
                                        text: chip.modelData.stints
                                        color: theme.text
                                        font.pointSize: theme.fontCaption
                                        font.features: { "tnum": 1 }
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
                            TpButton {  // shown on hover & keyboard focus (Delete does the same)
                                id: removeButton
                                visible: chip.showRemove
                                focusPolicy: Qt.NoFocus  // keyboard: Delete on the chip
                                flat: true
                                size: "xs"
                                glyph: ""  // cancel
                                fallback: "✕"
                                anchors.right: parent.right
                                anchors.rightMargin: theme.space1
                                anchors.verticalCenter: parent.verticalCenter
                                tip: i18n.tr("Remove from Stock")
                                onClicked: backend.removeTyre(chip.tyreName)
                            }
                            Rectangle {  // dragged copy
                                id: ghost
                                readonly property string tyreName: chip.tyreName
                                visible: chipArea.drag.active
                                width: chip.width
                                height: chip.height
                                radius: chip.radius
                                color: theme.accentFill
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

            // Race on each compound (scenarios, worker thread)
            TpSectionCard {
                id: compoundCard
                readonly property var compare: (backend.scenarios || ({})).compounds || ({})
                visible: compare.visible === true
                Layout.columnSpan: grid.columns
                Layout.fillWidth: true
                title: i18n.tr("Compound Comparison")
                glyph: "\uE8AB"  // switch
                tip: i18n.tr("Whole race on each compound: tyres changed when worn or when used tyres lose more than a change costs, best one in bold")
                RaceTable {
                    Layout.fillWidth: true
                    columns: compoundCard.compare.columns || []
                    rows: compoundCard.compare.rows || []
                    boldRow: compoundCard.compare.best !== undefined ? compoundCard.compare.best : -1
                }
                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: compoundCard.compare.note || ""
                    color: theme.dimText
                    font.pointSize: theme.fontLabel
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
