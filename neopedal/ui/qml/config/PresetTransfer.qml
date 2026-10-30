import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Transfer: settings of the loaded preset (overlays, modules, units...) copied into another preset, only the
// option types chosen (positions, colors, fonts...). Loaded & locked presets are not destinations. Overwrites the
// other preset's options: asked first. Settings & option types are chips (a check mark on the chosen ones).
TpPopup {
    id: popup
    readonly property var transfer: backend.transfer
    readonly property bool sideBySide: width >= theme.em * 36  // content-tuned: two lists of 16 em side by side

    parent: Overlay.overlay
    modal: true
    width: Math.min((parent ? parent.width : theme.em * 44) - theme.em * 4, theme.em * 48)
    height: Math.min((parent ? parent.height : theme.em * 36) - theme.em * 4, theme.em * 34)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    onAboutToShow: popup.transfer.start()
    onOpened: destination.forceActiveFocus()

    // Chip list with its title, All & None
    component ChoiceList: ColumnLayout {
        id: choiceList
        property string title: ""
        property var model: null
        property int checkedCount: 0
        property int totalCount: 0
        signal toggled(string key)
        signal allChosen(bool checked)
        spacing: theme.space2
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space1
            TpSectionLabel {
                Layout.fillWidth: true
                text: choiceList.title + "  (" + choiceList.checkedCount + "/" + choiceList.totalCount + ")"
            }
            TpButton { flat: true; size: "xs"; text: i18n.tr("All"); onClicked: choiceList.allChosen(true) }
            TpButton { flat: true; size: "xs"; text: i18n.tr("None"); onClicked: choiceList.allChosen(false) }
        }
        Flickable {
            id: chipFlick
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: chips.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Flow {
                id: chips
                width: chipFlick.width - theme.space2
                spacing: theme.space1
                Repeater {
                    model: choiceList.model
                    TpChip {
                        required property string key
                        required property string label
                        required property bool chosen
                        multi: true
                        size: "sm"
                        selected: chosen
                        glyph: chosen ? "" : ""  // check: chosen told by a mark, not only by color
                        text: (chosen && theme.iconFont === "" ? "✓ " : "") + label  // mark without icon font too
                        onClicked: choiceList.toggled(key)
                    }
                }
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: theme.space3
        TpCardHeader {
            level: "popup"
            title: i18n.tr("Preset Transfer")
            closable: true
            onClosed: popup.close()
        }
        GridLayout {
            Layout.fillWidth: true
            columns: popup.sideBySide ? 4 : 2
            columnSpacing: theme.space3
            rowSpacing: theme.space2
            Text {
                text: i18n.tr("From:")
                color: theme.dimText
            }
            Text {
                Layout.fillWidth: true
                text: popup.transfer.source
                textFormat: Text.PlainText
                color: theme.text
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                text: i18n.tr("To:")
                color: theme.dimText
            }
            TpCombo {
                id: destination
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 10
                tip: i18n.tr("Destination preset")
                model: popup.transfer.destinations
                enabled: popup.transfer.destinations.length > 0
                currentIndex: popup.transfer.destinations.indexOf(popup.transfer.destination)
                onActivated: function(index) { popup.transfer.setDestination(popup.transfer.destinations[index]) }
            }
        }
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: popup.sideBySide ? 2 : 1
            columnSpacing: theme.space4
            rowSpacing: theme.space3
            ChoiceList {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1  // both lists as wide (French titles of option types)
                title: i18n.tr("Select Setting")
                model: popup.transfer.settings
                checkedCount: popup.transfer.settingCount
                totalCount: popup.transfer.settingTotal
                onToggled: function(key) { popup.transfer.toggleSetting(key) }
                onAllChosen: function(checked) { popup.transfer.setAllSettings(checked) }
            }
            ChoiceList {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                title: i18n.tr("Select Option Type")
                model: popup.transfer.optionTypes
                checkedCount: popup.transfer.typeCount
                totalCount: popup.transfer.typeTotal
                onToggled: function(key) { popup.transfer.toggleType(key) }
                onAllChosen: function(checked) { popup.transfer.setAllTypes(checked) }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: popup.transfer.error !== ""
            text: "⚠ " + popup.transfer.error
            textFormat: Text.PlainText
            color: theme.loss
            wrapMode: Text.WordWrap
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space2
            Text {
                Layout.fillWidth: true
                text: popup.transfer.destinations.length === 0 ? i18n.tr("No other preset to transfer to (loaded & locked presets are left out).")
                    : popup.transfer.settingCount === 0 ? i18n.tr("Choose settings to transfer.")
                    : popup.transfer.typeCount === 0 ? i18n.tr("Choose option types to transfer.") : ""
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.WordWrap
            }
            TpButton {
                text: i18n.tr("Cancel")
                onClicked: popup.close()
            }
            TpButton {
                accent: true
                glyph: ""  // switch
                text: i18n.tr("Transfer")
                enabled: popup.transfer.destination !== "" && popup.transfer.settingCount > 0 && popup.transfer.typeCount > 0
                onClicked: confirm.open()
            }
        }
    }

    // Options of another preset overwritten: cannot be undone, asked first
    TpConfirmDialog {
        id: confirm
        danger: true
        title: i18n.tr("Preset Transfer")
        text: popup.transfer.confirmText
        acceptText: i18n.tr("Transfer")
        onAccepted: if (popup.transfer.transfer()) popup.close()
        onClosed: destination.forceActiveFocus()
    }
}
