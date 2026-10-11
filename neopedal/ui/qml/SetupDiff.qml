import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Setup differences of a shown lap with reference lap: setup name & fingerprint, driver settings at lap start
// (and end if changed), starting fuel. Setup values themselves are not recorded: same or different setup only.
Popup {
    id: popup

    property var diff: ({})
    readonly property var rows: diff.rows || []

    function show(lapKey) {
        diff = backend.setupDiff("", lapKey)
        if (diff.rows !== undefined) open()
    }

    parent: Overlay.overlay  // centered on page, wherever it is declared
    modal: true
    dim: true
    padding: theme.em * 1.1
    width: Math.min((parent ? parent.width : theme.em * 40) - theme.em * 4, theme.em * 36)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 150 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
    background: Rectangle {
        radius: theme.em * 0.8
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    contentItem: ColumnLayout {
        spacing: theme.em * 0.45
        Text { text: i18n.tr("Setup Differences"); color: theme.text; font.weight: Font.DemiBold; font.pointSize: theme.fontPoint * 1.15 }
        Text {
            Layout.fillWidth: true
            text: popup.diff.note || ""
            color: popup.diff.state === "different" ? theme.warning : popup.diff.state === "same" ? theme.gain : theme.dimText
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 3
            columnSpacing: theme.em * 0.8
            rowSpacing: theme.em * 0.3
            Item { Layout.fillWidth: true; implicitHeight: 1 }
            Text { text: (popup.diff.a || "") + "\n" + (popup.diff.timeA || ""); color: popup.diff.colorA || theme.text; font.weight: Font.DemiBold }
            Text { text: (popup.diff.b || "") + "\n" + (popup.diff.timeB || ""); color: popup.diff.colorB || theme.text; font.weight: Font.DemiBold }
            Repeater {
                model: popup.rows.length * 3
                Text {
                    readonly property var row: popup.rows[Math.floor(index / 3)] || ({})
                    readonly property int part: index % 3
                    Layout.fillWidth: part === 0
                    text: (part === 0 ? row.name : part === 1 ? row.a : row.b) || ""
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
            text: popup.diff.values || ""
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.82
            wrapMode: Text.WordWrap
        }
        TpButton { Layout.alignment: Qt.AlignRight; text: i18n.tr("Close"); onClicked: popup.close() }
    }
}
