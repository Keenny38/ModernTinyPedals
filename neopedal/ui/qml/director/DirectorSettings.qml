import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Director settings: shot lengths, battle gap, cameras chosen by the director, overlays following the car
// on air, replay time before an event. Saved at once. Scrolls when taller than the window.
TpPopup {
    id: popup
    objectName: "settingsPopup"
    width: Math.min(theme.em * 26, (Overlay.overlay ? Overlay.overlay.width : theme.em * 28) - theme.em * 2)
    readonly property real maxContentHeight: Math.max(theme.em * 12, (Overlay.overlay ? Overlay.overlay.height : theme.em * 40) - theme.em * 8)

    component SettingLabel: ColumnLayout {
        property string title: ""
        property string hint: ""
        Layout.fillWidth: true
        spacing: 0
        Text {
            Layout.fillWidth: true
            text: parent.title
            textFormat: Text.PlainText
            color: theme.text
            wrapMode: Text.WordWrap  // whole title on several lines, never cut
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: parent.hint
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            wrapMode: Text.WordWrap
        }
    }

    contentItem: LazyPane {
        shown: popup.visible
        sourceComponent: ColumnLayout {
            spacing: theme.space4
            TpCardHeader {
                level: "popup"
                glyph: ""  // sliders
                title: i18n.tr("Director Settings")
                closable: true
                onClosed: popup.close()
            }
            ScrollView {
                id: scroller
                Layout.fillWidth: true
                implicitHeight: Math.min(settingsColumn.implicitHeight, popup.maxContentHeight)
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    id: settingsColumn
                    width: scroller.availableWidth - (scroller.ScrollBar.vertical.visible ? theme.space5 : 0)
                    spacing: theme.padCard

                    RowLayout {
                        Layout.fillWidth: true
                        SettingLabel { title: i18n.tr("Shortest shot"); hint: i18n.tr("Only an urgent event cuts sooner") }
                        NumberField {
                            objectName: "minShotField"
                            Layout.preferredWidth: theme.em * 5.5
                            value: backend.minShot
                            minimum: 3; maximum: 60; suffix: " s"
                            showRange: true
                            tip: i18n.tr("Shortest shot")
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
                            showRange: true
                            tip: i18n.tr("Longest shot")
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
                            showRange: true
                            tip: i18n.tr("Battle gap")
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
                            showRange: true
                            tip: i18n.tr("Replay: seconds before an event")
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
                            showRange: true
                            tip: i18n.tr("Instant replay: seconds after the event")
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
                            tip: i18n.tr("Director cameras")
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
                            tip: i18n.tr("Game computer")
                            onEditingFinished: backend.game.setGameHost(text)
                            onEscaped: text = backend.game.gameHost
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TpSwitch {
                            objectName: "logSwitch"
                            Layout.fillWidth: true
                            wrap: true
                            text: i18n.tr("Write events to a file as they happen")
                            tip: i18n.tr("One CSV file per session in the broadcast_logs folder: race control log")
                            checkable: false  // follows backend
                            checked: backend.log.logEvents
                            onClicked: backend.log.setLogEvents(!backend.log.logEvents)
                        }
                        TpButton {
                            glyph: theme.glyphs.openFolder
                            fallback: "…"
                            flat: true
                            tip: i18n.tr("Open Folder")
                            onClicked: backend.log.openLogFolder()
                        }
                    }
                    TpSwitch {
                        objectName: "gameCutsSwitch"
                        Layout.fillWidth: true
                        wrap: true
                        text: i18n.tr("Pause the director when the camera changes in the game")
                        tip: i18n.tr("Off when another app also moves the game camera: the director keeps cutting")
                        checkable: false  // follows backend
                        checked: backend.followGameCuts
                        onClicked: backend.setFollowGameCuts(!backend.followGameCuts)
                    }
                    TpSwitch {
                        objectName: "followSwitch"
                        Layout.fillWidth: true
                        wrap: true
                        text: i18n.tr("Overlays follow the car on air")
                        tip: i18n.tr("Spectate mode on the car on air: overlays and stream sources show it")
                        checkable: false  // follows backend
                        checked: backend.followOverlays
                        onClicked: backend.setFollowOverlays(!backend.followOverlays)
                    }
                }
            }
        }
    }
}
