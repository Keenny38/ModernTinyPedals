import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Key figure tile: tint strip, icon & title, large value, detail line, optional level letter & share bar.
// warning: value out of range, told by color AND a warning icon (never by color alone).
//   TpStatTile { title: i18n.tr("Fuel"); value: "42.1 L"; detail: ...; glyph: ""; tint: theme.seriesFuel }
Card {
    id: tile
    property string title: ""
    property string value: "—"  // missing value: em dash on every page (MISSING)
    property string detail: ""
    property string tip: ""
    property string glyph: ""
    property color tint: theme.accent
    property var valueColor: null  // value color (level), else text (dim when empty)
    property bool warning: false
    property string letter: ""  // level told without color: badge before value
    property real ratio: -1  // share bar 0..1 under the detail, -1: none (room kept when barSpace)
    property bool barSpace: false  // keep the bar height even without bar: same height as tiles with one
    property bool animateValue: false  // brief fade in when the value changes
    readonly property bool empty: value === "" || value === "—" || value === "-"
    readonly property color stripColor: warning ? theme.loss : tint
    readonly property real strip: Math.max(2, Math.round(theme.em * 0.25))

    implicitHeight: column.implicitHeight + theme.em * 1.3
    Layout.fillWidth: true
    Layout.preferredWidth: theme.em * 10
    Layout.minimumWidth: theme.em * 7

    Accessible.role: Accessible.StaticText
    Accessible.name: title + ": " + value + (detail !== "" ? ", " + detail : "") + (warning ? ", " + i18n.tr("Warning") : "")

    Rectangle {  // tint strip
        width: tile.strip
        radius: width / 2
        height: parent.height - theme.em * 1.3
        x: theme.em * 0.35
        anchors.verticalCenter: parent.verticalCenter
        color: tile.stripColor
        opacity: tile.empty ? 0.35 : 0.9
        Behavior on color { ColorAnimation { duration: theme.motionBase } }
    }

    ColumnLayout {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        anchors.leftMargin: theme.em * 0.9
        anchors.rightMargin: theme.padCard
        anchors.topMargin: theme.padCard
        spacing: 1
        RowLayout {
            spacing: theme.space3
            Layout.fillWidth: true
            Icon { glyph: tile.glyph; size: theme.iconSm; color: tile.stripColor }
            Text {
                text: tile.title
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
        RowLayout {
            spacing: theme.space3
            Layout.fillWidth: true
            Rectangle {  // level letter: level told without color
                visible: tile.letter !== ""
                Layout.preferredWidth: theme.em * 1.45
                Layout.preferredHeight: theme.em * 1.45
                radius: width / 2
                color: tile.tint
                Behavior on color { ColorAnimation { duration: theme.motionSlow } }
                Text {
                    anchors.centerIn: parent
                    text: tile.letter
                    textFormat: Text.PlainText
                    color: theme.inkOn(tile.tint)  // readable on level color
                    font.pointSize: theme.fontSmall
                    font.weight: Font.Bold
                }
            }
            Icon {  // out of range: shape, not only color
                visible: tile.warning
                glyph: ""  // warning
                fallback: "!"
                color: theme.loss
                size: theme.iconMd
            }
            Text {
                id: valueText
                text: tile.value !== "" ? tile.value : "—"
                textFormat: Text.PlainText
                color: tile.warning ? theme.loss : tile.valueColor ? tile.valueColor : tile.empty ? theme.dimText : theme.text
                font.pointSize: theme.fontTitle
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                elide: Text.ElideRight
                Layout.fillWidth: true
                Behavior on color { ColorAnimation { duration: theme.motionBase } }
                onTextChanged: if (tile.animateValue) valueFade.restart()
                NumberAnimation { id: valueFade; target: valueText; property: "opacity"; from: 0.25; to: 1; duration: theme.motionSlow }
            }
        }
        Text {
            text: tile.detail !== "" ? tile.detail : " "
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        TpMeter {  // share bar (valid laps...)
            visible: tile.ratio >= 0 || tile.barSpace
            opacity: tile.ratio >= 0 ? 1 : 0
            Layout.fillWidth: true
            Layout.topMargin: theme.space1
            value: Math.max(0, tile.ratio)
            tint: tile.tint
            name: tile.title
        }
    }

    HoverHandler { id: hover; enabled: tile.tip !== "" }
    ToolTip.visible: hover.hovered
    ToolTip.text: tile.tip
    ToolTip.delay: theme.tipDelay
}
