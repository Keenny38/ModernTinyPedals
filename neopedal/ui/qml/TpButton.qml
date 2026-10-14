import QtQuick
import QtQuick.Controls.Basic

// Rounded button: icon glyph and/or text, flat (toolbar) or accent (primary) look
AbstractButton {
    id: control
    property string glyph: ""
    property bool flat: false
    property bool accent: false
    property bool danger: false  // accent look in red: delete, remove
    property string tip: ""

    hoverEnabled: true
    focusPolicy: Qt.TabFocus  // reached with Tab, a click leaves keyboard focus where it was
    implicitHeight: Math.round(theme.em * 2.3)
    implicitWidth: Math.max(implicitHeight, content.implicitWidth + (text ? theme.em * 1.6 : theme.em * 0.8))
    opacity: enabled ? 1 : theme.disabledOpacity

    ToolTip.visible: tip !== "" && (hovered || visualFocus)
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay
    // Screen readers: text, else tooltip (icon only buttons)
    Accessible.role: Accessible.Button
    Accessible.name: text !== "" ? text : tip
    Accessible.description: text !== "" ? tip : ""
    // Space presses (AbstractButton), Enter too
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()

    background: Rectangle {
        radius: theme.radiusLg
        readonly property color fill: control.danger ? theme.lossFill : theme.accentFill
        color: control.accent ? (control.down ? Qt.darker(fill, 1.15) : control.hovered ? Qt.lighter(fill, 1.08) : fill)
             : control.checked ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.tintSelected)
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
            spacing: theme.em * 0.5
            Icon {
                glyph: control.glyph
                color: control.accent ? "white" : control.checked ? theme.accent : theme.text
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: control.text
                visible: text !== ""
                color: control.accent ? "white" : control.checked ? theme.accent : theme.text
                font.weight: control.accent ? Font.DemiBold : Font.Normal
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
