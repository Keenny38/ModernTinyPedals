import QtQuick
import QtQuick.Controls.Basic
import "../components"

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
    property bool recycling: false  // in reuse pool: no animation from the previous row's state
    signal menuRequested(Item item, real x, real y)

    GridView.onPooled: recycling = true
    GridView.onReused: recycling = false

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
        radius: theme.radiusLg
        // Hovered: hover surface in every state (enabled cards too)
        color: card.active ? Qt.tint(area.containsMouse ? theme.surfaceHover : theme.surfaceCard,
                                     theme.tint(theme.accent, "subtle"))
             : area.containsMouse ? theme.surfaceHover
             : theme.surfaceCard
        border.width: card.active || card.needed ? 1.5 : 1
        border.color: card.needed || card.failed || card.active ? card.edge
                    : area.containsMouse ? theme.strokeStrong
                    : theme.cardBorder
        Behavior on color { enabled: !card.recycling; ColorAnimation { duration: theme.motionBase } }
        Behavior on border.color { enabled: !card.recycling; ColorAnimation { duration: theme.motionBase } }

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
        TpIconTile {
            id: tile
            x: card.pad
            y: card.pad
            size: Math.round(theme.iconHero)
            glyph: card.glyph
            fallbackText: card.label
            tint: card.edge
            neutral: !card.active  // off: dim icon on a plain tile
        }

        // Name, state & update interval
        Column {
            id: heading
            anchors.left: tile.right
            anchors.leftMargin: theme.space4
            anchors.right: controls.left
            anchors.rightMargin: theme.space3
            anchors.verticalCenter: tile.verticalCenter
            spacing: 3
            Text {
                id: nameText
                width: parent.width
                text: card.label
                textFormat: Text.PlainText
                color: theme.text
                font.pointSize: theme.fontSubtitle
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Row {
                spacing: theme.space3
                Pill {
                    text: card.failed ? i18n.tr("Error") : card.running ? i18n.tr("Running") : i18n.tr("Disabled")
                    glyph: card.failed ? "" : card.running ? "" : ""  // warning, check mark
                    tint: card.failed ? theme.lossFill : card.running ? theme.gain : theme.dimText
                    solid: card.failed  // error badge as the overlays' (filled, warning icon)
                    fallback: card.failed ? "!" : ""
                    tip: card.failed ? i18n.tr("Module could not start, see log (Help menu)") : ""
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: card.interval > 0
                    text: card.interval + " ms"
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                    MouseArea {
                        id: intervalArea
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                    }
                    ToolTip.visible: intervalArea.containsMouse
                    ToolTip.text: intervalArea.containsMouse  // built only while hovered
                        ? i18n.trm("Updated every " + card.interval + " ms (" + card.idleInterval + " ms when not driving)") : ""
                    ToolTip.delay: theme.tipDelay
                }
            }
        }

        Row {
            id: controls
            anchors.right: parent.right
            anchors.rightMargin: card.pad - theme.em * 0.2
            anchors.verticalCenter: tile.verticalCenter
            spacing: theme.space1
            TpButton {
                flat: true
                glyph: ""  // settings
                fallback: "⚙"
                tip: i18n.tr("Options…")
                size: "sm"
                focusPolicy: Qt.NoFocus  // card keys: Enter opens settings (no Tab stop per card)
                anchors.verticalCenter: parent.verticalCenter
                onClicked: backend.openConfig(card.key)
                Accessible.name: i18n.tr("Options…")
            }
            TpSwitch {
                checkable: false  // follows model: switched by backend
                checked: card.active
                tip: i18n.tr("Enable / Disable")
                implicitWidth: theme.em * 2.6
                focusPolicy: Qt.NoFocus  // card keys: Space switches the current card
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
            anchors.topMargin: theme.space4
            text: card.description
            textFormat: Text.PlainText
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
            ToolTip.delay: theme.tipDelay
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
            spacing: theme.space3
            visible: usersLabel.text !== ""
            readonly property bool warn: card.needed || card.needs.length > 0
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                glyph: usersRow.warn ? "" : ""  // warning, layers
                fallback: usersRow.warn ? "!" : ""
                size: theme.iconSm
                color: usersRow.warn ? theme.warning : theme.dimText
            }
            Text {
                id: usersLabel
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, usersRow.width - theme.em * 1.3)
                text: card.usersText()
                textFormat: Text.PlainText
                color: usersRow.warn ? theme.warning : theme.dimText
                font.pointSize: theme.fontSmall
                font.weight: usersRow.warn ? Font.DemiBold : Font.Normal
                elide: Text.ElideRight
                MouseArea {
                    id: usersArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }
                readonly property string tip: usersArea.containsMouse ? card.usersTip() : ""  // built only while hovered
                ToolTip.visible: tip !== ""
                ToolTip.text: tip
                ToolTip.delay: theme.tipDelay
            }
        }
    }

    // Keyboard focus ring
    FocusRing { target: surface; visible: card.current }
}
