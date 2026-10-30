import QtQuick
import QtQuick.Controls.Basic

// Color swatch opening a color picker (clicked): the color, or a "?" in loss color when the code is invalid (never
// color alone). Hover: strong outline (accent stays for selection), Tab focus ring, Enter / Space pick (focusable
// false inside table cells: the table moves with the keys).
//   TpColorSwatch { color: editor.color; onClicked: editor.colorRequested() }
AbstractButton {
    id: swatch
    property string color: ""  // "" for an invalid code
    property bool focusable: true

    implicitWidth: Math.round(theme.fieldHeight)
    implicitHeight: implicitWidth
    hoverEnabled: true
    focusPolicy: focusable ? Qt.TabFocus : Qt.NoFocus
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
            event.accepted = true
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    ToolTip.visible: hovered || visualFocus
    ToolTip.text: i18n.tr("Select Color")
    ToolTip.delay: theme.tipDelay
    Accessible.role: Accessible.Button
    Accessible.name: i18n.tr("Select Color")

    background: Rectangle {
        radius: theme.radiusSm
        color: swatch.color !== "" ? swatch.color : "transparent"
        border.width: 1
        border.color: swatch.hovered ? theme.strokeStrong : theme.border
        Behavior on border.color { ColorAnimation { duration: theme.motionFast } }
        FocusRing { visible: swatch.visualFocus }
    }
    contentItem: Text {
        visible: swatch.color === ""
        text: "?"
        textFormat: Text.PlainText
        color: theme.loss
        font.pointSize: swatch.width < theme.controlHeightSm ? theme.fontCaption : theme.fontPoint
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
