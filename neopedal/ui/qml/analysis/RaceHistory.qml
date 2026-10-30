import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator consumption history: laps (newest first, or sorted by a column clicked or chosen with Tab &
// Enter, numbers by value), invalid laps struck through in red (or hidden), optional columns, selection (click,
// Up / Down; Ctrl, Shift, Ctrl+A), average of selected laps filled in (Enter, double click), laps deleted from
// history (Delete, after confirmation)
TpSectionCard {
    id: panel
    readonly property var history: backend.historyView  // columns, sort... (rows: backend.historyRows)
    readonly property var selection: backend.historySelection
    readonly property var columns: history.columns || []
    readonly property var shown: {
        var list = []
        for (var index = 0; index < columns.length; index++)
            if (columns[index].visible)
                list.push(index)
        return list
    }
    readonly property var samples: ({ lap: "0000", time: "0:00.000" })
    readonly property var widths: {
        var natural = []
        var total = 0
        for (var i = 0; i < shown.length; i++) {
            var column = columns[shown[i]]
            var size = Math.max(boldMetrics.advanceWidth(column.title.toUpperCase()), metrics.advanceWidth(samples[column.key] || "000.000"))
            size += theme.em * 1.1
            natural.push(size)
            total += size
        }
        var factor = total > 0 && tableScroll.width > total ? tableScroll.width / total : 1  // scrolled when wider
        return natural.map(function(size) { return size * factor })
    }
    readonly property real tableWidth: widths.reduce(function(sum, size) { return sum + size }, 0)
    readonly property real rowHeight: Math.round(theme.rowCompact)

    FontMetrics { id: metrics; font.features: { "tnum": 1 } }
    FontMetrics { id: boldMetrics; font.weight: Font.DemiBold; font.pointSize: theme.fontCaption }

    function modeOf(modifiers) {
        return modifiers & Qt.ShiftModifier ? 2 : modifiers & Qt.ControlModifier ? 1 : 0
    }
    property int cursorIndex: -1  // row of the keyboard cursor (focus ring)
    function moveBy(step, extend) {
        var index = backend.moveLapSelection(step, extend)
        cursorIndex = index
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }
    glyph: ""  // history
    title: i18n.tr("Consumption History")
    spacing: theme.space3
    actions: [
        RaceSwitch {
            Layout.fillWidth: false
            wrap: false
            text: i18n.tr("Valid Laps Only")
            on: panel.history.validOnly === true
            onSwitched: function(on) { backend.setValidOnly(on) }
        },
        TpButton {
            id: columnsButton
            flat: true
            size: "sm"
            glyph: ""  // sliders
            fallback: "☰"
            tip: i18n.tr("Columns")
            checked: columnMenu.visible
            onClicked: columnMenu.toggleBelow(columnsButton)
            TpMenu {
                id: columnMenu
                // focus put back where it was, but left on the window: list (keys kept)
                onClosed: if (!Window.activeFocusItem || Window.activeFocusItem === Window.contentItem)
                              list.forceActiveFocus()
                Repeater {
                    model: panel.history.menu || []
                    TpMenuItem {
                        required property var modelData
                        text: modelData.title
                        checkable: true
                        checked: modelData.checked
                        onTriggered: backend.toggleHistoryColumn(modelData.option)
                    }
                }
            }
        }
    ]

    Text {
        Layout.fillWidth: true
        text: i18n.tr("Select laps, then add them: their average goes to the calculator, invalid laps (struck through) left out.")
        color: theme.dimText
        font.pointSize: theme.fontSmall
        wrapMode: Text.Wrap
    }

    // Table: header sorts, rows select
    Flickable {
        id: tableScroll
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: !panel.history.empty
        contentWidth: Math.max(panel.tableWidth, width)
        contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.horizontal: ScrollBar { policy: tableScroll.contentWidth > tableScroll.width ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }

        Row {
            id: headerRow
            height: Math.round(theme.headerHeight)
            Repeater {
                model: panel.shown.length
                TpHeaderCell {
                    id: headerCell
                    required property int index
                    readonly property int column: panel.shown[index]
                    width: panel.widths[index] || 0
                    height: headerRow.height
                    text: panel.columns[column] ? panel.columns[column].title : ""
                    align: Qt.AlignRight
                    sortable: true
                    sorted: panel.history.sortColumn === column
                    descending: panel.history.sortAscending !== true
                    onSortRequested: backend.sortHistory(headerCell.column)
                }
            }
        }
        Rectangle {
            y: headerRow.height
            width: Math.max(panel.tableWidth, tableScroll.width)
            height: 1
            color: theme.border
        }
        ListView {
            id: list
            objectName: "historyList"
            y: headerRow.height + 1
            width: Math.max(panel.tableWidth, tableScroll.width)
            height: tableScroll.height - y
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true
            model: backend.historyRows  // synced in place: new lap inserted, selection changes one role
            activeFocusOnTab: true
            Accessible.role: Accessible.Table
            Accessible.name: i18n.tr("Consumption History")
            ScrollBar.vertical: ScrollBar {  // kept at the right of the panel when scrolled sideways
                parent: tableScroll
                x: tableScroll.width - width
                y: list.y
                height: list.height
            }
            Keys.onUpPressed: function(event) { panel.moveBy(-1, event.modifiers & Qt.ShiftModifier) }
            Keys.onDownPressed: function(event) { panel.moveBy(1, event.modifiers & Qt.ShiftModifier) }
            Keys.onReturnPressed: backend.addSelectedLaps()
            Keys.onEnterPressed: backend.addSelectedLaps()
            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_A && (event.modifiers & Qt.ControlModifier)) {
                    backend.selectAllLaps()
                    event.accepted = true
                } else if (event.key === Qt.Key_Delete) {
                    backend.deleteSelectedLaps()
                    event.accepted = true
                } else if (event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                    panel.moveBy(event.key === Qt.Key_Home ? -list.count : list.count, event.modifiers & Qt.ShiftModifier)
                    event.accepted = true
                }
            }
            delegate: Item {
                id: lapRow
                required property int index
                required property int serial
                required property bool valid
                required property var cells
                required property bool selected
                property bool live: true  // false while recycled (reuseItems): row look shown at once
                ListView.onPooled: live = false
                ListView.onReused: live = true
                width: Math.max(panel.tableWidth, list.width)
                height: panel.rowHeight
                TpListRow {
                    id: surface
                    anchors.fill: parent
                    anchors.margins: 2
                    radius: theme.radiusSm
                    animate: lapRow.live
                    hovered: rowArea.containsMouse
                    selected: lapRow.selected
                    striped: lapRow.index % 2 === 1
                }
                FocusRing {  // keyboard: row moved to with Up / Down
                    target: surface
                    anchors.margins: 0
                    visible: list.activeFocus && panel.cursorIndex === lapRow.index
                }
                Row {
                    Repeater {
                        model: panel.shown.length
                        Text {
                            required property int index
                            readonly property int column: panel.shown[index]
                            readonly property string key: panel.columns[column] ? panel.columns[column].key : ""
                            readonly property bool invalidValue: !lapRow.valid && (key === "time" || key === "fuel" || key === "energy")
                            width: panel.widths[index] || 0
                            height: lapRow.height
                            text: lapRow.cells && lapRow.cells[column] !== undefined ? lapRow.cells[column] : ""
                            textFormat: Text.PlainText
                            // Invalid lap: struck through, in red too (never told by color alone)
                            color: invalidValue ? panel.history.invalidColor : theme.text
                            font.strikeout: invalidValue
                            font.features: { "tnum": 1 }
                            rightPadding: theme.space3
                            horizontalAlignment: Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }
                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function(mouse) {
                        list.forceActiveFocus()
                        panel.cursorIndex = lapRow.index
                        backend.selectLap(lapRow.serial, panel.modeOf(mouse.modifiers))
                    }
                    onDoubleClicked: {
                        backend.selectLap(lapRow.serial, 0)
                        backend.addSelectedLaps()
                    }
                }
            }
        }
    }
    Item {  // no lap: message centered where the table goes
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: panel.history.empty === true
        TpStateView {
            anchors.centerIn: parent
            empty: true
            compact: true
            glyph: ""  // history
            title: i18n.tr("No lap recorded yet")
            text: i18n.tr("Drive a few laps, or load a file.")
        }
    }
    Text {
        Layout.fillWidth: true
        visible: text !== ""
        text: backend.notes.historyAdded
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontLabel
        elide: Text.ElideRight
    }
    Flow {  // actions wrap on narrow panels
        Layout.fillWidth: true
        spacing: theme.space3
        layoutDirection: Qt.LeftToRight
        TpButton {
            enabled: !panel.history.empty && panel.selection.length > 0
            glyph: theme.glyphs.delete
            text: i18n.tr("Delete Selected")
            tip: i18n.tr("Delete selected laps from consumption history") + " (" + i18n.tr("Delete") + ")"
            onClicked: backend.deleteSelectedLaps()
        }
        TpButton {
            enabled: !panel.history.empty
            flat: true
            text: i18n.tr("Delete All")
            tip: i18n.tr("Delete whole consumption history of this track & class")
            onClicked: backend.deleteAllLaps()
        }
        TpButton {
            enabled: !panel.history.empty
            accent: true
            glyph: theme.glyphs.add
            text: i18n.tr("Add Selected Data")
            tip: i18n.tr("Average of selected laps (double click: one lap) to the calculator")
            onClicked: backend.addSelectedLaps()
        }
    }
}
