import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Editor of one option, made for its kind: switch (bool), choice list (choice, font), number field (integer,
// float), color swatch & code (color), path field with Browse (and Open Folder for folders: path), text field
// (with a table button when table is set). Same editor, sizes & keys on the Settings and Overlay Options pages.
// Values come from the row, edits go to the page backend as signals:
//   - typed text is taken at each key (textTyped: unsaved changes bar, Apply & Ctrl+S see it), checked as typed;
//   - Enter or field left: textCommitted; Esc: reverted (backend puts the saved value back, field shows it).
// reset(): row reused for another option (fields show its value), release(): before (choice list closed).
//   TpOptionEditor { kind: row.kind; text: row.text; onTextTyped: function(text) { backend.typeText(row.key, text) } }
Loader {
    id: editor
    property string kind: ""
    property string label: ""  // option name: tooltips & screen readers
    property bool checked: false
    property var choices: []
    property int choiceIndex: -1
    property string text: ""
    property real number: 0
    property int decimals: 0
    property real step: 1
    property real minimum: 0
    property real maximum: 0
    property string range: ""  // allowed values ("Allowed: 0 - 10"), "" made from minimum & maximum
    property string color: ""  // swatch color, "" for an invalid code ("?" shown)
    property bool invalid: false
    property bool table: false  // text option edited as a table too (button beside the field)

    signal switched(bool checked)
    signal chosen(int index)
    signal numberEdited(real value)
    signal textTyped(string text)
    signal textCommitted(string text)
    signal reverted()
    signal colorRequested()
    signal browseRequested()
    signal folderRequested()
    signal tableRequested()

    function reset() {
        if (item && item.reset)
            item.reset()
    }
    function release() {
        if (item && item.release)
            item.release()
    }

    sourceComponent: kind === "bool" ? boolEditor
                   : kind === "choice" || kind === "font" ? choiceEditor
                   : kind === "integer" || kind === "float" ? numberEditor
                   : kind === "color" ? colorEditor
                   : kind === "path" || kind === "image" || kind === "file" ? pathEditor
                   : textEditor

    Component {
        id: boolEditor
        Item {
            implicitHeight: switchItem.implicitHeight
            TpSwitch {
                id: switchItem
                anchors.right: parent.right
                checkable: false  // follows backend
                checked: editor.checked
                text: editor.checked ? i18n.tr("Enabled") : i18n.tr("Disabled")
                onClicked: editor.switched(!editor.checked)
                Accessible.role: Accessible.CheckBox
                Accessible.name: editor.label
                Accessible.checked: editor.checked
            }
        }
    }
    Component {
        id: choiceEditor
        TpCombo {
            id: combo
            function reset() {
                currentIndex = Qt.binding(function() { return editor.choiceIndex })
            }
            function release() {
                combo.popup.close()
            }
            model: editor.choices
            currentIndex: editor.choiceIndex
            tip: editor.label
            onActivated: function(index) { editor.chosen(index) }
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
                width: Math.min(parent.width, theme.em * 9)
                value: editor.number
                decimals: editor.decimals
                step: editor.step
                minimum: editor.minimum
                maximum: editor.maximum
                range: editor.range
                showRange: true  // allowed values in tooltip & for screen readers, not found only by an error
                tip: editor.label
                onEdited: function(value) { editor.numberEdited(value) }
                // Typed text marked invalid, clamped back to the value shown (no edit sent by field): mark cleared
                // (runs after field's own commit, which already cleared it when the number changed)
                onEditingFinished: if (editor.invalid) editor.numberEdited(numberField.value)
                // Number taken while typing (unsaved changes bar, Apply): out of range marked, clamped when left
                Keys.onEscapePressed: editor.reverted()  // saved value back (field handles Esc too)
                onTextEdited: {
                    var number = parseFloat(text.replace(",", ".").replace(/\s/g, ""))
                    if (!isNaN(number))
                        editor.textTyped(text)
                }
            }
        }
    }
    Component {
        id: colorEditor
        RowLayout {
            readonly property string swatchColor: editor.color  // color shown by the swatch ("" invalid)
            function reset() {
                colorField.text = Qt.binding(function() { return editor.text })
            }
            spacing: theme.space3
            TpColorSwatch {  // color picker (Tab, then Enter or Space)
                id: swatch
                Layout.preferredWidth: implicitWidth
                Layout.preferredHeight: implicitHeight
                color: editor.color
                onClicked: editor.colorRequested()
            }
            TpTextField {
                id: colorField
                Layout.fillWidth: true
                text: editor.text
                invalid: editor.invalid
                font.features: { "tnum": 1 }
                tip: editor.label
                maximumLength: 9
                onTextEdited: editor.textTyped(text)
                onEditingFinished: editor.textCommitted(text)
                onEscaped: { editor.reverted(); text = Qt.binding(function() { return editor.text }) }
            }
        }
    }
    Component {
        id: textEditor
        RowLayout {
            function reset() {
                textField.text = Qt.binding(function() { return editor.text })
            }
            spacing: theme.space2
            TpTextField {
                id: textField
                Layout.fillWidth: true
                text: editor.text
                invalid: editor.invalid
                tip: editor.label
                onTextEdited: editor.textTyped(text)
                onEditingFinished: editor.textCommitted(text)
                onEscaped: { editor.reverted(); text = Qt.binding(function() { return editor.text }) }
            }
            TpButton {
                visible: editor.table
                glyph: "\uE8BC"  // list
                fallback: "…"
                tip: i18n.tr("Edit as a table")
                implicitHeight: Math.round(theme.fieldHeight)  // as tall as the field
                onClicked: editor.tableRequested()
            }
        }
    }
    Component {
        id: pathEditor
        RowLayout {
            function reset() {
                pathField.text = Qt.binding(function() { return editor.text })
            }
            spacing: theme.space2
            TpTextField {
                id: pathField
                Layout.fillWidth: true
                text: editor.text
                invalid: editor.invalid
                tip: editor.label
                onTextEdited: editor.textTyped(text)
                onEditingFinished: editor.textCommitted(text)
                onEscaped: { editor.reverted(); text = Qt.binding(function() { return editor.text }) }
            }
            TpButton {
                glyph: "\uE838"  // folder open
                fallback: "…"
                tip: editor.kind === "path" ? i18n.tr("Choose Folder…") : i18n.tr("Choose File…")
                implicitHeight: Math.round(theme.fieldHeight)  // as tall as the field
                onClicked: editor.browseRequested()
            }
            TpButton {
                visible: editor.kind === "path"
                flat: true
                glyph: "\uE8DA"  // open folder
                fallback: "↗"
                tip: i18n.tr("Open Folder")
                implicitHeight: Math.round(theme.fieldHeight)  // as tall as the field
                onClicked: editor.folderRequested()
            }
        }
    }
}
