import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Unsaved changes bar at the bottom of an editor page: count of changes (or the first invalid value, with Show),
// Undo & Redo, Discard, Apply (Ctrl+S on the pages). Shown only while something is pending; after Discard it
// stays a few seconds with Undo when the editor can undo. Hidden bar: out of the Tab order (not only folded),
// its buttons never take focus unseen. Actions as signals, the page calls its backend:
//   TpPendingBar { pendingCount: backend.pendingCount; canUndo: backend.canUndo; onApplyRequested: backend.apply() }
// pending: set instead of pendingCount by editors that only know whether something changed.
Rectangle {
    id: bar
    property int pendingCount: 0
    property bool pending: pendingCount > 0
    property int errorCount: 0
    property string firstError: ""  // first invalid value: name & reason
    property string detail: ""  // more about the changes ("Overlays: 3"), after the count
    property bool historyButtons: true  // Undo & Redo while pending (editors with them in their toolbar: false)
    property bool canUndo: false
    property bool canRedo: false
    property bool showErrorButton: true  // Show: first invalid value shown (showErrorRequested)
    property string applyText: i18n.tr("Apply")
    property string applyTip: i18n.tr("Save & apply (Ctrl+S)")
    property bool applyEnabled: errorCount === 0
    readonly property bool discarded: undoGrace.running && !pending
    readonly property bool shown: pending || discarded
    signal undoRequested()
    signal redoRequested()
    signal discardRequested()
    signal applyRequested()
    signal showErrorRequested()

    visible: shown || heightAnimation.running
    enabled: shown
    Layout.fillWidth: true
    implicitHeight: shown ? barRow.implicitHeight + theme.space6 : 0
    clip: true
    color: theme.surfaceCard  // above the page
    Behavior on implicitHeight {
        NumberAnimation { id: heightAnimation; duration: theme.motionBase; easing.type: Easing.OutCubic }
    }
    onPendingChanged: if (pending) undoGrace.stop()  // edited or undone meanwhile: the usual bar
    Rectangle { width: parent.width; height: 1; color: theme.border }
    Timer { id: undoGrace; interval: 6000 }  // restarted by Discard

    RowLayout {
        id: barRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: theme.space3
        anchors.leftMargin: theme.padPage
        anchors.rightMargin: theme.padPage
        spacing: theme.space3
        Icon {
            glyph: bar.discarded ? "" : bar.errorCount > 0 ? "" : ""  // check, warning, edit
            fallback: bar.discarded ? "✓" : bar.errorCount > 0 ? "!" : ""
            color: bar.discarded ? theme.gain : bar.errorCount > 0 ? theme.loss : theme.accent
        }
        Text {
            Layout.fillWidth: true
            text: bar.discarded ? i18n.tr("Changes discarded")
                : bar.errorCount > 0
                  ? i18n.trm("Fix " + bar.errorCount + " invalid value(s) to save")
                    + (bar.firstError !== "" ? "  ·  " + bar.firstError : "")
                : (bar.pendingCount > 0 ? i18n.trm("Unsaved changes: " + bar.pendingCount) : i18n.tr("Unsaved changes"))
                  + (bar.detail !== "" ? "  ·  " + bar.detail : "")
            textFormat: Text.PlainText
            color: bar.errorCount > 0 && !bar.discarded ? theme.loss : theme.text
            elide: Text.ElideRight
            Accessible.role: Accessible.AlertMessage
            Accessible.name: text
        }
        TpButton {  // invalid value: show it (keyboard reachable)
            objectName: "pendingShowError"
            visible: bar.errorCount > 0 && bar.showErrorButton && !bar.discarded
            flat: true
            text: i18n.tr("Show")
            tip: bar.firstError
            onClicked: bar.showErrorRequested()
        }
        TpButton {
            objectName: "pendingUndo"
            visible: bar.discarded ? bar.canUndo : bar.historyButtons
            flat: true
            glyph: theme.glyphs.undo
            text: bar.discarded ? i18n.tr("Undo") : ""  // after Discard: told in words
            fallback: i18n.tr("Undo")
            tip: i18n.tr("Undo (Ctrl+Z)")
            enabled: bar.canUndo
            onClicked: bar.undoRequested()
        }
        TpButton {
            objectName: "pendingRedo"
            visible: !bar.discarded && bar.historyButtons
            flat: true
            glyph: ""  // redo
            fallback: i18n.tr("Redo")
            tip: i18n.tr("Redo (Ctrl+Y)")
            enabled: bar.canRedo
            onClicked: bar.redoRequested()
        }
        TpButton {
            objectName: "pendingDiscard"
            visible: !bar.discarded
            text: i18n.tr("Discard")
            tip: i18n.tr("Drop every unsaved change")
            onClicked: {
                bar.discardRequested()
                if (bar.canUndo && !bar.pending)
                    undoGrace.restart()  // bar kept with Undo for a moment
            }
        }
        TpButton {
            objectName: "pendingApply"
            visible: !bar.discarded
            accent: true
            text: bar.applyText
            tip: bar.applyTip
            enabled: bar.applyEnabled
            onClicked: bar.applyRequested()
        }
    }
}
