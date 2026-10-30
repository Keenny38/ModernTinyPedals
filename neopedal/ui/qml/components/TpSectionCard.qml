import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Section of a page: card with header (eyebrow, icon, title, count chip, warning, busy spinner, actions, trailing
// items) and content below, filling the card when the card is taller than its content, then footer buttons at the
// bottom. One card look for every page (Home cards, release notes, panels). No header when it has nothing to show.
// clickable: the whole card opens something (opened signal): pointing hand, surfaceHover background, pressed
// surface, Tab focus ring, Enter / Space open it; buttons & links inside keep their own clicks. Accent stays for
// selection & main actions (never the hover border).
//   TpSectionCard { title: i18n.tr("Stints"); glyph: ""; count: "3"; actions: [TpButton { ... }]; Text { ... } }
//   TpSectionCard { eyebrow: i18n.tr("Last session"); title: backend.track; glyph: ""; clickable: true
//                   tip: i18n.tr("Open the results"); onOpened: backend.openPage("results")
//                   trailing: [GameLogo { ... }]; footer: [TpButton { text: i18n.tr("Debrief") }]; Text { ... } }
Card {
    id: card
    property string title: ""
    property string eyebrow: ""  // small capitals above the title ("LAST SESSION")
    property string glyph: ""
    property string fallback: ""  // header icon text without icon font
    property color tint: theme.headerTint  // header icon color
    property string tip: ""  // title tooltip, or what a click opens (clickable)
    property string count: ""
    property bool warning: false
    property bool busy: false
    property bool clickable: false
    // Card taller than its content: content spread over the height (fill items grow), false: kept at the top
    // (Home cards: footer buttons at the bottom, content under the header)
    property bool fillContent: true
    property real spacing: theme.space3  // between content items
    default property alias content: body.data
    property alias actions: header.actions
    property alias trailing: trailingRow.data  // right of the header (logos, status), after the actions
    property alias footer: footerRow.data  // buttons at the bottom of the card, right aligned
    property alias headerItem: header
    readonly property real pad: theme.padCard
    readonly property bool hovered: area.containsMouse
    readonly property bool pressed: area.pressed
    // Sizes from properties & children counts, never from .visible (false inside a hidden parent)
    readonly property bool headerShown: title !== "" || glyph !== "" || count !== "" || warning || busy
                                        || actionCount > 0 || trailingRow.children.length > 0
    readonly property int actionCount: header.actions.length !== undefined ? header.actions.length : 0
    readonly property bool footerShown: footerRow.children.length > 0
    readonly property real eyebrowHeight: eyebrow !== "" ? eyebrowText.implicitHeight + theme.space1 : 0
    readonly property real headerHeight: headerShown ? header.implicitHeight : 0
    readonly property real bodyY: pad + eyebrowHeight + headerHeight + (headerShown ? theme.space3 : 0)
    readonly property real footerHeight: footerShown ? footerRow.implicitHeight + theme.space3 : 0
    signal opened()

    Layout.fillWidth: true
    implicitWidth: Math.max(header.implicitWidth + trailingRow.implicitWidth, body.implicitWidth,
                            footerRow.implicitWidth) + pad * 2
    implicitHeight: bodyY + body.implicitHeight + footerHeight + pad

    color: clickable && pressed ? theme.surfaceSunken : clickable && hovered ? theme.surfaceHover : theme.surfaceCard
    border.color: clickable && hovered ? theme.strokeStrong : theme.strokeSubtle
    Behavior on color { ColorAnimation { duration: theme.motionFast } }

    activeFocusOnTab: clickable
    Keys.onReturnPressed: if (clickable) card.opened()
    Keys.onEnterPressed: if (clickable) card.opened()
    Keys.onSpacePressed: if (clickable) card.opened()
    Keys.onShortcutOverride: function(event) {  // focused card takes Enter & Space: page shortcuts do not fire
        if (clickable && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space))
            event.accepted = true
    }
    Accessible.role: clickable ? Accessible.Button : Accessible.Grouping
    Accessible.name: eyebrow !== "" ? eyebrow + ", " + title : title
    Accessible.description: tip
    Accessible.onPressAction: if (clickable) card.opened()

    // Own items in data: the default property (content) takes the children declared by users of the card
    data: [
        MouseArea {  // under the content: buttons inside take their own clicks
            id: area
            anchors.fill: parent
            enabled: card.clickable
            hoverEnabled: true
            cursorShape: card.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: card.opened()
        },
        FocusRing { visible: card.activeFocus && card.clickable },
        TpText {
            id: eyebrowText
            x: card.pad
            y: card.pad
            width: card.width - card.pad * 2
            visible: card.eyebrow !== ""
            role: "overline"
            text: card.eyebrow
        },
        TpCardHeader {
            id: header
            x: card.pad
            y: card.pad + card.eyebrowHeight
            width: card.width - card.pad * 2 - (trailingRow.children.length > 0 ? trailingRow.implicitWidth + theme.space3 : 0)
            height: implicitHeight
            visible: card.headerShown
            title: card.title
            glyph: card.glyph
            fallback: card.fallback
            tint: card.tint
            tip: card.clickable ? "" : card.tip
            count: card.count
            warning: card.warning
            busy: card.busy
        },
        RowLayout {
            id: trailingRow
            anchors.right: parent.right
            anchors.rightMargin: card.pad
            y: header.y + (header.height - height) / 2
            spacing: theme.space3
        },
        ColumnLayout {
            id: body
            x: card.pad
            y: card.bodyY
            width: card.width - card.pad * 2
            // card taller than content: fill items grow (footer kept at the bottom)
            height: card.fillContent ? Math.max(implicitHeight, card.height - y - card.pad - card.footerHeight) : implicitHeight
            spacing: card.spacing
        },
        Item {  // clickable card: what a click opens, in a tooltip over the card
            anchors.fill: parent
            ToolTip.visible: card.clickable && card.tip !== "" && card.hovered
            ToolTip.text: card.tip
            ToolTip.delay: theme.tipDelay
        },
        RowLayout {
            id: footerRow
            anchors.right: parent.right
            anchors.rightMargin: card.pad
            anchors.bottom: parent.bottom
            anchors.bottomMargin: card.pad
            visible: card.footerShown
            spacing: theme.space3
        }
    ]
}
