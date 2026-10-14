import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Director settings: shot lengths, battle gap, cameras chosen by the director, overlays following the car
// on air, replay time before an event. Saved at once.
Popup {
    id: popup
    objectName: "settingsPopup"
    width: theme.em * 26
    padding: theme.em * 1.0
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }
    background: Rectangle {
        radius: theme.radiusXl
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    component SettingLabel: ColumnLayout {
        property string title: ""
        property string hint: ""
        Layout.fillWidth: true
        spacing: 0
        Text {
            Layout.fillWidth: true
            text: parent.title
            color: theme.text
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: parent.hint
            color: theme.dimText
            font.pointSize: theme.fontSmall
            wrapMode: Text.WordWrap
        }
    }

    contentItem: LazyPane {
        shown: popup.visible
        sourceComponent: ColumnLayout {
            spacing: theme.em * 0.7

            Text {
                text: i18n.tr("Director Settings")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontSubtitle
            }
            RowLayout {
                Layout.fillWidth: true
                SettingLabel { title: i18n.tr("Shortest shot"); hint: i18n.tr("Only an urgent event cuts sooner") }
                NumberField {
                    objectName: "minShotField"
                    Layout.preferredWidth: theme.em * 5.5
                    value: backend.minShot
                    minimum: 3; maximum: 60; suffix: " s"
                    onEdited: function(value) { backend.setNumber("minShot", value) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                SettingLabel { title: i18n.tr("Longest shot"); hint: i18n.tr("Then another car, even if the story goes on") }
                NumberField {
                    Layout.preferredWidth: theme.em * 5.5
                    value: backend.maxShot
                    minimum: 5; maximum: 300; suffix: " s"
                    onEdited: function(value) { backend.setNumber("maxShot", value) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                SettingLabel { title: i18n.tr("Battle gap"); hint: i18n.tr("Two cars of a class closer than this") }
                NumberField {
                    Layout.preferredWidth: theme.em * 5.5
                    value: backend.battleGap
                    decimals: 1; step: 0.1; minimum: 0.2; maximum: 3; suffix: " s"
                    onEdited: function(value) { backend.setNumber("battleGap", value) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                SettingLabel { title: i18n.tr("Replay: seconds before an event") }
                NumberField {
                    Layout.preferredWidth: theme.em * 5.5
                    value: backend.secondsBefore
                    minimum: 0; maximum: 60; suffix: " s"
                    onEdited: function(value) { backend.setNumber("secondsBefore", value) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                SettingLabel { title: i18n.tr("Instant replay: seconds after the event"); hint: i18n.tr("Then back to live") }
                NumberField {
                    Layout.preferredWidth: theme.em * 5.5
                    value: backend.postRoll
                    minimum: 0; maximum: 60; suffix: " s"
                    onEdited: function(value) { backend.setNumber("postRoll", value) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                SettingLabel { title: i18n.tr("Director cameras") }
                TpCombo {
                    objectName: "cameraStyleBox"
                    Layout.preferredWidth: theme.em * 9
                    model: backend.cameraStyles
                    currentIndex: backend.cameraStyle
                    onActivated: function(index) { backend.setCameraStyle(index) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                SettingLabel { title: i18n.tr("Game computer"); hint: i18n.tr("Address of the computer running LMU, empty: this one") }
                TpTextField {
                    id: hostField
                    objectName: "gameHostField"
                    Layout.preferredWidth: theme.em * 9
                    placeholderText: "localhost"
                    text: backend.game.gameHost
                    onEditingFinished: backend.game.setGameHost(text)
                    onEscaped: text = backend.game.gameHost
                }
            }
            RowLayout {
                Layout.fillWidth: true
                TpSwitch {
                    objectName: "logSwitch"
                    Layout.fillWidth: true
                    text: i18n.tr("Write events to a file as they happen")
                    tip: i18n.tr("One CSV file per session in the broadcast_logs folder: race control log")
                    checked: backend.log.logEvents
                    onToggled: backend.log.setLogEvents(checked)
                }
                TpButton {
                    glyph: "\ue838"  // folder open
                    flat: true
                    tip: i18n.tr("Open Folder")
                    onClicked: backend.log.openLogFolder()
                }
            }
            TpSwitch {
                objectName: "gameCutsSwitch"
                Layout.fillWidth: true
                text: i18n.tr("Pause the director when the camera changes in the game")
                tip: i18n.tr("Off when another app also moves the game camera: the director keeps cutting")
                checked: backend.followGameCuts
                onToggled: backend.setFollowGameCuts(checked)
            }
            TpSwitch {
                objectName: "followSwitch"
                Layout.fillWidth: true
                text: i18n.tr("Overlays follow the car on air")
                tip: i18n.tr("Spectate mode on the car on air: overlays and stream sources show it")
                checked: backend.followOverlays
                onToggled: backend.setFollowOverlays(checked)
            }
        }
    }
}
