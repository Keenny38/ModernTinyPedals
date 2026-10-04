import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Lap telemetry viewer page: lap list, channel charts, track map / G circle / corners
TpPage {
    id: page

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5

            ComboBox {
                id: trackBox
                Layout.preferredWidth: theme.em * 20
                implicitHeight: Math.round(theme.em * 2.3)
                model: backend.tracks
                currentIndex: backend.tracks.indexOf(backend.currentTrack)
                onActivated: function(index) { backend.currentTrack = backend.tracks[index] }
                background: Rectangle {
                    radius: theme.em * 0.55
                    color: trackBox.hovered ? theme.hover : theme.raised
                    border.width: 1
                    border.color: trackBox.popup.visible ? theme.accent : theme.border
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
                contentItem: RowLayout {
                    spacing: theme.em * 0.5
                    Icon { glyph: ""; color: theme.accent; Layout.leftMargin: theme.em * 0.6 }  // map pin
                    Text {
                        text: trackBox.displayText || i18n.tr("No recorded lap")
                        color: theme.text
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
                indicator: Icon {
                    glyph: ""  // chevron down
                    size: theme.em * 0.75
                    color: theme.dimText
                    x: trackBox.width - width - theme.em * 0.7
                    y: (trackBox.height - height) / 2
                }
                popup: Popup {
                    y: trackBox.height + 4
                    width: trackBox.width
                    padding: 4
                    implicitHeight: Math.min(contentItem.implicitHeight + 8, theme.em * 24)
                    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
                    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
                    contentItem: ListView {
                        clip: true
                        implicitHeight: contentHeight
                        model: trackBox.popup.visible ? trackBox.delegateModel : null
                        ScrollBar.vertical: ScrollBar {}
                    }
                    background: Rectangle {
                        radius: theme.em * 0.6
                        color: theme.raised
                        border.width: 1
                        border.color: theme.border
                    }
                }
                delegate: ItemDelegate {
                    required property string modelData
                    required property int index
                    width: trackBox.width - 8
                    height: theme.em * 2.2
                    highlighted: trackBox.highlightedIndex === index
                    contentItem: Text {
                        text: parent.modelData
                        color: theme.text
                        font.weight: trackBox.currentIndex === parent.index ? Font.DemiBold : Font.Normal
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle {
                        radius: theme.em * 0.4
                        color: parent.highlighted ? theme.hover : "transparent"
                    }
                }
            }
            TpButton { glyph: ""; tip: i18n.tr("Refresh"); onClicked: backend.refresh() }  // refresh
            TpButton { glyph: ""; text: i18n.tr("Add File..."); tip: i18n.tr("Add laps from another folder or track, or import a MoTeC log (.ld)"); onClicked: backend.addFiles() }
            TpButton {
                glyph: ""  // folder
                text: i18n.tr("Imported Laps...")
                tip: i18n.tr("Laps imported from MoTeC logs: add to viewer, rename, delete")
                onClicked: backend.openLibrary()
            }
            TpButton {
                id: exportButton
                glyph: ""  // export
                text: i18n.tr("Export")
                tip: i18n.tr("Export laps to MoTeC i2 log files (.ld), or displayed charts to CSV (Excel)")
                checked: exportMenu.visible
                onClicked: exportMenu.visible ? exportMenu.close() : exportMenu.popup(exportButton, 0, exportButton.height + 4)
                TpMenu {
                    id: exportMenu
                    TpMenu {
                        title: "MoTeC i2 (.ld)"
                        Action { text: i18n.tr("Reference Lap..."); onTriggered: backend.exportMotec("") }
                        Action { text: i18n.tr("Displayed Laps..."); onTriggered: backend.exportMotecMany(false) }
                        Action { text: i18n.tr("All Laps of Track..."); onTriggered: backend.exportMotecMany(true) }
                    }
                    Action { text: i18n.tr("CSV, Displayed Laps..."); onTriggered: backend.exportCsv() }
                }
            }

            // Legend: lap colors
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: theme.em * 0.6
                spacing: theme.em * 0.35
                Repeater {
                    model: backend.legend
                    Rectangle {
                        height: theme.em * 1.8
                        width: chipRow.implicitWidth + theme.em * 1.0
                        radius: height / 2
                        color: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.14)
                        border.width: modelData.reference ? 1.5 : 0
                        border.color: modelData.color
                        opacity: 0
                        Component.onCompleted: opacity = 1
                        Behavior on opacity { NumberAnimation { duration: 200 } }
                        ToolTip.visible: chipArea.containsMouse
                        ToolTip.text: modelData.full
                        ToolTip.delay: 400
                        MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true }
                        Row {
                            id: chipRow
                            anchors.centerIn: parent
                            spacing: theme.em * 0.4
                            Rectangle { width: theme.em * 0.55; height: width; radius: width / 2; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                text: modelData.label
                                color: theme.text
                                font.pointSize: theme.fontPoint * 0.9
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                visible: modelData.reference
                                text: i18n.tr("REF")
                                color: modelData.color
                                font.pointSize: theme.fontPoint * 0.75
                                font.weight: Font.Bold
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                }
            }

            TpSwitch {
                text: i18n.tr("Time axis")
                tip: i18n.tr("Charts along lap time instead of lap distance")
                checked: backend.timeAxis
                onToggled: backend.setTimeAxis(checked)
            }
            TpButton {
                id: channelButton
                glyph: ""  // area chart
                text: i18n.tr("Channels")
                checked: channelPopup.visible
                onClicked: channelPopup.visible ? channelPopup.close() : channelPopup.open()

                Popup {
                    id: channelPopup
                    y: channelButton.height + 6
                    x: channelButton.width - width
                    width: theme.em * 17
                    height: Math.min(theme.em * 30, page.height - theme.em * 6)
                    padding: theme.em * 0.4
                    enter: Transition {
                        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 150 }
                        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: 150; easing.type: Easing.OutCubic }
                    }
                    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
                    background: Rectangle {
                        radius: theme.em * 0.7
                        color: theme.raised
                        border.width: 1
                        border.color: theme.border
                    }
                    contentItem: ColumnLayout {
                        spacing: theme.em * 0.3
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: backend.channelMenu
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar {}
                            section.property: "group"
                            section.delegate: Text {
                                required property string section
                                text: section
                                visible: section !== ""
                                height: section !== "" ? implicitHeight + theme.em * 0.6 : 0
                                verticalAlignment: Text.AlignBottom
                                leftPadding: theme.em * 0.4
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.8
                                font.weight: Font.DemiBold
                            }
                            delegate: Rectangle {
                                width: ListView.view.width - theme.em * 0.6
                                height: theme.em * 2
                                radius: theme.em * 0.4
                                color: channelArea.containsMouse ? theme.hover : "transparent"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: theme.em * 0.4
                                    spacing: theme.em * 0.5
                                    Rectangle {
                                        implicitWidth: theme.em * 1.05
                                        implicitHeight: implicitWidth
                                        radius: theme.em * 0.28
                                        color: modelData.visible ? theme.accent : "transparent"
                                        border.width: modelData.visible ? 0 : 1.5
                                        border.color: theme.dimText
                                        Icon { anchors.centerIn: parent; glyph: ""; size: theme.em * 0.7; color: "white"; visible: modelData.visible && theme.iconFont !== "" }
                                    }
                                    Text { text: modelData.title; color: theme.text; Layout.fillWidth: true }
                                }
                                MouseArea {
                                    id: channelArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.setChannelVisible(modelData.column, !modelData.visible)
                                }
                            }
                        }
                        TpButton {
                            Layout.fillWidth: true
                            text: i18n.tr("Reset")
                            flat: true
                            onClicked: backend.resetChannels()
                        }
                    }
                }
            }
        }

        // Laps | charts | map, G circle & corners
        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: Item {
                implicitWidth: theme.em * 0.6
                Rectangle {
                    anchors.centerIn: parent
                    width: 3
                    height: theme.em * 2.5
                    radius: 1.5
                    color: SplitHandle.pressed ? theme.accent : SplitHandle.hovered ? theme.dimText : theme.border
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
            }

            LapList {
                SplitView.preferredWidth: theme.em * 21
                SplitView.minimumWidth: theme.em * 14
            }

            Card {
                SplitView.fillWidth: true
                SplitView.minimumWidth: theme.em * 30
                TraceChart {
                    id: chart
                    anchors.fill: parent
                    anchors.margins: theme.em * 0.6
                    anchors.leftMargin: theme.em * 0.2
                }
            }

            Card {
                SplitView.preferredWidth: theme.em * 27
                SplitView.minimumWidth: theme.em * 18
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: theme.em * 0.6
                    spacing: theme.em * 0.5
                    TpSegmented {
                        id: sideTabs
                        Layout.alignment: Qt.AlignHCenter
                        options: [i18n.tr("Track Map"), i18n.tr("G Circle"), i18n.tr("Corners")]
                    }
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        TrackMap {
                            anchors.fill: parent
                            chart: chart
                            opacity: sideTabs.currentIndex === 0 ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                        }
                        GCircle {
                            anchors.fill: parent
                            chart: chart
                            opacity: sideTabs.currentIndex === 1 ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                        }
                        CornerList {
                            anchors.fill: parent
                            chart: chart
                            opacity: sideTabs.currentIndex === 2 ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                        }
                    }
                }
            }
        }

        // Status
        RowLayout {
            Layout.fillWidth: true
            visible: backend.status !== "" || backend.warning !== "" || backend.loading
            spacing: theme.em * 0.5
            BusyIndicator {
                running: backend.loading
                visible: running
                implicitWidth: theme.em * 1.4
                implicitHeight: implicitWidth
            }
            Text { text: backend.status; color: theme.dimText; textFormat: Text.StyledText }
            Text { text: backend.warning; color: "#F97316"; Layout.fillWidth: true; elide: Text.ElideRight }
        }
    }
}
