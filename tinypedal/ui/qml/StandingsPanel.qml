import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Standings of the session (or replay) open in game: class chips (click: that class only), cars by position with
// class color, number, driver & car, laps, best lap (purple: fastest of class), last lap, gap, pit stops, status,
// incidents (click: incidents of driver). Car followed by camera marked; double click or camera button: camera on car.
Item {
    id: root

    readonly property bool wide: width > theme.em * (backend.hasEnergy ? 47 : 40)  // last lap column shown
    readonly property real cellPad: theme.em * 0.35
    property string menuKey: ""
    property string menuDriver: ""

    function tone(name) { return name === "loss" ? theme.loss : name === "gain" ? theme.gain : name === "warning" ? theme.warning : theme.dimText }
    function showSelected() {
        var index = backend.carIndex(backend.selectedCar)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
    }

    TpMenu {
        id: rowMenu
        Action {
            text: i18n.tr("Camera on This Car")
            enabled: backend.inSession
            onTriggered: backend.watchCar(root.menuKey)
        }
        Action {
            text: i18n.tr("Go to Lap...")
            enabled: backend.replayActive
            onTriggered: backend.goToLap(root.menuKey)
        }
        Action {
            text: i18n.tr("Incidents of %1").arg(root.menuDriver)
            onTriggered: backend.showDriverIncidents(root.menuDriver)
        }
    }

    component HeaderText: Text {
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.8
        font.weight: Font.DemiBold
        elide: Text.ElideRight
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        anchors.topMargin: 0
        spacing: theme.em * 0.45

        // Classes: click to see one class only
        ListView {
            id: classes
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(theme.em * 2.0)
            visible: count > 1
            orientation: ListView.Horizontal
            spacing: theme.em * 0.35
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: backend.classes
            delegate: AbstractButton {
                id: chip
                required property var modelData
                readonly property bool active: backend.classFilter === modelData.name
                height: classes.height
                width: chipRow.implicitWidth + theme.em * 1.1
                hoverEnabled: true
                focusPolicy: Qt.NoFocus
                onClicked: backend.setClassFilter(modelData.name)
                background: Rectangle {
                    radius: height / 2
                    color: chip.active ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.2)
                         : chip.hovered ? theme.hover : theme.raised
                    border.width: 1
                    border.color: chip.active ? theme.accent : theme.border
                    Behavior on color { ColorAnimation { duration: 120 } }
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
                        Text { text: chip.modelData.name; color: theme.text; font.pointSize: theme.fontPoint * 0.9 }
                        Text {
                            text: chip.modelData.count
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.9
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
        }

        // Last session (game in menus): standings kept
        Text {
            visible: backend.lastSession && list.count > 0
            text: i18n.tr("Last Session")
            color: theme.warning
            font.pointSize: theme.fontPoint * 0.85
            font.weight: Font.DemiBold
        }

        // Column titles, lined up with row cells (same margins, scroll bar room)
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: theme.em * 0.35
            Layout.rightMargin: theme.em * 0.2 + (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
            visible: list.count > 0
            spacing: root.cellPad
            HeaderText { text: i18n.tr("Pos"); Layout.preferredWidth: theme.em * 2.4; horizontalAlignment: Text.AlignHCenter }
            HeaderText { text: i18n.tr("Driver"); Layout.fillWidth: true }
            HeaderText { text: i18n.tr("Laps"); Layout.preferredWidth: theme.em * 2.4; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Best"); Layout.preferredWidth: theme.em * 4.9; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Last"); visible: root.wide; Layout.preferredWidth: theme.em * 4.9; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Gap"); Layout.preferredWidth: theme.em * 4.6; horizontalAlignment: Text.AlignRight }
            HeaderText { text: i18n.tr("Pit"); Layout.preferredWidth: theme.em * 3.2; horizontalAlignment: Text.AlignHCenter }
            HeaderText { text: i18n.tr("Energy"); visible: backend.hasEnergy; Layout.preferredWidth: theme.em * 3.8; horizontalAlignment: Text.AlignHCenter }
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
            model: backend.standingRows
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onUpPressed: { backend.moveCarSelection(-1); root.showSelected() }
            Keys.onDownPressed: { backend.moveCarSelection(1); root.showSelected() }
            Keys.onReturnPressed: backend.watchCar(backend.selectedCar)
            Keys.onEnterPressed: backend.watchCar(backend.selectedCar)
            move: Transition { NumberAnimation { properties: "y"; duration: 250; easing.type: Easing.OutCubic } }
            moveDisplaced: Transition { NumberAnimation { properties: "y"; duration: 250; easing.type: Easing.OutCubic } }
            displaced: Transition { NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic } }

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
                readonly property bool selected: key === backend.selectedCar

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 2.9)
                radius: theme.em * 0.45
                color: selected ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, rowArea.containsMouse ? 0.22 : 0.15)
                     : row.player ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.07)
                     : rowArea.containsMouse ? theme.hover : "transparent"
                Behavior on color { ColorAnimation { duration: 110 } }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: { list.forceActiveFocus(); backend.selectCar(row.key) }
                    onClicked: function(mouse) {
                        if (mouse.button !== Qt.RightButton) return
                        root.menuKey = row.key
                        root.menuDriver = row.driver
                        rowMenu.popup(rowArea, mouse.x, mouse.y)
                    }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.watchCar(row.key) }
                }
                Rectangle {  // class color
                    x: 2
                    width: 3
                    height: parent.height - theme.em * 0.7
                    anchors.verticalCenter: parent.verticalCenter
                    radius: 1.5
                    color: row.classColor
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: theme.em * 0.35
                    anchors.rightMargin: theme.em * 0.2
                    spacing: root.cellPad

                    Column {  // position, class position when several classes
                        Layout.preferredWidth: theme.em * 2.4
                        Text {
                            width: parent.width
                            text: row.position > 0 ? row.position : "-"
                            color: theme.text
                            font.weight: Font.Bold
                            font.features: { "tnum": 1 }
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            width: parent.width
                            visible: classes.count > 1
                            text: row.classPosition
                            color: row.classColor
                            font.pointSize: theme.fontPoint * 0.75
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.35
                            Rectangle {  // car number
                                visible: row.number !== ""
                                implicitWidth: Math.max(numberText.implicitWidth + theme.em * 0.5, theme.em * 1.6)
                                implicitHeight: numberText.implicitHeight + 2
                                radius: theme.em * 0.25
                                color: Qt.rgba(theme.text.r, theme.text.g, theme.text.b, 0.1)
                                Text {
                                    id: numberText
                                    anchors.centerIn: parent
                                    text: row.number
                                    color: theme.text
                                    font.pointSize: theme.fontPoint * 0.8
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
                            spacing: theme.em * 0.35
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
                                    font.pointSize: theme.fontPoint * 0.72
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
                                font.pointSize: theme.fontPoint * 0.78
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
                        visible: backend.hasEnergy
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
                        onClicked: backend.showDriverIncidents(row.driver)
                        ToolTip.visible: hovered
                        ToolTip.text: i18n.tr("Incidents of %1").arg(row.driver)
                        ToolTip.delay: 400
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
                                    font.pointSize: theme.fontPoint * 0.8
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
                        TpButton {
                            anchors.fill: parent
                            visible: !row.onCamera && backend.inSession && (row.selected || rowArea.containsMouse || hovered)
                            flat: true
                            glyph: ""
                            tip: i18n.tr("Camera on This Car") + " (" + i18n.tr("double click") + ")"
                            onClicked: backend.watchCar(row.key)
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
                    text: backend.inSession ? i18n.tr("Asking game...")
                        : i18n.tr("Standings show once a session or a replay is loaded in the game.")
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
