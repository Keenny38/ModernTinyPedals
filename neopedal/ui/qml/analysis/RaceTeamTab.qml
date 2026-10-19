import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator team tab: stints of every driver of the team car read from the game (LMU, asked
// while the tab is shown), usage per lap of each stint & driver, average of selected stints filled in.
// Stints: click (Ctrl: add, Shift: range), or Tab then Up / Down & Space; Enter fills the calculator in.
Item {
    id: tab
    readonly property var team: backend.teamInfo  // columns, drivers, count, canFill (rows: backend.teamRows)
    readonly property bool busy: backend.teamBusy
    readonly property int count: team.count || 0
    readonly property var columns: team.columns || []

    function modeOf(modifiers) {
        return modifiers & Qt.ShiftModifier ? 2 : modifiers & Qt.ControlModifier ? 1 : 0
    }
    // Names shown in rich text: never read as markup
    function esc(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }

    TpSectionCard {
        anchors.fill: parent
        anchors.topMargin: theme.space3
        title: i18n.tr("Team Stints")
        glyph: ""  // people
        busy: tab.busy
        actions: [
            TpButton {
                enabled: !tab.busy
                size: "sm"
                glyph: ""  // refresh
                fallback: "⟳"
                text: tab.busy ? i18n.tr("Asking game...") : i18n.tr("Refresh")
                tip: i18n.tr("Ask game again")
                onClicked: backend.refreshTeam()
            }
        ]
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Stints of every driver of the car read from the game (LMU), teammates included: usage per lap, out laps & pit laps left out. Select stints, then fill in: their average goes to the calculator.")
            color: theme.dimText
            font.pointSize: theme.fontSmall
            wrapMode: Text.Wrap
        }
        Row {  // header
            Layout.fillWidth: true
            visible: tab.count > 0
            Repeater {
                model: tab.columns
                TpHeaderCell {
                    required property var modelData
                    required property int index
                    width: list.width / Math.max(tab.columns.length, 1)
                    text: modelData
                    align: index === 0 ? Qt.AlignLeft : Qt.AlignRight
                }
            }
        }
        ListView {
            id: list
            objectName: "teamStints"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 8
            visible: tab.count > 0
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: backend.teamRows  // synced in place: scroll position & rows kept at each refresh
            activeFocusOnTab: true
            currentIndex: -1
            keyNavigationEnabled: true
            highlightFollowsCurrentItem: false
            Accessible.role: Accessible.Table
            Accessible.name: i18n.tr("Team Stints")
            ScrollBar.vertical: ScrollBar {}
            onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
            Keys.onSpacePressed: if (currentItem && currentItem.usable) backend.selectStint(currentItem.stint, 1)
            Keys.onReturnPressed: if (tab.team.canFill === true) backend.fillInTeam()
            Keys.onEnterPressed: if (tab.team.canFill === true) backend.fillInTeam()
            delegate: Item {
                id: stintRow
                required property int index
                required property var model
                readonly property int stint: model.number  // of the stint (sent back when clicked)
                readonly property bool usable: model.enabled
                readonly property bool selected: model.selected
                readonly property var cells: model.cells || []
                width: list.width
                height: Math.round(theme.rowCompact)
                Accessible.role: Accessible.Row
                Accessible.name: cells.join(", ") + (selected ? ", " + i18n.tr("Selected") : "")
                TpListRow {
                    id: surface
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: theme.radiusSm
                    hovered: stintArea.containsMouse && stintRow.usable
                    selected: stintRow.selected
                    striped: stintRow.index % 2 === 1
                }
                FocusRing {
                    target: surface
                    anchors.margins: 0
                    visible: list.activeFocus && stintRow.ListView.isCurrentItem
                }
                Row {
                    Repeater {
                        model: stintRow.cells.length
                        Text {
                            required property int index
                            width: list.width / Math.max(tab.columns.length, 1)
                            height: stintRow.height
                            text: stintRow.cells[index]
                            // Stint left out (out lap, no usage): dim & italic, never faded by opacity
                            color: stintRow.usable ? theme.text : theme.dimText
                            font.italic: !stintRow.usable
                            font.features: { "tnum": 1 }
                            leftPadding: theme.space2
                            rightPadding: theme.space2
                            horizontalAlignment: index === 0 ? Text.AlignLeft : Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }
                MouseArea {
                    id: stintArea
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: stintRow.usable
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function(mouse) {
                        list.currentIndex = stintRow.index
                        backend.selectStint(stintRow.stint, tab.modeOf(mouse.modifiers))
                    }
                }
            }
        }
        Item {  // nothing read yet: why, or waiting for the game
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: tab.count === 0
            TpStateView {
                anchors.centerIn: parent
                loading: tab.busy
                empty: true
                compact: true
                loadingText: i18n.tr("Asking game...")
                glyph: ""  // people
                text: i18n.tr("No team stint from game yet: LMU running with the car on track needed.")
            }
        }
        Repeater {  // usage of each driver
            model: tab.team.drivers || []
            Text {
                required property var modelData
                Layout.fillWidth: true
                text: "<b>" + tab.esc(modelData.name) + "</b> · " + tab.esc(modelData.text)
                textFormat: Text.StyledText
                color: theme.text
                elide: Text.ElideRight
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: backend.teamStatus
                color: theme.dimText
                font.pointSize: theme.fontLabel
                elide: Text.ElideRight
            }
            TpButton {
                accent: true
                enabled: tab.team.canFill === true
                glyph: ""  // add
                text: i18n.tr("Fill In Calculator")
                tip: i18n.tr("Average per lap of selected stints (all stints if none selected): fuel, energy & tyre wear")
                onClicked: backend.fillInTeam()
            }
        }
    }
}
