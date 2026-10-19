import QtQuick
import QtQuick.Layouts
import "../components"

// Lap compared with reference lap (corner table, gain / loss & racing line map): one chip per comparable lap,
// lap color dot & name, chosen lap selected. Shown when there is a choice (two laps or more).
//   ComparedLapPicker { laps: backend.comparedLaps; currentKey: backend.cornerTable.compareKey
//                       onPicked: function(key) { backend.cornerTable.setCompareKey(key) } }
Flow {
    id: picker
    property var laps: []  // {key, label, color}
    property string currentKey: ""
    signal picked(string key)

    visible: laps.length > 1
    spacing: theme.space2
    Text {
        text: i18n.tr("Compared:")
        color: theme.dimText
        height: Math.round(theme.em * 1.7)
        verticalAlignment: Text.AlignVCenter
    }
    Repeater {
        model: picker.laps
        TpChip {
            required property var modelData
            size: "sm"
            multi: false
            showDot: true
            dotColor: modelData.color
            text: modelData.label
            selected: picker.currentKey === modelData.key
            onClicked: picker.picked(modelData.key)
        }
    }
}
