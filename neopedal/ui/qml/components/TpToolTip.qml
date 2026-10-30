import QtQuick
import QtQuick.Controls.Basic

// Tooltip object of its own (placed & shown by bindings), in place of ToolTip {}: the Basic style text is AutoText,
// a name starting with a tag would be rich text. Plain text by default; textFormat: Text.StyledText for a text
// made of escaped values with <b> & <br> (race plan stints).
ToolTip {
    id: tip
    property int textFormat: Text.PlainText
    contentItem: Text {
        text: tip.text
        textFormat: tip.textFormat
        font: tip.font
        wrapMode: Text.Wrap
        color: theme.text
    }
    background: TpToolTipBackground {}
}
