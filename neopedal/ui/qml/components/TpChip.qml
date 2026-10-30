import QtQuick
import QtQuick.Controls.Basic

// Filter chip: optional color dot, text & count, accent tint when selected. Reached with Tab, Space / Enter
// choose it. One chip look for every filter (categories, classes, event kinds, channels).
// Without results (count 0) the text is dim, never faded by opacity. removable: active filter chip with a ✕ button
// (removeRequested; Delete / Backspace on the focused chip too). interactive false: tag of a value (no click, no
// hover), removable or not. maximumTextWidth > 0: long texts cut with "..." (full text for screen readers).
//   TpChip { text: i18n.tr("Timing"); count: 4; selected: page.filter === "timing"; onClicked: ... }
//   TpChip { text: i18n.tr("Class: Hypercar"); selected: true; removable: true; onRemoveRequested: backend.clearClass() }
//   TpChip { interactive: false; text: modelData.name; showDot: true; dotColor: modelData.color; removable: true }
AbstractButton {
    id: chip
    property color dotColor: "transparent"
    property bool showDot: false
    property string glyph: ""  // icon before the text (Segoe icon code)
    property int count: -1  // shown when 0 or more
    property bool selected: false
    property bool multi: false  // several chips can be selected (check box for screen readers)
    property string tip: ""
    property string size: "md"  // "sm": dense panels
    property bool dimmed: count === 0 && !selected  // dim text (no results, not recorded)
    property bool removable: false
    property bool interactive: true  // false: tag (no click, no hover)
    property real maximumTextWidth: 0
    signal removeRequested()

    hoverEnabled: true
    focusPolicy: interactive || removable ? Qt.TabFocus : Qt.NoFocus
    implicitHeight: Math.round(size === "sm" ? theme.chipFilterHeightSm : theme.chipFilterHeight)
    implicitWidth: content.implicitWidth + theme.em * (size === "sm" ? 1.0 : 1.3) - (removable ? theme.space3 : 0)
    opacity: enabled ? 1 : theme.disabledOpacity

    Accessible.role: !interactive ? Accessible.StaticText : multi ? Accessible.CheckBox : Accessible.RadioButton
    Accessible.name: count >= 0 ? text + " (" + count + ")" : text
    Accessible.description: removable ? (tip !== "" ? tip + ", " : "") + i18n.tr("Delete key removes it") : tip
    Accessible.checked: selected
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space
                || (removable && (event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace)))
            event.accepted = true
    }
    Keys.onDeletePressed: if (removable) removeRequested()
    Keys.onPressed: function(event) {
        if (removable && event.key === Qt.Key_Backspace) {
            event.accepted = true
            removeRequested()
        }
    }
    ToolTip.visible: tip !== "" && (hovered || visualFocus)
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay

    HoverHandler { cursorShape: chip.enabled && chip.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor }

    background: Rectangle {
        radius: height / 2
        color: chip.selected ? theme.rowColor(chip.hovered, true)
             : !chip.interactive ? theme.tint(theme.accent, "subtle")
             : chip.down ? theme.surfaceSunken
             : chip.hovered ? theme.hover : "transparent"
        border.width: 1
        border.color: chip.selected ? theme.accent : chip.hovered && chip.interactive ? theme.strokeStrong : theme.border
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
            Icon {  // hidden without glyph (or icon font)
                glyph: chip.glyph
                size: theme.iconSm
                color: chip.selected ? theme.accent : chip.dimmed ? theme.dimText : theme.text
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: chip.text
                textFormat: Text.PlainText
                width: chip.maximumTextWidth > 0 ? Math.min(implicitWidth, chip.maximumTextWidth) : implicitWidth
                elide: Text.ElideRight
                color: chip.dimmed ? theme.dimText : theme.text
                font.weight: chip.selected ? Font.DemiBold : Font.Normal
                font.pointSize: chip.size === "sm" ? theme.fontSmall : theme.fontPoint
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: chip.count >= 0
                text: chip.count
                textFormat: Text.PlainText
                color: chip.selected ? theme.accent : theme.dimText
                font.pointSize: theme.fontSmall
                font.features: { "tnum": 1 }
                anchors.verticalCenter: parent.verticalCenter
            }
            TpButton {  // remove (active filter): its own click, not the chip
                visible: chip.removable
                flat: true
                size: "xs"
                glyph: theme.glyphs.remove
                fallback: "✕"
                tip: i18n.tr("Remove") + " " + chip.text
                focusPolicy: Qt.NoFocus  // the chip takes Tab, Delete removes
                anchors.verticalCenter: parent.verticalCenter
                onClicked: chip.removeRequested()
            }
        }
    }
}
