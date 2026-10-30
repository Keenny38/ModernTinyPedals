import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Session events: contacts (reported by both cars, shown once), penalties, track limits (other than no
// further action) and chat, by session time. Filter by kind, or events of car picked only. Session with a
// replay (LMU): watch an event in the replay (button, double click, or Tab then Up / Down & Enter), camera on
// the car concerned.
Item {
    id: events

    readonly property bool replay: (backend.sessionHeader.replay || "") !== ""

    // Purple is kept for best times (as overlays): track limits in warning, told apart by their icon & letter
    function kindColor(kind) {
        return kind === "contact" ? theme.loss : kind === "penalty" || kind === "track_limits" ? theme.warning
             : theme.dimText
    }
    // Without icon font: a letter of the kind (shape of the event told without its color too)
    function kindLetter(kind) {
        return kind === "contact" ? "C" : kind === "penalty" ? "!" : kind === "track_limits" ? "T" : "…"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.space4
        spacing: theme.space3

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space4
            TpSegmented {
                readonly property var counts: backend.eventCounts
                name: i18n.tr("Events")
                options: [
                    i18n.tr("All") + "  " + (counts[0] || 0),
                    i18n.tr("Contacts") + "  " + (counts[1] || 0),
                    i18n.tr("Penalties") + "  " + (counts[2] || 0),
                    i18n.tr("Track Limits") + "  " + (counts[3] || 0),
                    i18n.tr("Chat") + "  " + (counts[4] || 0),
                ]
                currentIndex: backend.eventKind
                maxWidth: events.width * 0.72
                onActivated: function(index) { backend.setEventKind(index) }
            }
            Item { Layout.fillWidth: true }
            TpSwitch {
                text: i18n.tr("Car picked only")
                checkable: false  // state of backend shown (binding never broken by the click)
                checked: backend.eventMine
                onClicked: backend.setEventMine(!backend.eventMine)
            }
        }

        Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        ListView {
            id: list
            objectName: "eventList"
            anchors.fill: parent
            clip: true
            model: backend.eventModel
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            reuseItems: true
            activeFocusOnTab: count > 0
            currentIndex: -1
            keyNavigationEnabled: true
            highlightFollowsCurrentItem: false
            Accessible.role: Accessible.List
            Accessible.name: i18n.tr("Events")
            onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
            Keys.onReturnPressed: if (events.replay && currentItem) backend.watchEvent(currentItem.key)
            Keys.onEnterPressed: if (events.replay && currentItem) backend.watchEvent(currentItem.key)

            delegate: Item {
                id: row
                required property int index
                required property string key
                required property string clock
                required property string kind
                required property string glyph
                required property string title
                required property string detail
                required property bool mine
                readonly property color tone: events.kindColor(kind)

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.controlHeight)
                Accessible.role: Accessible.ListItem
                Accessible.name: row.clock + ", " + row.title + ", " + row.detail

                TpListRow {
                    id: surface
                    anchors.fill: parent
                    hovered: rowArea.containsMouse
                    striped: row.index % 2 === 1
                }
                FocusRing {
                    target: surface
                    anchors.margins: 0
                    visible: list.activeFocus && row.ListView.isCurrentItem
                }
                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: list.currentIndex = row.index
                    onDoubleClicked: if (events.replay) backend.watchEvent(row.key)
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.5
                    anchors.rightMargin: theme.em * 0.5
                    spacing: theme.space4
                    Text {
                        Layout.preferredWidth: theme.em * 4.6
                        text: row.clock
                        textFormat: Text.PlainText
                        color: theme.dimOn(surface.color)
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                    }
                    TpIconTile {
                        size: Math.round(theme.iconLg)
                        glyph: row.glyph
                        fallbackText: events.kindLetter(row.kind)
                        tint: row.tone
                    }
                    Text {
                        Layout.preferredWidth: Math.min(implicitWidth, events.width * 0.45)
                        text: row.title
                        textFormat: Text.PlainText
                        color: theme.text
                        font.weight: row.mine ? Font.Bold : Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: row.detail
                        textFormat: Text.PlainText
                        color: theme.dimOn(surface.color)
                        elide: Text.ElideRight
                    }
                    TpButton {  // replay of session at this event
                        visible: events.replay
                        flat: true
                        size: "sm"
                        glyph: ""  // play
                        fallback: "▶"
                        tip: i18n.tr("Watch in replay")
                        onClicked: backend.watchEvent(row.key)
                    }
                }
            }

        }
        TpStateView {  // centered where the list goes (not under it)
            anchors.centerIn: parent
            empty: list.count === 0
            compact: true
            glyph: ""  // flag
            title: i18n.tr("No event")
        }
        }
    }
}
