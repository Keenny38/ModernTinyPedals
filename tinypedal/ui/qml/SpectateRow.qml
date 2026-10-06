import QtQuick
import QtQuick.Controls.Basic

// Driver row of Spectate page: place, class color, driver & car, best lap, pit state. Spectated driver
// is tinted with an eye mark. Click (or Enter) spectates the driver.
Item {
    id: row
    required property int index
    required property int slot
    required property int place
    required property string name
    required property string vehicle
    required property string carClass
    required property string classColor
    required property string bestLap
    required property string lastLap
    required property string status
    required property bool player
    required property bool spectated
    required property string brandLogo
    readonly property bool current: ListView.isCurrentItem && ListView.view.activeFocus
    readonly property bool wide: width > theme.em * 34
    signal picked(int slot)

    width: ListView.view ? ListView.view.width - theme.em * 0.7 : 0  // room for scroll bar
    height: Math.round(theme.em * 2.7)

    Accessible.role: Accessible.ListItem
    Accessible.name: place + ", " + name + ", " + vehicle + (spectated ? ", " + i18n.tr("Spectating") : "")

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: theme.em * 0.5
        color: row.spectated ? Qt.tint(theme.base, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.14))
             : area.containsMouse ? theme.hover : theme.base
        border.width: 1
        border.color: row.spectated ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.8)
                    : theme.dark ? Qt.lighter(theme.base, 1.3) : theme.border
        Behavior on color { ColorAnimation { duration: 150 } }
        Behavior on border.color { ColorAnimation { duration: 150 } }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                row.ListView.view.currentIndex = row.index
                row.picked(row.slot)
            }
        }

        // Class color strip
        Rectangle {
            x: theme.em * 0.35
            width: Math.round(theme.em * 0.28)
            height: parent.height - theme.em * 0.8
            anchors.verticalCenter: parent.verticalCenter
            radius: width / 2
            color: row.classColor
        }
        Text {
            id: placeText
            x: theme.em * 0.9
            width: theme.em * 2
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            text: row.place > 0 ? row.place : "-"
            color: row.spectated ? theme.accent : theme.dimText
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
        }
        Item {  // car brand logo of game, same room on every row
            id: logoBox
            anchors.left: placeText.right
            anchors.leftMargin: theme.em * 0.6
            anchors.verticalCenter: parent.verticalCenter
            width: theme.em * 2.4
            height: theme.em * 1.4
            GameLogo {
                anchors.centerIn: parent
                source: row.brandLogo
                boxWidth: theme.em * 2.4
                boxHeight: theme.em * 1.4
            }
        }
        Column {
            anchors.left: logoBox.right
            anchors.leftMargin: theme.em * 0.6
            anchors.right: details.left
            anchors.rightMargin: theme.em * 0.6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            Row {
                width: parent.width
                spacing: theme.em * 0.4
                Text {
                    id: nameText
                    width: Math.min(implicitWidth, parent.width - (youPill.visible ? youPill.width + theme.em * 0.4 : 0))
                    text: row.name
                    color: theme.text
                    font.weight: row.spectated ? Font.DemiBold : Font.Medium
                    elide: Text.ElideRight
                }
                Pill {
                    id: youPill
                    visible: row.player
                    text: i18n.tr("You")
                    anchors.verticalCenter: nameText.verticalCenter
                }
            }
            Text {
                width: parent.width
                text: row.wide ? row.vehicle : [row.carClass, row.vehicle].filter(function(part) { return part !== "" }).join(" · ")
                visible: text !== ""
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                elide: Text.ElideRight
            }
        }

        Row {
            id: details
            anchors.right: parent.right
            anchors.rightMargin: theme.em * 0.7
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.7
            Row {
                visible: row.wide && row.carClass !== ""
                spacing: theme.em * 0.35
                anchors.verticalCenter: parent.verticalCenter
                width: theme.em * 7
                Rectangle {
                    width: Math.round(theme.em * 0.55)
                    height: width
                    radius: width / 2
                    color: row.classColor
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    width: parent.width - theme.em
                    text: row.carClass
                    color: theme.dimText
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            Item {  // fixed room: columns stay aligned
                width: theme.em * 4.6
                height: statusPill.height
                anchors.verticalCenter: parent.verticalCenter
                Pill {
                    id: statusPill
                    visible: row.status !== ""
                    anchors.right: parent.right
                    text: row.status === "garage" ? i18n.tr("Garage") : i18n.tr("Pit")
                    tint: row.status === "garage" ? theme.dimText : theme.warning
                }
            }
            Text {
                visible: row.wide || row.bestLap !== ""
                width: theme.em * 5
                horizontalAlignment: Text.AlignRight
                text: row.bestLap !== "" ? row.bestLap : "-"
                color: row.bestLap !== "" ? theme.text : theme.dimText
                font.features: { "tnum": 1 }
                anchors.verticalCenter: parent.verticalCenter
                MouseArea { id: lapArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                ToolTip.visible: lapArea.containsMouse
                ToolTip.text: i18n.tr("Best Lap") + (row.lastLap !== "" ? "  ·  " + i18n.tr("Last lap") + " " + row.lastLap : "")
                ToolTip.delay: 500
            }
            Item {
                width: theme.em * 1.3
                height: width
                anchors.verticalCenter: parent.verticalCenter
                Icon {
                    anchors.centerIn: parent
                    glyph: ""  // view
                    color: theme.accent
                    opacity: row.spectated ? 1 : area.containsMouse ? 0.35 : 0
                    Behavior on opacity { NumberAnimation { duration: 150 } }
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
