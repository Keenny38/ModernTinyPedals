import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Show menu of lap viewer, one for both views: channels shown on charts (advanced view) are the items of simple view.
// Search, presets, groups (all on / off) & their channels (chips; one wheel channels listed while shown or searched,
// channels not recorded in shown laps dimmed), then chart options: smoothing, gain/loss window, min / max band,
// delta vs ideal lap, math channels, reset
Popup {
    id: picker

    signal mathRequested()

    readonly property var catalog: visible ? backend.dashboardCatalog : []
    readonly property string query: searchField.text.toLowerCase().trim()
    function matches(item) { return query !== "" && item.search.indexOf(query) >= 0 }
    function listed(item) { return query === "" ? !item.detail || item.shown : matches(item) }

    width: theme.em * 24
    padding: theme.em * 0.6
    onOpened: searchField.forceActiveFocus()
    onClosed: searchField.text = ""
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
        spacing: theme.em * 0.4
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
            visible: picker.query === ""
            Repeater {
                model: backend.channelPresets
                TpButton {
                    required property var modelData
                    text: modelData.title
                    implicitHeight: theme.em * 1.8
                    flat: true
                    onClicked: backend.applyPreset(modelData.name)
                }
            }
        }
        Flickable {
            id: pickerList
            objectName: "showList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 8
            implicitHeight: pickerGroups.height
            contentHeight: pickerGroups.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            Column {
                id: pickerGroups
                width: pickerList.width - theme.em * 0.6
                spacing: theme.em * 0.6
                Repeater {
                    model: picker.catalog
                    Column {
                        id: pickerGroup
                        required property var modelData
                        readonly property var items: modelData.items.filter(picker.listed)
                        readonly property bool anyShown: modelData.items.some(function(item) { return item.shown })
                        width: pickerGroups.width
                        spacing: theme.em * 0.3
                        visible: items.length > 0
                        Rectangle {
                            width: parent.width
                            height: theme.em * 1.8
                            radius: theme.em * 0.4
                            color: groupArea.containsMouse ? theme.hover : "transparent"
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                x: theme.em * 0.3
                                spacing: theme.em * 0.5
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: theme.em * 1.05
                                    height: width
                                    radius: theme.em * 0.28
                                    color: pickerGroup.anyShown ? theme.accent : "transparent"
                                    border.width: pickerGroup.anyShown ? 0 : 1.5
                                    border.color: theme.dimText
                                    Icon { anchors.centerIn: parent; glyph: ""; size: theme.em * 0.7; color: "white"; visible: pickerGroup.anyShown && theme.iconFont !== "" }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: pickerGroup.modelData.title
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                }
                            }
                            MouseArea {
                                id: groupArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: backend.setDashboardGroup(pickerGroup.modelData.key, !pickerGroup.anyShown)
                            }
                        }
                        Flow {
                            width: parent.width
                            leftPadding: theme.em * 0.3
                            spacing: theme.em * 0.25
                            Repeater {
                                model: pickerGroup.items
                                Rectangle {
                                    id: chip
                                    required property var modelData
                                    readonly property string channel: modelData.key
                                    readonly property bool shown: modelData.shown
                                    readonly property bool detail: modelData.detail
                                    objectName: "showChip"
                                    height: theme.em * 1.6
                                    width: chipText.implicitWidth + theme.em * 0.9
                                    radius: height / 2
                                    color: modelData.shown ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.22) : "transparent"
                                    border.width: 1
                                    border.color: modelData.shown ? theme.accent : theme.border
                                    opacity: modelData.available || modelData.shown ? 1 : 0.45
                                    ToolTip.visible: chipArea.containsMouse && !modelData.available
                                    ToolTip.text: i18n.tr("Not recorded in shown laps")
                                    ToolTip.delay: 500
                                    Text {
                                        id: chipText
                                        anchors.centerIn: parent
                                        text: chip.modelData.title
                                        color: chip.modelData.shown ? theme.text : theme.dimText
                                        font.pointSize: theme.fontPoint * 0.85
                                    }
                                    MouseArea {
                                        id: chipArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: backend.setChannelVisible(chip.modelData.key, !chip.modelData.shown)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Text {  // search without result
                width: pickerList.width
                y: theme.em * 0.8
                visible: picker.query !== "" && !picker.catalog.some(function(group) { return group.items.some(picker.matches) })
                text: i18n.tr("No channel matches")
                color: theme.dimText
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border }
        // Display options
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            Text { text: i18n.tr("Smoothing"); color: theme.dimText }
            Slider {
                Layout.fillWidth: true
                from: 0; to: backend.smoothingLevels - 1; stepSize: 1
                snapMode: Slider.SnapAlways
                focusPolicy: Qt.NoFocus
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
            options: backend.deltaWindowTexts
            currentIndex: backend.deltaWindows.indexOf(backend.deltaWindow)
            onActivated: function(index) { backend.setDeltaWindow(backend.deltaWindows[index]) }
        }
        TpSwitch {
            text: i18n.tr("Min / max band")
            tip: i18n.tr("Lowest & highest value of shown laps (3 laps or more): consistency")
            checked: backend.envelope
            onToggled: backend.setEnvelope(checked)
        }
        TpSwitch {
            text: i18n.tr("Delta vs ideal lap")
            tip: i18n.tr("Delta & time gain/loss against ideal lap: fastest clean shown lap in each mini-sector")
            checked: backend.idealDelta
            onToggled: backend.setIdealDelta(checked)
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            TpButton {
                Layout.fillWidth: true
                text: i18n.tr("Math Channels...")
                flat: true
                tip: i18n.tr("Channels computed from others: understeer angle, pedal rates, your own expressions")
                onClicked: { picker.close(); picker.mathRequested() }
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
