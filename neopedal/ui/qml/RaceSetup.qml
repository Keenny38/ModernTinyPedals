import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator race setup, shared by all tabs: race type (time or laps) & length, formation laps,
// pit stop time, safety margin & its unit. Fields wrap on narrow pages.
Card {
    id: setup
    property var store  // page: inputs & specs
    readonly property var inputs: store ? store.inputs : ({})
    readonly property bool lapRace: inputs.enable_lap_race === true
    readonly property real pad: theme.em * 0.7

    implicitHeight: flow.implicitHeight + pad * 2

    component Caption: Text {
        property string tip: ""
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.85
        HoverHandler { id: captionHover; enabled: parent.tip !== "" }
        ToolTip.visible: captionHover.hovered
        ToolTip.text: tip
        ToolTip.delay: 500
    }
    component SetupField: Column {
        id: setupField
        property string key: ""
        property string label: ""
        property string tip: ""
        property var store
        property var spec: store ? store.specs[key] : null
        spacing: 3
        Caption { text: setupField.label; tip: setupField.tip }
        NumberField {
            width: theme.em * 8.5
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
        spacing: theme.em * 1.1

        Column {
            spacing: 3
            Caption { text: i18n.tr("Race Type") }
            TpSegmented {
                id: raceType
                options: [i18n.tr("Time"), i18n.tr("Laps")]
                currentIndex: setup.lapRace ? 1 : 0
                implicitHeight: Math.round(theme.em * 2.05)
                onActivated: function(index) {
                    backend.setInput("enable_lap_race", index === 1)
                    currentIndex = Qt.binding(function() { return setup.lapRace ? 1 : 0 })
                }
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
            spacing: 3
            readonly property var spec: backend.marginSpec
            readonly property string tip: i18n.tr("Fuel kept in the tank at every stop and at the finish: laps of fuel, fuel, or % more consumption per lap")
            Caption { text: i18n.tr("Safety Margin"); tip: marginColumn.tip }
            Row {
                spacing: theme.em * 0.3
                NumberField {
                    width: theme.em * 7
                    value: Number(setup.inputs.input_safety_margin)
                    decimals: marginColumn.spec.decimals
                    step: marginColumn.spec.step
                    minimum: marginColumn.spec.min
                    maximum: marginColumn.spec.max
                    suffix: marginColumn.spec.suffix
                    tip: marginColumn.tip
                    Accessible.name: i18n.tr("Safety Margin")
                    onEdited: function(number) { backend.setInput("input_safety_margin", number) }
                }
                TpSegmented {
                    id: marginUnit
                    options: backend.marginUnits
                    currentIndex: Number(setup.inputs.input_safety_margin_kind)
                    implicitHeight: Math.round(theme.em * 2.05)
                    ToolTip.visible: unitHover.hovered
                    ToolTip.text: i18n.tr("Safety margin in laps, in fuel kept in the tank, or in % more consumption per lap")
                    ToolTip.delay: 600
                    HoverHandler { id: unitHover }
                    onActivated: function(index) {
                        backend.setInput("input_safety_margin_kind", index)
                        currentIndex = Qt.binding(function() { return Number(setup.inputs.input_safety_margin_kind) })
                    }
                }
            }
        }
    }
}
