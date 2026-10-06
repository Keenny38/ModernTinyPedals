import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Find Option page: search all options (overlays, modules, preset, application) in any language,
// group chips with counts, "Changed only" lists options set apart from default. Results show the
// current value; on / off options switch in place. Keys: type to search, Down / Up move,
// Enter opens the option, Space switches it, Menu key for more.
TpPage {
    id: page

    function openCurrent() {
        results.forceLayout()  // search just flushed by Enter: rows not laid out yet
        if (results.currentItem)
            backend.openOption(results.currentItem.key)
    }
    function openMenu(item, x, y, entry) {
        rowMenu.key = entry.key
        rowMenu.modified = entry.modified
        rowMenu.popup(item, x, y)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.8
        anchors.bottomMargin: theme.em * 0.6
        spacing: theme.em * 0.6

        TpSearchField {
            id: search
            Layout.fillWidth: true
            focus: true
            placeholderText: i18n.tr("Type option name, in any language (ex. font color speed)")
            onSearchChanged: function(text) { backend.setSearch(text) }
            onExitField: results.forceActiveFocus()
            Keys.onReturnPressed: page.openCurrent()
            Keys.onEnterPressed: page.openCurrent()
            Keys.onUpPressed: results.decrementCurrentIndex()
            Keys.onDownPressed: results.incrementCurrentIndex()
            Component.onCompleted: forceActiveFocus()
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.35
                Repeater {
                    model: backend.groups
                    OverlayChip {
                        required property var modelData
                        text: modelData.label
                        showDot: false
                        count: modelData.count
                        showCount: backend.searching
                        selected: backend.group === modelData.key
                        onClicked: backend.setGroup(selected && modelData.key !== "" ? "" : modelData.key)
                    }
                }
            }
            TpSwitch {
                Layout.alignment: Qt.AlignTop
                checkable: false
                checked: backend.changedOnly
                text: i18n.tr("Changed only")
                tip: i18n.tr("Only options set apart from their default value")
                onClicked: backend.setChangedOnly(!backend.changedOnly)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Changed only")
                Accessible.checked: backend.changedOnly
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: results
                anchors.fill: parent
                clip: true
                model: backend.results
                boundsBehavior: Flickable.StopAtBounds
                highlightFollowsCurrentItem: false
                keyNavigationEnabled: true
                activeFocusOnTab: true
                cacheBuffer: theme.em * 30
                currentIndex: count > 0 ? 0 : -1
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: OptionResultRow {
                    id: resultRow
                    onMenuRequested: function(item, x, y) { page.openMenu(item, x, y, resultRow) }
                }
                onCountChanged: if (count > 0 && (currentIndex < 0 || currentIndex >= count)) currentIndex = 0
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

                add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
                displaced: Transition {
                    NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic }
                    NumberAnimation { property: "opacity"; to: 1; duration: 180 }
                }

                Keys.onReturnPressed: page.openCurrent()
                Keys.onEnterPressed: page.openCurrent()
                Keys.onSpacePressed: if (currentItem && currentItem.kind === "bool") backend.toggle(currentItem.key)
                Keys.onMenuPressed: if (currentItem) page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem)
                Keys.onPressed: function(event) {
                    // Type to search
                    var code = event.text.length === 1 ? event.text.charCodeAt(0) : 0
                    if (code > 32 && code !== 127 && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
                        search.forceActiveFocus()
                        search.insert(search.length, event.text)
                        backend.setSearch(search.text)
                        event.accepted = true
                    }
                }
            }

            EmptyState {
                anchors.centerIn: parent
                visible: results.count === 0
                glyph: backend.searching ? "" : ""  // search, settings
                title: !backend.searching ? i18n.tr("Find any option")
                     : backend.changedOnly && backend.searchText === "" ? i18n.tr("Every option has its default value")
                     : i18n.tr("No option found")
                text: !backend.searching
                      ? i18n.trm("Search " + backend.optionCount + " options of overlays, modules, preset & application, "
                                 + "in English or in the app language. Example: font color speed, opacity, units.")
                      : backend.foundCount === 0 && backend.searchText !== "" ? i18n.tr("Check spelling, or try fewer or other words.")
                      : ""
                actionText: backend.searching && backend.group !== "" ? i18n.tr("Show All Groups") : ""
                onAction: backend.setGroup("")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Text {
                text: backend.searching ? i18n.trm("Found: " + backend.foundCount) : i18n.trm("Options: " + backend.optionCount)
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            Text {
                visible: backend.foundCount > backend.shownCount
                text: i18n.trm(backend.shownCount + " shown")
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            Item { Layout.fillWidth: true }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                text: i18n.tr("Enter opens the option, Space switches it on / off")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                elide: Text.ElideRight
            }
        }
    }

    TpMenu {
        id: rowMenu
        property string key: ""
        property bool modified: false
        Action { text: i18n.tr("Open in Settings"); onTriggered: backend.openOption(rowMenu.key) }
        Action { text: i18n.tr("Reset to Default"); enabled: rowMenu.modified; onTriggered: backend.resetOption(rowMenu.key) }
        MenuSeparator {}
        Action { text: i18n.tr("Copy Option Key"); onTriggered: backend.copyKey(rowMenu.key) }
        onClosed: results.forceActiveFocus()
    }

    Connections {
        target: backend
        function onFilterChanged() {
            if (search.text !== backend.searchText)
                search.text = backend.searchText
        }
    }
}
