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
    color: theme.tint(tone, "subtle")
    border.width: 1
    border.color: theme.tint(tone, "outline")
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    RowLayout {
        id: noticeRow
        anchors.fill: parent
        anchors.leftMargin: theme.padCard
        anchors.rightMargin: theme.space3
        spacing: theme.space3
        Icon { glyph: notice.glyph; fallback: notice.fallback; color: notice.tone }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: theme.text
            text: notice.text
            textFormat: Text.PlainText
        }
        TpButton {
            visible: notice.actionText !== ""
            flat: true
            text: notice.actionText
            onClicked: notice.action()
        }
    }
}
