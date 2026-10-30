import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Lap history of a car (laps seen while the page watched): lap time & sectors colored (purple ◆: best of class,
// green ●: personal best, yellow: slower), pit lane lap, energy used, class place at lap end. Newest first.
// Sized to the window (smaller windows: the list scrolls).
TpPopup {
    id: popup
    modal: true
    anchors.centerIn: parent
    // closed at once (not after the exit transition): a lap answer meanwhile must not open it again
    onAboutToHide: if (backend.lapsOpen) backend.showLaps(-1)
    Connections {
        target: backend
        function onLapsChanged() {
            if (backend.lapsOpen && !popup.opened) popup.open()
            else if (!backend.lapsOpen && popup.visible) popup.close()
        }
    }

    readonly property real windowWidth: parent ? parent.width : theme.em * 40
    readonly property real windowHeight: parent ? parent.height : theme.em * 32

    // Marks besides colors (colorblind): ◆ best of class, ● personal best
    // Record mark right of the time, as every page (TpLapTime): ◆ best of class first, ● personal best
    function mark(tone) { return tone === "fastest" ? " ◆" : tone === "gain" ? " ●" : "" }

    component Cell: Text {
        textFormat: Text.PlainText  // text of each use: names & values, never markup
        property string tint: ""
        Layout.preferredWidth: theme.em * 4.6
        horizontalAlignment: Text.AlignRight
        color: tint !== "" ? theme.tone(tint) : theme.text
        font.features: { "tnum": 1 }
        elide: Text.ElideRight
    }
    component Head: TpHeaderCell {
        Layout.preferredWidth: theme.em * 4.6
        align: Qt.AlignRight
    }

    contentItem: LazyPane {
        shown: popup.visible
        sourceComponent: ColumnLayout {
            spacing: theme.space3
            TpCardHeader {
                level: "popup"
                glyph: ""  // stopwatch
                title: i18n.tr("Lap History") + "  ·  " + backend.lapsTitle
                closable: true
                onClosed: popup.close()
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.rightMargin: theme.space5
                spacing: theme.space3
                Head { text: i18n.tr("Lap"); Layout.preferredWidth: theme.em * 3; align: Qt.AlignLeft }
                Head { text: i18n.tr("Time"); Layout.preferredWidth: theme.em * 5.4 }
                Head { text: "S1" }
                Head { text: "S2" }
                Head { text: "S3" }
                Head { text: i18n.tr("Energy") }
                Head { text: i18n.tr("Class"); Layout.preferredWidth: theme.em * 3.4 }
            }
            ListView {
                id: laps
                objectName: "lapList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(theme.em * 8, Math.min(theme.em * 26, popup.windowHeight - theme.em * 10))
                Layout.preferredWidth: Math.min(theme.em * 36, popup.windowWidth - theme.em * 4)
                clip: true
                model: backend.lapRows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Item {
                    id: lapRow
                    required property int index
                    required property int lap
                    required property string time
                    required property string s1
                    required property string s2
                    required property string s3
                    required property string timeTone
                    required property string s1Tone
                    required property string s2Tone
                    required property string s3Tone
                    required property bool pit
                    required property string energy
                    required property int position
                    width: ListView.view.width - (laps.ScrollBar.vertical.visible ? laps.ScrollBar.vertical.width : 0)
                    height: Math.round(theme.rowCompact)
                    TpListRow { anchors.fill: parent; striped: lapRow.index % 2 === 1 }
                    RowLayout {
                        anchors.fill: parent
                        spacing: theme.space3
                        Text {
                            Layout.preferredWidth: theme.em * 3
                            leftPadding: theme.space2
                            text: lapRow.lap + (lapRow.pit ? "  P" : "")
                            textFormat: Text.PlainText
                            color: lapRow.pit ? theme.warning : theme.dimText
                            font.weight: lapRow.pit ? Font.DemiBold : Font.Normal
                            font.features: { "tnum": 1 }
                        }
                        Cell { text: lapRow.time + popup.mark(lapRow.timeTone); tint: lapRow.timeTone; Layout.preferredWidth: theme.em * 5.4; font.weight: Font.DemiBold }
                        Cell { text: lapRow.s1 + popup.mark(lapRow.s1Tone); tint: lapRow.s1Tone }
                        Cell { text: lapRow.s2 + popup.mark(lapRow.s2Tone); tint: lapRow.s2Tone }
                        Cell { text: lapRow.s3 + popup.mark(lapRow.s3Tone); tint: lapRow.s3Tone }
                        Cell { text: lapRow.energy; color: theme.dimText }
                        Cell { text: lapRow.position > 0 ? "P" + lapRow.position : ""; Layout.preferredWidth: theme.em * 3.4 }
                    }
                }
                TpStateView {
                    parent: laps
                    anchors.centerIn: parent
                    empty: laps.count === 0
                    compact: true
                    glyph: ""  // stopwatch
                    title: i18n.tr("No lap yet")
                    text: i18n.tr("Laps are recorded while this page watches the race.")
                }
            }
        }
    }
}
