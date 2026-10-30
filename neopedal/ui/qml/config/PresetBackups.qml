import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Backups of presets & style presets (automatic, or Backup Preset), newest first. Files are listed at once and
// checked in background: an unreadable backup is marked and cannot be restored. Restore: a preset backup becomes a
// new preset (name asked by the page: restoreAsPreset), a style preset backup replaces the style preset (asked
// first). Delete permanently asks first.
TpPopup {
    id: popup
    readonly property var backups: backend.backups
    signal restoreAsPreset(string name)

    parent: Overlay.overlay
    modal: true
    width: Math.min((parent ? parent.width : theme.em * 40) - theme.em * 4, theme.em * 38)
    height: Math.min((parent ? parent.height : theme.em * 34) - theme.em * 4, theme.em * 30)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    onAboutToShow: popup.backups.refresh()
    onOpened: list.forceActiveFocus()
    onClosed: popup.backups.stop()

    function restore(name) {
        var kind = popup.backups.prepareRestore(name)
        if (kind === "style") {
            confirm.key = name
            confirm.style = true
            confirm.title = i18n.tr("Restore Style Preset")
            confirm.text = popup.backups.styleRestoreText(name)
            confirm.acceptText = i18n.tr("Restore")
            confirm.open()
        } else if (kind === "preset") {
            popup.restoreAsPreset(name)
        }
    }
    function askDelete(name) {
        confirm.key = name
        confirm.style = false
        confirm.title = i18n.tr("Delete Preset")
        confirm.text = popup.backups.deleteText(name)
        confirm.acceptText = i18n.tr("Delete Permanently")
        confirm.open()
    }

    contentItem: ColumnLayout {
        spacing: theme.space3
        TpCardHeader {
            level: "popup"
            title: i18n.tr("Restore Backup")
            closable: true
            onClosed: popup.close()
            TpButton {
                glyph: theme.glyphs.refresh
                fallback: "↻"
                flat: true
                tip: i18n.tr("Refresh")
                size: "sm"
                onClicked: popup.backups.refresh()
            }
        }
        Text {
            Layout.fillWidth: true
            text: i18n.tr("A preset backup is restored as a new preset, a style preset backup replaces the style preset.")
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            wrapMode: Text.WordWrap
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ListView {
                id: list
                objectName: "backupList"
                anchors.fill: parent
                clip: true
                model: popup.backups.rows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // Keys: arrows move, Enter restores, Delete deletes permanently (asked first)
                activeFocusOnTab: true
                keyNavigationEnabled: true
                Keys.onReturnPressed: if (currentItem && currentItem.status !== "invalid") popup.restore(currentItem.key)
                Keys.onEnterPressed: if (currentItem && currentItem.status !== "invalid") popup.restore(currentItem.key)
                Keys.onDeletePressed: if (currentItem) popup.askDelete(currentItem.key)
                delegate: TpListRow {
                    id: row
                    required property int index
                    required property string key
                    required property bool style
                    required property string status
                    width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.rowTall)
                    hovered: rowArea.containsMouse
                    Accessible.role: Accessible.ListItem
                    Accessible.name: row.key + (row.status === "invalid" ? ", " + i18n.tr("Unreadable file") : "")
                    FocusRing { visible: row.ListView.isCurrentItem && list.activeFocus }
                    MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.space4
                        anchors.rightMargin: theme.space2
                        spacing: theme.space3
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: row.key
                                textFormat: Text.PlainText
                                color: theme.text
                                font.weight: Font.DemiBold
                                elide: Text.ElideMiddle
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.status === "checking" ? i18n.tr("Checking…")
                                    : row.style ? i18n.tr("Style preset") : i18n.tr("Preset")
                                textFormat: Text.PlainText
                                color: theme.dimText
                                font.pointSize: theme.fontSmall
                                elide: Text.ElideRight
                            }
                        }
                        Pill {
                            visible: row.status === "invalid"
                            glyph: ""  // warning
                            text: i18n.tr("Unreadable file")
                            tint: theme.loss
                            size: "sm"
                            tip: i18n.trm("Selected backup file is invalid and cannot be restored.")
                        }
                        TpButton {
                            glyph: theme.glyphs.restore
                            fallback: "↶"
                            text: i18n.tr("Restore")
                            flat: true
                            size: "sm"
                            enabled: row.status !== "invalid"
                            onClicked: popup.restore(row.key)
                        }
                        TpButton {
                            glyph: theme.glyphs.delete
                            fallback: "✕"
                            tip: i18n.tr("Delete Permanently")
                            flat: true
                            size: "sm"
                            onClicked: popup.askDelete(row.key)
                        }
                    }
                }
            }
            TpStateView {
                anchors.centerIn: parent
                empty: list.count === 0
                glyph: ""  // history
                title: i18n.tr("No backup yet")
                text: i18n.tr("Backups are made automatically when a preset is saved, or with Backup Preset.")
            }
        }
    }

    // Style preset replaced, or backup deleted for good: cannot be undone, asked first
    TpConfirmDialog {
        id: confirm
        property string key: ""
        property bool style: false
        danger: !style  // backup deleted for good
        onAccepted: style ? popup.backups.restoreStyle(key) : popup.backups.remove(key)
        onClosed: list.forceActiveFocus()
    }
}
