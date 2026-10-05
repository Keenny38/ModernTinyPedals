import QtQuick
import QtQuick.Controls.Basic

// Driver stats table: header (click: sort, drag edge: resize, right click: columns), rows of backend.rows
// (key, cells of shown columns). Click: select, right click: row menu, double click or Enter: open row.
// Scroll kept when rows are refreshed (stats saved by stats module).
FocusScope {
    id: table

    property var columns: backend.columns
    property var dragWidths: ({})  // column key: width while its edge is dragged
    readonly property real rowHeight: Math.round(theme.em * 2.1)
    readonly property real totalWidth: {
        var sum = 0
        for (var i = 0; i < columns.length; i++) sum += widthOf(i)
        return sum
    }
    property real savedX: 0
    property real savedY: 0
    signal cellMenu(string key, string column, real x, real y)
    signal headerMenu(real x, real y)

    function widthOf(index) {
        var column = columns[index]
        if (!column) return 0
        return dragWidths[column.key] !== undefined ? dragWidths[column.key] : column.width
    }
    function columnIndexAt(x) {
        var edge = 0
        for (var i = 0; i < columns.length; i++) {
            edge += widthOf(i)
            if (x < edge) return i
        }
        return columns.length - 1
    }
    function restoreScroll() {
        list.contentX = Math.max(list.originX, Math.min(savedX, list.originX + Math.max(0, list.contentWidth - list.width)))
        list.contentY = Math.max(list.originY, Math.min(savedY, list.originY + Math.max(0, list.contentHeight - list.height)))
    }
    function showSelected() {
        if (backend.selectedIndex >= 0) list.positionViewAtIndex(backend.selectedIndex, ListView.Contain)
    }

    Connections {
        target: backend.rows
        function onModelAboutToBeReset() { table.savedX = list.contentX; table.savedY = list.contentY }
        function onModelReset() { Qt.callLater(table.restoreScroll) }
    }

    ListView {
        id: list
        anchors.fill: parent
        clip: true
        focus: true
        model: backend.rows
        contentWidth: Math.max(table.totalWidth, width)
        flickableDirection: Flickable.HorizontalAndVerticalFlick
        boundsBehavior: Flickable.StopAtBounds
        headerPositioning: ListView.OverlayHeader
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
        Keys.onUpPressed: { backend.moveSelection(-1); table.showSelected() }
        Keys.onDownPressed: { backend.moveSelection(1); table.showSelected() }
        Keys.onReturnPressed: backend.openRow(backend.selectedKey)
        Keys.onEnterPressed: backend.openRow(backend.selectedKey)

        header: Rectangle {
            z: 3
            width: list.contentWidth
            height: table.rowHeight
            color: theme.dark ? Qt.darker(theme.base, 1.25) : Qt.darker(theme.window, 1.04)
            Row {
                Repeater {
                    model: table.columns
                    Item {
                        id: headerCell
                        required property var modelData
                        required property int index
                        readonly property bool sorted: backend.sortKey === modelData.key
                        width: table.widthOf(index)
                        height: table.rowHeight
                        ToolTip.visible: headerArea.containsMouse && modelData.tip !== ""
                        ToolTip.text: modelData.tip
                        ToolTip.delay: 600
                        Text {
                            anchors.fill: parent
                            anchors.leftMargin: theme.em * 0.6
                            anchors.rightMargin: theme.em * 1.1
                            text: headerCell.modelData.label
                            color: headerCell.sorted ? theme.accent : theme.text
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                            horizontalAlignment: headerCell.modelData.align === "left" ? Text.AlignLeft : Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        Icon {
                            visible: headerCell.sorted
                            glyph: backend.sortDescending ? "" : ""  // chevron down, up
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
                            height: parent.height * 0.5
                            anchors.verticalCenter: parent.verticalCenter
                            color: theme.border
                            opacity: edgeArea.containsMouse || edgeArea.pressed ? 1 : 0.5
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
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: theme.border }
        }

        delegate: Rectangle {
            id: rowItem
            required property int index
            required property string key
            required property var cells
            readonly property bool selected: key === backend.selectedKey
            property int hoveredColumn: -1
            readonly property string tip: hoveredColumn >= 0 && cells[hoveredColumn] ? (cells[hoveredColumn].tip || "") : ""
            width: list.contentWidth
            height: table.rowHeight
            color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.22)
                 : rowArea.containsMouse ? theme.hover
                 : index % 2 ? (theme.dark ? Qt.lighter(theme.base, 1.12) : Qt.darker(theme.base, 1.03)) : "transparent"
            Behavior on color { ColorAnimation { duration: 100 } }
            ToolTip.visible: rowArea.containsMouse && tip !== ""
            ToolTip.text: tip
            ToolTip.delay: 500

            Row {
                height: parent.height
                Repeater {
                    model: table.columns.length
                    Item {
                        id: cellItem
                        required property int index
                        readonly property var cell: rowItem.cells[index] || ({})
                        width: table.widthOf(index)
                        height: rowItem.height
                        clip: true
                        Row {
                            id: content
                            readonly property real room: cellItem.width - theme.em * 1.2
                            anchors.verticalCenter: parent.verticalCenter
                            x: table.columns[cellItem.index] && table.columns[cellItem.index].align === "left"
                               ? theme.em * 0.6 : Math.max((cellItem.width - width) / 2, theme.em * 0.3)
                            spacing: theme.em * 0.35
                            Text {
                                width: Math.min(implicitWidth, content.room - (badge.visible ? badge.width + content.spacing : 0))
                                text: cellItem.cell.text || ""
                                color: cellItem.cell.color ? cellItem.cell.color : theme.text
                                font.weight: cellItem.cell.bold ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Rectangle {  // level letter: level told without color
                                id: badge
                                visible: (cellItem.cell.badge || "") !== ""
                                width: theme.em * 1.25
                                height: width
                                radius: width / 2
                                color: cellItem.cell.color ? cellItem.cell.color : theme.border
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    anchors.centerIn: parent
                                    text: cellItem.cell.badge || ""
                                    color: "white"
                                    font.pointSize: theme.fontPoint * 0.72
                                    font.weight: Font.Bold
                                }
                            }
                        }
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
