import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Row of Hotkeys page: section header (fold, name, assigned count) or binding (action name, preset it loads,
// actions sharing its key, key button opening the capture, clear button). Keys handled by the list.
Item {
    id: row
    required property int index
    required property string key
    required property bool header
    required property string section
    required property string label
    required property string binding
    required property bool bound
    required property bool isPreset
    required property string preset
    required property string conflict
    required property int count
    required property int assigned
    required property bool expanded
    property bool current: false  // keyboard row of the list
    property bool editable: true  // global hotkeys on
    signal captureRequested()
    signal clearRequested()
    signal toggleRequested()

    implicitHeight: header ? Math.round(theme.rowTall) : Math.max(Math.round(theme.rowTall), content.implicitHeight + theme.space4)

    Accessible.role: header ? Accessible.Button : Accessible.ListItem
    Accessible.name: header ? label : label + ", " + (bound ? binding : i18n.tr("None"))

    TpListRow {
        anchors.fill: parent
        hovered: area.containsMouse
        selected: row.current && !row.header
    }
    FocusRing { visible: row.current && row.ListView.view && row.ListView.view.activeFocus }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: row.header || row.editable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: row.header ? row.toggleRequested() : row.editable ? row.captureRequested() : undefined
    }

    // Section header
    RowLayout {
        visible: row.header
        anchors.fill: parent
        anchors.leftMargin: theme.space2
        anchors.rightMargin: theme.space4
        spacing: theme.space3
        Icon {
            glyph: row.expanded ? "" : ""  // chevron down, chevron right
            fallback: row.expanded ? "▾" : "▸"
            size: theme.iconXs
            color: theme.dimText
        }
        Text {
            Layout.fillWidth: true
            text: row.label
            textFormat: Text.PlainText
            color: theme.text
            font.pointSize: theme.fontSubtitle
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Accessible.role: Accessible.Heading
            Accessible.name: text
        }
        Text {
            text: i18n.trm(row.assigned + " / " + row.count + " assigned")
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            font.features: { "tnum": 1 }
        }
    }

    // Binding
    RowLayout {
        id: content
        visible: !row.header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: theme.space6
        anchors.rightMargin: theme.space2
        spacing: theme.space3
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Text {
                Layout.fillWidth: true
                text: row.label
                textFormat: Text.PlainText
                color: row.editable ? theme.text : theme.dimText
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                visible: row.isPreset
                text: row.preset !== "" ? i18n.trm("Loads: " + row.preset) : i18n.tr("No preset chosen")
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                elide: Text.ElideRight
            }
            RowLayout {
                Layout.fillWidth: true
                visible: row.conflict !== ""
                spacing: theme.space2
                Icon { glyph: ""; fallback: "!"; size: theme.iconSm; color: theme.warning }  // warning
                Text {
                    Layout.fillWidth: true
                    text: i18n.trm("Same key as: " + row.conflict)
                    textFormat: Text.PlainText
                    color: theme.text
                    font.pointSize: theme.fontSmall
                    elide: Text.ElideRight
                }
            }
        }
        TpButton {
            Layout.preferredWidth: Math.round(theme.em * 10)
            enabled: row.editable
            text: row.bound ? row.binding : i18n.tr("None")
            tip: i18n.tr("Change key binding")
            onClicked: row.captureRequested()
        }
        TpButton {
            flat: true
            size: "sm"
            glyph: theme.glyphs.remove
            fallback: "✕"
            tip: i18n.tr("Clear key binding")
            enabled: row.editable && row.bound
            opacity: row.bound ? 1 : 0  // room kept: key buttons stay aligned
            onClicked: row.clearRequested()
        }
    }
}
