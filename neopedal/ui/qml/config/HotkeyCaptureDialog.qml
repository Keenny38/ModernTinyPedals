import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Key capture of Hotkeys page: keys, mouse & game controller buttons pressed are shown and taken (read by the
// backend while the dialog shows; every key goes to the capture, Esc cancels), preset to load for preset hotkeys,
// actions already using the captured key. Clear empties the binding, Save (or "Assign Anyway") keeps it.
TpDialog {
    id: dialog
    readonly property string conflict: backend.captureConflict

    title: backend.captureTitle
    acceptText: conflict !== "" ? i18n.tr("Assign Anyway") : i18n.tr("Save")
    dismissOnOutside: false  // captured key kept: only Esc or the buttons close it
    width: Math.min(parent ? parent.width - theme.space6 * 2 : theme.em * 30, theme.em * 30)
    onAccepted: backend.saveCapture()
    onCancelled: backend.cancelCapture()

    // Captured keys
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Math.round(theme.rowTall) + theme.space6
        radius: theme.radiusLg
        color: theme.surfaceSunken  // keys typed: sunken as a field
        border.width: 1
        border.color: dialog.conflict !== "" ? theme.warning : theme.accent
        Text {
            anchors.fill: parent
            anchors.margins: theme.space4
            text: backend.captureText
            textFormat: Text.PlainText
            color: backend.capturedBinding !== "" ? theme.text : theme.dimText
            font.pointSize: backend.capturedBinding !== "" ? theme.fontHeading : theme.fontLabel
            font.weight: backend.capturedBinding !== "" ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
            Accessible.role: Accessible.StaticText
            Accessible.name: text
        }
    }

    // Same key used by other actions
    RowLayout {
        Layout.fillWidth: true
        visible: dialog.conflict !== ""
        spacing: theme.space3
        Icon { glyph: ""; fallback: "!"; color: theme.warning }  // warning
        Text {
            Layout.fillWidth: true
            text: i18n.trm("Already used for: " + dialog.conflict)
            textFormat: Text.PlainText
            color: theme.text
            wrapMode: Text.WordWrap
        }
    }

    // Preset loaded by preset hotkeys
    TpCombo {
        Layout.fillWidth: true
        visible: backend.captureIsPreset
        model: backend.captureIsPreset ? backend.presetChoices : []
        currentIndex: backend.presetIndex
        tip: i18n.tr("Preset loaded by this hotkey")
        onActivated: function(index) { backend.setPresetIndex(index) }
    }

    TpButton {
        flat: true
        glyph: theme.glyphs.remove
        text: i18n.tr("Clear")
        tip: i18n.tr("No key for this action (saved with Save)")
        onClicked: backend.clearCapture()
    }
}
