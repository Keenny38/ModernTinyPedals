import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Between chart markers A & B: time taken by each lap (gap to reference), min / max / mean of shown channels.
// Laps & channels scroll together (many laps never squeeze the channels away)
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

    // No passage yet: how to set one
    TpStateView {
        anchors.centerIn: parent
        compact: true
        empty: !root.hasRange
        glyph: ""  // flag
        text: i18n.tr("Set markers A and B on charts (right-click, or A / B keys at cursor) to compare laps between them.")
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: theme.space3
        visible: root.hasRange

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space2
            Text {
                text: root.stats.title || ""
                textFormat: Text.PlainText
                color: theme.text
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            TpButton {
                text: i18n.tr("Zoom")
                flat: true
                size: "sm"
                tip: i18n.tr("Zoom Between Markers")
                onClicked: root.chart.zoomRange([Math.min(root.chart.markerA, root.chart.markerB),
                                                 Math.max(root.chart.markerA, root.chart.markerB)], 0.03)
            }
            TpButton {
                text: i18n.tr("Clear")
                flat: true
                size: "sm"
                tip: i18n.tr("Clear Markers")
                onClicked: root.chart.clearMarkers()
            }
        }

        ListView {
            id: channelList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: theme.space2
            model: root.hasRange ? (root.stats.channels || []) : []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            // Time of each lap, then channel values
            header: Column {
                width: ListView.view.width
                spacing: theme.space2
                bottomPadding: theme.space3
                Repeater {
                    model: root.hasRange ? (root.stats.laps || []) : []
                    RowLayout {
                        required property var modelData
                        width: parent.width
                        spacing: theme.space3
                        ColorDot { size: Math.round(theme.em * 0.6); color: modelData.color }
                        Text { text: modelData.label; color: theme.text; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
                        TpText { role: "caption"; tabular: true; text: modelData.distance; elide: Text.ElideNone }
                        Text { text: modelData.time; color: theme.text; font.weight: Font.DemiBold; font.features: { "tnum": 1 }; textFormat: Text.PlainText }
                        Text {
                            text: modelData.gap
                            textFormat: Text.PlainText
                            Layout.preferredWidth: theme.em * 4.5
                            horizontalAlignment: Text.AlignRight
                            color: modelData.gap.charAt(0) === "+" ? theme.loss : modelData.gap !== "" ? theme.gain : theme.dimText
                            font.features: { "tnum": 1 }
                        }
                    }
                }
                TpSectionLabel {
                    visible: (root.stats.channels || []).length > 0
                    width: parent.width
                    topPadding: theme.space3
                    text: i18n.tr("Min / max / mean")
                }
            }
            delegate: Column {
                required property var modelData
                width: ListView.view.width
                TpText {
                    width: parent.width
                    role: "label"
                    text: modelData.title
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Repeater {
                    model: modelData.cells
                    Text {
                        required property var modelData
                        width: parent.width
                        leftPadding: theme.space4
                        text: modelData.text
                        textFormat: Text.PlainText
                        color: modelData.color
                        font.pointSize: theme.fontSmall
                        font.features: { "tnum": 1 }
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
