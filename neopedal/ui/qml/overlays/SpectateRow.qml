import QtQuick
import QtQuick.Controls.Basic
import "../components"

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
    required property string classAlias
    required property string bestLap
    required property string lastLap
    required property string status
    required property bool player
    required property bool spectated
    required property string brandLogo
    readonly property bool current: ListView.isCurrentItem && ListView.view.activeFocus
    readonly property bool wide: width > theme.em * 34  // content-tuned: row width (not page) fits class & best lap columns
    property bool recycling: false  // in reuse pool: no animation from the previous row's state
    signal picked(int slot)

    ListView.onPooled: recycling = true
    ListView.onReused: recycling = false

    width: ListView.view ? ListView.view.width - theme.em * 0.7 : 0  // room for scroll bar
    height: Math.round(theme.row)

    Accessible.role: Accessible.ListItem
    Accessible.name: place + ", " + name + ", " + vehicle + (spectated ? ", " + i18n.tr("Spectating") : "")

    TpListRow {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        // Spectated row stays tinted while hovered (on the hovered surface): both states shown
        card: true
        hovered: area.containsMouse
        selected: row.spectated
        animate: !row.recycling

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
        TpClassStrip {
            x: theme.em * 0.35
            height: parent.height - theme.em * 0.8
            anchors.verticalCenter: parent.verticalCenter
            tint: row.classColor
        }
        Text {
            id: placeText
            x: theme.em * 0.9
            width: theme.em * 2
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            text: row.place > 0 ? row.place : "-"
            textFormat: Text.PlainText
            color: row.spectated ? theme.accent : theme.dimOn(surface.color)
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
        }
        Item {  // car brand logo of game, same room on every row
            id: logoBox
            anchors.left: placeText.right
            anchors.leftMargin: theme.space4
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
            anchors.leftMargin: theme.space4
            anchors.right: details.left
            anchors.rightMargin: theme.space4
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            Row {
                width: parent.width
                spacing: theme.space3
                Text {
                    id: nameText
                    width: Math.min(implicitWidth, parent.width - (youPill.visible ? youPill.width + theme.space3 : 0))
                    text: row.name
                    textFormat: Text.PlainText
                    color: theme.text
                    font.weight: row.spectated ? Font.DemiBold : Font.Medium
                    elide: Text.ElideRight
                }
                Pill {
                    id: youPill
                    visible: row.player
                    text: i18n.tr("You")
                    size: "sm"
                    anchors.verticalCenter: nameText.verticalCenter
                }
            }
            Text {
                width: parent.width
                text: row.wide ? row.vehicle : [row.carClass, row.vehicle].filter(function(part) { return part !== "" }).join(" · ")
                textFormat: Text.PlainText
                visible: text !== ""
                color: theme.dimOn(surface.color)
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
            }
        }

        Row {
            id: details
            anchors.right: parent.right
            anchors.rightMargin: theme.padCard
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.padCard
            Row {
                visible: row.wide && row.carClass !== ""
                spacing: theme.space3
                anchors.verticalCenter: parent.verticalCenter
                width: theme.em * 7
                TpClassBadge {  // as overlays: class alias on class color
                    label: row.classAlias
                    fullName: row.carClass
                    fill: row.classColor
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
                textFormat: Text.PlainText
                color: row.bestLap !== "" ? theme.text : theme.dimOn(surface.color)
                font.features: { "tnum": 1 }
                anchors.verticalCenter: parent.verticalCenter
                MouseArea { id: lapArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                ToolTip.visible: lapArea.containsMouse
                ToolTip.text: lapArea.containsMouse  // text built only while hovered, not on each lap for every row
                    ? i18n.tr("Best Lap") + (row.lastLap !== "" ? "  ·  " + i18n.tr("Last lap") + " " + row.lastLap : "") : ""
                ToolTip.delay: theme.tipDelay
            }
            Item {
                width: theme.em * 1.3
                height: width
                anchors.verticalCenter: parent.verticalCenter
                Icon {  // spectated: eye (or a ring without icon font), shape on top of the tint
                    anchors.centerIn: parent
                    glyph: ""  // view
                    fallback: "◉"
                    color: row.spectated ? theme.accent : theme.dimOn(surface.color)  // hovered: hint in dim text
                    opacity: row.spectated || area.containsMouse ? 1 : 0
                    Behavior on opacity { enabled: !row.recycling; NumberAnimation { duration: theme.motionBase } }
                }
            }
        }
    }

    FocusRing { target: surface; visible: row.current }
}
