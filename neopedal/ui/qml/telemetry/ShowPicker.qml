import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Show menu of lap viewer, one for both views: channels shown on charts (advanced view) are the items of simple view.
// Search (Enter shows or hides the first channel found), presets, groups (box: all, some or none shown; click: all on,
// or all off once every channel shown) & their channels (chips; one wheel channels listed while shown or searched,
// channels not recorded in shown laps marked ∅), then chart options: smoothing, gain/loss window, min / max band,
// delta vs ideal lap, math channels, reset (confirmed). Tab moves through it, Esc clears search, then closes.
TpPopup {
    id: picker

    signal mathRequested()

    // Channels: read when first opened, then kept while closed (chips made once), read again on opening only if
    // channels or their availability changed (never on toggles: chips kept). Shown state apart, read while open:
    // channels & group boxes looked up by key (no scan of every channel per group on each toggle)
    property var catalog: []
    property bool catalogStale: true
    property var shownState: ({ "channels": {}, "groups": {} })
    readonly property var shownKeys: shownState.channels
    readonly property string query: searchField.text.toLowerCase().trim()
    function isShown(item) { return shownKeys[item.key] === true }
    function matches(item) { return query !== "" && item.search.indexOf(query) >= 0 }
    function readShown() { shownState = backend.dashboard.shownState }
    function readCatalog() {
        if (!catalogStale) return
        catalogStale = false
        catalog = backend.dashboard.channels
    }
    onAboutToShow: { readShown(); readCatalog() }  // shown state first: new chips made in their final state
    Connections {
        target: backend.dashboard
        function onChanged() { if (picker.visible) picker.readShown() }
        function onChannelsChanged() {
            picker.catalogStale = true
            if (picker.visible) { picker.readShown(); picker.readCatalog() }
        }
    }
    // Enter in search: first channel found shown (or hidden if it was)
    function toggleFirstMatch() {
        for (var i = 0; i < catalog.length; i++) {
            var items = catalog[i].items
            for (var j = 0; j < items.length; j++)
                if (matches(items[j])) { backend.setChannelVisible(items[j].key, !isShown(items[j])); return }
        }
    }

    width: theme.em * 24
    padding: theme.space4
    onOpened: searchField.forceActiveFocus()
    onClosed: searchField.text = ""
    contentItem: ColumnLayout {
        spacing: theme.space3
        TpSearchField {
            id: searchField
            Layout.fillWidth: true
            searchDelay: 0  // query bound to text
            placeholderText: i18n.tr("Search channel")
            onExitField: picker.close()  // Esc: clears search, then closes
            Keys.onReturnPressed: picker.toggleFirstMatch()
            Keys.onEnterPressed: picker.toggleFirstMatch()
        }
        // Presets
        Flow {
            Layout.fillWidth: true
            spacing: theme.space2
            visible: picker.query === ""
            Repeater {
                model: backend.channelPresets
                TpButton {
                    required property var modelData
                    text: modelData.title
                    size: "sm"
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
                width: pickerList.width - theme.space4
                spacing: theme.space4
                Repeater {
                    model: picker.catalog
                    Column {
                        id: pickerGroup
                        required property var modelData
                        // 0 none, 1 some, 2 all shown (one wheel channels aside: what a click on the box shows)
                        readonly property int shownLevel: picker.shownState.groups[modelData.key] || 0
                        readonly property bool anyShown: shownLevel > 0
                        readonly property bool allShown: shownLevel === 2
                        width: pickerGroups.width
                        spacing: theme.space2
                        // listed: always without search (one wheel channels come with their 4 wheels channel)
                        visible: picker.query === "" ? modelData.items.length > 0 : modelData.items.some(picker.matches)
                        // Group: box checked (all shown), mixed (some), empty (none); click: all on, or all off
                        Rectangle {
                            id: groupRow
                            width: parent.width
                            height: Math.round(theme.controlHeightSm)
                            radius: theme.radiusMd
                            color: groupArea.pressed ? theme.surfaceSunken : groupArea.containsMouse ? theme.hover : "transparent"
                            activeFocusOnTab: true
                            Accessible.role: Accessible.CheckBox
                            Accessible.name: pickerGroup.modelData.title
                            Accessible.checked: pickerGroup.allShown
                            Accessible.checkStateMixed: pickerGroup.anyShown && !pickerGroup.allShown
                            function toggle() { backend.dashboard.setGroup(pickerGroup.modelData.key, !pickerGroup.allShown) }
                            Keys.onSpacePressed: toggle()
                            Keys.onReturnPressed: toggle()
                            Keys.onEnterPressed: toggle()
                            FocusRing { visible: groupRow.activeFocus }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                x: theme.space2
                                spacing: theme.space3
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: theme.em * 1.05
                                    height: width
                                    radius: theme.radiusSm
                                    color: pickerGroup.anyShown ? theme.accentFill : "transparent"
                                    border.width: pickerGroup.anyShown ? 0 : 1.5
                                    border.color: theme.dimText
                                    Icon {
                                        anchors.centerIn: parent
                                        glyph: pickerGroup.allShown ? "" : ""  // check (all), minus (some)
                                        fallback: pickerGroup.allShown ? "✓" : "–"
                                        size: theme.iconXs
                                        color: theme.inkOn(theme.accentFill)
                                        visible: pickerGroup.anyShown && text !== ""
                                    }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: pickerGroup.modelData.title
                                    textFormat: Text.PlainText
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                }
                            }
                            MouseArea {
                                id: groupArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: groupRow.toggle()
                            }
                        }
                        Flow {
                            width: parent.width
                            leftPadding: theme.space2
                            spacing: theme.space2
                            Repeater {
                                model: pickerGroup.modelData.items  // every chip kept, hidden while not listed
                                TpChip {
                                    id: chip
                                    required property var modelData
                                    readonly property string channel: modelData.key
                                    readonly property bool shown: picker.shownKeys[modelData.key] === true
                                    readonly property bool detail: modelData.detail
                                    objectName: "showChip"
                                    // one wheel channels listed while shown or searched
                                    visible: picker.query === "" ? !detail || shown : picker.matches(modelData)
                                    size: "sm"
                                    multi: true
                                    selected: shown
                                    // not recorded in shown laps: marked (never only faded)
                                    text: (modelData.available || shown ? "" : "∅ ") + modelData.title
                                    tip: modelData.available ? "" : i18n.tr("Not recorded in shown laps")
                                    onClicked: backend.setChannelVisible(chip.modelData.key, !chip.shown)
                                }
                            }
                        }
                    }
                }
            }
            Text {  // search without result
                width: pickerList.width
                y: theme.space5
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
            spacing: theme.space3
            Text { text: i18n.tr("Smoothing"); color: theme.dimText }
            TpSlider {
                Layout.fillWidth: true
                from: 0; to: backend.smoothingLevels - 1; stepSize: 1
                snapMode: Slider.SnapAlways
                value: backend.smoothing
                onMoved: backend.setSmoothing(Math.round(value))
                tip: i18n.tr("Moving average of noisy channels: G, steering rate, wheel slip, time gain/loss")
            }
            Text { text: backend.smoothing === 0 ? i18n.tr("Off") : backend.smoothing; color: theme.text; Layout.preferredWidth: theme.em * 1.8; textFormat: Text.PlainText }
        }
        Text {
            text: i18n.tr("Gain/Loss window")
            color: theme.dimText
            ToolTip.visible: windowArea.containsMouse
            ToolTip.text: i18n.tr("Distance over which time gain/loss is measured (chart & map)")
            ToolTip.delay: theme.tipDelay
            MouseArea { id: windowArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
        }
        TpSegmented {
            Layout.alignment: Qt.AlignHCenter
            name: i18n.tr("Gain/Loss window")
            options: backend.deltaWindowTexts
            currentIndex: backend.deltaWindows.indexOf(backend.deltaWindow)
            onActivated: function(index) { backend.setDeltaWindow(backend.deltaWindows[index]) }
        }
        TpSwitch {
            text: i18n.tr("Min / max band")
            tip: i18n.tr("Lowest & highest value of shown laps (3 laps or more): consistency")
            checked: backend.envelope
            checkable: false  // follows the backend (never unbound by a click)
            onClicked: backend.setEnvelope(!backend.envelope)
        }
        TpSwitch {
            text: i18n.tr("Delta vs ideal lap")
            tip: i18n.tr("Delta & time gain/loss against ideal lap: fastest clean shown lap in each mini-sector")
            checked: backend.idealDelta
            checkable: false
            onClicked: backend.setIdealDelta(!backend.idealDelta)
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpButton {
                Layout.fillWidth: true
                text: i18n.tr("Math Channels…")
                flat: true
                tip: i18n.tr("Channels computed from others: understeer angle, pedal rates, your own expressions")
                onClicked: { picker.close(); picker.mathRequested() }
            }
            TpButton {
                Layout.fillWidth: true
                text: i18n.tr("Reset")
                flat: true
                tip: i18n.tr("Default channels & chart heights")
                onClicked: resetDialog.open()
            }
        }
    }
    // Shown channels & chart heights back to defaults: asked first (own choice of channels lost)
    TpConfirmDialog {
        id: resetDialog
        objectName: "showResetDialog"
        title: i18n.tr("Reset shown channels?")
        text: i18n.tr("Channels shown on charts & simple view and chart heights go back to defaults.")
        acceptText: i18n.tr("Reset")
        onAccepted: { backend.resetChannels(); backend.resetPanelWeights() }
    }
}
