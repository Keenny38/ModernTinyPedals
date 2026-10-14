import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Standings of the session (or replay) open in game: class chips (click: that class only), cars by position with
// class color, number, driver & car, laps, best lap (purple: fastest of class), last lap, gap, pit stops, status,
// incidents (click: incidents of driver). Car followed by camera marked; double click or camera button: camera on car.
Item {
    id: root

    readonly property bool wide: width > theme.em * (replays.hasEnergy ? 47 : 40)  // last lap column shown
    readonly property real cellPad: theme.em * 0.35
    readonly property real posWidth: classes.count > 1 ? theme.em * 4.4 : theme.em * 2.4  // room for class badges
    property string menuKey: ""
    property string menuDriver: ""

    function tone(name) { return name === "loss" ? theme.loss : name === "gain" ? theme.gain : name === "warning" ? theme.warning : theme.dimText }
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
            text: i18n.tr("Go to Lap...")
            enabled: replays.replayActive
            onTriggered: replays.goToLap(root.menuKey)
        }
        Action {
            text: i18n.tr("Incidents of %1").arg(root.menuDriver)
            onTriggered: replays.showDriverIncidents(root.menuDriver)
        }
    }

    component HeaderText: Text {
        color: theme.dimText
        font.pointSize: theme.fontCaption
        font.weight: Font.DemiBold
        elide: Text.ElideRight
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        anchors.topMargin: 0
        spacing: theme.em * 0.5

        // Classes: click to see one class only
        ListView {
            id: classes
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.em * 2.0)
            visible: count > 1
            orientation: ListView.Horizontal
            spacing: theme.em * 0.4
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: replays.classes
            delegate: AbstractButton {
                id: chip
                required property var modelData
                readonly property bool active: replays.classFilter === modelData.name
                height: classes.height
                width: chipRow.implicitWidth + theme.em * 1.1
                hoverEnabled: true
                focusPolicy: Qt.NoFocus
                onClicked: replays.setClassFilter(modelData.name)
                background: Rectangle {
                    radius: height / 2
                    color: chip.active ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.2)
                         : chip.hovered ? theme.hover : theme.raised
                    border.width: 1
                    border.color: chip.active ? theme.accent : theme.border
                    Behavior on color { ColorAnimation { duration: theme.motionFast } }
                }
                contentItem: Item {
                    Row {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: theme.em * 0.4
                        Rectangle {
                            width: theme.em * 0.55
                            height: width
                            radius: width / 2
                            color: chip.modelData.color
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text { text: chip.modelData.name; color: theme.text; font.pointSize: theme.fontLabel }
                        Text {
                            text: chip.modelData.count
                            color: theme.dimText
                            font.pointSize: theme.fontLabel
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
        }

        // Last session (game in menus): standings kept
        Text {
            visible: replays.lastSession && list.count > 0
            text: i18n.tr("Last Session")
            color: theme.warning
            font.pointSize: theme.fontSmall
            font.weight: Font.DemiBold
        }

        // Column titles, lined up with row cells (same margins, scroll bar room)
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: theme.em * 0.4
            Layout.rightMargin: theme.em * 0.2 + (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
            visible: list.count > 0
            spacing: root.cellPad
            HeaderText { text: i18n.tr("Pos"); Layout.preferredWidth: root.posWidth; horizontalAlignment: Text.AlignHCenter }
            HeaderText { text: i18n.tr("Driver"); Layout.fillWidth: true }
            HeaderText { text: i18n.tr("Laps"); Layout.preferredWidth: theme.em * 2.4; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Best"); Layout.preferredWidth: theme.em * 4.9; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Last"); visible: root.wide; Layout.preferredWidth: theme.em * 4.9; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Gap"); Layout.preferredWidth: theme.em * 4.6; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Pit"); Layout.preferredWidth: theme.em * 3.2; horizontalAlignment: Text.AlignHCenter }
            HeaderText { text: i18n.tr("Energy"); visible: replays.hasEnergy; Layout.preferredWidth: theme.em * 3.8; horizontalAlignment: Text.AlignHCenter }
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
            move: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            moveDisplaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }

            delegate: Rectangle {
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
                readonly property bool selected: key === replays.selectedCar
                // Reused row: fed other car values at once, no color animation from the old car
                property bool live: true
                ListView.onPooled: live = false
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 2.9)
                radius: theme.radiusMd
                color: row.player && !selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.07)
                     : theme.rowColor(rowArea.containsMouse, selected)
                Behavior on color { enabled: row.live; ColorAnimation { duration: theme.motionFast } }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
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
                    anchors.leftMargin: theme.em * 0.4
                    anchors.rightMargin: theme.em * 0.2
                    spacing: root.cellPad

                    Column {  // position, class badge (as overlays: alias & position in class) when several classes
                        Layout.preferredWidth: root.posWidth
                        Text {
                            width: parent.width
                            text: row.position > 0 ? row.position : "-"
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
                            spacing: theme.em * 0.4
                            Rectangle {  // car number
                                visible: row.number !== ""
                                implicitWidth: Math.max(numberText.implicitWidth + theme.em * 0.5, theme.em * 1.6)
                                implicitHeight: numberText.implicitHeight + 2
                                radius: theme.radiusSm
                                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.1)
                                Text {
                                    id: numberText
                                    anchors.centerIn: parent
                                    text: row.number
                                    color: theme.text
                                    font.pointSize: theme.fontCaption
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.driver
                                color: row.onCamera ? theme.accent : theme.text
                                font.weight: row.player || row.onCamera ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                        }
                        RowLayout {  // status (garage, pits, finished...), class, team or car, penalties
                            Layout.fillWidth: true
                            spacing: theme.em * 0.4
                            Rectangle {  // pit, finished, retired
                                visible: row.status !== ""
                                readonly property color tint: root.tone(row.statusTone)
                                implicitWidth: statusLabel.implicitWidth + theme.em * 0.6
                                implicitHeight: statusLabel.implicitHeight + 2
                                radius: height / 2
                                color: Qt.rgba(tint.r, tint.g, tint.b, 0.16)
                                Text {
                                    id: statusLabel
                                    anchors.centerIn: parent
                                    text: row.status
                                    color: parent.tint
                                    font.pointSize: theme.fontTiny
                                    font.weight: Font.DemiBold
                                }
                            }
                            GameLogo {  // car brand logo of game
                                source: row.brandLogo
                                boxWidth: theme.em * 1.8
                                boxHeight: theme.em * 0.95
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.carClass + (row.vehicle !== "" ? "  ·  " + row.vehicle : "")
                                      + (row.penalties > 0 ? "  ·  " + i18n.tr("Penalties") + " " + row.penalties : "")
                                color: theme.dimText
                                font.pointSize: theme.fontCaption
                                elide: Text.ElideRight
                            }
                        }
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 2.4
                        text: row.laps
                        color: theme.text
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 4.9
                        text: row.best
                        color: row.fastest ? theme.purple : theme.text
                        font.weight: row.fastest ? Font.DemiBold : Font.Normal
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                    }
                    Text {
                        visible: root.wide
                        Layout.preferredWidth: theme.em * 4.9
                        text: row.last
                        color: theme.dimText
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 4.6
                        text: row.gap
                        color: theme.text
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideLeft
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 3.2
                        text: row.pits
                        color: theme.dimText
                        font.features: { "tnum": 1 }
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Item {  // virtual energy (else fuel) left: told by game for cars of own team
                        visible: replays.hasEnergy
                        Layout.preferredWidth: theme.em * 3.8
                        Layout.preferredHeight: theme.em * 1.6
                        Row {
                            anchors.centerIn: parent
                            spacing: theme.em * 0.3
                            visible: row.energy !== ""
                            Rectangle {
                                width: theme.em * 0.3
                                height: theme.em * 1.1
                                radius: 1
                                color: theme.hover
                                anchors.verticalCenter: parent.verticalCenter
                                Rectangle {
                                    anchors.bottom: parent.bottom
                                    width: parent.width
                                    height: parent.height * Math.max(0, Math.min(row.energyLevel, 1))
                                    radius: 1
                                    color: row.energyLevel < 0.2 ? theme.loss : row.energyLevel < 0.4 ? theme.warning : theme.gain
                                }
                            }
                            Text {
                                text: row.energy
                                color: theme.text
                                font.features: { "tnum": 1 }
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                    AbstractButton {  // incidents of driver
                        Layout.preferredWidth: theme.em * 2.4
                        Layout.preferredHeight: theme.em * 1.6
                        visible: row.incidents > 0
                        hoverEnabled: true
                        focusPolicy: Qt.NoFocus
                        onClicked: replays.showDriverIncidents(row.driver)
                        ToolTip.visible: hovered
                        ToolTip.text: hovered ? i18n.tr("Incidents of %1").arg(row.driver) : ""
                        ToolTip.delay: theme.tipDelay
                        background: Rectangle {
                            radius: height / 2
                            color: parent.hovered ? Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.22)
                                                  : Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.12)
                        }
                        contentItem: Item {
                            Row {
                                anchors.centerIn: parent
                                spacing: 2
                                Icon { glyph: ""; size: theme.em * 0.7; color: theme.loss; anchors.verticalCenter: parent.verticalCenter }
                                Text {
                                    text: row.incidents
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
                            size: theme.em * 0.9
                            color: theme.accent
                        }
                        Loader {  // made only for the selected or hovered row
                            id: cameraLoader
                            anchors.fill: parent
                            active: !row.onCamera && replays.inSession
                                    && (row.selected || rowArea.containsMouse
                                        || (cameraLoader.item !== null && cameraLoader.item.hovered))
                            sourceComponent: TpButton {
                                flat: true
                                glyph: ""
                                tip: hovered ? i18n.tr("Camera on This Car") + " (" + i18n.tr("double click") + ")" : ""
                                onClicked: replays.watchCar(row.key)
                            }
                        }
                    }
                }
            }

            // No standings: no session or replay loaded in game
            Column {
                anchors.centerIn: parent
                width: parent.width - theme.em * 4
                visible: list.count === 0
                spacing: theme.em * 0.6
                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    glyph: ""  // people
                    size: theme.em * 2.2
                    color: theme.dimText
                }
                Text {
                    width: parent.width
                    text: replays.inSession ? i18n.tr("Asking game...")
                        : i18n.tr("Standings show once a session or a replay is loaded in the game.")
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
