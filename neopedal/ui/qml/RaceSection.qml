import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator input section: card with a title that folds it (kept by backend), optional switch
// in the title (scenario on / off: content enabled with it), summary shown while folded
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
    readonly property real pad: theme.em * 0.75

    Layout.fillWidth: true
    implicitHeight: titleRow.height + pad * 2 + (collapsed ? 0 : body.implicitHeight + pad * 0.7)
    clip: true
    Behavior on implicitHeight { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }

    Item {
        id: titleRow
        x: section.pad
        y: section.pad
        width: section.width - section.pad * 2
        height: Math.round(theme.em * 1.9)

        Icon {
            id: chevron
            glyph: ""  // chevron right
            size: theme.em * 0.7
            color: theme.dimText
            rotation: section.collapsed ? 0 : 90
            anchors.verticalCenter: parent.verticalCenter
            Behavior on rotation { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
        }
        Icon {
            id: sectionIcon
            glyph: section.glyph
            color: theme.accent
            size: theme.em * 0.95
            x: chevron.width + theme.em * 0.45
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: titleText
            x: (sectionIcon.visible ? sectionIcon.x + sectionIcon.width : chevron.width) + theme.em * 0.45
            anchors.verticalCenter: parent.verticalCenter
            width: (titleSwitch.visible ? titleSwitch.x : parent.width) - x - theme.em * 0.4
            text: section.title + (section.collapsed && section.summary !== ""
                                   ? "  <font color='" + theme.dimText + "'>" + section.summary + "</font>" : "")
            textFormat: Text.StyledText
            color: theme.text
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        MouseArea {
            anchors.fill: parent
            anchors.rightMargin: titleSwitch.visible ? parent.width - titleSwitch.x : 0
            cursorShape: Qt.PointingHandCursor
            hoverEnabled: true
            onClicked: backend.setSectionCollapsed(section.name, !section.collapsed)
            ToolTip.visible: section.tip !== "" && containsMouse
            ToolTip.text: section.tip
            ToolTip.delay: 600
        }
        RaceSwitch {
            id: titleSwitch
            visible: section.switchKey !== ""
            store: section.store
            key: section.switchKey
            Layout.fillWidth: false
            implicitWidth: theme.em * 2.4
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            Accessible.name: section.title
            onSwitched: function(on) {
                if (on && section.collapsed)
                    backend.setSectionCollapsed(section.name, false)
            }
        }
    }

    ColumnLayout {
        id: body
        x: section.pad
        y: titleRow.y + titleRow.height + section.pad * 0.7
        width: section.width - section.pad * 2
        spacing: theme.em * 0.4
        visible: opacity > 0
        opacity: section.collapsed ? 0 : 1
        enabled: section.switchOn
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }
}
