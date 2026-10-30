import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Progression chart & sessions of selected vehicle (side by side when wide enough, else one at a time),
// session filters in use as chips (each removable)
TpSectionCard {
    id: progressionBox
    readonly property var progression: backend.progression
    readonly property var sessions: backend.sessions
    // Backend tone name in its status color (gain, loss), else fallback
    function tone(name, fallback) { return name === "loss" || name === "gain" ? theme.tone(name) : fallback }
    // Race result: podium gold, silver, bronze, DNF & DQ loss (resultTone: same rule as Results page)
    function resultColor(tone) { return tone !== "" ? theme.tone(tone) : theme.text }
    signal filtersRequested(Item button)  // page opens its filters menu below the button
    property bool filtersOpen: false  // filters menu of the page open
    readonly property bool split: width > theme.em * 54  // content-tuned: chart (25 em) & sessions list (29 em)
    property bool showSessions: false
    property int hoveredPoint: -1  // chart point of the session hovered in the list
    property int pickedSession: -1  // session of the chart point clicked (shown in the list)
    title: i18n.tr("Progression")
    glyph: ""  // area chart
    tip: i18n.tr("Best lap of each session & personal best so far, level limits of community lap times")
    actions: [
        TpSegmented {
            name: i18n.tr("Sessions")
            options: backend.sessionFilters
            currentIndex: backend.sessionFilter
            onActivated: function(index) { backend.setSessionFilter(index) }
        },
        TpButton {
            id: filtersButton
            objectName: "statsFiltersButton"
            flat: !backend.filtered
            checked: progressionBox.filtersOpen || backend.filtered
            glyph: ""  // filter
            size: "sm"
            fallback: i18n.tr("Filters")
            tip: i18n.tr("Sessions of a road condition, online or offline, since a game version")
            onClicked: progressionBox.filtersRequested(filtersButton)
        },
        TpButton {
            visible: !progressionBox.split
            flat: true
            checked: progressionBox.showSessions
            glyph: ""  // list
            size: "sm"
            fallback: i18n.tr("Sessions")
            tip: i18n.tr("Sessions")
            onClicked: progressionBox.showSessions = !progressionBox.showSessions
        }
    ]
    Flow {  // filters in use: chips removed one by one (click), or all at once
        objectName: "statsFilterChips"
        visible: backend.filtered
        Layout.fillWidth: true
        spacing: theme.space2
        Repeater {
            model: backend.filterChips
            TpChip {
                required property var modelData
                text: modelData.text
                glyph: "\uE711"  // cancel
                selected: true
                size: "sm"
                tip: i18n.tr("Remove this filter")
                Accessible.name: i18n.tr("Remove this filter") + ": " + modelData.text
                onClicked: backend.clearFilter(modelData.key)
            }
        }
        TpButton {
            flat: true
            size: "sm"
            text: i18n.tr("Clear Filters")
            onClicked: backend.clearFilters()
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: theme.space5
        ColumnLayout {
            visible: progressionBox.split || !progressionBox.showSessions
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: theme.space2
            StatsChart {
                visible: progressionBox.progression.visible === true
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: theme.em * 8
                chartData: progressionBox.progression
                linkedPoint: progressionBox.hoveredPoint
                onPointClicked: function(session) {
                    progressionBox.pickedSession = session
                    if (session < 0) return
                    if (!progressionBox.split) progressionBox.showSessions = true
                    sessionList.positionViewAtIndex(session, ListView.Contain)
                }
            }
            Item {  // no chart yet: why, centered in the room of the chart (shared TpStateView)
                visible: progressionBox.progression.visible !== true
                Layout.fillWidth: true
                Layout.fillHeight: true
                implicitHeight: chartEmpty.implicitHeight
                TpStateView {
                    id: chartEmpty
                    anchors.centerIn: parent
                    empty: true
                    compact: true
                    glyph: ""
                    title: i18n.tr("2 sessions with a lap time needed for a chart.")
                }
            }
            Text {
                Layout.fillWidth: true
                text: progressionBox.progression.info || ""
                textFormat: Text.PlainText
                color: theme.dimText
                wrapMode: Text.WordWrap
                font.pointSize: theme.fontLabel
            }
        }
        Rectangle {
            visible: progressionBox.split
            Layout.fillHeight: true
            implicitWidth: 1
            color: theme.border
            opacity: 0.6
        }
        ColumnLayout {  // sessions of selected vehicle, newest first
            visible: progressionBox.split || progressionBox.showSessions
            Layout.fillWidth: !progressionBox.split
            // content-tuned: 34 em when the chart keeps 56 em or more
            Layout.preferredWidth: progressionBox.split
                ? Math.min(progressionBox.width > theme.em * 90 ? theme.em * 34 : theme.em * 29, progressionBox.width * 0.5) : -1  // content-tuned
            Layout.fillHeight: true
            spacing: theme.space1
            RowLayout {
                Layout.fillWidth: true
                StatsLabel { text: i18n.tr("Sessions"); Layout.topMargin: 0 }
                Text {
                    readonly property int total: progressionBox.progression.sessions || 0  // all, list shows newest
                    text: !progressionBox.sessions.length ? ""
                          : total > progressionBox.sessions.length ? progressionBox.sessions.length + " / " + total
                          : String(progressionBox.sessions.length)
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontSmall
                    font.features: { "tnum": 1 }
                }
                Item { Layout.fillWidth: true }
            }
            ListView {
                id: sessionList
                objectName: "sessionList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                reuseItems: true
                boundsBehavior: Flickable.StopAtBounds
                model: progressionBox.sessions
                // Keyboard: Tab, Up / Down, Enter shows the session in Results & Replays (results file)
                activeFocusOnTab: count > 0
                currentIndex: -1
                keyNavigationEnabled: true
                highlightFollowsCurrentItem: false
                Accessible.role: Accessible.List
                Accessible.name: i18n.tr("Sessions")
                onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
                Keys.onReturnPressed: if (currentItem && currentItem.modelData.results) backend.openResults(currentItem.modelData.results)
                Keys.onEnterPressed: if (currentItem && currentItem.modelData.results) backend.openResults(currentItem.modelData.results)
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Item {
                    id: sessionItem
                    required property var modelData
                    required property int index
                    readonly property bool linked: (modelData.results || "") !== ""  // results file: opens it
                    width: ListView.view.width
                    height: Math.round(theme.rowCompact)
                    Accessible.role: Accessible.ListItem
                    Accessible.name: modelData.tip || ""
                    ToolTip.visible: sessionArea.containsMouse || (sessionList.activeFocus && ListView.isCurrentItem)
                    ToolTip.text: modelData.tip
                    ToolTip.delay: theme.tipDelay
                    TpListRow {  // hover only on sessions that open something
                        id: sessionSurface
                        anchors.fill: parent
                        anchors.margins: 1
                        radius: theme.radiusSm
                        hovered: sessionArea.containsMouse && sessionItem.linked
                        selected: sessionItem.index === progressionBox.pickedSession
                    }
                    FocusRing {
                        target: sessionSurface
                        anchors.margins: 0
                        visible: sessionList.activeFocus && sessionItem.ListView.isCurrentItem
                    }
                    MouseArea {  // session of a results file: shown in race results page
                        id: sessionArea
                        onContainsMouseChanged: progressionBox.hoveredPoint = containsMouse ? sessionItem.modelData.point : -1
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: sessionItem.linked ? Qt.LeftButton : Qt.NoButton
                        cursorShape: sessionItem.linked ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: backend.openResults(sessionItem.modelData.results)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.space2
                        anchors.rightMargin: theme.space2
                        spacing: theme.em * 0.5
                        Text {
                            text: sessionItem.modelData.date
                            textFormat: Text.PlainText
                            color: theme.dimText
                            font.features: { "tnum": 1 }
                            font.pointSize: theme.fontLabel
                            Layout.preferredWidth: theme.em * 5.6  // dd/mm/yyyy
                        }
                        ResultsBadge {  // session badge of every page: letter & session color
                            code: sessionItem.modelData.code || ""
                            tip: sessionItem.modelData.session
                            implicitWidth: Math.round(theme.em * 1.5)
                        }
                        Text {  // game version when driven
                            visible: text !== ""
                            text: sessionItem.modelData.version ? "v" + sessionItem.modelData.version : ""
                            textFormat: Text.PlainText
                            color: theme.dimText
                            font.pointSize: theme.fontCaption
                            font.features: { "tnum": 1 }
                        }
                        Icon {  // best lap on a damp or wet road
                            visible: sessionItem.modelData.wet === true
                            glyph: ""  // water drop
                            fallback: "~"
                            size: theme.iconXs
                            color: theme.accent
                        }
                        Icon {  // driven on an online server
                            visible: sessionItem.modelData.online === 1
                            glyph: ""  // globe
                            fallback: "@"
                            size: theme.iconXs
                            color: theme.dimText
                        }
                        Item { Layout.fillWidth: true }
                        Icon {  // contacts & penalties of session (results file)
                            visible: sessionItem.modelData.incidents > 0
                            glyph: "\uE945"  // lightning
                            size: theme.iconXs
                            color: theme.warning
                        }
                        TpLapTime {  // personal best: ● green right of the time (shared record mark)
                            text: sessionItem.modelData.best
                            record: sessionItem.modelData.pb === true ? "personal" : ""
                            textColor: sessionItem.modelData.best === "—" ? theme.dimText : theme.text
                            reserveMark: false
                        }
                        Text {  // places gained in a race (start to finish)
                            visible: text !== ""
                            text: sessionItem.modelData.gained || ""
                            textFormat: Text.PlainText
                            color: progressionBox.tone(sessionItem.modelData.gainedColor, theme.dimText)
                            font.pointSize: theme.fontLabel
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                        Text {
                            text: sessionItem.modelData.laps
                            textFormat: Text.PlainText
                            color: theme.dimText
                            font.features: { "tnum": 1 }
                            font.pointSize: theme.fontLabel
                            Layout.preferredWidth: theme.em * 2.8
                            horizontalAlignment: Text.AlignRight
                        }
                        Item {
                            Layout.preferredWidth: theme.em * 3.6
                            implicitHeight: resultChip.implicitHeight
                            StatsPill {
                                id: resultChip
                                anchors.right: parent.right
                                text: sessionItem.modelData.result || sessionItem.modelData.rank
                                tint: sessionItem.modelData.result ? progressionBox.resultColor(sessionItem.modelData.resultTone || "")
                                                                   : theme.dimText
                                strong: sessionItem.modelData.result !== ""
                            }
                        }
                    }
                }
                TpStateView {
                    parent: sessionList  // over the list, not inside its scrolled content
                    anchors.centerIn: parent
                    empty: sessionList.count === 0
                    compact: true
                    text: i18n.tr("No session recorded yet: history starts with your next session.")
                }
            }
        }
    }
}
