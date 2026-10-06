import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Session events: contacts (reported by both cars, shown once), penalties, track limits (other than no
// further action) and chat, by session time. Filter by kind, or events of car picked only.
Item {
    id: events

    function kindColor(kind) {
        return kind === "contact" ? theme.loss : kind === "penalty" ? theme.warning
             : kind === "track_limits" ? theme.purple : theme.dimText
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.6
        spacing: theme.em * 0.5

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            TpSegmented {
                readonly property var counts: backend.eventCounts
                options: [
                    i18n.tr("All") + "  " + (counts[0] || 0),
                    i18n.tr("Contacts") + "  " + (counts[1] || 0),
                    i18n.tr("Penalties") + "  " + (counts[2] || 0),
                    i18n.tr("Track limits") + "  " + (counts[3] || 0),
                    i18n.tr("Chat") + "  " + (counts[4] || 0),
                ]
                currentIndex: backend.eventKind
                maxWidth: events.width * 0.72
                onActivated: function(index) { backend.setEventKind(index) }
            }
            Item { Layout.fillWidth: true }
            TpSwitch {
                text: i18n.tr("Car picked only")
                checked: backend.eventMine
                onToggled: backend.setEventMine(checked)
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.eventModel
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            reuseItems: true

            delegate: Rectangle {
                id: row
                required property int index
                required property string clock
                required property string kind
                required property string glyph
                required property string title
                required property string detail
                required property bool mine
                readonly property color tone: events.kindColor(kind)

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 2.3)
                radius: theme.em * 0.4
                color: rowArea.containsMouse ? theme.hover
                     : index % 2 ? Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.025 : 0.03) : "transparent"
                MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.5
                    anchors.rightMargin: theme.em * 0.5
                    spacing: theme.em * 0.6
                    Text {
                        Layout.preferredWidth: theme.em * 4.6
                        text: row.clock
                        color: theme.dimText
                        font.features: { "tnum": 1 }
                    }
                    Rectangle {
                        implicitWidth: Math.round(theme.em * 1.6)
                        implicitHeight: implicitWidth
                        radius: width / 2
                        color: Qt.rgba(row.tone.r, row.tone.g, row.tone.b, 0.16)
                        Icon {
                            anchors.centerIn: parent
                            glyph: row.glyph
                            size: theme.em * 0.8
                            color: row.tone
                        }
                    }
                    Text {
                        Layout.preferredWidth: Math.min(implicitWidth, events.width * 0.45)
                        text: row.title
                        color: theme.text
                        font.weight: row.mine ? Font.Bold : Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: row.detail
                        color: theme.dimText
                        elide: Text.ElideRight
                    }
                }
            }
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            visible: list.count === 0
            text: i18n.tr("No event")
            color: theme.dimText
        }
    }
}
