import QtQuick
import QtQuick.Layouts

// Page title row: title (display face), status items right after it (status: Pill, TpTally...), optional count
// badge, subtitle under the title, then the page's actions (children, right side). An empty title (tool pages: the
// host's title bar shows it) keeps status, subtitle & actions.
//   TpPageHeader { title: i18n.tr("Presets"); count: backend.presetCount; TpButton { ... } }
//   TpPageHeader { title: backend.title; subtitle: backend.detail
//                  status: [Pill { text: backend.chip; tint: theme.gain }]; TpCombo { ... } }
RowLayout {
    id: header
    property string title: ""
    property string subtitle: ""
    property string count: ""
    property bool countActive: false  // count in accent color (something enabled), else dim
    default property alias actions: actionRow.data
    property alias status: statusRow.data

    Layout.fillWidth: true
    spacing: theme.space4

    ColumnLayout {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpText {
                // Up to its own width: status & count stay right after the title, cut with "..." when short of room
                Layout.fillWidth: true
                Layout.maximumWidth: implicitWidth
                visible: text !== ""  // tool pages: title already in the host's title bar
                role: "title"
                text: header.title
            }
            RowLayout {
                id: statusRow
                // A nested layout fills by default: empty status would push the count badge away from the title
                Layout.fillWidth: false
                Layout.alignment: Qt.AlignVCenter
                visible: children.length > 0  // no double spacing between title & badge
                spacing: theme.space3
            }
            TpCountBadge {
                Layout.alignment: Qt.AlignVCenter
                visible: header.count !== ""
                text: header.count
                tone: header.countActive ? "accent" : "neutral"
            }
            Item { Layout.fillWidth: true }
        }
        TpText {
            Layout.fillWidth: true
            visible: text !== ""
            role: "body"
            color: theme.dimText
            text: header.subtitle
        }
    }
    RowLayout {
        id: actionRow
        Layout.fillWidth: false
        visible: children.length > 0
        Layout.alignment: Qt.AlignVCenter
        spacing: theme.space4
    }
}
