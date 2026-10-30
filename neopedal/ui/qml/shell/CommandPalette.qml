import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Command palette (Ctrl+K): search pages, tools, every menu command, settings, overlays, modules, presets &
// options; results in groups with icons & shortcuts, recent commands first when nothing is typed. Prefixes:
// ">" commands, "@" options, "#" presets. Up / Down move, Enter runs, Esc clears the search then closes.
TpPage {
    id: page
    color: theme.surfaceFlyout  // popup window: native drop shadow of Windows popups around it
    border.width: 1
    border.color: theme.strokeSubtle

    property string shownQuery: ""

    function runCurrent() {
        var before = shownQuery
        search.flushSearch()  // Enter typed before the search ran: results of the full text, first one
        list.forceLayout()
        if (shownQuery !== before)
            list.resetCurrent()
        if (list.currentIndex >= 0 && list.count > 0)
            backend.run(list.currentIndex)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.space3

        TpSearchField {
            id: search
            Layout.fillWidth: true
            focus: true
            searchDelay: 60
            placeholderText: i18n.tr("Search pages, tools, commands, settings, presets, options…")
            onSearchChanged: function(text) { page.shownQuery = text; backend.setQuery(text) }
            onExitField: backend.close()  // Esc with nothing typed
            Keys.onUpPressed: list.decrementCurrentIndex()
            Keys.onDownPressed: list.incrementCurrentIndex()
            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_PageDown) {
                    list.currentIndex = Math.min(list.count - 1, list.currentIndex + 8)
                    event.accepted = true
                } else if (event.key === Qt.Key_PageUp) {
                    list.currentIndex = Math.max(0, list.currentIndex - 8)
                    event.accepted = true
                }
            }
            Keys.onReturnPressed: page.runCurrent()
            Keys.onEnterPressed: page.runCurrent()
            Component.onCompleted: forceActiveFocus()
        }

        TpText {
            Layout.fillWidth: true
            role: "caption"
            text: backend.hint
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.resultsModel
            boundsBehavior: Flickable.StopAtBounds
            highlightFollowsCurrentItem: false
            keyNavigationEnabled: false  // keys stay in the search field
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            section.property: "group"
            section.criteria: ViewSection.FullString
            section.delegate: Item {
                required property string section
                width: ListView.view.width
                implicitHeight: label.implicitHeight + theme.space3 * 2
                TpSectionLabel {
                    id: label
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: theme.space4
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: theme.space1
                    text: parent.section
                }
            }
            delegate: PaletteRow {
                width: ListView.view.width
                current: ListView.isCurrentItem
                onHoveredRow: list.currentIndex = index
                onActivated: backend.run(index)
            }
            // Not a binding: hover sets currentIndex, which would drop it; new results select the first one
            function resetCurrent() { currentIndex = count > 0 ? 0 : -1 }
            onCountChanged: resetCurrent()
            onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
            Component.onCompleted: resetCurrent()
            Connections {
                target: backend
                function onResultsChanged() { list.resetCurrent() }  // same count, other rows: first one again
            }

            TpStateView {
                anchors.centerIn: parent
                empty: list.count === 0
                compact: true
                glyph: ""  // search
                title: i18n.tr("Nothing found")
                text: i18n.tr("Check spelling, or try fewer or other words.")
            }
        }

        TpText {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignRight
            role: "caption"
            text: i18n.tr("Up / Down to move, Enter to run, Esc to close")
        }
    }
}
