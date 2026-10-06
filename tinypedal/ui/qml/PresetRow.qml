import QtQuick
import QtQuick.Controls.Basic

// Preset row of Presets page: name, loaded & locked marks, last change & content (overlays, modules),
// primary tags (car classes, tracks) & preset hotkeys. Click selects, double click loads, right click
// (or the more button) opens the menu. Load button shows on hover.
Item {
    id: row
    required property int index
    required property string key
    required property string name
    required property bool loaded
    required property bool locked
    required property string lockVersion
    required property string changedText
    required property var classes
    required property var tracks
    required property var hotkeys
    required property int overlays
    required property int modules
    required property bool unreadable
    property bool selected: false
    readonly property bool current: ListView.isCurrentItem && ListView.view.activeFocus
    readonly property bool wide: width > theme.em * 36
    signal clicked()
    signal loadRequested()
    signal menuRequested(Item item, real x, real y)

    width: ListView.view ? ListView.view.width - theme.em * 0.7 : 0  // room for scroll bar
    height: Math.round(theme.em * 3.3)

    Accessible.role: Accessible.ListItem
    Accessible.name: name + (loaded ? ", " + i18n.tr("Loaded") : "") + (locked ? ", " + i18n.tr("Locked") : "")

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: theme.em * 0.55
        color: row.selected ? Qt.tint(theme.base, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.12))
             : area.containsMouse ? theme.hover : theme.base
        border.width: 1
        border.color: row.selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.75)
                    : theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: function(mouse) {
                row.ListView.view.currentIndex = row.index
                row.clicked()
                if (mouse.button === Qt.RightButton)
                    row.menuRequested(area, mouse.x, mouse.y)
            }
            onDoubleClicked: function(mouse) {
                if (mouse.button === Qt.LeftButton)
                    row.loadRequested()
            }
        }

        // Loaded preset strip
        Rectangle {
            visible: row.loaded
            x: theme.em * 0.3
            width: Math.round(theme.em * 0.24)
            height: parent.height - theme.em * 0.9
            anchors.verticalCenter: parent.verticalCenter
            radius: width / 2
            color: theme.accent
        }

        Rectangle {
            id: badge
            x: theme.em * 0.75
            anchors.verticalCenter: parent.verticalCenter
            width: Math.round(theme.em * 2.1)
            height: width
            radius: theme.em * 0.5
            color: row.loaded ? theme.accent : Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.15 : 0.1)
            Icon {
                anchors.centerIn: parent
                glyph: row.unreadable ? "" : row.loaded ? "" : ""  // warning, check, library
                size: theme.em * 0.95
                color: row.loaded ? "white" : row.unreadable ? theme.warning : theme.accent
            }
            Text {
                anchors.centerIn: parent
                visible: theme.iconFont === ""
                text: row.name.charAt(0).toUpperCase()
                color: row.loaded ? "white" : theme.accent
                font.weight: Font.DemiBold
            }
        }

        Column {
            anchors.left: badge.right
            anchors.leftMargin: theme.em * 0.7
            anchors.right: tags.left
            anchors.rightMargin: theme.em * 0.6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Row {
                width: parent.width
                spacing: theme.em * 0.4
                Text {
                    id: nameText
                    width: Math.min(implicitWidth, parent.width - marks.width - theme.em * 0.4)
                    text: row.name
                    color: theme.text
                    font.weight: row.loaded ? Font.DemiBold : Font.Medium
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                }
                Row {
                    id: marks
                    spacing: theme.em * 0.3
                    anchors.verticalCenter: parent.verticalCenter
                    Pill {
                        visible: row.loaded
                        text: i18n.tr("Loaded")
                        solid: true
                    }
                    Pill {
                        visible: row.locked
                        glyph: ""  // lock
                        text: row.lockVersion
                        tint: theme.dimText
                        tip: i18n.tr("Locked: changes are not saved")
                    }
                }
            }
            Text {
                width: parent.width
                text: row.unreadable ? i18n.tr("Unreadable file") + "  ·  " + row.changedText
                    : row.changedText + "  ·  " + i18n.trm(row.overlays + " overlays") + "  ·  " + i18n.trm(row.modules + " modules")
                color: row.unreadable ? theme.warning : theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                elide: Text.ElideRight
            }
        }

        Row {
            id: tags
            anchors.right: actions.left
            anchors.rightMargin: theme.em * 0.5
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.3
            visible: row.wide
            width: visible ? implicitWidth : 0
            Repeater {
                model: row.classes.slice(0, 3)
                Pill {
                    required property var modelData
                    text: modelData.name
                    tint: modelData.color !== "" ? modelData.color : theme.accent
                    solid: true
                    tip: i18n.tr("Primary preset for class")
                }
            }
            Repeater {
                model: row.tracks.slice(0, 2)
                Pill {
                    required property string modelData
                    glyph: ""  // flag
                    text: modelData
                    tip: i18n.tr("Primary preset for track")
                }
            }
            Pill {
                readonly property int more: Math.max(row.classes.length - 3, 0) + Math.max(row.tracks.length - 2, 0)
                visible: more > 0
                text: "+" + more
                tint: theme.dimText
            }
            Pill {
                visible: row.hotkeys.length > 0
                glyph: ""  // keyboard
                text: row.hotkeys.join(", ")
                tint: theme.dimText
                tip: i18n.tr("Loaded by preset hotkey")
            }
        }

        Row {
            id: actions
            anchors.right: parent.right
            anchors.rightMargin: theme.em * 0.4
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.2
            TpButton {
                text: i18n.tr("Load")
                accent: true
                visible: !row.loaded
                implicitHeight: Math.round(theme.em * 1.9)
                opacity: area.containsMouse || hovered || row.current || row.selected ? 1 : 0
                enabled: opacity > 0
                Behavior on opacity { NumberAnimation { duration: 120 } }
                onClicked: row.loadRequested()
            }
            TpButton {
                id: moreButton
                flat: true
                glyph: ""  // more
                text: theme.iconFont === "" ? "..." : ""
                tip: i18n.tr("More actions")
                implicitHeight: Math.round(theme.em * 1.9)
                onClicked: {
                    row.ListView.view.currentIndex = row.index
                    row.clicked()
                    row.menuRequested(moreButton, 0, moreButton.height + 4)
                }
            }
        }
    }

    Rectangle {
        anchors.fill: surface
        anchors.margins: -2
        radius: surface.radius + 2
        color: "transparent"
        border.width: 2
        border.color: theme.accent
        visible: row.current
    }
}
