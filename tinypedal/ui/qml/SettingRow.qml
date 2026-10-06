import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Option row of Settings page: name, description & editor matching the option kind (switch, choice,
// number, color, text, folder, image), reset to default when changed from it. Rows of a group form a
// card, the group title above its first row (with a notice preview in Notification category).
// Unsaved edits are marked by an accent bar, invalid values by a red reason under the name.
Item {
    id: row
    required property int index
    required property string key
    required property string label
    required property string help
    required property string kind
    required property string group
    required property bool first
    required property bool last
    required property bool checked
    required property var choices
    required property int choiceIndex
    required property string text
    required property real number
    required property int decimals
    required property real step
    required property real minimum
    required property real maximum
    required property string color
    required property bool modified
    required property bool changed
    required property string error
    required property string defaultText
    required property string applies  // "restart", "next_start" or ""
    property var preview: null  // notice preview of group: {text, color, background}
    readonly property real editorWidth: Math.min(theme.em * 19, Math.max(theme.em * 11, width * 0.42))

    function flash() {
        flashAnimation.restart()
    }
    function holdsFocus() {
        for (var item = Window.activeFocusItem; item; item = item.parent)
            if (item === row) return true
        return false
    }

    // Row of a ListView with reuseItems: required properties fed again for another option, editor Loader
    // follows kind (same kind: editor kept, its bindings read the new option)
    ListView.onPooled: {
        if (holdsFocus())
            ListView.view.forceActiveFocus()  // field left (typed text taken) before it shows another option
        flashAnimation.stop()
        flashRect.opacity = 0
    }

    implicitHeight: header.height + card.height

    // Group title
    Item {
        id: header
        width: parent.width
        height: !row.first ? 0 : row.group === "" ? Math.round(theme.em * 0.4)
              : Math.round(theme.em * (row.index === 0 ? 2.2 : 3))
        visible: row.first && row.group !== ""
        Text {
            anchors.left: parent.left
            anchors.leftMargin: theme.em * 0.2
            anchors.bottom: parent.bottom
            anchors.bottomMargin: theme.em * 0.45
            text: row.group
            color: theme.text
            font.pointSize: theme.fontPoint * 1.05
            font.weight: Font.DemiBold
        }
        Rectangle {
            visible: row.preview !== null && row.preview !== undefined
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: theme.em * 0.35
            height: Math.round(theme.em * 1.6)
            width: previewText.implicitWidth + theme.em * 1.4
            radius: theme.em * 0.3
            color: row.preview && row.preview.background !== "" ? row.preview.background : "transparent"
            border.width: 1
            border.color: theme.border
            Text {
                id: previewText
                anchors.centerIn: parent
                text: row.preview ? row.preview.text : ""
                color: row.preview && row.preview.color !== "" ? row.preview.color : theme.text
                font.pointSize: theme.fontPoint * 0.9
            }
            MouseArea { id: previewArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            ToolTip.visible: previewArea.containsMouse
            ToolTip.text: i18n.tr("Preview of the notice")
            ToolTip.delay: 500
        }
    }

    Rectangle {
        id: card
        y: header.height
        width: parent.width
        height: Math.max(content.implicitHeight + theme.em * 1.0, theme.em * 3)
        radius: theme.em * 0.7
        color: theme.base

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
            color: theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border
            opacity: 0.8
        }
        Rectangle {  // unsaved edit
            visible: row.changed
            x: 0
            width: Math.round(theme.em * 0.22)
            height: parent.height - theme.em * 0.8
            anchors.verticalCenter: parent.verticalCenter
            radius: width / 2
            color: row.error !== "" ? theme.loss : theme.accent
        }
        Rectangle {  // flash when opened from option search
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

        RowLayout {
            id: content
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: theme.em * 0.9
            anchors.rightMargin: theme.em * 0.5
            spacing: theme.em * 0.6

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.4
                    Text {
                        Layout.fillWidth: true
                        Layout.maximumWidth: implicitWidth
                        text: row.label
                        color: theme.text
                        font.weight: Font.Medium
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Pill {
                        visible: row.applies !== ""
                        text: row.applies === "restart" ? i18n.tr("Restart required") : i18n.tr("Next start")
                        tint: row.applies === "restart" ? theme.warning : theme.dimText
                        tip: row.applies === "restart" ? i18n.tr("Applied once Modern Tiny Pedals restarts (offered after Apply)")
                                                       : i18n.tr("Used when Modern Tiny Pedals starts")
                    }
                    Item { Layout.fillWidth: true }
                }
                Text {
                    id: helpText
                    Layout.fillWidth: true
                    visible: row.help !== ""
                    text: row.help
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.85
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    MouseArea { id: helpArea; anchors.fill: parent; hoverEnabled: helpText.truncated; acceptedButtons: Qt.NoButton }
                    ToolTip.visible: helpText.truncated && helpArea.containsMouse
                    ToolTip.text: row.help
                    ToolTip.delay: 500
                }
                Text {
                    Layout.fillWidth: true
                    visible: row.error !== ""
                    text: "⚠ " + row.error
                    color: theme.loss
                    font.pointSize: theme.fontPoint * 0.85
                    wrapMode: Text.WordWrap
                }
            }

            Loader {
                id: editor
                Layout.preferredWidth: row.editorWidth
                Layout.alignment: Qt.AlignVCenter
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
                tip: row.defaultText !== "" ? i18n.trm("Back to default: " + row.defaultText) : i18n.tr("Reset to Default")
                implicitHeight: Math.round(theme.em * 1.9)
                enabled: row.modified
                opacity: row.modified ? 0.85 : 0  // room kept: editors stay aligned
                onClicked: backend.resetOption(row.key)
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
                onClicked: backend.setBool(row.key, !row.checked)
                Accessible.role: Accessible.CheckBox
                Accessible.name: row.label
                Accessible.checked: row.checked
            }
        }
    }
    Component {
        id: choiceEditor
        TpCombo {
            model: row.choices
            currentIndex: row.choiceIndex
            tip: row.label
            onActivated: function(index) { backend.setChoice(row.key, index) }
        }
    }
    Component {
        id: numberEditor
        Item {
            implicitHeight: numberField.implicitHeight
            NumberField {
                id: numberField
                anchors.right: parent.right
                width: Math.min(parent.width, theme.em * 9)
                value: row.number
                decimals: row.decimals
                step: row.step
                minimum: row.minimum
                maximum: row.maximum
                tip: row.label
                onEdited: function(value) { backend.setNumber(row.key, value) }
                // Number taken while typing (unsaved changes bar, Apply): out of range marked, clamped when left
                Keys.onEscapePressed: backend.revertOption(row.key)  // saved value back (field handles Esc too)
                onTextEdited: {
                    var number = parseFloat(text.replace(",", ".").replace(/\s/g, ""))
                    if (!isNaN(number))
                        backend.typeText(row.key, text)
                }
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
                color: row.color !== "" ? row.color : "transparent"
                border.width: 1
                border.color: swatchArea.containsMouse ? theme.accent : theme.border
                Text {
                    anchors.centerIn: parent
                    visible: row.color === ""
                    text: "?"
                    color: theme.loss
                }
                MouseArea {
                    id: swatchArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: backend.pickColor(row.key)
                }
                ToolTip.visible: swatchArea.containsMouse
                ToolTip.text: i18n.tr("Select Color")
                ToolTip.delay: 500
                Accessible.role: Accessible.Button
                Accessible.name: i18n.tr("Select Color")
            }
            TpTextField {
                Layout.fillWidth: true
                text: row.text
                invalid: row.error !== ""
                font.features: { "tnum": 1 }
                tip: row.label
                maximumLength: 9
                onTextEdited: backend.typeText(row.key, text)
                onEditingFinished: backend.setText(row.key, text)
                onEscaped: { backend.revertOption(row.key); text = Qt.binding(function() { return row.text }) }
            }
        }
    }
    Component {
        id: textEditor
        TpTextField {
            text: row.text
            invalid: row.error !== ""
            tip: row.label
            onTextEdited: backend.typeText(row.key, text)
            onEditingFinished: backend.setText(row.key, text)
            onEscaped: { backend.revertOption(row.key); text = Qt.binding(function() { return row.text }) }
        }
    }
    Component {
        id: pathEditor
        RowLayout {
            spacing: theme.em * 0.3
            TpTextField {
                Layout.fillWidth: true
                text: row.text
                invalid: row.error !== ""
                tip: row.label
                onTextEdited: backend.typeText(row.key, text)
                onEditingFinished: backend.setText(row.key, text)
                onEscaped: { backend.revertOption(row.key); text = Qt.binding(function() { return row.text }) }
            }
            TpButton {
                glyph: ""  // folder open
                text: theme.iconFont === "" ? "..." : ""
                tip: row.kind === "path" ? i18n.tr("Choose Folder...") : i18n.tr("Choose File...")
                implicitHeight: Math.round(theme.em * 2.05)
                onClicked: backend.browse(row.key)
            }
            TpButton {
                visible: row.kind === "path"
                flat: true
                glyph: ""  // open folder
                text: theme.iconFont === "" ? "↗" : ""
                tip: i18n.tr("Open Folder")
                implicitHeight: Math.round(theme.em * 2.05)
                onClicked: backend.openFolder(row.key)
            }
        }
    }
}
