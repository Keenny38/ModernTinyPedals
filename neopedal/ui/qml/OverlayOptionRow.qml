import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Row of Overlay Options page: section header (title, item on/off switch, collapse, reset), option
// (name, description, editor matching its kind, reset & more actions) or display order list. Rows of a
// section form one card. Unsaved edits are marked by an accent bar, invalid values by a red reason,
// options of an item that is off are dimmed (still editable), options set by a profile are locked.
// Only the block of the row type is made (Loader per block). Rows are reused by the ListView (reuseItems):
// model fed again for another row, block & editor kept when of the same type & kind, editor reset on reuse.
Item {
    id: row
    required property var model
    required property int index
    // Roles read by many bindings: fed once (and again on reuse or change) instead of a model read per binding
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
              : row.rowType === "order" ? orderLoader.implicitHeight + theme.em * 1.2
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
            visible: !row.model.last
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
            color: theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border
            opacity: 0.8
        }
        Rectangle {  // unsaved edit
            visible: row.model.changed || (row.rowType === "header" && row.model.collapsed && row.model.changedCount > 0)
            width: Math.round(theme.em * 0.22)
            height: parent.height - theme.em * 0.8
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
                MouseArea {
                    id: headerArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: backend.filtering ? Qt.ArrowCursor : Qt.PointingHandCursor
                    onClicked: if (!backend.filtering) backend.toggleSection(row.model.key)
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.6
                    anchors.rightMargin: theme.em * 0.5
                    spacing: theme.em * 0.5
                    Icon {
                        visible: !backend.filtering
                        glyph: ""  // chevron down
                        size: theme.em * 0.7
                        color: theme.dimText
                        rotation: row.model.collapsed ? -90 : 0
                        Behavior on rotation { enabled: row.settled; NumberAnimation { duration: theme.motionBase } }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: row.model.title
                        color: theme.text
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        opacity: row.model.toggle !== "" && !row.model.toggleChecked ? 0.6 : 1
                    }
                    Pill {
                        visible: row.model.customizedCount > 0
                        text: visible ? i18n.trm("Modified: " + row.model.customizedCount) : ""
                        tip: i18n.tr("Options changed from default")
                    }
                    Text {
                        visible: row.model.collapsed
                        text: row.model.count
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        font.features: { "tnum": 1 }
                    }
                    TpButton {
                        flat: true
                        glyph: ""  // undo
                        text: theme.iconFont === "" ? "↺" : ""
                        tip: i18n.tr("Reset options of this section to default")
                        implicitHeight: Math.round(theme.em * 1.9)
                        visible: row.model.customizedCount > 0
                        opacity: headerArea.containsMouse || hovered ? 0.9 : 0.35
                        onClicked: backend.resetSection(row.model.key)
                    }
                    TpSwitch {
                        visible: row.model.toggle !== ""
                        enabled: !row.locked
                        checkable: false  // follows backend
                        checked: row.model.toggleChecked
                        text: row.model.toggleChecked ? i18n.tr("On") : i18n.tr("Off")
                        tip: row.label
                        onClicked: backend.setBool(row.model.toggle, !row.model.toggleChecked)
                        Accessible.role: Accessible.CheckBox
                        Accessible.name: row.label
                        Accessible.checked: row.model.toggleChecked
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
            anchors.margins: theme.em * 0.6
            anchors.leftMargin: theme.em * 0.9
            active: row.rowType === "order"
            sourceComponent: ColumnLayout {
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: row.help !== "" ? row.help
                                                : i18n.tr("Order of shown items, top first: drag them, or use the arrows.")
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    wrapMode: Text.WordWrap
                }
                Repeater {
                    model: row.model.orders
                    Rectangle {
                        id: orderItem
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        implicitHeight: Math.round(theme.em * 2.1)
                        radius: theme.radiusMd
                        property real shift: 0  // dragged distance
                        z: dragger.active ? 10 : 0
                        color: dragger.active ? theme.raised : orderArea.containsMouse ? theme.hover : "transparent"
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
                                var place = Math.max(0, Math.min(row.model.orders.length - 1,
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
                            anchors.leftMargin: theme.em * 0.3
                            spacing: theme.em * 0.5
                            Text {
                                Layout.preferredWidth: theme.em * 1.4
                                text: orderItem.index + 1
                                color: theme.dimText
                                horizontalAlignment: Text.AlignRight
                                font.features: { "tnum": 1 }
                            }
                            Rectangle {
                                Layout.preferredWidth: Math.round(theme.em * 0.4)
                                Layout.preferredHeight: Layout.preferredWidth
                                radius: width / 2
                                color: theme.accent
                                opacity: orderItem.modelData.changed ? 1 : 0
                            }
                            TpSwitch {  // item shown or hidden (column of driver lists)
                                visible: orderItem.modelData.toggle !== ""
                                checkable: false  // follows backend
                                checked: orderItem.modelData.checked
                                implicitHeight: Math.round(theme.em * 1.8)
                                tip: i18n.tr("Show or hide this column")
                                onClicked: backend.setBool(orderItem.modelData.toggle, !orderItem.modelData.checked)
                                Accessible.role: Accessible.CheckBox
                                Accessible.name: orderItem.modelData.label
                                Accessible.checked: orderItem.modelData.checked
                            }
                            Text {
                                Layout.fillWidth: true
                                text: orderItem.modelData.label
                                color: orderItem.modelData.checked ? theme.text : theme.dimText
                                elide: Text.ElideRight
                            }
                            TpButton {
                                flat: true
                                glyph: ""  // chevron up
                                text: theme.iconFont === "" ? "▲" : ""
                                tip: i18n.tr("Move Up")
                                implicitHeight: Math.round(theme.em * 1.8)
                                enabled: orderItem.index > 0
                                onClicked: row.moveItem(orderItem.modelData.key, -1)
                            }
                            TpButton {
                                flat: true
                                glyph: ""  // chevron down
                                text: theme.iconFont === "" ? "▼" : ""
                                tip: i18n.tr("Move Down")
                                implicitHeight: Math.round(theme.em * 1.8)
                                enabled: orderItem.index < row.model.orders.length - 1
                                onClicked: row.moveItem(orderItem.modelData.key, 1)
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: theme.em * 0.2
                    Item { Layout.fillWidth: true }
                    TpButton {
                        flat: true
                        glyph: ""  // undo
                        text: i18n.tr("Default Order")
                        tip: i18n.tr("Back to default order (saved with Apply)")
                        implicitHeight: Math.round(theme.em * 1.9)
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
            anchors.rightMargin: theme.em * 0.4
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
                    opacity: row.dimmed ? 0.55 : 1
                    Behavior on opacity { enabled: row.settled; NumberAnimation { duration: theme.motionBase } }
                    Text {
                        Layout.fillWidth: true
                        text: row.label
                        color: theme.text
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
                    opacity: row.dimmed ? 0.6 : 1  // still editable
                    Behavior on opacity { enabled: row.settled; NumberAnimation { duration: theme.motionBase } }
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
                    glyph: ""  // undo
                    text: theme.iconFont === "" ? "↺" : ""
                    tip: (hovered || visualFocus) && row.model.defaultText !== ""
                         ? i18n.trm("Back to default: " + row.model.defaultText) : i18n.tr("Reset to Default")
                    implicitHeight: Math.round(theme.em * 1.9)
                    enabled: row.modified && !row.locked
                    opacity: row.modified ? 0.85 : 0  // room kept: editors stay aligned
                    onClicked: backend.resetOption(row.model.key)
                }
                TpButton {
                    id: moreButton
                    Layout.alignment: Qt.AlignVCenter
                    flat: true
                    glyph: ""  // more
                    text: theme.iconFont === "" ? "..." : ""
                    tip: i18n.tr("More actions")
                    implicitHeight: Math.round(theme.em * 1.9)
                    opacity: hovered ? 0.9 : 0.5
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
                onEdited: function(value) { backend.setNumber(row.model.key, value) }
            }
        }
    }
    Component {
        id: colorEditor
        RowLayout {
            function reset() {
                colorField.text = Qt.binding(function() { return row.text })
            }
            spacing: theme.em * 0.4
            Rectangle {
                Layout.preferredWidth: Math.round(theme.em * 2.05)
                Layout.preferredHeight: Layout.preferredWidth
                radius: theme.radiusMd
                color: row.model.color !== "" ? row.model.color : "transparent"
                border.width: 1
                border.color: swatchArea.containsMouse ? theme.accent : theme.border
                Text {
                    anchors.centerIn: parent
                    visible: row.model.color === ""
                    text: "?"
                    color: theme.loss
                }
                MouseArea {
                    id: swatchArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: backend.pickColor(row.model.key)
                }
                ToolTip.visible: swatchArea.containsMouse
                ToolTip.text: i18n.tr("Select Color")
                ToolTip.delay: theme.tipDelay
                Accessible.role: Accessible.Button
                Accessible.name: i18n.tr("Select Color")
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
            spacing: theme.em * 0.3
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
                text: theme.iconFont === "" ? "..." : ""
                tip: i18n.tr("Edit as a table")
                implicitHeight: Math.round(theme.em * 2.05)
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
            spacing: theme.em * 0.3
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
                text: theme.iconFont === "" ? "..." : ""
                tip: row.kind === "path" ? i18n.tr("Choose Folder...") : i18n.tr("Choose File...")
                implicitHeight: Math.round(theme.em * 2.05)
                onClicked: backend.browse(row.model.key)
            }
        }
    }
}
