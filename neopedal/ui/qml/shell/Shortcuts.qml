import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Keyboard shortcuts sheet (Ctrl+/ or F1): main window shortcuts, menu entries, navigation bar entries, keys of
// pages and global hotkeys bound on the Hotkeys page, in groups; type to filter. Esc clears, then closes.
TpPage {
    id: page
    color: theme.surfaceFlyout  // popup window: native drop shadow of Windows popups around it
    border.width: 1
    border.color: theme.strokeSubtle

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.space3

        TpCardHeader {
            level: "popup"
            glyph: ""  // keyboard
            title: i18n.tr("Keyboard Shortcuts")
            closable: true
            closeTip: i18n.tr("Close") + " (Esc)"
            onClosed: backend.close()
        }

        TpSearchField {
            id: search
            Layout.fillWidth: true
            focus: true
            placeholderText: i18n.tr("Find a shortcut")
            onSearchChanged: function(text) { backend.setSearch(text) }
            onExitField: backend.close()  // Esc with nothing typed
            Keys.onDownPressed: list.flick(0, -theme.em * 40)
            Keys.onUpPressed: list.flick(0, theme.em * 40)
            Component.onCompleted: forceActiveFocus()
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.rows
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            section.property: "group"
            section.criteria: ViewSection.FullString
            section.delegate: Item {
                required property string section
                width: ListView.view.width
                implicitHeight: label.implicitHeight + theme.space4
                TpSectionLabel {
                    id: label
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: theme.space1
                    text: parent.section
                }
            }
            delegate: RowLayout {
                required property var modelData
                width: ListView.view.width
                height: theme.rowCompact
                spacing: theme.space4
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData.keys + ": " + modelData.text
                TpText {
                    Layout.fillWidth: true
                    text: modelData.text
                    textFormat: Text.PlainText
                    color: theme.text
                    elide: Text.ElideRight
                }
                Rectangle {  // key cap
                    implicitWidth: keys.implicitWidth + theme.space4 * 2
                    implicitHeight: keys.implicitHeight + theme.space1 * 2
                    radius: theme.radiusSm
                    color: "transparent"
                    border.width: 1
                    border.color: theme.strokeSubtle
                    TpText {
                        id: keys
                        anchors.centerIn: parent
                        role: "caption"
                        color: theme.text
                        font.family: theme.monoFont
                        text: modelData.keys
                    }
                }
            }
            TpStateView {
                anchors.centerIn: parent
                empty: list.count === 0
                compact: true
                glyph: ""  // search
                title: i18n.tr("No shortcut found")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpText {
                Layout.fillWidth: true
                role: "caption"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                text: backend.hotkeysEnabled ? i18n.tr("Global hotkeys work while the game has focus.")
                                             : i18n.tr("Global hotkeys are off: turn them on in the Hotkeys page.")
            }
            TpButton {
                size: "sm"
                text: i18n.tr("Edit Hotkeys…")
                onClicked: backend.openHotkeys()
            }
        }
    }
}
