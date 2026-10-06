import QtQuick
import QtQuick.Controls.Basic
import TinyPedal

// Track map of the session or replay open in game: track & pit lane, cars (class color, number), car followed by
// the camera ringed in accent color, your car in white. Cars glide between game answers.
// Click a car: camera on it. Wheel: zoom, drag: move, double click: whole map.
Item {
    id: root

    readonly property var view: backend.mapView
    readonly property bool loaded: view.road !== undefined
    // Glide well under the time between game answers (about 1.9 s replay, 4.8 s live): cars stop before the next
    // answer, scene idle (no redraw) in between. No glide while page hidden: positions jump, nothing animates.
    readonly property int glide: backend.replayActive ? 1150 : 2900
    readonly property bool gliding: pageState.active

    MapCanvas {
        id: canvas
        anchors.fill: parent
        anchors.margins: theme.em * 0.4
        anchors.topMargin: 0
        maxZoom: 40
        minX: root.view.minX || 0
        minY: root.view.minY || 0
        maxX: root.view.maxX || 1
        maxY: root.view.maxY || 1
        onSettled: if (root.loaded) backend.setMapScale(canvas.metersPerPixel)

        GpuShape {
            key: root.view.edge || ""
            color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.18 : 0.25)
            revision: backend.mapRevision
            transform: Matrix4x4 { matrix: canvas.matrix }
        }
        GpuShape {
            key: root.view.road || ""
            color: theme.dark ? Qt.lighter(theme.base, 1.6) : Qt.darker(theme.base, 1.1)
            revision: backend.mapRevision
            transform: Matrix4x4 { matrix: canvas.matrix }
        }
        GpuShape {
            key: root.view.pit || ""
            color: Qt.rgba(theme.warning.r, theme.warning.g, theme.warning.b, 0.35)
            revision: backend.mapRevision
            transform: Matrix4x4 { matrix: canvas.matrix }
        }

        Repeater {
            model: root.loaded ? backend.mapCars : null
            Item {
                id: car
                required property string key
                required property real mapX
                required property real mapY
                required property string color
                required property string number
                required property string driver
                required property int position
                required property bool onCamera
                required property bool player
                required property bool inPit
                // World position glides to each new answer, screen position follows zoom at once
                property real worldX: mapX
                property real worldY: mapY
                Behavior on worldX { enabled: root.gliding; NumberAnimation { duration: root.glide; easing.type: Easing.OutSine } }
                Behavior on worldY { enabled: root.gliding; NumberAnimation { duration: root.glide; easing.type: Easing.OutSine } }
                z: onCamera ? 3 : player ? 2 : 1

                Rectangle {
                    readonly property real size: theme.em * (car.onCamera ? 1.65 : 1.3)
                    x: canvas.screenX(car.worldX) - size / 2
                    y: canvas.screenY(car.worldY) - size / 2
                    width: size
                    height: size
                    radius: size / 2
                    color: car.color
                    opacity: car.inPit ? 0.45 : 1
                    border.width: car.onCamera || car.player ? 2 : 1
                    border.color: car.onCamera ? theme.accent : car.player ? "white" : Qt.rgba(0, 0, 0, 0.45)
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                    Text {
                        anchors.centerIn: parent
                        text: car.number
                        color: "white"
                        style: Text.Outline
                        styleColor: Qt.rgba(0, 0, 0, 0.5)
                        font.pointSize: theme.fontPoint * 0.6
                        font.weight: Font.Bold
                    }
                    MouseArea {
                        id: carArea
                        anchors.fill: parent
                        anchors.margins: -3
                        hoverEnabled: true
                        cursorShape: backend.inSession ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: backend.watchCar(car.key)
                    }
                    ToolTip.visible: carArea.containsMouse
                    ToolTip.text: carArea.containsMouse  // text built only while hovered, not for every car on each answer
                        ? car.position + ". " + car.driver + (backend.inSession ? "\n" + i18n.tr("Camera on This Car") : "") : ""
                    ToolTip.delay: 200
                }
            }
        }

        // No map yet
        Column {
            anchors.centerIn: parent
            width: parent.width - theme.em * 4
            visible: !root.loaded
            spacing: theme.em * 0.6
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                glyph: ""  // map pin
                size: theme.em * 2.2
                color: theme.dimText
            }
            Text {
                width: parent.width
                text: backend.inSession ? i18n.tr("Asking game...")
                    : i18n.tr("Track map shows once a session or a replay is loaded in the game.")
                color: theme.dimText
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
    Connections {
        target: backend
        function onMapChanged() { canvas.reset(false) }
    }
}
