import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Between chart markers A & B: time taken by each lap (gap to reference), min / max / mean of shown channels
Item {
    id: root
    property var chart
    readonly property bool hasRange: chart ? chart.hasRange : false
    property var stats: ({})
    property bool stale: false  // markers or laps changed while tab hidden

    function update() {
        if (!visible) { stale = true; return }  // tab kept hidden: refreshed when shown again
        stale = false
        stats = hasRange ? backend.rangeStats(chart.markerA, chart.markerB) : ({})
    }

    onHasRangeChanged: update()
    onVisibleChanged: if (visible && stale) update()
    Component.onCompleted: { stale = true; update() }  // tab created when first shown
    Connections {
        target: root.chart
        function onMarkerAChanged() { root.update() }
        function onMarkerBChanged() { root.update() }
    }
    Connections {
        target: backend
        function onChartChanged() { root.update() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.em * 0.5

        Text {
            visible: !root.hasRange
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18n.tr("Set markers A and B on charts (right-click, or A / B keys at cursor) to compare laps between them.")
            color: theme.dimText
        }

        RowLayout {
            visible: root.hasRange
            Layout.fillWidth: true
            Text {
                text: root.stats.title || ""
                color: theme.text
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            TpButton {
                text: i18n.tr("Zoom")
                flat: true
                implicitHeight: theme.em * 1.8
                onClicked: root.chart.zoomRange([Math.min(root.chart.markerA, root.chart.markerB),
                                                 Math.max(root.chart.markerA, root.chart.markerB)], 0.03)
            }
            TpButton {
                text: i18n.tr("Clear")
                flat: true
                implicitHeight: theme.em * 1.8
                onClicked: root.chart.clearMarkers()
            }
        }

        // Time of each lap
        Repeater {
            model: root.hasRange ? (root.stats.laps || []) : []
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.em * 0.5
                Rectangle { implicitWidth: theme.em * 0.6; implicitHeight: implicitWidth; radius: implicitWidth / 2; color: modelData.color }
                Text { text: modelData.label; color: theme.text; Layout.fillWidth: true; elide: Text.ElideRight }
                Text { text: modelData.distance; color: theme.dimText; font.pointSize: theme.fontPoint * 0.8; font.features: { "tnum": 1 } }
                Text { text: modelData.time; color: theme.text; font.weight: Font.DemiBold; font.features: { "tnum": 1 } }
                Text {
                    text: modelData.gap
                    Layout.preferredWidth: theme.em * 4.5
                    horizontalAlignment: Text.AlignRight
                    color: modelData.gap.charAt(0) === "+" ? theme.loss : modelData.gap !== "" ? theme.gain : theme.dimText
                    font.features: { "tnum": 1 }
                }
            }
        }

        Text {
            visible: root.hasRange && (root.stats.channels || []).length > 0
            text: i18n.tr("Min / max / mean")
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.85
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.hasRange
            clip: true
            spacing: theme.em * 0.3
            model: root.stats.channels || []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            delegate: Column {
                width: ListView.view.width
                Text { text: modelData.title; color: theme.text; font.weight: Font.DemiBold; font.pointSize: theme.fontPoint * 0.9 }
                Repeater {
                    model: modelData.cells
                    Text {
                        leftPadding: theme.em * 0.6
                        text: modelData.text
                        color: modelData.color
                        font.pointSize: theme.fontPoint * 0.85
                        font.features: { "tnum": 1 }
                    }
                }
            }
        }
    }
}
