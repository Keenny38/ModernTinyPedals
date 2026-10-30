import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Find Option page: search all options (overlays, modules, preset, application) in any language,
// group chips with counts, "Changed Only" lists options set apart from default. Results show the
// current value; on / off options switch in place. Keys: type to search, Down / Up move,
// Enter opens the option, Space switches it, Menu key for more, Ctrl+F back to the search. Ctrl+Z / Ctrl+Y undo & redo switches
// and resets (saved & applied again); the search field keeps its own undo while focused.
TpPage {
    id: page

    Shortcut { sequence: "Ctrl+Z"; enabled: pageState.active && backend.canUndo; onActivated: backend.undo() }
    Shortcut { sequences: ["Ctrl+Y", "Ctrl+Shift+Z"]; enabled: pageState.active && backend.canRedo; onActivated: backend.redo() }
    Shortcut {  // search of this page, as on every page with a search
        sequences: [StandardKey.Find]
        enabled: pageState.active
        onActivated: { search.forceActiveFocus(); search.selectAll() }
    }

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
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Title (page title look of every page, page name as its window title & menu entry): how many options shown
        TpPageHeader {
            title: i18n.tr("Find Option")
            count: "" + (backend.searching ? backend.foundCount : backend.optionCount)
        }

        TpSearchField {
            id: search
            Layout.fillWidth: true
            focus: true
            placeholderText: i18n.tr("Type option name, in any language (ex. font color speed)") + "   Ctrl+F"
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
            spacing: theme.space4
            Flow {
                Layout.fillWidth: true
                spacing: theme.space3
                Repeater {
                    model: backend.groups
                    TpChip {
                        required property var modelData
                        text: modelData.label
                        count: backend.searching ? modelData.count : -1
                        selected: backend.group === modelData.key
                        onClicked: backend.setGroup(selected && modelData.key !== "" ? "" : modelData.key)
                    }
                }
            }
            TpSwitch {
                Layout.alignment: Qt.AlignTop
                checkable: false
                checked: backend.changedOnly
                text: i18n.tr("Changed Only")
                tip: i18n.tr("Only options set apart from their default value")
                onClicked: backend.setChangedOnly(!backend.changedOnly)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Changed Only")
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
                reuseItems: true  // results synced at each search: rows of other options reuse delegates
                currentIndex: count > 0 ? 0 : -1
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: OptionResultRow {
                    id: resultRow
                    onMenuRequested: function(item, x, y) { page.openMenu(item, x, y, resultRow) }
                }
                onCountChanged: if (count > 0 && (currentIndex < 0 || currentIndex >= count)) currentIndex = 0
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

                add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast } }
                displaced: count > 30 ? null : moved  // long lists: rows placed at once, not animated
                Transition {
                    id: moved
                    NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic }
                    NumberAnimation { property: "opacity"; to: 1; duration: theme.motionBase }
                }

                Keys.onReturnPressed: page.openCurrent()
                Keys.onEnterPressed: page.openCurrent()
                Keys.onSpacePressed: if (currentItem && currentItem.kind === "bool") backend.toggle(currentItem.key)
                Keys.onMenuPressed: if (currentItem) page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem)
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier) && currentItem) {
                        page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem)
                        event.accepted = true
                    } else if (search.routeTyped(event)) {  // type to search
                        event.accepted = true
                    }
                }
            }

            TpStateView {
                anchors.centerIn: parent
                empty: results.count === 0
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
                visible: backend.foundCount > backend.shownCount
                text: i18n.trm(backend.shownCount + " shown")
                textFormat: Text.PlainText
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            Item { Layout.fillWidth: true }
            TpText {
                Layout.fillWidth: true
                role: "caption"
                horizontalAlignment: Text.AlignRight
                text: i18n.tr("Enter opens the option, Space switches it on / off")
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

    // Dialogs & toasts asked by the backend (ui/quick/dialogs.py, ui/toast.show_toast)
    TpDialogHost {}
}
