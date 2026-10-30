import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Standings of the session (or replay) open in game: class chips (click: that class only), cars by position with
// class color, number, driver & car, laps, best lap (purple ◆: fastest of class), last lap, gap, pit stops, status,
// incidents (click: incidents of driver). Car followed by camera marked; double click or camera button: camera on car.
// Keys: Up / Down move, Enter puts the camera on the car.
Item {
    id: root

    TpLapTime { id: markProbe; visible: false }  // room of record mark: Best header lines up with times

    // Read once here (rows bind to these, not to the backend: one evaluation per change, not one per row)
    readonly property bool hasEnergy: replays.hasEnergy
    readonly property bool inSession: replays.inSession
    readonly property bool wide: width > theme.em * (hasEnergy ? 47 : 40)  // content-tuned: last lap column fits
    readonly property real cellPad: theme.em * 0.35
    readonly property real posWidth: classes.count > 1 ? theme.em * 4.4 : theme.em * 2.4  // room for class badges
    property string menuKey: ""
    property string menuDriver: ""

    function showSelected() {
        var index = replays.carIndex(replays.selectedCar)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }

    TpMenu {
        id: rowMenu
        Action {
            text: i18n.tr("Camera on This Car")
            enabled: replays.inSession
            onTriggered: replays.watchCar(root.menuKey)
        }
        Action {
            text: i18n.tr("Go to Lap…")
            enabled: replays.replayActive
            onTriggered: replays.goToLap(root.menuKey)
        }
        Action {
            text: i18n.tr("Incidents of %1").arg(root.menuDriver)
            onTriggered: replays.showDriverIncidents(root.menuDriver)
        }
        onClosed: list.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        anchors.topMargin: 0
        spacing: theme.space3

        // Classes: click to see one class only
        ListView {
            id: classes
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.em * 2.0)
            visible: count > 1
            orientation: ListView.Horizontal
            spacing: theme.space3
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: replays.classes
            delegate: TpChip {
                required property var modelData
                height: classes.height
                text: modelData.name
                showDot: true
                dotColor: modelData.color
                count: modelData.count
                selected: replays.classFilter === modelData.name
                onClicked: replays.setClassFilter(modelData.name)
            }
        }

        // Last session (game in menus): standings kept
        Pill {
            visible: replays.lastSession && list.count > 0
            text: i18n.tr("Last Session")
            tint: theme.warning
            glyph: ""  // history
        }

        // Column titles, lined up with row cells (same margins, scroll bar room)
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: theme.space3
            Layout.rightMargin: theme.space1 + (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
            visible: list.count > 0
            spacing: root.cellPad
            TpHeaderCell { text: i18n.tr("Pos"); Layout.preferredWidth: root.posWidth; align: Qt.AlignHCenter }
            TpHeaderCell { text: i18n.tr("Driver"); Layout.fillWidth: true }
            TpHeaderCell { text: i18n.tr("Laps"); Layout.preferredWidth: theme.em * 2.4; align: Qt.AlignRight }
            TpHeaderCell { text: i18n.tr("Best"); Layout.preferredWidth: theme.em * 5.6; align: Qt.AlignRight
                           rightPadding: markProbe.markRoom }
            TpHeaderCell { text: i18n.tr("Last"); visible: root.wide; Layout.preferredWidth: theme.em * 4.9; align: Qt.AlignRight }
            TpHeaderCell { text: i18n.tr("Gap"); Layout.preferredWidth: theme.em * 4.6; align: Qt.AlignRight }
            TpHeaderCell { text: i18n.tr("Pit"); Layout.preferredWidth: theme.em * 3.2; align: Qt.AlignHCenter }
            TpHeaderCell { text: i18n.tr("Energy"); visible: root.hasEnergy; Layout.preferredWidth: theme.em * 3.8; align: Qt.AlignHCenter }
            Item { Layout.preferredWidth: theme.em * 2.4 }  // incidents
            Item { Layout.preferredWidth: theme.em * 2.0 }  // camera
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            focus: true
            activeFocusOnTab: true
            model: replays.standingRows
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true  // rows scrolled out fed again with other cars (see delegate onPooled)
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: { replays.moveCarSelection(-1); root.showSelected() }
            Keys.onDownPressed: { replays.moveCarSelection(1); root.showSelected() }
            Keys.onReturnPressed: replays.watchCar(replays.selectedCar)
            Keys.onEnterPressed: replays.watchCar(replays.selectedCar)
            Keys.onShortcutOverride: function(event) {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                    event.accepted = true
            }
            move: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            moveDisplaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }

            delegate: Item {
                id: row
                required property int index
                required property string key
                required property int position
                required property int classPosition
                required property string number
                required property string driver
                required property string vehicle
                required property string carClass
                required property string classColor
                required property string classAlias
                required property int laps
                required property string best
                required property string last
                required property string gap
                required property int pits
                required property string status
                required property string statusTone
                required property int penalties
                required property bool onCamera
                required property bool player
                required property bool fastest
                required property int incidents
                required property string energy
                required property real energyLevel
                required property string brandLogo
                required property bool selected  // role changed for two rows on selection, no binding per row
                // Reused row: fed other car values at once, no color animation from the old car
                property bool live: true
                ListView.onPooled: live = false
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.row)
                Accessible.role: Accessible.ListItem
                Accessible.name: [row.position > 0 ? "P" + row.position : "", row.number !== "" ? "#" + row.number : "", row.driver,
                                  row.onCamera ? i18n.tr("Camera on This Car") : "", row.status].filter(function(part) { return part !== "" }).join(", ")

                TpListRow {  // own car: accent tint without selection
                    id: rowBack
                    anchors.fill: parent
                    animate: row.live
                    hovered: rowArea.containsMouse
                    selected: row.selected
                    emphasized: row.player
                    striped: row.index % 2 === 1  // timing table: odd rows striped
                }
                FocusRing { target: rowBack; visible: row.selected && list.activeFocus }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: { list.forceActiveFocus(); replays.selectCar(row.key) }
                    onClicked: function(mouse) {
                        if (mouse.button !== Qt.RightButton) return
                        root.menuKey = row.key
                        root.menuDriver = row.driver
                        rowMenu.popup(rowArea, mouse.x, mouse.y)
                    }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) replays.watchCar(row.key) }
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.space3
                    anchors.rightMargin: theme.space1
                    spacing: root.cellPad

                    Column {  // position, class badge (as overlays: alias & position in class) when several classes
                        Layout.preferredWidth: root.posWidth
                        Text {
                            width: parent.width
                            text: row.position > 0 ? row.position : "—"
                            textFormat: Text.PlainText
                            color: theme.text
                            font.weight: Font.Bold
                            font.features: { "tnum": 1 }
                            horizontalAlignment: Text.AlignHCenter
                        }
                        TpClassBadge {
                            visible: classes.count > 1 && label !== ""
                            anchors.horizontalCenter: parent.horizontalCenter
                            label: row.classAlias
                            fullName: row.carClass
                            fill: row.classColor
                            position: row.classPosition > 0 ? String(row.classPosition) : ""
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.space3
                            Rectangle {  // car number
                                visible: row.number !== ""
                                implicitWidth: Math.max(numberText.implicitWidth + theme.em * 0.5, theme.em * 1.6)
                                implicitHeight: numberText.implicitHeight + 2
                                radius: theme.radiusSm
                                color: theme.tint(theme.text, "subtle")
                                Text {
                                    id: numberText
                                    anchors.centerIn: parent
                                    text: row.number
                                    textFormat: Text.PlainText
                                    color: theme.text
                                    font.pointSize: theme.fontCaption
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.driver
                                textFormat: Text.PlainText
                                color: row.onCamera ? theme.accent : theme.text
                                font.weight: row.player || row.onCamera ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                        }
                        RowLayout {  // status (garage, pits, finished...), class, team or car, penalties
                            Layout.fillWidth: true
                            spacing: theme.space3
                            Pill {  // pit, finished, retired
                                visible: row.status !== ""
                                size: "sm"
                                text: row.status
                                tint: theme.tone(row.statusTone)
                            }
                            Item {  // car brand logo of game: room kept, texts stay aligned while logos load
                                Layout.preferredWidth: theme.em * 1.8
                                Layout.preferredHeight: theme.em * 0.95
                                GameLogo {
                                    anchors.centerIn: parent
                                    source: row.brandLogo
                                    boxWidth: theme.em * 1.8
                                    boxHeight: theme.em * 0.95
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.carClass + (row.vehicle !== "" ? "  ·  " + row.vehicle : "")
                                      + (row.penalties > 0 ? "  ·  " + i18n.tr("Penalties") + " " + row.penalties : "")
                                textFormat: Text.PlainText
                                color: theme.dimOn(rowBack.color)
                                font.pointSize: theme.fontCaption
                                elide: Text.ElideRight
                            }
                        }
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 2.4
                        text: row.laps
                        textFormat: Text.PlainText
                        color: theme.text
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                    }
                    TpLapTime {  // fastest of class: purple & ◆ mark right of the time (shared record mark)
                        Layout.preferredWidth: theme.em * 5.6
                        Layout.preferredHeight: implicitHeight
                        text: row.best
                        record: row.fastest && row.best !== "" ? "session" : ""
                    }
                    Text {
                        visible: root.wide
                        Layout.preferredWidth: theme.em * 4.9
                        text: row.last
                        textFormat: Text.PlainText
                        color: theme.dimOn(rowBack.color)
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 4.6
                        text: row.gap
                        textFormat: Text.PlainText
                        color: theme.text
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideLeft
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 3.2
                        text: row.pits
                        textFormat: Text.PlainText
                        color: theme.dimOn(rowBack.color)
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Item {  // virtual energy (else fuel) left: told by game for cars of own team
                        visible: root.hasEnergy
                        Layout.preferredWidth: theme.em * 3.8
                        Layout.preferredHeight: theme.em * 1.6
                        Row {
                            anchors.centerIn: parent
                            spacing: theme.space2
                            visible: row.energy !== ""
                            TpMeter {
                                vertical: true
                                animated: row.live  // recycled row: other car level at once
                                thickness: theme.em * 0.3
                                height: theme.em * 1.1
                                value: row.energyLevel
                                tint: row.energyLevel < 0.2 ? theme.loss : row.energyLevel < 0.4 ? theme.warning : theme.gain
                                name: i18n.tr("Energy")
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: row.energy
                                textFormat: Text.PlainText
                                color: theme.text
                                font.features: { "tnum": 1 }
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                    AbstractButton {  // incidents of driver (Tab, Enter or Space)
                        id: incidentsButton
                        Layout.preferredWidth: theme.em * 2.4
                        Layout.preferredHeight: theme.em * 1.6
                        visible: row.incidents > 0
                        hoverEnabled: true
                        focusPolicy: Qt.TabFocus
                        onClicked: replays.showDriverIncidents(row.driver)
                        Keys.onReturnPressed: animateClick()
                        Keys.onEnterPressed: animateClick()
                        Keys.onShortcutOverride: function(event) {
                            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
                                event.accepted = true
                        }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        ToolTip.visible: hovered || visualFocus
                        ToolTip.text: hovered || visualFocus ? i18n.tr("Incidents of %1").arg(row.driver) : ""
                        ToolTip.delay: theme.tipDelay
                        Accessible.role: Accessible.Button
                        Accessible.name: i18n.tr("Incidents of %1").arg(row.driver) + " (" + row.incidents + ")"
                        background: Rectangle {
                            radius: height / 2
                            color: theme.tint(theme.loss, incidentsButton.hovered ? "selected" : "subtle")
                            FocusRing { visible: incidentsButton.visualFocus }
                        }
                        contentItem: Item {
                            Row {
                                anchors.centerIn: parent
                                spacing: 2
                                Icon { glyph: ""; fallback: "!"; size: theme.iconXs; color: theme.loss; anchors.verticalCenter: parent.verticalCenter }  // lightning
                                Text {
                                    text: row.incidents
                                    textFormat: Text.PlainText
                                    color: theme.loss
                                    font.pointSize: theme.fontCaption
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }
                    }
                    Item { visible: row.incidents === 0; Layout.preferredWidth: theme.em * 2.4 }
                    Item {  // camera: on this car (icon), or button to put it there
                        Layout.preferredWidth: theme.em * 2.0
                        Layout.preferredHeight: theme.em * 2.0
                        Icon {
                            anchors.centerIn: parent
                            visible: row.onCamera
                            glyph: ""  // camera
                            fallback: "◉"
                            size: theme.iconSm
                            color: theme.accent
                        }
                        TpButton {  // shown on the selected or hovered row (kept by pooled rows)
                            id: cameraButton
                            anchors.fill: parent
                            visible: !row.onCamera && root.inSession
                                     && (row.selected || rowArea.containsMouse || cameraButton.hovered)
                            flat: true
                            size: "sm"
                            glyph: ""  // camera
                            fallback: "◎"
                            tip: i18n.tr("Camera on This Car") + " (" + i18n.tr("double click") + ")"
                            onClicked: replays.watchCar(row.key)
                        }
                    }
                }
            }

            // No standings: game asked (session open), or no session or replay loaded in game
            TpStateView {
                anchors.centerIn: parent
                loading: list.count === 0 && root.inSession
                empty: list.count === 0 && !root.inSession
                loadingText: i18n.tr("Asking game…")
                glyph: ""  // people
                text: i18n.tr("Standings show once a session or a replay is loaded in the game.")
            }
        }
    }
}
