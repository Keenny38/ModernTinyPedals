import QtQuick
import QtQuick.Controls.Basic

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
    signal menuRequested(Item item, real x, real y)

    width: GridView.view.cellWidth
    height: GridView.view.cellHeight

    Accessible.role: Accessible.ListItem
    Accessible.name: label + ", " + categoryLabel + ", " + (active ? i18n.tr("Enabled") : i18n.tr("Disabled"))

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: theme.em * 0.5
        color: area.containsMouse ? theme.hover
             : row.active ? Qt.tint(theme.base, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.07))
             : theme.base
        border.width: 1
        border.color: row.active ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.7)
                    : theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border
        Behavior on color { ColorAnimation { duration: 120 } }

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

        Rectangle {
            id: dot
            x: theme.em * 0.8
            anchors.verticalCenter: parent.verticalCenter
            width: Math.round(theme.em * 0.55)
            height: width
            radius: width / 2
            color: row.categoryColor
        }
        Text {
            id: nameText
            anchors.left: dot.right
            anchors.leftMargin: theme.em * 0.6
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, controls.x - x - theme.em * 0.6)
            text: row.label
            color: row.active ? theme.text : Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.72)
            font.weight: row.active ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
        }
        Text {
            anchors.left: nameText.right
            anchors.leftMargin: theme.em * 0.8
            anchors.right: controls.left
            anchors.rightMargin: theme.em * 0.6
            anchors.verticalCenter: parent.verticalCenter
            text: row.categoryLabel
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.85
            elide: Text.ElideRight
            visible: width > theme.em * 3
        }
        Row {
            id: controls
            anchors.right: parent.right
            anchors.rightMargin: theme.em * 0.5
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.25
            Rectangle {
                visible: row.failed
                anchors.verticalCenter: parent.verticalCenter
                height: Math.round(theme.em * 1.5)
                width: failedText.implicitWidth + theme.em * 0.9
                radius: height / 2
                color: Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.92)
                Text {
                    id: failedText
                    anchors.centerIn: parent
                    text: i18n.tr("Error")
                    color: "white"
                    font.pointSize: theme.fontPoint * 0.8
                    font.weight: Font.DemiBold
                }
                MouseArea { id: failedArea; anchors.fill: parent; hoverEnabled: true }
                ToolTip.visible: failedArea.containsMouse
                ToolTip.text: i18n.tr("Overlay could not start, see log (Help menu)")
                ToolTip.delay: 300
            }
            TpButton {
                flat: true
                glyph: ""  // settings
                text: theme.iconFont === "" ? "⚙" : ""
                tip: i18n.tr("Config")
                implicitHeight: Math.round(theme.em * 1.9)
                opacity: area.containsMouse || hovered || row.current ? 1 : 0.6
                anchors.verticalCenter: parent.verticalCenter
                onClicked: backend.openConfig(row.name)
                Accessible.name: i18n.tr("Config")
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
            visible: area.containsMouse && row.previewState === 1 && !row.menuOpen
                     && area.mouseX < controls.x - theme.em
            delay: 350
            x: Math.round(area.mouseX + theme.em)
            y: surface.height + 4
            padding: Math.round(theme.em * 0.4)
            readonly property real fit: Math.min(1, theme.em * 30 / Math.max(row.previewWidth, 1),
                                                 theme.em * 20 / Math.max(row.previewHeight, 1))
            contentItem: Image {
                source: previewTip.visible ? row.preview : ""
                width: Math.round(row.previewWidth * previewTip.fit)
                height: Math.round(row.previewHeight * previewTip.fit)
                cache: false
                smooth: true
                mipmap: true
            }
            background: Rectangle {
                radius: theme.em * 0.5
                color: "#14171C"
                border.width: 1
                border.color: theme.border
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
