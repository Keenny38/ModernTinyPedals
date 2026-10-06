import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Setup wizard: steps on the left (progress bar on narrow windows), step content slides in from
// the side it comes from, Back / Next at the bottom (Enter: Next, Esc: quit after confirmation). Choices live in the
// backend: a step is created when shown and reads them back.
TpPage {
    id: page

    readonly property bool narrow: width < theme.em * 46
    readonly property var stepFiles: [
        "SetupWelcome.qml", "SetupGame.qml", "SetupUnits.qml", "SetupLook.qml", "SetupOverlays.qml", "SetupReady.qml"
    ]
    readonly property var current: backend.steps[backend.step]
    readonly property bool last: backend.step === backend.stepCount - 1
    property int shownStep: 0
    property int direction: 1  // 1: next step comes from the right

    function forward() {
        if (page.last) {
            if (backend.canFinish)
                backend.finish()
        } else if (backend.canGoNext) {
            backend.next()
        }
    }

    focus: true
    Keys.onReturnPressed: page.forward()
    Keys.onEnterPressed: page.forward()
    Keys.onEscapePressed: function(event) {
        event.accepted = true
        skipDialog.open()
    }

    // Quit asked (Esc, window close): choices dropped only once confirmed
    TpDialog {
        id: skipDialog
        title: i18n.tr("Quit the setup wizard?")
        acceptText: i18n.tr("Quit")
        cancelText: i18n.tr("Continue Setup")
        onAccepted: backend.skip()
        onClosed: page.forceActiveFocus()  // Enter goes on again
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Your choices will not be applied. Open the wizard again any time from Help > Setup Wizard.")
            color: theme.dimText
            wrapMode: Text.WordWrap
        }
    }

    Component.onCompleted: {
        page.shownStep = backend.step
        stepLoader.setSource(page.stepFiles[backend.step])
    }

    Connections {
        target: backend
        function onStepChanged() {
            page.direction = backend.step >= page.shownStep ? 1 : -1
            page.shownStep = backend.step
            stepLoader.setSource(page.stepFiles[backend.step])
            page.forceActiveFocus()  // Enter goes on from any step
        }
        function onSkipRequested() { skipDialog.open() }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Steps
        Rectangle {
            visible: !page.narrow
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(theme.em * 15)
            color: theme.dark ? Qt.darker(theme.window, 1.12) : Qt.darker(theme.window, 1.025)

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: theme.em * 1.1
                spacing: 0

                RowLayout {
                    Layout.bottomMargin: theme.em * 1.6
                    spacing: theme.em * 0.6
                    Image {
                        source: backend.appIcon
                        Layout.preferredWidth: Math.round(theme.em * 2.4)
                        Layout.preferredHeight: Math.round(theme.em * 2.4)
                        sourceSize.width: Math.round(theme.em * 4.8)
                        sourceSize.height: Math.round(theme.em * 4.8)
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Text {
                            Layout.fillWidth: true
                            text: "Modern Tiny Pedals"
                            color: theme.text
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: i18n.tr("Setup Wizard")
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.9
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                Repeater {
                    model: backend.steps
                    delegate: Item {
                        id: entry
                        required property var modelData
                        required property int index
                        readonly property bool active: index === backend.step
                        readonly property bool done: index < backend.step
                        Layout.fillWidth: true
                        implicitHeight: Math.round(theme.em * 2.7)
                        Accessible.role: Accessible.PageTab
                        Accessible.name: modelData.label
                        Accessible.selected: active

                        Rectangle {
                            anchors.fill: parent
                            anchors.leftMargin: -theme.em * 0.3
                            radius: theme.em * 0.5
                            color: entryArea.containsMouse && !entry.active ? theme.hover : "transparent"
                            Behavior on color { ColorAnimation { duration: 120 } }
                        }
                        // Line to next step, filled once passed
                        Rectangle {
                            visible: entry.index < backend.stepCount - 1
                            x: dot.x + dot.width / 2 - 1
                            y: dot.y + dot.height + 3
                            width: 2
                            height: entry.height - dot.height - 6
                            radius: 1
                            color: entry.done ? theme.accent : theme.border
                            Behavior on color { ColorAnimation { duration: 250 } }
                        }
                        Rectangle {
                            id: dot
                            x: theme.em * 0.2
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.round(theme.em * 1.75)
                            height: width
                            radius: width / 2
                            color: entry.active || entry.done ? theme.accent : "transparent"
                            border.width: entry.active || entry.done ? 0 : 1.5
                            border.color: theme.border
                            scale: entry.active ? 1.08 : 1
                            Behavior on color { ColorAnimation { duration: 200 } }
                            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
                            Text {
                                anchors.centerIn: parent
                                visible: !entry.done
                                text: entry.index + 1
                                color: entry.active ? "white" : theme.dimText
                                font.pointSize: theme.fontPoint * 0.85
                                font.weight: Font.DemiBold
                            }
                            Icon {
                                anchors.centerIn: parent
                                visible: entry.done
                                glyph: ""  // check
                                color: "white"
                                size: theme.em * 0.8
                            }
                        }
                        Text {
                            anchors.left: dot.right
                            anchors.leftMargin: theme.em * 0.7
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: entry.modelData.label
                            color: entry.active || entry.done ? theme.text : theme.dimText
                            font.weight: entry.active ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                        MouseArea {
                            id: entryArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.goTo(entry.index)
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Every choice can be changed later.")
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    font.pointSize: theme.fontPoint * 0.88
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Narrow window: progress bar
            RowLayout {
                visible: page.narrow
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 2
                Layout.rightMargin: theme.em * 2
                Layout.topMargin: theme.em * 1.2
                spacing: theme.em * 0.3
                Repeater {
                    model: backend.stepCount
                    Rectangle {
                        required property int index
                        Layout.fillWidth: true
                        implicitHeight: Math.round(theme.em * 0.3)
                        radius: height / 2
                        color: index <= backend.step ? theme.accent : theme.border
                        Behavior on color { ColorAnimation { duration: 250 } }
                    }
                }
            }

            // Header & step content, slid in together
            Item {
                id: stage
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ColumnLayout {
                    id: stageContent
                    width: stage.width
                    height: stage.height
                    spacing: theme.em * 1.2

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: theme.em * 2
                        Layout.rightMargin: theme.em * 2
                        Layout.topMargin: theme.em * 1.6
                        spacing: theme.em * 0.3
                        Text {
                            Layout.fillWidth: true
                            text: (backend.step + 1) + " / " + backend.stepCount + "  ·  " + page.current.label
                            color: theme.accent
                            font.pointSize: theme.fontPoint * 0.85
                            font.weight: Font.DemiBold
                            font.capitalization: Font.AllUppercase
                            font.letterSpacing: 0.8
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: page.current.title
                            color: theme.text
                            wrapMode: Text.WordWrap
                            font.pointSize: theme.fontPoint * 1.75
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: page.current.subtitle
                            color: theme.dimText
                            wrapMode: Text.WordWrap
                        }
                    }

                    Loader {
                        id: stepLoader
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        onLoaded: slideIn.restart()
                    }
                }

                ParallelAnimation {
                    id: slideIn
                    NumberAnimation {
                        target: stageContent
                        property: "x"
                        from: page.direction * theme.em * 2.5
                        to: 0
                        duration: 280
                        easing.type: Easing.OutCubic
                    }
                    NumberAnimation {
                        target: stageContent
                        property: "opacity"
                        from: 0
                        to: 1
                        duration: 220
                        easing.type: Easing.OutQuad
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: theme.border
                opacity: 0.6
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 1.4
                Layout.rightMargin: theme.em * 1.4
                Layout.topMargin: theme.em * 0.8
                Layout.bottomMargin: theme.em * 0.8
                spacing: theme.em * 0.5

                Text {  // why Finish is off (Overlays step shows it under the name)
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: page.last ? backend.nameError : ""
                    color: theme.loss
                    elide: Text.ElideRight
                }
                TpButton {
                    visible: backend.step > 0
                    glyph: ""  // back arrow
                    text: i18n.tr("Back")
                    onClicked: backend.back()
                }
                TpButton {
                    accent: true
                    text: page.last ? i18n.tr("Finish Setup") : i18n.tr("Next")
                    enabled: page.last ? backend.canFinish : backend.canGoNext
                    implicitWidth: Math.max(theme.em * 7, contentItem.implicitWidth + theme.em * 1.6)
                    onClicked: page.forward()
                }
            }
        }
    }
}
