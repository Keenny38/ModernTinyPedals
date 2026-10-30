import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Synthesis band under lap chips (charts & simple view): total gap of the compared lap to the reference lap and the
// corners where it loses most time with their likely cause (corner table coaching, built by the backend). Click a
// corner: charts zoom on it; ‹ › (or { } keys on charts) step through them, "1/3" tells which one is shown.
// One row of fixed height while laps are shown (charts never jump when a lap is compared or not).
Item {
    id: band
    property var chart  // TraceChart: summary, lost corner shown, zoom
    readonly property var summary: chart ? chart.summary : ({})
    readonly property var corners: summary.corners || []
    readonly property bool compared: summary.lap !== undefined
    readonly property string hint: i18n.tr("Shift+[ ]: previous / next corner where time is lost")

    implicitHeight: Math.round(theme.controlHeightSm)
    height: chart && chart.legendLaps.length > 0 ? implicitHeight : 0
    visible: height > 0
    clip: true

    RowLayout {
        anchors.fill: parent
        spacing: theme.space3

        // Compared lap against reference lap, total gap (sign tells, color repeats it)
        Text {
            visible: band.compared && band.width > theme.em * 34  // content-tuned: corners keep the room when narrow
            text: band.compared ? i18n.tr("%1 vs %2").arg(band.summary.lap).arg(band.summary.reference) : ""
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
            Layout.maximumWidth: theme.em * 11
        }
        Text {
            objectName: "summaryGap"
            visible: band.compared
            text: band.summary.gap || ""
            textFormat: Text.PlainText
            color: band.summary.tone ? theme.tone(band.summary.tone) : theme.text
            font.pointSize: theme.fontSmall
            font.weight: Font.Bold
            font.features: { "tnum": 1 }
        }
        Text {
            visible: band.compared && band.corners.length === 0
            text: i18n.tr("No corner where time is lost")
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        // Worst corners, worst first: name, time lost, likely cause (all causes in tooltip)
        Repeater {
            model: band.corners
            AbstractButton {
                id: lossChip
                required property var modelData
                required property int index
                readonly property bool current: band.chart && band.chart.lostIndex === index
                objectName: "summaryCorner"
                Layout.fillWidth: true
                Layout.maximumWidth: implicitWidth
                Layout.minimumWidth: Math.min(implicitWidth, theme.em * 4)
                implicitHeight: Math.round(theme.chipHeight)
                implicitWidth: chipText.implicitWidth + theme.space5
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label + " " + modelData.loss + ": " + modelData.causes.join(", ")
                ToolTip.visible: hovered || visualFocus
                ToolTip.delay: theme.tipDelay
                ToolTip.text: modelData.label + " " + modelData.loss + "\n" + modelData.causes.join("\n") + "\n" + band.hint
                Keys.onReturnPressed: animateClick()
                Keys.onEnterPressed: animateClick()
                Keys.onShortcutOverride: function(event) {
                    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) event.accepted = true
                }
                onClicked: band.chart.showLost(index)
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                background: Rectangle {
                    radius: height / 2
                    color: theme.rowColor(lossChip.hovered, lossChip.current)
                    border.width: 1
                    border.color: lossChip.current ? theme.accent : lossChip.hovered ? theme.strokeStrong : theme.border
                    FocusRing { visible: lossChip.visualFocus }
                }
                contentItem: Text {
                    id: chipText
                    // Number (as on the simple view delta line), corner & loss in bold (escaped: corner names never
                    // markup), first cause after
                    function esc(text) { return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
                    text: (lossChip.index + 1) + "&nbsp;&nbsp;<b>" + esc(lossChip.modelData.label) + "</b> <font color='" + theme.loss + "'><b>"
                          + esc(lossChip.modelData.loss) + "</b></font> " + esc(lossChip.modelData.causes[0] || "")
                    textFormat: Text.StyledText
                    color: theme.text
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: theme.space3
                    rightPadding: theme.space3
                }
            }
        }
        Item { Layout.fillWidth: true; visible: band.corners.length > 0 }

        // Step through lost corners: shown one of all (1/3)
        TpButton {
            objectName: "previousLost"
            visible: band.corners.length > 1
            glyph: ""  // chevron left
            fallback: "‹"
            flat: true
            size: "xs"
            tip: i18n.tr("Previous corner where time is lost") + " (Shift+[)"
            onClicked: band.chart.stepLost(-1)
        }
        Text {
            objectName: "lostPosition"
            visible: band.corners.length > 0
            text: (band.chart && band.chart.lostIndex >= 0 ? band.chart.lostIndex + 1 : "—") + "/" + band.corners.length
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            font.features: { "tnum": 1 }
            Accessible.name: i18n.tr("Corner where time is lost") + " " + text
        }
        TpButton {
            objectName: "nextLost"
            visible: band.corners.length > 0
            glyph: ""  // chevron right
            fallback: "›"
            flat: true
            size: "xs"
            tip: i18n.tr("Next corner where time is lost") + " (Shift+])"
            onClicked: band.chart.stepLost(1)
        }

        // Nothing compared: how to see where time is lost
        Text {
            visible: !band.compared
            text: i18n.tr("Compare a lap with the reference lap to see where time is lost")
            textFormat: Text.PlainText
            color: theme.dimText
            font.pointSize: theme.fontSmall
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        TpButton {
            objectName: "bandAnalyze"
            visible: !band.compared
            text: i18n.tr("Analyze My Last Lap")
            flat: true
            size: "sm"
            tip: i18n.tr("Best lap against last lap, Corners tool opened on the corner where most time is lost")
            onClicked: backend.analyzeLastLap()
        }
    }
}
