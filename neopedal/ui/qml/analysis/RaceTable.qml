import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Race calculator result table: columns sized to their texts then stretched to the width (elided
// when narrow), alternate rows, one row in bold, a colored column (tyre changes), header tooltips.
// Texts measured only when rows or columns change (not on resize, each text measured once: widths cached),
// column widths & shown columns replaced only when they differ; rows & cells kept when values change.
Item {
    id: table
    property var columns: []  // titles, or {title, tip, key}
    property var rows: []  // rows of texts
    property var hidden: []  // column indexes left out
    property var hiddenKeys: []  // keys of columns left out (columns given as {key})
    property int boldRow: -1
    property int colorColumn: -1
    property color cellColor: theme.text
    property real rowHeight: Math.round(theme.rowCompact)
    property var shown: []  // column indexes shown (same array while the same columns are shown)
    property var naturalWidths: []  // same array while the widths are the same: cells keep their width
    readonly property real naturalTotal: naturalWidths.reduce(function(sum, size) { return sum + size }, 0)
    readonly property var widths: {
        var factor = naturalTotal > 0 ? width / naturalTotal : 1
        return naturalWidths.map(function(size) { return size * factor })
    }
    property var textWidths: ({})  // text: advance width (cleared when the font changes)
    property int textCount: 0

    function title(column) {
        return typeof column === "string" ? column : column.title
    }
    function sameList(first, second) {
        if (first.length !== second.length)
            return false
        for (var index = 0; index < first.length; index++)
            if (first[index] !== second[index])
                return false
        return true
    }
    function textWidth(text, bold) {
        var key = (bold ? "b|" : "n|") + text
        var size = textWidths[key]
        if (size === undefined) {
            if (textCount > 4000) {  // many different texts over time: measured again
                textWidths = {}
                textCount = 0
            }
            size = (bold ? boldMetrics : metrics).advanceWidth(text)
            textWidths[key] = size
            textCount++
        }
        return size
    }
    function updateShown() {
        var list = []
        for (var index = 0; index < columns.length; index++) {
            var column = columns[index]
            if (hidden.indexOf(index) < 0 && !(typeof column === "object" && hiddenKeys.indexOf(column.key) >= 0))
                list.push(index)
        }
        if (!sameList(list, shown))
            shown = list
    }
    function measure() {
        var natural = []
        for (var i = 0; i < shown.length; i++) {
            var column = shown[i]
            var size = textWidth(title(columns[column]), true)
            for (var row = 0; row < rows.length; row++)
                size = Math.max(size, textWidth(String(rows[row][column]), false))
            natural.push(size + theme.em * 1.2)
        }
        if (!sameList(natural, naturalWidths))
            naturalWidths = natural
    }
    function refresh() {
        updateShown()
        measure()
    }
    function fontChanged() {
        textWidths = {}
        textCount = 0
        measure()
    }

    onColumnsChanged: refresh()
    onRowsChanged: measure()
    onHiddenChanged: refresh()
    onHiddenKeysChanged: refresh()
    Component.onCompleted: refresh()

    implicitHeight: rowHeight * (rows.length + 1)
    implicitWidth: theme.em * 20

    // Measured as drawn: tabular digits (else a changed digit changes the width, columns resized at each input)
    FontMetrics { id: metrics; font.features: { "tnum": 1 }; onFontChanged: table.fontChanged() }
    FontMetrics {
        id: boldMetrics
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
        onFontChanged: table.fontChanged()
    }

    // First column (stint, plan, driver) at left, numbers at right (tabular digits: decimals line up)
    function alignOf(index) { return index === 0 ? Qt.AlignLeft : Qt.AlignRight }

    Column {
        width: table.width
        Row {  // header
            height: table.rowHeight
            Repeater {
                model: table.shown.length
                TpHeaderCell {
                    required property int index
                    readonly property var column: table.columns[table.shown[index]]
                    width: table.widths[index] || 0
                    height: table.rowHeight
                    text: column !== undefined ? table.title(column) : ""
                    tip: typeof column === "object" && column.tip ? column.tip : ""
                    align: table.alignOf(index)
                }
            }
        }
        Rectangle { width: table.width; height: 1; color: theme.border }
        Repeater {
            model: table.rows.length  // rows kept when their texts change (new values every input step)
            TpListRow {
                id: rowItem
                required property int index
                readonly property var cells: table.rows[index] || []
                width: table.width
                height: table.rowHeight
                radius: theme.radiusSm
                striped: index % 2 === 1
                Row {
                    Repeater {
                        model: table.shown.length
                        Text {
                            required property int index
                            readonly property int column: table.shown[index]
                            width: table.widths[index] || 0
                            height: table.rowHeight
                            text: rowItem.cells[column] !== undefined ? rowItem.cells[column] : ""
                            textFormat: Text.PlainText
                            color: column === table.colorColumn && text !== "" ? table.cellColor : theme.text
                            font.weight: rowItem.index === table.boldRow ? Font.DemiBold : Font.Normal
                            font.features: { "tnum": 1 }
                            leftPadding: theme.space1
                            rightPadding: theme.space1
                            horizontalAlignment: index === 0 ? Text.AlignLeft : Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
