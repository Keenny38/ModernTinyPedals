import QtQuick
import QtQuick.Layouts

// Page title row: title, optional subtitle & count badge, then the page's actions (children, right side)
//   TpPageHeader { title: i18n.tr("Presets"); count: backend.presetCount; TpButton { ... } }
RowLayout {
    id: header
    property string title: ""
    property string subtitle: ""
    property string count: ""
    property bool countActive: false  // count in accent color (something enabled), else dim
    default property alias actions: actionRow.data

    Layout.fillWidth: true
    spacing: theme.em * 0.6

    ColumnLayout {
        Layout.fillWidth: header.subtitle !== ""
        spacing: 0
        Text {
            Layout.fillWidth: true
            text: header.title
            color: theme.text
            font.pointSize: theme.fontTitle
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Accessible.role: Accessible.Heading
            Accessible.name: text
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: header.subtitle
            color: theme.dimText
            elide: Text.ElideRight
        }
    }
    Pill {
        Layout.alignment: Qt.AlignVCenter
        visible: header.count !== ""
        text: header.count
        tint: header.countActive ? theme.accent : theme.dimText
    }
    Item { Layout.fillWidth: header.subtitle === ""; visible: header.subtitle === "" }
    RowLayout {
        id: actionRow
        spacing: theme.em * 0.6
    }
}
