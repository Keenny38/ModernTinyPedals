import QtQuick
import QtQuick.Layouts

// Section of a page: card with header (icon, title, count chip, warning, busy spinner, actions) and content
// below, filling the card when the card is taller than its content. One card look for every page.
//   TpSectionCard { title: i18n.tr("Stints"); glyph: ""; count: "3"; actions: [TpButton { ... }]; Text { ... } }
Card {
    id: card
    property string title: ""
    property string glyph: ""
    property string tip: ""
    property string count: ""
    property bool warning: false
    property bool busy: false
    default property alias content: body.data
    property alias actions: header.actions
    property alias headerItem: header
    readonly property real pad: theme.padCard

    Layout.fillWidth: true
    implicitWidth: Math.max(header.implicitWidth, body.implicitWidth) + pad * 2
    implicitHeight: header.height + body.implicitHeight + pad * 2 + theme.space3

    TpCardHeader {
        id: header
        x: card.pad
        y: card.pad
        width: card.width - card.pad * 2
        height: implicitHeight
        title: card.title
        glyph: card.glyph
        tip: card.tip
        count: card.count
        warning: card.warning
        busy: card.busy
    }
    ColumnLayout {
        id: body
        x: card.pad
        y: header.y + header.height + theme.space3
        width: card.width - card.pad * 2
        height: Math.max(implicitHeight, card.height - y - card.pad)  // card taller than content: fill items grow
        spacing: theme.space3
    }
}
