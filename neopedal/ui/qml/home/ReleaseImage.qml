import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Changelog screenshot: card width at most (never enlarged), decoded at shown size only. Asked to the backend
// when built (list delegates near the view: visible ones first), forgotten when dropped before its turn. Its
// size is read first (file header), so the space is kept and the card never jumps. Dashed placeholder while
// loading or unavailable; click (Enter, Space) opens the viewer, or the image online when unavailable.
ColumnLayout {
    id: shot
    property string url: ""
    property string caption: ""
    signal opened()

    readonly property var info: backend.images[url] || ({})
    readonly property bool ready: info.status === "ready"
    readonly property bool failed: info.status === "failed"
    readonly property real shownWidth: ready ? Math.min(width, info.width) : width
    spacing: theme.space1

    function activate() {
        if (failed)
            backend.openImage(url)
        else
            opened()
    }

    Component.onCompleted: backend.requestImage(url)
    Component.onDestruction: backend.dropImage(url)

    Item {
        id: frame
        Layout.fillWidth: true
        // Real ratio once read, 16:9 meanwhile (most screenshots), short placeholder when unavailable
        implicitHeight: shot.ready ? Math.round(shot.shownWidth * shot.info.height / Math.max(shot.info.width, 1))
                      : shot.failed ? Math.round(theme.controlHeight * 1.6) : Math.round(width * 9 / 16)
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: shot.caption !== "" ? shot.caption : i18n.tr("Screenshot")
        Keys.onReturnPressed: shot.activate()
        Keys.onEnterPressed: shot.activate()
        Keys.onSpacePressed: shot.activate()

        Rectangle {
            anchors.fill: parent
            visible: !picture.visible
            radius: theme.radiusMd
            color: theme.tint(theme.dimText, "subtle")
            border.width: 1
            border.color: theme.border
            Text {
                anchors.fill: parent
                anchors.margins: theme.space2
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
                color: theme.dimText
                text: shot.failed ? i18n.tr("Image not available, click to open it online") : i18n.tr("Loading image...")
            }
        }
        Image {
            id: picture
            width: shot.shownWidth
            height: parent.height
            visible: status === Image.Ready
            source: shot.ready ? shot.info.source : ""
            sourceSize.width: Math.ceil(shot.shownWidth * Screen.devicePixelRatio)
            asynchronous: true
            fillMode: Image.PreserveAspectFit
            smooth: true
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.width: 1
                border.color: theme.border
            }
        }
        FocusRing { visible: frame.activeFocus; radius: theme.radiusMd }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            hoverEnabled: true
            onClicked: shot.activate()
            ToolTip.visible: containsMouse && shot.caption !== ""
            ToolTip.delay: theme.tipDelay
            ToolTip.text: shot.caption
        }
    }
    Text {
        Layout.fillWidth: true
        visible: shot.caption !== ""
        text: shot.caption
        color: theme.dimText
        font.pointSize: theme.fontSmall
        elide: Text.ElideRight
    }
}
