import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Overlay row of Overlays page (compact list): category dot, name, category, settings & on/off switch.
// Preview shown in a tooltip while hovering the row. Click opens settings, right-click the menu.
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
                     + (failed ? ", " + i18n.tr("Error") : "")

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: theme.radiusMd
        // Same states as the cards: active tint, a step stronger while hovered
        color: row.active ? Qt.tint(theme.base, theme.tint(theme.accent, row.hovered ? theme.tintSubtle * 1.4 : theme.tintSubtle * 0.7))
             : row.hovered ? theme.hover
             : theme.base
        border.width: 1
        border.color: row.active ? theme.accent : theme.cardBorder
        Behavior on color { enabled: !row.recycling; ColorAnimation { duration: theme.motionFast } }

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
            width: Math.min(implicitWidth, controls.x - x - theme.space4)
            text: row.label
            color: row.active ? theme.text : theme.dimOn(surface.color)
            font.weight: row.active ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
        }
        Text {
            anchors.left: nameText.right
            anchors.leftMargin: theme.space5
            anchors.right: controls.left
            anchors.rightMargin: theme.space4
            anchors.verticalCenter: parent.verticalCenter
            text: row.categoryLabel
            color: theme.dimOn(surface.color)
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
            visible: width > theme.em * 3  // content-tuned: hidden when too narrow to be read
        }
        Row {
            id: controls
            anchors.right: parent.right
            anchors.rightMargin: theme.em * 0.5
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.space2
            Rectangle {  // start error: icon & text (same badge as the cards)
                visible: row.failed
                anchors.verticalCenter: parent.verticalCenter
                height: Math.round(theme.em * 1.5)
                width: failedRow.implicitWidth + theme.space5
                radius: height / 2
                color: theme.lossFill
                Row {
                    id: failedRow
                    anchors.centerIn: parent
                    spacing: theme.space2
                    Icon { glyph: ""; fallback: "!"; size: theme.em * 0.8; color: theme.inkOn(theme.lossFill); anchors.verticalCenter: parent.verticalCenter }  // warning
                    Text {
                        text: i18n.tr("Error")
                        color: theme.inkOn(theme.lossFill)
                        font.pointSize: theme.fontCaption
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea { id: failedArea; anchors.fill: parent; hoverEnabled: true }
                ToolTip.visible: failedArea.containsMouse
                ToolTip.text: i18n.tr("Overlay could not start, see log (Help menu)")
                ToolTip.delay: theme.tipDelay
            }
            TpButton {
                flat: true
                size: "sm"
                glyph: ""  // settings
                fallback: "⚙"
                tip: i18n.tr("Config")
                opacity: row.hovered || hovered || visualFocus || row.current ? 1 : 0.6
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
        ToolTip {
            id: previewTip
            visible: row.hovered && row.previewState === 1 && !row.menuOpen
                     && area.mouseX < controls.x - theme.em
            delay: 350
            x: Math.round(area.mouseX + theme.em)
            y: surface.height + 4
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
                radius: theme.radiusMd
                color: theme.stageBottom
                border.width: 1
                border.color: theme.border
            }
        }
    }

    FocusRing { target: surface; visible: row.current }
}
