import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Corner by corner comparison of first compared lap with reference lap, click a corner to zoom charts on it
// Time: positive = compared lap slower. Braking: positive = brakes later. Full throttle: negative = earlier.
Item {
    id: root
    property var chart
    readonly property var rows: backend.corners
    readonly property real maxDelta: rows.reduce(function(top, row) {
        return row.kind === "corner" ? Math.max(top, Math.abs(row.bar)) : top }, 0.05)
    property int selected: -1

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
                onMoved: backend.setHysteresis(value)
                ToolTip.visible: hovered
                ToolTip.text: i18n.tr("Speed drop & rise counted as a corner: lower finds more corners")
            }
            Text { text: Math.round(slider.value) + " km/h"; color: theme.text; font.features: { "tnum": 1 } }
        }

        Text {
            visible: root.rows.length === 0
            text: i18n.tr("No corner found: speed not recorded.")
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
                    onClicked: {
                        root.selected = modelData.index
                        var range = backend.cornerRange(modelData.index)
                        if (range.length === 2 && root.chart) {
                            var margin = (range[1] - range[0]) * 0.15
                            root.chart.setView(range[0] - margin, range[1] + margin, true)
                        }
                    }
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
                                color: theme.text
                                font.weight: modelData.kind === "total" ? Font.Bold : Font.DemiBold
                            }
                            Text {
                                text: modelData.apex
                                color: theme.dimText
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
                                color: modelData.timeColor || theme.dimText
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
                                color: modelData.timeColor || theme.text
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                        }
                        Text {
                            visible: rowItem.corner
                            Layout.preferredWidth: theme.em * 5.5
                            horizontalAlignment: Text.AlignRight
                            text: modelData.speed || ""
                            color: modelData.speedColor || theme.text
                            font.features: { "tnum": 1 }
                        }
                    }

                    // Driving details: braking & full throttle points, trail braking, coasting, overlap
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
                            return "<font color='" + (color || theme.text) + "'>" + text + "</font>"
                        }
                        text: !rowItem.corner ? "" : [
                            i18n.tr("Braking") + " " + value(modelData.brake),
                            i18n.tr("Full Throttle") + " " + value(modelData.throttle),
                            i18n.tr("Trail Braking") + " " + value(modelData.trail),
                            i18n.tr("Coasting") + " " + value(modelData.coast, modelData.coastColor),
                            i18n.tr("Overlap") + " " + value(modelData.overlap, modelData.overlapColor),
                        ].join(" &nbsp; ")
                        ToolTip.visible: detailArea.containsMouse
                        ToolTip.delay: 500
                        ToolTip.text: [
                            i18n.tr("Braking point of compared lap: positive = brakes later"),
                            i18n.tr("Full throttle point of compared lap: negative = earlier"),
                            i18n.tr("Seconds braking while turning: reference lap, compared lap"),
                            i18n.tr("Seconds without throttle nor brake: reference lap, compared lap (red: more than reference)"),
                            i18n.tr("Seconds with throttle & brake together: reference lap, compared lap (red: more than reference)"),
                        ].join("\n")
                        MouseArea { id: detailArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                }
            }
        }
    }
}
