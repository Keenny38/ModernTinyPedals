import QtQuick
import QtQuick.Layouts

// Car brand or circuit logo of the game (file URL from page backend), fitted in its box (aspect
// kept), takes no room while there is none (not fetched from game yet, or unknown)
Image {
    property real boxWidth: theme.em * 2.2
    property real boxHeight: theme.em * 1.1
    readonly property bool shown: source != "" && status === Image.Ready
    readonly property real fitWidth: shown ? Math.min(boxWidth, boxHeight * implicitWidth / Math.max(implicitHeight, 1)) : 0
    visible: shown
    width: fitWidth
    height: shown ? boxHeight : 0
    Layout.preferredWidth: fitWidth
    Layout.preferredHeight: height
    Layout.alignment: Qt.AlignVCenter
    sourceSize.width: Math.round(boxWidth * 2)
    sourceSize.height: Math.round(boxHeight * 2)
    fillMode: Image.PreserveAspectFit
    asynchronous: true
    smooth: true
    mipmap: true
}
