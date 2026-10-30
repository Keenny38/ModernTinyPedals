import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Tile of the Tools page: clickable section card with the tool icon (accent tile while the tool is on), name, live
// state (On / Off) of tools with a switch, mark of tools in the navigation bar, and what the tool is for.
// Click, Enter or Space opens the tool (opened signal of the card).
//   ToolTile { tool: modelData; status: backend.statuses[modelData.name] || ""; onOpened: backend.openTool(tool.path) }
TpSectionCard {
    id: tile
    required property var tool
    property string status: ""  // "on", "off", "" (page closed or no switch)

    clickable: true
    fillContent: false
    implicitWidth: theme.em * 16
    Layout.fillHeight: true  // tiles of a row as tall as the tallest
    Accessible.name: tool.label
    Accessible.description: tool.description + (status === "on" ? ", " + i18n.tr("Enabled") : status === "off" ? ", " + i18n.tr("Disabled") : "")

    RowLayout {
        Layout.fillWidth: true
        spacing: theme.space4
        TpIconTile {
            Layout.alignment: Qt.AlignTop
            glyph: tile.tool.glyph
            fallbackText: tile.tool.letter
            strong: tile.status === "on"
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: theme.space1
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                TpText {
                    Layout.fillWidth: true
                    role: "label"
                    font.weight: Font.DemiBold
                    text: tile.tool.label
                }
                Pill {
                    visible: tile.status !== ""
                    size: "sm"
                    dot: true
                    text: tile.status === "on" ? i18n.tr("Enabled") : i18n.tr("Disabled")
                    tint: tile.status === "on" ? theme.gain : theme.dimText
                }
                Icon {
                    visible: tile.tool.inRail
                    glyph: ""  // global navigation button
                    fallback: "≡"
                    size: theme.iconSm
                    color: theme.dimText
                    ToolTip.visible: railArea.containsMouse
                    ToolTip.text: i18n.tr("In the navigation bar")
                    ToolTip.delay: theme.tipDelay
                    MouseArea { id: railArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
            }
            TpText {
                id: descriptionText
                Layout.fillWidth: true
                visible: text !== ""
                role: "caption"
                color: theme.dimOn(tile.color)
                text: tile.tool.description
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                ToolTip.visible: tile.hovered && truncated
                ToolTip.text: tile.tool.description
                ToolTip.delay: theme.tipDelay
            }
        }
    }
}
