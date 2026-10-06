import QtQuick
import QtQuick.Controls.Basic
import QtQml.Models
import QtQuick.Layouts

// Modules page: title & counts, what modules are for, search, All / Active / Inactive, notices (modules off that
// enabled overlays need, start errors), modules as cards (see ModuleCard), enable / disable all shown modules.
// Keys: type to search, "/" search, arrows move, Space switches, Enter opens settings, Menu key the menu.
TpPage {
    id: page

    readonly property real cardMinWidth: theme.em * 21
    readonly property var neededNames: backend.neededNames

    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }
    function resetText(label) {
        return i18n.trm("Reset " + label) + "..."
    }
    function openMenu(item, x, y, entry) {
        cardMenu.name = entry.key
        cardMenu.active = entry.active
        cardMenu.resets = entry.resets
        // Menu as wide as its longest entry (data names can be long)
        var texts = [i18n.tr("Config") + "...", entry.active ? i18n.tr("Disable") : i18n.tr("Enable")]
        for (var i = 0; i < entry.resets.length; i++)
            texts.push(page.resetText(entry.resets[i].label))
        var widest = 0
        for (var j = 0; j < texts.length; j++) {
            menuMetrics.text = texts[j]
            widest = Math.max(widest, menuMetrics.advanceWidth)
        }
        cardMenu.width = Math.max(theme.em * 13, widest + theme.em * 3.8)
        cardMenu.popup(item, x, y)
    }

    // Notice above cards: icon, text, action button
    component Notice: Rectangle {
        id: notice
        property color tint: theme.warning
        property string glyph: ""  // warning
        property string text: ""
        property string actionText: ""
        signal action()
        Layout.fillWidth: true
        implicitHeight: noticeRow.implicitHeight + theme.em * 0.9
        radius: theme.em * 0.6
        color: Qt.rgba(tint.r, tint.g, tint.b, 0.12)
        border.width: 1
        border.color: Qt.rgba(tint.r, tint.g, tint.b, 0.6)
        RowLayout {
            id: noticeRow
            anchors.fill: parent
            anchors.leftMargin: theme.em * 0.7
            anchors.rightMargin: theme.em * 0.4
            spacing: theme.em * 0.5
            Icon { glyph: notice.glyph; color: notice.tint }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: theme.text
                text: notice.text
            }
            TpButton {
                visible: notice.actionText !== ""
                flat: true
                text: notice.actionText
                onClicked: notice.action()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.8
        anchors.bottomMargin: theme.em * 0.6
        spacing: theme.em * 0.6

        // Title & counts
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            Text {
                text: i18n.tr("Module")  // navigation bar name ("Modules" in French)
                color: theme.text
                font.pointSize: theme.fontPoint * 1.5
                font.weight: Font.DemiBold
            }
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                implicitHeight: Math.round(theme.em * 1.6)
                implicitWidth: countText.implicitWidth + theme.em * 1.1
                radius: height / 2
                color: backend.activeCount > 0 ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.16) : theme.hover
                Text {
                    id: countText
                    anchors.centerIn: parent
                    text: i18n.trm(backend.activeCount + " / " + backend.totalCount + " enabled")
                    color: backend.activeCount > 0 ? theme.accent : theme.dimText
                    font.pointSize: theme.fontPoint * 0.9
                    font.weight: Font.DemiBold
                    font.features: { "tnum": 1 }
                }
            }
            Item { Layout.fillWidth: true }
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: theme.dimText
            lineHeight: 1.1
            text: i18n.tr("Modules compute the data that overlays show (lap times, fuel, positions...). A module turned off computes nothing: overlays using its data stay empty.")
        }

        // Search & state filter
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            TpSearchField {
                id: search
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 8
                focus: true
                placeholderText: i18n.tr("Search modules") + "   /"
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: modules.forceActiveFocus()
                Keys.onReturnPressed: modules.forceActiveFocus()
                Keys.onEnterPressed: modules.forceActiveFocus()
                Connections {
                    target: backend
                    function onFilterChanged() {
                        if (search.text !== backend.searchText)
                            search.text = backend.searchText
                    }
                }
            }
            TpSegmented {
                options: [i18n.tr("All"), i18n.tr("Active"), i18n.tr("Inactive")]
                currentIndex: backend.stateFilter
                onActivated: function(index) { backend.setStateFilter(index) }
            }
        }

        // Modules off that enabled overlays need, start errors
        Notice {
            visible: page.neededNames.length > 0
            text: i18n.trm("Off but needed by enabled overlays or modules: " + page.neededNames.join(", "))
            actionText: i18n.tr("Enable Them")
            onAction: backend.enableNeeded()
        }
        Notice {
            visible: backend.failedCount > 0
            tint: theme.loss
            text: backend.failedCount === 1 ? i18n.tr("1 module could not start, see log.")
                : i18n.trm(backend.failedCount + " modules could not start, see log.")
            actionText: i18n.tr("Show Log")
            onAction: backend.showLog()
        }

        // Modules
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            GridView {
                id: modules
                anchors.fill: parent
                anchors.leftMargin: -Math.round(theme.em * 0.3)  // card margins aligned with header
                anchors.rightMargin: -Math.round(theme.em * 0.3)
                clip: true
                model: backend.model
                readonly property int columns: Math.max(1, Math.floor(width / page.cardMinWidth))
                cellWidth: Math.floor((width - theme.em * 0.7) / columns)  // room for scroll bar
                cellHeight: Math.round(theme.em * 9.2)
                boundsBehavior: Flickable.StopAtBounds
                highlightFollowsCurrentItem: false
                keyNavigationEnabled: true
                activeFocusOnTab: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: ModuleCard {
                    id: cardItem
                    onMenuRequested: function(item, x, y) { page.openMenu(item, x, y, cardItem) }
                }

                add: Transition {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 170 }
                    NumberAnimation { property: "scale"; from: 0.95; to: 1; duration: 170; easing.type: Easing.OutCubic }
                }
                remove: Transition {
                    NumberAnimation { property: "opacity"; to: 0; duration: 130 }
                    NumberAnimation { property: "scale"; to: 0.95; duration: 130 }
                }
                displaced: Transition {
                    NumberAnimation { properties: "x,y"; duration: 220; easing.type: Easing.OutCubic }
                    NumberAnimation { property: "opacity"; to: 1; duration: 220 }  // add interrupted: never left faded
                    NumberAnimation { property: "scale"; to: 1; duration: 220 }
                }

                Keys.onSpacePressed: if (currentItem) backend.toggle(currentItem.key)
                Keys.onReturnPressed: if (currentItem) backend.openConfig(currentItem.key)
                Keys.onEnterPressed: if (currentItem) backend.openConfig(currentItem.key)
                Keys.onMenuPressed: if (currentItem) page.openMenu(currentItem, currentItem.width / 2, currentItem.height / 2, currentItem)
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
                visible: modules.count === 0
                glyph: ""  // search
                title: i18n.tr("No module matches the search")
                actionText: backend.filtered ? i18n.tr("Clear Filters") : ""
                onAction: { backend.clearFilters(); page.focusSearch() }
            }
        }

        // Shown count & batch actions on shown modules
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Text {
                Layout.fillWidth: true
                elide: Text.ElideRight
                color: theme.dimText
                text: backend.filtered
                    ? i18n.trm(backend.shownCount + " of " + backend.totalCount + " modules shown")
                    : i18n.trm(backend.totalCount + " modules")
            }
            TpButton {
                text: backend.filtered ? i18n.tr("Enable Shown") : i18n.tr("Enable All")
                enabled: backend.shownCount > 0
                onClicked: backend.enableShown()
            }
            TpButton {
                text: backend.filtered ? i18n.tr("Disable Shown") : i18n.tr("Disable All")
                enabled: backend.shownCount > 0
                onClicked: backend.disableShown()
            }
        }
    }

    TextMetrics { id: menuMetrics }
    TpMenu {
        id: cardMenu
        property string name: ""
        property bool active: false
        property var resets: []
        Action { text: i18n.tr("Config") + "..."; onTriggered: backend.openConfig(cardMenu.name) }
        Action {
            text: cardMenu.active ? i18n.tr("Disable") : i18n.tr("Enable")
            onTriggered: backend.toggle(cardMenu.name)
        }
        MenuSeparator { visible: cardMenu.resets.length > 0; height: visible ? implicitHeight : 0 }
        // Saved data of module (delta best, fuel delta...), asked before reset
        Instantiator {
            model: cardMenu.resets
            delegate: Action {
                required property var modelData
                text: page.resetText(modelData.label)
                onTriggered: backend.resetData(cardMenu.name, modelData.key)
            }
            onObjectAdded: function(index, object) { cardMenu.insertAction(3 + index, object) }
            onObjectRemoved: function(index, object) { cardMenu.removeAction(object) }
        }
    }
}
