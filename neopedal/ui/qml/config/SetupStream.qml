import QtQuick
import QtQuick.Layouts
import "../components"

// Streaming step (optional): stream overlay server on once setup is finished, layout address copied for a browser
// source of the streaming software. Nothing to do here to go on: Next keeps streaming off.
SetupStep {
    SetupCard {
        Layout.fillWidth: true
        glyph: ""  // streaming
        title: i18n.tr("Show my overlays on stream")
        text: i18n.tr("Overlays are sent to your streaming software as a browser source, also while you spectate. The server starts when setup is finished.")
        multi: true  // on or off (check box mark)
        checked: backend.stream
        onClicked: backend.setStream(!backend.stream)
    }

    SetupHeading {
        visible: backend.stream
        text: i18n.tr("Layout address")
    }
    Card {
        Layout.fillWidth: true
        visible: backend.stream
        implicitHeight: addressColumn.implicitHeight + theme.padCard * 2
        ColumnLayout {
            id: addressColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: theme.padCard
            spacing: theme.space3
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Add a browser source of 1920 x 1080 with this address: every overlay at its place on your screen.")
                textFormat: Text.PlainText
                color: theme.text
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                Text {
                    Layout.fillWidth: true
                    visible: backend.streamUrl !== ""
                    text: backend.streamUrl
                    textFormat: Text.PlainText
                    color: theme.text
                    font.family: theme.monoFont
                    font.pointSize: theme.fontLabel
                    elide: Text.ElideMiddle
                }
                Item { Layout.fillWidth: true; visible: backend.streamUrl === "" }
                TpButton {
                    objectName: "copyStreamUrl"
                    accent: backend.streamUrl === ""
                    glyph: theme.glyphs.copy
                    text: backend.streamUrl === "" ? i18n.tr("Copy Address") : i18n.tr("Copied")
                    tip: i18n.tr("Copy Address")
                    onClicked: backend.copyStreamUrl()
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        text: i18n.tr("Other sources, the 16:9 or screen layout and access from another computer: Stream Overlays page.")
        textFormat: Text.PlainText
        color: theme.dimText
        wrapMode: Text.WordWrap
        font.pointSize: theme.fontLabel
    }
}
