import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Dialogs & toasts asked by the page's Python backend (ui/quick/dialogs.py: ask_text, ask_number, confirm, alert,
// toasts of ui/toast.show_toast): text & number input, confirmation & alert in a TpDialog over the page, toasts in a
// TpToast at its bottom. One per page, last child of the page root item (fills it, takes no click; not inside a
// layout). Without it, the backend's requests open widget dialogs & toasts as before. Multiline input: Ctrl+Enter
// accepts. Number input: Up / Down step (Shift: 10 steps), decimal comma accepted.
//   TpDialogHost {}
Item {
    id: host
    readonly property var request: dialogs.current
    readonly property int requestId: request && request.id ? request.id : 0
    readonly property string kind: requestId > 0 ? request.kind : ""
    readonly property bool textInput: kind === "text"
    readonly property bool numberInput: kind === "number"
    readonly property bool multiline: textInput && request.multiline === true
    property alias toast: pageToast

    anchors.fill: parent
    z: 1000
    Component.onCompleted: dialogs.attach()
    Component.onDestruction: dialogs.detach()

    function fieldText() { return numberInput ? number.text : multiline ? area.text : field.text }
    // Answer taken: the page moves to its next request (show() below closes the dialog or shows the next one)
    function accept() {
        if (requestId > 0 && !dialogs.answer(requestId, true, fieldText()) && (textInput || numberInput))
            (numberInput ? number : multiline ? area : field).forceActiveFocus()  // refused: typed text kept to correct
    }
    // Read from dialogs.current itself: bindings depending on requestId may not be updated yet in its handler
    function show() {
        var shown = dialogs.current
        if (!shown || !(shown.id > 0)) {
            if (dialog.opened || dialog.visible)
                dialog.done()  // answered, or cancelled by the page (hidden, closed)
            return
        }
        var text = shown.kind === "text"
        var lines = text && shown.multiline === true
        field.text = text && !lines ? String(shown.value || "") : ""
        area.text = lines ? String(shown.value || "") : ""
        if (shown.kind === "number") {  // range & decimals before the value: text formatted with them
            number.decimals = shown.decimals || 0
            number.minimum = shown.minimum
            number.maximum = shown.maximum
            number.step = shown.step || 1
            number.suffix = shown.suffix || ""
            number.value = Number(shown.value) || 0
            number.text = number.format(number.value)
        }
        dialog.open()
    }
    onRequestIdChanged: show()

    TpDialog {
        id: dialog
        objectName: "bridgeDialog"
        title: host.request.title || ""
        acceptText: host.request.acceptText || "OK"
        cancelText: host.request.cancelText || i18n.tr("Cancel")
        showCancel: host.kind !== "alert"
        danger: host.request.danger === true
        closeOnAccept: false  // closed once the page took the answer (refused text: kept open)
        dismissOnOutside: !host.textInput && !host.numberInput
        width: Math.min(parent ? parent.width - theme.em * 2 : theme.em * 28, host.multiline ? theme.em * 34 : theme.em * 28)
        onAccepted: host.accept()
        onCancelled: if (host.requestId > 0) dialogs.answer(host.requestId, false, "")
        onOpened: {
            if (host.numberInput) {
                number.forceActiveFocus()  // NumberField selects all once focused
            } else if (host.textInput) {
                var input = host.multiline ? area : field
                input.forceActiveFocus()
                if (!host.multiline)
                    field.selectAll()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space4
            visible: messageText.text !== ""
            Icon {  // alert level: shape with the color
                Layout.alignment: Qt.AlignTop
                visible: host.kind === "alert"
                glyph: host.request.level === "info" || host.request.level === "success" ? "" : ""  // info, warning
                fallback: host.request.level === "info" || host.request.level === "success" ? "i" : "!"
                color: host.request.level === "error" ? theme.loss : host.request.level === "warning" ? theme.warning : theme.accent
            }
            Text {
                id: messageText
                objectName: "bridgeMessage"
                Layout.fillWidth: true
                text: host.request.text || ""
                // escaped by Python (safe_markup): <b>, <i>, <br> only
                textFormat: host.request.rich === true ? Text.StyledText : Text.PlainText
                color: host.textInput || host.numberInput ? theme.text : theme.dimText
                wrapMode: Text.Wrap
                lineHeight: 1.1
            }
        }
        NumberField {
            id: number
            objectName: "bridgeNumber"
            Layout.preferredWidth: theme.em * 9
            visible: host.numberInput
            showRange: true  // out of range value told by the tooltip, put back in range
            onEdited: function(value) { number.value = value }  // stepped or typed value shown as it is
            onAccepted: dialog.accept()
            // NumberField's own Esc puts the value back and keeps the page open: here it cancels the dialog
            Keys.onShortcutOverride: function(event) {
                if (event.key === Qt.Key_Escape) {
                    event.accepted = true
                    dialog.close()
                }
            }
        }
        TpTextField {
            id: field
            objectName: "bridgeField"
            Layout.fillWidth: true
            visible: host.textInput && !host.multiline
            placeholderText: host.request.placeholder || ""
            onAccepted: dialog.accept()
            onEscaped: dialog.close()
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: theme.em * 9
            visible: host.multiline
            TextArea {
                id: area
                objectName: "bridgeArea"
                wrapMode: TextEdit.Wrap
                color: theme.text
                placeholderText: host.request.placeholder || ""
                placeholderTextColor: theme.dimText
                selectionColor: theme.accentFill
                selectedTextColor: theme.accentInk
                selectByMouse: true
                textFormat: TextEdit.PlainText
                background: Rectangle {
                    radius: theme.radiusSm
                    color: theme.surfaceSunken
                    border.width: area.activeFocus ? 1.5 : 1
                    border.color: area.activeFocus ? theme.accent : theme.border
                }
                // Ctrl+Enter accepts (Enter is a new line), Esc cancels: taken, never closes the page
                Keys.onPressed: function(event) {
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                        event.accepted = true
                        dialog.accept()
                    } else if (event.key === Qt.Key_Escape) {
                        event.accepted = true
                        dialog.close()
                    }
                }
            }
        }
    }

    TpToast {
        id: pageToast
        objectName: "bridgeToast"
        textFormat: Text.StyledText  // escaped by Python (safe_markup)
        onAction: dialogs.toastAction()
        Connections {
            target: dialogs
            function onToastRequested(text, level, duration, actionText) {
                pageToast.text = text
                pageToast.level = level
                pageToast.duration = duration
                pageToast.actionText = actionText
                pageToast.show()
            }
        }
    }
}
