import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Tools page: every tool & editor as a tile (icon, name, what it is for, live On / Off state of tools with a
// switch, mark of tools in the navigation bar), grouped by section. Search by name, description or former name
// (type anywhere to search, Enter in the search opens the first tile). Tab moves between tiles, Enter or Space
// opens the focused one.
TpPage {
    id: page
    readonly property real tileWidth: theme.em * 17  // content-tuned: name & two lines of description
    readonly property int columns: Math.max(1, Math.floor((width - theme.padPage * 2 + theme.space4) / (tileWidth + theme.space4)))

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        TpPageHeader {
            title: i18n.tr("Tools")
            count: "" + backend.shownCount
            TpSearchField {
                id: search
                Layout.preferredWidth: Math.min(theme.em * 16, page.width * 0.4)
                placeholderText: i18n.tr("Find a tool")
                onSearchChanged: function(text) { backend.setSearch(text) }
                onExitField: if (tiles.firstTile) tiles.firstTile.forceActiveFocus()
                Keys.onReturnPressed: if (tiles.firstTile) tiles.firstTile.opened()
                Keys.onEnterPressed: if (tiles.firstTile) tiles.firstTile.opened()
            }
        }

        Flickable {
            id: flick
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            contentHeight: tiles.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Column {
                id: tiles
                property Item firstTile: null
                width: flick.width
                spacing: theme.space5

                Repeater {
                    model: backend.sections
                    Column {
                        id: section
                        required property var modelData
                        required property int index
                        width: tiles.width
                        spacing: theme.space3
                        TpSectionLabel { width: parent.width; text: section.modelData.title }
                        GridLayout {
                            width: parent.width
                            columns: page.columns
                            columnSpacing: theme.space4
                            rowSpacing: theme.space4
                            Repeater {
                                model: section.modelData.tools
                                ToolTile {
                                    required property var modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: page.tileWidth
                                    tool: modelData
                                    status: backend.statuses[modelData.name] || ""
                                    onOpened: backend.openTool(tool.path)
                                    onActiveFocusChanged: if (activeFocus) flick.ensureVisible(this)
                                    Component.onCompleted: if (section.index === 0 && index === 0) tiles.firstTile = this
                                    Component.onDestruction: if (tiles.firstTile === this) tiles.firstTile = null
                                }
                            }
                        }
                    }
                }
            }

            function ensureVisible(item) {
                var top = item.mapToItem(tiles, 0, 0).y
                if (top < contentY)
                    contentY = top
                else if (top + item.height > contentY + height)
                    contentY = top + item.height - height
            }
            // Type anywhere on the page to search
            Keys.onPressed: function(event) {
                if (search.routeTyped(event))
                    event.accepted = true
            }
        }
    }

    TpStateView {
        anchors.centerIn: parent
        empty: backend.shownCount === 0
        glyph: ""  // search
        title: i18n.tr("No tool found")
        text: i18n.tr("Check spelling, or try fewer or other words.")
        actionText: i18n.tr("Clear Search")
        onAction: search.clearSearch()
    }

    TpDialogHost {}
}
