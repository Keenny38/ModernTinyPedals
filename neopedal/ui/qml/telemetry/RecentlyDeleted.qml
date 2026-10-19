import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Recently deleted laps (trash folder of telemetry laps, kept a number of days then removed for good), newest
// deletion first. Restore: lap back in its track folder (note, kept state, check & reference too when deleted while
// the viewer was open).
TpPopup {
    id: popup

    parent: Overlay.overlay  // centered on page, wherever it is declared
    modal: true
    width: Math.min((parent ? parent.width : theme.em * 40) - theme.em * 4, theme.em * 34)
    height: Math.min((parent ? parent.height : theme.em * 34) - theme.em * 4, theme.em * 30)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    onAboutToShow: backend.openTrash()
    onOpened: list.forceActiveFocus()

    contentItem: ColumnLayout {
        spacing: theme.space3
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Recently Deleted Laps")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontHeading
                elide: Text.ElideRight
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            TpButton {
                glyph: ""  // cancel
                fallback: "✕"
                flat: true
                tip: i18n.tr("Close")
                size: "sm"
                onClicked: popup.close()
            }
        }
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Deleted laps are kept %1 days, then removed for good.").arg(backend.trashDays)
            color: theme.dimText
            font.pointSize: theme.fontSmall
            wrapMode: Text.WordWrap
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ListView {
                id: list
                objectName: "trashList"
                anchors.fill: parent
                clip: true
                model: backend.trashRows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // Keys: arrows move, Enter / Space restore the lap under keyboard
                activeFocusOnTab: true
                keyNavigationEnabled: true
                Keys.onReturnPressed: if (currentItem) backend.restoreTrashed(currentItem.modelData.key)
                Keys.onEnterPressed: if (currentItem) backend.restoreTrashed(currentItem.modelData.key)
                Keys.onSpacePressed: if (currentItem) backend.restoreTrashed(currentItem.modelData.key)
                delegate: TpListRow {
                    id: row
                    required property var modelData
                    required property int index
                    width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.rowTall)
                    hovered: rowArea.containsMouse
                    Accessible.role: Accessible.ListItem
                    Accessible.name: row.modelData.title + " " + row.modelData.time
                    FocusRing { visible: row.ListView.isCurrentItem && list.activeFocus }
                    MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.space4
                        anchors.rightMargin: theme.space2
                        spacing: theme.space4
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            RowLayout {
                                spacing: theme.space3
                                Text { text: row.modelData.title; color: theme.text; font.weight: Font.DemiBold }
                                Text {
                                    text: row.modelData.time
                                    color: theme.text
                                    font.features: { "tnum": 1 }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: [row.modelData.track, row.modelData.recorded].filter(Boolean).join(" · ")
                                color: theme.dimText
                                font.pointSize: theme.fontSmall
                                elide: Text.ElideRight
                            }
                        }
                        Text {
                            text: i18n.tr("Deleted %1").arg(row.modelData.deleted)
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            font.features: { "tnum": 1 }
                        }
                        TpButton {
                            glyph: ""  // undo
                            fallback: "↶"
                            text: i18n.tr("Restore")
                            flat: true
                            size: "sm"
                            onClicked: backend.restoreTrashed(row.modelData.key)
                        }
                    }
                }
            }
            TpStateView {
                anchors.centerIn: parent
                loading: backend.trashLoading && list.count === 0
                empty: !backend.trashLoading && list.count === 0
                loadingText: i18n.tr("Reading deleted laps...")
                glyph: "\uE74D"  // delete
                title: i18n.tr("No deleted lap")
            }
        }
    }
}
