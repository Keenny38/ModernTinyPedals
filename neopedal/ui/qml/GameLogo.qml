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
    // Decoded at box height (box fixed by theme: never reloaded; height only: a width too would make it
    // cover the box), drawn 1:1 unless wider than the box. No mipmaps (+33% texture, out of the shared
    // atlas): drawn at about decoded size, and a mipmap change reloads the image (status, then shown,
    // width... binding loop)
    sourceSize.height: Math.max(1, Math.ceil(boxHeight * Screen.devicePixelRatio))
    fillMode: Image.PreserveAspectFit
    asynchronous: true
    smooth: true
}
