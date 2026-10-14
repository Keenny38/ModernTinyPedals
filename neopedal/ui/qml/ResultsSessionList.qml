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
        // focus put back where it was, but left on the window: list (Up / Down kept)
        onClosed: if (!Window.activeFocusItem || Window.activeFocusItem === Window.contentItem) list.forceActiveFocus()
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
                font.pointSize: theme.fontSubtitle
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
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                }
            }
            BusyIndicator {
                running: backend.busy && pageState.active
                visible: backend.busy
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
        TpSearchField {
            id: searchField
            Layout.fillWidth: true
            searchDelay: 200
            placeholderText: i18n.tr("Search: track, server, car...")
            onSearchChanged: function(text) { backend.setSearch(text) }
            onExitField: list.forceActiveFocus()
            Keys.onEscapePressed: { clearSearch(); list.forceActiveFocus() }
            Keys.onReturnPressed: list.forceActiveFocus()
            Keys.onEnterPressed: list.forceActiveFocus()
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
            readonly property string selectedKey: backend.selectedKey  // read once for every row
            reuseItems: true  // rows scrolled out fed again with other sessions (see delegate onPooled)
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: root.moveSelection(-1)
            Keys.onDownPressed: root.moveSelection(1)

            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }

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
                    font.pointSize: theme.fontLabel
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
                required property bool replay
                readonly property bool selected: key === list.selectedKey
                // Pooled row fed again: no color animation from the session it showed before
                property bool live: true
                ListView.onPooled: { live = false; opacity = 1 }  // add transition may have been running
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 3.4)
                radius: theme.radiusMd
                color: theme.rowColor(rowArea.containsMouse, selected)
                Behavior on color { enabled: row.live; ColorAnimation { duration: theme.motionFast } }

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
                            Icon {  // replay saved by game
                                visible: row.replay
                                glyph: "\uE714"  // video
                                size: theme.em * 0.8
                                color: theme.dimText
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
                            font.pointSize: theme.fontSmall
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
                            font.pointSize: theme.fontSubtitle
                            font.features: { "tnum": 1 }
                        }
                        Text {
                            Layout.alignment: Qt.AlignRight
                            Layout.maximumWidth: theme.em * 8
                            text: row.detailText
                            color: theme.dimText
                            font.pointSize: theme.fontCaption
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
