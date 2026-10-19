import QtQuick

// Nothing to show: icon, title, explanation & optional actions, fades in. compact: small icon & title
// (side panels, cards). Put it centered in the area it explains (anchors.centerIn), see TpStateView.
Column {
    id: state
    property string glyph: ""  // search
    property string title: ""
    property string text: ""
    property string actionText: ""
    property string secondaryActionText: ""
    property bool compact: false
    signal action()
    signal secondaryAction()

    width: Math.min(parent ? parent.width - theme.em * 2 : theme.em * 24, theme.em * 26)
    spacing: compact ? theme.space2 : theme.space4
    opacity: visible ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
    Accessible.role: Accessible.StaticText
    Accessible.name: title !== "" ? title + (text !== "" ? ". " + text : "") : text

    Icon {
        anchors.horizontalCenter: parent.horizontalCenter
        glyph: state.glyph
        size: theme.em * (state.compact ? 1.6 : 2.6)
        color: theme.dimText
    }
    Text {
        width: parent.width
        visible: text !== ""
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: state.title
        color: theme.text
        font.pointSize: state.compact ? theme.fontPoint : theme.fontSubtitle
        font.weight: Font.DemiBold
    }
    Text {
        width: parent.width
        visible: text !== ""
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: state.text
        color: theme.dimText
        font.pointSize: state.compact ? theme.fontSmall : theme.fontPoint
        lineHeight: 1.15
    }
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: theme.space3
        visible: state.actionText !== "" || state.secondaryActionText !== ""
        TpButton {
            objectName: "emptyStateAction"
            visible: state.actionText !== ""
            size: state.compact ? "sm" : "md"
            text: state.actionText
            onClicked: state.action()
        }
        TpButton {
            visible: state.secondaryActionText !== ""
            flat: true
            size: state.compact ? "sm" : "md"
            text: state.secondaryActionText
            onClicked: state.secondaryAction()
        }
    }
}
