import QtQuick
import QtQuick.Layouts

// Notice banner above a page's content: tinted frame, icon, text (wraps), optional action button.
// tone: theme.warning (default), theme.loss (error), theme.accent (information)
//   TpNotice { visible: backend.restartNeeded; text: i18n.tr("Restart needed"); actionText: i18n.tr("Restart"); onAction: ... }
Rectangle {
    id: notice
    property color tone: theme.warning
    property string glyph: ""  // warning
    property string fallback: "!"
    property string text: ""
    property string actionText: ""
    signal action()

    Layout.fillWidth: true
    implicitHeight: noticeRow.implicitHeight + theme.em * 0.9
    radius: theme.radiusLg
    color: Qt.rgba(tone.r, tone.g, tone.b, theme.tintSubtle * 1.2)
    border.width: 1
    border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.55)
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    RowLayout {
        id: noticeRow
        anchors.fill: parent
        anchors.leftMargin: theme.padCard
        anchors.rightMargin: theme.space3
        spacing: theme.em * 0.5
        Icon { glyph: notice.glyph; fallback: notice.fallback; color: notice.tone }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: theme.text
            text: notice.text
        }
        TpButton {
            visible: notice.actionText !== ""
            flat: true
            text: notice.actionText
            onClicked: notice.action()
        }
    }
}
