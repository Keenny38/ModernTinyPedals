import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Details of selected preset (Presets page, wide windows): load, actions, auto load tags (car classes,
// tracks: add & remove), preset hotkeys, overlays & modules it turns on, file info.
Card {
    id: details
    property var info: ({ "found": false })
    signal nameRequested(string mode)  // duplicate, rename
    signal classMenuRequested(Item item)
    signal trackMenuRequested(Item item)

    readonly property bool found: info.found === true

    component SectionTitle: Text {
        Layout.fillWidth: true
        Layout.topMargin: theme.em * 0.5
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.8
        font.weight: Font.DemiBold
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.6
        elide: Text.ElideRight
    }
    // Action of the grid: icon & text left aligned, text cut to the column (full text in tooltip)
    component ActionButton: TpButton {
        id: action
        property bool danger: false
        Layout.fillWidth: true
        Layout.preferredWidth: 1  // columns of same width
        flat: true
        implicitHeight: Math.round(theme.em * 2.1)
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
                anchors.leftMargin: theme.em * 0.55
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
        anchors.margins: theme.em * 0.8
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: column
            width: flick.width - theme.em * 0.6
            spacing: theme.em * 0.35
            visible: details.found

            // Name & load
            Text {
                Layout.fillWidth: true
                text: details.info.name || ""
                color: theme.text
                font.pointSize: theme.fontPoint * 1.3
                font.weight: Font.DemiBold
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: details.info.date || ""
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
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
                ActionButton { glyph: ""; text: i18n.tr("Copy Share Code"); onClicked: backend.copyShareCode(details.info.key) }  // share
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
                font.pointSize: theme.fontPoint * 0.9
            }
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.3
                Repeater {
                    model: details.info.classes || []
                    Rectangle {
                        id: classTag
                        required property var modelData
                        height: Math.round(theme.em * 1.7)
                        width: classRow.implicitWidth + theme.em * 0.6
                        radius: height / 2
                        color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.1)
                        border.width: 1
                        border.color: theme.border
                        Row {
                            id: classRow
                            anchors.verticalCenter: parent.verticalCenter
                            x: theme.em * 0.45
                            spacing: theme.em * 0.35
                            Rectangle {
                                width: Math.round(theme.em * 0.6)
                                height: width
                                radius: width / 2
                                color: classTag.modelData.color !== "" ? classTag.modelData.color : theme.accent
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text { text: classTag.modelData.name; color: theme.text; anchors.verticalCenter: parent.verticalCenter }
                            TpButton {
                                flat: true
                                glyph: ""  // cancel
                                text: theme.iconFont === "" ? "x" : ""
                                tip: i18n.tr("Remove")
                                implicitHeight: Math.round(theme.em * 1.4)
                                implicitWidth: implicitHeight
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: backend.removePrimaryClass(classTag.modelData.name)
                            }
                        }
                    }
                }
                Repeater {
                    model: details.info.tracks || []
                    Rectangle {
                        id: trackTag
                        required property string modelData
                        height: Math.round(theme.em * 1.7)
                        width: trackRow.implicitWidth + theme.em * 0.6
                        radius: height / 2
                        color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.1)
                        border.width: 1
                        border.color: theme.border
                        Row {
                            id: trackRow
                            anchors.verticalCenter: parent.verticalCenter
                            x: theme.em * 0.45
                            spacing: theme.em * 0.35
                            Icon { glyph: ""; size: theme.em * 0.75; color: theme.accent; anchors.verticalCenter: parent.verticalCenter }  // flag
                            Text { text: trackTag.modelData; color: theme.text; anchors.verticalCenter: parent.verticalCenter }
                            TpButton {
                                flat: true
                                glyph: ""  // cancel
                                text: theme.iconFont === "" ? "x" : ""
                                tip: i18n.tr("Remove")
                                implicitHeight: Math.round(theme.em * 1.4)
                                implicitWidth: implicitHeight
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: backend.removePrimaryTrack(trackTag.modelData)
                            }
                        }
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
                    implicitHeight: Math.round(theme.em * 2)
                    onClicked: details.classMenuRequested(addClass)
                }
                TpButton {
                    id: addTrack
                    flat: true
                    glyph: ""  // add
                    text: i18n.tr("Track")
                    enabled: (details.info.trackChoices || []).length > 0
                    tip: (details.info.trackChoices || []).length === 0 ? i18n.tr("Tracks come from Track Info Editor (Tools)") : ""
                    implicitHeight: Math.round(theme.em * 2)
                    onClicked: details.trackMenuRequested(addTrack)
                }
            }
            Text {
                Layout.fillWidth: true
                visible: (details.info.hotkeys || []).length > 0
                text: i18n.trm("Preset hotkeys: " + (details.info.hotkeys || []).join(", "))
                color: theme.dimText
                wrapMode: Text.WordWrap
                font.pointSize: theme.fontPoint * 0.9
            }

            // Content
            SectionTitle { text: i18n.trm((details.info.overlays || 0) + " overlays") }
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.25
                Repeater {
                    model: details.info.overlayNames || []
                    Pill { required property string modelData; text: modelData; tint: theme.dimText }
                }
                Pill { visible: (details.info.overlayMore || 0) > 0; text: "+" + details.info.overlayMore; tint: theme.dimText }
            }
            SectionTitle { text: i18n.trm((details.info.modules || 0) + " modules") }
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.25
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
                font.pointSize: theme.fontPoint * 0.8
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
