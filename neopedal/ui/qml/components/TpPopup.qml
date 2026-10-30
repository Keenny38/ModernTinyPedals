import QtQuick
import QtQuick.Controls.Basic

// Popup surface in app look: flyout surface with a soft shadow (TpShadow), fades & scales in, page dimmed (scrim)
// when modal.
// Base of TpDialog and of the pages' own popups (settings, pickers, help). dismissOnOutside false: only Esc
// (or the popup's own buttons) closes it, for popups holding typed input.
//   TpPopup { parent: Overlay.overlay; anchors.centerIn: parent; modal: true; width: ...; Column { ... } }
Popup {
    id: popup
    property bool dismissOnOutside: true

    padding: theme.padPopup
    closePolicy: dismissOnOutside ? Popup.CloseOnEscape | Popup.CloseOnPressOutside : Popup.CloseOnEscape

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast }
        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: theme.motionBase; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast }
    }
    Overlay.modal: Rectangle {
        color: theme.scrim
        Behavior on opacity { NumberAnimation { duration: theme.motionFast } }
    }
    background: Rectangle {
        radius: theme.radiusLg
        color: theme.surfaceFlyout
        border.width: 1
        border.color: theme.strokeSubtle
        TpShadow {}
    }
}
