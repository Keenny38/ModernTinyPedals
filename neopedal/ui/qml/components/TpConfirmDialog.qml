import QtQuick
import QtQuick.Layouts

// Confirmation before an action: message, accept button (danger: red, for what cannot be undone)
//   TpConfirmDialog { id: confirm; danger: true; title: i18n.tr("Remove...?"); text: ...; acceptText: i18n.tr("Remove"); onAccepted: ... }
TpDialog {
    id: dialog
    property string text: ""
    danger: false  // set true for what cannot be undone (same default as dialogs.confirm)

    Text {
        Layout.fillWidth: true
        visible: text !== ""
        text: dialog.text
        textFormat: Text.PlainText
        color: theme.dimText
        wrapMode: Text.WordWrap
        lineHeight: 1.1
    }
}
