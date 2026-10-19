import QtQuick
import QtQuick.Controls.Basic

// Waiting for data: spinner & text (only spins while the page is shown), centered in its parent
//   TpLoadingState { anchors.centerIn: parent; visible: backend.loading; text: i18n.tr("Reading files...") }
Column {
    id: state
    property string text: ""
    property bool compact: false

    width: Math.min(parent ? parent.width - theme.em * 2 : theme.em * 24, theme.em * 26)
    spacing: compact ? theme.space2 : theme.space4
    opacity: visible ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    BusyIndicator {
        anchors.horizontalCenter: parent.horizontalCenter
        running: state.visible && pageState.active
        implicitWidth: theme.em * (state.compact ? 1.6 : 2.4)
        implicitHeight: implicitWidth
    }
    Text {
        width: parent.width
        visible: text !== ""
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: state.text
        color: theme.dimText
        font.pointSize: state.compact ? theme.fontSmall : theme.fontPoint
    }
}
