import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator switch: TpSwitch (focus ring, Space / Enter, wrapped label) showing an on / off input of the
// backend (key), or the state given in on. Clicked: input changed (key), switched(on) told; the shown state
// always follows on (backend value), never the click alone.
TpSwitch {
    id: control
    property var store  // page: inputs
    property string key: ""
    property bool on: key !== "" && store ? Boolean(store.inputs[key]) : false
    signal switched(bool on)

    wrap: true
    Layout.fillWidth: true
    checked: on
    onToggled: {
        var value = checked
        checked = Qt.binding(function() { return control.on })  // backend tells the state
        if (key !== "")
            backend.setInput(key, value)
        switched(value)
    }
}
