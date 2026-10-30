import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Recently deleted presets (trash of the presets folder, kept a number of days then removed for good), newest
// deletion first: same panel as the recently deleted laps of the telemetry viewer. Restore: preset back with its
// primary tags & hotkeys (renamed if a preset has its name meanwhile). Delete permanently & empty ask first.
TpPopup {
    id: popup
    readonly property var trash: backend.trash

    parent: Overlay.overlay  // centered on page, wherever it is declared
    modal: true
    width: Math.min((parent ? parent.width : theme.em * 40) - theme.em * 4, theme.em * 36)
    height: Math.min((parent ? parent.height : theme.em * 34) - theme.em * 4, theme.em * 30)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    onAboutToShow: popup.trash.refresh()
    onOpened: list.forceActiveFocus()

    function askDelete(key) {
        confirm.key = key
        confirm.title = i18n.tr("Delete Preset")
        confirm.text = popup.trash.deleteText(key)
        confirm.acceptText = i18n.tr("Delete Permanently")
        confirm.open()
    }

    contentItem: ColumnLayout {
        spacing: theme.space3
        TpCardHeader {
            level: "popup"
            title: i18n.tr("Recently Deleted Presets")
            closable: true
            onClosed: popup.close()
        }
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Deleted presets are kept %1 days, then removed for good.").arg(popup.trash.keepDays)
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
                objectName: "deletedPresets"
                anchors.fill: parent
                clip: true
                model: popup.trash.rows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // Keys: arrows move, Enter / Space restore, Delete deletes permanently (asked first)
                activeFocusOnTab: true
                keyNavigationEnabled: true
                Keys.onReturnPressed: if (currentItem) popup.trash.restore(currentItem.key)
                Keys.onEnterPressed: if (currentItem) popup.trash.restore(currentItem.key)
                Keys.onSpacePressed: if (currentItem) popup.trash.restore(currentItem.key)
                Keys.onDeletePressed: if (currentItem) popup.askDelete(currentItem.key)
                delegate: TpListRow {
                    id: row
                    required property int index
                    required property string key
                    required property string name
                    required property string deleted
                    required property int daysLeft
                    width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.rowTall)
                    hovered: rowArea.containsMouse
                    Accessible.role: Accessible.ListItem
                    Accessible.name: row.name + ", " + i18n.tr("Deleted %1").arg(row.deleted)
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
                                text: row.name
                                textFormat: Text.PlainText
                                color: theme.text
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: i18n.tr("Deleted %1").arg(row.deleted) + "  ·  " + i18n.tr("%1 day(s) left").arg(row.daysLeft)
                                textFormat: Text.PlainText
                                color: theme.dimText
                                font.pointSize: theme.fontSmall
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                            }
                        }
                        TpButton {
                            glyph: theme.glyphs.restore
                            fallback: "↶"
                            text: i18n.tr("Restore")
                            flat: true
                            size: "sm"
                            onClicked: popup.trash.restore(row.key)
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
                loading: popup.trash.loading && list.count === 0
                empty: !popup.trash.loading && list.count === 0
                loadingText: i18n.tr("Reading deleted presets…")
                glyph: theme.glyphs.delete
                title: i18n.tr("No deleted preset")
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space2
            Item { Layout.fillWidth: true }
            TpButton {
                flat: true
                glyph: theme.glyphs.delete
                text: i18n.tr("Empty Trash")
                enabled: list.count > 0
                onClicked: {
                    confirm.key = ""
                    confirm.title = i18n.tr("Empty Trash")
                    confirm.text = popup.trash.emptyText()
                    confirm.acceptText = i18n.tr("Empty Trash")
                    confirm.open()
                }
            }
        }
    }

    // Deleting for good cannot be undone: asked first (key "": every preset in trash)
    TpConfirmDialog {
        id: confirm
        property string key: ""
        danger: true  // deleted for good
        onAccepted: key === "" ? popup.trash.empty() : popup.trash.remove(key)
        onClosed: list.forceActiveFocus()
    }
}
