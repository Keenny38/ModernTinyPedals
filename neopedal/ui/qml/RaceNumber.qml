import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator input row: label (tooltip) & number field of an input of the backend, its range,
// decimals & unit from backend specs (spec given: own range, value & edit handled by the user)
RowLayout {
    id: row
    property var store  // page: inputs & specs
    property string key: ""
    property string label: ""
    property string tip: ""
    property var spec: key !== "" && store ? store.specs[key] : null
    property real value: key !== "" && store ? Number(store.inputs[key]) : 0
    property real fieldWidth: theme.em * 7.5
    signal edited(real value)

    spacing: theme.em * 0.5
    Layout.fillWidth: true

    Text {
        text: row.label
        color: theme.text
        elide: Text.ElideRight
        Layout.fillWidth: true
        Layout.minimumWidth: theme.em * 3
        HoverHandler { id: labelHover; enabled: row.tip !== "" }
        ToolTip.visible: labelHover.hovered
        ToolTip.text: row.tip
        ToolTip.delay: 500
    }
    NumberField {
        id: field
        Layout.preferredWidth: row.fieldWidth
        value: row.value
        decimals: row.spec ? row.spec.decimals : 0
        step: row.spec ? row.spec.step : 1
        minimum: row.spec ? row.spec.min : 0
        maximum: row.spec ? row.spec.max : 9999
        suffix: row.spec ? row.spec.suffix : ""
        tip: row.tip
        Accessible.name: row.label
        onEdited: function(number) {
            if (row.key !== "")
                backend.setInput(row.key, number)
            row.edited(number)
        }
    }
}
