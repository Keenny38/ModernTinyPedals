import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Option row of Settings page: name (searched words in bold), description & editor matching the option kind
// (TpOptionEditor, shared with Overlay Options), reset to default when changed from it, more actions ("⋯", right
// click or Menu key: menuRequested). Rows of a group form a card, the group title above its first row (with a
// notice preview in Notification category). Unsaved edits are marked by an accent bar, invalid values by a red
// reason under the name.
Item {
    id: row
    readonly property bool rowHovered: rowHover.hovered  // hover-revealed actions shown
    required property int index
    required property string key
    required property string option  // option key (as in setting files & documentation)
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
    required property string marked  // label with searched words in bold (rich text), "" if not searching
    property var preview: null  // notice preview of group: {text, color, background}
    readonly property real editorWidth: Math.min(theme.em * 19, Math.max(theme.em * 11, width * 0.42))
    signal menuRequested(var data, Item anchor, real x, real y)  // x < 0: menu below anchor, right aligned

    // Field being edited left first (typed text taken): an action of the menu (reset) is never undone by the
    // field committing its old text once focus moves; data copied: row may be reused while the menu is open
    function openMenu(anchor, x, y) {
        row.releaseFocus()
        row.menuRequested({ key: row.key, option: row.option, kind: row.kind, modified: row.modified }, anchor, x, y)
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

    // Row of a ListView with reuseItems: required properties fed again for another option, editor Loader
    // follows kind (same kind: editor kept, its bindings read the new option, fields reset once reused)
    ListView.onPooled: {
        if (releaseFocus())
            ListView.view.forceActiveFocus()  // before the row shows another option
        editor.release()
        flashAnimation.stop()
        flashRect.opacity = 0
    }
    ListView.onReused: {
        editor.reset()  // value of the new option shown (bindings broken by typing, same value)
    }

    implicitHeight: header.height + card.height
    // Menu key (or Shift+F10) in the row's editor: more actions
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
            row.openMenu(card, -1, -1)
            event.accepted = true
        }
    }

    // Group title
    Item {
        id: header
        width: parent.width
        height: !row.first ? 0 : row.group === "" ? Math.round(theme.em * 0.4)
              : Math.round(theme.em * (row.index === 0 ? 2.2 : 3))
        visible: row.first && row.group !== ""
        Text {
            anchors.left: parent.left
            anchors.leftMargin: theme.space1
            anchors.bottom: parent.bottom
            anchors.bottomMargin: theme.em * 0.5
            // Long (French) titles cut before the notice preview, never under it
            width: Math.min(implicitWidth, parent.width - theme.space1 - (previewBox.visible ? previewBox.width + theme.space4 : 0))
            text: row.group
            textFormat: Text.PlainText
            color: theme.text
            font.pointSize: theme.fontSubtitle
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Accessible.role: Accessible.Heading
            Accessible.name: text
        }
        Rectangle {
            id: previewBox
            visible: row.preview !== null && row.preview !== undefined
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: theme.space3
            height: Math.round(theme.em * 1.6)
            width: previewText.implicitWidth + theme.em * 1.4
            radius: theme.radiusSm
            color: row.preview && row.preview.background !== "" ? row.preview.background : "transparent"
            border.width: 1
            border.color: theme.border
            Text {
                id: previewText
                anchors.centerIn: parent
                text: row.preview ? row.preview.text : ""
                textFormat: Text.PlainText
                color: row.preview && row.preview.color !== "" ? row.preview.color : theme.text
                font.pointSize: theme.fontLabel
            }
            MouseArea { id: previewArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            ToolTip.visible: previewArea.containsMouse
            ToolTip.text: i18n.tr("Preview of the notice")
            ToolTip.delay: theme.tipDelay
        }
    }

    Rectangle {
        id: card
        y: header.height
        width: parent.width
        height: Math.max(content.implicitHeight + theme.em * 1.0, theme.rowTall)  // one height whatever the editor
        radius: theme.radiusLg
        color: theme.surfaceCard
        TapHandler {  // right click: more actions at the pointer
            acceptedButtons: Qt.RightButton
            onTapped: function(eventPoint) { row.openMenu(card, eventPoint.position.x, eventPoint.position.y) }
        }

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
                NumberAnimation { target: flashRect; property: "opacity"; to: 0.28; duration: theme.motionBase }
                PauseAnimation { duration: theme.animate ? 350 : 0 }  // animations off: no flash
                NumberAnimation { target: flashRect; property: "opacity"; to: 0; duration: theme.animate ? 700 : 0; easing.type: Easing.InOutQuad }
            }
        }

        RowLayout {
            id: content
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: theme.em * 0.9
            anchors.rightMargin: theme.em * 0.5
            spacing: theme.space4

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                RowLayout {
                    Layout.fillWidth: true
                    spacing: theme.space3
                    Text {
                        Layout.fillWidth: true
                        Layout.maximumWidth: implicitWidth
                        text: row.marked !== "" ? row.marked : row.label
                        textFormat: row.marked !== "" ? Text.StyledText : Text.PlainText
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
                        tip: row.applies === "restart" ? i18n.tr("Applied once NeoPedal restarts (offered after Apply)")
                                                       : i18n.tr("Used when NeoPedal starts")
                    }
                    Item { Layout.fillWidth: true }
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
                kind: row.kind
                label: row.label
                checked: row.checked
                choices: row.choices
                choiceIndex: row.choiceIndex
                text: row.text
                number: row.number
                decimals: row.decimals
                step: row.step
                minimum: row.minimum
                maximum: row.maximum
                color: row.color
                invalid: row.error !== ""
                onSwitched: function(checked) { backend.setBool(row.key, checked) }
                onChosen: function(index) { backend.setChoice(row.key, index) }
                onNumberEdited: function(value) { backend.setNumber(row.key, value) }
                onTextTyped: function(text) { backend.typeText(row.key, text) }
                onTextCommitted: function(text) { backend.setText(row.key, text) }
                onReverted: backend.revertOption(row.key)
                onColorRequested: backend.pickColor(row.key)
                onBrowseRequested: backend.browse(row.key)
                onFolderRequested: backend.openFolder(row.key)
            }

            TpButton {
                Layout.alignment: Qt.AlignVCenter
                flat: true
                size: "sm"
                glyph: theme.glyphs.reset
                fallback: "↺"
                tip: (hovered || visualFocus) && row.defaultText !== ""
                     ? i18n.trm("Back to default: " + row.defaultText) : i18n.tr("Reset to Default")
                enabled: row.modified
                opacity: row.modified ? 1 : 0  // room kept: editors stay aligned (disabled: no Tab stop)
                onClicked: backend.resetOption(row.key)
            }
            TpButton {
                id: moreButton
                Layout.alignment: Qt.AlignVCenter
                flat: true
                size: "sm"
                glyph: theme.glyphs.more
                fallback: "⋯"
                tip: i18n.tr("More actions")
                opacity: hovered || visualFocus || row.rowHovered ? 1 : 0  // revealed: hover, focus, current
                onClicked: row.openMenu(moreButton, -1, -1)
            }
        }
    }
    HoverHandler { id: rowHover }
}
