import QtQuick
import QtQuick.Controls.Basic

// Module card of Modules page: icon, name, state & update interval, what the module computes, overlays & modules
// using its data (warning when it is off but enabled ones need it), settings & on/off switch.
// Click opens settings, right-click the menu.
Item {
    id: card
    required property int index
    required property string key
    required property string label
    required property string description
    required property string glyph
    required property bool active
    required property bool running
    required property bool failed
    required property int interval
    required property int idleInterval
    required property var users  // labels of enabled overlays using its data
    required property int userCount
    required property int userTotal  // overlays using its data, enabled or not
    required property var moduleUsers  // labels of enabled modules using its data
    required property var needs  // labels of modules it needs that are off
    required property bool needed
    required property var resets
    readonly property bool current: GridView.isCurrentItem && GridView.view.activeFocus
    readonly property real pad: Math.round(theme.em * 0.75)
    readonly property color edge: card.needed ? theme.warning : card.failed ? theme.loss : theme.accent
    signal menuRequested(Item item, real x, real y)

    width: GridView.view.cellWidth
    height: GridView.view.cellHeight

    Accessible.role: Accessible.ListItem
    Accessible.name: label + ", " + (active ? i18n.tr("Enabled") : i18n.tr("Disabled")) + ", " + description

    function usersText() {
        if (card.needed)
            return card.userCount === 1 ? i18n.tr("Needed by 1 enabled overlay")
                 : card.userCount > 1 ? i18n.trm("Needed by " + card.userCount + " enabled overlays")
                 : i18n.trm("Needed by modules: " + card.moduleUsers.join(", "))
        if (card.needs.length > 0)
            return i18n.trm("Needs " + card.needs.join(", ") + " (off)")
        if (card.userCount > 0)
            return card.userCount === 1 ? i18n.tr("1 enabled overlay uses it")
                 : i18n.trm(card.userCount + " enabled overlays use it")
        if (card.userTotal > 0)
            return card.userTotal === 1 ? i18n.tr("Used by 1 overlay, not enabled")
                 : i18n.trm("Used by " + card.userTotal + " overlays, none enabled")
        if (card.moduleUsers.length > 0)
            return i18n.trm("Used by modules: " + card.moduleUsers.join(", "))
        return ""
    }
    function usersTip() {
        var lines = []
        if (card.users.length > 0)
            lines.push(i18n.tr("Enabled overlays using it:") + " " + card.users.join(", "))
        if (card.moduleUsers.length > 0)
            lines.push(i18n.tr("Modules using it:") + " " + card.moduleUsers.join(", "))
        return lines.join("\n")
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.margins: Math.round(theme.em * 0.3)
        radius: theme.em * 0.7
        color: card.active ? Qt.tint(theme.base, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.06))
             : area.containsMouse ? (theme.dark ? Qt.lighter(theme.base, 1.12) : Qt.darker(theme.base, 1.02))
             : theme.base
        border.width: card.active || card.needed ? 1.5 : 1
        border.color: card.needed || card.failed || card.active ? card.edge
                    : area.containsMouse ? Qt.lighter(theme.border, 1.3)
                    : theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border
        Behavior on color { ColorAnimation { duration: 150 } }
        Behavior on border.color { ColorAnimation { duration: 150 } }

        // Card background click (buttons above get their own clicks)
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onClicked: function(mouse) {
                card.GridView.view.currentIndex = card.index
                if (mouse.button === Qt.RightButton)
                    card.menuRequested(area, mouse.x, mouse.y)
                else
                    backend.openConfig(card.key)
            }
        }

        // Icon tile
        Rectangle {
            id: tile
            x: card.pad
            y: card.pad
            width: Math.round(theme.em * 2.7)
            height: width
            radius: theme.em * 0.6
            color: card.active ? Qt.rgba(card.edge.r, card.edge.g, card.edge.b, theme.dark ? 0.22 : 0.14)
                 : theme.dark ? Qt.lighter(theme.base, 1.25) : Qt.darker(theme.base, 1.05)
            Behavior on color { ColorAnimation { duration: 150 } }
            Icon {
                anchors.centerIn: parent
                glyph: card.glyph
                size: theme.em * 1.3
                color: card.active ? card.edge : theme.dimText
                Behavior on color { ColorAnimation { duration: 150 } }
            }
            Text {  // no icon font: first letter
                anchors.centerIn: parent
                visible: theme.iconFont === ""
                text: card.label.charAt(0)
                font.pointSize: theme.fontPoint * 1.3
                font.weight: Font.DemiBold
                color: card.active ? card.edge : theme.dimText
            }
        }

        // Name, state & update interval
        Column {
            id: heading
            anchors.left: tile.right
            anchors.leftMargin: theme.em * 0.6
            anchors.right: controls.left
            anchors.rightMargin: theme.em * 0.4
            anchors.verticalCenter: tile.verticalCenter
            spacing: 3
            Text {
                id: nameText
                width: parent.width
                text: card.label
                color: theme.text
                font.pointSize: theme.fontPoint * 1.08
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Row {
                spacing: theme.em * 0.4
                Pill {
                    text: card.failed ? i18n.tr("Error") : card.running ? i18n.tr("Running") : i18n.tr("Disabled")
                    glyph: card.failed ? "" : card.running ? "" : ""  // warning, check mark
                    tint: card.failed ? theme.loss : card.running ? theme.gain : theme.dimText
                    tip: card.failed ? i18n.tr("Module could not start, see log (Help menu)") : ""
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: card.interval > 0
                    text: card.interval + " ms"
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.82
                    font.features: { "tnum": 1 }
                    MouseArea {
                        id: intervalArea
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                    }
                    ToolTip.visible: intervalArea.containsMouse
                    ToolTip.text: i18n.trm("Updated every " + card.interval + " ms (" + card.idleInterval + " ms when not driving)")
                    ToolTip.delay: 400
                }
            }
        }

        Row {
            id: controls
            anchors.right: parent.right
            anchors.rightMargin: card.pad - theme.em * 0.2
            anchors.verticalCenter: tile.verticalCenter
            spacing: theme.em * 0.15
            TpButton {
                flat: true
                glyph: ""  // settings
                text: theme.iconFont === "" ? "⚙" : ""
                tip: i18n.tr("Config")
                implicitHeight: Math.round(theme.em * 2)
                opacity: area.containsMouse || hovered || card.current ? 1 : 0.55
                anchors.verticalCenter: parent.verticalCenter
                onClicked: backend.openConfig(card.key)
                Accessible.name: i18n.tr("Config")
            }
            TpSwitch {
                checkable: false  // follows model: switched by backend
                checked: card.active
                tip: i18n.tr("Enable / Disable")
                implicitWidth: theme.em * 2.6
                anchors.verticalCenter: parent.verticalCenter
                onClicked: {
                    card.GridView.view.currentIndex = card.index
                    backend.toggle(card.key)
                }
                Accessible.role: Accessible.CheckBox
                Accessible.name: card.label
                Accessible.checked: card.active
            }
        }

        // What it computes
        Text {
            id: descriptionText
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: tile.bottom
            anchors.leftMargin: card.pad
            anchors.rightMargin: card.pad
            anchors.topMargin: theme.em * 0.55
            text: card.description
            color: theme.dimText
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            lineHeight: 1.1
            MouseArea {
                id: descriptionArea
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton  // clicks go to card
            }
            ToolTip.visible: truncated && descriptionArea.containsMouse
            ToolTip.text: card.description
            ToolTip.delay: 500
        }

        // Overlays & modules using its data
        Row {
            id: usersRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: card.pad
            anchors.rightMargin: card.pad
            anchors.bottomMargin: card.pad - theme.em * 0.15
            spacing: theme.em * 0.35
            visible: usersLabel.text !== ""
            readonly property bool warn: card.needed || card.needs.length > 0
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                glyph: usersRow.warn ? "" : ""  // warning, layers
                size: theme.em * 0.85
                color: usersRow.warn ? theme.warning : theme.dimText
            }
            Text {
                id: usersLabel
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, usersRow.width - theme.em * 1.3)
                text: card.usersText()
                color: usersRow.warn ? theme.warning : theme.dimText
                font.pointSize: theme.fontPoint * 0.88
                font.weight: usersRow.warn ? Font.DemiBold : Font.Normal
                elide: Text.ElideRight
                MouseArea {
                    id: usersArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }
                ToolTip.visible: usersArea.containsMouse && card.usersTip() !== ""
                ToolTip.text: card.usersTip()
                ToolTip.delay: 300
            }
        }
    }

    // Keyboard focus ring
    Rectangle {
        anchors.fill: surface
        anchors.margins: -3
        radius: surface.radius + 3
        color: "transparent"
        border.width: 2
        border.color: theme.accent
        visible: card.current
    }
}
