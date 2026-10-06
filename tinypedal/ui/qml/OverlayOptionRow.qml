import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Row of Overlay Options page: section header (title, item on/off switch, collapse, reset), option
// (name, description, editor matching its kind, reset & more actions) or display order list. Rows of a
// section form one card. Unsaved edits are marked by an accent bar, invalid values by a red reason,
// options of an item that is off are dimmed (still editable), options set by a profile are locked.
Item {
    id: row
    required property var model
    required property int index
    readonly property string rowType: model.row
    readonly property real editorWidth: Math.min(theme.em * 17, Math.max(theme.em * 10, width * 0.4))
    signal menuRequested(var data, Item anchor)

    function flash() {
        flashAnimation.restart()
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
              : row.rowType === "order" ? orderColumn.implicitHeight + theme.em * 1.2
              : Math.max(optionContent.implicitHeight + theme.em * 0.9, theme.em * 2.9)
        radius: theme.em * 0.7
        color: row.rowType === "header" ? (theme.dark ? Qt.lighter(theme.base, 1.08) : Qt.darker(theme.base, 1.015)) : theme.base
        Behavior on height { enabled: row.rowType === "order"; NumberAnimation { duration: 150 } }

        // Square corners between rows of a card
        Rectangle {
            visible: !row.model.first
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
            visible: !row.model.first
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
            color: row.model.error !== "" ? theme.loss : theme.accent
        }
        Rectangle {  // flash when opened at an option
            id: flashRect
            anchors.fill: parent
            radius: parent.radius
            color: theme.accent
            opacity: 0
            SequentialAnimation {
                id: flashAnimation
                NumberAnimation { target: flashRect; property: "opacity"; to: 0.28; duration: 180 }
                PauseAnimation { duration: 350 }
                NumberAnimation { target: flashRect; property: "opacity"; to: 0; duration: 700; easing.type: Easing.InOutQuad }
            }
        }

        // Section header
        MouseArea {
            id: headerArea
            visible: row.rowType === "header"
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: backend.filtering ? Qt.ArrowCursor : Qt.PointingHandCursor
            onClicked: if (!backend.filtering) backend.toggleSection(row.model.key)
        }
        RowLayout {
            visible: row.rowType === "header"
            anchors.fill: parent
            anchors.leftMargin: theme.em * 0.6
            anchors.rightMargin: theme.em * 0.5
            spacing: theme.em * 0.45
            Icon {
                visible: !backend.filtering
                glyph: ""  // chevron down
                size: theme.em * 0.7
                color: theme.dimText
                rotation: row.model.collapsed ? -90 : 0
                Behavior on rotation { NumberAnimation { duration: 150 } }
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
                text: i18n.trm("Modified: " + row.model.customizedCount)
                tip: i18n.tr("Options changed from default")
            }
            Text {
                visible: row.model.collapsed
                text: row.model.count
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
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
                enabled: !row.model.locked
                checkable: false  // follows backend
                checked: row.model.toggleChecked
                text: row.model.toggleChecked ? i18n.tr("On") : i18n.tr("Off")
                tip: row.model.label
                onClicked: backend.setBool(row.model.toggle, !row.model.toggleChecked)
                Accessible.role: Accessible.CheckBox
                Accessible.name: row.model.label
                Accessible.checked: row.model.toggleChecked
            }
        }

        // Display order
        ColumnLayout {
            id: orderColumn
            visible: row.rowType === "order"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.em * 0.6
            anchors.leftMargin: theme.em * 0.9
            spacing: 2
            Text {
                Layout.fillWidth: true
                text: row.model.help !== "" ? row.model.help
                                            : i18n.tr("Order of shown items, top first: drag them, or use the arrows.")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                wrapMode: Text.WordWrap
            }
            Repeater {
                model: row.rowType === "order" ? row.model.orders : []
                Rectangle {
                    id: orderItem
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: Math.round(theme.em * 2.1)
                    radius: theme.em * 0.4
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
                            if (place !== orderItem.index)
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
                            onClicked: backend.moveOrder(row.model.overlay, orderItem.modelData.key, -1)
                        }
                        TpButton {
                            flat: true
                            glyph: ""  // chevron down
                            text: theme.iconFont === "" ? "▼" : ""
                            tip: i18n.tr("Move Down")
                            implicitHeight: Math.round(theme.em * 1.8)
                            enabled: orderItem.index < row.model.orders.length - 1
                            onClicked: backend.moveOrder(row.model.overlay, orderItem.modelData.key, 1)
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
                    enabled: row.model.modified
                    onClicked: backend.resetOrder(row.model.overlay)
                }
            }
        }

        // Option
        RowLayout {
            id: optionContent
            visible: row.rowType === "option"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: theme.em * 0.9
            anchors.rightMargin: theme.em * 0.4
            spacing: theme.em * 0.5

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                opacity: row.model.dimmed ? 0.55 : 1
                Behavior on opacity { NumberAnimation { duration: 150 } }
                Text {
                    Layout.fillWidth: true
                    text: row.model.label
                    color: theme.text
                    font.weight: Font.Medium
                    font.italic: row.model.locked
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                Text {
                    id: helpText
                    Layout.fillWidth: true
                    visible: row.model.help !== ""
                    text: row.model.help
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.85
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    MouseArea { id: helpArea; anchors.fill: parent; hoverEnabled: helpText.truncated; acceptedButtons: Qt.NoButton }
                    ToolTip.visible: helpText.truncated && helpArea.containsMouse
                    ToolTip.text: row.model.help
                    ToolTip.delay: 500
                }
                Text {
                    Layout.fillWidth: true
                    visible: row.model.note !== "" || row.model.hint !== ""
                    text: [row.model.hint, row.model.note].filter(function(part) { return part !== "" }).join("  ·  ")
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.85
                    font.italic: true
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: row.model.error !== ""
                    text: "⚠ " + row.model.error
                    color: theme.loss
                    font.pointSize: theme.fontPoint * 0.85
                    wrapMode: Text.WordWrap
                }
            }

            Loader {
                id: editor
                active: row.rowType === "option"
                Layout.preferredWidth: row.editorWidth
                Layout.alignment: Qt.AlignVCenter
                enabled: !row.model.locked
                opacity: row.model.dimmed ? 0.6 : 1  // still editable
                Behavior on opacity { NumberAnimation { duration: 150 } }
                sourceComponent: row.model.kind === "bool" ? boolEditor
                               : row.model.kind === "choice" || row.model.kind === "font" ? choiceEditor
                               : row.model.kind === "integer" || row.model.kind === "float" ? numberEditor
                               : row.model.kind === "color" ? colorEditor
                               : row.model.kind === "path" || row.model.kind === "image" ? pathEditor
                               : textEditor
            }

            TpButton {
                Layout.alignment: Qt.AlignVCenter
                flat: true
                glyph: ""  // undo
                text: theme.iconFont === "" ? "↺" : ""
                tip: row.model.defaultText !== "" ? i18n.trm("Back to default: " + row.model.defaultText) : i18n.tr("Reset to Default")
                implicitHeight: Math.round(theme.em * 1.9)
                enabled: row.model.modified && !row.model.locked
                opacity: row.model.modified ? 0.85 : 0  // room kept: editors stay aligned
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
                onClicked: row.menuRequested(row.model, moreButton)
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
                checked: row.model.checked
                text: row.model.checked ? i18n.tr("On") : i18n.tr("Off")
                onClicked: backend.setBool(row.model.key, !row.model.checked)
                Accessible.role: Accessible.CheckBox
                Accessible.name: row.model.label
                Accessible.checked: row.model.checked
            }
        }
    }
    Component {
        id: choiceEditor
        TpCombo {
            model: row.model.choices
            currentIndex: row.model.choiceIndex
            tip: row.model.label
            onActivated: function(index) { backend.setChoice(row.model.key, index) }
        }
    }
    Component {
        id: numberEditor
        Item {
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
                tip: row.model.label
                onEdited: function(value) { backend.setNumber(row.model.key, value) }
            }
        }
    }
    Component {
        id: colorEditor
        RowLayout {
            spacing: theme.em * 0.4
            Rectangle {
                Layout.preferredWidth: Math.round(theme.em * 2.05)
                Layout.preferredHeight: Layout.preferredWidth
                radius: theme.em * 0.4
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
                ToolTip.delay: 500
                Accessible.role: Accessible.Button
                Accessible.name: i18n.tr("Select Color")
            }
            TpTextField {
                Layout.fillWidth: true
                text: row.model.text
                invalid: row.model.error !== ""
                font.features: { "tnum": 1 }
                tip: row.model.label
                maximumLength: 9
                onEditingFinished: if (text !== row.model.text) backend.setText(row.model.key, text)
                onEscaped: text = Qt.binding(function() { return row.model.text })
            }
        }
    }
    Component {
        id: textEditor
        RowLayout {
            spacing: theme.em * 0.3
            TpTextField {
                Layout.fillWidth: true
                text: row.model.text
                invalid: row.model.error !== ""
                tip: row.model.label
                onEditingFinished: if (text !== row.model.text) backend.setText(row.model.key, text)
                onEscaped: text = Qt.binding(function() { return row.model.text })
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
            spacing: theme.em * 0.3
            TpTextField {
                Layout.fillWidth: true
                text: row.model.text
                invalid: row.model.error !== ""
                tip: row.model.label
                onEditingFinished: if (text !== row.model.text) backend.setText(row.model.key, text)
                onEscaped: text = Qt.binding(function() { return row.model.text })
            }
            TpButton {
                glyph: ""  // folder open
                text: theme.iconFont === "" ? "..." : ""
                tip: row.model.kind === "path" ? i18n.tr("Choose Folder...") : i18n.tr("Choose File...")
                implicitHeight: Math.round(theme.em * 2.05)
                onClicked: backend.browse(row.model.key)
            }
        }
    }
}
