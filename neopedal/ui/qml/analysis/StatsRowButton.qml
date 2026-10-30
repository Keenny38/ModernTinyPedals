import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Clickable row of a driver stats card (official race, rival, progress of the week): list row look, Tab then
// Enter / Space, pointing hand, tooltip. Content: children laid out in a row filling it.
//   StatsRowButton { tip: i18n.tr("..."); onClicked: ...; Text { ... } }
AbstractButton {
    id: button
    property string tip: ""
    default property alias content: row.data

    Layout.fillWidth: true
    implicitHeight: row.implicitHeight + theme.space2 * 2
    implicitWidth: row.implicitWidth + theme.space2 * 2
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    Accessible.role: Accessible.Button
    Accessible.description: tip
    Keys.onReturnPressed: animateClick()
    Keys.onEnterPressed: animateClick()
    // Focused row takes Enter & Space: page shortcuts on these keys do not fire
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
            event.accepted = true
    }
    ToolTip.visible: tip !== "" && (hovered || visualFocus)
    ToolTip.text: tip
    ToolTip.delay: theme.tipDelay
    background: TpListRow {
        hovered: button.hovered
        pressed: button.down
        FocusRing { visible: button.visualFocus }
    }
    contentItem: Item {}
    // Own objects in data: the default property (content) would take them otherwise
    data: [
        HoverHandler { cursorShape: Qt.PointingHandCursor },
        RowLayout {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            x: theme.space2
            width: button.width - theme.space2 * 2
            spacing: theme.space3
        }
    ]
}
