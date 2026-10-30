import QtQuick
import QtQuick.Controls.Basic

// Rounded button: icon glyph and/or text, flat (toolbar) or accent (primary) look.
// size: "md" (default), "sm" (compact toolbars, buttons inside rows), "xs" (inside chips & tags).
// Without icon font (Linux...), an icon only button shows its fallback text, else its tooltip (cut).
// Long texts are cut with "...", the full text is then in the tooltip.
// Disabled: still hovered (Qt 6 Controls), its tooltip tells why (disabledTip, else tip).
// shortcut: key of the action shown in the tooltip ("Ctrl+S"), the button does not bind it.
AbstractButton {
    id: control
    property string glyph: ""
    property string fallback: ""  // short text shown instead of the glyph without icon font: "+", "▶", "✕"
    property bool flat: false
    property bool accent: false
    property bool danger: false  // accent look in red: delete, remove
    property string tip: ""
    property string disabledTip: ""  // why the button is disabled (tooltip while disabled), else tip
    property string shortcut: ""  // key of the action, in the tooltip after its text
    property string size: "md"
    readonly property string shownText: text !== "" ? text
        : glyph !== "" && theme.iconFont === "" ? (fallback !== "" ? fallback : tip) : ""
    readonly property real pad: shownText !== "" ? (size === "xs" ? theme.em * 0.8 : theme.em * 1.6)
                                                 : (size === "xs" ? theme.em * 0.3 : theme.em * 0.8)
    // Sizes from texts, never from .visible: false inside a hidden parent (hidden probe buttons measure labels)
    readonly property bool iconShown: icon.text !== ""
    readonly property real iconWidth: iconShown ? icon.implicitWidth + (shownText !== "" ? content.spacing : 0) : 0
    // Text from the tooltip (no icon font): kept short, the tooltip has it all
    readonly property real labelMax: text === "" && fallback === "" ? theme.em * 8 : Infinity

    hoverEnabled: true
    focusPolicy: Qt.TabFocus  // reached with Tab, a click leaves keyboard focus where it was
    implicitHeight: Math.round(size === "sm" ? theme.controlHeightSm : size === "xs" ? theme.controlHeightXs : theme.controlHeight)
    implicitWidth: Math.max(implicitHeight, iconWidth + (shownText !== "" ? Math.min(label.implicitWidth, labelMax) : 0) + pad)
    opacity: enabled ? 1 : theme.disabledOpacity

    readonly property string tipText: !enabled && disabledTip !== "" ? disabledTip
        : (tip !== "" ? tip : text) + (shortcut !== "" ? "  (" + shortcut + ")" : "")
    ToolTip.visible: (tip !== "" || shortcut !== "" || label.truncated || (!enabled && disabledTip !== ""))
                     && (hovered || visualFocus)
    ToolTip.text: tipText
    ToolTip.delay: theme.tipDelay
    // Screen readers: text, else tooltip (icon only buttons)
    Accessible.role: Accessible.Button
    Accessible.name: text !== "" ? text : tip
    Accessible.description: !enabled && disabledTip !== "" ? disabledTip : text !== "" ? tip : ""
    // Space presses (AbstractButton), Enter too
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()
    // Focused button takes Enter & Space: page shortcuts on these keys (Broadcast Director) do not fire
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
            event.accepted = true
    }

    background: Rectangle {
        radius: control.size === "xs" ? theme.radiusXs : theme.radiusSm
        // Accent darkens on hover: white text keeps 4.5:1 (fill is just dark enough)
        color: control.accent ? (control.danger ? (control.down ? theme.lossPressed : control.hovered ? theme.lossHover : theme.lossFill)
                                                : (control.down ? theme.accentPressed : control.hovered ? theme.accentHover : theme.accentFill))
             : control.checked ? theme.tint(theme.accent, control.down ? theme.tintSelected + 0.12
                                            : control.hovered ? theme.tintSelected * 4 / 3 : theme.tintSelected)
             : control.down ? theme.border
             : control.hovered ? theme.hover
             : control.flat ? "transparent" : theme.raised
        border.width: control.flat || control.accent || control.checked ? 0 : 1
        border.color: theme.border
        Behavior on color { ColorAnimation { duration: theme.motionFast } }

        FocusRing { visible: control.visualFocus }
    }

    contentItem: Item {
        implicitWidth: content.implicitWidth
        implicitHeight: content.implicitHeight
        Row {
            id: content
            anchors.centerIn: parent
            spacing: control.size === "xs" ? theme.space1 : theme.em * 0.5
            Icon {
                id: icon
                glyph: control.glyph
                size: control.size === "xs" ? theme.iconSm : theme.iconMd
                color: control.accent ? theme.accentInk : control.checked ? theme.accent : theme.text
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                id: label
                text: control.shownText
                textFormat: Text.PlainText
                visible: text !== ""
                // Half a pixel spare: fractional sizes (130.2 - 19.2 - 20 = 90.99999) never cut a fitting label
                width: Math.max(0, Math.min(implicitWidth, control.labelMax, control.availableWidth - control.pad - control.iconWidth + 0.5))
                elide: Text.ElideRight
                color: control.accent ? theme.accentInk : control.checked ? theme.accent : theme.text
                font.weight: control.accent ? Font.DemiBold : Font.Normal
                font.pointSize: control.size === "xs" ? theme.fontSmall : theme.fontPoint
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
