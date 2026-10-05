import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator consumption history: laps (newest first, or sorted by a column clicked, numbers by
// value), invalid laps in red (or hidden), optional columns, selection (Ctrl, Shift, Ctrl+A), average of
// selected laps filled in, laps deleted from history
Card {
    id: panel
    readonly property var history: backend.history
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
            var size = Math.max(boldMetrics.advanceWidth(column.title), metrics.advanceWidth(samples[column.key] || "000.000"))
            size += theme.em * 1.1
            natural.push(size)
            total += size
        }
        var factor = total > 0 && tableScroll.width > total ? tableScroll.width / total : 1  // scrolled when wider
        return natural.map(function(size) { return size * factor })
    }
    readonly property real tableWidth: widths.reduce(function(sum, size) { return sum + size }, 0)
    readonly property real pad: theme.em * 0.75

    FontMetrics { id: metrics }
    FontMetrics { id: boldMetrics; font.weight: Font.DemiBold; font.pointSize: theme.fontPoint * 0.9 }

    function modeOf(modifiers) {
        return modifiers & Qt.ShiftModifier ? 2 : modifiers & Qt.ControlModifier ? 1 : 0
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: panel.pad
        spacing: theme.em * 0.45

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.45
            Icon { glyph: ""; color: theme.accent; size: theme.em * 0.95 }  // history
            Text {
                text: i18n.tr("Consumption History")
                color: theme.text
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            RaceSwitch {
                Layout.fillWidth: false
                text: i18n.tr("Valid Laps Only")
                on: panel.history.validOnly === true
                onSwitched: function(on) { backend.setValidOnly(on) }
            }
            TpButton {
                id: columnsButton
                flat: true
                glyph: ""  // sliders
                text: theme.iconFont === "" ? i18n.tr("Columns") : ""
                tip: i18n.tr("Columns")
                onClicked: columnMenu.popup(columnsButton, 0, columnsButton.height + 4)
                Accessible.name: i18n.tr("Columns")
                TpMenu {
                    id: columnMenu
                    Repeater {
                        model: panel.history.menu || []
                        MenuItem {
                            required property var modelData
                            text: modelData.title
                            checkable: true
                            checked: modelData.checked
                            onTriggered: backend.toggleHistoryColumn(modelData.option)
                        }
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Select laps, then add them: their average goes to the calculator, invalid laps (red) left out.")
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.88
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
                height: Math.round(theme.em * 1.9)
                Repeater {
                    model: panel.shown
                    Item {
                        id: headerCell
                        required property int index
                        required property var modelData
                        readonly property bool sorted: panel.history.sortColumn === modelData
                        width: panel.widths[index] || 0
                        height: headerRow.height
                        Row {
                            anchors.centerIn: parent
                            spacing: 2
                            Text {
                                text: panel.columns[headerCell.modelData].title
                                color: headerCell.sorted ? theme.text : theme.dimText
                                font.weight: Font.DemiBold
                                font.pointSize: theme.fontPoint * 0.9
                                width: Math.min(implicitWidth, headerCell.width - theme.em)
                                elide: Text.ElideRight
                            }
                            Icon {
                                visible: headerCell.sorted
                                glyph: panel.history.sortAscending ? "" : ""  // chevron up / down
                                size: theme.em * 0.6
                                color: theme.accent
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: backend.sortHistory(headerCell.modelData)
                        }
                    }
                }
            }
            Rectangle {
                y: headerRow.height
                width: Math.max(panel.tableWidth, tableScroll.width)
                height: 1
                color: theme.border
                opacity: 0.6
            }
            ListView {
                id: list
                y: headerRow.height + 1
                width: Math.max(panel.tableWidth, tableScroll.width)
                height: tableScroll.height - y
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                model: panel.history.rows || []
                activeFocusOnTab: true
                ScrollBar.vertical: ScrollBar {  // kept at the right of the panel when scrolled sideways
                    parent: tableScroll
                    x: tableScroll.width - width
                    y: list.y
                    height: list.height
                }
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_A && (event.modifiers & Qt.ControlModifier)) {
                        backend.selectAllLaps()
                        event.accepted = true
                    } else if (event.key === Qt.Key_Delete) {
                        backend.deleteSelectedLaps()
                        event.accepted = true
                    }
                }
                delegate: Rectangle {
                    id: lapRow
                    required property var modelData
                    required property int index
                    readonly property bool selected: panel.selection.indexOf(modelData.serial) >= 0
                    width: Math.max(panel.tableWidth, list.width)
                    height: Math.round(theme.em * 1.75)
                    radius: theme.em * 0.3
                    color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.3 : 0.2)
                         : rowArea.containsMouse ? theme.hover
                         : index % 2 ? (theme.dark ? Qt.rgba(1, 1, 1, 0.035) : Qt.rgba(0, 0, 0, 0.03)) : "transparent"
                    Row {
                        Repeater {
                            model: panel.shown
                            Text {
                                required property int index
                                required property var modelData
                                readonly property string key: panel.columns[modelData].key
                                width: panel.widths[index] || 0
                                height: lapRow.height
                                text: lapRow.modelData.cells[modelData]
                                color: !lapRow.modelData.valid && (key === "time" || key === "fuel" || key === "energy")
                                       ? panel.history.invalidColor : theme.text
                                font.features: { "tnum": 1 }
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                        }
                    }
                    MouseArea {
                        id: rowArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: function(mouse) {
                            list.forceActiveFocus()
                            backend.selectLap(lapRow.modelData.serial, panel.modeOf(mouse.modifiers))
                        }
                        onDoubleClicked: {
                            backend.selectLap(lapRow.modelData.serial, 0)
                            backend.addSelectedLaps()
                        }
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: panel.history.empty === true
            text: i18n.tr("No lap recorded yet: drive a few laps, or load a file.")
            color: theme.dimText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: backend.notes.historyAdded
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.9
            elide: Text.ElideRight
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            TpButton {
                enabled: !panel.history.empty && panel.selection.length > 0
                glyph: ""  // delete
                text: i18n.tr("Delete Selected")
                tip: i18n.tr("Delete selected laps from consumption history")
                onClicked: backend.deleteSelectedLaps()
            }
            TpButton {
                enabled: !panel.history.empty
                flat: true
                text: i18n.tr("Delete All")
                tip: i18n.tr("Delete whole consumption history of this track & class")
                onClicked: backend.deleteAllLaps()
            }
            Item { Layout.fillWidth: true }
            TpButton {
                enabled: !panel.history.empty
                accent: true
                glyph: ""  // add
                text: i18n.tr("Add Selected Data")
                tip: i18n.tr("Average of selected laps (double click: one lap) to the calculator")
                onClicked: backend.addSelectedLaps()
            }
        }
    }
}
