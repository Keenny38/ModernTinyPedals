import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Table editor page (brakes, tyre compounds, car classes & brands, track info, heatmaps): rows of a style preset.
// Search filters rows (Ctrl+F), header click sorts, click selects (Ctrl toggles, Shift extends), arrows move the
// cursor, Enter or F2 edits the cell (Esc puts it back), typing a character edits it starting with that character,
// Delete removes selected rows (toast with Undo), Esc clears the selection, menu key or right click opens the cell
// menu. Ctrl+Z / Ctrl+Y undo & redo. Changes not saved: unsaved changes bar at the bottom (TpPendingBar, as on Settings),
// Apply (Ctrl+S) checks, saves & applies at once, Discard puts the saved rows back (Undo). Columns are as wide as their
// header and longest value (never cut, French too; very long names up to a limit, full text in a tooltip), the
// name column takes what is left; the table scrolls sideways when the page is narrower. Confirmations, warnings &
// toasts of the backend are shown by TpDialogHost (ui/quick/dialogs.py).
// Heatmaps: preset picker (New, Copy, Delete) & live preview of the colors, Offset of selected temperatures.
TpPage {
    id: page
    readonly property var columns: backend.columns
    readonly property bool heatmap: backend.features.indexOf("heatmap") >= 0
    property var headerWidths: []  // natural width of each header (probes), so French headers are never cut
    property var valueWidths: []  // width of the longest value of each column (probes)
    property int editKey: 0
    property int editColumn: -1
    property string editSeed: ""  // character typed on the table that started the edit (cell text replaced)
    readonly property real longestValue: theme.em * 30  // longer values are cut (full text in a tooltip)
    readonly property real gap: theme.space2
    // Name column takes the width left; tables without one (heatmap steps) stay compact on the left
    readonly property int stretchColumn: columns.length > 0 && columns[0].kind === "name" ? 0 : -1
    readonly property real naturalTotal: {
        var total = theme.space2 * 2
        for (var i = 0; i < columns.length; ++i)
            total += natural(i) + (i > 0 ? gap : 0)
        return total
    }
    readonly property real tableWidth: Math.max(flick.width, naturalTotal)

    function natural(index) {
        var header = index < headerWidths.length ? headerWidths[index] : 0
        var value = index < valueWidths.length ? Math.min(valueWidths[index], longestValue) : 0
        if (value > 0)
            value += theme.space2 * 2 + (columns[index].kind === "color" ? Math.round(theme.em * 1.1) + theme.space2 : 0)
        return Math.ceil(Math.max(columns[index].width * theme.em, header, value))
    }
    function columnWidth(index) {
        return natural(index) + (index === stretchColumn ? tableWidth - naturalTotal : 0)
    }
    function columnX(index) {
        var x = theme.space2
        for (var i = 0; i < index; ++i)
            x += columnWidth(i) + gap
        return x
    }
    function measureHeaders() {
        var widths = []
        for (var i = 0; i < probes.count; ++i)
            widths.push(probes.itemAt(i) ? probes.itemAt(i).implicitWidth : 0)
        headerWidths = widths
        var values = []
        for (var j = 0; j < valueProbes.count; ++j)
            values.push(valueProbes.itemAt(j) ? valueProbes.itemAt(j).implicitWidth : 0)
        valueWidths = values
    }
    // Edit of a cell, seed: character typed on the table (text cells start with it, lists just open)
    function startEdit(key, column, seed) {
        if (key <= 0 || column < 0 || column >= columns.length)
            return
        editSeed = seed === undefined ? "" : seed
        backend.select(key, column, 0)
        table.positionViewAtIndex(backend.currentIndex, ListView.Contain)
        showColumn(column)
        editKey = key
        editColumn = column
    }
    function stopEdit() {
        editKey = 0
        editColumn = -1
        editSeed = ""
    }
    function editFinished(moveNext) {
        Qt.callLater(stopEdit)  // editor deleted after its own handler
        table.forceActiveFocus()
        if (moveNext)
            backend.moveCurrent(0, 1, false)
    }
    function showColumn(column) {
        var x = columnX(column)
        var width = columnWidth(column)
        if (x < flick.contentX)
            flick.contentX = Math.max(0, x - theme.space2)
        else if (x + width > flick.contentX + flick.width)
            flick.contentX = Math.min(flick.contentWidth - flick.width, x + width - flick.width + theme.space2)
    }
    function openCellMenu(item, x, y) {
        cellMenu.popup(item, x, y)
    }
    function openReplace() {
        replaceDialog.column = backend.replaceColumns.length > 0 ? backend.replaceColumns[0].index : -1
        findField.text = ""
        replaceField.text = ""
        replaceDialog.open()
    }

    Shortcut {
        sequences: [StandardKey.Find]
        enabled: pageState.active
        onActivated: search.forceActiveFocus()
    }

    // Natural header widths (sorted mark included: width never jumps when sorting)
    Item {
        visible: false
        Repeater {
            id: probes
            model: page.columns
            TpHeaderCell {
                required property var modelData
                text: modelData.header
                sortable: true
                sorted: true
                onImplicitWidthChanged: Qt.callLater(page.measureHeaders)
            }
        }
        Repeater {
            id: valueProbes
            model: page.columns
            TpText {
                required property var modelData
                required property int index
                role: modelData.right ? "numeric" : "body"
                text: index < backend.longest.length ? backend.longest[index] : ""
                onImplicitWidthChanged: Qt.callLater(page.measureHeaders)
            }
        }
    }
    onColumnsChanged: Qt.callLater(measureHeaders)
    Component.onCompleted: {
        measureHeaders()
        table.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: theme.padPage
            spacing: theme.space3

            // Heatmap preset (picker, new, copy, delete) & preview
            Loader {
                Layout.fillWidth: true
                active: page.heatmap
                visible: active
                sourceComponent: heatmapBar
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                TpSearchField {
                    id: search
                    objectName: "editorSearch"
                    Layout.preferredWidth: theme.em * 14
                    Layout.minimumWidth: theme.em * 8
                    placeholderText: i18n.tr("Filter rows")
                    text: backend.filterText
                    onSearchChanged: function(text) { backend.setFilter(text) }
                    onExitField: table.forceActiveFocus()
                }
                TpToolbar {
                    id: actionsBar
                    Layout.fillWidth: true
                    alignRight: false
                    onMenuClosed: table.forceActiveFocus()
                    TpAction {
                        name: "addAction"
                        text: i18n.tr("Add")
                        glyph: theme.glyphs.add
                        fallback: "+"
                        priority: 9
                        pinned: true
                        tip: i18n.tr("Add the missing rows of the running session, else a new row")
                        onTriggered: backend.addRow()
                    }
                    TpAction {
                        name: "deleteAction"
                        text: i18n.tr("Delete")
                        glyph: theme.glyphs.delete
                        fallback: "✕"
                        priority: 8
                        enabled: backend.selectedCount > 0
                        tip: i18n.tr("Delete selected rows (Delete key)")
                        onTriggered: backend.deleteSelected()
                    }
                    TpAction {
                        name: "importAction"
                        text: i18n.tr("Import")
                        glyph: theme.glyphs["import"]
                        fallback: "↓"
                        priority: 7
                        shown: backend.importSources.length > 0
                        enabled: !backend.busy
                        tip: i18n.tr("Import car makers: from the game while it runs (its REST API), or from a JSON file")
                        onTriggered: function(source) { importMenu.toggleBelow(source) }
                    }
                    TpAction {
                        name: "replaceAction"
                        text: i18n.tr("Replace…")
                        priority: 2
                        shown: backend.replaceColumns.length > 0
                        enabled: backend.rowCount > 0
                        tip: i18n.tr("Replace a text in every row of a column")
                        onTriggered: page.openReplace()
                    }
                    TpAction {
                        name: "offsetAction"
                        text: i18n.tr("Offset…")
                        glyph: ""  // sliders
                        fallback: "±"
                        priority: 3
                        shown: page.heatmap
                        enabled: backend.selectedCount > 0
                        tip: i18n.tr("Add a value to the temperatures of selected rows, or scale them")
                        onTriggered: offsetDialog.open()
                    }
                    TpAction {
                        name: "resetAction"
                        text: i18n.tr("Reset")
                        glyph: theme.glyphs.reset
                        fallback: "↺"
                        priority: 1
                        enabled: backend.canReset
                        tip: i18n.tr("Back to default rows")
                        onTriggered: backend.askReset()
                    }
                    TpAction {
                        name: "undoAction"
                        text: i18n.tr("Undo")
                        glyph: theme.glyphs.undo
                        fallback: "↶"
                        priority: 6
                        enabled: backend.canUndo
                        tip: i18n.tr("Undo (Ctrl+Z)")
                        onTriggered: backend.undo()
                    }
                    TpAction {
                        name: "redoAction"
                        text: i18n.tr("Redo")
                        glyph: ""  // redo
                        fallback: "↷"
                        priority: 5
                        enabled: backend.canRedo
                        tip: i18n.tr("Redo (Ctrl+Y)")
                        onTriggered: backend.redo()
                    }
                }
            }

            // Table: header, then rows; sideways scroll when narrower than its columns
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: theme.radiusLg
                color: theme.surfaceCard
                border.width: 1
                border.color: theme.cardBorder
                clip: true

                Flickable {
                    id: flick
                    anchors.fill: parent
                    anchors.margins: 1
                    contentWidth: page.tableWidth
                    contentHeight: height
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    interactive: contentWidth > width
                    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                    Column {
                        width: page.tableWidth
                        height: flick.height

                        Row {
                            id: headerRow
                            x: theme.space2
                            spacing: page.gap
                            Repeater {
                                model: page.columns.length
                                TpHeaderCell {
                                    required property int index
                                    width: page.columnWidth(index)
                                    text: page.columns[index].header
                                    align: page.columns[index].right ? Qt.AlignRight : Qt.AlignLeft
                                    sortable: true
                                    sorted: backend.sortColumn === index
                                    descending: backend.sortDescending
                                    tip: i18n.tr("Sort rows by this column")
                                    onSortRequested: backend.sortBy(index)
                                }
                            }
                        }
                        Rectangle {
                            width: parent.width
                            height: 1
                            color: theme.cardBorder
                        }

                        ListView {
                            id: table
                            objectName: "editorTable"
                            width: parent.width
                            height: parent.height - headerRow.height - 1
                            clip: true
                            model: backend.rowsModel
                            boundsBehavior: Flickable.StopAtBounds
                            highlightFollowsCurrentItem: false
                            keyNavigationEnabled: false  // keys handled below (cursor & selection in backend)
                            activeFocusOnTab: true
                            currentIndex: backend.currentIndex
                            cacheBuffer: theme.em * 20
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            Accessible.role: Accessible.Table
                            Accessible.name: i18n.tr("Rows")
                            onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)

                            readonly property int pageRows: Math.max(1, Math.floor(height / Math.round(theme.row)) - 1)

                            // Keys of the table taken before page & app shortcuts
                            Keys.onShortcutOverride: function(event) {
                                if ([Qt.Key_Delete, Qt.Key_F2, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Up, Qt.Key_Down,
                                     Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp,
                                     Qt.Key_PageDown].indexOf(event.key) >= 0)
                                    event.accepted = true
                                else if (backend.currentKey > 0 && event.text.length === 1 && event.text > " "
                                         && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)))
                                    event.accepted = true  // typed character edits the cell (single key shortcuts not run)
                            }
                            Keys.onPressed: function(event) {
                                var extend = (event.modifiers & Qt.ShiftModifier) !== 0
                                event.accepted = true
                                switch (event.key) {
                                case Qt.Key_Up: backend.moveCurrent(-1, 0, extend); break
                                case Qt.Key_Down: backend.moveCurrent(1, 0, extend); break
                                case Qt.Key_PageUp: backend.moveCurrent(-pageRows, 0, extend); break
                                case Qt.Key_PageDown: backend.moveCurrent(pageRows, 0, extend); break
                                case Qt.Key_Home: backend.moveCurrent(-backend.rowCount, 0, extend); break
                                case Qt.Key_End: backend.moveCurrent(backend.rowCount, 0, extend); break
                                case Qt.Key_Left: backend.moveCurrent(0, -1, false); page.showColumn(backend.currentColumn); break
                                case Qt.Key_Right: backend.moveCurrent(0, 1, false); page.showColumn(backend.currentColumn); break
                                case Qt.Key_Return:
                                case Qt.Key_Enter:
                                case Qt.Key_F2: page.startEdit(backend.currentKey, backend.currentColumn); break
                                case Qt.Key_Delete: backend.deleteSelected(); break
                                case Qt.Key_Menu:
                                    if (currentItem)
                                        page.openCellMenu(currentItem, page.columnX(backend.currentColumn), currentItem.height)
                                    break
                                case Qt.Key_A:
                                    if (event.modifiers & Qt.ControlModifier)
                                        backend.selectAll()
                                    else
                                        event.accepted = false
                                    break
                                case Qt.Key_Escape:
                                    // Selection cleared first, else the key closes the page
                                    event.accepted = backend.clearSelection()
                                    break
                                default:
                                    // Character typed on a cell: edit it, starting with that character (spreadsheet)
                                    event.accepted = backend.currentKey > 0 && event.text.length === 1
                                                     && event.text >= " " && event.text !== "\u007f"
                                                     && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
                                    if (event.accepted)
                                        page.startEdit(backend.currentKey, backend.currentColumn, event.text)
                                }
                            }

                            delegate: Item {
                                id: rowItem
                                required property int index
                                required property int key
                                required property var cells
                                required property var colors
                                required property var marks
                                required property bool selected
                                required property int current
                                width: table.width
                                height: Math.round(theme.row)

                                TpListRow {
                                    id: rowBack
                                    anchors.fill: parent
                                    hovered: rowHover.hovered
                                    selected: rowItem.selected
                                    striped: rowItem.index % 2 === 1
                                }
                                HoverHandler { id: rowHover }

                                Row {
                                    x: theme.space2
                                    height: parent.height
                                    spacing: page.gap
                                    Repeater {
                                        model: page.columns.length
                                        EditorCell {
                                            id: editorCell
                                            required property int index
                                            width: page.columnWidth(index)
                                            height: rowItem.height
                                            rowKey: rowItem.key
                                            column: index
                                            kind: page.columns[index].kind
                                            header: page.columns[index].header
                                            alignEnd: page.columns[index].right
                                            value: rowItem.cells[index]
                                            swatch: rowItem.colors[index]
                                            mark: rowItem.marks[index]
                                            cursor: rowItem.current === index && table.activeFocus
                                            editing: page.editKey === rowItem.key && page.editColumn === index
                                            seed: editing ? page.editSeed : ""
                                            onPressedWith: function(mode) {
                                                if (mode >= 0 || !rowItem.selected)
                                                    backend.select(rowItem.key, index, Math.max(0, mode))
                                                else
                                                    backend.setCurrent(rowItem.key, index)  // right click: selection kept
                                                table.forceActiveFocus()
                                            }
                                            onEditRequested: page.startEdit(rowItem.key, index)
                                            onMenuRequested: function(x, y) { page.openCellMenu(editorCell, x, y) }
                                            onEditFinished: function(moveNext) { page.editFinished(moveNext) }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                TpStateView {
                    anchors.centerIn: parent
                    empty: backend.shownCount === 0
                    glyph: backend.rowCount === 0 ? "" : ""  // list, search
                    title: backend.rowCount === 0 ? i18n.tr("No rows") : i18n.tr("No row matches the search")
                    text: backend.rowCount === 0 ? i18n.tr("Add rows of the running session, or a new row.") : ""
                    actionText: backend.rowCount === 0 ? i18n.tr("Add") : i18n.tr("Clear Search")
                    onAction: backend.rowCount === 0 ? backend.addRow() : search.clearSearch()
                }
            }

            // Counts & keys
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space4
                TpText {
                    role: "caption"
                    tabular: true
                    text: i18n.tr("Rows:") + " " + backend.shownCount
                          + (backend.shownCount !== backend.rowCount ? " / " + backend.rowCount : "")
                          + (backend.selectedCount > 0 ? "   " + i18n.tr("Selected:") + " " + backend.selectedCount : "")
                }
                TpText {
                    Layout.fillWidth: true
                    role: "caption"
                    horizontalAlignment: Text.AlignRight
                    text: i18n.tr("Enter or F2: edit · Delete: delete rows · Esc: cancel")
                }
            }
        }

        // Unsaved changes: Discard (saved rows back, Undo kept a few seconds) or Apply (Ctrl+S)
        TpPendingBar {
            objectName: "pendingBar"
            pending: backend.modified
            historyButtons: false  // Undo & Redo in the toolbar above
            canUndo: backend.canUndo
            canRedo: backend.canRedo
            onUndoRequested: backend.undo()
            onDiscardRequested: {
                page.stopEdit()  // cell being edited dropped too
                table.forceActiveFocus()
                backend.discard()
            }
            onApplyRequested: backend.save()
        }
    }

    Connections {
        target: backend
        function onRowAdded(key, typed) {
            table.positionViewAtEnd()
            if (typed)
                Qt.callLater(page.startEdit, key, 0)
            else
                table.forceActiveFocus()
        }
    }

    // Cell menu (right click, menu key)
    TpMenu {
        id: cellMenu
        objectName: "cellMenu"
        readonly property int column: backend.currentColumn
        readonly property var spec: column >= 0 && column < page.columns.length ? page.columns[column] : null
        onClosed: table.forceActiveFocus()
        TpMenuItem {
            text: i18n.tr("Edit")
            onTriggered: page.startEdit(backend.currentKey, cellMenu.column)
        }
        TpMenuItem {
            visible: cellMenu.spec !== null && cellMenu.spec.kind === "color"
            height: visible ? implicitHeight : 0
            text: i18n.tr("Select Color")
            onTriggered: backend.pickColor(backend.currentKey, cellMenu.column)
        }
        TpMenuItem {
            visible: cellMenu.spec !== null && cellMenu.spec.action !== ""
            height: visible ? implicitHeight : 0
            text: cellMenu.spec !== null ? cellMenu.spec.actionText : ""
            onTriggered: backend.cellAction(backend.currentKey, cellMenu.column)
        }
        MenuSeparator {}
        TpMenuItem {
            text: i18n.tr("Delete Rows")
            enabled: backend.selectedCount > 0
            onTriggered: backend.deleteSelected()
        }
    }

    // Import (car brands): game REST API or JSON file
    TpMenu {
        id: importMenu
        objectName: "importMenu"
        Instantiator {
            model: backend.importSources
            delegate: TpMenuItem {
                required property var modelData
                required property int index
                text: modelData.label
                ToolTip.visible: hovered
                ToolTip.text: hovered ? modelData.tip : ""
                ToolTip.delay: theme.tipDelay
                onTriggered: backend.importFrom(index)
            }
            onObjectAdded: function(index, object) { importMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { importMenu.removeItem(object) }
        }
    }

    // Replace: text of a column, in every row
    TpDialog {
        id: replaceDialog
        objectName: "replaceDialog"
        property int column: -1
        property bool whole: false
        property bool matchCase: false
        title: i18n.tr("Replace")
        acceptText: i18n.tr("Replace")
        acceptEnabled: findField.text !== "" && column >= 0
        dismissOnOutside: false
        onAccepted: backend.replace(column, findField.text, replaceField.text, whole, matchCase)
        onClosed: table.forceActiveFocus()

        TpCombo {
            Layout.fillWidth: true
            visible: backend.replaceColumns.length > 1
            model: backend.replaceColumns
            textRole: "header"
            tip: i18n.tr("Column")
            onActivated: function(index) { replaceDialog.column = backend.replaceColumns[index].index }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space2
            TpTextField {
                id: findField
                Layout.fillWidth: true
                placeholderText: i18n.tr("Find")
                tip: i18n.tr("Find")
                Keys.onReturnPressed: replaceDialog.accept()
                Keys.onEnterPressed: replaceDialog.accept()
            }
            TpButton {
                id: valuesButton
                glyph: ""  // chevron down
                fallback: "▼"
                tip: i18n.tr("Values of the column")
                onClicked: valuesMenu.toggleBelow(valuesButton)
            }
        }
        TpTextField {
            id: replaceField
            Layout.fillWidth: true
            placeholderText: i18n.tr("Replace with")
            tip: i18n.tr("Replace with")
            Keys.onReturnPressed: replaceDialog.accept()
            Keys.onEnterPressed: replaceDialog.accept()
        }
        TpSwitch {
            checkable: false
            checked: replaceDialog.whole
            text: i18n.tr("Match Whole Word")
            onClicked: replaceDialog.whole = !replaceDialog.whole
        }
        TpSwitch {
            checkable: false
            checked: replaceDialog.matchCase
            text: i18n.tr("Match Case")
            onClicked: replaceDialog.matchCase = !replaceDialog.matchCase
        }
    }
    TpMenu {
        id: valuesMenu
        onClosed: findField.forceActiveFocus()
        Instantiator {
            model: valuesMenu.opened ? backend.replaceValues(replaceDialog.column) : []
            delegate: TpMenuItem {
                required property var modelData
                text: modelData
                onTriggered: findField.text = modelData
            }
            onObjectAdded: function(index, object) { valuesMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { valuesMenu.removeItem(object) }
        }
    }

    // Heatmap: offset or scale of selected temperatures
    TpDialog {
        id: offsetDialog
        objectName: "offsetDialog"
        property bool scaling: false
        property real amount: 0
        title: i18n.tr("Offset")
        acceptText: i18n.tr("Apply")
        acceptEnabled: scaling ? amount > 0 : amount !== 0
        dismissOnOutside: false
        onAboutToShow: { amount = 0; amountField.value = 0; amountField.text = amountField.format(0) }
        onAccepted: backend.offsetSelected(amount, scaling)
        onClosed: table.forceActiveFocus()

        NumberField {
            id: amountField
            Layout.fillWidth: true
            decimals: offsetDialog.scaling ? 3 : 1
            step: offsetDialog.scaling ? 0.1 : 1
            minimum: offsetDialog.scaling ? 0 : -99999
            maximum: offsetDialog.scaling ? 100 : 99999
            suffix: offsetDialog.scaling || page.columns.length === 0 ? "" : " " + page.columns[0].symbol
            tip: offsetDialog.scaling ? i18n.tr("Scale") : i18n.tr("Offset")
            onEdited: function(number) {
                value = number
                offsetDialog.amount = number
            }
            // Typed value counted at once: Apply is clicked without leaving the field
            onTextEdited: {
                var number = parseFloat(text.replace(",", ".").replace(/\s/g, ""))
                offsetDialog.amount = isNaN(number) ? 0 : clamp(number)
            }
            Keys.onReturnPressed: { commit(); offsetDialog.accept() }
            Keys.onEnterPressed: { commit(); offsetDialog.accept() }
        }
        TpSwitch {
            checkable: false
            checked: offsetDialog.scaling
            text: i18n.tr("Scale Mode")
            tip: i18n.tr("Multiply temperatures instead of adding the value")
            onClicked: { offsetDialog.scaling = !offsetDialog.scaling; offsetDialog.amount = 0; amountField.value = 0; amountField.text = amountField.format(0) }
        }
    }

    // Heatmap: name of a new or copied preset
    TpDialog {
        id: nameDialog
        objectName: "nameDialog"
        property bool copy: false
        readonly property string error: page.heatmap && visible && nameField.text !== "" ? backend.checkPresetName(nameField.text) : ""
        title: copy ? i18n.tr("Duplicate Heatmap Preset") : i18n.tr("Create Heatmap Preset")
        acceptText: copy ? i18n.tr("Copy") : i18n.tr("Create")
        acceptEnabled: nameField.text !== "" && error === ""
        dismissOnOutside: false
        onAboutToShow: nameField.text = ""
        onOpened: nameField.forceActiveFocus()
        onAccepted: backend.createPreset(nameField.text, copy)
        onClosed: table.forceActiveFocus()

        TpTextField {
            id: nameField
            Layout.fillWidth: true
            placeholderText: i18n.tr("Enter a new preset name")
            maximumLength: 40
            validator: RegularExpressionValidator { regularExpression: /[0-9a-zA-Z_]*/ }
            invalid: nameDialog.error !== ""
            Keys.onReturnPressed: nameDialog.accept()
            Keys.onEnterPressed: nameDialog.accept()
        }
        TpText {
            Layout.fillWidth: true
            visible: nameDialog.error !== ""
            role: "caption"
            text: nameDialog.error
            color: theme.loss
            wrapMode: Text.WordWrap
        }
    }

    Component {
        id: heatmapBar
        ColumnLayout {
            spacing: theme.space2
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space2
                TpCombo {
                    id: presetCombo
                    objectName: "heatmapPresets"
                    Layout.fillWidth: true
                    Layout.minimumWidth: theme.em * 6
                    Layout.maximumWidth: theme.em * 24
                    model: backend.presetNames
                    currentIndex: backend.presetIndex
                    tip: i18n.tr("Heatmap preset")
                    onActivated: function(index) {
                        backend.selectPreset(index)  // refused while the table has errors
                        currentIndex = Qt.binding(function() { return backend.presetIndex })
                    }
                }
                TpButton {
                    Layout.minimumWidth: implicitWidth  // whole, the picker gets narrower
                    text: i18n.tr("New…")
                    tip: i18n.tr("Create Heatmap Preset")
                    onClicked: { nameDialog.copy = false; nameDialog.open() }
                }
                TpButton {
                    Layout.minimumWidth: implicitWidth  // whole, the picker gets narrower
                    text: i18n.tr("Copy…")
                    tip: i18n.tr("Duplicate Heatmap Preset")
                    onClicked: { nameDialog.copy = true; nameDialog.open() }
                }
                TpButton {
                    Layout.minimumWidth: implicitWidth  // whole, the picker gets narrower
                    text: i18n.tr("Delete Preset")
                    enabled: backend.canDeletePreset
                    tip: backend.canDeletePreset ? "" : i18n.tr("Built-in heatmap presets cannot be deleted")
                    onClicked: backend.askDeletePreset()
                }
                Item { Layout.fillWidth: true }
            }
            HeatmapPreview {
                Layout.fillWidth: true
                bands: backend.bands
            }
        }
    }

    // Confirmations, warnings & toasts of the backend (last child of the page)
    TpDialogHost {}
}
