import QtQuick
import QtQuick.Controls.Basic

// Number input: value shown with its decimals & unit, typed value applied on Enter or leaving the field
// (not at every key: a half typed value would plan the race again for nothing), Up / Down keys & wheel
// (once focused) step it (Shift: 10 steps), Esc puts the value back. Decimal comma accepted.
TextField {
    id: field
    property real value: 0
    property int decimals: 0
    property real step: 1
    property real minimum: 0
    property real maximum: 9999
    property string suffix: ""
    property string tip: ""
    signal edited(real value)  // value typed or stepped, in range

    function format(number) {
        return decimals > 0 ? Number(number).toFixed(decimals) : String(Math.round(number))
    }
    function clamp(number) {
        return Math.min(Math.max(number, minimum), maximum)
    }
    function commit() {
        var number = parseFloat(text.replace(",", ".").replace(/\s/g, ""))
        if (isNaN(number)) {
            text = format(value)
            return
        }
        number = clamp(number)
        // Text left as shown: value kept (not rounded to shown decimals), else typed number compared to
        // value, not to shown text: 4.6 typed over 5 shown without decimals is a change too
        if (text !== format(value) && number !== value)
            edited(number)
        text = format(value)
    }
    function stepBy(count) {
        var number = clamp(Math.round((value + step * count) * 1000000) / 1000000)
        if (number !== value)
            edited(number)
        text = format(value)
        selectAll()
    }

    text: format(value)
    onValueChanged: if (!activeFocus) text = format(value)
    onEditingFinished: commit()
    onActiveFocusChanged: {
        if (activeFocus)
            selectAll()
        else
            text = format(value)
    }
    Keys.onUpPressed: function(event) { stepBy(event.modifiers & Qt.ShiftModifier ? 10 : 1) }
    Keys.onDownPressed: function(event) { stepBy(event.modifiers & Qt.ShiftModifier ? -10 : -1) }
    Keys.onEscapePressed: function(event) {  // typed text dropped, page kept open
        text = format(value)
        focus = false
        event.accepted = true
    }

    implicitHeight: Math.round(theme.em * 2.05)
    implicitWidth: theme.em * 7.5
    horizontalAlignment: TextInput.AlignRight
    verticalAlignment: TextInput.AlignVCenter
    rightPadding: (unitText.visible ? unitText.implicitWidth + theme.em * 0.45 : 0) + theme.em * 0.55
    leftPadding: theme.em * 0.5
    color: theme.text
    selectionColor: theme.accent
    selectedTextColor: "white"
    selectByMouse: true
    font.features: { "tnum": 1 }
    inputMethodHints: Qt.ImhFormattedNumbersOnly
    opacity: enabled ? 1 : 0.5
    Accessible.name: tip

    ToolTip.visible: tip !== "" && hovered && !activeFocus
    ToolTip.text: tip
    ToolTip.delay: 700

    background: Rectangle {
        radius: theme.em * 0.4
        color: theme.dark ? Qt.darker(theme.base, 1.3) : Qt.darker(theme.base, 1.03)
        border.width: field.activeFocus ? 1.5 : 1
        border.color: field.activeFocus ? theme.accent : field.hovered ? Qt.lighter(theme.border, 1.2) : theme.border
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    Text {
        id: unitText
        visible: field.suffix !== ""
        text: field.suffix
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.9
        anchors.right: parent.right
        anchors.rightMargin: theme.em * 0.5
        anchors.verticalCenter: parent.verticalCenter
    }

    WheelHandler {
        enabled: field.activeFocus
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
            field.stepBy(event.angleDelta.y > 0 ? 1 : -1)
            event.accepted = true
        }
    }
}
