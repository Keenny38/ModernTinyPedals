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
    property string tip: ""
    property string count: ""
    property bool warning: false  // title in loss color with warning icon
    property bool busy: false  // waiting for data: small spinner after the title
    property string level: "card"
    property bool closable: false
    default property alias actions: actionRow.data
    signal closed()

    Layout.fillWidth: true
    spacing: theme.em * 0.5
    implicitHeight: Math.max(Math.round(theme.em * (level === "popup" ? 2.3 : 2)), actionRow.implicitHeight)

    Icon {
        glyph: header.warning ? "" : header.glyph  // warning
        fallback: header.warning ? "!" : ""
        color: header.warning ? theme.loss : theme.accent
        size: header.level === "popup" ? theme.em * 1.15 : theme.em * 0.95
        Layout.alignment: Qt.AlignVCenter
    }
    Text {
        id: titleText
        text: header.title
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
    Rectangle {  // count chip
        visible: header.count !== ""
        implicitHeight: Math.round(theme.em * 1.4)
        implicitWidth: countText.implicitWidth + theme.em * 0.9
        radius: height / 2
        color: theme.hover
        Layout.alignment: Qt.AlignVCenter
        Text {
            id: countText
            anchors.centerIn: parent
            text: header.count
            color: theme.dimOn(theme.hover)
            font.pointSize: theme.fontSmall
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
        }
    }
    BusyIndicator {
        visible: header.busy
        running: visible && pageState.active
        implicitWidth: Math.round(theme.em * 1.3)
        implicitHeight: implicitWidth
        Layout.alignment: Qt.AlignVCenter
    }
    Item { visible: header.count !== "" || header.busy; Layout.fillWidth: true }
    RowLayout {
        id: actionRow
        spacing: theme.space3
        Layout.alignment: Qt.AlignVCenter
    }
    TpButton {
        visible: header.closable
        flat: true
        size: "sm"
        glyph: ""  // cancel
        fallback: "✕"
        tip: i18n.tr("Close")
        Layout.alignment: Qt.AlignVCenter
        onClicked: header.closed()
    }
}
