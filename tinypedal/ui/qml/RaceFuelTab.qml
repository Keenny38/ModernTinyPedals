import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator fuel tab: input sections (fold, kept folded), pit stop plan & export, driving time,
// details, saving target & scenarios, plan against race, class rivals; consumption history beside
// (wide page) or below
Item {
    id: tab
    property var store  // page: inputs, specs, header, calc
    readonly property var inputs: store.inputs
    readonly property var calc: store.calc
    readonly property var notes: backend.notes
    readonly property var scenarios: backend.scenarios
    readonly property bool showHistory: store.header.showHistory
    readonly property bool sideHistory: width >= theme.em * 74
    readonly property real inputsWidth: theme.em * 21
    readonly property color tyreColor: "#F5B342"

    function fmt(value, decimals) {
        return Number(value).toFixed(decimals)
    }

    component Note: Text {
        Layout.fillWidth: true
        visible: text !== ""
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.9
        textFormat: Text.StyledText
        wrapMode: Text.Wrap
    }
    component ValueRow: RowLayout {
        property string label: ""
        property string value: "-"
        property string tip: ""
        property bool warning: false
        Layout.fillWidth: true
        Text {
            text: parent.label
            color: theme.text
            elide: Text.ElideRight
            Layout.fillWidth: true
            HoverHandler { id: valueHover; enabled: parent.tip !== "" }
            ToolTip.visible: valueHover.hovered
            ToolTip.text: parent.tip
            ToolTip.delay: 500
        }
        Text {
            text: parent.value
            color: parent.warning ? theme.loss : theme.text
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
        }
    }

    GridLayout {
        anchors.fill: parent
        anchors.topMargin: theme.em * 0.4
        columns: tab.sideHistory ? 2 : 1
        columnSpacing: theme.em * 0.6
        rowSpacing: theme.em * 0.6

        Flickable {
            id: flick
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 10
            contentHeight: content.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: flick.contentHeight > flick.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }

            GridLayout {
                id: content
                width: flick.width - theme.em * 0.8
                columns: width >= tab.inputsWidth + theme.em * 24 ? 2 : 1
                columnSpacing: theme.em * 0.6
                rowSpacing: theme.em * 0.6

                // Inputs
                ColumnLayout {
                    Layout.preferredWidth: content.columns > 1 ? tab.inputsWidth : content.width
                    Layout.maximumWidth: content.columns > 1 ? tab.inputsWidth : content.width
                    Layout.alignment: Qt.AlignTop
                    spacing: theme.em * 0.5

                    RaceSection {
                        store: tab.store
                        name: "lap"
                        title: i18n.tr("Lap & Consumption")
                        glyph: ""  // stopwatch
                        summary: tab.inputs.lap_time_text + " · " + tab.fmt(tab.inputs.input_fuel_per_lap, 3) + " " + backend.fuelSymbol
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.5
                            Text {
                                text: i18n.tr("Lap Time")
                                color: theme.text
                                Layout.fillWidth: true
                            }
                            TextField {
                                id: lapTime
                                Layout.preferredWidth: theme.em * 7.5
                                implicitHeight: Math.round(theme.em * 2.05)
                                text: tab.inputs.lap_time_text
                                horizontalAlignment: TextInput.AlignRight
                                verticalAlignment: TextInput.AlignVCenter
                                color: theme.text
                                selectionColor: theme.accent
                                selectedTextColor: "white"
                                selectByMouse: true
                                font.features: { "tnum": 1 }
                                leftPadding: theme.em * 0.5
                                rightPadding: theme.em * 0.55
                                Accessible.name: i18n.tr("Lap Time")
                                ToolTip.visible: hovered && !activeFocus
                                ToolTip.text: i18n.tr("Minutes:seconds.milliseconds, Up / Down: 0.1 s (Shift: 1 s)")
                                ToolTip.delay: 700
                                background: Rectangle {
                                    radius: theme.em * 0.4
                                    color: theme.dark ? Qt.darker(theme.base, 1.3) : Qt.darker(theme.base, 1.03)
                                    border.width: lapTime.activeFocus ? 1.5 : 1
                                    border.color: lapTime.activeFocus ? theme.accent : theme.border
                                }
                                onEditingFinished: text = backend.setLapTime(text)
                                onActiveFocusChanged: activeFocus ? selectAll() : (text = tab.inputs.lap_time_text)
                                Keys.onUpPressed: function(event) { text = backend.stepLapTime(event.modifiers & Qt.ShiftModifier ? 1 : 0.1); selectAll() }
                                Keys.onDownPressed: function(event) { text = backend.stepLapTime(event.modifiers & Qt.ShiftModifier ? -1 : -0.1); selectAll() }
                                Connections {
                                    target: backend
                                    function onInputsChanged() {
                                        if (!lapTime.activeFocus)
                                            lapTime.text = tab.inputs.lap_time_text
                                    }
                                }
                            }
                        }
                        RaceNumber { store: tab.store; key: "input_fuel_per_lap"; label: i18n.tr("Fuel per Lap") }
                        RaceNumber {
                            store: tab.store; key: "input_energy_per_lap"; label: i18n.tr("Energy per Lap")
                            tip: i18n.tr("Virtual energy, 0 if the car has none")
                        }
                        RaceNumber { store: tab.store; key: "input_tank_capacity"; label: i18n.tr("Tank Capacity") }
                        ValueRow {
                            label: i18n.tr("F/E Ratio")
                            value: tab.calc.fuelRatio || "-"
                            tip: i18n.tr("Fuel used per 1% of virtual energy")
                        }
                        Note { text: tab.notes.fillSource }
                    }

                    RaceSection {
                        store: tab.store
                        name: "start"
                        title: i18n.tr("Start")
                        glyph: ""  // flag
                        summary: tab.inputs.start_time_text
                        RaceNumber {
                            store: tab.store; key: "input_fuel_start"; label: i18n.tr("Starting Fuel")
                            tip: i18n.tr("0 = full tank, or exactly what the race needs without a stop")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_energy_start"; label: i18n.tr("Starting Energy")
                            tip: i18n.tr("0 = full, or exactly what the race needs without a stop")
                        }
                        Note { text: i18n.tr("0 = full tank"); horizontalAlignment: Text.AlignRight }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.5
                            RaceSwitch {
                                text: i18n.tr("Start Time")
                                tip: i18n.tr("Pit stops shown at their time of day, unchecked: race time")
                                on: tab.inputs.start_time_text !== ""
                                onSwitched: function(on) { startTime.text = backend.setStartTime(on, startTime.text) }
                            }
                            TextField {
                                id: startTime
                                enabled: tab.inputs.start_time_text !== ""
                                Layout.preferredWidth: theme.em * 5.5
                                implicitHeight: Math.round(theme.em * 2.05)
                                text: tab.inputs.start_time_text
                                placeholderText: "hh:mm"
                                placeholderTextColor: theme.dimText
                                horizontalAlignment: TextInput.AlignHCenter
                                verticalAlignment: TextInput.AlignVCenter
                                color: theme.text
                                selectByMouse: true
                                selectionColor: theme.accent
                                selectedTextColor: "white"
                                opacity: enabled ? 1 : 0.5
                                Accessible.name: i18n.tr("Start Time")
                                ToolTip.visible: hovered && !activeFocus
                                ToolTip.text: i18n.tr("Time of day of the race start")
                                ToolTip.delay: 700
                                background: Rectangle {
                                    radius: theme.em * 0.4
                                    color: theme.dark ? Qt.darker(theme.base, 1.3) : Qt.darker(theme.base, 1.03)
                                    border.width: startTime.activeFocus ? 1.5 : 1
                                    border.color: startTime.activeFocus ? theme.accent : theme.border
                                }
                                onEditingFinished: text = backend.setStartTime(true, text)
                                Connections {
                                    target: backend
                                    function onInputsChanged() {
                                        if (!startTime.activeFocus)
                                            startTime.text = tab.inputs.start_time_text
                                    }
                                }
                            }
                        }
                    }

                    RaceSection {
                        store: tab.store
                        name: "pit"
                        title: i18n.tr("Pit Stop")
                        glyph: ""  // repair
                        RaceNumber {
                            store: tab.store; key: "input_refuel_rate"; label: i18n.tr("Refuel Rate")
                            tip: i18n.tr("Fuel added per second, 0 = refuelling time included in pit stop time")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_energy_rate"; label: i18n.tr("Energy Rate")
                            tip: i18n.tr("Energy added per second, 0 = included in pit stop time")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_driver_change_seconds"; label: i18n.tr("Driver Change")
                            tip: i18n.tr("Time added to every stop when drivers take turns")
                        }
                        RaceSwitch {
                            store: tab.store; key: "enable_tyres_during_refuel"
                            text: i18n.tr("Tyres Changed While Refuelling")
                            tip: i18n.tr("Longest of refuelling and tyre change counts, not both")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_pit_lap_consumption"; label: i18n.tr("In & Out Laps")
                            tip: i18n.tr("Consumption of the laps into & out of the pits (pit lane speed limit), % of race pace")
                        }
                    }

                    RaceSection {
                        store: tab.store
                        name: "rules"
                        title: i18n.tr("Race Rules")
                        glyph: ""  // document
                        RaceNumber {
                            store: tab.store; key: "input_minimum_stops"; label: i18n.tr("Mandatory Stops")
                            tip: i18n.tr("Stints shortened evenly until the race has at least this many stops")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_max_stint_minutes"; label: i18n.tr("Max Stint Time")
                            tip: i18n.tr("Driver limit: longest stint allowed, 0 = none")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_drivers"; label: i18n.tr("Drivers")
                            tip: i18n.tr("Drivers taking turns, driver change after their stints (Drivers card)")
                        }
                        RaceSwitch {
                            store: tab.store; key: "enable_balanced_stints"
                            text: i18n.tr("Balanced Stints")
                            tip: i18n.tr("Race laps spread evenly over the stints, same stops (no short splash stint at the end)")
                        }
                        RaceSwitch {
                            store: tab.store; key: "enable_leader_finish"
                            text: i18n.tr("Leader Finishes First (+1 Lap)")
                            tip: i18n.tr("Time race: the race ends when the leader crosses the line after the timer, so a car behind may drive one lap more (fuel for it)")
                        }
                    }

                    RaceSection {
                        store: tab.store
                        visible: Number(tab.inputs.input_drivers) > 1
                        name: "drivers"
                        title: i18n.tr("Drivers")
                        glyph: ""  // people
                        RaceNumber {
                            store: tab.store; key: "input_stints_per_driver"; label: i18n.tr("Stints per Driver")
                            tip: i18n.tr("Stints driven before the next driver takes over")
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 4
                            columnSpacing: theme.em * 0.3
                            rowSpacing: theme.em * 0.3
                            Repeater {
                                model: [
                                    { text: i18n.tr("Driver"), tip: "" },
                                    { text: i18n.tr("Pace"), tip: i18n.tr("Lap time difference of the driver (seconds)") },
                                    { text: i18n.tr("Min"), tip: i18n.tr("Total driving time the driver must reach (minutes), 0 = none") },
                                    { text: i18n.tr("Max"), tip: i18n.tr("Total driving time allowed to the driver (minutes), 0 = none") },
                                ]
                                Text {
                                    required property var modelData
                                    text: modelData.text
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.85
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    HoverHandler { id: driverHeadHover; enabled: parent.modelData.tip !== "" }
                                    ToolTip.visible: driverHeadHover.hovered
                                    ToolTip.text: modelData.tip
                                    ToolTip.delay: 500
                                }
                            }
                            Repeater {
                                model: Math.min(Number(tab.inputs.input_drivers), backend.maxDrivers) * 4
                                Item {
                                    id: driverCell
                                    required property int index
                                    readonly property int driver: Math.floor(index / 4)
                                    readonly property int column: index % 4 - 1
                                    readonly property var spec: column >= 0 ? tab.store.specs["driver_" + column] : null
                                    Layout.fillWidth: true
                                    implicitHeight: Math.round(theme.em * 2.05)
                                    implicitWidth: column < 0 ? theme.em * 1.8 : theme.em * 5
                                    Text {
                                        visible: driverCell.column < 0
                                        anchors.centerIn: parent
                                        text: driverCell.driver + 1
                                        color: theme.text
                                        font.weight: Font.DemiBold
                                    }
                                    NumberField {
                                        visible: driverCell.column >= 0
                                        anchors.fill: parent
                                        value: driverCell.column >= 0 ? tab.inputs.drivers_table[driverCell.driver][driverCell.column] : 0
                                        decimals: driverCell.spec ? driverCell.spec.decimals : 0
                                        step: driverCell.spec ? driverCell.spec.step : 1
                                        minimum: driverCell.spec ? driverCell.spec.min : 0
                                        maximum: driverCell.spec ? driverCell.spec.max : 0
                                        suffix: driverCell.spec ? driverCell.spec.suffix : ""
                                        leftPadding: theme.em * 0.3
                                        onEdited: function(number) { backend.setDriverValue(driverCell.driver, driverCell.column, number) }
                                    }
                                }
                            }
                        }
                    }

                    RaceSection {
                        store: tab.store
                        name: "pace"
                        title: i18n.tr("Pace")
                        glyph: ""  // speed
                        RaceNumber {
                            store: tab.store; key: "input_fuel_effect"; label: i18n.tr("Fuel Effect")
                            tip: i18n.tr("Lap time lost per 10 fuel units in the tank (lap time is the one at half tank)")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_track_evolution"; label: i18n.tr("Track Evolution")
                            tip: i18n.tr("Lap time change per hour of race, negative when the track gets faster")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_saving_cost"; label: i18n.tr("Saving Cost")
                            tip: i18n.tr("Lap time lost per 10% less consumption (lift & coast): saving target & strategy comparison count it")
                        }
                        TpButton {
                            Layout.fillWidth: true
                            glyph: ""  // history
                            text: i18n.tr("Estimate from History")
                            tip: i18n.tr("Pit stop time, fuel effect & track evolution from the laps of the consumption history (stints & stops in a row)")
                            onClicked: backend.estimateFromHistory()
                        }
                        Note { text: tab.notes.estimate }
                    }

                    RaceSection {
                        store: tab.store
                        name: "safety_car"
                        switchKey: "enable_safety_car"
                        title: i18n.tr("Safety Car")
                        glyph: ""  // warning
                        tip: i18n.tr("Plan with a safety car (or full course yellow) period")
                        RaceNumber {
                            store: tab.store; key: "input_sc_lap"; label: i18n.tr("From Lap")
                            tip: i18n.tr("First lap under safety car (lap of the plan)")
                        }
                        RaceNumber { store: tab.store; key: "input_sc_laps"; label: i18n.tr("Laps"); tip: i18n.tr("Laps under safety car") }
                        RaceNumber {
                            store: tab.store; key: "input_sc_consumption"; label: i18n.tr("Consumption")
                            tip: i18n.tr("Consumption under safety car, % of race pace")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_sc_laptime"; label: i18n.tr("Lap Time")
                            tip: i18n.tr("Lap time under safety car, % of race pace")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_sc_wear"; label: i18n.tr("Tyre Wear")
                            tip: i18n.tr("Tyre wear under safety car, % of race pace")
                        }
                        RaceSwitch {
                            store: tab.store; key: "enable_sc_pit"
                            text: i18n.tr("Stop under Safety Car")
                            tip: i18n.tr("Stop at the end of the first lap under safety car")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_sc_pit_saving"; label: i18n.tr("Pit Time Saved")
                            tip: i18n.tr("Part of pit lane time not lost under safety car")
                        }
                        Note { text: tab.scenarios.safetyCar || "" }
                    }

                    RaceSection {
                        store: tab.store
                        name: "rain"
                        switchKey: "enable_rain"
                        title: i18n.tr("Rain")
                        glyph: ""  // drop
                        tip: i18n.tr("Plan with a wet period")
                        RaceNumber {
                            store: tab.store; key: "input_rain_lap"; label: i18n.tr("From Lap")
                            tip: i18n.tr("First lap in the wet (lap of the plan)")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_rain_laps"; label: i18n.tr("Laps")
                            tip: i18n.tr("Laps in the wet, 0 = until the finish")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_rain_consumption"; label: i18n.tr("Consumption")
                            tip: i18n.tr("Consumption in the wet, % of race pace")
                        }
                        RaceNumber {
                            store: tab.store; key: "input_rain_laptime"; label: i18n.tr("Lap Time")
                            tip: i18n.tr("Lap time in the wet, % of race pace")
                        }
                        RaceSwitch {
                            store: tab.store; key: "enable_rain_tyres"
                            text: i18n.tr("Wet Tyres")
                            tip: i18n.tr("Stop for wet tyres at the end of the first lap in the wet, and for slicks at the end of the last one (4 tyres)")
                        }
                        Note { text: tab.scenarios.rain || "" }
                    }
                    Item { Layout.fillHeight: true }
                }

                // Results
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    spacing: theme.em * 0.5

                    RaceCard {
                        id: planCard
                        readonly property var plan: backend.plan
                        title: plan.title || i18n.tr("Pit Stop Plan")
                        glyph: ""  // repair
                        actions: [
                            Rectangle {  // fuel unit of the plan (team using another unit)
                                height: Math.round(theme.em * 1.6)
                                width: unitLabel.implicitWidth + theme.em * 0.9
                                radius: theme.em * 0.35
                                color: "transparent"
                                border.width: 1
                                border.color: theme.accent
                                anchors.verticalCenter: parent ? parent.verticalCenter : undefined
                                Text {
                                    id: unitLabel
                                    anchors.centerIn: parent
                                    text: backend.fuelSymbol
                                    color: theme.accent
                                    font.weight: Font.DemiBold
                                }
                                HoverHandler { id: unitHover }
                                ToolTip.visible: unitHover.hovered
                                ToolTip.text: i18n.tr("Fuel unit of the plan (Units setting)")
                                ToolTip.delay: 500
                            },
                            TpButton {
                                id: exportButton
                                enabled: planCard.plan.ready === true
                                glyph: ""  // share
                                text: i18n.tr("Export")
                                tip: i18n.tr("Pit stop plan as text, for Discord, as spreadsheet or image")
                                onClicked: exportMenu.popup(exportButton, 0, exportButton.height + 4)
                                TpMenu {
                                    id: exportMenu
                                    MenuItem { text: i18n.tr("Copy as Text"); onTriggered: backend.copyPlanText() }
                                    MenuItem { text: i18n.tr("Copy for Discord"); onTriggered: backend.copyPlanMarkdown() }
                                    MenuSeparator {}
                                    MenuItem { text: i18n.tr("Export CSV..."); onTriggered: backend.exportPlanCsv() }
                                    MenuItem { text: i18n.tr("Save Image..."); onTriggered: backend.savePlanImage() }
                                    MenuItem { text: i18n.tr("Copy Picture"); onTriggered: backend.copyPlanImage() }
                                }
                            }
                        ]
                        RaceTable {
                            Layout.fillWidth: true
                            visible: planCard.plan.ready === true
                            columns: planCard.plan.columns || []
                            rows: planCard.plan.rows || []
                            hidden: {
                                var keys = planCard.plan.hidden || []
                                var columns = planCard.plan.columns || []
                                var list = []
                                for (var index = 0; index < columns.length; index++)
                                    if (keys.indexOf(columns[index].key) >= 0)
                                        list.push(index)
                                return list
                            }
                            colorColumn: 6
                            cellColor: tab.tyreColor
                        }
                        Text {
                            visible: planCard.plan.ready !== true
                            Layout.fillWidth: true
                            text: i18n.tr("Enter lap time, consumption and race length")
                            color: theme.dimText
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                        }
                    }

                    RaceCard {
                        id: timesCard
                        readonly property var times: backend.driverTimes
                        visible: times.visible === true
                        title: i18n.tr("Driving Time")
                        glyph: ""  // people
                        warning: times.warning === true
                        RaceTable {
                            Layout.fillWidth: true
                            columns: timesCard.times.columns || []
                            rows: timesCard.times.rows || []
                        }
                    }

                    RaceCard {
                        id: detailCard
                        readonly property var details: backend.details
                        title: i18n.tr("Details")
                        glyph: ""  // chart
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 4
                            columnSpacing: theme.em * 0.8
                            rowSpacing: theme.em * 0.25
                            Item { Layout.fillWidth: true; implicitHeight: 1 }
                            Text {
                                text: detailCard.details.fuelTitle || ""
                                color: theme.dimText
                                font.weight: Font.DemiBold
                                opacity: detailCard.details.fuelEnabled ? 1 : 0.4
                                Layout.alignment: Qt.AlignRight
                            }
                            Text {
                                text: detailCard.details.energyTitle || ""
                                color: theme.dimText
                                font.weight: Font.DemiBold
                                opacity: detailCard.details.energyEnabled ? 1 : 0.4
                                Layout.alignment: Qt.AlignRight
                            }
                            Item { implicitWidth: theme.em * 3; implicitHeight: 1 }
                            Repeater {
                                model: (detailCard.details.rows || []).length * 4
                                Text {
                                    required property int index
                                    readonly property var row: detailCard.details.rows[Math.floor(index / 4)]
                                    readonly property int column: index % 4
                                    text: column === 0 ? row.title : column === 1 ? row.fuel : column === 2 ? row.energy : row.unit
                                    color: column === 0 ? theme.text : column === 3 ? theme.dimText : theme.text
                                    font.weight: column === 1 || column === 2 ? Font.DemiBold : Font.Normal
                                    font.features: { "tnum": 1 }
                                    opacity: column === 1 && !detailCard.details.fuelEnabled
                                             || column === 2 && !detailCard.details.energyEnabled ? 0.4 : 1
                                    elide: column === 0 ? Text.ElideRight : Text.ElideNone
                                    Layout.fillWidth: column === 0
                                    Layout.alignment: column === 1 || column === 2 ? Qt.AlignRight : Qt.AlignLeft
                                    HoverHandler { id: detailHover; enabled: parent.column === 0 }
                                    ToolTip.visible: detailHover.hovered
                                    ToolTip.text: row.tip
                                    ToolTip.delay: 500
                                }
                            }
                        }
                    }

                    RaceCard {
                        title: i18n.tr("Saving Target")
                        glyph: ""  // drop
                        Note { text: tab.scenarios.oneLess || ""; color: theme.text }
                        RaceNumber {
                            store: tab.store; key: "input_target_stint_laps"; label: i18n.tr("Laps per Stint")
                            tip: i18n.tr("Laps per stint to aim for, 0 = none")
                        }
                        Note { text: tab.scenarios.target || "" }
                    }

                    RaceCard {
                        id: comparisonCard
                        readonly property var comparison: tab.scenarios.comparison || ({})
                        visible: comparison.visible === true
                        title: i18n.tr("Strategy Comparison")
                        glyph: ""  // switch
                        tip: i18n.tr("Plans with fewer stops (fuel saving) or one stop more, best one in bold. Fuel & energy per lap, lap time lost to saving.")
                        RaceTable {
                            Layout.fillWidth: true
                            columns: comparisonCard.comparison.columns || []
                            rows: comparisonCard.comparison.rows || []
                            hidden: comparisonCard.comparison.hidden || []
                            boldRow: comparisonCard.comparison.best !== undefined ? comparisonCard.comparison.best : -1
                        }
                        Note { text: i18n.tr("Saving cost (Pace card) slows the laps of plans saving fuel.") }
                    }

                    RaceCard {
                        id: againstCard
                        readonly property var against: backend.planVsRace
                        visible: against.visible === true
                        title: i18n.tr("Plan against Race")
                        glyph: ""  // activity
                        tip: i18n.tr("Stints driven (consumption history of this race) against the plan: race value / plan value")
                        RaceTable {
                            Layout.fillWidth: true
                            columns: againstCard.against.columns || []
                            rows: againstCard.against.rows || []
                            hidden: againstCard.against.hidden || []
                        }
                    }

                    RaceCard {
                        id: rivalsCard
                        readonly property var rivals: backend.rivals
                        visible: rivals.visible === true
                        title: i18n.tr("Class Rivals")
                        glyph: ""  // car
                        tip: i18n.tr("Cars of your class in the live race. Next stop: lap of last stop seen (while the page is open) plus your full tank laps, ~ when unknown")
                        RaceTable {
                            Layout.fillWidth: true
                            columns: rivalsCard.rivals.columns || []
                            rows: rivalsCard.rivals.rows || []
                            boldRow: rivalsCard.rivals.player !== undefined ? rivalsCard.rivals.player : -1
                        }
                    }
                }
            }
        }

        RaceHistory {
            visible: tab.showHistory
            Layout.fillWidth: !tab.sideHistory
            Layout.fillHeight: tab.sideHistory
            Layout.preferredWidth: tab.sideHistory ? Math.max(tab.width * 0.36, theme.em * 24) : -1
            Layout.preferredHeight: tab.sideHistory ? -1 : Math.max(tab.height * 0.42, theme.em * 14)
        }
    }
}
