import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator race setup, shared by all tabs: race type (time or laps) & length, formation laps,
// pit stop time, safety margin & its unit. Fields wrap on narrow pages.
Card {
    id: setup
    property var store  // page: inputs & specs
    readonly property var inputs: store ? store.inputs : ({})
    readonly property bool lapRace: inputs.enable_lap_race === true
    readonly property real pad: theme.padCard

    implicitHeight: flow.implicitHeight + pad * 2

    component Caption: TpText {  // names & values, never markup
        property string tip: ""
        role: "caption"
        elide: Text.ElideNone
        HoverHandler { id: captionHover; enabled: parent.tip !== "" }
        ToolTip.visible: captionHover.hovered
        ToolTip.text: tip
        ToolTip.delay: theme.tipDelay
    }
    component SetupField: Column {
        id: setupField
        property string key: ""
        property string label: ""
        property string tip: ""
        property var store
        property var spec: store ? store.specs[key] : null
        spacing: theme.space1
        Caption { text: setupField.label; tip: setupField.tip }
        NumberField {
            width: theme.em * 8.5
            showRange: setupField.spec !== null && setupField.spec !== undefined
            value: setupField.store ? Number(setupField.store.inputs[setupField.key]) : 0
            decimals: setupField.spec ? setupField.spec.decimals : 0
            step: setupField.spec ? setupField.spec.step : 1
            minimum: setupField.spec ? setupField.spec.min : 0
            maximum: setupField.spec ? setupField.spec.max : 9999
            suffix: setupField.spec ? setupField.spec.suffix : ""
            tip: setupField.tip
            Accessible.name: setupField.label
            onEdited: function(number) { backend.setInput(setupField.key, number) }
        }
    }

    Flow {
        id: flow
        x: setup.pad
        y: setup.pad
        width: setup.width - setup.pad * 2
        spacing: theme.space6

        Column {
            spacing: theme.space1
            Caption { text: i18n.tr("Race Type") }
            TpSegmented {
                id: raceType
                name: i18n.tr("Race Type")
                options: [i18n.tr("Time"), i18n.tr("Laps")]
                currentIndex: setup.lapRace ? 1 : 0
                implicitHeight: Math.round(theme.fieldHeight)  // as the fields next to it
                onActivated: function(index) { backend.setInput("enable_lap_race", index === 1) }
            }
        }
        SetupField {
            store: setup.store
            visible: !setup.lapRace
            key: "input_race_minutes"
            label: i18n.tr("Duration")
        }
        SetupField {
            store: setup.store
            visible: setup.lapRace
            key: "input_race_laps"
            label: i18n.tr("Race Laps")
        }
        SetupField {
            store: setup.store
            key: "input_formation_laps"
            label: i18n.tr("Formation / Rolling")
            tip: i18n.tr("Laps driven before the race counts, fuel needed for them too")
        }
        SetupField {
            store: setup.store
            key: "input_pit_seconds"
            label: i18n.tr("Pit Stop Time")
            tip: i18n.tr("Time lost per stop, tyre change time of the tyre plan added (time race: fewer laps fit in the race time)")
        }
        Column {
            id: marginColumn
            spacing: theme.space1
            readonly property var spec: backend.marginSpec
            readonly property string tip: i18n.tr("Fuel kept in the tank at every stop and at the finish: laps of fuel, fuel, or % more consumption per lap")
            Caption { text: i18n.tr("Safety Margin"); tip: marginColumn.tip }
            Row {
                spacing: theme.space2
                NumberField {
                    width: theme.em * 7
                    value: Number(setup.inputs.input_safety_margin)
                    decimals: marginColumn.spec.decimals
                    step: marginColumn.spec.step
                    minimum: marginColumn.spec.min
                    maximum: marginColumn.spec.max
                    suffix: marginColumn.spec.suffix
                    showRange: true
                    tip: marginColumn.tip
                    Accessible.name: i18n.tr("Safety Margin")
                    onEdited: function(number) { backend.setInput("input_safety_margin", number) }
                }
                TpSegmented {
                    id: marginUnit
                    name: i18n.tr("Safety Margin")
                    options: backend.marginUnits
                    currentIndex: Number(setup.inputs.input_safety_margin_kind)
                    implicitHeight: Math.round(theme.fieldHeight)  // as the fields next to it
                    ToolTip.visible: unitHover.hovered
                    ToolTip.text: i18n.tr("Safety margin in laps, in fuel kept in the tank, or in % more consumption per lap")
                    ToolTip.delay: theme.tipDelay
                    HoverHandler { id: unitHover }
                    onActivated: function(index) { backend.setInput("input_safety_margin_kind", index) }
                }
            }
        }
    }
}
