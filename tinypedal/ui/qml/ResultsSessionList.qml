import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Sessions of results files: search (track, server, car), session kind filter, sessions without any lap
// hidden, sections by day. Click (or Up / Down): show session. Folder menu: open, choose another folder.
Item {
    id: root

    function moveSelection(step) {
        var index = backend.moveSelection(step)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }

    TpMenu {
        id: folderMenu
        Action {
            text: i18n.tr("Open Folder")
            enabled: backend.folderText !== ""
            onTriggered: backend.openFolder()
        }
        Action {
            text: i18n.tr("Choose Folder...")
            onTriggered: backend.chooseFolder()
        }
        Action {
            text: i18n.tr("Use Game Folders")
            enabled: backend.customFolder
            onTriggered: backend.resetFolder()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.5

        // Title, count, folder & refresh
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Icon { glyph: ""; color: theme.accent }  // flag
            Text {
                text: i18n.tr("Sessions")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontPoint * 1.1
            }
            Rectangle {
                visible: backend.sessionCount > 0
                implicitHeight: countText.implicitHeight + theme.em * 0.3
                implicitWidth: countText.implicitWidth + theme.em * 1.0
                radius: height / 2
                color: theme.hover
                Text {
                    id: countText
                    anchors.centerIn: parent
                    text: backend.shownCount === backend.sessionCount ? backend.sessionCount
                          : backend.shownCount + " / " + backend.sessionCount
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.85
                    font.features: { "tnum": 1 }
                }
            }
            BusyIndicator {
                running: backend.busy
                visible: running
                implicitWidth: theme.em * 1.4
                implicitHeight: implicitWidth
            }
            Item { Layout.fillWidth: true }
            TpButton {
                id: folderButton
                glyph: ""  // folder
                flat: true
                checked: folderMenu.visible
                tip: backend.folderText !== "" ? i18n.tr("Results Folder") + ":\n" + backend.folderText
                                               : i18n.tr("No results folder found")
                onClicked: folderMenu.visible ? folderMenu.close() : folderMenu.popup(folderButton, 0, folderButton.height + 4)
            }
            TpButton {
                glyph: ""  // refresh
                flat: true
                tip: i18n.tr("Read results files again (F5)")
                enabled: !backend.busy
                onClicked: backend.reload()
            }
        }

        // Search
        TextField {
            id: searchField
            Layout.fillWidth: true
            implicitHeight: Math.round(theme.em * 2.3)
            leftPadding: theme.em * 2
            rightPadding: theme.em * 2
            placeholderText: i18n.tr("Search: track, server, car...")
            color: theme.text
            placeholderTextColor: theme.dimText
            onTextEdited: searchTimer.restart()
            Keys.onEscapePressed: { text = ""; backend.setSearch(""); list.forceActiveFocus() }
            Keys.onReturnPressed: { backend.setSearch(text); list.forceActiveFocus() }
            Keys.onEnterPressed: { backend.setSearch(text); list.forceActiveFocus() }
            Keys.onDownPressed: list.forceActiveFocus()
            Timer { id: searchTimer; interval: 200; onTriggered: backend.setSearch(searchField.text) }
            background: Rectangle {
                radius: theme.em * 0.5
                color: theme.base
                border.width: 1
                border.color: searchField.activeFocus ? theme.accent : theme.border
                Behavior on border.color { ColorAnimation { duration: 120 } }
            }
            Icon {
                anchors.left: parent.left
                anchors.leftMargin: theme.em * 0.65
                anchors.verticalCenter: parent.verticalCenter
                glyph: ""  // search
                size: theme.em * 0.85
                color: theme.dimText
            }
            Text {
                visible: searchField.text !== ""
                anchors.right: parent.right
                anchors.rightMargin: theme.em * 0.7
                anchors.verticalCenter: parent.verticalCenter
                text: "×"
                color: clearArea.containsMouse ? theme.text : theme.dimText
                font.weight: Font.Bold
                MouseArea {
                    id: clearArea
                    anchors.fill: parent
                    anchors.margins: -4
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { searchField.text = ""; backend.setSearch("") }
                }
            }
        }

        // Session kind, sessions without laps
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            TpSegmented {
                Layout.fillWidth: false
                options: [i18n.tr("All"), i18n.tr("Races"), i18n.tr("Qualifying"), i18n.tr("Practice")]
                currentIndex: backend.kindFilter
                maxWidth: root.width - theme.em * 1.4
                onActivated: function(index) { backend.setKindFilter(index) }
            }
            Item { Layout.fillWidth: true }
        }
        TpSwitch {
            text: i18n.tr("Hide sessions without laps")
            checked: backend.hideEmpty
            onToggled: backend.setHideEmpty(checked)
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            focus: true
            activeFocusOnTab: true
            model: backend.sessionModel
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: root.moveSelection(-1)
            Keys.onDownPressed: root.moveSelection(1)

            displaced: Transition { NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic } }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 180 } }

            section.property: "day"
            section.labelPositioning: ViewSection.InlineLabels | ViewSection.CurrentLabelAtStart
            section.delegate: Rectangle {
                required property string section
                width: ListView.view.width
                height: Math.round(theme.em * 2.1)
                color: theme.base
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: theme.em * 0.3
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.section
                    color: theme.dimText
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontPoint * 0.9
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: theme.border; opacity: 0.6 }
            }

            delegate: Rectangle {
                id: row
                required property int index
                required property string key
                required property string title
                required property string course
                required property string code
                required property string kindText
                required property string clock
                required property int cars
                required property bool online
                required property string resultText
                required property string resultTone
                required property string detailText
                required property bool newest
                required property string trackLogo
                readonly property bool selected: key === backend.selectedKey

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 3.4)
                radius: theme.em * 0.5
                color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, rowArea.containsMouse ? 0.22 : 0.15)
                     : rowArea.containsMouse ? theme.hover : "transparent"
                Behavior on color { ColorAnimation { duration: 110 } }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onPressed: {
                        list.forceActiveFocus()
                        backend.select(row.key)
                    }
                }

                // Selected: accent bar
                Rectangle {
                    visible: row.selected
                    width: Math.round(theme.em * 0.22)
                    height: parent.height * 0.56
                    radius: width / 2
                    color: theme.accent
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.6
                    anchors.rightMargin: theme.em * 0.6
                    spacing: theme.em * 0.6

                    ResultsBadge { code: row.code }
                    GameLogo {  // circuit logo of game
                        source: row.trackLogo
                        boxWidth: theme.em * 2.6
                        boxHeight: theme.em * 1.7
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.4
                            Text {
                                Layout.fillWidth: true
                                text: row.title
                                color: theme.text
                                font.weight: row.selected ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                            Rectangle {  // newest session: dot
                                visible: row.newest
                                implicitWidth: Math.round(theme.em * 0.5)
                                implicitHeight: implicitWidth
                                radius: width / 2
                                color: theme.accent
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: [row.kindText, row.clock, row.cars + " " + (row.cars === 1 ? i18n.tr("car") : i18n.tr("cars")),
                                   row.online ? i18n.tr("Online") : ""].filter(function(part) { return part !== "" }).join(" · ")
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.86
                            font.features: { "tnum": 1 }
                            elide: Text.ElideRight
                        }
                    }

                    // Result of player
                    ColumnLayout {
                        spacing: 0
                        visible: row.resultText !== "" || row.detailText !== ""
                        Text {
                            Layout.alignment: Qt.AlignRight
                            visible: row.resultText !== ""
                            text: row.resultText
                            color: row.resultTone === "gold" ? theme.gold : row.resultTone === "gain" ? theme.gain
                                 : row.resultTone === "loss" ? theme.loss : theme.text
                            font.weight: Font.Bold
                            font.pointSize: theme.fontPoint * 1.1
                            font.features: { "tnum": 1 }
                        }
                        Text {
                            Layout.alignment: Qt.AlignRight
                            Layout.maximumWidth: theme.em * 8
                            text: row.detailText
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
