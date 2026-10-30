import QtQuick
import QtQuick.Controls.Basic

// Round transport button of a player (replays, playback bars): glyph (rotated for backwards; fallback text without
// icon font), primary (play / pause: larger, accent fill), current (its command is the one running: accent tint &
// icon), caption on the glyph (slow: "½"). Tab reaches it, Space / Enter press it (taken from page shortcuts).
//   TpTransportButton { glyph: ""; fallback: "«"; tip: i18n.tr("Rewind"); current: replays.lastCommand === "VCRCOMMAND_REVERSESCAN"
//                       onClicked: replays.playback("VCRCOMMAND_REVERSESCAN") }
AbstractButton {
    id: control
    property string glyph: ""
    property string fallback: ""
    property real glyphRotation: 0
    property bool primary: false
    property bool current: false
    property string tip: ""
    property string caption: ""  // speed shown on glyph (slow: ½)

    Accessible.role: Accessible.Button
    Accessible.name: tip
    Accessible.checked: current
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    implicitWidth: Math.round(primary ? theme.em * 3.3 : theme.em * 2.6)
    implicitHeight: implicitWidth
    opacity: enabled ? 1 : theme.disabledOpacity
    scale: down ? 0.92 : 1
    Behavior on scale { NumberAnimation { duration: theme.motionFast } }
    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()
    Keys.onShortcutOverride: function(event) {  // focused: Space presses it (not the page play / pause)
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
            event.accepted = true
    }
    ToolTip.visible: tip !== "" && (hovered || visualFocus)
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    background: Rectangle {
        radius: width / 2
        color: control.primary ? (control.down ? theme.accentPressed : control.hovered ? theme.accentHover : theme.accentFill)
             : control.current ? theme.tint(theme.accent, "selected")
             : control.down ? theme.border : control.hovered ? theme.hover : "transparent"
        border.width: control.primary || control.current ? 0 : 1
        border.color: theme.border
        Behavior on color { ColorAnimation { duration: theme.motionFast } }
        FocusRing { visible: control.visualFocus }
    }
    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            glyph: control.glyph
            fallback: control.fallback
            rotation: iconShown ? control.glyphRotation : 0
            size: control.primary ? theme.em * 1.35 : theme.em
            color: control.primary ? theme.accentInk : control.current ? theme.accent : theme.text
        }
        Text {
            visible: control.caption !== ""
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: theme.space1 / 2
            text: control.caption
            textFormat: Text.PlainText
            color: control.current ? theme.accent : theme.dimText
            font.pointSize: theme.fontTiny
            font.weight: Font.Bold
        }
    }
}
