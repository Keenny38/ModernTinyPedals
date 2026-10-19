import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Setup differences of a shown lap with reference lap: setup name & fingerprint, driver settings at lap start
// (and end if changed), starting fuel. Setup values themselves are not recorded: same or different setup only.
// App dialog (TpDialog): title & one Close button, Esc or a click beside closes it.
TpDialog {
    id: popup

    property var diff: ({})
    readonly property var rows: diff.rows || []

    function show(lapKey) {
        diff = backend.conditions.setupDiff("", lapKey)
        if (diff.rows !== undefined) open()
    }

    title: i18n.tr("Setup Differences")
    showCancel: false
    acceptText: i18n.tr("Close")
    width: Math.min((parent ? parent.width : theme.em * 40) - theme.em * 4, theme.em * 36)

    Text {
        Layout.fillWidth: true
        text: popup.diff.note || ""
        // Same / different told by the words, the color only adds to them
        color: popup.diff.state === "different" ? theme.warning : popup.diff.state === "same" ? theme.gain : theme.dimText
        font.weight: Font.DemiBold
        wrapMode: Text.WordWrap
    }
    GridLayout {
        Layout.fillWidth: true
        columns: 3
        columnSpacing: theme.space5
        rowSpacing: theme.space2
        Item { Layout.fillWidth: true; implicitHeight: 1 }
        Text { text: (popup.diff.a || "") + "\n" + (popup.diff.timeA || ""); color: popup.diff.colorA || theme.text; font.weight: Font.DemiBold }
        Text { text: (popup.diff.b || "") + "\n" + (popup.diff.timeB || ""); color: popup.diff.colorB || theme.text; font.weight: Font.DemiBold }
        Repeater {
            model: popup.rows.length * 3
            Text {
                readonly property var row: popup.rows[Math.floor(index / 3)] || ({})
                readonly property int part: index % 3
                Layout.fillWidth: part === 0
                // Different values: bold & marked (not only in accent color)
                text: (part > 0 && row.differs === true ? "● " : "") + ((part === 0 ? row.name : part === 1 ? row.a : row.b) || "")
                color: part === 0 ? theme.dimText : row.differs === true ? theme.accent : theme.text
                font.weight: part > 0 && row.differs === true ? Font.DemiBold : Font.Normal
                font.features: { "tnum": 1 }
                elide: Text.ElideRight
            }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: popup.rows.length === 0
        text: i18n.tr("Nothing recorded about setup for these laps.")
        color: theme.dimText
        wrapMode: Text.WordWrap
    }
    Text {
        Layout.fillWidth: true
        visible: text !== ""
        text: popup.diff.values || ""
        color: theme.dimText
        font.pointSize: theme.fontSmall
        wrapMode: Text.WordWrap
    }
}
