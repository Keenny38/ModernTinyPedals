import QtQuick
import QtQuick.Controls.Basic

// Rounded button: icon glyph and/or text, flat (toolbar) or accent (primary) look
AbstractButton {
    id: control
    property string glyph: ""
    property bool flat: false
    property bool accent: false
    property string tip: ""

    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    implicitHeight: Math.round(theme.em * 2.3)
    implicitWidth: Math.max(implicitHeight, content.implicitWidth + (text ? theme.em * 1.6 : theme.em * 0.8))
    opacity: enabled ? 1 : 0.45

    ToolTip.visible: tip !== "" && hovered
    ToolTip.text: tip
    ToolTip.delay: 600
    // Screen readers: text, else tooltip (icon only buttons)
    Accessible.role: Accessible.Button
    Accessible.name: text !== "" ? text : tip
    Accessible.description: text !== "" ? tip : ""

    background: Rectangle {
        radius: theme.em * 0.55
        color: control.accent ? (control.down ? Qt.darker(theme.accent, 1.15) : control.hovered ? Qt.lighter(theme.accent, 1.08) : theme.accent)
             : control.checked ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.18)
             : control.down ? theme.border
             : control.hovered ? theme.hover
             : control.flat ? "transparent" : theme.raised
        border.width: control.flat || control.accent || control.checked ? 0 : 1
        border.color: theme.border
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    contentItem: Item {
        implicitWidth: content.implicitWidth
        implicitHeight: content.implicitHeight
        Row {
            id: content
            anchors.centerIn: parent
            spacing: theme.em * 0.45
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
