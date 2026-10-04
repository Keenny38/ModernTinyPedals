import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Lap telemetry viewer page: lap list, channel charts, track map / G circle / corners / range statistics
TpPage {
    id: page

    property bool mapFocus: false  // large track map over laps & charts

    // Page picture (laps, charts, map) saved to PNG or copied to clipboard
    function grabPicture(copy) {
        bodyArea.grabToImage(function(result) {
            if (copy) backend.copyImage(result.image)
            else backend.saveImage(result.image)
        })
    }

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
                tip: i18n.tr("Export laps to MoTeC i2 log files (.ld), displayed charts to CSV (Excel), or a picture of the page")
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
                    MenuSeparator {}
                    Action { text: i18n.tr("Picture (PNG)..."); onTriggered: page.grabPicture(false) }
                    Action { text: i18n.tr("Copy Picture"); onTriggered: page.grabPicture(true) }
                }
            }

            Item { Layout.fillWidth: true }

            TpSwitch {
                text: i18n.tr("Live")
                tip: i18n.tr("New recorded laps listed at once, newest lap compared with best lap")
                checked: backend.liveMode
                onToggled: backend.setLiveMode(checked)
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
                    width: theme.em * 19
                    height: Math.min(theme.em * 38, page.height - theme.em * 6)
                    padding: theme.em * 0.5
                    onOpened: searchField.forceActiveFocus()
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
                        spacing: theme.em * 0.35
                        TextField {
                            id: searchField
                            Layout.fillWidth: true
                            placeholderText: i18n.tr("Search channel")
                            color: theme.text
                            placeholderTextColor: theme.dimText
                            background: Rectangle {
                                radius: theme.em * 0.45
                                color: theme.base
                                border.width: 1
                                border.color: searchField.activeFocus ? theme.accent : theme.border
                            }
                        }
                        // Presets
                        Flow {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.25
                            Repeater {
                                model: backend.channelPresets
                                TpButton {
                                    text: modelData.title
                                    implicitHeight: theme.em * 1.8
                                    flat: true
                                    onClicked: backend.applyPreset(modelData.name)
                                }
                            }
                        }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: {
                                var query = searchField.text.toLowerCase().trim()
                                if (query === "") return backend.channelMenu
                                return backend.channelMenu.filter(function(item) {
                                    return item.search.indexOf(query) >= 0 || item.group.toLowerCase().indexOf(query) >= 0
                                })
                            }
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
                                opacity: modelData.available || modelData.visible ? 1 : 0.45
                                ToolTip.visible: channelArea.containsMouse && !modelData.available
                                ToolTip.text: i18n.tr("Not recorded in shown laps")
                                ToolTip.delay: 500
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
                                    Text { text: modelData.title; color: theme.text; Layout.fillWidth: true; elide: Text.ElideRight }
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
                        // Display options
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.4
                            Text { text: i18n.tr("Smoothing"); color: theme.dimText }
                            Slider {
                                id: smoothSlider
                                Layout.fillWidth: true
                                from: 0; to: backend.smoothingLevels - 1; stepSize: 1
                                snapMode: Slider.SnapAlways
                                value: backend.smoothing
                                onMoved: backend.setSmoothing(Math.round(value))
                                ToolTip.visible: hovered
                                ToolTip.text: i18n.tr("Moving average of noisy channels: G, steering rate, wheel slip, time gain/loss")
                            }
                            Text { text: backend.smoothing === 0 ? i18n.tr("Off") : backend.smoothing; color: theme.text; Layout.preferredWidth: theme.em * 1.8 }
                        }
                        Text {
                            text: i18n.tr("Gain/Loss window")
                            color: theme.dimText
                            ToolTip.visible: windowArea.containsMouse
                            ToolTip.text: i18n.tr("Distance over which time gain/loss is measured (chart & map)")
                            MouseArea { id: windowArea; anchors.fill: parent; hoverEnabled: true }
                        }
                        TpSegmented {
                            Layout.alignment: Qt.AlignHCenter
                            options: backend.deltaWindows.map(function(meters) { return meters + " m" })
                            currentIndex: backend.deltaWindows.indexOf(backend.deltaWindow)
                            onActivated: function(index) { backend.setDeltaWindow(backend.deltaWindows[index]) }
                        }
                        TpSwitch {
                            text: i18n.tr("Min / max band")
                            tip: i18n.tr("Lowest & highest value of shown laps (3 laps or more): consistency")
                            checked: backend.envelope
                            onToggled: backend.setEnvelope(checked)
                        }
                        TpButton {
                            Layout.fillWidth: true
                            text: i18n.tr("Reset")
                            flat: true
                            onClicked: { backend.resetChannels(); backend.resetPanelWeights() }
                        }
                    }
                }
            }
        }

        // Laps | charts | map, G circle, corners & range
        Item {
            id: bodyArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            SplitView {
                id: body
                anchors.fill: parent
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
                Component.onCompleted: if (backend.layoutState.length > 0) restoreState(backend.layoutState)
                onResizingChanged: if (!resizing) backend.setLayoutState(saveState())

                LapList {
                    chart: chart
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
                        onPictureRequested: function(copy) { page.grabPicture(copy) }
                        onRangeSet: backend.setSideTab(3)
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
                            options: [i18n.tr("Track Map"), i18n.tr("G Circle"), i18n.tr("Corners"), i18n.tr("Range")]
                            currentIndex: backend.sideTab
                            onActivated: function(index) { backend.setSideTab(index) }
                            Connections {  // tab changed by code (markers set): clicking a tab replaced the binding
                                target: backend
                                function onOptionsChanged() { sideTabs.currentIndex = backend.sideTab }
                            }
                        }
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            TrackMap {
                                anchors.fill: parent
                                chart: chart
                                opacity: sideTabs.currentIndex === 0 && !page.mapFocus ? 1 : 0
                                visible: opacity > 0
                                Behavior on opacity { NumberAnimation { duration: 180 } }
                                onExpandToggled: page.mapFocus = true
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
                            RangeStats {
                                anchors.fill: parent
                                chart: chart
                                opacity: sideTabs.currentIndex === 3 ? 1 : 0
                                visible: opacity > 0
                                Behavior on opacity { NumberAnimation { duration: 180 } }
                            }
                        }
                    }
                }
            }

            // Focus mode: large track map over laps & charts (charts keep driving cursor & zoom)
            Card {
                anchors.fill: parent
                visible: opacity > 0
                opacity: page.mapFocus ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 200 } }
                TrackMap {
                    anchors.fill: parent
                    anchors.margins: theme.em * 0.6
                    chart: chart
                    expanded: true
                    visible: page.mapFocus
                    onExpandToggled: page.mapFocus = false
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
            Text { text: backend.warning; color: theme.warning; Layout.fillWidth: true; elide: Text.ElideRight }
        }
    }
}
