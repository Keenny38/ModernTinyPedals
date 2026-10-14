import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Modal box over the page: title, content, Cancel & accept buttons. Fades & scales in.
// Esc or a click outside cancels (cancelled signal), Enter in a field of the content accepts (call accept()).
Popup {
    id: dialog
    property string title: ""
    property string acceptText: "OK"
    property string cancelText: i18n.tr("Cancel")
    property bool acceptEnabled: true
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
    padding: theme.em * 1.1
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    property bool acceptedNow: false
    onAboutToShow: acceptedNow = false
    onClosed: if (!acceptedNow) cancelled()

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast }
        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: theme.motionBase; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast }
    }
    Overlay.modal: Rectangle {
        color: Qt.rgba(0, 0, 0, theme.dark ? 0.45 : 0.25)
        Behavior on opacity { NumberAnimation { duration: theme.motionFast } }
    }
    background: Rectangle {
        radius: theme.radiusXl
        color: theme.dark ? Qt.lighter(theme.base, 1.12) : theme.base
        border.width: 1
        border.color: theme.border
    }

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
