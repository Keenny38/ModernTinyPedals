import QtQuick
import QtQuick.Layouts

// Confirmation before an action that cannot be undone: message, danger (red) accept button
//   TpConfirmDialog { id: confirm; title: i18n.tr("Remove...?"); text: ...; acceptText: i18n.tr("Remove"); onAccepted: ... }
TpDialog {
    id: dialog
    property string text: ""
    danger: true

    Text {
        Layout.fillWidth: true
        visible: text !== ""
        text: dialog.text
        color: theme.dimText
        wrapMode: Text.WordWrap
        lineHeight: 1.1
    }
}
