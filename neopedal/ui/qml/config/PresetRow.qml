import QtQuick
import QtQuick.Controls.Basic
import "../components"

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
    required property bool pending  // content not read yet: last change only
    required property string contentText  // last change & content, translated by backend
    property bool selected: false
    readonly property bool current: ListView.isCurrentItem && ListView.view.activeFocus
    readonly property bool wide: width > theme.em * 36  // content-tuned: row width (not page), extra column shown
    signal clicked()
    signal loadRequested()
    property bool recycling: false  // in reuse pool: no animation from the previous row's state
    signal menuRequested(Item item, real x, real y)

    ListView.onPooled: recycling = true
    ListView.onReused: recycling = false

    width: ListView.view ? ListView.view.width - theme.em * 0.7 : 0  // room for scroll bar
    height: Math.round(theme.rowTall)

    Accessible.role: Accessible.ListItem
    Accessible.name: name + (loaded ? ", " + i18n.tr("Loaded") : "") + (locked ? ", " + i18n.tr("Locked") : "")

    TpListRow {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        card: true
        hovered: area.containsMouse
        selected: row.selected
        animate: !row.recycling

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
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

        TpIconTile {
            id: badge
            x: theme.em * 0.75
            anchors.verticalCenter: parent.verticalCenter
            size: Math.round(theme.em * 2.1)
            strong: row.loaded
            tint: row.unreadable && !row.loaded ? theme.warning : theme.accent
            fallbackText: row.name
            glyph: row.unreadable ? "" : row.loaded ? "" : ""  // warning, check, library
        }

        Column {
            anchors.left: badge.right
            anchors.leftMargin: theme.padCard
            anchors.right: tags.left
            anchors.rightMargin: theme.space4
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Row {
                width: parent.width
                spacing: theme.space3
                Text {
                    id: nameText
                    width: Math.min(implicitWidth, parent.width - marks.width - theme.em * 0.4)
                    text: row.name
                    textFormat: Text.PlainText
                    color: theme.text
                    font.weight: row.loaded ? Font.DemiBold : Font.Medium
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                }
                Row {
                    id: marks
                    spacing: theme.space2
                    anchors.verticalCenter: parent.verticalCenter
                    Pill {
                        visible: row.loaded
                        text: i18n.tr("Loaded")
                        solid: true
                    }
                    Pill {
                        visible: row.locked
                        glyph: theme.glyphs.lock
                        text: row.lockVersion
                        tint: theme.dimText
                        tip: i18n.tr("Locked: changes are not saved")
                    }
                }
            }
            Text {
                width: parent.width
                text: row.contentText
                textFormat: Text.PlainText
                color: row.unreadable ? theme.warning : theme.dimText
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
            }
        }

        Row {
            id: tags
            anchors.right: actions.left
            anchors.rightMargin: theme.em * 0.5
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.space2
            visible: row.wide
            // Many tags: cut at 40 % of the row, the preset name keeps its room
            width: visible ? Math.min(implicitWidth, Math.round(row.width * 0.4)) : 0
            clip: true
            Repeater {
                model: row.classes.slice(0, 3)
                Pill {
                    required property var modelData
                    // Class preset of one session: "GT3 · Race"
                    text: modelData.name + (modelData.session === "practice" ? "  ·  " + i18n.tr("Practice")
                        : modelData.session === "qualify" ? "  ·  " + i18n.tr("Qualify")
                        : modelData.session === "race" ? "  ·  " + i18n.tr("Race") : "")
                    tint: modelData.color !== "" ? modelData.color : theme.accent
                    solid: true
                    tip: modelData.session ? i18n.tr("Primary preset for class in this session")
                                           : i18n.tr("Primary preset for class")
                }
            }
            Repeater {
                model: row.tracks.slice(0, 2)
                Pill {
                    required property string modelData
                    maximumTextWidth: theme.em * 9
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
                maximumTextWidth: theme.em * 9
                tint: theme.dimText
                tip: i18n.tr("Loaded by preset hotkey")
            }
        }

        Row {
            id: actions
            anchors.right: parent.right
            anchors.rightMargin: theme.space3
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.space1
            TpButton {
                text: i18n.tr("Load")
                accent: true
                visible: !row.loaded
                size: "sm"
                opacity: area.containsMouse || hovered || row.current || row.selected ? 1 : 0
                enabled: opacity > 0
                Behavior on opacity { enabled: !row.recycling; NumberAnimation { duration: theme.motionFast } }
                onClicked: row.loadRequested()
            }
            TpButton {
                id: moreButton
                flat: true
                glyph: theme.glyphs.more
                fallback: "…"
                tip: i18n.tr("More actions")
                size: "sm"
                onClicked: {
                    row.ListView.view.currentIndex = row.index
                    row.clicked()
                    row.menuRequested(moreButton, 0, moreButton.height + 4)
                }
            }
        }
    }

    FocusRing { target: surface; visible: row.current }
}
