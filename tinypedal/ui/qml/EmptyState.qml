import QtQuick

// Nothing to show: icon, title, explanation & optional action button, fades in
Column {
    id: state
    property string glyph: ""  // search
    property string title: ""
    property string text: ""
    property string actionText: ""
    signal action()

    width: Math.min(parent ? parent.width - theme.em * 2 : theme.em * 24, theme.em * 26)
    spacing: theme.em * 0.6
    opacity: visible ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Icon {
        anchors.horizontalCenter: parent.horizontalCenter
        glyph: state.glyph
        size: theme.em * 2.6
        color: theme.dimText
    }
    Text {
        width: parent.width
        visible: text !== ""
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: state.title
        color: theme.text
        font.pointSize: theme.fontPoint * 1.1
        font.weight: Font.DemiBold
    }
    Text {
        width: parent.width
        visible: text !== ""
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: state.text
        color: theme.dimText
        lineHeight: 1.15
    }
    TpButton {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: state.actionText !== ""
        text: state.actionText
        onClicked: state.action()
    }
}
