import QtQuick
import QtQuick.Layouts

// Car or circuit picture of the game (file URL from page backend) in a framed box (cropped to fill
// it), takes no room while there is none
Rectangle {
    id: frame
    property alias source: picture.source
    property real boxHeight: theme.em * 3.2
    property real aspect: 16 / 9  // box width / height
    property bool crop: true
    readonly property bool shown: picture.source != "" && picture.status === Image.Ready
    visible: shown
    implicitHeight: shown ? boxHeight : 0
    implicitWidth: shown ? Math.round(boxHeight * aspect) : 0
    Layout.preferredHeight: implicitHeight
    Layout.preferredWidth: implicitWidth
    radius: theme.radiusSm
    color: theme.raised
    border.color: theme.border
    clip: true

    Image {
        id: picture
        anchors.fill: parent
        anchors.margins: 1
        // Decoded covering box size (box fixed by theme: never reloaded): cropped picture drawn 1:1;
        // mipmaps (+33% texture, out of the shared atlas) only for one drawn well under its decoded
        // size (fitted picture of another shape than the box)
        sourceSize.width: Math.max(1, Math.ceil(frame.boxHeight * frame.aspect * Screen.devicePixelRatio))
        sourceSize.height: Math.max(1, Math.ceil(frame.boxHeight * Screen.devicePixelRatio))
        fillMode: frame.crop ? Image.PreserveAspectCrop : Image.PreserveAspectFit
        asynchronous: true
        smooth: true
        mipmap: frame.shown && Math.min(paintedWidth / Math.max(implicitWidth, 1),
                                        paintedHeight / Math.max(implicitHeight, 1)) * Screen.devicePixelRatio < 0.75
    }
}
