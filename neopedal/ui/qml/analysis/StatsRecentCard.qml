import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Latest sessions of All Tracks: click shows race results of the session when linked to a results file (same
// main action as the Progression card), else its track & vehicle; right click or Menu key: the other actions
TpSectionCard {
    id: card
    property var menuSession: ({})  // session of the row menu
    // Race result: podium gold, silver, bronze, DNF & DQ loss (resultTone: same rule as Results page)
    function resultColor(tone) { return tone !== "" ? theme.tone(tone) : theme.text }
    visible: backend.recent.length > 0
    title: i18n.tr("Recent Sessions")
    glyph: ""  // history
    Repeater {
        model: backend.recent
        AbstractButton {  // click, or Tab then Enter / Space: results (track & vehicle without results file)
            id: recentItem
            required property var modelData
            readonly property bool linked: (modelData.results || "") !== ""
            function openMenu(x, y) {
                card.menuSession = modelData
                sessionMenu.popup(recentItem, x, y)
            }
            Layout.fillWidth: true
            implicitHeight: recentRow.implicitHeight + theme.em * 0.5
            hoverEnabled: true
            focusPolicy: Qt.TabFocus
            onClicked: {
                if (linked) backend.openResults(modelData.results)
                else backend.openSession(modelData.track, modelData.vehicle)
            }
            Keys.onReturnPressed: animateClick()
            Keys.onEnterPressed: animateClick()
            Keys.onMenuPressed: openMenu(theme.space4, height)
            Accessible.role: Accessible.Button
            Accessible.name: modelData.track + ", " + modelData.vehicle + ", " + modelData.date
            Accessible.description: linked ? i18n.tr("Click to show race results") : i18n.tr("Show this track & car")
            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler {
                acceptedButtons: Qt.RightButton
                onTapped: function(point) { recentItem.openMenu(point.position.x, point.position.y) }
            }
            ToolTip.visible: hovered || visualFocus
            ToolTip.text: linked ? i18n.tr("Click to show race results") : i18n.tr("Show this track & car")
            ToolTip.delay: theme.tipDelay
            background: TpListRow {
                hovered: recentItem.hovered
                pressed: recentItem.down
                FocusRing { visible: recentItem.visualFocus }
            }
            contentItem: Item {}
            RowLayout {
                id: recentRow
                anchors.verticalCenter: parent.verticalCenter
                x: theme.space2
                width: parent.width - theme.space2 * 2
                spacing: theme.em * 0.5
                GameLogo {  // circuit logo of game
                    source: recentItem.modelData.trackLogo || ""
                    boxWidth: theme.em * 2.6
                    boxHeight: theme.em * 1.6
                }
                ColumnLayout {
                    spacing: 0
                    Layout.fillWidth: true
                    Text {
                        text: recentItem.modelData.track
                        textFormat: Text.PlainText
                        color: theme.text
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: recentItem.modelData.date + " · " + recentItem.modelData.vehicle
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        font.features: { "tnum": 1 }
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
                ColumnLayout {
                    spacing: theme.space1
                    Row {
                        Layout.alignment: Qt.AlignRight
                        spacing: theme.space2
                        TpLapTime {  // personal best: ● green right of the time (shared record mark)
                            text: recentItem.modelData.best
                            record: recentItem.modelData.pb === true ? "personal" : ""
                            textColor: recentItem.modelData.best === "—" ? theme.dimText : theme.text
                            reserveMark: false
                        }
                    }
                    Row {
                        Layout.alignment: Qt.AlignRight
                        spacing: theme.space2
                        StatsPill {
                            text: recentItem.modelData.result
                            tint: card.resultColor(recentItem.modelData.resultTone || "")
                            strong: true
                        }
                        ResultsBadge {  // session badge of every page: letter & session color
                            visible: code !== ""
                            code: recentItem.modelData.code || ""
                            tip: recentItem.modelData.session
                            implicitWidth: Math.round(theme.em * 1.5)
                        }
                    }
                }
            }
        }
    }
    TpMenu {
        id: sessionMenu
        Action {
            text: i18n.tr("Show Results")
            enabled: (card.menuSession.results || "") !== ""
            onTriggered: backend.openResults(card.menuSession.results)
        }
        Action {
            text: i18n.tr("Show this track & car")
            onTriggered: backend.openSession(card.menuSession.track, card.menuSession.vehicle)
        }
    }
}
