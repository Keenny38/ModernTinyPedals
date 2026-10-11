import QtQuick
import QtQuick.Controls.Basic

// Race calculator result table: columns sized to their texts then stretched to the width (elided
// when narrow), alternate rows, one row in bold, a colored column (tyre changes), header tooltips.
// Texts measured only when rows or columns change (not on resize); rows & cells kept when values change.
Item {
    id: table
    property var columns: []  // titles, or {title, tip}
    property var rows: []  // rows of texts
    property var hidden: []  // column indexes left out
    property int boldRow: -1
    property int colorColumn: -1
    property color cellColor: theme.text
    property real rowHeight: Math.round(theme.em * 1.85)
    readonly property var shown: {
        var list = []
        for (var index = 0; index < columns.length; index++)
            if (hidden.indexOf(index) < 0)
                list.push(index)
        return list
    }
    readonly property var naturalWidths: measure(shown, columns, rows)
    readonly property real naturalTotal: naturalWidths.reduce(function(sum, size) { return sum + size }, 0)
    readonly property var widths: {
        var factor = naturalTotal > 0 ? width / naturalTotal : 1
        return naturalWidths.map(function(size) { return size * factor })
    }

    function title(column) {
        return typeof column === "string" ? column : column.title
    }
    function measure(shown, columns, rows) {
        var natural = []
        for (var i = 0; i < shown.length; i++) {
            var column = shown[i]
            var size = boldMetrics.advanceWidth(title(columns[column]))
            for (var row = 0; row < rows.length; row++)
                size = Math.max(size, metrics.advanceWidth(String(rows[row][column])))
            natural.push(size + theme.em * 1.2)
        }
        return natural
    }

    implicitHeight: rowHeight * (rows.length + 1)
    implicitWidth: theme.em * 20

    FontMetrics { id: metrics }
    FontMetrics { id: boldMetrics; font.weight: Font.DemiBold }

    Column {
        width: table.width
        Row {  // header
            height: table.rowHeight
            Repeater {
                model: table.shown.length
                Text {
                    required property int index
                    readonly property var column: table.columns[table.shown[index]]
                    width: table.widths[index] || 0
                    height: table.rowHeight
                    text: column !== undefined ? table.title(column) : ""
                    color: theme.dimText
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontPoint * 0.9
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    HoverHandler { id: headerHover; enabled: typeof parent.column === "object" && parent.column.tip !== "" }
                    ToolTip.visible: headerHover.hovered
                    ToolTip.text: typeof column === "object" ? column.tip : ""
                    ToolTip.delay: 500
                }
            }
        }
        Rectangle { width: table.width; height: 1; color: theme.border; opacity: 0.6 }
        Repeater {
            model: table.rows.length  // rows kept when their texts change (new values every input step)
            Rectangle {
                id: rowItem
                required property int index
                readonly property var cells: table.rows[index] || []
                width: table.width
                height: table.rowHeight
                radius: theme.em * 0.3
                color: index % 2 ? (theme.dark ? Qt.rgba(1, 1, 1, 0.035) : Qt.rgba(0, 0, 0, 0.03)) : "transparent"
                Row {
                    Repeater {
                        model: table.shown.length
                        Text {
                            required property int index
                            readonly property int column: table.shown[index]
                            width: table.widths[index] || 0
                            height: table.rowHeight
                            text: rowItem.cells[column] !== undefined ? rowItem.cells[column] : ""
                            color: column === table.colorColumn && text !== "" ? table.cellColor : theme.text
                            font.weight: rowItem.index === table.boldRow ? Font.DemiBold : Font.Normal
                            font.features: { "tnum": 1 }
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
