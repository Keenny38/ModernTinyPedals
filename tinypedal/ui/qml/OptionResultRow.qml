import QtQuick
import QtQuick.Controls.Basic

// Result row of Find Option page: group icon, option name (searched words in bold), overlay or section,
// current value (on / off switch, color, text) & changed-from-default dot. Click opens the option.
Item {
    id: row
    required property int index
    required property string key
    required property string label
    required property string sectionLabel
    required property string groupLabel
    required property string glyph
    required property string kind
    required property string value
    required property string color
    required property bool checked
    required property bool modified
    required property string help
    readonly property bool current: ListView.isCurrentItem && ListView.view.activeFocus
    signal menuRequested(Item item, real x, real y)

    width: ListView.view ? ListView.view.width - theme.em * 0.7 : 0  // room for scroll bar
    height: Math.round(theme.em * 3.1)

    Accessible.role: Accessible.ListItem
    Accessible.name: sectionLabel + ", " + label.replace(/<[^>]*>/g, "") + ", " + value

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: theme.em * 0.5
        color: area.containsMouse ? theme.hover : theme.base
        border.width: 1
        border.color: theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border
        Behavior on color { ColorAnimation { duration: 120 } }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onClicked: function(mouse) {
                row.ListView.view.currentIndex = row.index
                if (mouse.button === Qt.RightButton)
                    row.menuRequested(area, mouse.x, mouse.y)
                else
                    backend.openOption(row.key)
            }
        }

        Rectangle {
            id: badge
            x: theme.em * 0.55
            anchors.verticalCenter: parent.verticalCenter
            width: Math.round(theme.em * 2)
            height: width
            radius: theme.em * 0.45
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.16 : 0.1)
            Icon {
                anchors.centerIn: parent
                glyph: row.glyph
                size: theme.em * 0.95
                color: theme.accent
            }
            Text {
                anchors.centerIn: parent
                visible: theme.iconFont === ""
                text: row.groupLabel.charAt(0)
                color: theme.accent
                font.weight: Font.DemiBold
            }
        }

        Column {
            anchors.left: badge.right
            anchors.leftMargin: theme.em * 0.65
            anchors.right: valueBox.left
            anchors.rightMargin: theme.em * 0.6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Text {
                width: parent.width
                text: row.label
                textFormat: Text.StyledText
                color: theme.text
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: row.sectionLabel + "  ·  " + row.groupLabel
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                elide: Text.ElideRight
            }
        }

        Row {
            id: valueBox
            anchors.right: chevron.left
            anchors.rightMargin: theme.em * 0.4
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.45
            Rectangle {
                visible: row.modified
                width: Math.round(theme.em * 0.5)
                height: width
                radius: width / 2
                color: theme.accent
                anchors.verticalCenter: parent.verticalCenter
                MouseArea { id: dotArea; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                ToolTip.visible: dotArea.containsMouse
                ToolTip.text: i18n.tr("Changed from default")
                ToolTip.delay: 300
            }
            TpSwitch {
                visible: row.kind === "bool"
                checkable: false  // follows saved value
                checked: row.checked
                implicitWidth: theme.em * 2.6
                tip: i18n.tr("Switch on / off now (saved & applied)")
                anchors.verticalCenter: parent.verticalCenter
                onClicked: {
                    row.ListView.view.currentIndex = row.index
                    backend.toggle(row.key)
                }
                Accessible.role: Accessible.CheckBox
                Accessible.name: row.label.replace(/<[^>]*>/g, "")
                Accessible.checked: row.checked
            }
            Rectangle {
                visible: row.kind === "color" && row.color !== ""
                width: Math.round(theme.em * 1.2)
                height: width
                radius: theme.em * 0.3
                color: row.color !== "" ? row.color : "transparent"
                border.width: 1
                border.color: theme.border
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: row.kind !== "bool" && row.value !== ""
                width: Math.min(implicitWidth, row.width * 0.3)
                text: row.value
                color: theme.dimText
                elide: Text.ElideMiddle
                font.features: { "tnum": 1 }
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Icon {
            id: chevron
            anchors.right: parent.right
            anchors.rightMargin: theme.em * 0.6
            anchors.verticalCenter: parent.verticalCenter
            glyph: ""  // chevron right
            size: theme.em * 0.75
            color: theme.dimText
            opacity: area.containsMouse || row.current ? 1 : 0.4
        }

        ToolTip.visible: area.containsMouse && row.help !== "" && area.mouseX < valueBox.x
        ToolTip.text: row.help
        ToolTip.delay: 700
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
