import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Modal box over the page: title, content, Cancel & accept buttons (always in that order). Fades & scales in.
// Esc cancels (cancelled signal), a click outside too unless dismissOnOutside is false (dialogs with fields:
// typed text is not lost by a click beside), Enter in a field of the content accepts (call accept()).
// showCancel false: one button (acceptText, "Close") for dialogs that only show something.
TpPopup {
    id: dialog
    property string title: ""
    property string acceptText: "OK"
    property string cancelText: i18n.tr("Cancel")
    property bool acceptEnabled: true
    property bool showCancel: true
    property bool danger: false  // accept button in red (action cannot be undone)
    property bool closeOnAccept: true  // false: page closes it with done() once the action succeeded
    default property alias content: body.data
    signal accepted()
    signal cancelled()

    function accept() {
        if (!acceptEnabled)
            return
        if (closeOnAccept)
            done()
        accepted()
    }
    function done() {
        acceptedNow = true
        close()
    }

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(parent ? parent.width - theme.em * 2 : theme.em * 28, theme.em * 28)
    modal: true
    focus: true
    property bool acceptedNow: false
    onAboutToShow: acceptedNow = false
    onClosed: if (!acceptedNow) cancelled()

    contentItem: ColumnLayout {
        spacing: theme.em * 0.8
        Text {
            Layout.fillWidth: true
            text: dialog.title
            visible: text !== ""
            color: theme.text
            wrapMode: Text.WordWrap
            font.pointSize: theme.fontHeading
            font.weight: Font.DemiBold
        }
        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: theme.em * 0.5
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: theme.em * 0.2
            spacing: theme.em * 0.5
            Item { Layout.fillWidth: true }
            TpButton {
                visible: dialog.showCancel
                text: dialog.cancelText
                onClicked: dialog.close()
            }
            TpButton {
                accent: true
                danger: dialog.danger
                text: dialog.acceptText
                enabled: dialog.acceptEnabled
                onClicked: dialog.accept()
            }
        }
    }
}
