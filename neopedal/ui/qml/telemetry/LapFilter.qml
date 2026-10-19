import QtQuick
import QtQuick.Controls.Basic

// Lap chips of shown laps: click (or Space / Enter once reached with Tab) to hide or show a lap in this view only
// (charts keep every lap). Hidden lap: no tint, name struck through
Flow {
    id: filter

    property var hidden: ({})  // lap key: true while hidden in this view
    // Chip tooltips translated once (not per chip), made while hovered
    readonly property string hideHint: i18n.tr("Click: hide in this view")
    readonly property string showHint: i18n.tr("Click: show in this view")

    // Shown laps read once per chart change: each backend.legend read converts a Python list of dicts, and shown()
    // is called for every G circle & scatter point on each cursor move
    readonly property var legend: backend.legend
    readonly property bool single: legend.length <= 1  // lap alone: always shown (no chips to show it again)
    // Lap marks (1, 2, 3... in legend order, as on chart chips & values)
    readonly property var marks: {
        var legend = filter.legend, found = {}
        if (legend.length > 1)
            for (var i = 0; i < legend.length; i++) found[legend[i].key] = String(i + 1)
        return found
    }
    function shown(lapKey) { return single || hidden[lapKey] !== true }
    // Hidden laps no longer compared forgotten (a lap compared again is shown), all of them once a lap is
    // alone (still shown when another lap is added). Run once legend property holds the new laps
    onLegendChanged: forgetRemoved()
    function forgetRemoved() {
        var keys = Object.keys(hidden)
        if (!keys.length) return
        var legend = filter.legend, kept = {}, changed = false
        if (legend.length <= 1) { hidden = {}; return }
        var present = {}
        for (var i = 0; i < legend.length; i++) present[legend[i].key] = true
        for (var k = 0; k < keys.length; k++) {
            if (present[keys[k]]) kept[keys[k]] = true
            else changed = true
        }
        if (changed) hidden = kept
    }
    function toggle(lapKey) {
        var next = Object.assign({}, hidden)
        if (next[lapKey] === true) delete next[lapKey]
        else next[lapKey] = true
        hidden = next
    }

    visible: !single
    spacing: theme.space2
    Repeater {
        model: backend.legendModel
        LapChip {
            id: chip
            readonly property bool lapShown: filter.shown(model.key)
            size: "sm"
            lapColor: model.color
            label: model.label
            mark: filter.marks[model.key] || ""
            struck: !lapShown
            tip: chip.hovered || chip.activeFocus ? model.full + "\n" + (lapShown ? filter.hideHint : filter.showHint) : ""
            onClicked: filter.toggle(model.key)
        }
    }
}
