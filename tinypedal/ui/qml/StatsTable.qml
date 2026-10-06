import QtQuick
import QtQuick.Controls.Basic

// Driver stats table: header (click: sort, drag edge: resize, right click: columns), rows of backend.rows
// (key, cells of shown columns). Click: select, right click: row menu, double click or Enter: open row,
// Delete: remove row, Backspace: back to All Tracks, Menu key: row menu.
// Rows of the same track are moved in place when sorted or reloaded (animated, scroll kept); a cell is a
// single text, level pill or letter badge loaded only where shown.
FocusScope {
    id: table

    readonly property var columns: backend.columns
    readonly property string selectedKey: backend.selectedKey
    readonly property string sortKey: backend.sortKey
    readonly property bool sortDescending: backend.sortDescending
    property var dragWidths: ({})  // column key: width while its edge is dragged
    readonly property real rowHeight: Math.round(theme.em * 2.2)
    readonly property var edges: {  // x of each column, total width last
        var result = [0]
        for (var i = 0; i < columns.length; i++) result.push(result[i] + widthOf(i))
        return result
    }
    readonly property real totalWidth: edges[edges.length - 1]
    readonly property int count: list.count
    readonly property real neededHeight: rowHeight * (list.count + 1) + 2  // header & every row
    signal cellMenu(string key, string column, real x, real y)
    signal headerMenu(real x, real y)

    function widthOf(index) {
        var column = columns[index]
        if (!column) return 0
        return dragWidths[column.key] !== undefined ? dragWidths[column.key] : column.width
    }
    function columnIndexAt(x) {
        for (var i = 0; i < columns.length; i++) {
            if (x < edges[i + 1]) return i
        }
        return columns.length - 1
    }
    function showSelected() {
        if (backend.selectedIndex >= 0) list.positionViewAtIndex(backend.selectedIndex, ListView.Contain)
    }
    function moveBy(step) {
        backend.moveSelection(step)
        showSelected()
    }
    function openSelectedMenu() {
        var index = backend.selectedIndex
        if (index < 0) return
        var item = list.itemAtIndex(index)
        if (!item) return
        var point = item.mapToItem(table, theme.em * 2, item.height * 0.8)
        table.cellMenu(table.selectedKey, columns.length ? columns[0].key : "", point.x, point.y)
    }

    // Level pill behind a cell text, level letter badge after it (tint & letter from loader)
    Component {
        id: pillShape
        Rectangle {
            radius: height / 2
            color: Qt.rgba(parent.tint.r, parent.tint.g, parent.tint.b, theme.dark ? 0.18 : 0.13)
            border.width: 1
            border.color: Qt.rgba(parent.tint.r, parent.tint.g, parent.tint.b, 0.35)
        }
    }
    Component {
        id: badgeShape
        Rectangle {
            radius: width / 2
            color: parent.tint
            Text {
                anchors.centerIn: parent
                text: parent.parent.letter
                color: "white"
                font.pointSize: theme.fontPoint * 0.72
                font.weight: Font.Bold
            }
        }
    }

    ListView {
        id: list
        anchors.fill: parent
        clip: true
        focus: true
        reuseItems: true
        model: backend.rows
        contentWidth: Math.max(table.totalWidth, width)
        flickableDirection: Flickable.HorizontalAndVerticalFlick
        boundsBehavior: Flickable.StopAtBounds
        headerPositioning: ListView.OverlayHeader
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
        Keys.onUpPressed: table.moveBy(-1)
        Keys.onDownPressed: table.moveBy(1)
        Keys.onPressed: function(event) {
            var page = Math.max(1, Math.floor(list.height / table.rowHeight) - 2)
            if (event.key === Qt.Key_PageUp) table.moveBy(-page)
            else if (event.key === Qt.Key_PageDown) table.moveBy(page)
            else if (event.key === Qt.Key_Home) table.moveBy(-list.count)
            else if (event.key === Qt.Key_End) table.moveBy(list.count)
            else if (event.key === Qt.Key_Delete) backend.deleteSelected()
            else if (event.key === Qt.Key_Backspace && !backend.allTracks) backend.showAllTracks()
            else if (event.key === Qt.Key_Menu) table.openSelectedMenu()
            else return
            event.accepted = true
        }
        Keys.onReturnPressed: backend.openRow(table.selectedKey)
        Keys.onEnterPressed: backend.openRow(table.selectedKey)

        // Rows sorted again: slide to their new place; other track: rows fade in
        move: Transition { NumberAnimation { property: "y"; duration: 240; easing.type: Easing.OutCubic } }
        moveDisplaced: Transition { NumberAnimation { property: "y"; duration: 240; easing.type: Easing.OutCubic } }
        displaced: Transition { NumberAnimation { property: "y"; duration: 200; easing.type: Easing.OutCubic } }
        add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 180 } }
        populate: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 } }

        header: Rectangle {
            z: 3
            width: list.contentWidth
            height: table.rowHeight
            color: theme.base
            Repeater {
                model: table.columns
                Item {
                    id: headerCell
                    required property var modelData
                    required property int index
                    readonly property bool sorted: table.sortKey === modelData.key
                    readonly property bool alignedLeft: modelData.align === "left"
                    x: table.edges[index] || 0
                    width: table.widthOf(index)
                    height: table.rowHeight
                    ToolTip.visible: headerArea.containsMouse && modelData.tip !== ""
                    ToolTip.text: modelData.tip
                    ToolTip.delay: 600
                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: theme.em * 0.7
                        anchors.rightMargin: theme.em * 1.1
                        text: headerCell.modelData.label
                        color: headerCell.sorted ? theme.accent : headerArea.containsMouse ? theme.text : theme.dimText
                        font.pointSize: theme.fontPoint * 0.92
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        horizontalAlignment: headerCell.alignedLeft ? Text.AlignLeft : Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    Icon {
                        visible: headerCell.sorted
                        glyph: table.sortDescending ? "" : ""  // chevron down, up
                        size: theme.em * 0.6
                        color: theme.accent
                        anchors.right: parent.right
                        anchors.rightMargin: theme.em * 0.45
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    MouseArea {
                        id: headerArea
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function(mouse) {
                            if (mouse.button === Qt.RightButton) {
                                var point = mapToItem(table, mouse.x, mouse.y)
                                table.headerMenu(point.x, point.y)
                            } else {
                                backend.sortBy(headerCell.modelData.key)
                            }
                        }
                    }
                    Rectangle {  // column edge
                        anchors.right: parent.right
                        width: 1
                        height: parent.height * 0.45
                        anchors.verticalCenter: parent.verticalCenter
                        color: theme.border
                        opacity: edgeArea.containsMouse || edgeArea.pressed ? 1 : 0.4
                    }
                    MouseArea {  // drag to resize, saved when released
                        id: edgeArea
                        width: theme.em * 0.6
                        height: parent.height
                        anchors.right: parent.right
                        hoverEnabled: true
                        preventStealing: true
                        cursorShape: Qt.SplitHCursor
                        property real startX: 0
                        property real startWidth: 0
                        onPressed: function(mouse) {
                            startX = mapToItem(table, mouse.x, 0).x
                            startWidth = headerCell.width
                        }
                        onPositionChanged: function(mouse) {
                            if (!pressed) return
                            var widths = Object.assign({}, table.dragWidths)
                            widths[headerCell.modelData.key] = Math.max(theme.em * 2, startWidth + mapToItem(table, mouse.x, 0).x - startX)
                            table.dragWidths = widths
                        }
                        onReleased: {
                            var width = table.dragWidths[headerCell.modelData.key]
                            if (width !== undefined) backend.setColumnWidth(headerCell.modelData.key, width)
                            table.dragWidths = ({})
                        }
                    }
                }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: theme.border }
        }

        delegate: Item {
            id: rowItem
            required property int index
            required property string key
            required property var cells
            readonly property bool selected: key === table.selectedKey
            property int hoveredColumn: -1
            readonly property string tip: hoveredColumn >= 0 && cells[hoveredColumn] ? (cells[hoveredColumn].tip || "") : ""
            width: list.contentWidth
            height: table.rowHeight
            ListView.onPooled: hoveredColumn = -1  // kept for another row (reuseItems)
            ToolTip.visible: rowArea.containsMouse && tip !== ""
            ToolTip.text: tip
            ToolTip.delay: 500

            Rectangle {  // selected, hovered, alternate rows
                anchors.fill: parent
                anchors.topMargin: 1
                anchors.bottomMargin: 1
                radius: theme.em * 0.35
                color: rowItem.selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.18 : 0.12)
                     : rowArea.containsMouse ? theme.hover
                     : rowItem.index % 2 ? (theme.dark ? Qt.lighter(theme.base, 1.1) : Qt.darker(theme.base, 1.025)) : "transparent"
                Behavior on color { ColorAnimation { duration: 110 } }
            }
            Rectangle {  // selected marker
                x: 2
                width: 3
                height: parent.height * 0.55
                radius: 1.5
                anchors.verticalCenter: parent.verticalCenter
                color: theme.accent
                opacity: rowItem.selected ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 150 } }
            }
            Repeater {
                model: table.columns.length
                Text {
                    id: cellText
                    required property int index
                    readonly property var cell: rowItem.cells[index] || ({})
                    readonly property bool alignedLeft: table.columns[index] !== undefined && table.columns[index].align === "left"
                    readonly property real columnWidth: table.widthOf(index)
                    readonly property real columnX: table.edges[index] || 0
                    readonly property real extra: decoration.active && !decoration.pill ? theme.em * 1.6 : 0  // badge
                    readonly property real logoRoom: logo.shown ? theme.em * 2.6 : 0  // game logo before text
                    x: alignedLeft ? columnX + theme.em * 0.7 + logoRoom
                       : columnX + Math.max((columnWidth - width - extra + logoRoom) / 2, theme.em * 0.3)
                    width: Math.max(0, Math.min(implicitWidth, columnWidth - theme.em * (decoration.pill ? 1.8 : 1.2) - extra - logoRoom))
                    height: rowItem.height
                    verticalAlignment: Text.AlignVCenter
                    text: cell.text || ""
                    color: cell.color ? cell.color : cell.dim ? theme.dimText : theme.text
                    font.weight: cell.bold ? Font.DemiBold : Font.Normal
                    font.features: { "tnum": 1 }
                    elide: Text.ElideRight
                    GameLogo {  // car brand or circuit logo of game
                        id: logo
                        source: cellText.cell.logo || ""
                        boxWidth: theme.em * 2.2
                        boxHeight: theme.em * 1.25
                        x: -cellText.logoRoom + (theme.em * 2.2 - width) / 2
                        y: (cellText.height - height) / 2
                    }
                    Loader {
                        id: decoration
                        readonly property bool pill: cellText.cell.pill === true
                        property color tint: cellText.cell.color || theme.border
                        readonly property string letter: cellText.cell.badge || ""
                        active: pill || letter !== ""
                        z: -1
                        x: pill ? -theme.em * 0.55 : cellText.width + theme.em * 0.35
                        width: pill ? cellText.width + theme.em * 1.1 : theme.em * 1.25
                        height: pill ? Math.round(theme.em * 1.5) : theme.em * 1.25
                        y: (cellText.height - height) / 2
                        sourceComponent: pill ? pillShape : badgeShape
                    }
                }
            }
            MouseArea {
                id: rowArea
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onPositionChanged: function(mouse) { rowItem.hoveredColumn = table.columnIndexAt(mouse.x) }
                onExited: rowItem.hoveredColumn = -1
                onPressed: {
                    list.forceActiveFocus()
                    backend.selectRow(rowItem.key)
                }
                onClicked: function(mouse) {
                    if (mouse.button !== Qt.RightButton) return
                    var column = table.columns[table.columnIndexAt(mouse.x)]
                    var point = mapToItem(table, mouse.x, mouse.y)
                    table.cellMenu(rowItem.key, column ? column.key : "", point.x, point.y)
                }
                onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.openRow(rowItem.key) }
            }
        }
    }
}
