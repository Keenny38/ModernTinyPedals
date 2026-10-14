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
    onAboutToShow: backend.timing.setTimingOpen(true)
    onAboutToHide: backend.timing.setTimingOpen(false)
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }
    background: Rectangle {
        radius: theme.radiusXl
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    readonly property var columns: backend.timing.timingColumns
    property int dragFrom: -1
    property int dragTo: -1

    function tone(name) {
        return name === "fastest" ? theme.purple : name === "gain" ? theme.gain : name === "yellow" ? theme.gold
             : name === "loss" ? theme.loss : name === "warning" ? theme.warning : name === "dim" ? theme.dimText : theme.text
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
            model: backend.timing.timingChoices
            delegate: MenuItem {
                required property var modelData
                text: modelData.title
                checkable: true
                checked: modelData.shown
                onTriggered: backend.timing.toggleTimingColumn(modelData.key)
            }
            onObjectAdded: function(index, object) { columnMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { columnMenu.removeItem(object) }
        }
    }

    contentItem: LazyPane {
        shown: popup.visible
        keep: false  // rows of every car freed once closed
        sourceComponent: ColumnLayout {
            spacing: theme.em * 0.5

            // Drawn under the cell text, made for their columns only (parent: the cell, its rowData)
            Component {
                id: tyreCell
                Item {  // compound badges
                    id: tyres
                    anchors.fill: parent
                    z: -1
                    readonly property var list: parent ? parent.rowData.tyreList : []
                    Row {
                        anchors.centerIn: parent
                        spacing: theme.em * 0.2
                        Repeater {
                            model: 2
                            delegate: TpCompound {
                                required property int index
                                name: index < tyres.list.length ? tyres.list[index] : ""
                            }
                        }
                    }
                }
            }
            Component {
                id: energyCell
                Item {  // bar under the percent
                    id: energy
                    anchors.fill: parent
                    z: -1
                    readonly property real level: parent ? parent.rowData.energyLevel : -1
                    // Same thresholds & colors as overlays and stream graphics (energy_tone)
                    readonly property color tint: popup.tone(parent ? parent.rowData.energyTone : "")
                    Rectangle {
                        visible: energy.level >= 0
                        anchors.verticalCenter: parent.verticalCenter
                        x: theme.em * 0.3
                        width: (parent.width - theme.em * 0.6) * Math.max(energy.level, 0)
                        height: Math.round(theme.em * 1.3)
                        radius: theme.radiusXs
                        color: Qt.rgba(energy.tint.r, energy.tint.g, energy.tint.b, 0.3)
                    }
                }
            }
            Component {
                id: penaltyCell
                Item {  // red badge under the count
                    id: penalty
                    anchors.fill: parent
                    z: -1
                    readonly property string count: parent ? parent.rowData.penalties : ""
                    Rectangle {
                        visible: penalty.count !== ""
                        anchors.centerIn: parent
                        width: Math.round(theme.em * 1.6)
                        height: Math.round(theme.em * 1.3)
                        radius: theme.radiusSm
                        color: theme.loss
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.em * 0.6
                Icon { glyph: ""; color: theme.accent }  // list
                Text {
                    text: i18n.tr("Timing")
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontSubtitle
                }
                TpSegmented {
                    objectName: "timingViews"
                    options: [i18n.tr("Race"), i18n.tr("Qualifying"), i18n.tr("Pit Stops")]
                    currentIndex: backend.timing.timingViewIndex
                    onActivated: function(index) { backend.timing.setTimingView(index) }
                }
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("Drag a column title to move it, right click: columns shown")
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    elide: Text.ElideRight
                }
                TpButton {
                    glyph: ""  // undo
                    flat: true
                    tip: i18n.tr("Columns of this view by default")
                    onClicked: backend.timing.resetTimingColumns()
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
                                model: backend.timing.timingColumnRows
                                delegate: Rectangle {
                                    id: heading
                                    required property string title
                                    required property real size
                                    required property string align
                                    required property int index
                                    width: size * theme.em
                                    height: titles.height
                                    color: popup.dragFrom === index ? theme.hover : "transparent"
                                    radius: theme.radiusSm
                                    Text {
                                        anchors.fill: parent
                                        anchors.leftMargin: theme.em * 0.3
                                        anchors.rightMargin: theme.em * 0.3
                                        verticalAlignment: Text.AlignVCenter
                                        horizontalAlignment: heading.align === "right" ? Text.AlignRight
                                                           : heading.align === "center" ? Text.AlignHCenter : Text.AlignLeft
                                        text: heading.title
                                        color: theme.dimText
                                        font.pointSize: theme.fontCaption
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
                                            popup.dragFrom = heading.index
                                            popup.dragTo = heading.index
                                        }
                                        onPositionChanged: function(mouse) {
                                            if (popup.dragFrom < 0) return
                                            const point = mapToItem(titles, mouse.x, mouse.y)
                                            popup.dragTo = popup.columnAt(point.x - theme.em * 0.6)
                                        }
                                        onReleased: {
                                            if (popup.dragFrom >= 0 && popup.dragTo >= 0 && popup.dragTo !== popup.dragFrom)
                                                backend.timing.moveTimingColumn(popup.dragFrom, popup.dragTo)
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
                        model: backend.timing.timingRows
                        boundsBehavior: Flickable.StopAtBounds
                        reuseItems: true
                        spacing: 1
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        move: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                        displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }

                        delegate: Rectangle {
                            id: row
                            property var rowData: model
                            width: ListView.view.width
                            height: Math.round(theme.em * 2.1)
                            radius: theme.radiusSm
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
                                    // Columns model: a column moved, shown or hidden moves, makes or frees its cells only
                                    model: backend.timing.timingColumnRows
                                    delegate: Text {  // one Text per cell, tyres, energy & penalties draw under it
                                        id: cell
                                        required property string key
                                        required property real size
                                        required property string align
                                        readonly property var rowData: row.rowData
                                        width: size * theme.em
                                        height: row.height
                                        leftPadding: theme.em * 0.3
                                        rightPadding: theme.em * 0.3
                                        verticalAlignment: Text.AlignVCenter
                                        horizontalAlignment: align === "right" ? Text.AlignRight
                                                           : align === "center" ? Text.AlignHCenter : Text.AlignLeft
                                        text: {
                                            if (key === "tyres") return ""
                                            const value = row.rowData[key]
                                            if (key === "interval" && row.rowData.battle)
                                                return (row.rowData.trend < 0 ? "▼ " : row.rowData.trend > 0 ? "▲ " : "• ") + value
                                            return value === undefined ? "" : value
                                        }
                                        color: {
                                            if (key === "penalties") return "white"
                                            if (key === "change") return row.rowData.changeValue > 0 ? theme.gain : theme.loss
                                            if (key === "status") return popup.tone(row.rowData.statusTone)
                                            if (key === "interval" && row.rowData.battle && row.rowData.intervalTone === "")
                                                return theme.accent
                                            const tint = row.rowData[key + "Tone"]
                                            return tint ? popup.tone(tint) : (key === "driver" || key === "pos" || key === "classPos" ? theme.text
                                                 : key === "team" || key === "number" ? theme.dimText : theme.text)
                                        }
                                        font.weight: key === "driver" || key === "classPos" || row.rowData.onAir && key === "number"
                                                     ? Font.DemiBold : Font.Normal
                                        font.pointSize: (key === "penalties" ? theme.fontCaption : theme.fontLabel)
                                        font.features: { "tnum": 1 }
                                        elide: Text.ElideRight
                                        // Tyres, energy & penalties: drawn under the text, made for those columns only
                                        Component.onCompleted: {
                                            const extra = key === "tyres" ? tyreCell : key === "energy" ? energyCell
                                                        : key === "penalties" ? penaltyCell : null
                                            if (extra !== null) extra.createObject(cell)
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
}
