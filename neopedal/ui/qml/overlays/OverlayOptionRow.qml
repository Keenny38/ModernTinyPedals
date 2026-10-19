import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Row of Overlay Options page: section header (title, item on/off switch, collapse, reset), option
// (name, description, editor matching its kind, reset & more actions) or display order list. Rows of a
// section form one card. Unsaved edits are marked by an accent bar, invalid values by a red reason,
// options of an item that is off are in dim text (still editable), options set by a profile are locked.
// Only the block of the row type is made (Loader per block). Rows are reused by the ListView (reuseItems):
// model fed again for another row, block & editor kept when of the same type & kind, editor reset on reuse.
Item {
    id: row
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
    readonly property string rowType: model.row
    readonly property real editorWidth: Math.min(theme.em * 17, Math.max(theme.em * 10, width * 0.4))
    property bool settled: true  // height, chevron & dimming animated, not while reused for another row
    signal menuRequested(var data, Item anchor)

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
              : Math.max(optionLoader.implicitHeight + theme.em * 0.9, theme.em * 2.9)
        radius: theme.radiusXl
        color: row.rowType === "header" ? (theme.dark ? Qt.lighter(theme.base, 1.08) : Qt.darker(theme.base, 1.015)) : theme.base
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
                    anchors.rightMargin: theme.em * 0.5
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
                        color: theme.dimOn(card.color)
                        font.pointSize: theme.fontSmall
                        font.features: { "tnum": 1 }
                    }
                    TpButton {
                        flat: true
                        size: "sm"
                        glyph: ""  // undo
                        fallback: "↺"
                        tip: i18n.tr("Reset options of this section to default")
                        visible: headerBlock.customizedCount > 0
                        opacity: headerArea.containsMouse || hovered || visualFocus ? 1 : 0.5
                        onClicked: backend.resetSection(row.model.key)
                    }
                    TpSwitch {
                        visible: headerBlock.toggle !== ""
                        enabled: !row.locked
                        checkable: false  // follows backend
                        checked: headerBlock.toggleChecked
                        text: headerBlock.toggleChecked ? i18n.tr("On") : i18n.tr("Off")
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
                        color: dragger.active ? theme.raised : orderArea.containsMouse ? theme.hover : theme.base
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
                            spacing: theme.em * 0.5
                            Text {
                                Layout.preferredWidth: theme.em * 1.4
                                text: orderItem.index + 1
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
                        glyph: ""  // undo
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
                spacing: theme.em * 0.5

                function reset() {
                    if (editor.item && editor.item.reset)
                        editor.item.reset()
                }
                function release() {
                    if (editor.item && editor.item.release)
                        editor.item.release()
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: row.label
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
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        font.italic: true
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: row.error !== ""
                        text: "⚠ " + row.error
                        color: theme.loss
                        font.pointSize: theme.fontSmall
                        wrapMode: Text.WordWrap
                    }
                }

                Loader {
                    id: editor
                    Layout.preferredWidth: row.editorWidth
                    Layout.alignment: Qt.AlignVCenter
                    enabled: !row.locked
                    sourceComponent: row.kind === "bool" ? boolEditor
                                   : row.kind === "choice" || row.kind === "font" ? choiceEditor
                                   : row.kind === "integer" || row.kind === "float" ? numberEditor
                                   : row.kind === "color" ? colorEditor
                                   : row.kind === "path" || row.kind === "image" ? pathEditor
                                   : textEditor
                }

                TpButton {
                    Layout.alignment: Qt.AlignVCenter
                    flat: true
                    size: "sm"
                    glyph: ""  // undo
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
                    glyph: ""  // more
                    fallback: "⋯"
                    tip: i18n.tr("More actions")
                    opacity: hovered || visualFocus ? 1 : 0.6
                    onClicked: row.menuRequested({  // copy: row may be reused for another option while menu is open
                        key: row.model.key, option: row.model.option, modified: row.modified,
                        locked: row.locked, shared: row.model.shared, error: row.error
                    }, moreButton)
                }
            }
        }
    }

    Component {
        id: boolEditor
        Item {
            implicitHeight: switchItem.implicitHeight
            TpSwitch {
                id: switchItem
                anchors.right: parent.right
                checkable: false  // follows backend
                checked: row.checked
                text: row.checked ? i18n.tr("On") : i18n.tr("Off")
                onClicked: backend.setBool(row.model.key, !row.checked)
                Accessible.role: Accessible.CheckBox
                Accessible.name: row.label
                Accessible.checked: row.checked
            }
        }
    }
    Component {
        id: choiceEditor
        TpCombo {
            id: combo
            function reset() {
                currentIndex = Qt.binding(function() { return row.model.choiceIndex })
            }
            function release() {
                combo.popup.close()
            }
            model: row.model.choices
            currentIndex: row.model.choiceIndex
            tip: row.label
            onActivated: function(index) { backend.setChoice(row.model.key, index) }
        }
    }
    Component {
        id: numberEditor
        Item {
            function reset() {
                numberField.text = numberField.format(numberField.value)  // decimals may differ, same value
            }
            implicitHeight: numberField.implicitHeight
            NumberField {
                id: numberField
                anchors.right: parent.right
                width: Math.min(parent.width, theme.em * 8)
                value: row.model.number
                decimals: row.model.decimals
                step: row.model.step
                minimum: row.model.minimum
                maximum: row.model.maximum
                tip: row.label
                range: row.model.rangeText || ""
                onEdited: function(value) { backend.setNumber(row.model.key, value) }
            }
        }
    }
    Component {
        id: colorEditor
        RowLayout {
            id: colorBlock
            readonly property string swatchColor: row.model.color  // one model read (swatch & its text)
            function reset() {
                colorField.text = Qt.binding(function() { return row.text })
            }
            spacing: theme.space3
            AbstractButton {  // swatch: color picker (Tab, Enter / Space)
                id: swatch
                Layout.preferredWidth: Math.round(theme.fieldHeight)
                Layout.preferredHeight: Layout.preferredWidth
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                onClicked: backend.pickColor(row.model.key)
                Keys.onReturnPressed: animateClick()
                Keys.onEnterPressed: animateClick()
                Keys.onShortcutOverride: function(event) {
                    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
                        event.accepted = true
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                ToolTip.visible: hovered || visualFocus
                ToolTip.text: i18n.tr("Select Color")
                ToolTip.delay: theme.tipDelay
                Accessible.role: Accessible.Button
                Accessible.name: i18n.tr("Select Color")
                background: Rectangle {
                    radius: theme.radiusMd
                    color: colorBlock.swatchColor !== "" ? colorBlock.swatchColor : "transparent"
                    border.width: 1
                    border.color: swatch.hovered ? theme.accent : theme.border
                    FocusRing { visible: swatch.visualFocus }
                }
                contentItem: Text {
                    visible: colorBlock.swatchColor === ""
                    text: "?"
                    color: theme.loss
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            TpTextField {
                id: colorField
                Layout.fillWidth: true
                text: row.text
                invalid: row.error !== ""
                font.features: { "tnum": 1 }
                tip: row.label
                maximumLength: 9
                onEditingFinished: if (text !== row.text) backend.setText(row.model.key, text)
                onEscaped: text = Qt.binding(function() { return row.text })
            }
        }
    }
    Component {
        id: textEditor
        RowLayout {
            function reset() {
                textField.text = Qt.binding(function() { return row.text })
            }
            spacing: theme.space2
            TpTextField {
                id: textField
                Layout.fillWidth: true
                text: row.text
                invalid: row.error !== ""
                tip: row.label
                onEditingFinished: if (text !== row.text) backend.setText(row.model.key, text)
                onEscaped: text = Qt.binding(function() { return row.text })
            }
            TpButton {
                visible: row.model.table
                glyph: ""  // list
                fallback: "…"
                tip: i18n.tr("Edit as a table")
                implicitHeight: Math.round(theme.fieldHeight)
                onClicked: backend.editTable(row.model.key)
            }
        }
    }
    Component {
        id: pathEditor
        RowLayout {
            function reset() {
                pathField.text = Qt.binding(function() { return row.text })
            }
            spacing: theme.space2
            TpTextField {
                id: pathField
                Layout.fillWidth: true
                text: row.text
                invalid: row.error !== ""
                tip: row.label
                onEditingFinished: if (text !== row.text) backend.setText(row.model.key, text)
                onEscaped: text = Qt.binding(function() { return row.text })
            }
            TpButton {
                glyph: ""  // folder open
                fallback: "…"
                tip: row.kind === "path" ? i18n.tr("Choose Folder...") : i18n.tr("Choose File...")
                implicitHeight: Math.round(theme.fieldHeight)
                onClicked: backend.browse(row.model.key)
            }
        }
    }
}
