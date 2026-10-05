import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Corner by corner comparison of a compared lap with reference lap, click a corner to zoom charts on it
// Time: positive = compared lap slower. Braking: positive = brakes later. Full throttle: negative = earlier.
// Ideal lap: fastest lap in every corner & straight among shown clean laps.
// Coaching: corners where compared lap loses most time, with likely causes (click: zoom on corner).
Item {
    id: root
    property var chart
    readonly property var rows: backend.corners
    readonly property real maxDelta: rows.reduce(function(top, row) {
        return row.kind === "corner" ? Math.max(top, Math.abs(row.bar)) : top }, 0.05)
    readonly property int selected: backend.selectedCorner  // also selected by clicking map corners
    onSelectedChanged: {  // corner selected on map: row shown
        for (var i = 0; i < rows.length; i++)
            if (rows[i].index === selected && rows[i].kind === "corner") { cornerView.positionViewAtIndex(i, ListView.Contain); break }
    }

    function tone(name, fallback) { return name === "loss" ? theme.loss : name === "gain" ? theme.gain : fallback }
    function showCorner(index) {
        backend.setSelectedCorner(index)
        var range = backend.cornerRange(index)
        if (range.length === 2 && root.chart) {
            var margin = (range[1] - range[0]) * 0.15
            root.chart.setView(range[0] - margin, range[1] + margin, true)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.4

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.5
            Text { text: i18n.tr("Corner detection"); color: theme.dimText }
            Slider {
                id: slider
                Layout.fillWidth: true
                from: 3; to: 40; stepSize: 1
                value: backend.hysteresis
                // Corners found again once released (dragging stays smooth)
                onPressedChanged: if (!pressed && Math.round(value) !== backend.hysteresis) backend.setHysteresis(Math.round(value))
                ToolTip.visible: hovered
                ToolTip.text: i18n.tr("Speed drop & rise counted as a corner: lower finds more corners")
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
            visible: root.rows.length > 0
            spacing: theme.em * 0.4
            Flow {
                Layout.fillWidth: true
                spacing: theme.em * 0.3
                visible: backend.comparedLaps.length > 1
                Text { text: i18n.tr("Compared:"); color: theme.dimText; height: theme.em * 1.8; verticalAlignment: Text.AlignVCenter }
                Repeater {
                    model: backend.comparedLaps
                    TpButton {
                        text: modelData.label
                        flat: true
                        implicitHeight: theme.em * 1.8
                        checked: backend.compareKey === modelData.key
                        onClicked: backend.setCompareKey(modelData.key)
                    }
                }
            }
            Item { Layout.fillWidth: true; visible: backend.comparedLaps.length <= 1 }
            TpSegmented {
                options: [i18n.tr("Track order"), i18n.tr("Time lost")]
                currentIndex: backend.cornerSort === "loss" ? 1 : 0
                onActivated: function(index) { backend.setCornerSort(index === 1 ? "loss" : "track") }
            }
        }

        // Where compared lap loses most time
        Rectangle {
            visible: backend.coaching.length > 0
            Layout.fillWidth: true
            implicitHeight: coachColumn.implicitHeight + theme.em * 0.8
            radius: theme.em * 0.5
            color: Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, theme.dark ? 0.1 : 0.07)
            border.width: 1
            border.color: Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.35)
            ColumnLayout {
                id: coachColumn
                anchors.fill: parent
                anchors.margins: theme.em * 0.4
                spacing: theme.em * 0.15
                Text {
                    text: i18n.tr("Where time is lost") + (backend.coachingLap ? " · " + backend.coachingLap : "")
                    color: theme.text
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontPoint * 0.9
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Repeater {
                    model: backend.coaching
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: tipRow.implicitHeight + theme.em * 0.3
                        radius: theme.em * 0.35
                        color: tipArea.containsMouse ? theme.hover : "transparent"
                        RowLayout {
                            id: tipRow
                            anchors.fill: parent
                            anchors.leftMargin: theme.em * 0.3
                            anchors.rightMargin: theme.em * 0.3
                            spacing: theme.em * 0.5
                            Text {
                                Layout.alignment: Qt.AlignTop
                                Layout.preferredWidth: theme.em * 4.2
                                text: modelData.label
                                color: theme.text
                                font.weight: Font.Bold
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.alignment: Qt.AlignTop
                                text: modelData.loss
                                color: theme.loss
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.causes.join(" · ")
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.82
                                wrapMode: Text.WordWrap
                            }
                        }
                        MouseArea {
                            id: tipArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.showCorner(modelData.index)
                        }
                    }
                }
            }
        }

        Text {
            visible: root.rows.length === 0
            text: backend.legend.length === 0 ? i18n.tr("Select recorded laps to compare.")
                : i18n.tr("No corner found: speed not recorded.")
            color: theme.dimText
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }

        // Header
        RowLayout {
            visible: root.rows.length > 0
            Layout.fillWidth: true
            Layout.leftMargin: theme.em * 0.5
            Layout.rightMargin: theme.em * 0.5
            spacing: theme.em * 0.5
            Text { text: i18n.tr("Corner"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.85; Layout.preferredWidth: theme.em * 6.5 }
            Text { text: i18n.tr("Time"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.85; Layout.fillWidth: true }
            Text {
                text: i18n.tr("Min Speed")
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.85
                Layout.preferredWidth: theme.em * 5.5
                horizontalAlignment: Text.AlignRight
            }
        }

        ListView {
            id: cornerView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.rows
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                id: rowItem
                readonly property bool corner: modelData.kind === "corner"
                width: ListView.view.width
                height: corner ? rowContent.implicitHeight + theme.em * 0.6 : theme.em * 2.2
                radius: theme.em * 0.4
                color: root.selected === modelData.index && corner ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.16)
                     : area.containsMouse && corner ? theme.hover
                     : corner ? "transparent" : (theme.dark ? Qt.lighter(theme.base, 1.15) : theme.alternate)
                Behavior on color { ColorAnimation { duration: 120 } }

                // Under details: their tooltips get hover, clicks reach this area
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: rowItem.corner
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.showCorner(modelData.index)
                }

                ColumnLayout {
                    id: rowContent
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.5
                    anchors.rightMargin: theme.em * 0.5
                    anchors.topMargin: 2
                    anchors.bottomMargin: 2
                    spacing: 0

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: theme.em * 1.6
                        spacing: theme.em * 0.5
                        Row {
                            Layout.preferredWidth: theme.em * 6.5
                            spacing: theme.em * 0.4
                            Text {
                                id: cornerLabel
                                text: modelData.label
                                color: modelData.kind === "ideal" ? theme.purple : theme.text
                                font.weight: modelData.kind === "total" || modelData.kind === "ideal" ? Font.Bold : Font.DemiBold
                            }
                            Text {
                                text: modelData.apex
                                color: modelData.kind === "ideal" ? theme.purple : theme.dimText
                                font.pointSize: theme.fontPoint * 0.8
                                anchors.baseline: cornerLabel.baseline
                            }
                        }
                        // Time delta, with a bar centered on zero
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Rectangle {
                                readonly property real half: parent.width * 0.32
                                readonly property real amount: Math.min(Math.abs(modelData.bar) / root.maxDelta, 1) * half
                                visible: rowItem.corner && modelData.bar !== 0
                                height: theme.em * 0.5
                                radius: height / 2
                                anchors.verticalCenter: parent.verticalCenter
                                x: modelData.bar > 0 ? parent.width - half : parent.width - half - amount
                                width: amount
                                color: root.tone(modelData.timeColor, theme.dimText)
                                opacity: 0.55
                            }
                            Rectangle {
                                visible: rowItem.corner
                                x: parent.width - parent.width * 0.32
                                width: 1
                                height: parent.height * 0.6
                                anchors.verticalCenter: parent.verticalCenter
                                color: theme.dimText
                                opacity: 0.5
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.time
                                color: root.tone(modelData.timeColor, theme.text)
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                        }
                        Text {
                            visible: rowItem.corner || modelData.kind === "ideal"
                            Layout.preferredWidth: theme.em * 5.5
                            horizontalAlignment: Text.AlignRight
                            text: modelData.speed || ""
                            color: modelData.kind === "ideal" ? theme.purple : root.tone(modelData.speedColor, theme.text)
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
                        color: theme.dimText
                        font.pointSize: theme.fontPoint * 0.78
                        font.features: { "tnum": 1 }
                        function value(text, color) {
                            return "<font color='" + root.tone(color, theme.text) + "'>" + text.replace(/ /g, "&nbsp;") + "</font>"
                        }
                        text: !rowItem.corner ? "" : [
                            i18n.tr("Braking") + " " + value(modelData.brake),
                            i18n.tr("Full Throttle") + " " + value(modelData.throttle),
                            i18n.tr("Trail Braking") + " " + value(modelData.trail),
                            i18n.tr("Coasting") + " " + value(modelData.coast, modelData.coastColor),
                            i18n.tr("Overlap") + " " + value(modelData.overlap, modelData.overlapColor),
                            i18n.tr("Entry") + " " + value(modelData.entry, modelData.entryColor),
                            i18n.tr("Exit") + " " + value(modelData.exit, modelData.exitColor),
                            i18n.tr("Gear") + " " + value(modelData.gear),
                            i18n.tr("Brake Pressure") + " " + value(modelData.peakBrake),
                        ].concat(modelData.best ? [i18n.tr("Fastest") + " " + value(modelData.best, "")] : []).join(" &nbsp; ")
                        ToolTip.visible: detailArea.containsMouse
                        ToolTip.delay: 500
                        ToolTip.text: [
                            i18n.tr("Braking point of compared lap: positive = brakes later"),
                            i18n.tr("Full throttle point of compared lap: negative = earlier"),
                            i18n.tr("Seconds braking while turning: reference lap, compared lap"),
                            i18n.tr("Seconds without throttle nor brake: reference lap, compared lap (red: more than reference)"),
                            i18n.tr("Seconds with throttle & brake together: reference lap, compared lap (red: more than reference)"),
                            i18n.tr("Speed at corner start & end: reference lap, compared lap"),
                            i18n.tr("Gear at minimum speed, highest brake pressure: reference lap, compared lap"),
                            i18n.tr("Fastest: lap with the best time in this corner (ideal lap)"),
                        ].join("\n")
                        MouseArea { id: detailArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                }
            }
        }
    }
}
