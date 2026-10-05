import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator team tab: stints of every driver of the team car read from the game (LMU, asked
// while the tab is shown), usage per lap of each stint & driver, average of selected stints filled in
Item {
    id: tab
    readonly property var team: backend.team
    readonly property var selection: backend.teamSelection
    readonly property var rows: team.rows || []
    readonly property var columns: team.columns || []

    function modeOf(modifiers) {
        return modifiers & Qt.ShiftModifier ? 2 : modifiers & Qt.ControlModifier ? 1 : 0
    }

    RaceCard {
        anchors.fill: parent
        anchors.topMargin: theme.em * 0.4
        title: i18n.tr("Team Stints")
        glyph: ""  // people
        actions: [
            TpButton {
                enabled: !tab.team.busy
                glyph: ""  // refresh
                text: tab.team.busy ? i18n.tr("Asking game...") : i18n.tr("Refresh")
                tip: i18n.tr("Ask game again")
                onClicked: backend.refreshTeam()
            }
        ]
        Text {
            Layout.fillWidth: true
            text: i18n.tr("Stints of every driver of the car read from the game (LMU), teammates included: usage per lap, out laps & pit laps left out. Select stints, then fill in: their average goes to the calculator.")
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.88
            wrapMode: Text.Wrap
        }
        Row {  // header
            Layout.fillWidth: true
            visible: tab.rows.length > 0
            Repeater {
                model: tab.columns
                Text {
                    required property var modelData
                    width: list.width / Math.max(tab.columns.length, 1)
                    height: Math.round(theme.em * 1.8)
                    text: modelData
                    color: theme.dimText
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontPoint * 0.9
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
            }
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 8
            visible: tab.rows.length > 0
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: tab.rows
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                id: stintRow
                required property var modelData
                required property int index
                readonly property bool selected: tab.selection.indexOf(modelData.index) >= 0
                width: list.width
                height: Math.round(theme.em * 1.75)
                radius: theme.em * 0.3
                opacity: modelData.enabled ? 1 : 0.5
                color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.3 : 0.2)
                     : stintArea.containsMouse && modelData.enabled ? theme.hover
                     : index % 2 ? (theme.dark ? Qt.rgba(1, 1, 1, 0.035) : Qt.rgba(0, 0, 0, 0.03)) : "transparent"
                Row {
                    Repeater {
                        model: stintRow.modelData.cells
                        Text {
                            required property var modelData
                            width: list.width / Math.max(tab.columns.length, 1)
                            height: stintRow.height
                            text: modelData
                            color: theme.text
                            font.features: { "tnum": 1 }
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }
                MouseArea {
                    id: stintArea
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: stintRow.modelData.enabled
                    onClicked: function(mouse) { backend.selectStint(stintRow.modelData.index, tab.modeOf(mouse.modifiers)) }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: tab.rows.length === 0
            text: i18n.tr("No team stint from game yet: LMU running with the car on track needed.")
            color: theme.dimText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
        }
        Repeater {  // usage of each driver
            model: tab.team.drivers || []
            Text {
                required property var modelData
                Layout.fillWidth: true
                text: "<b>" + modelData.name + "</b> · " + modelData.text
                textFormat: Text.StyledText
                color: theme.text
                elide: Text.ElideRight
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: tab.team.status || ""
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.9
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
