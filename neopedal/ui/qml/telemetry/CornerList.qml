import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Corner by corner comparison of a compared lap with reference lap, click a corner to zoom charts on it
// Time: positive = compared lap slower. Braking: positive = brakes later. Full throttle: negative = earlier.
// Ideal lap: fastest lap in every corner & straight among shown clean laps.
// Coaching: corners where compared lap loses most time, with likely causes (click: zoom on corner).
// Keys: Tab reaches coaching rows & the corner list (arrows move, Enter / Space zoom on the corner, Esc: charts).
Item {
    id: root
    property var chart
    // Rows: backend model (rows kept while their corner stays: only changed values update their items)
    readonly property bool hasRows: cornerView.count > 0
    readonly property real maxDelta: backend.cornerTable.maxDelta
    readonly property int selected: backend.selectedCorner  // also selected by clicking map corners
    readonly property var comparedLaps: backend.comparedLaps  // read once (list built by backend)
    readonly property var alignment: backend.charts.alignment
    onSelectedChanged: {  // corner selected on map: row shown
        var position = backend.cornerTable.position(selected)
        if (position >= 0) cornerView.positionViewAtIndex(position, ListView.Contain)
    }
    // Details tooltip: built once, shown text only while a row is hovered
    readonly property string detailsTip: [
        i18n.tr("Braking point of compared lap: positive = brakes later"),
        i18n.tr("Full throttle point of compared lap: negative = earlier"),
        i18n.tr("Seconds braking while turning: reference lap, compared lap"),
        i18n.tr("Seconds without throttle nor brake: reference lap, compared lap (red: more than reference)"),
        i18n.tr("Seconds with throttle & brake together: reference lap, compared lap (red: more than reference)"),
        i18n.tr("Speed at corner start & end: reference lap, compared lap"),
        i18n.tr("Gear at minimum speed, highest brake pressure: reference lap, compared lap"),
        i18n.tr("Fastest: lap with the best time in this corner (ideal lap)"),
    ].join("\n")

    // Backend tones: gain & loss in theme colors (colorblind safe when that style is on), others as given
    function tone(name, fallback) { return name === "loss" || name === "gain" ? theme.tone(name) : fallback }
    function showCorner(index) {
        backend.setSelectedCorner(index)
        var range = backend.cornerTable.range(index)
        if (range.length === 2 && root.chart) {
            var margin = (range[1] - range[0]) * 0.15
            root.chart.setView(range[0] - margin, range[1] + margin, true)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.space3

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            Text {
                text: i18n.tr("Corner detection")
                color: theme.dimText
                elide: Text.ElideRight
                Layout.maximumWidth: implicitWidth
                Layout.fillWidth: true
            }
            TpSlider {
                id: slider
                Layout.fillWidth: true
                Layout.minimumWidth: theme.em * 5
                from: 3; to: 40; stepSize: 1
                value: backend.cornerTable.hysteresis
                tip: i18n.tr("Speed drop & rise counted as a corner: lower finds more corners")
                function apply() {
                    applyTimer.stop()
                    if (Math.round(value) !== backend.cornerTable.hysteresis) backend.cornerTable.setHysteresis(Math.round(value))
                }
                // Corners found again once released, or once value stays a moment (dragging, arrow keys stay smooth)
                onMoved: applyTimer.restart()
                onPressedChanged: if (!pressed) apply()
                Timer { id: applyTimer; interval: 400; onTriggered: slider.apply() }
            }
            Text {
                text: Math.round(slider.value * backend.speedScale) + " " + backend.speedUnit
                color: theme.text
                font.features: { "tnum": 1 }
            }
        }

        // Compared lap & order
        RowLayout {
            Layout.fillWidth: true
            visible: root.hasRows
            spacing: theme.space3
            ComparedLapPicker {
                Layout.fillWidth: true
                laps: root.comparedLaps
                currentKey: backend.cornerTable.compareKey
                onPicked: function(key) { backend.cornerTable.setCompareKey(key) }
            }
            Item { Layout.fillWidth: true; visible: root.comparedLaps.length <= 1 }
            TpSegmented {
                name: i18n.tr("Order")
                options: [i18n.tr("Track order"), i18n.tr("Time lost")]
                currentIndex: backend.cornerTable.sort === "loss" ? 1 : 0
                onActivated: function(index) { backend.cornerTable.setSort(index === 1 ? "loss" : "track") }
            }
        }

        // Laps aligned on braking point of selected corner, corner report
        RowLayout {
            Layout.fillWidth: true
            visible: root.hasRows
            spacing: theme.space3
            TpButton {
                readonly property bool aligned: root.alignment.index !== undefined && root.alignment.index === root.selected
                text: "↔ " + i18n.tr("Align on Braking")
                flat: true
                size: "sm"
                enabled: root.selected >= 0 && root.comparedLaps.length > 0
                checked: aligned
                tip: i18n.tr("Shift laps along distance so their braking starts in selected corner line up with reference lap")
                onClicked: backend.charts.alignBraking(aligned ? -1 : root.selected)
            }
            Item { Layout.fillWidth: true }
            TpButton {
                glyph: ""  // export
                fallback: "⇪"
                text: i18n.tr("Report...")
                flat: true
                size: "sm"
                tip: i18n.tr("Export corner report: table, deltas, coaching notes & map (HTML or PDF)")
                onClicked: backend.exports.exportCornerReport()
            }
        }

        // Where compared lap loses most time
        Rectangle {
            id: coachCard
            visible: backend.cornerTable.coaching.length > 0
            Layout.fillWidth: true
            implicitHeight: coachColumn.implicitHeight + theme.space5
            radius: theme.radiusMd
            color: theme.tint(theme.loss, theme.dark ? "subtle" : 0.07)
            border.width: 1
            border.color: theme.tint(theme.loss, 0.35)
            ColumnLayout {
                id: coachColumn
                anchors.fill: parent
                anchors.margins: theme.space3
                spacing: theme.space1
                Text {
                    text: i18n.tr("Where time is lost") + (backend.cornerTable.coachingLap ? " · " + backend.cornerTable.coachingLap : "")
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontLabel
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Repeater {
                    model: backend.cornerTable.coaching
                    Rectangle {
                        id: tip
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: tipRow.implicitHeight + theme.space2
                        radius: theme.radiusSm
                        color: tipArea.pressed ? theme.border : tipArea.containsMouse ? theme.hover : "transparent"
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.label + " " + modelData.loss + ": " + modelData.causes.join(", ")
                        Keys.onSpacePressed: root.showCorner(modelData.index)
                        Keys.onReturnPressed: root.showCorner(modelData.index)
                        Keys.onEnterPressed: root.showCorner(modelData.index)
                        FocusRing { visible: tip.activeFocus }
                        RowLayout {
                            id: tipRow
                            anchors.fill: parent
                            anchors.leftMargin: theme.space2
                            anchors.rightMargin: theme.space2
                            spacing: theme.space3
                            Text {
                                Layout.alignment: Qt.AlignTop
                                Layout.preferredWidth: theme.em * 4.2
                                text: tip.modelData.label
                                color: theme.text
                                font.weight: Font.Bold
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.alignment: Qt.AlignTop
                                text: tip.modelData.loss
                                color: theme.loss
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: tip.modelData.causes.join(" · ")
                                color: theme.dimOn(tipArea.containsMouse ? theme.hover : coachCard.color)
                                font.pointSize: theme.fontSmall
                                wrapMode: Text.WordWrap
                            }
                        }
                        MouseArea {
                            id: tipArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.showCorner(tip.modelData.index)
                        }
                    }
                }
            }
        }

        // Header
        RowLayout {
            visible: root.hasRows
            Layout.fillWidth: true
            Layout.leftMargin: theme.space3
            Layout.rightMargin: theme.space3
            spacing: theme.space3
            TpHeaderCell { text: i18n.tr("Corner"); Layout.preferredWidth: theme.em * 6.5 }
            TpHeaderCell { text: i18n.tr("Time"); Layout.fillWidth: true }
            TpHeaderCell { text: i18n.tr("Min Speed"); align: Qt.AlignRight; Layout.preferredWidth: theme.em * 5.5 }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: cornerView
                objectName: "cornerList"
                anchors.fill: parent
                clip: true
                model: backend.cornerTable.model
                spacing: 2
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                activeFocusOnTab: true
                keyNavigationEnabled: true
                Accessible.role: Accessible.List
                Accessible.name: i18n.tr("Corners")
                function showCurrent() {
                    var item = currentItem
                    if (item && item.corner) root.showCorner(item.modelData.index)
                }
                Keys.onSpacePressed: showCurrent()
                Keys.onReturnPressed: showCurrent()
                Keys.onEnterPressed: showCurrent()
                Keys.onEscapePressed: if (root.chart) root.chart.forceActiveFocus()
                Keys.onShortcutOverride: function(event) {  // focused list takes its keys (charts shortcuts wait)
                    if ([Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Up, Qt.Key_Down].indexOf(event.key) >= 0)
                        event.accepted = true
                }
                delegate: TpListRow {
                    id: rowItem
                    required property var model
                    required property int index
                    readonly property var modelData: model  // row values (roles)
                    readonly property bool corner: modelData.kind === "corner"
                    width: ListView.view.width
                    height: corner ? rowContent.implicitHeight + theme.space4 : Math.round(theme.rowCompact)
                    hovered: area.containsMouse && corner
                    pressed: area.pressed && corner
                    selected: root.selected === modelData.index && corner
                    emphasized: !corner  // totals & ideal lap
                    tint: corner ? theme.accent : theme.text
                    Accessible.role: Accessible.ListItem
                    Accessible.name: modelData.label + " " + modelData.time

                    FocusRing { visible: rowItem.ListView.isCurrentItem && cornerView.activeFocus }

                    // Under details: their tooltips get hover, clicks reach this area
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: rowItem.corner
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { cornerView.currentIndex = rowItem.index; root.showCorner(rowItem.modelData.index) }
                    }

                    ColumnLayout {
                        id: rowContent
                        anchors.fill: parent
                        anchors.leftMargin: theme.space3
                        anchors.rightMargin: theme.space3
                        anchors.topMargin: 2
                        anchors.bottomMargin: 2
                        spacing: 0

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: theme.em * 1.6
                            spacing: theme.space3
                            Row {
                                Layout.preferredWidth: theme.em * 6.5
                                spacing: theme.space3
                                Text {
                                    id: cornerLabel
                                    text: rowItem.modelData.label
                                    color: rowItem.modelData.kind === "ideal" ? theme.purple : theme.text
                                    font.weight: rowItem.modelData.kind === "total" || rowItem.modelData.kind === "ideal" ? Font.Bold : Font.DemiBold
                                }
                                Text {
                                    text: rowItem.modelData.apex
                                    color: rowItem.modelData.kind === "ideal" ? theme.purple : theme.dimOn(rowItem.color)
                                    font.pointSize: theme.fontCaption
                                    anchors.baseline: cornerLabel.baseline
                                }
                            }
                            // Time delta, with a bar centered on zero (sign in text too)
                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Rectangle {
                                    readonly property real half: parent.width * 0.32
                                    readonly property real amount: Math.min(Math.abs(rowItem.modelData.bar) / root.maxDelta, 1) * half
                                    visible: rowItem.corner && rowItem.modelData.bar !== 0
                                    height: theme.em * 0.5
                                    radius: height / 2
                                    anchors.verticalCenter: parent.verticalCenter
                                    x: rowItem.modelData.bar > 0 ? parent.width - half : parent.width - half - amount
                                    width: amount
                                    color: theme.tint(root.tone(rowItem.modelData.timeColor, theme.dimText), 0.55)
                                }
                                Rectangle {
                                    visible: rowItem.corner
                                    x: parent.width - parent.width * 0.32
                                    width: 1
                                    height: parent.height * 0.6
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: theme.tint(theme.dimText, 0.5)
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: rowItem.modelData.time
                                    color: root.tone(rowItem.modelData.timeColor, theme.text)
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                            Text {
                                visible: rowItem.corner || rowItem.modelData.kind === "ideal"
                                Layout.preferredWidth: theme.em * 5.5
                                horizontalAlignment: Text.AlignRight
                                text: rowItem.modelData.speed || ""
                                color: rowItem.modelData.kind === "ideal" ? theme.purple : root.tone(rowItem.modelData.speedColor, theme.text)
                                font.features: { "tnum": 1 }
                            }
                        }

                        // Driving details: braking & full throttle points, trail braking, coasting, overlap,
                        // entry & exit speed, gear at apex, brake pressure, fastest lap here
                        Text {
                            id: details
                            visible: rowItem.corner
                            Layout.fillWidth: true
                            textFormat: Text.StyledText
                            wrapMode: Text.WordWrap
                            color: theme.dimOn(rowItem.color)
                            font.pointSize: theme.fontCaption
                            font.features: { "tnum": 1 }
                            function value(text, color) {
                                return "<font color='" + root.tone(color, theme.text) + "'>" + text.replace(/ /g, "&nbsp;") + "</font>"
                            }
                            text: !rowItem.corner ? "" : [
                                i18n.tr("Braking") + " " + value(rowItem.modelData.brake),
                                i18n.tr("Full Throttle") + " " + value(rowItem.modelData.throttle),
                                i18n.tr("Trail Braking") + " " + value(rowItem.modelData.trail),
                                i18n.tr("Coasting") + " " + value(rowItem.modelData.coast, rowItem.modelData.coastColor),
                                i18n.tr("Overlap") + " " + value(rowItem.modelData.overlap, rowItem.modelData.overlapColor),
                                i18n.tr("Entry") + " " + value(rowItem.modelData.entry, rowItem.modelData.entryColor),
                                i18n.tr("Exit") + " " + value(rowItem.modelData.exit, rowItem.modelData.exitColor),
                                i18n.tr("Gear") + " " + value(rowItem.modelData.gear),
                                i18n.tr("Brake Pressure") + " " + value(rowItem.modelData.peakBrake),
                            ].concat(rowItem.modelData.best ? [i18n.tr("Fastest") + " " + value(rowItem.modelData.best, "")] : []).join(" &nbsp; ")
                            ToolTip.visible: detailArea.containsMouse
                            ToolTip.delay: theme.tipDelay
                            ToolTip.text: detailArea.containsMouse ? root.detailsTip : ""
                            MouseArea { id: detailArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                }
            }
            // Laps being read: spinner (never "no corner" meanwhile), else why there is no corner
            TpStateView {
                objectName: "cornerState"
                anchors.centerIn: parent
                compact: true
                loading: !root.hasRows && backend.loading
                empty: !root.hasRows && !backend.loading
                loadingText: i18n.tr("Reading laps...")
                glyph: ""  // map pin
                title: backend.legend.length === 0 ? i18n.tr("Select recorded laps to compare.")
                    : i18n.tr("No corner found: speed not recorded.")
            }
        }
    }
}
