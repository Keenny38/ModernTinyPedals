import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Cars of the session by place: class chips (click: that class only), class place, number, driver & team,
// interval to the car ahead in class, battle / pit / status badges. Car on air marked red.
// Click: car sheet, double click or camera button: cut to car.
Item {
    id: root

    property int menuSlot: -1
    property string menuDriver: ""
    signal timingRequested()  // timing table asked (opened by the page)

    // One menu for every row (right click)
    TpMenu {
        id: carMenu
        Action { text: i18n.tr("Cut to this car (double click)"); onTriggered: backend.cutToCar(root.menuSlot) }
        Action { text: i18n.tr("Lap History"); onTriggered: backend.showLaps(root.menuSlot) }
        Action { text: i18n.tr("Car Sheet"); onTriggered: backend.selectCar(root.menuSlot) }
    }

    function tone(name) {
        return name === "loss" ? theme.loss : name === "gain" ? theme.gain : name === "warning" ? theme.warning
             : name === "fastest" ? theme.purple : name === "yellow" ? theme.gold : theme.dimText
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.6
        spacing: theme.em * 0.5

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            Icon { glyph: ""; color: theme.accent }  // car
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Cars") + (backend.carCount > 0 ? "  " + backend.carCount : "")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontSubtitle
                elide: Text.ElideRight
            }
            TpButton {  // timing table of every car
                objectName: "timingButton"
                glyph: "\ue8bc"  // list
                flat: true
                text: root.width > theme.em * 26 ? i18n.tr("Timing") : ""
                tip: i18n.tr("Timing table: race, qualifying & pits views, columns of your choice")
                onClicked: root.timingRequested()
            }
            TpButton { glyph: ""; flat: true; tip: i18n.tr("Previous car") + " (←)"; onClicked: backend.stepCar(-1) }  // chevron left
            TpButton { glyph: ""; flat: true; tip: i18n.tr("Next car") + " (→)"; onClicked: backend.stepCar(1) }  // chevron right
        }

        // Search by number, driver, team: Enter puts the first car found on air
        TpSearchField {
            id: carSearch
            objectName: "carSearch"
            Layout.fillWidth: true
            placeholderText: i18n.tr("Number or driver, Enter: on air")
            onSearchChanged: function(text) { backend.setSearch(text) }
            onExitField: list.forceActiveFocus()
            Keys.onReturnPressed: { flushSearch(); backend.cutToFirstMatch() }
            Keys.onEnterPressed: { flushSearch(); backend.cutToFirstMatch() }
        }

        // Classes: click to see one class only
        Flow {
            Layout.fillWidth: true
            visible: backend.classes.length > 1
            spacing: theme.em * 0.3
            Repeater {
                model: backend.classes
                delegate: AbstractButton {
                    id: chip
                    required property var modelData
                    readonly property bool active: backend.classFilter === modelData.name
                    height: Math.round(theme.em * 1.8)
                    width: chipRow.implicitWidth + theme.em * 1.0
                    hoverEnabled: true
                    focusPolicy: Qt.NoFocus
                    onClicked: backend.setClassFilter(modelData.name)
                    background: Rectangle {
                        radius: height / 2
                        color: chip.active ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.2)
                             : chip.hovered ? theme.hover : theme.raised
                        border.width: 1
                        border.color: chip.active ? theme.accent : theme.border
                    }
                    contentItem: Item {
                        Row {
                            id: chipRow
                            anchors.centerIn: parent
                            spacing: theme.em * 0.4
                            Rectangle {
                                width: theme.em * 0.5; height: width; radius: width / 2
                                color: chip.modelData.color
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text { text: chip.modelData.name; color: theme.text; font.pointSize: theme.fontSmall }
                            Text {
                                text: chip.modelData.count
                                color: theme.dimText
                                font.pointSize: theme.fontSmall
                                font.features: { "tnum": 1 }
                            }
                        }
                    }
                }
            }
        }

        ListView {
            id: list
            objectName: "carList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.carRows
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true
            spacing: 2
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            move: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            moveDisplaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }

            delegate: Rectangle {
                id: row
                required property string key
                required property int slot
                required property int position
                required property int classPosition
                required property string number
                required property string driver
                required property string team
                required property string carClass
                required property string classColor
                required property string classAlias
                required property string interval
                required property string best
                required property bool fastest
                required property int pits
                required property string status
                required property string statusTone
                required property bool onAir
                required property bool battle
                required property int incidents
                required property bool selected
                required property string intervalTone
                required property int gained
                required property string s1Tone
                required property string s2Tone
                required property string s3Tone
                required property string sectorTip
                required property string brandLogo
                required property string tyreFront
                required property string tyreRear
                // Reused row: fed other car values at once, no color animation from the old car
                property bool live: true
                ListView.onPooled: live = false
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.em * 2.7)
                radius: theme.radiusMd
                color: onAir ? Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, rowArea.containsMouse ? 0.24 : 0.16)
                     : theme.rowColor(rowArea.containsMouse, selected)
                border.width: onAir ? 1 : 0
                border.color: theme.loss
                Behavior on color { enabled: row.live; ColorAnimation { duration: theme.motionFast } }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.RightButton) {
                            root.menuSlot = row.slot
                            root.menuDriver = row.driver
                            carMenu.popup()
                        } else {
                            backend.selectCar(row.slot)
                        }
                    }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.cutToCar(row.slot) }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 0
                    anchors.rightMargin: theme.em * 0.2
                    spacing: theme.em * 0.4
                    Column {  // class badge (as overlays: alias & class place), places gained since the start (races)
                        Layout.preferredWidth: theme.em * 4.4
                        TpClassBadge {
                            anchors.horizontalCenter: parent.horizontalCenter
                            label: row.classAlias
                            fullName: row.carClass
                            fill: row.classColor
                            position: row.classPosition > 0 ? String(row.classPosition) : "-"
                        }
                        Text {
                            width: parent.width
                            visible: row.gained !== 0
                            horizontalAlignment: Text.AlignHCenter
                            text: (row.gained > 0 ? "▲" : "▼") + Math.abs(row.gained)
                            color: row.gained > 0 ? theme.gain : theme.loss
                            font.pointSize: theme.fontMicro
                            font.features: { "tnum": 1 }
                            ToolTip.visible: gainedArea.containsMouse
                            ToolTip.text: i18n.tr("Places gained since the start")
                            MouseArea { id: gainedArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 2.4
                        text: row.number !== "" ? "#" + row.number : ""
                        color: theme.dimText
                        font.pointSize: theme.fontLabel
                        font.features: { "tnum": 1 }
                        elide: Text.ElideRight
                    }
                    GameLogo {  // car brand logo of game
                        source: row.brandLogo
                        boxWidth: theme.em * 1.6
                        boxHeight: theme.em * 1.0
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Text {
                            Layout.fillWidth: true
                            text: row.driver
                            color: theme.text
                            font.weight: row.onAir ? Font.Bold : Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: row.status !== "" ? row.status : row.team
                            color: row.status !== "" ? root.tone(row.statusTone) : theme.dimText
                            font.pointSize: theme.fontCaption
                            elide: Text.ElideRight
                        }
                    }
                    Row {  // tyres front & rear (shared memory of the game on this computer)
                        visible: row.tyreFront !== ""
                        spacing: theme.em * 0.2
                        Repeater {
                            model: 2  // front, rear when another compound (badges kept, letters change)
                            delegate: TpCompound {
                                required property int index
                                name: index === 0 ? row.tyreFront : row.tyreRear
                                visible: name !== "" && (index === 0 || row.tyreRear !== row.tyreFront)
                            }
                        }
                    }
                    Icon {  // battle
                        visible: row.battle
                        glyph: ""  // pulse
                        size: theme.em * 0.85
                        color: theme.accent
                    }
                    Icon {  // incidents
                        visible: row.incidents > 0
                        glyph: ""  // lightning
                        size: theme.em * 0.8
                        color: theme.warning
                        ToolTip.visible: incidentArea.containsMouse
                        ToolTip.text: i18n.tr("%1 contacts").arg(row.incidents)
                        MouseArea { id: incidentArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                    Column {  // interval to car ahead (red / amber when close), sectors of the lap
                        Layout.preferredWidth: theme.em * 3.6
                        spacing: theme.em * 0.2
                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignRight
                            text: row.interval
                            color: row.intervalTone !== "" ? root.tone(row.intervalTone) : theme.dimText
                            font.pointSize: theme.fontSmall
                            font.weight: row.intervalTone !== "" ? Font.DemiBold : Font.Normal
                            font.features: { "tnum": 1 }
                            elide: Text.ElideRight
                        }
                        Item {  // sectors: purple best of class, green personal best, yellow slower
                            anchors.right: parent.right
                            width: bars.implicitWidth
                            height: bars.implicitHeight
                            visible: row.s1Tone !== "" || row.s2Tone !== "" || row.s3Tone !== ""
                            ToolTip.visible: sectorArea.containsMouse && row.sectorTip !== ""
                            ToolTip.text: row.sectorTip
                            Row {
                                id: bars
                                spacing: 2
                                Repeater {
                                    model: 3  // bars kept, colors change as sectors complete
                                    delegate: Rectangle {
                                        required property int index
                                        readonly property string toneName: index === 0 ? row.s1Tone : index === 1 ? row.s2Tone : row.s3Tone
                                        width: Math.round(theme.em * 0.75)
                                        height: Math.max(3, Math.round(theme.em * 0.28))
                                        radius: height / 2
                                        color: toneName !== "" ? root.tone(toneName) : theme.border
                                    }
                                }
                            }
                            MouseArea { id: sectorArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                    TpButton {  // cut to car
                        Layout.preferredWidth: Math.round(theme.em * 2.0)
                        Layout.preferredHeight: Math.round(theme.em * 2.0)
                        flat: !row.onAir
                        accent: row.onAir
                        glyph: ""  // camera
                        tip: i18n.tr("Cut to this car (double click)")
                        opacity: row.onAir || rowArea.containsMouse || hovered ? 1 : 0.35
                        onClicked: backend.cutToCar(row.slot)
                    }
                }
            }
        }
    }
}
