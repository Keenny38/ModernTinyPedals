import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Overlay row of Overlays page (compact list): category dot, name, when it shows (if not always), category & what
// it shows, favorite star, settings & on/off switch. Preview shown in a tooltip while hovering the row. Click opens
// settings, right-click the menu.
Item {
    id: row
    required property int index
    required property string name
    required property string label
    required property string category
    required property string categoryLabel
    required property color categoryColor
    required property bool active
    required property bool failed
    required property string preview
    required property int previewState
    required property int previewWidth
    required property int previewHeight
    required property string description
    required property bool favorite
    required property var badges  // [{kind, text, tip}]: shown only in some situations
    property bool menuOpen: false  // no preview over the menu
    readonly property bool current: GridView.isCurrentItem && GridView.view.activeFocus
    readonly property bool hovered: area.containsMouse
    property bool recycling: false  // in reuse pool: no animation from the previous row's state
    signal menuRequested(Item item, real x, real y)

    GridView.onPooled: {
        recycling = true
        opacity = 1  // add transition cut short by pooling: not reused faded or shrunk
        scale = 1
    }
    GridView.onReused: recycling = false

    width: GridView.view.cellWidth
    height: GridView.view.cellHeight

    Accessible.role: Accessible.ListItem
    Accessible.name: label + ", " + categoryLabel + ", " + (active ? i18n.tr("Enabled") : i18n.tr("Disabled"))
                     + (favorite ? ", " + i18n.tr("Favorite") : "") + (failed ? ", " + i18n.tr("Error") : "")
    Accessible.description: description

    TpListRow {  // card row: active overlay tinted (outline too), hover on the card surface
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        card: true
        hovered: row.hovered
        emphasized: row.active
        animate: !row.recycling

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onClicked: function(mouse) {
                row.GridView.view.currentIndex = row.index
                if (mouse.button === Qt.RightButton)
                    row.menuRequested(area, mouse.x, mouse.y)
                else
                    backend.openConfig(row.name)
            }
        }

        ColorDot {
            id: dot
            x: theme.space5
            anchors.verticalCenter: parent.verticalCenter
            color: row.categoryColor
        }
        Text {
            id: nameText
            anchors.left: dot.right
            anchors.leftMargin: theme.space4
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, controls.x - x - theme.space4 - badgeIcons.width)
            text: row.label
            textFormat: Text.PlainText
            color: row.active ? theme.text : theme.dimOn(surface.color)
            font.weight: row.active ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
        }
        // Shown only in some situations: icon per limit, text in its tooltip
        Row {
            id: badgeIcons
            anchors.left: nameText.right
            anchors.leftMargin: row.badges.length ? theme.space3 : 0
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.space2
            Repeater {
                model: row.badges
                Icon {
                    required property var modelData
                    glyph: modelData.kind === "stream" ? "" : modelData.kind === "screen" ? "" : ""
                    fallback: "•"
                    size: theme.iconSm
                    color: theme.dimOn(surface.color)
                    MouseArea { id: iconArea; anchors.fill: parent; hoverEnabled: true }
                    ToolTip.visible: iconArea.containsMouse
                    ToolTip.text: modelData.text + ": " + modelData.tip
                    ToolTip.delay: theme.tipDelay
                }
            }
        }
        Text {
            anchors.left: badgeIcons.right
            anchors.leftMargin: theme.space5
            anchors.right: controls.left
            anchors.rightMargin: theme.space4
            anchors.verticalCenter: parent.verticalCenter
            text: row.description !== "" ? row.categoryLabel + "  \u00b7  " + row.description : row.categoryLabel
            textFormat: Text.PlainText
            color: theme.dimOn(surface.color)
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
            visible: width > theme.em * 3  // content-tuned: hidden when too narrow to be read
        }
        Row {
            id: controls
            anchors.right: parent.right
            anchors.rightMargin: theme.space3
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.space2
            Pill {  // start error: icon & text (same badge as the cards)
                objectName: "errorBadge"
                visible: row.failed
                anchors.verticalCenter: parent.verticalCenter
                solid: true
                tint: theme.lossFill
                glyph: "\uE7BA"  // warning
                fallback: "!"
                text: i18n.tr("Error")
                tip: i18n.tr("Overlay could not start, see log (Help menu)")
            }
            TpButton {
                flat: true
                size: "sm"
                glyph: row.favorite ? theme.glyphs.favoriteOn : theme.glyphs.favorite
                fallback: row.favorite ? "★" : "☆"
                tip: row.favorite ? i18n.tr("Remove from Favorites") : i18n.tr("Add to Favorites")
                shortcut: "Ctrl+D"  // list key, in the tooltip
                opacity: row.favorite || row.hovered || hovered || visualFocus || row.current ? 1 : 0
                anchors.verticalCenter: parent.verticalCenter
                onClicked: {
                    row.GridView.view.currentIndex = row.index
                    backend.toggleFavorite(row.name)
                }
            }
            TpButton {
                flat: true
                size: "sm"
                glyph: ""  // settings
                fallback: "⚙"
                tip: i18n.tr("Options…")
                opacity: row.hovered || hovered || visualFocus || row.current ? 1 : 0  // revealed: hover, focus, current
                anchors.verticalCenter: parent.verticalCenter
                onClicked: backend.openConfig(row.name)
            }
            TpSwitch {
                checkable: false  // follows model: switched by backend
                checked: row.active
                tip: i18n.tr("Enable / Disable")
                implicitWidth: theme.em * 2.6
                anchors.verticalCenter: parent.verticalCenter
                onClicked: {
                    row.GridView.view.currentIndex = row.index
                    backend.toggle(row.name)
                }
                Accessible.role: Accessible.CheckBox
                Accessible.name: row.label
                Accessible.checked: row.active
            }
        }

        // Preview tooltip next to cursor
        TpToolTip {  // picture on the preview stage (always dark): its own background
            id: previewTip
            visible: row.hovered && row.previewState === 1 && !row.menuOpen
                     && area.mouseX < controls.x - theme.em
            delay: theme.hoverIntentDelay  // a row hovered a moment, not passed over
            x: Math.round(area.mouseX + theme.em)
            y: surface.height + theme.space1
            padding: theme.space3
            readonly property real fit: Math.min(1, theme.em * 30 / Math.max(row.previewWidth, 1),
                                                 theme.em * 20 / Math.max(row.previewHeight, 1))
            contentItem: Image {
                source: previewTip.visible ? row.preview : ""
                width: Math.round(row.previewWidth * previewTip.fit)
                height: Math.round(row.previewHeight * previewTip.fit)
                asynchronous: true
                retainWhileLoading: true
                cache: true
                sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
                smooth: true
            }
            background: Rectangle {
                radius: theme.radiusSm
                color: theme.stageBottom
                border.width: 1
                border.color: theme.border
            }
        }
    }

    FocusRing { target: surface; visible: row.current }
}
