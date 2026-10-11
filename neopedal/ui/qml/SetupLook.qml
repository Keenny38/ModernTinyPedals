import QtQuick
import QtQuick.Layouts

// Appearance step: window theme (drawn sample window in its colors), overlay theme (overlay rendered in
// each theme), colorblind colors & font, then overlays rendered in the chosen style
SetupStep {
    id: step
    maxWidth: theme.em * 56
    readonly property int columns: width > theme.em * 44 ? 4 : 2

    SetupHeading { text: i18n.tr("App window") }

    GridLayout {
        Layout.fillWidth: true
        columns: step.columns
        columnSpacing: theme.em * 0.7
        rowSpacing: theme.em * 0.7
        Repeater {
            model: backend.windowThemes
            SetupCard {
                id: windowCard
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1  // same width for every card
                padding: theme.em * 0.6
                title: modelData.label
                checked: backend.windowTheme === modelData.name
                onClicked: backend.setWindowTheme(modelData.name)

                // Sample window: navigation, title, rows & accent button in theme colors
                Rectangle {
                    id: sample
                    readonly property real corner: windowCard.modelData.legacy ? 2 : theme.em * 0.25
                    width: parent.width
                    height: Math.round(width * 0.58)
                    radius: windowCard.modelData.legacy ? 2 : theme.em * 0.4
                    color: windowCard.modelData.window
                    border.width: 1
                    border.color: windowCard.modelData.border
                    clip: true
                    Rectangle {
                        id: sideBar
                        x: 1
                        y: 1
                        width: Math.round(parent.width * 0.27)
                        height: parent.height - 2
                        color: Qt.darker(windowCard.modelData.window, windowCard.modelData.name.indexOf("Light") >= 0 ? 1.04 : 1.18)
                        Column {
                            x: 5
                            y: 7
                            spacing: 5
                            Repeater {
                                model: 4
                                Rectangle {
                                    required property int index
                                    width: sideBar.width - 10
                                    height: 4
                                    radius: 2
                                    color: index === 0 ? windowCard.modelData.accent : windowCard.modelData.dim
                                    opacity: index === 0 ? 1 : 0.55
                                }
                            }
                        }
                    }
                    Column {
                        x: sideBar.width + 7
                        y: 7
                        width: parent.width - sideBar.width - 14
                        spacing: 4
                        Rectangle {
                            width: parent.width * 0.55
                            height: 5
                            radius: 2
                            color: windowCard.modelData.text
                        }
                        Repeater {
                            model: 3
                            Rectangle {
                                width: parent.width
                                height: Math.max(7, Math.round(sample.height * 0.14))
                                radius: sample.corner
                                color: windowCard.modelData.base
                                border.width: 1
                                border.color: windowCard.modelData.border
                            }
                        }
                        Rectangle {
                            width: parent.width * 0.38
                            height: Math.max(7, Math.round(sample.height * 0.14))
                            radius: sample.corner
                            color: windowCard.modelData.accent
                        }
                    }
                }
            }
        }
    }

    SetupHeading { text: i18n.tr("In-game overlays") }

    GridLayout {
        Layout.fillWidth: true
        columns: step.columns
        columnSpacing: theme.em * 0.7
        rowSpacing: theme.em * 0.7
        Repeater {
            model: backend.overlayThemes
            SetupCard {
                id: overlayCard
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                padding: theme.em * 0.6
                title: modelData.label
                checked: backend.overlayTheme === modelData.name
                onClicked: backend.setOverlayTheme(modelData.name)

                SetupBackdrop {
                    width: parent.width
                    height: Math.round(theme.em * 4)
                    source: overlayCard.modelData.preview
                    sourceWidth: overlayCard.modelData.previewWidth
                    sourceHeight: overlayCard.modelData.previewHeight
                    loading: overlayCard.modelData.previewState === 0
                }
            }
        }
    }

    Flow {
        Layout.fillWidth: true
        spacing: theme.em * 1.5
        TpSwitch {
            text: i18n.tr("Colorblind safe colors")
            checked: backend.colorblind
            onToggled: backend.setColorblind(checked)
        }
        TpSwitch {
            text: i18n.tr("Modern font (JetBrains Mono)")
            checked: backend.modernFont
            onToggled: backend.setModernFont(checked)
        }
    }

    SetupHeading { text: i18n.tr("Preview") }

    // Sample overlays in chosen style, scaled down to fit side by side
    Rectangle {
        id: stage
        readonly property real gap: theme.em * 1.2
        readonly property int count: Math.max(backend.sampleCount, 1)
        readonly property real room: (width - theme.em * 2 - gap * (count - 1)) / count  // per overlay
        Layout.fillWidth: true
        implicitHeight: Math.round(theme.em * 10)
        radius: theme.em * 0.75
        clip: true
        gradient: Gradient {
            GradientStop { position: 0; color: "#566070" }
            GradientStop { position: 1; color: "#23272E" }
        }
        Row {
            anchors.centerIn: parent
            spacing: stage.gap
            Repeater {
                model: backend.tileModel
                Item {
                    id: sampleItem
                    required property bool sample
                    required property string preview
                    required property int previewWidth
                    required property int previewHeight
                    required property int previewState
                    readonly property real fit: previewWidth > 0
                        ? Math.min(1, stage.room / previewWidth, (stage.height - theme.em * 1.6) / previewHeight) : 1
                    visible: sample
                    anchors.verticalCenter: parent ? parent.verticalCenter : undefined
                    width: previewState === 1 ? Math.round(previewWidth * fit) : Math.round(stage.room)
                    height: previewState === 1 ? Math.round(previewHeight * fit) : Math.round(theme.em * 4)
                    Image {
                        anchors.fill: parent
                        visible: sampleItem.previewState === 1
                        source: sampleItem.preview
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        retainWhileLoading: true
                        cache: true
                        sourceSize.width: Math.ceil(width * Screen.devicePixelRatio / 32) * 32
                        smooth: true
                    }
                    Rectangle {
                        anchors.fill: parent
                        visible: sampleItem.previewState === 0
                        radius: theme.em * 0.3
                        color: Qt.rgba(1, 1, 1, 0.1)
                        SequentialAnimation on opacity {
                            running: sampleItem.previewState === 0 && pageState.active
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.35; duration: 600; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: 1; duration: 600; easing.type: Easing.InOutQuad }
                        }
                    }
                }
            }
        }
    }
}
