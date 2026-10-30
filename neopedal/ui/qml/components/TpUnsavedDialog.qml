import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Question asked before closing an editor with unsaved changes: Cancel (keep editing), Discard, then Apply, as the
// Save / Discard / Cancel question of the app pages. Esc or a click outside cancel. Opened, Apply has the focus
// (Enter applies); applyEnabled false (invalid value): Discard or Cancel only, Cancel focused.
// Answer by signal once closed (the handler may open the editor again):
//   TpUnsavedDialog { id: unsaved; text: ...; onApplyChosen: ...; onDiscardChosen: ...; onCancelled: ... }
TpPopup {
    id: dialog
    property string title: i18n.tr("Unsaved changes")
    property string text: ""
    property string applyText: i18n.tr("Apply")
    property string discardText: i18n.tr("Discard")
    property string cancelText: i18n.tr("Cancel")
    property bool applyEnabled: true
    property string answer: ""  // "apply", "discard", "" (cancelled) once closed
    signal applyChosen()
    signal discardChosen()
    signal cancelled()

    function apply() {
        if (!applyEnabled)
            return
        answer = "apply"
        close()
    }
    function discard() {
        answer = "discard"
        close()
    }
    function focusDefault() {
        if (opened)
            (applyButton.enabled ? applyButton : cancelButton).forceActiveFocus(Qt.TabFocusReason)
    }

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(parent ? parent.width - theme.em * 2 : theme.em * 30, theme.em * 30)
    modal: true
    focus: true
    onAboutToShow: answer = ""
    onOpened: Qt.callLater(focusDefault)
    onClosed: {
        var chosen = answer
        answer = ""
        if (chosen === "apply")
            applyChosen()
        else if (chosen === "discard")
            discardChosen()
        else
            cancelled()
    }

    contentItem: ColumnLayout {
        spacing: theme.space5
        Text {
            Layout.fillWidth: true
            text: dialog.title
            textFormat: Text.PlainText
            visible: text !== ""
            color: theme.text
            wrapMode: Text.WordWrap
            font.pointSize: theme.fontHeading
            font.weight: Font.DemiBold
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: dialog.text
            textFormat: Text.PlainText
            color: theme.dimText
            wrapMode: Text.WordWrap
            lineHeight: 1.1
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: theme.space1
            spacing: theme.space3
            Item { Layout.fillWidth: true }
            TpButton {
                id: cancelButton
                objectName: "unsavedCancel"
                text: dialog.cancelText
                onClicked: dialog.close()
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
            }
            TpButton {
                id: discardButton
                objectName: "unsavedDiscard"
                text: dialog.discardText
                onClicked: dialog.discard()
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
            }
            TpButton {
                id: applyButton
                objectName: "unsavedApply"
                accent: true
                text: dialog.applyText
                enabled: dialog.applyEnabled
                onClicked: dialog.apply()
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
            }
        }
    }
}
