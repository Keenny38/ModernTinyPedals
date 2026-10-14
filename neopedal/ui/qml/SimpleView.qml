import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import NeoPedal

// Simple view (page mode shown over charts): what each lap does at chart cursor, drawn like overlays. Pedals & steering
// wheel card of each lap (clutch, brake & throttle capsules, steering wheel turned by real angle when recorded, gear &
// speed), side by side when wide enough, then groups of channels (timing, engine, tyres, brakes, chassis, electronics,
// track, math channels): values of main lap (lap card clicked, else reference lap), other laps as marks of their color.
// Lap chips of charts above it (same place in both views): click highlights the main lap. Follows cursor, playback, map
// hover & kept position; playback bar under it moves the cursor along lap (charts hidden).
Item {
    id: root

    property var chart
    // Shown values: none while hidden (no item updated on every cursor move)
    readonly property var laps: visible && chart ? chart.cursorInputs : []
    readonly property var values: visible && chart ? chart.cursorDashboard : []
    readonly property var shownLaps: laps
    readonly property string highlightKey: chart ? chart.highlightKey : ""
    // Items shown: read only while tab is shown (hidden tab never builds it again on chart & math changes)
    readonly property var layout: visible ? backend.dashboard.layout : []
    readonly property bool cardsShown: layout.length > 0 && layout[0].key === "driver"
    readonly property var groups: cardsShown ? layout.slice(1) : layout
    // Main lap: highlighted (lap card or lap chip), else reference lap, else first lap
    readonly property int mainIndex: {
        var legend = chart ? chart.legendLaps : []
        var key = highlightKey
        for (var i = 0; key === "" && i < legend.length; i++) if (legend[i].reference) key = legend[i].key
        for (var j = 0; j < laps.length; j++) if (laps[j].lap === key) return j
        return 0
    }
    readonly property var mainLap: laps[mainIndex] || null
    // Lap cards side by side when wide enough, same size; height fills room left by groups (compact above many
    // groups, scrolls past a few rows)
    readonly property int cardColumns: Math.max(1, Math.min(shownLaps.length,
        Math.floor((list.width + list.spacing) / (theme.em * 24 + list.spacing))))
    readonly property int cardRows: Math.ceil(shownLaps.length / cardColumns)
    readonly property real cardWidth: (column.width - (cardColumns - 1) * list.spacing) / cardColumns
    readonly property real cardRoom: list.height - (groups.length > 0
        ? groupColumn.height + list.spacing + (mainRow.visible ? mainRow.height + list.spacing : 0) : 0)
    readonly property real cardHeight: Math.max(Math.min((cardRoom - (cardRows - 1) * list.spacing) / Math.max(cardRows, 1),
                                                         theme.em * 20), groups.length > 0 ? theme.em * 8.5 : theme.em * 7)

    function lapOpacity(lapKey) { return highlightKey === "" || lapKey === highlightKey ? 1 : 0.3 }
    // Items shown changed: values asked again (one entry per shown item)
    onLayoutChanged: if (visible && chart && chart.hasCursor) chart.fetchCursor()
    Component.onCompleted: if (chart && chart.hasCursor) chart.fetchCursor()

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.4

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Text {
                anchors.centerIn: parent
                width: parent.width - theme.em * 2
                visible: root.laps.length === 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: root.layout.length === 0 ? i18n.tr("Nothing picked: choose what is shown with Show")
                                               : i18n.tr("Move over track map, drag bar below or play lap to see driver inputs")
                color: theme.dimText
            }

            Flickable {
                id: list
                readonly property real spacing: theme.em * 0.5
                anchors.fill: parent
                visible: root.laps.length > 0
                clip: true
                contentHeight: column.height
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                ScrollBar.vertical: ScrollBar { policy: list.interactive ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }

                Column {
                    id: column
                    width: list.width - (list.interactive ? theme.em * 0.7 : 0)
                    spacing: list.spacing
                    // One card per lap, kept while cursor moves (values read by index)
                    Flow {
                        width: column.width
                        spacing: list.spacing
                        visible: root.cardsShown
                        Repeater {
                            model: root.cardsShown ? root.shownLaps.length : 0
                            InputsCard {
                                required property int index
                                width: root.cardWidth
                                height: root.cardHeight
                                lap: root.shownLaps[index] || null
                                opacity: lap ? (lap.ended ? 0.4 : root.lapOpacity(lap.lap)) : 1
                            }
                        }
                    }
                    // Main lap of groups (full values), other laps as marks
                    Row {
                        id: mainRow
                        visible: root.groups.length > 0 && root.shownLaps.length > 1 && root.mainLap !== null
                        spacing: theme.em * 0.4
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: theme.em * 0.55
                            height: width
                            radius: width / 2
                            color: root.mainLap ? root.mainLap.color : "transparent"
                        }
                        Text {
                            width: column.width - theme.em
                            text: i18n.tr("Values of %1, other laps as marks").arg(root.mainLap ? root.mainLap.label : "")
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            elide: Text.ElideRight
                            HoverHandler { id: mainHover }
                            ToolTip.visible: mainHover.hovered
                            ToolTip.text: i18n.tr("Click a lap card or chip to see its values here")
                            ToolTip.delay: theme.tipDelay
                        }
                    }
                    Column {
                        id: groupColumn
                        width: column.width
                        spacing: list.spacing
                        Repeater {
                            model: root.groups
                            DashboardGroup {
                                required property var modelData
                                width: column.width
                                info: modelData
                                values: root.values
                                laps: root.laps
                                mainIndex: root.mainIndex
                            }
                        }
                    }
                }
            }
        }
    }

    component InputsCard: Rectangle {
        id: card

        property var lap
        readonly property real pad: theme.em * 0.6
        readonly property real bodyHeight: height - header.height - pad * 2 - theme.em * 0.4
        readonly property real gaugeHeight: bodyHeight - theme.em * 2.4  // readings above, labels under

        readonly property bool pinned: lap !== null && root.chart && root.chart.pinnedKey === lap.lap

        radius: theme.radiusLg
        color: cardArea.containsMouse ? theme.hover : theme.alternate
        border.width: pinned ? 2 : 1
        border.color: lap ? Qt.rgba(Qt.color(lap.color).r, Qt.color(lap.color).g, Qt.color(lap.color).b, pinned ? 1 : 0.45)
                          : theme.border

        // Click: values of this lap in groups below (lap highlighted), again: back to reference lap
        MouseArea {
            id: cardArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (card.lap && root.chart) root.chart.pinnedKey = card.pinned ? "" : card.lap.lap
        }

        RowLayout {
            id: header
            x: card.pad
            y: card.pad
            width: card.width - card.pad * 2
            spacing: theme.em * 0.4
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                width: theme.em * 0.6
                height: width
                radius: width / 2
                color: card.lap ? card.lap.color : "transparent"
            }
            Text {
                Layout.fillWidth: true
                text: card.lap ? card.lap.label : ""
                color: theme.text
                font.bold: true
                elide: Text.ElideRight
            }
            Text {
                visible: card.lap !== null && card.lap.speed !== ""
                text: card.lap ? card.lap.speed + " " + card.lap.speedUnit : ""
                color: theme.dimText
                font.features: { "tnum": 1 }
            }
            Rectangle {  // gear
                visible: card.lap !== null && card.lap.gear !== ""
                implicitWidth: Math.max(gearText.implicitWidth + theme.em * 0.6, theme.em * 1.6)
                implicitHeight: theme.em * 1.5
                radius: theme.radiusSm
                color: theme.raised
                Text {
                    id: gearText
                    anchors.centerIn: parent
                    text: card.lap ? card.lap.gear : ""
                    color: theme.text
                    font.bold: true
                }
            }
        }

        RowLayout {
            x: card.pad
            y: header.y + header.height + theme.em * 0.4
            width: card.width - card.pad * 2
            height: card.bodyHeight
            spacing: theme.em * 0.5

            Repeater {
                model: [["clutch", "C", theme.accent], ["brake", "B", theme.loss], ["throttle", "T", theme.gain]]
                PedalGauge {
                    required property var modelData
                    Layout.fillHeight: true
                    value: card.lap ? card.lap[modelData[0]] : -1
                    label: modelData[1]
                    fillColor: modelData[2]
                    gaugeHeight: card.gaugeHeight
                    visible: value >= 0
                }
            }
            Item { Layout.fillWidth: true }
            SteeringWheel {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: Math.min(card.bodyHeight, card.width * 0.55)
                Layout.preferredHeight: Layout.preferredWidth
                steering: card.lap ? card.lap.steering : 0
                angle: card.lap ? card.lap.angle : 0
                realAngle: card.lap !== null && card.lap.rotation > 0
            }
            Item { Layout.fillWidth: true }
        }
    }

    // Capsule filled to input from bottom (brighter toward input end), reading above, short label under
    component PedalGauge: Item {
        id: gauge

        property real value: 0
        property string label
        property color fillColor
        property real gaugeHeight

        implicitWidth: theme.em * 2.6
        Text {
            id: reading
            anchors.horizontalCenter: parent.horizontalCenter
            text: Math.round(Math.max(gauge.value, 0) * 100)
            color: theme.dimText
            font.pointSize: theme.fontSmall
            font.features: { "tnum": 1 }
        }
        Rectangle {
            id: track
            anchors.horizontalCenter: parent.horizontalCenter
            y: reading.height + theme.em * 0.2
            width: theme.em * 1.25
            height: Math.max(gauge.gaugeHeight, theme.em)
            radius: width / 2
            color: theme.raised
            Rectangle {
                readonly property real filled: Math.max(gauge.value, 0) * track.height
                anchors.bottom: parent.bottom
                width: parent.width
                height: filled
                visible: filled > 0.5
                radius: Math.min(width, height) / 2
                gradient: Gradient {
                    GradientStop { position: 0; color: Qt.lighter(gauge.fillColor, 1.15) }
                    GradientStop { position: 1; color: Qt.darker(gauge.fillColor, 1.25) }
                }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: track.y + track.height + theme.em * 0.15
            text: gauge.label
            color: theme.dimText
            font.bold: true
            font.pointSize: theme.fontSmall
        }
    }

    // Steering wheel turned by steering: rim with top stripe, three spokes, hub, rotation arc from top,
    // angle over hub (degrees if wheel rotation recorded, else percent of lock)
    component SteeringWheel: Item {
        id: wheel
        // Multisampled layer while shown: smooth turned spokes & arc (window without MSAA), small texture
        layer.enabled: pageState.active && visible && width > 0 && height > 0
        layer.samples: 4

        property real steering: 0  // -1 left to 1 right
        property real angle: 0  // degrees
        property bool realAngle: false  // wheel rotation recorded (laps of older versions: not)
        readonly property real turn: realAngle ? angle : steering * 225  // unknown rotation: 450° wheel drawn
        readonly property real size: Math.min(width, height)
        readonly property real arcWidth: Math.max(size * 0.05, 2)
        readonly property real rimWidth: Math.max(size * 0.075, 2.5)
        readonly property real arcRadius: size / 2 - size * 0.025 - arcWidth / 2
        readonly property real rimRadius: arcRadius - arcWidth / 2 - size * 0.025 - rimWidth / 2

        Rectangle {  // dial
            anchors.centerIn: parent
            width: wheel.size
            height: width
            radius: width / 2
            color: theme.base
            border.width: 1
            border.color: theme.border
        }
        ArcItem {  // rotation from top (scene graph geometry: no painting on GUI thread)
            anchors.fill: parent
            sweep: Math.round(wheel.turn)  // whole degrees: built again only once arc grows visibly
            radius: wheel.arcRadius
            thickness: wheel.arcWidth
            color: theme.accent
        }
        Item {  // wheel shapes, turned
            anchors.centerIn: parent
            width: wheel.rimRadius * 2 + wheel.rimWidth
            height: width
            rotation: wheel.turn
            Repeater {
                model: [90, 180, 270]  // right, bottom, left spokes: hub to rim, turned around center
                Item {
                    required property var modelData
                    anchors.fill: parent
                    rotation: modelData
                    Rectangle {
                        x: parent.width / 2 - width / 2
                        y: parent.height / 2 - wheel.rimRadius
                        width: wheel.rimRadius * 0.2
                        height: wheel.rimRadius * 0.73
                        color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.55)
                    }
                }
            }
            Rectangle {  // rim
                anchors.fill: parent
                radius: width / 2
                color: "transparent"
                border.width: wheel.rimWidth
                border.color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.85)
            }
            Rectangle {  // top center stripe
                x: parent.width / 2 - width / 2
                y: 0
                width: Math.max(wheel.rimRadius * 0.3, 3)
                height: wheel.rimWidth
                color: theme.warning
            }
            Rectangle {  // hub
                anchors.centerIn: parent
                width: wheel.rimRadius * 0.68
                height: width
                radius: width / 2
                color: theme.raised
                border.width: Math.max(wheel.rimWidth * 0.3, 1)
                border.color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.3)
            }
        }
        Rectangle {  // reading over hub
            anchors.centerIn: parent
            width: angleText.implicitWidth + theme.em * 0.6
            height: angleText.implicitHeight + theme.em * 0.2
            radius: theme.radiusSm
            color: Qt.rgba(theme.base.r, theme.base.g, theme.base.b, 0.9)
            Text {
                id: angleText
                anchors.centerIn: parent
                text: wheel.realAngle ? Math.round(Math.abs(wheel.angle)) + "°" : Math.round(Math.abs(wheel.steering) * 100) + "%"
                color: theme.text
                font.bold: true
                font.features: { "tnum": 1 }
            }
        }
    }

    // Group of items (timing, engine, tyres...): bars & lights two per row when wide enough
    component DashboardGroup: Rectangle {
        id: group

        property var info: ({ "title": "", "items": [] })
        property var values: []
        property var laps: []
        property int mainIndex: 0
        property var hidden: ({})
        readonly property real pad: theme.em * 0.6
        readonly property int columns: width >= theme.em * 26 ? 2 : 1
        readonly property real cell: (width - pad * 2 - (columns - 1) * flow.spacing) / columns

        height: flow.y + flow.height + pad
        radius: theme.radiusLg
        color: theme.alternate
        border.width: 1
        border.color: theme.dark ? Qt.lighter(theme.alternate, 1.3) : theme.border

        Text {
            id: groupTitle
            x: group.pad
            y: group.pad * 0.8
            text: group.info.title
            color: theme.dimText
            font.weight: Font.DemiBold
            font.pointSize: theme.fontSmall
        }
        Flow {
            id: flow
            x: group.pad
            y: groupTitle.y + groupTitle.height + theme.em * 0.4
            width: group.width - group.pad * 2
            spacing: theme.em * 0.6
            Repeater {
                model: group.info.items
                Item {
                    id: cellItem
                    required property var modelData
                    readonly property var cursorValue: group.values[modelData.index]
                    readonly property var entries: cursorValue && cursorValue.key === modelData.key ? cursorValue.laps : []  // former layout: none
                    readonly property string kind: modelData.kind
                    width: kind === "light" ? (group.cell - flow.spacing) / 2 : group.cell
                    height: loader.item ? loader.item.implicitHeight : 0
                    Loader {
                        id: loader
                        width: parent.width
                        sourceComponent: cellItem.kind === "wheels" ? wheelsItem : cellItem.kind === "light" ? lightItem
                                         : cellItem.kind === "g" ? gItem : barItem
                    }
                    Component {
                        id: barItem
                        BarItem { info: cellItem.modelData; entries: cellItem.entries; laps: group.laps; mainIndex: group.mainIndex; hidden: group.hidden }
                    }
                    Component {
                        id: wheelsItem
                        WheelsItem { info: cellItem.modelData; entries: cellItem.entries; laps: group.laps; mainIndex: group.mainIndex; hidden: group.hidden }
                    }
                    Component {
                        id: lightItem
                        LightItem { info: cellItem.modelData; entries: cellItem.entries; laps: group.laps; mainIndex: group.mainIndex; hidden: group.hidden }
                    }
                    Component {
                        id: gItem
                        GItem { info: cellItem.modelData; entries: cellItem.entries; laps: group.laps; mainIndex: group.mainIndex; hidden: group.hidden }
                    }
                }
            }
        }
    }

    // Item base: values of each lap, main lap, laps hidden in this view
    component ItemBase: Item {
        property var info: ({ "title": "", "unit": "", "kind": "bar" })
        property var entries: []
        property var laps: []
        property int mainIndex: 0
        property var hidden: ({})
        readonly property var main: entries[mainIndex] && entries[mainIndex].ok ? entries[mainIndex] : null
        readonly property color mainColor: laps[mainIndex] ? laps[mainIndex].color : theme.accent
        readonly property string titleText: info.title + (info.unit ? " (" + info.unit + ")" : "")

        function marked(index) {  // other lap shown as a mark
            var entry = entries[index]
            return index !== mainIndex && entry !== undefined && entry.ok && laps[index] !== undefined
                && hidden[laps[index].lap] !== true
        }
        // Every lap value (tooltip)
        function lapTexts(text) {
            var lines = []
            for (var i = 0; i < entries.length; i++)
                if (entries[i] && entries[i].ok && laps[i] && hidden[laps[i].lap] !== true) lines.push(laps[i].label + " : " + text(entries[i]))
            return lines.join("\n")
        }
    }

    // Value from low to high (or around 0: center): main lap filled in its color, other laps as marks.
    // Car setting (number): value only
    component BarItem: ItemBase {
        id: bar

        readonly property bool centered: info.kind === "center"
        readonly property bool plain: info.kind === "number"
        function position(at) { return (centered ? (at + 1) / 2 : at) * track.width }

        implicitHeight: plain ? barLabel.height + theme.em * 0.2 : barLabel.height + theme.em * 0.3 + track.height + theme.em * 0.2
        HoverHandler { id: barHover }
        ToolTip.visible: barHover.hovered && bar.entries.length > 1
        ToolTip.text: barHover.hovered ? bar.lapTexts(function(entry) { return entry.t }) : ""  // built only while hovered
        ToolTip.delay: theme.tipDelay

        Text {
            id: barLabel
            width: parent.width - barValue.width - theme.em * 0.4
            text: bar.titleText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
        }
        Text {
            id: barValue
            anchors.right: parent.right
            anchors.baseline: barLabel.baseline
            text: bar.main ? bar.main.t : "–"
            color: theme.text
            font.bold: true
            font.features: { "tnum": 1 }
        }
        Rectangle {
            id: track
            visible: !bar.plain
            y: barLabel.height + theme.em * 0.3
            width: parent.width
            height: theme.em * 0.5
            radius: height / 2
            color: theme.raised
            Rectangle {  // main lap
                readonly property real at: bar.main ? bar.main.a : 0
                visible: bar.main !== null && width > 0.5
                x: bar.centered ? Math.min(bar.position(at), track.width / 2) : 0
                width: bar.centered ? Math.abs(bar.position(at) - track.width / 2) : bar.position(at)
                height: parent.height
                radius: height / 2
                color: bar.mainColor
            }
            Rectangle {  // zero
                visible: bar.centered
                x: track.width / 2 - 0.5
                y: -theme.em * 0.15
                width: 1
                height: track.height + theme.em * 0.3
                color: theme.dimText
            }
            Repeater {
                model: bar.entries.length
                Rectangle {
                    required property int index
                    visible: bar.marked(index)
                    x: visible ? bar.position(bar.entries[index].a) - width / 2 : 0
                    y: -theme.em * 0.2
                    width: 3
                    height: track.height + theme.em * 0.4
                    radius: 1.5
                    color: bar.laps[index] ? bar.laps[index].color : "transparent"
                    border.width: 1
                    border.color: theme.base
                }
            }
        }
    }

    // On / off (TC, ABS active): main lap lamp, other laps as small lamps of their color
    component LightItem: ItemBase {
        id: light

        implicitHeight: theme.em * 1.6
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: theme.em * 0.4
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: theme.em * 1.05
                height: width
                radius: width / 2
                color: light.main && light.main.on ? theme.warning : theme.raised
                border.width: 1
                border.color: light.main && light.main.on ? Qt.lighter(theme.warning, 1.3) : theme.border
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, light.width - theme.em * 1.5 - others.width)
                text: light.info.title
                color: light.main && light.main.on ? theme.text : theme.dimText
                font.pointSize: theme.fontLabel
                elide: Text.ElideRight
            }
            Row {
                id: others
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3
                Repeater {
                    model: light.entries.length
                    Rectangle {
                        required property int index
                        visible: light.marked(index)
                        width: theme.em * 0.5
                        height: width
                        radius: width / 2
                        color: visible && light.entries[index].on ? light.laps[index].color : "transparent"
                        border.width: 1
                        border.color: light.laps[index] ? light.laps[index].color : "transparent"
                    }
                }
            }
        }
    }

    // 4 wheels (FL FR / RL RR): tile of main lap value (colored cold to hot for temperatures), bar under it with
    // other laps as marks
    component WheelsItem: ItemBase {
        id: wheels

        readonly property var names: ["FL", "FR", "RL", "RR"]
        implicitHeight: wheelsLabel.height + theme.em * 0.3 + tiles.height
        HoverHandler { id: wheelsHover }
        ToolTip.visible: wheelsHover.hovered && wheels.entries.length > 1
        ToolTip.text: wheelsHover.hovered ? wheels.lapTexts(function(entry) { return entry.t.join(" · ") }) : ""
        ToolTip.delay: theme.tipDelay

        Text {
            id: wheelsLabel
            width: parent.width
            text: wheels.titleText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
        }
        Grid {
            id: tiles
            y: wheelsLabel.height + theme.em * 0.3
            width: parent.width
            columns: 2
            spacing: theme.em * 0.3
            Repeater {
                model: 4
                Rectangle {
                    id: tile
                    required property int index
                    readonly property real at: wheels.main ? wheels.main.a[index] : -1
                    readonly property bool hot: wheels.info.heat && at >= 0
                    width: (tiles.width - tiles.spacing) / 2
                    height: theme.em * 2.5
                    radius: theme.radiusMd
                    color: hot ? Qt.hsla(0.62 * (1 - at), 0.72, theme.dark ? 0.4 : 0.47, 1) : theme.raised
                    Text {
                        x: theme.em * 0.35
                        y: theme.em * 0.15
                        text: wheels.names[tile.index]
                        color: tile.hot ? Qt.rgba(1, 1, 1, 0.75) : theme.dimText
                        font.pointSize: theme.fontTiny
                    }
                    Text {
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: -theme.em * 0.1
                        text: wheels.main && wheels.main.t[tile.index] !== "" ? wheels.main.t[tile.index] : "–"
                        color: tile.hot ? "white" : theme.text
                        font.bold: true
                        font.features: { "tnum": 1 }
                    }
                    Item {  // main lap fill (not colored tiles), other laps marks
                        id: tileTrack
                        x: theme.em * 0.35
                        y: tile.height - theme.em * 0.4
                        width: tile.width - theme.em * 0.7
                        height: 3
                        Rectangle {
                            visible: !tile.hot && tile.at > 0
                            width: Math.max(tile.at, 0) * parent.width
                            height: parent.height
                            radius: 1.5
                            color: wheels.mainColor
                        }
                        Repeater {
                            model: wheels.entries.length
                            Rectangle {
                                required property int index
                                readonly property real at: wheels.marked(index) ? wheels.entries[index].a[tile.index] : -1
                                visible: at >= 0
                                x: at * tileTrack.width - width / 2
                                y: -3
                                width: 3
                                height: 9
                                radius: 1.5
                                color: wheels.laps[index] ? wheels.laps[index].color : "transparent"
                                border.width: 1
                                border.color: theme.base
                            }
                        }
                    }
                }
            }
        }
    }

    // Lateral & longitudinal G: dot of main lap on rings (1 G apart), other laps as small dots
    component GItem: ItemBase {
        id: gview

        readonly property real size: Math.min(width, theme.em * 9)
        readonly property real limit: {
            for (var i = 0; i < entries.length; i++) if (entries[i] && entries[i].ok) return entries[i].limit
            return 1
        }
        function dotX(entry) { return plot.width / 2 + Math.max(Math.min(entry.x, 1), -1) * plot.width / 2 }
        function dotY(entry) { return plot.height / 2 - Math.max(Math.min(entry.y, 1), -1) * plot.height / 2 }

        implicitHeight: gLabel.height + theme.em * 0.3 + size
        Text {
            id: gLabel
            width: parent.width - gValue.width
            text: gview.info.title
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
        }
        Text {
            id: gValue
            anchors.right: parent.right
            anchors.baseline: gLabel.baseline
            text: gview.main ? (Math.sqrt(gview.main.x * gview.main.x + gview.main.y * gview.main.y) * gview.limit).toFixed(1).replace(".", theme.decimalPoint) + " G" : "–"
            color: theme.text
            font.bold: true
            font.features: { "tnum": 1 }
        }
        Item {
            id: plot
            x: (parent.width - width) / 2
            y: gLabel.height + theme.em * 0.3
            width: gview.size
            height: width
            Repeater {
                model: Math.max(Math.round(gview.limit), 1)
                Rectangle {
                    required property int index
                    readonly property real ringRadius: (index + 1) / gview.limit * plot.width / 2
                    x: plot.width / 2 - ringRadius
                    y: plot.height / 2 - ringRadius
                    width: ringRadius * 2
                    height: width
                    radius: ringRadius
                    color: index === 0 ? Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.04) : "transparent"
                    border.width: 1
                    border.color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.15)
                }
            }
            Rectangle { x: 0; y: plot.height / 2; width: plot.width; height: 1; color: theme.text; opacity: 0.1 }
            Rectangle { x: plot.width / 2; y: 0; width: 1; height: plot.height; color: theme.text; opacity: 0.1 }
            Repeater {
                model: gview.entries.length
                Rectangle {
                    required property int index
                    visible: gview.marked(index)
                    width: theme.em * 0.5
                    height: width
                    radius: width / 2
                    x: visible ? gview.dotX(gview.entries[index]) - width / 2 : 0
                    y: visible ? gview.dotY(gview.entries[index]) - height / 2 : 0
                    color: gview.laps[index] ? gview.laps[index].color : "transparent"
                    opacity: 0.8
                }
            }
            Rectangle {
                visible: gview.main !== null
                width: theme.em * 0.85
                height: width
                radius: width / 2
                x: gview.main ? gview.dotX(gview.main) - width / 2 : 0
                y: gview.main ? gview.dotY(gview.main) - height / 2 : 0
                color: gview.mainColor
                border.width: 2
                border.color: theme.base
            }
        }
    }
}
