import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Keys sheet of the Broadcast Director (? key, keyboard button): page keys, then director hotkeys of the
// keyboard shortcut settings (they work with the page hidden too, global hotkeys on). Scrolls when taller than
// the window.
TpPopup {
    id: popup
    objectName: "keysSheet"
    width: Math.min(theme.em * 30, (Overlay.overlay ? Overlay.overlay.width : theme.em * 32) - theme.em * 2)
    readonly property real maxContentHeight: Math.max(theme.em * 12, (Overlay.overlay ? Overlay.overlay.height : theme.em * 40) - theme.em * 8)

    // Key cap(s) & what the key does
    component KeyRow: RowLayout {
        id: keyRow
        property string keys: ""
        property string label: ""
        property bool unset: false
        Layout.fillWidth: true
        spacing: theme.space3
        Rectangle {
            Layout.preferredWidth: Math.max(keyText.implicitWidth + theme.space4, theme.em * 6)  // labels aligned
            Layout.preferredHeight: theme.controlHeightSm
            Layout.alignment: Qt.AlignTop
            radius: theme.radiusSm
            color: keyRow.unset ? "transparent" : theme.raised
            border.width: 1
            border.color: theme.border
            Text {
                id: keyText
                anchors.centerIn: parent
                text: keyRow.unset ? i18n.tr("Not set") : keyRow.keys
                textFormat: Text.PlainText
                color: keyRow.unset ? theme.dimText : theme.text
                font.pointSize: theme.fontSmall
                font.weight: keyRow.unset ? Font.Normal : Font.DemiBold
            }
        }
        Text {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            text: keyRow.label
            textFormat: Text.PlainText
            color: theme.text
            wrapMode: Text.WordWrap
        }
    }

    contentItem: Flickable {
        implicitHeight: Math.min(sheetColumn.implicitHeight, popup.maxContentHeight)
        contentHeight: sheetColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: sheetColumn
            width: parent.width
            spacing: theme.space3

            TpCardHeader { title: i18n.tr("Director keys"); level: "popup" }
            TpSectionLabel { Layout.fillWidth: true; text: i18n.tr("Page keys") }
            KeyRow { keys: "← →"; label: i18n.tr("Previous / next car on air") }
            KeyRow { keys: i18n.tr("Enter"); label: i18n.tr("Take the best suggestion (assisted & automatic modes)") }
            KeyRow { keys: "1 – 6"; label: i18n.tr("Take the suggestion showing that number") }
            KeyRow { keys: i18n.tr("Space"); label: i18n.tr("Play / pause the replay") }
            KeyRow { keys: "F5"; label: i18n.tr("Ask Game Again") }
            KeyRow { keys: "?"; label: i18n.tr("Show or hide this sheet") }
            KeyRow { keys: i18n.tr("Esc"); label: i18n.tr("Close the open popup (never the page)") }
            Text {
                Layout.fillWidth: true
                text: i18n.tr("A focused button, list or field keeps its own keys: click an empty place of the page first.")
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.WordWrap
            }

            TpSectionLabel { Layout.fillWidth: true; Layout.topMargin: theme.space2; text: i18n.tr("Director hotkeys") }
            Text {
                Layout.fillWidth: true
                text: backend.globalHotkeys
                      ? i18n.tr("Work with this page hidden too. Set them on the Hotkeys page.")
                      : i18n.tr("Global hotkeys are off: turn them on in the settings to use these keys.")
                textFormat: Text.PlainText
                color: backend.globalHotkeys ? theme.dimText : theme.warning
                font.pointSize: theme.fontSmall
                wrapMode: Text.WordWrap
            }
            Repeater {
                model: backend.hotkeyRows
                delegate: KeyRow {
                    required property var modelData
                    keys: modelData.key
                    unset: modelData.key === ""
                    label: modelData.label
                }
            }
        }
    }
}
