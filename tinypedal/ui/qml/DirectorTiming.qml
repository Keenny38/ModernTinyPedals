import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Timing table of the session: race, qualifying & pits views, each with its own columns. Drag a column title to
// move it, right click the titles to show or hide columns (saved for each view). Sectors & laps colored (purple
// best of class, green personal best, yellow slower), battles marked with their trend, car on air red, cars
// slow or causing a yellow flag amber. Click: car sheet, double click: cut to the car.
Popup {
    id: popup
    objectName: "timingTable"
    modal: true
    dim: true
    padding: theme.em * 0.9
    anchors.centerIn: parent
    width: parent ? parent.width * 0.94 : theme.em * 60
    height: parent ? parent.height * 0.9 : theme.em * 40
    onAboutToShow: backend.setTimingOpen(true)
    onAboutToHide: backend.setTimingOpen(false)
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
    background: Rectangle {
        radius: theme.em * 0.8
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    readonly property var columns: backend.timingColumns
    property int dragFrom: -1
    property int dragTo: -1

    function tone(name) {
        return name === "fastest" ? theme.purple : name === "gain" ? theme.gain : name === "yellow" ? theme.gold
             : name === "loss" ? theme.loss : name === "warning" ? theme.warning : name === "dim" ? theme.dimText : theme.text
    }
    function tyreColor(letter) {
        return letter === "S" ? "#E5484D" : letter === "M" ? "#F5C518" : letter === "H" ? (theme.dark ? "#EDEDED" : "#777777")
             : letter === "W" ? "#3E8EF7" : letter === "I" ? "#30A46C" : theme.dimText
    }
    // Place of a column at x in the titles row (dragged column dropped there)
    function columnAt(x) {
        let left = 0
        for (let index = 0; index < columns.length; index++) {
            const width = columns[index].width * theme.em
            if (x < left + width / 2) return index
            left += width
        }
        return columns.length - 1
    }
    function columnX(index) {
        let left = 0
        for (let i = 0; i < index && i < columns.length; i++) left += columns[i].width * theme.em
        return left
    }

    TpMenu {
        id: columnMenu
        Instantiator {
            model: backend.timingChoices
            delegate: MenuItem {
                required property var modelData
                text: modelData.title
                checkable: true
                checked: modelData.shown
                onTriggered: backend.toggleTimingColumn(modelData.key)
            }
            onObjectAdded: function(index, object) { columnMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { columnMenu.removeItem(object) }
        }
    }

    contentItem: ColumnLayout {
        spacing: theme.em * 0.5

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            Icon { glyph: ""; color: theme.accent }  // list
            Text {
                text: i18n.tr("Timing")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontPoint * 1.1
            }
            TpSegmented {
                objectName: "timingViews"
                options: [i18n.tr("Race"), i18n.tr("Qualifying"), i18n.tr("Pit Stops")]
                currentIndex: backend.timingViewIndex
                onActivated: function(index) { backend.setTimingView(index) }
            }
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Drag a column title to move it, right click: columns shown")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.82
                elide: Text.ElideRight
            }
            TpButton {
                glyph: ""  // undo
                flat: true
                tip: i18n.tr("Columns of this view by default")
                onClicked: backend.resetTimingColumns()
            }
            TpButton {
                glyph: ""  // close
                flat: true
                tip: i18n.tr("Close")
                onClicked: popup.close()
            }
        }

        Flickable {
            id: sideways
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: Math.max(width, popup.columnX(popup.columns.length) + theme.em * 1.2)
            contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentWidth > width
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                width: sideways.contentWidth
                height: sideways.height
                spacing: 2

                // Column titles: drag to move, right click: columns shown
                Item {
                    id: titles
                    Layout.fillWidth: true
                    implicitHeight: Math.round(theme.em * 2.0)
                    Row {
                        x: theme.em * 0.6
                        height: parent.height
                        Repeater {
                            model: popup.columns
                            delegate: Rectangle {
                                id: title
                                required property var modelData
                                required property int index
                                width: modelData.width * theme.em
                                height: titles.height
                                color: popup.dragFrom === index ? theme.hover : "transparent"
                                radius: theme.em * 0.3
                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: theme.em * 0.3
                                    anchors.rightMargin: theme.em * 0.3
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: title.modelData.align === "right" ? Text.AlignRight
                                                       : title.modelData.align === "center" ? Text.AlignHCenter : Text.AlignLeft
                                    text: title.modelData.title
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.8
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                    property real startX: 0
                                    onPressed: function(mouse) {
                                        if (mouse.button === Qt.RightButton) { columnMenu.popup(); return }
                                        startX = mouse.x
                                        popup.dragFrom = title.index
                                        popup.dragTo = title.index
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (popup.dragFrom < 0) return
                                        const point = mapToItem(titles, mouse.x, mouse.y)
                                        popup.dragTo = popup.columnAt(point.x - theme.em * 0.6)
                                    }
                                    onReleased: {
                                        if (popup.dragFrom >= 0 && popup.dragTo >= 0 && popup.dragTo !== popup.dragFrom)
                                            backend.moveTimingColumn(popup.dragFrom, popup.dragTo)
                                        popup.dragFrom = -1
                                        popup.dragTo = -1
                                    }
                                }
                            }
                        }
                    }
                    Rectangle {  // where the dragged column goes
                        visible: popup.dragFrom >= 0 && popup.dragTo !== popup.dragFrom
                        x: theme.em * 0.6 + popup.columnX(popup.dragTo > popup.dragFrom ? popup.dragTo + 1 : popup.dragTo) - width / 2
                        width: 3
                        height: parent.height
                        color: theme.accent
                    }
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border }

                ListView {
                    id: list
                    objectName: "timingList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: backend.timingRows
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true
                    spacing: 1
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    move: Transition { NumberAnimation { properties: "y"; duration: 220; easing.type: Easing.OutCubic } }
                    displaced: Transition { NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic } }

                    delegate: Rectangle {
                        id: row
                        property var rowData: model
                        width: ListView.view.width
                        height: Math.round(theme.em * 2.1)
                        radius: theme.em * 0.3
                        color: rowData.onAir ? Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.18)
                             : rowData.yellow ? Qt.rgba(theme.gold.r, theme.gold.g, theme.gold.b, 0.16)
                             : rowArea.containsMouse ? theme.hover
                             : index % 2 ? Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.025 : 0.03) : "transparent"

                        MouseArea {
                            id: rowArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: backend.selectCar(row.rowData.slot)
                            onDoubleClicked: backend.cutToCar(row.rowData.slot)
                        }
                        Rectangle {  // class color
                            x: 0
                            width: Math.round(theme.em * 0.25)
                            height: parent.height - theme.em * 0.5
                            anchors.verticalCenter: parent.verticalCenter
                            radius: width / 2
                            color: row.rowData.classColor
                        }
                        Row {
                            x: theme.em * 0.6
                            height: parent.height
                            Repeater {
                                model: popup.columns
                                delegate: Item {
                                    id: cellBox
                                    required property var modelData
                                    readonly property string key: modelData.key
                                    width: modelData.width * theme.em
                                    height: row.height
                                    // Tyres: rings colored by compound
                                    Row {
                                        anchors.centerIn: parent
                                        visible: cellBox.key === "tyres"
                                        spacing: 1
                                        Repeater {
                                            model: cellBox.key === "tyres" ? row.rowData.tyreList : []
                                            delegate: Rectangle {
                                                required property string modelData
                                                width: Math.round(theme.em * 1.05)
                                                height: width
                                                radius: width / 2
                                                color: "transparent"
                                                border.width: Math.max(1.5, theme.em * 0.14)
                                                border.color: popup.tyreColor(modelData)
                                                Text {
                                                    anchors.centerIn: parent
                                                    text: parent.modelData
                                                    color: theme.text
                                                    font.pointSize: theme.fontPoint * 0.6
                                                    font.weight: Font.Bold
                                                }
                                            }
                                        }
                                    }
                                    // Energy: bar & percent
                                    Rectangle {
                                        visible: cellBox.key === "energy" && row.rowData.energyLevel >= 0
                                        anchors.verticalCenter: parent.verticalCenter
                                        x: theme.em * 0.3
                                        width: (parent.width - theme.em * 0.6) * Math.max(row.rowData.energyLevel, 0)
                                        height: Math.round(theme.em * 1.3)
                                        radius: theme.em * 0.2
                                        color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.28)
                                    }
                                    // Penalties: red badge
                                    Rectangle {
                                        visible: cellBox.key === "penalties" && row.rowData.penalties !== ""
                                        anchors.centerIn: parent
                                        width: Math.round(theme.em * 1.6)
                                        height: Math.round(theme.em * 1.3)
                                        radius: theme.em * 0.25
                                        color: theme.loss
                                    }
                                    Text {
                                        anchors.fill: parent
                                        anchors.leftMargin: theme.em * 0.3
                                        anchors.rightMargin: theme.em * 0.3
                                        visible: cellBox.key !== "tyres"
                                        verticalAlignment: Text.AlignVCenter
                                        horizontalAlignment: cellBox.modelData.align === "right" ? Text.AlignRight
                                                           : cellBox.modelData.align === "center" ? Text.AlignHCenter : Text.AlignLeft
                                        text: {
                                            const value = row.rowData[cellBox.key]
                                            if (cellBox.key === "interval" && row.rowData.battle)
                                                return (row.rowData.trend < 0 ? "▼ " : row.rowData.trend > 0 ? "▲ " : "• ") + value
                                            return value === undefined ? "" : value
                                        }
                                        color: {
                                            const key = cellBox.key
                                            if (key === "penalties") return "white"
                                            if (key === "change") return row.rowData.changeValue > 0 ? theme.gain : theme.loss
                                            if (key === "status") return popup.tone(row.rowData.statusTone)
                                            if (key === "interval" && row.rowData.battle && row.rowData.intervalTone === "")
                                                return theme.accent
                                            const tint = row.rowData[key + "Tone"]
                                            return tint ? popup.tone(tint) : (key === "driver" || key === "pos" || key === "classPos" ? theme.text
                                                 : key === "team" || key === "number" ? theme.dimText : theme.text)
                                        }
                                        font.weight: cellBox.key === "driver" || cellBox.key === "classPos" || row.rowData.onAir && cellBox.key === "number"
                                                     ? Font.DemiBold : Font.Normal
                                        font.pointSize: theme.fontPoint * (cellBox.key === "penalties" ? 0.75 : 0.92)
                                        font.features: { "tnum": 1 }
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
