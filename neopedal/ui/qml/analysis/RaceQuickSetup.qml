import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// First use of the race calculator: race length, pit stop time and where laps & consumption come from, then the
// whole page (everything stays editable there). Skip shows the page at once; never asked again either way.
TpSectionCard {
    id: quick
    objectName: "quickSetup"
    property var store  // page: inputs, specs & source choice
    readonly property var inputs: store ? store.inputs : ({})
    readonly property bool lapRace: inputs.enable_lap_race === true
    readonly property var lengthSpec: store ? store.specs[lapRace ? "input_race_laps" : "input_race_minutes"] : null
    readonly property var pitSpec: store ? store.specs.input_pit_seconds : null


    component Question: TpText {
        Layout.fillWidth: true
        font.weight: Font.DemiBold
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
    }
    glyph: ""  // calculator
    title: i18n.tr("Plan a Race in 3 Questions")
    spacing: theme.space4

    TpText { Layout.fillWidth: true; role: "caption"; wrap: true; text: i18n.tr("Then the whole calculator shows: every value stays editable there.") }

    Question { text: "1. " + i18n.tr("How long is the race?") }
    Flow {
        Layout.fillWidth: true
        spacing: theme.space3
        TpSegmented {
            objectName: "quickRaceType"
            name: i18n.tr("Race Type")
            options: [i18n.tr("Time"), i18n.tr("Laps")]
            currentIndex: quick.lapRace ? 1 : 0
            onActivated: function(index) { backend.setInput("enable_lap_race", index === 1) }
        }
        NumberField {
            objectName: "quickRaceLength"
            width: theme.em * 8.5
            showRange: quick.lengthSpec !== null && quick.lengthSpec !== undefined
            value: Number(quick.inputs[quick.lapRace ? "input_race_laps" : "input_race_minutes"])
            decimals: quick.lengthSpec ? quick.lengthSpec.decimals : 0
            step: quick.lengthSpec ? quick.lengthSpec.step : 1
            minimum: quick.lengthSpec ? quick.lengthSpec.min : 0
            maximum: quick.lengthSpec ? quick.lengthSpec.max : 9999
            suffix: quick.lengthSpec ? quick.lengthSpec.suffix : ""
            Accessible.name: quick.lapRace ? i18n.tr("Race Laps") : i18n.tr("Duration")
            onEdited: function(number) {
                backend.setInput(quick.lapRace ? "input_race_laps" : "input_race_minutes", number)
            }
        }
    }

    Question { text: "2. " + i18n.tr("How much time does a pit stop cost?") }
    NumberField {
        objectName: "quickPitTime"
        Layout.preferredWidth: theme.em * 8.5
        showRange: quick.pitSpec !== null && quick.pitSpec !== undefined
        value: Number(quick.inputs.input_pit_seconds)
        decimals: quick.pitSpec ? quick.pitSpec.decimals : 0
        step: quick.pitSpec ? quick.pitSpec.step : 1
        minimum: quick.pitSpec ? quick.pitSpec.min : 0
        maximum: quick.pitSpec ? quick.pitSpec.max : 9999
        suffix: quick.pitSpec ? quick.pitSpec.suffix : ""
        tip: i18n.tr("Time lost per stop, tyre change time of the tyre plan added (time race: fewer laps fit in the race time)")
        Accessible.name: i18n.tr("Pit Stop Time")
        onEdited: function(number) { backend.setInput("input_pit_seconds", number) }
    }
    TpText { Layout.fillWidth: true; role: "caption"; wrap: true; text: i18n.tr("Pit lane in and out plus the stop, about 25 to 60 s: the game session fills it in once you made a stop.") }

    Question { text: "3. " + i18n.tr("Where do lap times & consumption come from?") }
    TpSegmented {
        id: quickSource
        objectName: "quickSource"
        name: i18n.tr("Data Source")
        options: [i18n.tr("File"), i18n.tr("Game Session")]
        currentIndex: quick.store && quick.store.header.live ? 1 : 0
        onActivated: function(index) { quick.store.chooseSource(index, quickSource) }
    }
    TpText {
        Layout.fillWidth: true
        role: "caption"
        wrap: true
        text: quick.store && quick.store.header.live
              ? i18n.tr("Game Session: laps you drive fill in lap time, fuel, energy & tyre wear (drive a few laps at race pace).")
              : i18n.tr("File: consumption history recorded before (Stint module), or a CSV file.")
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: theme.space2
        spacing: theme.space3
        Item { Layout.fillWidth: true }
        TpButton {
            objectName: "quickSkip"
            flat: true
            text: i18n.tr("Skip")
            tip: i18n.tr("Show the whole calculator now")
            onClicked: backend.finishQuickSetup()
        }
        TpButton {
            objectName: "quickDone"
            accent: true
            text: i18n.tr("Show Plan")
            onClicked: backend.finishQuickSetup()
        }
    }
}
