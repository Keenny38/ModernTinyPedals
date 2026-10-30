import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Row of Overlay Options page: section header (title, item on/off switch, collapse, reset), option
// (name with searched words in bold, description, editor matching its kind: TpOptionEditor shared with the
// Settings page, reset & more actions: "⋯", right click or Menu key) or display order list. Rows of a
// section form one card. Unsaved edits are marked by an accent bar, invalid values by a red reason,
// options of an item that is off are in dim text (still editable), options set by a profile are locked.
// Only the block of the row type is made (Loader per block). Rows are reused by the ListView (reuseItems):
// model fed again for another row, block & editor kept when of the same type & kind, editor reset on reuse.
Item {
    id: row
    readonly property bool rowHovered: rowHover.hovered  // hover-revealed actions shown
    required property var model
    required property int index
    // Roles read by bindings of every row type: fed once (and again on reuse or change) instead of a model read
    // (Python data() call) per binding evaluation. Roles of one row type are read once by its block (header,
    // order list, editor): required ones would be fed to every row. Roles read only on click stay model reads.
    required property string kind
    required property string label
    required property string help
    required property string text
    required property string error
    required property string note
    required property string hint
    required property bool locked
    required property bool dimmed
    required property bool modified
    required property bool checked
    required property bool first
    required property bool last
    required property bool changed
    required property string marked  // label with searched words in bold (rich text), "" if not searching
    readonly property string rowType: model.row
    readonly property real editorWidth: Math.min(theme.em * 19, Math.max(theme.em * 11, width * 0.42))  // as Settings
    property bool settled: true  // height, chevron & dimming animated, not while reused for another row
    signal menuRequested(var data, Item anchor, real x, real y)  // x < 0: menu below anchor, right aligned

    // Field being edited left first (typed text taken): an action of the menu (reset) is never undone by the
    // field committing its old text once focus moves; data copied: row may be reused while the menu is open
    function openMenu(anchor, x, y) {
        if (row.rowType !== "option")
            return
        row.releaseFocus()
        row.menuRequested({
            key: row.model.key, option: row.model.option, kind: row.kind, modified: row.modified,
            locked: row.locked, shared: row.model.shared, error: row.error
        }, anchor, x, y)
    }

    function moveItem(item, offset) {  // order list item moved up (-1) or down (+1): display order, or list option
        if (row.model.option !== "")
            backend.moveListItem(row.model.overlay, row.model.option, item, offset)
        else
            backend.moveOrder(row.model.overlay, item, offset)
    }
    function flash() {
        flashAnimation.restart()
    }
    function releaseFocus() {  // focus of a field in the row dropped (field left: typed text taken), true if held
        var chain = []
        for (var item = Window.activeFocusItem; item; item = item.parent) {
            if (item === row) {
                for (var number = 0; number < chain.length; number++)
                    chain[number].focus = false  // field & focus scopes (Loaders) around it
                return true
            }
            chain.push(item)
        }
        return false
    }

    ListView.onPooled: {
        if (releaseFocus())
            ListView.view.forceActiveFocus()  // before the row shows another option
        if (optionLoader.item)
            optionLoader.item.release()
        flashAnimation.stop()
        flashRect.opacity = 0
        row.settled = false
    }
    ListView.onReused: {
        if (optionLoader.item)
            optionLoader.item.reset()  // fields show the value of the new option (bindings broken by typing)
        settleTimer.restart()
    }
    Timer {
        id: settleTimer
        interval: 100
        onTriggered: row.settled = true
    }

    implicitHeight: gap.height + card.height
    // Menu key (or Shift+F10) in the option's editor: more actions
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
            row.openMenu(card, -1, -1)
            event.accepted = row.rowType === "option"
        }
    }

    Item {  // room above each section card
        id: gap
        width: parent.width
        height: row.rowType === "header" ? Math.round(theme.em * (row.index === 0 ? 0.2 : 0.9)) : 0
    }

    Rectangle {
        id: card
        y: gap.height
        width: parent.width
        height: row.rowType === "header" ? Math.round(theme.em * 2.9)
              : row.rowType === "order" ? orderLoader.implicitHeight + theme.space6
              : Math.max(optionLoader.implicitHeight + theme.em * 1.0, theme.rowTall)  // as Settings rows
        radius: theme.radiusLg
        color: row.rowType === "header" ? theme.surfaceHover : theme.surfaceCard  // section titles stand out of their options
        TapHandler {  // right click on an option: more actions at the pointer
            enabled: row.rowType === "option"
            acceptedButtons: Qt.RightButton
            onTapped: function(eventPoint) { row.openMenu(card, eventPoint.position.x, eventPoint.position.y) }
        }
        Behavior on height { enabled: row.rowType === "order" && row.settled; NumberAnimation { duration: theme.motionBase } }

        // Square corners between rows of a card
        Rectangle {
            visible: !row.first
            width: parent.width
            height: parent.radius
            color: parent.color
        }
        Rectangle {
            visible: !row.last
            width: parent.width
            height: parent.radius
            anchors.bottom: parent.bottom
            color: parent.color
        }
        Rectangle {  // separator
            visible: !row.first
            x: theme.em * 0.9
            width: parent.width - theme.em * 1.8
            height: 1
            color: theme.cardBorder
        }
        Rectangle {  // unsaved edit
            visible: row.changed || (headerLoader.item !== null && headerLoader.item.pending)
            width: Math.round(theme.em * 0.22)
            height: parent.height - theme.space5
            anchors.verticalCenter: parent.verticalCenter
            radius: width / 2
            color: row.error !== "" ? theme.loss : theme.accent
        }
        Rectangle {  // flash when opened at an option
            id: flashRect
            anchors.fill: parent
            radius: parent.radius
            color: theme.accent
            opacity: 0
            SequentialAnimation {
                id: flashAnimation
                NumberAnimation { target: flashRect; property: "opacity"; to: 0.28; duration: theme.motionBase }
                PauseAnimation { duration: theme.animate ? 350 : 0 }  // animations off: no flash
                NumberAnimation { target: flashRect; property: "opacity"; to: 0; duration: theme.animate ? 700 : 0; easing.type: Easing.InOutQuad }
            }
        }

        // Section header
        Loader {
            id: headerLoader
            anchors.fill: parent
            active: row.rowType === "header"
            sourceComponent: Item {
                id: headerBlock
                // Header roles: one model read each (header rows only)
                readonly property string title: row.model.title
                readonly property string toggle: row.model.toggle
                readonly property bool toggleChecked: row.model.toggleChecked
                readonly property bool collapsed: row.model.collapsed
                readonly property int count: row.model.count
                readonly property int customizedCount: row.model.customizedCount
                readonly property bool pending: collapsed && row.model.changedCount > 0  // unsaved edit hidden
                MouseArea {
                    id: headerArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: backend.filtering ? Qt.ArrowCursor : Qt.PointingHandCursor
                    onClicked: if (!backend.filtering) backend.toggleSection(row.model.key)
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.space3
                    anchors.rightMargin: theme.space3
                    spacing: theme.space3
                    TpButton {  // collapse / expand: Tab & Enter (the whole header is clickable too)
                        visible: !backend.filtering
                        flat: true
                        size: "xs"
                        glyph: ""  // chevron down
                        fallback: "▾"
                        tip: headerBlock.collapsed ? i18n.tr("Expand Section") : i18n.tr("Collapse Section")
                        rotation: headerBlock.collapsed ? -90 : 0
                        Behavior on rotation { enabled: row.settled; NumberAnimation { duration: theme.motionBase } }
                        onClicked: backend.toggleSection(row.model.key)
                        Accessible.role: Accessible.Button
                        Accessible.name: headerBlock.title + ", " + (headerBlock.collapsed ? i18n.tr("Expand Section") : i18n.tr("Collapse Section"))
                    }
                    Text {
                        Layout.fillWidth: true
                        text: headerBlock.title
                        textFormat: Text.PlainText
                        // Item off: title in dim text (never faded)
                        color: headerBlock.toggle !== "" && !headerBlock.toggleChecked ? theme.dimOn(card.color) : theme.text
                        Behavior on color { enabled: row.settled; ColorAnimation { duration: theme.motionBase } }
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Accessible.role: Accessible.Heading
                        Accessible.name: text
                    }
                    Pill {
                        visible: headerBlock.customizedCount > 0
                        size: "sm"
                        text: visible ? i18n.trm("Modified: " + headerBlock.customizedCount) : ""
                        tip: i18n.tr("Options changed from default")
                    }
                    Text {
                        visible: headerBlock.collapsed
                        text: headerBlock.count
                        textFormat: Text.PlainText
                        color: theme.dimOn(card.color)
                        font.pointSize: theme.fontSmall
                        font.features: { "tnum": 1 }
                    }
                    TpButton {
                        flat: true
                        size: "sm"
                        glyph: theme.glyphs.reset
                        fallback: "↺"
                        tip: i18n.tr("Reset options of this section to default")
                        visible: headerBlock.customizedCount > 0
                        opacity: headerArea.containsMouse || hovered || visualFocus ? 1 : 0  // revealed: hover, focus, current
                        onClicked: backend.resetSection(row.model.key)
                    }
                    TpSwitch {
                        visible: headerBlock.toggle !== ""
                        enabled: !row.locked
                        checkable: false  // follows backend
                        checked: headerBlock.toggleChecked
                        text: headerBlock.toggleChecked ? i18n.tr("Enabled") : i18n.tr("Disabled")
                        tip: row.label
                        onClicked: backend.setBool(headerBlock.toggle, !headerBlock.toggleChecked)
                        Accessible.role: Accessible.CheckBox
                        Accessible.name: row.label
                        Accessible.checked: headerBlock.toggleChecked
                    }
                }
            }
        }

        // Display order
        Loader {
            id: orderLoader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.space4
            anchors.leftMargin: theme.em * 0.9
            active: row.rowType === "order"
            sourceComponent: ColumnLayout {
                id: orderBlock
                readonly property var orders: row.model.orders  // one model read (not one per item binding)
                spacing: 2  // drag step below counts it
                Text {
                    Layout.fillWidth: true
                    text: row.help !== "" ? row.help
                                                : i18n.tr("Order of shown items, top first: drag them, or use the arrows.")
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    wrapMode: Text.WordWrap
                }
                Repeater {
                    model: orderBlock.orders
                    Rectangle {
                        id: orderItem
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        implicitHeight: Math.round(theme.rowCompact)
                        radius: theme.radiusMd
                        property real shift: 0  // dragged distance
                        z: dragger.active ? 10 : 0
                        color: dragger.active ? theme.surfaceFlyout : orderArea.containsMouse ? theme.hover : theme.surfaceCard
                        border.width: dragger.active ? 1 : 0
                        border.color: theme.accent
                        transform: Translate { y: dragger.active ? orderItem.shift : 0 }
                        MouseArea {
                            id: orderArea
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.NoButton
                            cursorShape: dragger.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                        }
                        DragHandler {  // dropped at the place it is dragged to
                            id: dragger
                            target: null
                            xAxis.enabled: false
                            onActiveTranslationChanged: if (active) orderItem.shift = activeTranslation.y
                            onActiveChanged: {
                                if (active)
                                    return
                                var step = orderItem.height + 2
                                var place = Math.max(0, Math.min(orderBlock.orders.length - 1,
                                                                 orderItem.index + Math.round(orderItem.shift / step)))
                                orderItem.shift = 0
                                if (place === orderItem.index)
                                    return
                                if (row.model.option !== "")  // list option (class order...)
                                    backend.placeListItem(row.model.overlay, row.model.option, orderItem.modelData.key, place)
                                else
                                    backend.placeOrder(row.model.overlay, orderItem.modelData.key, place)
                            }
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: theme.space2
                            spacing: theme.space3
                            Text {
                                Layout.preferredWidth: theme.em * 1.4
                                text: orderItem.index + 1
                                textFormat: Text.PlainText
                                color: theme.dimOn(orderItem.color)
                                horizontalAlignment: Text.AlignRight
                                font.features: { "tnum": 1 }
                            }
                            Rectangle {  // moved, not saved yet
                                Layout.preferredWidth: Math.round(theme.em * 0.4)
                                Layout.preferredHeight: Layout.preferredWidth
                                radius: width / 2
                                color: orderItem.modelData.changed ? theme.accent : "transparent"
                            }
                            TpSwitch {  // item shown or hidden (column of driver lists)
                                visible: orderItem.modelData.toggle !== ""
                                checkable: false  // follows backend
                                checked: orderItem.modelData.checked
                                implicitHeight: theme.controlHeightSm
                                tip: i18n.tr("Show or hide this column")
                                onClicked: backend.setBool(orderItem.modelData.toggle, !orderItem.modelData.checked)
                                Accessible.role: Accessible.CheckBox
                                Accessible.name: orderItem.modelData.label
                                Accessible.checked: orderItem.modelData.checked
                            }
                            Text {  // column on but not shown: why, after its name
                                Layout.fillWidth: true
                                text: orderItem.modelData.note
                                      ? orderItem.modelData.label + "  ·  " + orderItem.modelData.note
                                      : orderItem.modelData.label
                                textFormat: Text.PlainText
                                color: orderItem.modelData.checked && !orderItem.modelData.note ? theme.text : theme.dimOn(orderItem.color)
                                elide: Text.ElideRight
                            }
                            TpButton {
                                flat: true
                                size: "sm"
                                glyph: ""  // chevron up
                                fallback: "▲"
                                tip: i18n.tr("Move Up")
                                enabled: orderItem.index > 0
                                onClicked: row.moveItem(orderItem.modelData.key, -1)
                            }
                            TpButton {
                                flat: true
                                size: "sm"
                                glyph: ""  // chevron down
                                fallback: "▼"
                                tip: i18n.tr("Move Down")
                                enabled: orderItem.index < orderBlock.orders.length - 1
                                onClicked: row.moveItem(orderItem.modelData.key, 1)
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: theme.space1
                    Item { Layout.fillWidth: true }
                    TpButton {
                        flat: true
                        size: "sm"
                        glyph: theme.glyphs.reset
                        text: i18n.tr("Default Order")
                        tip: i18n.tr("Back to default order (saved with Apply)")
                        enabled: row.modified
                        onClicked: row.model.option !== "" ? backend.resetList(row.model.overlay, row.model.option)
                                                           : backend.resetOrder(row.model.overlay)
                    }
                }
            }
        }

        // Option
        Loader {
            id: optionLoader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: theme.em * 0.9
            anchors.rightMargin: theme.space3
            active: row.rowType === "option"
            sourceComponent: RowLayout {
                spacing: theme.space3

                function reset() {
                    editor.reset()
                }
                function release() {
                    editor.release()
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: row.marked !== "" ? row.marked : row.label
                        textFormat: row.marked !== "" ? Text.StyledText : Text.PlainText
                        // Doing nothing with current values: dim text (readable, still editable)
                        color: row.dimmed ? theme.dimText : theme.text
                        Behavior on color { enabled: row.settled; ColorAnimation { duration: theme.motionBase } }
                        font.weight: Font.Medium
                        font.italic: row.locked
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        id: helpText
                        Layout.fillWidth: true
                        visible: row.help !== ""
                        text: row.help
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        MouseArea { id: helpArea; anchors.fill: parent; hoverEnabled: helpText.truncated; acceptedButtons: Qt.NoButton }
                        ToolTip.visible: helpText.truncated && helpArea.containsMouse
                        ToolTip.text: row.help
                        ToolTip.delay: theme.tipDelay
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: row.note !== "" || row.hint !== ""
                        text: [row.hint, row.note].filter(function(part) { return part !== "" }).join("  ·  ")
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        font.italic: true
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: row.error !== ""
                        text: "⚠ " + row.error
                        textFormat: Text.PlainText
                        color: theme.loss
                        font.pointSize: theme.fontSmall
                        wrapMode: Text.WordWrap
                    }
                }

                TpOptionEditor {
                    id: editor
                    Layout.preferredWidth: row.editorWidth
                    Layout.alignment: Qt.AlignVCenter
                    enabled: !row.locked
                    kind: row.kind
                    label: row.label
                    checked: row.checked
                    // Roles of one kind read only by rows of that kind (one model read each, not for every row)
                    readonly property bool choosing: row.kind === "choice" || row.kind === "font"
                    readonly property bool numeric: row.kind === "integer" || row.kind === "float"
                    choices: choosing ? row.model.choices : []
                    choiceIndex: choosing ? row.model.choiceIndex : -1
                    text: row.text
                    number: numeric ? row.model.number : 0
                    decimals: numeric ? row.model.decimals : 0
                    step: numeric ? row.model.step : 1
                    minimum: numeric ? row.model.minimum : 0
                    maximum: numeric ? row.model.maximum : 0
                    range: numeric ? row.model.rangeText || "" : ""
                    color: row.kind === "color" ? row.model.color : ""
                    invalid: row.error !== ""
                    table: row.kind === "text" && row.model.table
                    onSwitched: function(checked) { backend.setBool(row.model.key, checked) }
                    onChosen: function(index) { backend.setChoice(row.model.key, index) }
                    onNumberEdited: function(value) { backend.setNumber(row.model.key, value) }
                    onTextTyped: function(text) { backend.typeText(row.model.key, text) }
                    onTextCommitted: function(text) { backend.setText(row.model.key, text) }
                    onReverted: backend.revertOption(row.model.key)
                    onColorRequested: backend.pickColor(row.model.key)
                    onBrowseRequested: backend.browse(row.model.key)
                    onFolderRequested: backend.openFolder(row.model.key)
                    onTableRequested: backend.editTable(row.model.key)
                }

                TpButton {
                    Layout.alignment: Qt.AlignVCenter
                    flat: true
                    size: "sm"
                    glyph: "\uE7A7"  // undo
                    fallback: "↺"
                    tip: (hovered || visualFocus) && row.model.defaultText !== ""
                         ? i18n.trm("Back to default: " + row.model.defaultText) : i18n.tr("Reset to Default")
                    enabled: row.modified && !row.locked
                    opacity: row.modified ? 1 : 0  // room kept: editors stay aligned (disabled: no Tab stop)
                    onClicked: backend.resetOption(row.model.key)
                }
                TpButton {
                    id: moreButton
                    Layout.alignment: Qt.AlignVCenter
                    flat: true
                    size: "sm"
                    glyph: "\uE712"  // more
                    fallback: "⋯"
                    tip: i18n.tr("More actions")
                    opacity: hovered || visualFocus || row.rowHovered ? 1 : 0  // revealed: hover, focus, current
                    onClicked: row.openMenu(moreButton, -1, -1)
                }
            }
        }
    }
    HoverHandler { id: rowHover }
}
