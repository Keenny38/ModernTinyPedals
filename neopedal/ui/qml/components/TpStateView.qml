import QtQuick
import QtQuick.Layouts

// State of a panel without content to show, centered in its parent: waiting (spinner), error (warning icon,
// message) or empty (icon, title, explanation, action). One place & look everywhere; never "nothing
// recorded" while data is still loading (loading wins).
//   TpStateView { anchors.centerIn: parent; loading: backend.loading; empty: list.count === 0
//                 glyph: ""; title: i18n.tr("No laps"); text: ...; loadingText: i18n.tr("Reading laps…") }
Item {
    id: view
    property bool loading: false
    property bool empty: false
    property bool error: false
    property string loadingText: ""
    property string errorText: ""
    property string glyph: ""
    property string title: ""
    property string text: ""
    property string actionText: ""
    property string secondaryActionText: ""  // flat button beside the action ("Clear Search")
    property bool compact: false
    property real topPadding: 0  // room above, in a list or column (not centered): search results
    signal action()
    signal secondaryAction()

    visible: loading || error || empty
    // Anchored: width from the parent. In a layout: as wide as the layout gives, 26 em at most (never an
    // implicit width made from the layout's own width: polish loop), so texts wrap
    width: Math.max(0, Math.min(parent ? parent.width - theme.em * 2 : theme.em * 24, theme.em * 26))
    Layout.fillWidth: true
    Layout.maximumWidth: theme.em * 26
    implicitHeight: topPadding + (loading ? spinner.implicitHeight : message.implicitHeight)
    height: implicitHeight

    TpLoadingState {
        id: spinner
        y: view.topPadding
        width: view.width
        visible: view.loading
        compact: view.compact
        text: view.loadingText
    }
    EmptyState {
        id: message
        y: view.topPadding
        width: view.width
        visible: !view.loading && (view.error || view.empty)
        compact: view.compact
        glyph: view.error ? "" : view.glyph  // warning
        title: view.error ? "" : view.title
        text: view.error ? view.errorText : view.text
        actionText: view.error ? "" : view.actionText
        secondaryActionText: view.error ? "" : view.secondaryActionText
        onAction: view.action()
        onSecondaryAction: view.secondaryAction()
    }
}
