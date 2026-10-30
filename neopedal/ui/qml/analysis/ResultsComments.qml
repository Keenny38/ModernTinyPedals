import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Comments on the player's session (backend.sessionComments, see quick/results_comments.py): pace against the
// class median, places gained or lost on lap 1, lap time trend of each stint. One line each (wraps on narrow
// pages): icon, title, value (gain / loss tone, its sign tells it too), detail.
Flow {
    id: comments
    spacing: theme.space6
    Accessible.role: Accessible.List
    Accessible.name: i18n.tr("Session comments")

    Repeater {
        model: backend.sessionComments
        Row {
            required property var modelData
            readonly property color tone: modelData.tone !== "" ? theme.tone(modelData.tone) : theme.text
            spacing: theme.space2
            Accessible.role: Accessible.StaticText
            Accessible.name: modelData.title + ": " + modelData.value + ", " + modelData.detail
            Icon {
                id: icon
                anchors.verticalCenter: parent.verticalCenter
                glyph: modelData.glyph
                size: theme.iconSm
                color: theme.dimText
            }
            Text {
                id: title
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.title
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontLabel
            }
            Text {
                id: value
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.value
                textFormat: Text.PlainText
                color: parent.tone
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                // Narrow page: cut, whole text in the tooltip
                width: Math.max(0, Math.min(implicitWidth, comments.width - icon.width - title.implicitWidth
                                                           - value.implicitWidth - parent.spacing * 3))
                text: modelData.detail
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontLabel
                font.features: { "tnum": 1 }
                elide: Text.ElideRight
                ToolTip.visible: truncated && detailHover.hovered
                ToolTip.text: text
                ToolTip.delay: theme.tipDelay
                HoverHandler { id: detailHover }
            }
        }
    }
}
