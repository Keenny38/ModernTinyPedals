import QtQuick
import QtQuick.Controls.Basic

// Search field: magnifier icon & clear button. Esc clears the text, then leaves the field (exitField signal),
// Down leaves it too (focus the results). Esc is always taken: never closes the page hosting it.
TextField {
    id: field
    signal searchChanged(string text)  // typed or cleared
    signal exitField()

    function clearSearch() {
        clear()
        searchChanged("")
    }

    implicitHeight: Math.round(theme.em * 2.3)
    placeholderTextColor: theme.dimText
    color: theme.text
    selectionColor: theme.accent
    selectedTextColor: "white"
    selectByMouse: true
    leftPadding: theme.iconFont !== "" ? theme.em * 2.1 : theme.em * 0.7
    rightPadding: clearButton.visible ? clearButton.width + theme.em * 0.4 : theme.em * 0.7
    verticalAlignment: TextInput.AlignVCenter
    Accessible.name: placeholderText

    background: Rectangle {
        radius: theme.em * 0.6
        color: theme.base
        border.width: field.activeFocus ? 1.5 : 1
        border.color: field.activeFocus ? theme.accent : field.hovered ? Qt.lighter(theme.border, 1.2) : theme.border
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
    Icon {
        glyph: ""  // search
        x: theme.em * 0.7
        anchors.verticalCenter: parent.verticalCenter
        color: field.activeFocus ? theme.accent : theme.dimText
        size: theme.em * 0.95
    }
    TpButton {
        id: clearButton
        visible: field.text !== ""
        flat: true
        glyph: ""  // cancel
        text: theme.iconFont === "" ? "✕" : ""
        tip: i18n.tr("Clear")
        implicitHeight: Math.round(theme.em * 1.8)
        anchors.right: parent.right
        anchors.rightMargin: theme.em * 0.25
        anchors.verticalCenter: parent.verticalCenter
        onClicked: { field.clearSearch(); field.forceActiveFocus() }
    }

    onTextEdited: searchChanged(text)
    // Generic handler: pages may handle Down themselves (specific key handlers run first)
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
            event.accepted = true
            if (text !== "")
                clearSearch()
            else
                exitField()
        } else if (event.key === Qt.Key_Down) {
            event.accepted = true
            exitField()
        }
    }
}
