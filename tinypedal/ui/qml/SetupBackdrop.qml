import QtQuick

// Overlay picture of the setup wizard on a dark game-like backdrop: loading pulse, or picture icon
// when the overlay cannot be drawn
Rectangle {
    id: backdrop
    property string source: ""
    property int sourceWidth: 0
    property int sourceHeight: 0
    property bool loading: false
    property real dim: 1  // picture opacity
    radius: theme.em * 0.45
    clip: true
    gradient: Gradient {
        GradientStop { position: 0; color: "#566070" }
        GradientStop { position: 1; color: "#23272E" }
    }

    Image {
        anchors.centerIn: parent
        visible: backdrop.source !== ""
        width: Math.min(backdrop.sourceWidth, backdrop.width - theme.em * 0.8)
        height: Math.min(backdrop.sourceHeight, backdrop.height - theme.em * 0.8)
        source: backdrop.source
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        opacity: backdrop.dim
        Behavior on opacity { NumberAnimation { duration: 150 } }
    }
    Rectangle {
        anchors.centerIn: parent
        visible: backdrop.loading
        width: parent.width * 0.55
        height: Math.round(theme.em * 1.1)
        radius: height / 2
        color: Qt.rgba(1, 1, 1, 0.12)
        SequentialAnimation on opacity {
            running: backdrop.loading
            loops: Animation.Infinite
            NumberAnimation { to: 0.35; duration: 600; easing.type: Easing.InOutQuad }
            NumberAnimation { to: 1; duration: 600; easing.type: Easing.InOutQuad }
        }
    }
    Icon {
        anchors.centerIn: parent
        visible: !backdrop.loading && backdrop.source === ""
        glyph: ""  // picture
        size: theme.em * 1.6
        color: Qt.rgba(1, 1, 1, 0.45)
    }
}
