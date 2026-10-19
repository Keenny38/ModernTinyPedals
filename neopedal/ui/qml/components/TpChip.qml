import QtQuick
import QtQuick.Controls.Basic

// Filter chip: optional color dot, text & count, accent tint when selected. Reached with Tab, Space / Enter
// choose it. One chip look for every filter (categories, classes, event kinds, channels).
// Without results (count 0) the text is dim, never faded by opacity.
//   TpChip { text: i18n.tr("Timing"); count: 4; selected: page.filter === "timing"; onClicked: ... }
AbstractButton {
    id: chip
    property color dotColor: "transparent"
    property bool showDot: false
    property int count: -1  // shown when 0 or more
    property bool selected: false
    property bool multi: false  // several chips can be selected (check box for screen readers)
    property string tip: ""
    property string size: "md"  // "sm": dense panels
    property bool dimmed: count === 0 && !selected  // dim text (no results, not recorded)

    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    implicitHeight: Math.round(theme.em * (size === "sm" ? 1.7 : 2))
    implicitWidth: content.implicitWidth + theme.em * (size === "sm" ? 1.0 : 1.3)
    opacity: enabled ? 1 : theme.disabledOpacity

    Accessible.role: multi ? Accessible.CheckBox : Accessible.RadioButton
    Accessible.name: count >= 0 ? text + " (" + count + ")" : text
    Accessible.description: tip
    Accessible.checked: selected
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
            event.accepted = true
    }
    ToolTip.visible: tip !== "" && (hovered || visualFocus)
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay

    HoverHandler { cursorShape: chip.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    background: Rectangle {
        radius: height / 2
        color: chip.selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b,
                                       chip.hovered ? theme.tintSelected * 4 / 3 : theme.tintSelected)
             : chip.down ? theme.border
             : chip.hovered ? theme.hover : "transparent"
        border.width: 1
        border.color: chip.selected ? theme.accent : chip.hovered ? Qt.lighter(theme.border, 1.25) : theme.border
        Behavior on color { ColorAnimation { duration: theme.motionFast } }
        Behavior on border.color { ColorAnimation { duration: theme.motionFast } }
        FocusRing { visible: chip.visualFocus }
    }
    contentItem: Item {
        implicitWidth: content.implicitWidth
        implicitHeight: content.implicitHeight
        Row {
            id: content
            anchors.centerIn: parent
            spacing: theme.space3
            ColorDot {
                visible: chip.showDot
                color: chip.dotColor
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: chip.text
                color: chip.dimmed ? theme.dimText : theme.text
                font.weight: chip.selected ? Font.DemiBold : Font.Normal
                font.pointSize: chip.size === "sm" ? theme.fontSmall : theme.fontPoint
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: chip.count >= 0
                text: chip.count
                color: chip.selected ? theme.accent : theme.dimText
                font.pointSize: theme.fontSmall
                font.features: { "tnum": 1 }
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
