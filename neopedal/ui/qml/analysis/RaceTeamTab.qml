import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator team tab: line-up typed before the race (names, drivers added or removed: names of the LMU
// team take their place once the game gives them), driver of each stint of the plan (planned, else chosen by
// the plan), stints of every driver of the team car read from the game (LMU, asked while the tab is shown),
// usage per lap of each stint & driver, average of selected stints filled in.
// Stints: click (Ctrl: add, Shift: range), or Tab then Up / Down & Space; Enter fills the calculator in.
Item {
    id: tab
    readonly property var team: backend.teamInfo  // columns, drivers, count, canFill (rows: backend.teamRows)
    readonly property bool busy: backend.teamBusy
    readonly property int count: team.count || 0
    readonly property var columns: team.columns || []
    readonly property var plan: backend.teamPlan  // line-up & stints of the plan (see race_team_plan)
    readonly property var drivers: plan.drivers || []
    readonly property var stints: plan.stints || []
    readonly property bool narrow: width < theme.bpNarrow  // cards one below the other, plan or game stints
    property int narrowPart: 0  // narrow: 0 plan (line-up & stints), 1 stints read from the game

    function modeOf(modifiers) {
        return modifiers & Qt.ShiftModifier ? 2 : modifiers & Qt.ControlModifier ? 1 : 0
    }
    // Names shown in rich text: never read as markup
    function esc(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }
    function driverColor(number) {
        return number > 0 && number <= tab.drivers.length ? tab.drivers[number - 1].color : theme.dimText
    }

    GridLayout {
        anchors.fill: parent
        anchors.topMargin: theme.space3
        columns: tab.narrow ? 1 : 2
        columnSpacing: theme.space4
        rowSpacing: theme.space4

        TpSegmented {
            objectName: "teamPart"
            visible: tab.narrow
            name: i18n.tr("Team")
            options: [i18n.tr("Stint Plan"), i18n.tr("Team Stints")]
            currentIndex: tab.narrowPart
            onActivated: function(index) { tab.narrowPart = index }
        }

        // Line-up: names typed before the race, LMU team names once in the game
        TpSectionCard {
            objectName: "teamLineUp"
            visible: !tab.narrow || tab.narrowPart === 0
            Layout.fillHeight: true
            Layout.fillWidth: tab.narrow
            Layout.preferredWidth: tab.narrow ? -1 : theme.em * 26
            Layout.minimumHeight: theme.em * 10
            Layout.verticalStretchFactor: tab.narrow ? 1 : 2
            title: i18n.tr("Line-up")
            count: tab.drivers.length > 0 ? String(tab.drivers.length) : ""
            glyph: ""  // people
            tip: i18n.tr("Drivers of the car: names typed before the race are replaced by the names of the LMU team once the game gives them (same or close names keep their place)")
            actions: [
                TpButton {
                    objectName: "addDriver"
                    size: "sm"
                    enabled: tab.plan.canAdd === true
                    glyph: theme.glyphs.add
                    fallback: "+"
                    text: i18n.tr("Add Driver")
                    tip: i18n.tr("One more driver taking turns (Drivers of the race rules)")
                    onClicked: backend.addDriver()
                }
            ]
            ListView {
                id: lineUp
                objectName: "lineUpList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: theme.em * 4
                clip: true
                spacing: theme.space2
                boundsBehavior: Flickable.StopAtBounds
                model: tab.drivers.length  // rows kept when values change: typed name kept while focused
                ScrollBar.vertical: ScrollBar {}
                delegate: RowLayout {
                    id: driverRow
                    required property int index
                    readonly property var driver: tab.drivers[index] || ({})
                    width: lineUp.width - theme.space2
                    spacing: theme.space2
                    ColorDot {
                        color: driverRow.driver.color || theme.dimText
                        Layout.alignment: Qt.AlignVCenter
                    }
                    Text {
                        text: driverRow.index + 1
                        textFormat: Text.PlainText
                        color: theme.text
                        font.weight: Font.DemiBold
                        font.features: { "tnum": 1 }
                        Layout.preferredWidth: theme.em * 1.2
                        horizontalAlignment: Text.AlignHCenter
                    }
                    TpTextField {
                        id: nameField
                        objectName: "driverName" + driverRow.index
                        Layout.fillWidth: true
                        Layout.minimumWidth: theme.em * 6
                        placeholderText: driverRow.driver.placeholder || ""
                        maximumLength: 40
                        tip: driverRow.driver.fromGame === true ? i18n.tr("Name of the LMU team") : i18n.tr("Name of the driver, replaced by the name of the LMU team once in the game")
                        Accessible.name: i18n.tr("Driver") + " " + (driverRow.index + 1) + (driverRow.driver.fromGame === true ? ", " + i18n.tr("LMU team") : "")
                        Component.onCompleted: text = driverRow.driver.name || ""
                        onEditingFinished: if (text.trim() !== (driverRow.driver.name || "")) backend.setDriverName(driverRow.index, text)
                        onEscaped: text = driverRow.driver.name || ""  // typed name dropped
                        Connections {
                            target: tab
                            function onDriversChanged() {
                                if (!nameField.activeFocus)
                                    nameField.text = driverRow.driver.name || ""
                            }
                        }
                    }
                    Icon {  // name of the LMU team
                        visible: driverRow.driver.fromGame === true
                        glyph: ""  // check
                        fallback: "✓"
                        color: theme.gain
                        Layout.alignment: Qt.AlignVCenter
                    }
                    Text {
                        visible: tab.plan.team === true && tab.plan.ready === true
                        text: (driverRow.driver.stints || 0) + " · " + (driverRow.driver.time || "")
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                        Layout.preferredWidth: theme.em * 4.6
                        elide: Text.ElideRight
                        Accessible.name: i18n.tr("Stints") + " " + (driverRow.driver.stints || 0) + ", " + i18n.tr("Time") + " " + (driverRow.driver.time || "")
                        HoverHandler { id: statsHover }
                        ToolTip.visible: statsHover.hovered
                        ToolTip.delay: theme.tipDelay
                        ToolTip.text: Accessible.name
                    }
                    TpButton {
                        objectName: "removeDriver" + driverRow.index
                        flat: true
                        size: "xs"
                        enabled: tab.drivers.length > 1
                        glyph: theme.glyphs.remove
                        fallback: "✕"
                        tip: i18n.tr("Remove Driver") + " " + (driverRow.index + 1)
                        Accessible.name: tip
                        onClicked: backend.removeDriver(driverRow.index)
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: tab.plan.gameTeam ? i18n.tr("LMU team") + ": " + tab.plan.gameTeam
                                        : i18n.tr("Names of the LMU team replace the names typed once the game gives them.")
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        // Driver of each stint of the plan: planned, else chosen by the plan (Auto)
        TpSectionCard {
            objectName: "stintPlan"
            visible: !tab.narrow || tab.narrowPart === 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 10
            Layout.verticalStretchFactor: 2
            title: i18n.tr("Stint Plan")
            glyph: ""  // calendar
            tip: i18n.tr("Driver of each stint: Auto lets the plan choose (stints per driver, driving times), a driver chosen drives that stint whatever the plan changes")
            warning: (backend.driverTimes || {}).warning === true
            actions: [
                TpButton {
                    objectName: "keepRotation"
                    flat: true
                    size: "sm"
                    enabled: tab.plan.team === true && tab.plan.ready === true
                    glyph: ""  // pin
                    fallback: "📌"
                    text: tab.narrow ? "" : i18n.tr("Keep Rotation")
                    tip: i18n.tr("Drivers the plan chose kept for every stint: the rotation stays when the plan changes")
                    Accessible.name: i18n.tr("Keep Rotation")
                    onClicked: backend.keepStintDrivers()
                },
                TpButton {
                    objectName: "clearRotation"
                    flat: true
                    size: "sm"
                    enabled: tab.plan.planned === true
                    glyph: theme.glyphs.reset
                    fallback: "↺"
                    text: tab.narrow ? "" : i18n.tr("All Auto")
                    tip: i18n.tr("Every stint back to Auto: drivers chosen by the plan")
                    Accessible.name: i18n.tr("All Auto")
                    onClicked: backend.clearStintDrivers()
                }
            ]
            Row {  // header
                Layout.fillWidth: true
                visible: stintList.visible
                TpHeaderCell { width: theme.em * 2.6; text: "#"; align: Qt.AlignHCenter }
                TpHeaderCell { width: stintList.driverWidth; text: i18n.tr("Driver") }
                TpHeaderCell { width: stintList.width - theme.em * 2.6 - stintList.driverWidth - stintList.timeWidth; text: i18n.tr("Laps") }
                TpHeaderCell { width: stintList.timeWidth; text: i18n.tr("Start · Duration"); align: Qt.AlignRight }
            }
            ListView {
                id: stintList
                objectName: "stintPlanList"
                readonly property real driverWidth: Math.min(Math.max(width * 0.4, theme.em * 9), theme.em * 14)
                readonly property real timeWidth: theme.em * 9
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: theme.em * 4
                visible: tab.plan.team === true && tab.stints.length > 0
                clip: true
                spacing: 1
                boundsBehavior: Flickable.StopAtBounds
                model: tab.stints.length  // rows kept when values change: open combo kept
                Accessible.role: Accessible.Table
                Accessible.name: i18n.tr("Stint Plan")
                ScrollBar.vertical: ScrollBar {}
                delegate: Item {
                    id: stintRow
                    required property int index
                    readonly property var stint: tab.stints[index] || ({})
                    readonly property bool editable: stint.kind === "plan"
                    width: stintList.width
                    height: Math.round(theme.fieldHeight) + theme.space1 * 2
                    Accessible.role: Accessible.Row
                    Accessible.name: i18n.tr("Stint") + " " + (stint.number || "") + ", " + (stint.name || "") + ", " + (stint.laps || "") + ", " + (stint.timing || "")
                    TpListRow {
                        anchors.fill: parent
                        radius: theme.radiusSm
                        striped: stintRow.index % 2 === 1
                        emphasized: stintRow.stint.kind === "current"
                    }
                    Row {
                        anchors.fill: parent
                        Text {
                            width: theme.em * 2.6
                            height: stintRow.height
                            text: stintRow.stint.number || ""
                            textFormat: Text.PlainText
                            color: stintRow.editable ? theme.text : theme.dimText
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        Item {
                            width: stintList.driverWidth
                            height: stintRow.height
                            TpCombo {
                                id: driverBox
                                objectName: "stintDriver" + stintRow.index
                                visible: stintRow.editable
                                anchors.fill: parent
                                anchors.topMargin: theme.space1
                                anchors.bottomMargin: theme.space1
                                anchors.rightMargin: theme.space2
                                model: stintRow.stint.choices || []
                                currentIndex: stintRow.stint.planned || 0
                                dotColor: function(text) { return tab.driverColor(stintRow.stint.driver || 0) }
                                font.bold: (stintRow.stint.planned || 0) > 0
                                tip: i18n.tr("Driver of this stint: Auto lets the plan choose")
                                Accessible.name: i18n.tr("Driver") + ", " + i18n.tr("Stint") + " " + (stintRow.stint.number || "")
                                onActivated: function(index) {
                                    backend.setStintDriver(stintRow.stint.stint, index)
                                    currentIndex = Qt.binding(function() { return stintRow.stint.planned || 0 })
                                }
                            }
                            Row {  // stint done or in progress: driver seen, not planned any more
                                visible: !stintRow.editable
                                anchors.verticalCenter: parent.verticalCenter
                                leftPadding: theme.space2
                                spacing: theme.space2
                                ColorDot {
                                    color: tab.driverColor(stintRow.stint.driver || 0)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    width: stintList.driverWidth - theme.em * 1.6
                                    text: (stintRow.stint.name || "") + (stintRow.stint.kind === "current" ? " · " + i18n.tr("In car") : "")
                                    textFormat: Text.PlainText
                                    color: stintRow.stint.kind === "current" ? theme.text : theme.dimText
                                    font.weight: stintRow.stint.kind === "current" ? Font.DemiBold : Font.Normal
                                    elide: Text.ElideRight
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }
                        Text {
                            width: stintList.width - theme.em * 2.6 - stintList.driverWidth - stintList.timeWidth
                            height: stintRow.height
                            text: stintRow.stint.laps || ""
                            textFormat: Text.PlainText
                            color: stintRow.editable ? theme.text : theme.dimText
                            font.features: { "tnum": 1 }
                            leftPadding: theme.space2
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        Text {
                            width: stintList.timeWidth
                            height: stintRow.height
                            text: stintRow.stint.timing || ""
                            textFormat: Text.PlainText
                            color: stintRow.editable ? theme.text : theme.dimText
                            font.features: { "tnum": 1 }
                            rightPadding: theme.space2
                            horizontalAlignment: Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }
            }
            Item {  // one driver, or no plan yet
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !stintList.visible
                TpStateView {
                    anchors.centerIn: parent
                    empty: true
                    compact: true
                    glyph: ""  // calendar
                    text: tab.plan.team !== true ? i18n.tr("Add a driver to choose the driver of each stint.")
                                                 : i18n.tr("No plan yet: race set up in the Fuel tab.")
                    actionText: tab.plan.team !== true && tab.plan.canAdd === true ? i18n.tr("Add Driver") : ""
                    onAction: backend.addDriver()
                }
            }
            Text {  // driving time limits not met (planned drivers: checked, not used to plan)
                Layout.fillWidth: true
                visible: text !== ""
                text: (backend.driverTimes || {}).warning === true
                      ? i18n.tr("Driving time limits not met: see Driving Time in the Fuel tab.")
                        + (tab.plan.planned === true ? " " + i18n.tr("Stints planned: minimum driving times are checked, not used to plan.") : "")
                      : tab.plan.planned === true ? i18n.tr("Stints planned: minimum driving times are checked, not used to plan.") : ""
                textFormat: Text.PlainText
                color: (backend.driverTimes || {}).warning === true ? theme.warning : theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.Wrap
            }
        }

        // Stints driven, read from the game
        TpSectionCard {
            objectName: "teamStintsCard"
        visible: !tab.narrow || tab.narrowPart === 1
            Layout.columnSpan: tab.narrow ? 1 : 2
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 12
            Layout.verticalStretchFactor: 1
            title: i18n.tr("Team Stints")
            glyph: ""  // people
            busy: tab.busy
            actions: [
                TpButton {
                    enabled: !tab.busy
                    size: "sm"
                    glyph: theme.glyphs.refresh
                    fallback: "⟳"
                    text: tab.busy ? i18n.tr("Asking game…") : i18n.tr("Refresh")
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
                Layout.minimumHeight: theme.em * 4
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
                                textFormat: Text.PlainText
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
                    loadingText: i18n.tr("Asking game…")
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
                    textFormat: Text.PlainText
                    color: theme.dimText
                    font.pointSize: theme.fontLabel
                    elide: Text.ElideRight
                }
                TpButton {
                    accent: true
                    enabled: tab.team.canFill === true
                    glyph: theme.glyphs.add
                    text: i18n.tr("Fill In Calculator")
                    tip: i18n.tr("Average per lap of selected stints (all stints if none selected): fuel, energy & tyre wear")
                    onClicked: backend.fillInTeam()
                }
            }
        }
    }
}
