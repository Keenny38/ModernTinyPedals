import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Row of actions (TpAction children) fitted to its width: every action with its text when there is room, then
// the least important ones (lower priority) icon only, then moved into a "⋯" menu. Same handlers everywhere,
// every button & the menu reachable with Tab. Its implicit width is the full row: in a RowLayout give it
// Layout.fillWidth so it gets what is left.
//   TpToolbar {
//       Layout.fillWidth: true
//       TpAction { text: i18n.tr("Import"); glyph: ""; priority: 2; onTriggered: function(source) { ... } }
//       TpAction { text: i18n.tr("Export"); glyph: ""; priority: 1; onTriggered: backend.exportLaps() }
//   }
Item {
    id: bar
    default property list<QtObject> actions
    property real spacing: theme.space2
    property bool alignRight: true
    property string size: "md"  // button size
    signal menuClosed()  // "⋯" menu closed: page gives keyboard focus back (Menu leaves it on the window)
    // Mode of each action: 0 button with text, 1 icon only, 2 in the "⋯" menu (kept by fit())
    property var modes: []
    readonly property bool overflowing: modes.indexOf(2) >= 0
    readonly property real moreWidth: Math.round(size === "sm" ? theme.controlHeightSm : theme.controlHeight)

    implicitHeight: Math.round(size === "sm" ? theme.controlHeightSm : theme.controlHeight)
    implicitWidth: fullWidth
    Layout.minimumWidth: moreWidth
    property real fullWidth: 0
    // Button width of each action with its text & icon only, measured by measure() (one hidden probe button)
    property var fullWidths: []
    property var iconWidths: []
    // Everything a button width depends on (theme sizes are constant): measured again once after a change
    readonly property string measureKey: {
        var parts = [size]
        for (var i = 0; i < actions.length; ++i) {
            var entry = actions[i]
            parts.push(entry.text, entry.glyph, entry.fallback, entry.tip, entry.accent, entry.shown)
        }
        return parts.join("\u0001")
    }
    onMeasureKeyChanged: fitLater.restart()

    // Probe set up as each action's button would be (same TpButton: same sizes), with its text then icon only
    function measure() {
        var full = []
        var icon = []
        for (var i = 0; i < actions.length; ++i) {
            var entry = actions[i]
            probe.size = size
            probe.accent = entry.accent  // demi bold text
            probe.glyph = entry.glyph
            probe.fallback = entry.fallback
            probe.text = entry.text
            probe.tip = entry.tip  // button with text (mode 0)
            full.push(probe.implicitWidth)
            probe.text = ""
            probe.tip = entry.tip !== "" ? entry.tip : entry.text  // icon only (mode 1)
            icon.push(probe.implicitWidth)
        }
        fullWidths = full
        iconWidths = icon
    }
    function widthOf(widths, index) {
        return index < widths.length ? widths[index] : 0
    }

    function fit() {
        var count = actions.length
        if (fullWidths.length !== count)
            measure()
        var next = []
        var full = 0
        var shown = 0
        for (var i = 0; i < count; ++i) {
            next.push(0)
            if (actions[i].shown) {
                full += widthOf(fullWidths, i)
                shown += 1
            }
        }
        full += Math.max(0, shown - 1) * spacing
        fullWidth = full
        var order = []
        for (var j = 0; j < count; ++j)
            if (actions[j].shown)
                order.push(j)
        order.sort(function(a, b) { return actions[a].priority - actions[b].priority || b - a })
        var total = full
        // 1. least important first: icon only (actions with an icon)
        for (var k = 0; k < order.length && total > width; ++k) {
            var index = order[k]
            if (actions[index].glyph !== "") {
                total -= widthOf(fullWidths, index) - widthOf(iconWidths, index)
                next[index] = 1
            }
        }
        // 2. then into the menu, "⋯" button counted once
        var menuShown = false
        for (var m = 0; m < order.length && total > width; ++m) {
            var moved = order[m]
            if (actions[moved].pinned)
                continue
            if (!menuShown)
                total += moreWidth + spacing  // first action moved: "⋯" button shown
            total -= widthOf(next[moved] === 1 ? iconWidths : fullWidths, moved) + spacing
            next[moved] = 2
            menuShown = true
        }
        if (JSON.stringify(next) !== JSON.stringify(modes))
            modes = next
    }
    function modeOf(index) {
        return index < modes.length ? modes[index] : 0
    }

    onWidthChanged: fit()
    onActionsChanged: fitLater.restart()
    Component.onCompleted: { measure(); fit() }
    // Own objects in data: the default property (actions) would take them otherwise
    data: [
        Timer { id: fitLater; interval: 0; onTriggered: { bar.measure(); bar.fit() } },

        // Hidden probe set up by measure() for each action (TpButton sizes never depend on visibility)
        Item {
            visible: false
            TpButton { id: probe }
        },
        Row {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            x: bar.alignRight ? Math.max(0, bar.width - width) : 0
            spacing: bar.spacing
            Repeater {
                model: bar.actions.length
                TpButton {
                    id: button
                    required property int index
                    readonly property QtObject entry: bar.actions[index]
                    readonly property int mode: bar.modeOf(index)
                    objectName: entry.name
                    visible: entry.shown && mode !== 2
                    size: bar.size
                    text: mode === 0 ? entry.text : ""
                    glyph: entry.glyph
                    fallback: entry.fallback
                    tip: entry.tip !== "" ? entry.tip : (mode !== 0 ? entry.text : "")
                    enabled: entry.enabled
                    checkable: false  // follows the action (its owner stores the state)
                    checked: entry.checked
                    accent: entry.accent
                    flat: entry.flat
                    Accessible.name: entry.text !== "" ? entry.text : entry.tip
                    onClicked: entry.triggered(button)
                }
            }
            TpButton {
                id: more
                objectName: "toolbarMore"
                visible: bar.overflowing
                size: bar.size
                flat: true
                glyph: ""  // more
                fallback: "⋯"
                tip: i18n.tr("More actions")
                checked: overflowMenu.visible
                onClicked: overflowMenu.popup(more, 0, more.height + 4)
            }
        },
        TpMenu {
            id: overflowMenu
            objectName: "toolbarMenu"
            onClosed: bar.menuClosed()
            Instantiator {
                model: bar.actions.length
                delegate: TpMenuItem {
                    required property int index
                    readonly property QtObject entry: bar.actions[index]
                    readonly property bool inMenu: entry.shown && bar.modeOf(index) === 2
                    text: entry.text !== "" ? entry.text : entry.tip
                    enabled: entry.enabled
                    checkable: entry.checkable
                    checked: entry.checked
                    visible: inMenu
                    height: inMenu ? implicitHeight : 0
                    onTriggered: {
                        checked = Qt.binding(function() { return entry.checked })  // the action's owner keeps the state
                        entry.triggered(more)
                    }
                }
                onObjectAdded: function(index, object) { overflowMenu.insertItem(index, object) }
                onObjectRemoved: function(index, object) { overflowMenu.removeItem(object) }
            }
        }
    ]
}
