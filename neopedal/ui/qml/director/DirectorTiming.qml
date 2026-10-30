import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Timing table of the session: race, qualifying & pits views, each with its own columns. Drag a column title to
// move it, right click the titles (or the Columns button) to show or hide columns (saved for each view). Sectors &
// laps colored (purple ◆ best of class, green ● personal best, yellow slower), battles marked with their trend, car
// on air red with a ◉ mark, cars slow or causing a yellow flag amber with a ⚠ mark. Click: car sheet, double
// click: cut to the car. Keys in the table: Up / Down move, Enter opens the car sheet.
TpPopup {
    id: popup
    objectName: "timingTable"
    modal: true
    padding: theme.padPopup
    anchors.centerIn: parent
    width: parent ? parent.width * 0.94 : theme.em * 60
    height: parent ? parent.height * 0.9 : theme.em * 40
    onAboutToShow: backend.timing.setTimingOpen(true)
    onAboutToHide: backend.timing.setTimingOpen(false)

    readonly property var columns: backend.timing.timingColumns
    property int dragFrom: -1
    property int dragTo: -1

    // Cell color from the tone sent by the backend: "" plain text (marks besides colors, ◆ best of class, ● personal
    // best, and battle arrows: in the cell texts, director_timing.timing_cell)
    function cellColor(name) { return name ? theme.tone(name) : theme.text }
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
            delegate: TpMenuItem {
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
            spacing: theme.space3

            // Drawn under the cell text, made for their columns only (parent: the cell, its entry)
            Component {
                id: tyreCell
                Item {  // compound badges
                    id: tyres
                    anchors.fill: parent
                    z: -1
                    readonly property var list: (parent && parent.entry.tyres) || []
                    Row {
                        anchors.centerIn: parent
                        spacing: theme.space1
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
                    readonly property real level: parent && parent.entry.level !== undefined ? parent.entry.level : -1
                    // Same thresholds & colors as overlays and stream graphics (energy_tone)
                    readonly property color tint: popup.cellColor(parent ? parent.entry.tone || "" : "")
                    Rectangle {
                        visible: energy.level >= 0
                        anchors.verticalCenter: parent.verticalCenter
                        x: theme.space2
                        width: (parent.width - theme.space4) * Math.max(energy.level, 0)
                        height: Math.round(theme.em * 1.3)
                        radius: theme.radiusXs
                        color: theme.tint(energy.tint, "strong")
                    }
                }
            }
            Component {
                id: penaltyCell
                Item {  // red badge under the count
                    id: penalty
                    anchors.fill: parent
                    z: -1
                    readonly property string count: parent ? parent.text : ""
                    Rectangle {
                        visible: penalty.count !== ""
                        anchors.centerIn: parent
                        width: Math.round(theme.em * 1.6)
                        height: Math.round(theme.em * 1.3)
                        radius: theme.radiusSm
                        color: theme.lossFill
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space4
                TpCardHeader {
                    Layout.fillWidth: false
                    level: "popup"
                    glyph: ""  // list
                    title: i18n.tr("Timing")
                }
                TpSegmented {
                    objectName: "timingViews"
                    name: i18n.tr("Timing")
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
                TpButton {  // columns shown (as the right click on the titles), keyboard reachable
                    id: columnsButton
                    flat: true
                    glyph: ""  // list
                    text: i18n.tr("Columns")
                    onClicked: columnMenu.toggleBelow(columnsButton)  // second click closes it
                }
                TpButton {
                    glyph: theme.glyphs.reset
                    fallback: "↺"
                    flat: true
                    tip: i18n.tr("Columns of this view by default")
                    onClicked: backend.timing.resetTimingColumns()
                }
                TpButton {
                    glyph: theme.glyphs.close
                    fallback: "✕"
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
                contentWidth: Math.max(width, popup.columnX(popup.columns.length) + theme.em * 2)
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
                        implicitHeight: Math.round(theme.headerHeight)
                        Row {
                            x: theme.space4
                            height: parent.height
                            Repeater {
                                model: backend.timing.timingColumnRows
                                delegate: Item {
                                    id: heading
                                    required property string title
                                    required property real size
                                    required property string align
                                    required property int index
                                    width: size * theme.em
                                    height: titles.height
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: theme.radiusSm
                                        color: popup.dragFrom === heading.index ? theme.hover : "transparent"
                                    }
                                    TpHeaderCell {
                                        anchors.fill: parent
                                        text: heading.title
                                        align: heading.align === "right" ? Qt.AlignRight
                                             : heading.align === "center" ? Qt.AlignHCenter : Qt.AlignLeft
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
                                            popup.dragTo = popup.columnAt(point.x - theme.space4)
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
                            x: theme.space4 + popup.columnX(popup.dragTo > popup.dragFrom ? popup.dragTo + 1 : popup.dragTo) - width / 2
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
                        activeFocusOnTab: true
                        keyNavigationEnabled: true
                        highlightFollowsCurrentItem: false
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        move: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
                        displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
                        Keys.onShortcutOverride: function(event) {
                            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                                event.accepted = true
                        }
                        Keys.onReturnPressed: if (currentItem) backend.selectCar(currentItem.slot)
                        Keys.onEnterPressed: if (currentItem) backend.selectCar(currentItem.slot)
                        onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0

                        // Row roles bound once (required: updated on their change only), cells of the columns shown
                        // in one role made by the backend (text with its marks & tone): no model read per cell
                        delegate: Item {
                            id: row
                            required property int index
                            required property int slot
                            required property string classColor
                            required property bool onAir
                            required property bool yellow
                            required property var cells
                            readonly property bool current: ListView.isCurrentItem && list.activeFocus
                            property bool live: true  // false while recycled (reuseItems): row look shown at once
                            ListView.onPooled: live = false
                            ListView.onReused: live = true
                            width: ListView.view.width
                            height: Math.round(theme.rowCompact)

                            TpListRow {  // on air: loss tint, yellow flag: gold tint (marks after the last column)
                                id: rowBack
                                anchors.fill: parent
                                radius: theme.radiusSm
                                animate: row.live
                                hovered: rowArea.containsMouse
                                emphasized: row.onAir || row.yellow
                                tint: row.onAir ? theme.loss : theme.gold
                                striped: row.index % 2 === 1
                            }
                            FocusRing { target: rowBack; visible: row.current }
                            MouseArea {
                                id: rowArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { list.currentIndex = row.index; backend.selectCar(row.slot) }
                                onDoubleClicked: backend.cutToCar(row.slot)
                            }
                            TpClassStrip {  // class color
                                x: 0
                                height: parent.height - theme.em * 0.5
                                anchors.verticalCenter: parent.verticalCenter
                                tint: row.classColor
                            }
                            Row {
                                x: theme.space4
                                height: parent.height
                                Repeater {
                                    // Columns model: a column moved, shown or hidden moves, makes or frees its cells only
                                    model: backend.timing.timingColumnRows
                                    delegate: Text {  // one Text per cell, tyres, energy & penalties draw under it
                                        id: cell
                                        required property int index
                                        required property string key
                                        required property real size
                                        required property string align
                                        // Cell of this column (same order as the columns), {} until the rows follow
                                        // a column just shown
                                        readonly property var entry: row.cells[index] || ({})
                                        width: size * theme.em
                                        height: row.height
                                        leftPadding: theme.space2
                                        rightPadding: theme.space2
                                        verticalAlignment: Text.AlignVCenter
                                        horizontalAlignment: align === "right" ? Text.AlignRight
                                                           : align === "center" ? Text.AlignHCenter : Text.AlignLeft
                                        text: entry.text || ""
                                        textFormat: Text.PlainText
                                        color: key === "penalties" ? theme.inkOn(theme.lossFill)
                                             : entry.tone ? theme.tone(entry.tone)
                                             : key === "team" || key === "number" ? theme.dimOn(rowBack.color) : theme.text
                                        font.weight: key === "driver" || key === "classPos" || row.onAir && key === "number"
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
                            Text {  // state mark besides the tint (colorblind): ◉ on air, ⚠ yellow flag
                                x: theme.space4 + popup.columnX(popup.columns.length) + theme.space1
                                anchors.verticalCenter: parent.verticalCenter
                                visible: text !== ""
                                text: row.onAir ? "◉" : row.yellow ? "⚠" : ""
                                textFormat: Text.PlainText
                                color: row.onAir ? theme.loss : theme.text
                                font.pointSize: theme.fontSmall
                            }
                        }
                    }
                }
            }
        }
    }
}
