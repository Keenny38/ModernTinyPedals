import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Two presets side by side (A: loaded preset, B: preset chosen on the page): options with different values,
// filter, overlay positions left out by default. Rows chosen (click, Space, Ctrl+A) are copied B → A or A → B,
// pending until applied: unsaved changes bar (TpPendingBar, as on Settings) with Discard & Apply (only the copied
// values are written, into a fresh copy of each preset; the loaded preset is reloaded). Closing with copied values
// not applied asks first: Apply, Discard or Keep Editing (opens the panel again).
TpPopup {
    id: popup
    readonly property var compare: backend.compare
    readonly property bool roomy: width >= theme.em * 44  // content-tuned: option, both values & section on one line
    property string error: ""
    readonly property real valueWidth: roomy ? theme.em * 11 : theme.em * 7  // value columns of preset A & B
    signal dismissed()  // closed for good (not to ask about copied values): page takes focus back

    function openFor(key) {
        popup.error = ""
        popup.compare.start(key)
        popup.open()
    }

    parent: Overlay.overlay
    modal: true
    dismissOnOutside: false  // copied values kept: only Esc or Close close it
    width: Math.min((parent ? parent.width : theme.em * 50) - theme.em * 4, theme.em * 60)
    height: Math.min((parent ? parent.height : theme.em * 40) - theme.em * 4, theme.em * 42)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    onOpened: list.forceActiveFocus()
    onClosed: {
        if (popup.compare.modified) {
            unsavedDialog.open()
        } else {
            popup.compare.stop()
            popup.dismissed()
        }
    }

    contentItem: ColumnLayout {
        spacing: theme.space3
        TpCardHeader {
            level: "popup"
            title: i18n.tr("Preset Comparison")
            closable: true
            onClosed: popup.close()
        }

        // Presets compared
        GridLayout {
            Layout.fillWidth: true
            columns: popup.roomy ? 4 : 2
            columnSpacing: theme.space3
            rowSpacing: theme.space2
            Text { text: i18n.tr("Preset A"); color: theme.dimText }
            TpCombo {
                Layout.fillWidth: true
                tip: i18n.tr("Preset A")
                model: popup.compare.choices
                currentIndex: popup.compare.choices.indexOf(popup.compare.presetA)
                onActivated: function(index) { popup.compare.setPresetA(popup.compare.choices[index]) }
            }
            Text { text: i18n.tr("Preset B"); color: theme.dimText }
            TpCombo {
                Layout.fillWidth: true
                tip: i18n.tr("Preset B")
                model: popup.compare.choices
                currentIndex: popup.compare.choices.indexOf(popup.compare.presetB)
                onActivated: function(index) { popup.compare.setPresetB(popup.compare.choices[index]) }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpSearchField {
                id: filter
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                placeholderText: i18n.tr("Filter")
                onSearchChanged: function(text) { popup.compare.setFilter(text) }
                onExitField: list.forceActiveFocus()
            }
            TpSwitch {
                checkable: false
                checked: popup.compare.ignorePositions
                text: i18n.tr("Ignore overlay positions")
                onClicked: popup.compare.setIgnorePositions(!popup.compare.ignorePositions)
                Accessible.role: Accessible.CheckBox
                Accessible.name: text
                Accessible.checked: popup.compare.ignorePositions
            }
        }

        // Header & differences
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space2
            Item { Layout.preferredWidth: theme.em * 1.2 }  // check mark column
            TpHeaderCell { Layout.fillWidth: true; text: i18n.tr("Option") }
            TpHeaderCell { Layout.preferredWidth: popup.valueWidth; text: i18n.tr("Preset A") }
            TpHeaderCell { Layout.preferredWidth: popup.valueWidth; text: i18n.tr("Preset B") }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ListView {
                id: list
                objectName: "compareList"
                anchors.fill: parent
                clip: true
                model: popup.compare.rows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                activeFocusOnTab: true
                keyNavigationEnabled: true
                reuseItems: true
                // Keys: arrows move, Space chooses the row, Ctrl+A chooses every shown row
                Keys.onSpacePressed: if (currentItem) popup.compare.toggleSelected(currentItem.key)
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_A && (event.modifiers & Qt.ControlModifier)) {
                        popup.compare.selectShown(true)
                        event.accepted = true
                    } else if (filter.routeTyped(event)) {
                        event.accepted = true
                    }
                }
                delegate: TpListRow {
                    id: row
                    required property int index
                    striped: index % 2 === 1  // dense table: odd rows striped
                    required property string key
                    required property string sectionLabel
                    required property string label
                    required property string help
                    required property string valueA
                    required property string valueB
                    required property bool chosen
                    width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                    height: Math.round(popup.roomy ? theme.row : theme.rowTall)
                    hovered: rowArea.containsMouse
                    selected: row.chosen
                    Accessible.role: Accessible.CheckBox
                    Accessible.name: row.label + ", " + row.sectionLabel + ": " + row.valueA + " / " + row.valueB
                    Accessible.checked: row.chosen
                    FocusRing { visible: row.ListView.isCurrentItem && list.activeFocus }
                    MouseArea {
                        id: rowArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            list.currentIndex = row.index
                            popup.compare.toggleSelected(row.key)
                        }
                    }
                    ToolTip.visible: rowArea.containsMouse && row.help !== ""
                    ToolTip.text: row.help
                    ToolTip.delay: theme.tipDelay
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.space2
                        anchors.rightMargin: theme.space2
                        spacing: theme.space2
                        Icon {
                            Layout.preferredWidth: theme.em * 1.2
                            glyph: row.chosen ? "" : ""  // check: chosen told by a mark, not only by color
                            fallback: row.chosen ? "✓" : ""
                            color: theme.accent
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: popup.roomy ? row.label + "  ·  " + row.sectionLabel : row.label
                                textFormat: Text.PlainText
                                color: theme.text
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: !popup.roomy
                                text: row.sectionLabel
                                textFormat: Text.PlainText
                                color: theme.dimOn(row.color)
                                font.pointSize: theme.fontSmall
                                elide: Text.ElideRight
                            }
                        }
                        Text {
                            Layout.preferredWidth: popup.valueWidth
                            text: row.valueA
                            textFormat: Text.PlainText
                            color: theme.text
                            font.features: { "tnum": 1 }
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.preferredWidth: popup.valueWidth
                            text: row.valueB
                            textFormat: Text.PlainText
                            color: theme.text
                            font.features: { "tnum": 1 }
                            elide: Text.ElideRight
                        }
                    }
                }
            }
            TpStateView {
                anchors.centerIn: parent
                loading: popup.compare.loading
                empty: !popup.compare.loading && list.count === 0
                loadingText: i18n.tr("Reading presets…")
                glyph: popup.compare.samePreset ? "" : ""  // info, check
                title: popup.compare.samePreset ? i18n.tr("Select two different presets.")
                     : popup.compare.diffCount > 0 ? i18n.tr("No difference matches the filter")
                     : i18n.tr("Same options in both presets")
            }
        }
        Text {
            Layout.fillWidth: true
            visible: popup.error !== ""
            text: "⚠ " + popup.error
            textFormat: Text.PlainText
            color: theme.loss
            wrapMode: Text.WordWrap
        }

        // Selection & copy
        Flow {
            Layout.fillWidth: true
            spacing: theme.space2
            Text {
                height: Math.round(theme.controlHeight)
                verticalAlignment: Text.AlignVCenter
                text: i18n.trm("Differences: " + popup.compare.diffCount)
                    + (popup.compare.selectedCount > 0 ? "  ·  " + i18n.tr("%1 chosen").arg(popup.compare.selectedCount) : "")
                    + (popup.compare.copiedCount > 0 ? "  ·  " + i18n.tr("%1 copied, not saved").arg(popup.compare.copiedCount) : "")
                textFormat: Text.PlainText
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            TpButton {
                flat: true
                text: i18n.tr("All")
                tip: i18n.tr("Choose every shown row (Ctrl+A)")
                enabled: list.count > 0
                onClicked: popup.compare.selectShown(true)
            }
            TpButton {
                flat: true
                text: i18n.tr("None")
                enabled: popup.compare.selectedCount > 0
                onClicked: popup.compare.selectShown(false)
            }
            TpButton {
                text: i18n.tr("Copy B → A")
                enabled: popup.compare.selectedCount > 0 && !popup.compare.samePreset
                onClicked: popup.error = popup.compare.copySelected(true)
            }
            TpButton {
                text: i18n.tr("Copy A → B")
                enabled: popup.compare.selectedCount > 0 && !popup.compare.samePreset
                onClicked: popup.error = popup.compare.copySelected(false)
            }
        }

        // Copied values not written yet: same bar as the editor pages (no undo: Discard reads the presets again)
        TpPendingBar {
            objectName: "comparePendingBar"
            pendingCount: popup.compare.copiedCount
            historyButtons: false
            applyTip: i18n.tr("Write the copied values into the presets")
            onDiscardRequested: {
                popup.error = ""
                popup.compare.discard()
            }
            onApplyRequested: popup.error = popup.compare.save()
        }
    }

    // Closed with copied values not written: written, dropped, or panel opened again
    TpUnsavedDialog {
        id: unsavedDialog
        objectName: "compareUnsavedDialog"
        title: i18n.tr("Copied values not saved")
        text: i18n.tr("Write the copied values into the presets before closing the comparison?")
        cancelText: i18n.tr("Keep Editing")
        onApplyChosen: {
            popup.error = popup.compare.save()
            if (popup.error !== "") {
                popup.open()  // not written: why, in the panel
                return
            }
            popup.compare.stop()
            popup.dismissed()
        }
        onDiscardChosen: {
            popup.compare.stop()
            popup.dismissed()
        }
        onCancelled: popup.open()
    }
}
