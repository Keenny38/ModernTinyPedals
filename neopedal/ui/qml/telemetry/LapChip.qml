import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Chip of a lap (legend of charts, laps of a view): lap color dot, name, optional tag (REF) & detail (offset),
// close cross while hovered or focused. Reached with Tab: Space / Enter click it, menu key (or Shift+F10) opens its
// menu, Delete closes it (closable). Hidden lap (struck): no tint, name struck through (never color alone).
//   LapChip { lapColor: model.color; label: model.label; selected: pinned; onClicked: ...; onMenuRequested: ... }
Rectangle {
    id: chip
    property color lapColor: theme.accent
    property string label: ""
    property string mark: ""  // lap number shown before the dot, same as beside chart values (laps told apart without color)
    property string badge: ""  // short tag after the name, in lap color (REF)
    property string detail: ""  // dim text after the name (alignment offset)
    property bool selected: false  // highlighted lap: stronger tint & border
    property bool outlined: false  // border without selection (reference lap)
    property bool struck: false  // lap hidden in this view: no tint, struck name
    property bool excluded: false  // lap left out (other circuit...): dim italic name
    property bool dimmed: false  // another lap highlighted: name dim (no opacity on text)
    property bool closable: false
    property string tip: ""
    property string size: "md"  // "sm": dense panels
    readonly property bool hovered: area.containsMouse || closeArea.containsMouse
    signal clicked()
    signal doubleClicked()
    signal menuRequested(real x, real y)
    signal closeClicked()

    height: Math.round(theme.em * (size === "sm" ? 1.6 : 1.8))
    width: chipRow.implicitWidth + theme.em * (size === "sm" ? 0.8 : 0.9)
    radius: height / 2
    color: struck ? "transparent" : theme.tint(lapColor, selected ? "strong" : hovered ? "selected" : "subtle")
    border.width: selected || outlined ? 1.5 : 1
    border.color: struck ? theme.border : selected || outlined ? lapColor : theme.tint(lapColor, 0.45)
    Behavior on color { ColorAnimation { duration: theme.motionFast } }

    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: (mark !== "" ? mark + " " : "") + label + (badge !== "" ? " " + badge : "")
    Accessible.description: tip
    Accessible.checkable: true
    Accessible.checked: struck ? false : true
    Keys.onSpacePressed: chip.clicked()
    Keys.onReturnPressed: chip.clicked()
    Keys.onEnterPressed: chip.clicked()
    Keys.onDeletePressed: if (chip.closable) chip.closeClicked()
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
            chip.menuRequested(chip.width / 2, chip.height)
            event.accepted = true
        }
    }
    Keys.onShortcutOverride: function(event) {  // focused chip takes its keys (charts shortcuts wait)
        if ([Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Delete].indexOf(event.key) >= 0)
            event.accepted = true
    }

    ToolTip.visible: tip !== "" && (area.containsMouse || chip.activeFocus)
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay

    FocusRing { visible: chip.activeFocus }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton) chip.menuRequested(mouse.x, mouse.y)
            else chip.clicked()
        }
        onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) chip.doubleClicked() }
    }
    Row {
        id: chipRow
        anchors.centerIn: parent
        spacing: chip.size === "sm" ? theme.space2 : theme.space3
        Text {
            visible: chip.mark !== ""
            text: chip.mark
            color: theme.text
            font.pointSize: theme.fontCaption
            font.weight: Font.Bold
            font.features: { "tnum": 1 }
            anchors.verticalCenter: parent.verticalCenter
        }
        ColorDot {
            size: Math.round(theme.em * (chip.size === "sm" ? 0.45 : 0.55))
            color: chip.lapColor
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: chip.label
            color: chip.struck || chip.excluded || chip.dimmed ? theme.dimOn(chip.color) : theme.text
            font.pointSize: chip.size === "sm" ? theme.fontCaption : theme.fontLabel
            font.italic: chip.excluded
            font.strikeout: chip.struck
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: chip.badge !== ""
            text: chip.badge
            color: chip.dimmed ? theme.dimOn(chip.color) : chip.lapColor
            font.pointSize: theme.fontCaption
            font.weight: Font.Bold
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: chip.detail !== ""
            text: chip.detail
            color: theme.dimOn(chip.color)
            font.pointSize: theme.fontCaption
            font.features: { "tnum": 1 }
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: chip.closable && (chip.hovered || chip.activeFocus)
            text: "×"
            color: closeArea.containsMouse ? theme.text : theme.dimOn(chip.color)
            font.weight: Font.Bold
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                id: closeArea
                anchors.fill: parent
                anchors.margins: -theme.space1
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: chip.closeClicked()
            }
        }
    }
}
