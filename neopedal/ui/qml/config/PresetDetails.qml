import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Details of selected preset (Presets page, wide windows): load, actions, auto load tags (car classes,
// tracks: add & remove), preset hotkeys, overlays & modules it turns on, file info.
Card {
    id: details
    property var info: ({ "found": false })
    signal nameRequested(string mode)  // duplicate, rename
    signal classMenuRequested(Item item)
    signal trackMenuRequested(Item item)

    readonly property bool found: info.found === true

    component SectionTitle: TpSectionLabel {
        Layout.fillWidth: true
        Layout.topMargin: theme.em * 0.5
    }
    // Action of the grid: icon & text left aligned, text cut to the column (full text in tooltip)
    component ActionButton: TpButton {
        id: action
        Layout.fillWidth: true
        Layout.preferredWidth: 1  // columns of same width
        flat: true
        implicitHeight: Math.round(theme.rowCompact)
        tip: actionText.truncated ? text : ""
        contentItem: Item {
            implicitHeight: actionText.implicitHeight
            Icon {
                id: actionIcon
                x: theme.em * 0.4
                anchors.verticalCenter: parent.verticalCenter
                glyph: action.glyph
                size: theme.em * 0.95
                color: action.danger ? theme.loss : theme.dimText
            }
            Text {
                id: actionText
                anchors.left: actionIcon.visible ? actionIcon.right : parent.left
                anchors.leftMargin: theme.em * 0.6
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: action.text
                color: action.danger ? theme.loss : theme.text
                elide: Text.ElideRight
            }
        }
    }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.margins: theme.padCard
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        // Keyboard focus (Tab) on an action below or above the shown part: scrolled into view
        function ensureVisible(item) {
            for (var inside = item; inside; inside = inside.parent) {
                if (inside === column) {
                    var y = item.mapToItem(column, 0, 0).y
                    if (y < contentY)
                        contentY = Math.max(0, y - theme.space3)
                    else if (y + item.height > contentY + height)
                        contentY = Math.min(Math.max(0, contentHeight - height), y + item.height - height + theme.space3)
                    return
                }
            }
        }
        Connections {
            target: flick.Window.window
            function onActiveFocusItemChanged() {
                if (flick.Window.activeFocusItem)
                    flick.ensureVisible(flick.Window.activeFocusItem)
            }
        }

        ColumnLayout {
            id: column
            width: flick.width - theme.em * 0.6
            spacing: theme.em * 0.4
            visible: details.found

            // Name & load
            Text {
                Layout.fillWidth: true
                text: details.info.name || ""
                color: theme.text
                font.pointSize: theme.fontHeading
                font.weight: Font.DemiBold
                wrapMode: Text.WrapAtWordBoundaryOrAnywhere  // long names cut between words when they can
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: details.info.date || ""
                color: theme.dimText
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
            }
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.3
                Pill { visible: details.info.loaded === true; text: i18n.tr("Loaded"); solid: true }
                Pill {
                    visible: details.info.locked === true
                    glyph: ""  // lock
                    text: i18n.tr("Locked") + (details.info.lockVersion ? " " + details.info.lockVersion : "")
                    tint: theme.dimText
                    tip: i18n.tr("Locked: changes are not saved")
                }
                Pill {
                    visible: (details.info.api || "") !== ""
                    glyph: ""  // network
                    text: details.info.api || ""
                    tint: theme.dimText
                    tip: i18n.tr("Game API remembered by the preset")
                }
            }
            TpButton {
                Layout.fillWidth: true
                Layout.topMargin: theme.em * 0.3
                visible: details.info.loaded !== true
                accent: true
                glyph: ""  // play
                text: i18n.tr("Load Preset")
                onClicked: backend.load(details.info.key)
            }

            // Actions
            SectionTitle { text: i18n.tr("Actions") }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: theme.em * 0.2
                rowSpacing: 0
                ActionButton { glyph: ""; text: i18n.tr("Duplicate"); onClicked: details.nameRequested("duplicate") }  // copy
                ActionButton {
                    glyph: ""  // rename
                    text: i18n.tr("Rename")
                    enabled: details.info.locked !== true
                    onClicked: details.nameRequested("rename")
                }
                ActionButton {
                    glyph: details.info.locked ? "" : ""  // unlock, lock
                    text: details.info.locked ? i18n.tr("Unlock Preset") : i18n.tr("Lock Preset")
                    onClicked: backend.toggleLock(details.info.key)
                }
                ActionButton { glyph: ""; text: i18n.tr("Backup Preset"); onClicked: backend.backup(details.info.key) }  // history
                ActionButton { glyph: ""; text: i18n.tr("Export Package..."); onClicked: backend.exportPackage(details.info.key) }  // export
                ActionButton {
                    glyph: ""  // library
                    text: i18n.tr("Compare with Loaded Preset")
                    enabled: details.info.loaded !== true
                    onClicked: backend.compare(details.info.key)
                }
                ActionButton {
                    glyph: ""  // delete
                    text: i18n.tr("Delete")
                    danger: true
                    enabled: details.info.loaded !== true && details.info.locked !== true
                    onClicked: backend.remove(details.info.key)
                }
            }

            // Auto load
            SectionTitle { text: i18n.tr("Primary preset for") }
            Text {
                Layout.fillWidth: true
                visible: (details.info.classes || []).length === 0 && (details.info.tracks || []).length === 0
                text: i18n.tr("No car class or track: this preset is only loaded by hand or by hotkey.")
                color: theme.dimText
                wrapMode: Text.WordWrap
                font.pointSize: theme.fontLabel
            }
            Flow {
                Layout.fillWidth: true
                spacing: theme.space2
                Repeater {
                    model: details.info.classes || []
                    TpTag {
                        required property var modelData
                        text: modelData.name
                        dotColor: modelData.color !== "" ? modelData.color : theme.accent
                        maximumTextWidth: Math.max(theme.em * 4, flick.width - theme.em * 4)
                        removable: true
                        onRemoveRequested: backend.removePrimaryClass(modelData.name)
                    }
                }
                Repeater {
                    model: details.info.tracks || []
                    TpTag {
                        required property string modelData
                        text: modelData
                        glyph: ""  // flag
                        maximumTextWidth: Math.max(theme.em * 4, flick.width - theme.em * 5)
                        removable: true
                        onRemoveRequested: backend.removePrimaryTrack(modelData)
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.em * 0.3
                TpButton {
                    id: addClass
                    flat: true
                    glyph: ""  // add
                    text: i18n.tr("Car Class")
                    enabled: (details.info.classChoices || []).length > 0
                    size: "sm"
                    onClicked: details.classMenuRequested(addClass)
                }
                TpButton {
                    id: addTrack
                    flat: true
                    glyph: ""  // add
                    text: i18n.tr("Track")
                    enabled: (details.info.trackChoices || []).length > 0
                    tip: (details.info.trackChoices || []).length === 0 ? i18n.tr("Tracks come from Track Info Editor (Tools)") : ""
                    size: "sm"
                    onClicked: details.trackMenuRequested(addTrack)
                }
            }
            Text {
                Layout.fillWidth: true
                visible: (details.info.hotkeys || []).length > 0
                text: i18n.trm("Preset hotkeys: " + (details.info.hotkeys || []).join(", "))
                color: theme.dimText
                wrapMode: Text.WordWrap
                font.pointSize: theme.fontLabel
            }

            // Content
            SectionTitle {  // content read meanwhile: no count yet
                text: details.info.pending === true ? i18n.tr("Overlays") : i18n.trm((details.info.overlays || 0) + " overlays")
            }
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.3
                Repeater {
                    model: details.info.overlayNames || []
                    Pill { required property string modelData; text: modelData; tint: theme.dimText }
                }
                Pill { visible: (details.info.overlayMore || 0) > 0; text: "+" + details.info.overlayMore; tint: theme.dimText }
            }
            SectionTitle {
                text: details.info.pending === true ? i18n.tr("Module") : i18n.trm((details.info.modules || 0) + " modules")
            }
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.3
                Repeater {
                    model: details.info.moduleNames || []
                    Pill { required property string modelData; text: modelData; tint: theme.dimText }
                }
                Pill { visible: (details.info.moduleMore || 0) > 0; text: "+" + details.info.moduleMore; tint: theme.dimText }
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: theme.em * 0.5
                text: (details.info.key || "") + "  ·  " + (details.info.size || "")
                color: theme.dimText
                font.pointSize: theme.fontCaption
                elide: Text.ElideMiddle
            }
        }
    }

    EmptyState {
        anchors.centerIn: parent
        visible: !details.found
        glyph: ""  // library
        title: i18n.tr("No preset selected")
        text: i18n.tr("Select a preset to see what it contains.")
    }
}
