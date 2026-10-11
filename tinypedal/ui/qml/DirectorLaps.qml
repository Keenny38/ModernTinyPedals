import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Lap history of a car (laps seen while the page watched): lap time & sectors colored (purple: best of class,
// green: personal best, yellow: slower), pit lane lap, energy used, class place at lap end. Newest first.
Popup {
    id: popup
    modal: true
    dim: true
    padding: theme.em * 1.0
    anchors.centerIn: parent
    onClosed: if (backend.lapsOpen) backend.showLaps(-1)
    Connections {
        target: backend
        function onLapsChanged() {
            if (backend.lapsOpen && !popup.opened) popup.open()
            else if (!backend.lapsOpen && popup.opened) popup.close()
        }
    }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
    background: Rectangle {
        radius: theme.em * 0.8
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    function tone(name) {
        return name === "fastest" ? theme.purple : name === "gain" ? theme.gain : name === "yellow" ? theme.gold : theme.text
    }

    component Cell: Text {
        property string tint: ""
        Layout.preferredWidth: theme.em * 4.6
        horizontalAlignment: Text.AlignRight
        color: popup.tone(tint)
        font.features: { "tnum": 1 }
        elide: Text.ElideRight
    }
    component Head: Text {
        Layout.preferredWidth: theme.em * 4.6
        horizontalAlignment: Text.AlignRight
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.8
        font.weight: Font.DemiBold
    }

    contentItem: ColumnLayout {
        spacing: theme.em * 0.5
        RowLayout {
            Layout.fillWidth: true
            Icon { glyph: ""; color: theme.accent }  // stopwatch
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Lap History") + "  ·  " + backend.lapsTitle
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontPoint * 1.1
                elide: Text.ElideRight
            }
            TpButton { glyph: ""; flat: true; tip: i18n.tr("Close"); onClicked: popup.close() }  // close
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.rightMargin: theme.em * 0.8
            spacing: theme.em * 0.4
            Head { text: i18n.tr("Lap"); Layout.preferredWidth: theme.em * 3; horizontalAlignment: Text.AlignLeft }
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
            Layout.preferredHeight: theme.em * 26
            Layout.preferredWidth: theme.em * 36
            clip: true
            model: backend.lapRows
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: Rectangle {
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
                height: Math.round(theme.em * 1.9)
                radius: theme.em * 0.3
                color: index % 2 ? "transparent" : Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.04)
                RowLayout {
                    anchors.fill: parent
                    spacing: theme.em * 0.4
                    Text {
                        Layout.preferredWidth: theme.em * 3
                        leftPadding: theme.em * 0.3
                        text: lapRow.lap + (lapRow.pit ? "  P" : "")
                        color: lapRow.pit ? theme.warning : theme.dimText
                        font.features: { "tnum": 1 }
                    }
                    Cell { text: lapRow.time; tint: lapRow.timeTone; Layout.preferredWidth: theme.em * 5.4; font.weight: Font.DemiBold }
                    Cell { text: lapRow.s1; tint: lapRow.s1Tone }
                    Cell { text: lapRow.s2; tint: lapRow.s2Tone }
                    Cell { text: lapRow.s3; tint: lapRow.s3Tone }
                    Cell { text: lapRow.energy; color: theme.dimText }
                    Cell { text: lapRow.position > 0 ? "P" + lapRow.position : ""; Layout.preferredWidth: theme.em * 3.4 }
                }
            }
            EmptyState {
                parent: laps
                anchors.centerIn: parent
                visible: laps.count === 0
                glyph: ""  // stopwatch
                title: i18n.tr("No lap yet")
                text: i18n.tr("Laps are recorded while this page watches the race.")
            }
        }
    }
}
