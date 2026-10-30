import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Header row of a card, panel or popup: icon, title (full title in tooltip when cut), count chip, busy
// spinner, actions on the right (children), close button. level "card" (body size) or "popup" (fontHeading).
//   TpCardHeader { glyph: ""; title: i18n.tr("Laps"); count: "12"; TpButton { ... } }
RowLayout {
    id: header
    property string title: ""
    property string glyph: ""
    property string fallback: ""  // icon text without icon font
    property color tint: theme.headerTint  // icon color
    property string tip: ""
    property string count: ""
    property bool warning: false  // title in loss color with warning icon
    property bool busy: false  // waiting for data: small spinner after the title
    property string level: "card"
    property bool closable: false
    property string closeTip: i18n.tr("Close")  // popup windows: i18n.tr("Close") + " (Esc)"
    default property alias actions: actionRow.data
    signal closed()

    Layout.fillWidth: true
    spacing: theme.space3
    implicitHeight: Math.max(Math.round(level === "popup" ? theme.controlHeight : theme.em * 2), actionRow.implicitHeight)

    Icon {
        glyph: header.warning ? "" : header.glyph  // warning
        fallback: header.warning ? "!" : header.fallback
        color: header.warning ? theme.loss : header.tint
        size: theme.iconMd
        Layout.alignment: Qt.AlignVCenter
    }
    Text {
        id: titleText
        text: header.title
        textFormat: Text.PlainText
        color: header.warning ? theme.loss : theme.text
        font.weight: Font.DemiBold
        font.pointSize: header.level === "popup" ? theme.fontHeading : theme.fontPoint
        elide: Text.ElideRight
        Layout.fillWidth: header.count === "" && !header.busy
        Layout.alignment: Qt.AlignVCenter
        Accessible.role: Accessible.Heading
        Accessible.name: text
        HoverHandler { id: titleHover; enabled: header.tip !== "" || titleText.truncated }
        ToolTip.visible: titleHover.hovered
        ToolTip.text: header.tip !== "" ? (titleText.truncated ? header.title + "\n" + header.tip : header.tip) : header.title
        ToolTip.delay: theme.tipDelay
    }
    TpCountBadge {
        visible: header.count !== ""
        text: header.count
        Layout.alignment: Qt.AlignVCenter
    }
    TpSpinner {
        visible: header.busy
        Layout.alignment: Qt.AlignVCenter
    }
    Item { visible: header.count !== "" || header.busy; Layout.fillWidth: true }
    RowLayout {
        id: actionRow
        spacing: theme.space3
        Layout.fillWidth: false  // a nested layout fills by default: would share the title's room
        Layout.alignment: Qt.AlignVCenter
    }
    TpButton {
        visible: header.closable
        flat: true
        size: "sm"
        glyph: theme.glyphs.close
        fallback: "✕"
        tip: header.closeTip
        Layout.alignment: Qt.AlignVCenter
        onClicked: header.closed()
    }
}
