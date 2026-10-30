import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator switch: TpSwitch (focus ring, Space / Enter, wrapped label) showing an on / off input of the
// backend (key), or the state given in on. Clicked: input changed (key), switched(on) told; the shown state
// always follows on (backend value), never the click alone (not checkable: the click never breaks the binding).
TpSwitch {
    id: control
    property var store  // page: inputs
    property string key: ""
    property bool on: key !== "" && store ? Boolean(store.inputs[key]) : false
    signal switched(bool on)

    wrap: true
    Layout.fillWidth: true
    checkable: false
    checked: on
    onClicked: {
        var value = !on
        if (key !== "")
            backend.setInput(key, value)
        switched(value)
    }
}
