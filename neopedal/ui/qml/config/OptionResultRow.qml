import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Result row of Find Option page: group icon, option name (searched words in bold), overlay or section,
// current value (on / off switch, color, text) & changed-from-default dot. Click opens the option; more actions
// with "⋯", right click or Menu key (as the option rows of Settings & Overlay Options).
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
    property bool recycling: false  // in reuse pool: no animation from the previous row's state
    signal menuRequested(Item item, real x, real y)

    ListView.onPooled: {
        recycling = true
        opacity = 1  // add transition cut short by pooling: not reused faded
    }
    ListView.onReused: recycling = false

    width: ListView.view ? ListView.view.width - theme.em * 0.7 : 0  // room for scroll bar
    height: Math.round(theme.rowTall)

    Accessible.role: Accessible.ListItem
    Accessible.name: sectionLabel + ", " + label.replace(/<[^>]*>/g, "") + ", " + value

    TpListRow {
        id: surface
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        card: true
        hovered: area.containsMouse
        animate: !row.recycling

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

        TpIconTile {
            id: badge
            x: theme.em * 0.55
            anchors.verticalCenter: parent.verticalCenter
            size: Math.round(theme.em * 2)
            glyph: row.glyph
            fallbackText: row.groupLabel
        }

        Column {
            anchors.left: badge.right
            anchors.leftMargin: theme.padCard
            anchors.right: valueBox.left
            anchors.rightMargin: theme.space4
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
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
            }
        }

        Row {
            id: valueBox
            anchors.right: moreButton.left
            anchors.rightMargin: theme.space3
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.5
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
                ToolTip.delay: theme.tipDelay
            }
            TpSwitch {
                visible: row.kind === "bool"
                checkable: false  // follows saved value
                checked: row.checked
                implicitWidth: theme.em * 2.6
                focusPolicy: Qt.NoFocus  // list keys: Space switches the current row (no Tab stop per row)
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
                radius: theme.radiusSm
                color: row.color !== "" ? row.color : "transparent"
                border.width: 1
                border.color: theme.border
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: row.kind !== "bool" && row.value !== ""
                width: Math.min(implicitWidth, row.width * 0.3)
                text: row.value
                textFormat: Text.PlainText
                color: theme.dimText
                elide: Text.ElideMiddle
                font.features: { "tnum": 1 }
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        TpButton {
            id: moreButton
            anchors.right: chevron.left
            anchors.rightMargin: theme.space1
            anchors.verticalCenter: parent.verticalCenter
            flat: true
            size: "sm"
            glyph: theme.glyphs.more
            fallback: "⋯"
            tip: i18n.tr("More actions")
            focusPolicy: Qt.NoFocus  // list keys: Menu key opens it for the current row (no Tab stop per row)
            opacity: hovered || area.containsMouse || row.current ? 1 : 0  // revealed: hover, focus, current
            onClicked: {
                row.ListView.view.currentIndex = row.index
                row.menuRequested(moreButton, 0, moreButton.height)
            }
        }
        Icon {
            id: chevron
            anchors.right: parent.right
            anchors.rightMargin: theme.space4
            anchors.verticalCenter: parent.verticalCenter
            glyph: ""  // chevron right
            fallback: "›"
            size: theme.iconXs
            color: area.containsMouse || row.current ? theme.dimText : theme.border  // shown on hover / focus
        }

        ToolTip.visible: area.containsMouse && row.help !== "" && area.mouseX < valueBox.x
        ToolTip.text: row.help
        ToolTip.delay: theme.tipDelay
    }

    FocusRing { target: surface; visible: row.current }
}
