import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Spectate page: spectate mode switch, spectated driver card (previous / next by place), drivers of the
// session with search, class chips & sort. Click a driver to spectate it (turns spectate mode on).
// Keys: type to search, "/" search, arrows move, Enter or Space spectates, Alt+Left / Alt+Right previous / next.
TpPage {
    id: page

    readonly property var spectated: backend.spectated
    readonly property bool compact: width < theme.em * 40

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }

    Keys.onPressed: function(event) {
        if (event.modifiers & Qt.AltModifier && backend.enabled) {
            if (event.key === Qt.Key_Left) { backend.step(-1); event.accepted = true }
            else if (event.key === Qt.Key_Right) { backend.step(1); event.accepted = true }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.8
        anchors.bottomMargin: theme.em * 0.6
        spacing: theme.em * 0.6

        // Title & spectate mode
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Text {
                    text: i18n.tr("Spectate")
                    color: theme.text
                    font.pointSize: theme.fontPoint * 1.5
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Show the data of another driver in your overlays")
                    color: theme.dimText
                    elide: Text.ElideRight
                }
            }
            TpSwitch {
                checkable: false  // follows backend
                checked: backend.enabled
                text: backend.enabled ? i18n.tr("Enabled") : i18n.tr("Disabled")
                tip: i18n.tr("Spectate mode")
                onClicked: backend.setEnabled(!backend.enabled)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Spectate mode")
                Accessible.checked: backend.enabled
            }
        }

        // Spectated driver
        Card {
            id: hero
            Layout.fillWidth: true
            implicitHeight: heroRow.implicitHeight + theme.em * 1.4
            color: backend.enabled && page.spectated.found
                   ? Qt.tint(theme.base, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.08)) : theme.base
            Behavior on color { ColorAnimation { duration: 200 } }

            RowLayout {
                id: heroRow
                anchors.fill: parent
                anchors.margins: theme.em * 0.7
                spacing: theme.em * 0.8

                Rectangle {
                    Layout.preferredWidth: Math.round(theme.em * 2.8)
                    Layout.preferredHeight: Layout.preferredWidth
                    Layout.alignment: Qt.AlignVCenter
                    radius: width / 2
                    color: page.spectated.found ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.18) : theme.hover
                    Icon {
                        anchors.centerIn: parent
                        glyph: backend.enabled ? "" : ""  // view, car
                        size: theme.em * 1.3
                        color: page.spectated.found ? theme.accent : theme.dimText
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: theme.iconFont === ""
                        text: page.spectated.found ? page.spectated.place : "?"
                        color: theme.text
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        Layout.fillWidth: true
                        text: !backend.enabled ? i18n.tr("Spectate mode is off")
                            : page.spectated.found ? i18n.tr("Spectating")
                            : page.spectated.slot >= 0 ? i18n.tr("Spectated driver is not in this session")
                            : i18n.tr("No driver spectated")
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.85
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: page.spectated.found ? page.spectated.name
                            : backend.enabled ? i18n.tr("Pick a driver in the list")
                            : i18n.tr("Your overlays show your own car")
                        color: theme.text
                        font.pointSize: theme.fontPoint * (page.spectated.found ? 1.35 : 1.1)
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Flow {
                        Layout.fillWidth: true
                        visible: page.spectated.found === true
                        spacing: theme.em * 0.35
                        Pill {
                            visible: (page.spectated.place || 0) > 0
                            text: "P" + page.spectated.place
                            solid: true
                        }
                        Pill {
                            visible: (page.spectated.carClass || "") !== ""
                            text: page.spectated.carClass || ""
                            tint: page.spectated.classColor || theme.accent
                        }
                        Pill {
                            visible: (page.spectated.status || "") !== ""
                            text: page.spectated.status === "garage" ? i18n.tr("Garage") : i18n.tr("Pit")
                            tint: page.spectated.status === "garage" ? theme.dimText : theme.warning
                        }
                        Text {
                            text: page.spectated.vehicle || ""
                            visible: text !== ""
                            color: theme.dimText
                            height: Math.round(theme.em * 1.45)
                            verticalAlignment: Text.AlignVCenter
                        }
                        Text {
                            text: (page.spectated.bestLap || "") !== "" ? i18n.tr("Best Lap") + " " + page.spectated.bestLap : ""
                            visible: text !== ""
                            color: theme.dimText
                            height: Math.round(theme.em * 1.45)
                            verticalAlignment: Text.AlignVCenter
                            font.features: { "tnum": 1 }
                        }
                    }
                }
                Row {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: theme.em * 0.3
                    visible: backend.enabled
                    TpButton {
                        glyph: ""  // chevron left
                        text: theme.iconFont === "" ? "<" : ""
                        tip: i18n.tr("Previous driver (by place)") + "  Alt+Left"
                        enabled: backend.driverCount > 0
                        onClicked: backend.step(-1)
                    }
                    TpButton {
                        glyph: ""  // chevron right
                        text: theme.iconFont === "" ? ">" : ""
                        tip: i18n.tr("Next driver (by place)") + "  Alt+Right"
                        enabled: backend.driverCount > 0
                        onClicked: backend.step(1)
                    }
                    TpButton {
                        visible: page.spectatedSlotSet
                        flat: true
                        glyph: ""  // cancel
                        text: page.compact && theme.iconFont !== "" ? "" : i18n.tr("Stop")
                        tip: i18n.tr("Stop spectating this driver")
                        onClicked: backend.stopSpectating()
                    }
                }
                TpButton {
                    visible: !backend.enabled
                    Layout.alignment: Qt.AlignVCenter
                    accent: true
                    text: i18n.tr("Turn On Spectate Mode")
                    onClicked: backend.setEnabled(true)
                }
            }
        }

        // Search & sort
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            TpSearchField {
                id: search
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                placeholderText: i18n.tr("Search drivers, cars, classes") + "   /"
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: drivers.forceActiveFocus()
                Keys.onReturnPressed: drivers.forceActiveFocus()
                Keys.onEnterPressed: drivers.forceActiveFocus()
            }
            TpSegmented {
                options: [i18n.tr("Position"), i18n.tr("Name")]
                currentIndex: backend.sortByName ? 1 : 0
                onActivated: function(index) { backend.setSortByName(index === 1) }
            }
        }

        // Class chips (2 classes or more)
        Flow {
            Layout.fillWidth: true
            visible: backend.classes.length > 0
            spacing: theme.em * 0.35
            OverlayChip {
                text: i18n.tr("All")
                showDot: false
                count: backend.driverCount
                selected: backend.classFilter === ""
                onClicked: backend.setClassFilter("")
            }
            Repeater {
                model: backend.classes
                OverlayChip {
                    required property var modelData
                    text: modelData.label
                    dotColor: modelData.color
                    count: modelData.count
                    selected: backend.classFilter === modelData.key
                    onClicked: backend.setClassFilter(selected ? "" : modelData.key)
                }
            }
        }

        // Drivers
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: drivers
                anchors.fill: parent
                clip: true
                model: backend.drivers
                boundsBehavior: Flickable.StopAtBounds
                highlightFollowsCurrentItem: false
                keyNavigationEnabled: true
                activeFocusOnTab: true
                cacheBuffer: theme.em * 30
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: SpectateRow {
                    onPicked: function(slot) { backend.spectate(slot) }
                }

                add: Transition {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 }
                }
                remove: Transition {
                    NumberAnimation { property: "opacity"; to: 0; duration: 120 }
                }
                displaced: Transition {
                    NumberAnimation { properties: "y"; duration: 220; easing.type: Easing.OutCubic }
                    NumberAnimation { property: "opacity"; to: 1; duration: 220 }
                }
                move: Transition {
                    NumberAnimation { properties: "y"; duration: 260; easing.type: Easing.OutCubic }
                }

                Keys.onReturnPressed: if (currentItem) backend.spectate(currentItem.slot)
                Keys.onEnterPressed: if (currentItem) backend.spectate(currentItem.slot)
                Keys.onSpacePressed: if (currentItem) backend.spectate(currentItem.slot)
                Keys.onPressed: function(event) {
                    // Type to search
                    var code = event.text.length === 1 ? event.text.charCodeAt(0) : 0
                    if (event.text === "/" || (code > 32 && code !== 127
                            && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)))) {
                        search.forceActiveFocus()
                        if (event.text !== "/") {
                            search.insert(search.length, event.text)
                            backend.setSearch(search.text)
                        } else {
                            search.selectAll()
                        }
                        event.accepted = true
                    }
                }
                onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
            }

            EmptyState {
                anchors.centerIn: parent
                visible: drivers.count === 0
                glyph: backend.driverCount === 0 ? "" : ""  // car, search
                title: backend.driverCount === 0 ? i18n.tr("No driver in session") : i18n.tr("No driver matches the filters")
                text: backend.driverCount === 0 ? i18n.tr("Drivers show here while you are in a session, game running.") : ""
                actionText: backend.driverCount > 0 && backend.filtered ? i18n.tr("Clear Filters") : ""
                onAction: { backend.clearFilters(); search.clear(); page.focusSearch() }
            }
        }

        // Counts & hotkeys hint
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Text {
                text: backend.filtered
                    ? i18n.trm(backend.shownCount + " of " + backend.driverCount + " drivers shown")
                    : i18n.trm(backend.driverCount + " drivers")
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            Item { Layout.fillWidth: true }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                text: i18n.tr("Hotkeys can switch spectate mode & drivers (Hotkey page)")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                elide: Text.ElideRight
            }
        }
    }

    readonly property bool spectatedSlotSet: backend.spectatedSlot >= 0

    Connections {
        target: backend
        function onFilterChanged() {
            if (search.text !== backend.searchText)
                search.text = backend.searchText
        }
    }
}
