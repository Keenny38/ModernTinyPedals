import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Overlays step: new or existing preset, overlays to show as picture tiles (rendered in chosen style)
SetupStep {
    id: step
    maxWidth: theme.em * 64

    SetupHeading { text: i18n.tr("Preset to use") }

    Card {
        Layout.fillWidth: true
        implicitHeight: presetColumn.implicitHeight + theme.em * 1.6

        ColumnLayout {
            id: presetColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.em * 0.8
            spacing: theme.em * 0.6

            TpSegmented {
                visible: backend.presets.length > 0
                options: [i18n.tr("New preset"), i18n.tr("Existing preset")]
                currentIndex: backend.newPreset ? 0 : 1
                onActivated: function(index) { backend.setNewPreset(index === 0) }
            }

            RowLayout {
                visible: backend.newPreset
                Layout.fillWidth: true
                spacing: theme.em * 0.6
                Text {
                    text: i18n.tr("Name")
                    color: theme.dimText
                }
                TpTextField {
                    id: nameField
                    Layout.fillWidth: true
                    Layout.maximumWidth: theme.em * 22
                    text: backend.newName
                    placeholderText: i18n.tr("Enter a new preset name")
                    invalid: backend.nameError !== ""
                    validator: RegularExpressionValidator { regularExpression: new RegExp(backend.filenamePattern) }
                    onTextEdited: backend.setNewName(text)
                    onEscaped: text = backend.newName
                }
                Text {
                    Layout.fillWidth: true
                    text: backend.nameError
                    color: theme.loss
                    wrapMode: Text.WordWrap
                    font.pointSize: theme.fontPoint * 0.92
                }
            }

            RowLayout {
                visible: !backend.newPreset
                Layout.fillWidth: true
                spacing: theme.em * 0.6
                Text {
                    text: i18n.tr("Name")
                    color: theme.dimText
                }
                TpCombo {
                    Layout.preferredWidth: theme.em * 16
                    model: backend.presets
                    currentIndex: backend.presetIndex
                    tip: i18n.tr("Preset to use")
                    onActivated: function(index) { backend.setPresetIndex(index) }
                }
                Pill {
                    visible: backend.presets[backend.presetIndex] === backend.loadedPreset
                    text: i18n.tr("Loaded")
                    tint: theme.gain
                }
                Item { Layout.fillWidth: true }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: theme.em * 0.4
        spacing: theme.em * 0.4
        Text {
            text: i18n.tr("Overlays to show")
            color: theme.text
            font.pointSize: theme.fontPoint * 1.05
            font.weight: Font.DemiBold
        }
        Pill {
            text: backend.checkedCount + " / " + backend.tileCount
            tint: backend.checkedCount > 0 ? theme.accent : theme.dimText
        }
        Item { Layout.fillWidth: true }
        TpButton {
            flat: true
            text: i18n.tr("Recommended")
            onClicked: backend.checkOverlays("recommended")
        }
        TpButton {
            flat: true
            text: i18n.tr("All")
            onClicked: backend.checkOverlays("all")
        }
        TpButton {
            flat: true
            text: i18n.tr("None")
            onClicked: backend.checkOverlays("none")
        }
    }

    Text {
        Layout.fillWidth: true
        visible: backend.otherOverlaysKept
        text: i18n.tr("Overlays not listed here keep their state in this preset.")
        color: theme.dimText
        wrapMode: Text.WordWrap
        font.pointSize: theme.fontPoint * 0.92
    }

    Flow {
        id: grid
        readonly property int columns: Math.max(2, Math.floor((width + spacing) / (theme.em * 11.5 + spacing)))
        readonly property real tileWidth: Math.floor((width - spacing * (columns - 1)) / columns)
        Layout.fillWidth: true
        spacing: theme.em * 0.7

        Repeater {
            model: backend.tileModel
            Rectangle {
                id: tile
                required property string key
                required property string label
                required property string category
                required property string tint
                required property bool checked
                required property string preview
                required property int previewWidth
                required property int previewHeight
                required property int previewState
                width: grid.tileWidth
                height: picture.height + info.implicitHeight + theme.em * 1.3
                radius: theme.em * 0.75
                color: tileArea.containsMouse ? (theme.dark ? Qt.lighter(theme.base, 1.18) : Qt.darker(theme.base, 1.025)) : theme.base
                border.width: checked ? 2 : 1
                border.color: checked ? theme.accent : (theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border)
                scale: tileArea.pressed ? 0.98 : 1
                activeFocusOnTab: true
                Behavior on color { ColorAnimation { duration: 120 } }
                Behavior on border.color { ColorAnimation { duration: 150 } }
                Behavior on scale { NumberAnimation { duration: 90 } }
                Accessible.role: Accessible.CheckBox
                Accessible.name: label
                Accessible.checkable: true
                Accessible.checked: checked
                Keys.onSpacePressed: function(event) {
                    event.accepted = true
                    backend.toggleOverlay(tile.key)
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: -3
                    radius: parent.radius + 3
                    color: "transparent"
                    border.width: 2
                    border.color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.5)
                    visible: tile.activeFocus
                }

                SetupBackdrop {
                    id: picture
                    x: theme.em * 0.45
                    y: theme.em * 0.45
                    width: parent.width - theme.em * 0.9
                    height: Math.round(theme.em * 5.5)
                    source: tile.preview
                    sourceWidth: tile.previewWidth
                    sourceHeight: tile.previewHeight
                    loading: tile.previewState === 0
                    dim: tile.checked ? 1 : 0.5

                    Rectangle {  // check mark
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: theme.em * 0.35
                        width: Math.round(theme.em * 1.3)
                        height: width
                        radius: theme.em * 0.3
                        color: tile.checked ? theme.accent : Qt.rgba(0, 0, 0, 0.35)
                        border.width: tile.checked ? 0 : 1.5
                        border.color: Qt.rgba(1, 1, 1, 0.7)
                        Behavior on color { ColorAnimation { duration: 150 } }
                        Icon {
                            anchors.centerIn: parent
                            visible: tile.checked
                            glyph: ""  // check
                            color: "white"
                            size: theme.em * 0.72
                        }
                    }
                }

                ColumnLayout {
                    id: info
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: picture.bottom
                    anchors.margins: theme.em * 0.6
                    anchors.topMargin: theme.em * 0.45
                    spacing: theme.em * 0.3
                    Text {
                        Layout.fillWidth: true
                        text: tile.label
                        color: theme.text
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Pill {
                        text: tile.category
                        tint: tile.tint
                    }
                }

                MouseArea {
                    id: tileArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: backend.toggleOverlay(tile.key)
                }
            }
        }
    }
}
