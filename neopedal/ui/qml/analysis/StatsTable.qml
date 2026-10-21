import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Driver stats table: header (click, or Tab then Enter / Space: sort; drag edge: resize; right click: columns),
// rows of backend.rows (key, cells of shown columns). Click: select, right click: row menu, double click or
// Enter: open row, Delete: remove row, Backspace: back to All Tracks, Menu key: row menu.
// Rows of the same track are moved in place when sorted or reloaded (animated, scroll kept); a cell is a
// single text, its logo, level pill or letter badge made only in columns having any (backend column "extras").
// Names at left, numbers at right (tabular digits). Vehicles grouped by class: line above the first row of each class.
FocusScope {
    id: table

    readonly property var columns: backend.columns
    readonly property string selectedKey: backend.selectedKey
    readonly property string sortKey: backend.sortKey
    readonly property bool sortDescending: backend.sortDescending
    property var dragWidths: ({})  // column key: width while its edge is dragged
    readonly property real rowHeight: Math.round(theme.rowCompact)
    readonly property real cellPad: theme.em * 0.7
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
            color: theme.tint(parent.tint, "selected")
            border.width: 1
            border.color: theme.tint(parent.tint, 0.4)
        }
    }
    Component {
        id: logoImage
        GameLogo {
            source: parent ? parent.logoUrl : ""
            boxWidth: theme.em * 2.2
            boxHeight: theme.em * 1.25
        }
    }
    // Decorations of a cell (columns with extras only): game logo before text, level pill behind it or letter
    // badge after it. Parent: loader inside cell text.
    Component {
        id: cellExtras
        Item {
            id: extrasItem
            readonly property Item cellText: parent ? parent.parent : null
            readonly property var cell: cellText ? cellText.cell : ({})
            readonly property bool logoShown: logo.item !== null && logo.item.shown === true
            Loader {  // car brand or circuit logo of game: vehicle & track cells only
                id: logo
                readonly property string logoUrl: extrasItem.cell.logo || ""
                active: logoUrl !== ""
                x: extrasItem.cellText ? -extrasItem.cellText.logoRoom + (theme.em * 2.2 - width) / 2 : 0
                y: extrasItem.cellText ? (extrasItem.cellText.height - height) / 2 : 0
                sourceComponent: logoImage
            }
            Loader {
                id: decoration
                readonly property bool pill: extrasItem.cell.pill === true
                property color tint: extrasItem.cell.color || theme.border
                readonly property string letter: extrasItem.cell.badge || ""
                readonly property real textWidth: extrasItem.cellText ? extrasItem.cellText.width : 0
                active: pill || letter !== ""
                z: -1
                x: pill ? -theme.em * 0.55 : textWidth + theme.em * 0.35
                width: pill ? textWidth + theme.em * 1.1 : theme.em * 1.25
                height: pill ? Math.round(theme.em * 1.5) : theme.em * 1.25
                y: extrasItem.cellText ? (extrasItem.cellText.height - height) / 2 : 0
                sourceComponent: pill ? pillShape : badgeShape
            }
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
                color: theme.inkOn(parent.color)  // readable on level color
                font.pointSize: theme.fontTiny
                font.weight: Font.Bold
            }
        }
    }

    ListView {
        id: list
        objectName: "statsList"
        anchors.fill: parent
        clip: true
        focus: true
        reuseItems: true
        model: backend.rows
        contentWidth: Math.max(table.totalWidth, width)
        flickableDirection: Flickable.HorizontalAndVerticalFlick
        boundsBehavior: Flickable.StopAtBounds
        headerPositioning: ListView.OverlayHeader
        Accessible.role: Accessible.Table
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
        move: Transition { NumberAnimation { property: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
        moveDisplaced: Transition { NumberAnimation { property: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
        displaced: Transition { NumberAnimation { property: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
        add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }
        populate: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionBase } }
        // Other track with mostly the same vehicles: rows changed in place (delegates kept), shown from the top
        // with a short fade instead of being made again
        NumberAnimation {
            id: switchFade
            target: list.contentItem
            property: "opacity"
            from: 0.35
            to: 1
            duration: theme.motionBase
        }
        Connections {
            target: backend
            function onRowsSwitched() {
                list.positionViewAtBeginning()
                switchFade.restart()
            }
        }

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
                    readonly property bool alignedLeft: modelData.align === "left"
                    x: table.edges[index] || 0
                    width: table.widthOf(index)
                    height: table.rowHeight
                    TpHeaderCell {  // sort: click, or Tab then Enter / Space
                        anchors.fill: parent
                        anchors.leftMargin: theme.space3
                        anchors.rightMargin: theme.em * 0.6  // room for the resize edge
                        text: headerCell.modelData.label
                        tip: headerCell.modelData.tip || ""
                        align: headerCell.alignedLeft ? Qt.AlignLeft : Qt.AlignRight
                        sortable: true
                        sorted: table.sortKey === headerCell.modelData.key
                        descending: table.sortDescending
                        onSortRequested: backend.sortBy(headerCell.modelData.key)
                    }
                    MouseArea {  // right click: columns menu (left clicks go to the header cell)
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor  // header cells sort on click
                        onClicked: function(mouse) {
                            var point = mapToItem(table, mouse.x, mouse.y)
                            table.headerMenu(point.x, point.y)
                        }
                    }
                    Rectangle {  // column edge
                        anchors.right: parent.right
                        width: 1
                        height: parent.height * 0.45
                        anchors.verticalCenter: parent.verticalCenter
                        color: edgeArea.containsMouse || edgeArea.pressed ? theme.accent : theme.border
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
            required property string group  // class of a new class group (grouped by class), "" otherwise
            readonly property bool selected: key === table.selectedKey
            property int hoveredColumn: -1
            readonly property string tip: hoveredColumn >= 0 && cells[hoveredColumn] ? (cells[hoveredColumn].tip || "") : ""
            width: list.contentWidth
            height: table.rowHeight
            property bool live: true  // false while recycled: row look shown at once (no fade)
            ListView.onPooled: { hoveredColumn = -1; live = false }  // kept for another row (reuseItems)
            ListView.onReused: live = true
            ToolTip.visible: rowArea.containsMouse && tip !== ""
            ToolTip.text: tip
            ToolTip.delay: theme.tipDelay

            TpListRow {  // selected, hovered, alternate rows
                id: surface
                anchors.fill: parent
                anchors.topMargin: 1
                anchors.bottomMargin: 1
                radius: theme.radiusSm
                animate: rowItem.live
                hovered: rowArea.containsMouse
                selected: rowItem.selected
                striped: rowItem.index % 2 === 1
            }
            Rectangle {  // selected marker (keyboard: focus shown on the selected row)
                x: 2
                width: Math.max(3, Math.round(theme.em * 0.2))
                height: parent.height * 0.55
                radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                color: theme.accent
                opacity: rowItem.selected ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: theme.motionBase } }
            }
            Rectangle {  // first row of another class (vehicles grouped by class): line above it
                visible: rowItem.group !== ""
                width: parent.width
                height: Math.max(2, Math.round(theme.em * 0.12))
                color: theme.tint(theme.accent, 0.45)
            }
            FocusRing {
                target: surface
                anchors.margins: 0
                visible: rowItem.selected && list.activeFocus
            }
            Repeater {
                model: table.columns.length
                Text {
                    id: cellText
                    required property int index
                    readonly property var cell: rowItem.cells[index] || ({})
                    readonly property var column: table.columns[index]
                    readonly property bool alignedLeft: column !== undefined && column.align === "left"
                    readonly property real columnWidth: table.widthOf(index)
                    readonly property real columnX: table.edges[index] || 0
                    readonly property bool pill: cell.pill === true
                    readonly property real extra: !pill && (cell.badge || "") !== "" ? theme.em * 1.6 : 0  // badge
                    readonly property real logoRoom: extras.item !== null && extras.item.logoShown ? theme.em * 2.6 : 0  // game logo
                    readonly property real endPad: table.cellPad + (pill ? theme.em * 0.3 : 0)
                    x: alignedLeft ? columnX + table.cellPad + logoRoom
                       : columnX + Math.max(columnWidth - width - extra - endPad, theme.em * 0.3)
                    width: Math.max(0, Math.min(implicitWidth, columnWidth - theme.em * (pill ? 1.8 : 1.2) - extra - logoRoom))
                    height: rowItem.height
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: alignedLeft ? Text.AlignLeft : Text.AlignRight
                    text: cell.text || ""
                    color: cell.color ? cell.color : cell.dim ? theme.dimText : theme.text
                    font.weight: cell.bold ? Font.DemiBold : Font.Normal
                    font.features: { "tnum": 1 }
                    elide: Text.ElideRight
                    Loader {  // logo, pill or letter badge: made only in columns having any (most cells: text only)
                        id: extras
                        active: cellText.column !== undefined && cellText.column.extras === true
                        z: -1
                        sourceComponent: cellExtras
                    }
                }
            }
            MouseArea {
                id: rowArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
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
