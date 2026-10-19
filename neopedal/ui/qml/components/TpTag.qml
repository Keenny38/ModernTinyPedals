import QtQuick

// Tag with optional color dot or icon, removable (✕ button) and cut when long (full text for screen readers).
//   TpTag { text: modelData.name; dotColor: modelData.color; removable: true; onRemoveRequested: ... }
Rectangle {
    id: tag
    property string text: ""
    property string glyph: ""
    property var dotColor: null
    property bool removable: false
    property real maximumTextWidth: theme.em * 12
    signal removeRequested()

    implicitHeight: Math.round(theme.em * (removable ? 2.1 : 1.9))
    implicitWidth: row.implicitWidth + theme.em * (removable ? 0.5 : 0.9)
    radius: height / 2
    color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.tintSubtle)
    border.width: 1
    border.color: theme.border
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    Row {
        id: row
        anchors.verticalCenter: parent.verticalCenter
        x: theme.em * 0.45
        spacing: theme.space3
        ColorDot {
            visible: tag.dotColor !== null
            color: tag.dotColor !== null && tag.dotColor !== "" ? tag.dotColor : theme.accent
            size: Math.round(theme.em * 0.6)
            anchors.verticalCenter: parent.verticalCenter
        }
        Icon {
            glyph: tag.glyph
            size: theme.em * 0.75
            color: theme.accent
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: tag.text
            color: theme.text
            width: Math.min(implicitWidth, tag.maximumTextWidth)
            elide: Text.ElideRight
            anchors.verticalCenter: parent.verticalCenter
        }
        TpButton {
            visible: tag.removable
            flat: true
            size: "xs"
            glyph: ""  // cancel
            fallback: "✕"
            tip: i18n.tr("Remove") + " " + tag.text
            implicitHeight: Math.round(theme.controlHeightSm)  // large enough target: easy to hit
            implicitWidth: implicitHeight
            anchors.verticalCenter: parent.verticalCenter
            onClicked: tag.removeRequested()
        }
    }
}
