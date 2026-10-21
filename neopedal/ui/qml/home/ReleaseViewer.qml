import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Screenshot viewer over the page: image fitted to the page (full resolution decoded only while shown), caption,
// position, previous / next (arrow keys), open in the default image viewer. Esc or a click beside closes.
Rectangle {
    id: viewer
    property int current: -1
    readonly property var list: backend.imageList
    readonly property var entry: current >= 0 && current < list.length ? list[current] : null
    readonly property var info: entry !== null ? (backend.images[entry.url] || ({})) : ({})

    visible: entry !== null
    color: theme.window
    z: 10

    function show(url) {
        for (let index = 0; index < list.length; index++) {
            if (list[index].url === url) {
                current = index
                forceActiveFocus()
                return
            }
        }
    }
    function close() {
        current = -1
    }
    function step(delta) {
        if (list.length > 0)
            current = (current + delta + list.length) % list.length
    }

    onEntryChanged: if (entry !== null) backend.requestImage(entry.url)
    onVisibleChanged: if (!visible) current = -1  // rows changed (search, other version): viewer closed

    Keys.onEscapePressed: function(event) { viewer.close(); event.accepted = true }  // never closes the page
    Keys.onLeftPressed: step(-1)
    Keys.onRightPressed: step(1)

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.ArrowCursor
        onClicked: viewer.close()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space3

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space2
            Text {
                Layout.fillWidth: true
                text: viewer.entry !== null ? viewer.entry.caption : ""
                color: theme.text
                font.pointSize: theme.fontHeading
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                text: (viewer.current + 1) + " / " + viewer.list.length
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            TpButton {
                glyph: ""  // chevron left
                fallback: "‹"
                tip: i18n.tr("Previous image")
                enabled: viewer.list.length > 1
                onClicked: viewer.step(-1)
            }
            TpButton {
                glyph: ""  // chevron right
                fallback: "›"
                tip: i18n.tr("Next image")
                enabled: viewer.list.length > 1
                onClicked: viewer.step(1)
            }
            TpButton {
                glyph: ""  // open in new window
                fallback: "↗"
                tip: i18n.tr("Open in image viewer")
                onClicked: if (viewer.entry !== null) backend.openImage(viewer.entry.url)
            }
            TpButton {
                glyph: ""  // close
                fallback: "✕"
                tip: i18n.tr("Close")
                onClicked: viewer.close()
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Image {
                id: full
                anchors.centerIn: parent
                // Fitted to the page, never enlarged
                readonly property real fit: viewer.info.status === "ready"
                    ? Math.min(1, parent.width / viewer.info.width, parent.height / viewer.info.height) : 1
                width: viewer.info.status === "ready" ? viewer.info.width * fit : 0
                height: viewer.info.status === "ready" ? viewer.info.height * fit : 0
                source: viewer.visible && viewer.info.status === "ready" ? viewer.info.source : ""
                sourceSize.width: viewer.info.status === "ready"
                                  ? Math.min(viewer.info.width, Math.ceil(width * Screen.devicePixelRatio)) : 0
                asynchronous: true
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: viewer.step(1)
                }
            }
            Text {
                anchors.centerIn: parent
                visible: full.status !== Image.Ready
                color: theme.dimText
                text: viewer.info.status === "failed" ? i18n.tr("Image not available, click to open it online")
                                                      : i18n.tr("Loading image...")
                MouseArea {
                    anchors.fill: parent
                    enabled: viewer.info.status === "failed"
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (viewer.entry !== null) backend.openImage(viewer.entry.url)
                }
            }
        }
    }
}
