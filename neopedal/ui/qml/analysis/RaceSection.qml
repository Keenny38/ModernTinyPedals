import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator input section: card with a title that folds it (kept by backend; click, or Tab then Space /
// Enter), optional switch in the title (scenario on / off: content enabled with it), summary shown while folded
Card {
    id: section
    property string title: ""
    property string name: ""  // kept folded by this name
    property string glyph: ""
    property string tip: ""
    property string summary: ""  // shown folded
    property var store  // page: inputs & header (folded sections)
    property string switchKey: ""  // input of title switch, "" for none
    readonly property bool switchOn: switchKey !== "" && store ? Boolean(store.inputs[switchKey]) : true
    readonly property bool collapsed: store && name !== "" ? store.header.collapsed.indexOf(name) >= 0 : false
    default property alias content: body.data
    readonly property real pad: theme.padCard

    function toggle() { backend.setSectionCollapsed(section.name, !section.collapsed) }

    // Open part of the body (0 folded, 1 unfolded): only folding animated, content height changes (text wrapped
    // on resize, rows added) followed at once (an animated height lagged behind its content, clipped)
    property real openness: collapsed ? 0 : 1
    Behavior on openness { NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutCubic } }

    Layout.fillWidth: true
    implicitHeight: titleRow.height + pad * 2 + (openness > 0 ? (body.implicitHeight + theme.space4) * openness : 0)
    clip: true

    AbstractButton {  // fold / unfold: whole title but the switch
        id: titleRow
        x: section.pad
        y: section.pad
        width: (titleSwitch.visible ? titleSwitch.x - theme.space3 : section.width - section.pad * 2)
        height: Math.round(theme.headerHeight)
        hoverEnabled: true
        focusPolicy: Qt.TabFocus
        onClicked: section.toggle()
        Keys.onReturnPressed: section.toggle()
        Keys.onEnterPressed: section.toggle()
        Keys.onShortcutOverride: function(event) {
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
                event.accepted = true
        }
        Accessible.role: Accessible.Button
        Accessible.name: section.title
        Accessible.description: (section.collapsed ? i18n.tr("Collapsed") : i18n.tr("Expanded"))
                                + (section.tip !== "" ? ". " + section.tip : "")
        ToolTip.visible: section.tip !== "" && (hovered || visualFocus)
        ToolTip.text: section.tip
        ToolTip.delay: theme.tipDelay
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        background: Rectangle {
            radius: theme.radiusSm
            color: titleRow.hovered ? theme.hover : "transparent"
            Behavior on color { ColorAnimation { duration: theme.motionFast } }
            FocusRing { visible: titleRow.visualFocus }
        }
        contentItem: Item {
            Icon {
                id: chevron
                glyph: ""  // chevron right
                fallback: section.collapsed ? "▸" : "▾"
                size: theme.iconXs
                color: theme.dimText
                rotation: section.collapsed || !iconShown ? 0 : 90
                anchors.verticalCenter: parent.verticalCenter
                Behavior on rotation { NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutCubic } }
            }
            Icon {
                id: sectionIcon
                glyph: section.glyph
                color: theme.accent
                size: theme.iconSm
                x: chevron.width + theme.space3
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                id: titleText
                x: (sectionIcon.visible ? sectionIcon.x + sectionIcon.width : chevron.width) + theme.space3
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - x
                text: section.title
                textFormat: Text.PlainText
                color: theme.text
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                // Folded: summary after the title, in dim text (plain text: values never read as markup)
                Text {
                    visible: section.collapsed && section.summary !== "" && titleText.implicitWidth < titleText.width
                    x: titleText.implicitWidth + theme.space4
                    width: Math.max(0, titleText.width - x)
                    anchors.verticalCenter: parent.verticalCenter
                    text: section.summary
                    textFormat: Text.PlainText
                    color: theme.dimText
                    elide: Text.ElideRight
                }
            }
        }
    }
    RaceSwitch {
        id: titleSwitch
        visible: section.switchKey !== ""
        store: section.store
        key: section.switchKey
        wrap: false
        width: implicitWidth
        x: section.width - section.pad - width
        y: titleRow.y + (titleRow.height - height) / 2
        Accessible.name: section.title
        onSwitched: function(on) {
            if (on && section.collapsed)
                backend.setSectionCollapsed(section.name, false)
        }
    }

    ColumnLayout {
        id: body
        x: section.pad
        y: titleRow.y + titleRow.height + theme.space4
        width: section.width - section.pad * 2
        spacing: theme.space3
        visible: opacity > 0
        opacity: section.collapsed ? 0 : 1
        enabled: section.switchOn
        Behavior on opacity { NumberAnimation { duration: theme.motionFast } }
    }
}
