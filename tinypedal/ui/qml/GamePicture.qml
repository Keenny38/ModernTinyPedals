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
    radius: theme.em * 0.35
    color: theme.raised
    border.color: theme.border
    clip: true

    Image {
        id: picture
        anchors.fill: parent
        anchors.margins: 1
        sourceSize.width: Math.round(frame.boxHeight * frame.aspect * 2)
        fillMode: frame.crop ? Image.PreserveAspectCrop : Image.PreserveAspectFit
        asynchronous: true
        smooth: true
        mipmap: true
    }
}
