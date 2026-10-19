import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Cars of the session by place: class chips (click: that class only), class place, number, driver & team,
// interval to the car ahead in class, battle / pit / status badges. Car on air marked red (tint & frame).
// Click: car sheet, double click or camera button: cut to car. "/": search.
// Keys in the list: Up / Down move, Enter opens the car sheet, Menu key the car menu.
Item {
    id: root

    property int menuSlot: -1
    property string menuDriver: ""
    signal timingRequested()  // timing table asked (opened by the page)

    function focusSearch() {
        carSearch.forceActiveFocus()
        carSearch.selectAll()
    }
    function openMenu(slot, driver, item, x, y) {
        root.menuSlot = slot
        root.menuDriver = driver
        carMenu.popup(item, x, y)
    }

    // Text being typed (notes, settings): "/" is a character there
    readonly property bool typing: Window.activeFocusItem !== null && Window.activeFocusItem.cursorPosition !== undefined
    Shortcut {
        sequence: "/"
        enabled: pageState.active && carSearch.visible && !root.typing
        onActivated: root.focusSearch()
    }

    // One menu for every row (right click, Menu key)
    TpMenu {
        id: carMenu
        Action { text: i18n.tr("Cut to this car (double click)"); onTriggered: backend.cutToCar(root.menuSlot) }
        Action { text: i18n.tr("Lap History"); onTriggered: backend.showLaps(root.menuSlot) }
        Action { text: i18n.tr("Car Sheet"); onTriggered: backend.selectCar(root.menuSlot) }
        onClosed: list.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.em * 0.5

        TpCardHeader {
            glyph: ""  // car
            title: i18n.tr("Cars")
            count: backend.carCount > 0 ? String(backend.carCount) : ""
            TpButton {  // timing table of every car
                objectName: "timingButton"
                glyph: ""  // list
                fallback: i18n.tr("Timing")
                flat: true
                size: "sm"
                text: root.width > theme.em * 26 ? i18n.tr("Timing") : ""  // content-tuned: header fits the text
                tip: i18n.tr("Timing table: race, qualifying & pits views, columns of your choice")
                onClicked: root.timingRequested()
            }
            TpButton { glyph: ""; fallback: "‹"; flat: true; size: "sm"; tip: i18n.tr("Previous car") + " (←)"; onClicked: backend.stepCar(-1) }  // chevron left
            TpButton { glyph: ""; fallback: "›"; flat: true; size: "sm"; tip: i18n.tr("Next car") + " (→)"; onClicked: backend.stepCar(1) }  // chevron right
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
            spacing: theme.space2
            Repeater {
                model: backend.classes
                delegate: TpChip {
                    required property var modelData
                    size: "sm"
                    text: modelData.name
                    showDot: true
                    dotColor: modelData.color
                    count: modelData.count
                    selected: backend.classFilter === modelData.name
                    onClicked: backend.setClassFilter(modelData.name)
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
            activeFocusOnTab: true
            keyNavigationEnabled: true
            highlightFollowsCurrentItem: false
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            move: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            moveDisplaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            displaced: Transition { NumberAnimation { properties: "y"; duration: theme.motionBase; easing.type: Easing.OutCubic } }
            // Enter is the list's (car sheet), not the page's "take best"
            Keys.onShortcutOverride: function(event) {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                    event.accepted = true
            }
            Keys.onReturnPressed: if (currentItem) backend.selectCar(currentItem.slot)
            Keys.onEnterPressed: if (currentItem) backend.selectCar(currentItem.slot)
            Keys.onMenuPressed: if (currentItem) root.openMenu(currentItem.slot, currentItem.driver, currentItem, currentItem.width / 2, currentItem.height / 2)
            onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0

            delegate: Item {
                id: row
                required property int index
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
                readonly property bool current: ListView.isCurrentItem && list.activeFocus
                // Reused row: fed other car values at once, no color animation from the old car
                property bool live: true
                ListView.onPooled: live = false
                ListView.onReused: live = true

                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: Math.round(theme.row)
                Accessible.role: Accessible.ListItem
                Accessible.name: [row.position > 0 ? "P" + row.position : "", row.number !== "" ? "#" + row.number : "", row.driver,
                                  row.onAir ? i18n.tr("On Air") : "", row.status].filter(function(part) { return part !== "" }).join(", ")

                TpListRow {  // car on air: loss tint & frame (shape cue), selected: car sheet open
                    id: rowBack
                    anchors.fill: parent
                    animate: row.live
                    hovered: rowArea.containsMouse
                    selected: row.selected
                    emphasized: row.onAir
                    tint: row.onAir ? theme.loss : theme.accent
                    border.width: row.onAir ? 1 : 0
                    border.color: theme.loss
                }
                FocusRing { target: rowBack; visible: row.current }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function(mouse) {
                        list.currentIndex = row.index
                        if (mouse.button === Qt.RightButton)
                            root.openMenu(row.slot, row.driver, rowArea, mouse.x, mouse.y)
                        else
                            backend.selectCar(row.slot)
                    }
                    onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.cutToCar(row.slot) }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 0
                    anchors.rightMargin: theme.space1
                    spacing: theme.space3
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
                            ToolTip.delay: theme.tipDelay
                            MouseArea { id: gainedArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                    Text {
                        Layout.preferredWidth: theme.em * 2.4
                        text: row.number !== "" ? "#" + row.number : ""
                        color: theme.dimOn(rowBack.color)
                        font.pointSize: theme.fontLabel
                        font.features: { "tnum": 1 }
                        elide: Text.ElideRight
                    }
                    Item {  // car brand logo of game: room kept, names stay aligned while logos load
                        Layout.preferredWidth: theme.em * 1.6
                        Layout.preferredHeight: theme.em * 1.0
                        GameLogo {
                            anchors.centerIn: parent
                            source: row.brandLogo
                            boxWidth: theme.em * 1.6
                            boxHeight: theme.em * 1.0
                        }
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
                            color: row.status !== "" ? theme.tone(row.statusTone) : theme.dimOn(rowBack.color)
                            font.pointSize: theme.fontCaption
                            elide: Text.ElideRight
                        }
                    }
                    Row {  // tyres front & rear (shared memory of the game on this computer)
                        visible: row.tyreFront !== ""
                        spacing: theme.space1
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
                        fallback: "↔"
                        size: theme.em * 0.85
                        color: theme.accent
                        ToolTip.visible: battleArea.containsMouse
                        ToolTip.text: i18n.tr("Battles")
                        ToolTip.delay: theme.tipDelay
                        MouseArea { id: battleArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                    Icon {  // incidents
                        visible: row.incidents > 0
                        glyph: ""  // lightning
                        fallback: "!"
                        size: theme.em * 0.8
                        color: theme.warning
                        ToolTip.visible: incidentArea.containsMouse
                        ToolTip.text: i18n.tr("%1 contacts").arg(row.incidents)
                        ToolTip.delay: theme.tipDelay
                        MouseArea { id: incidentArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                    Column {  // interval to car ahead (red / amber & bold when close), sectors of the lap
                        Layout.preferredWidth: theme.em * 3.6
                        spacing: theme.space1
                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignRight
                            text: row.interval
                            color: row.intervalTone !== "" ? theme.tone(row.intervalTone) : theme.dimOn(rowBack.color)
                            font.pointSize: theme.fontSmall
                            font.weight: row.intervalTone !== "" ? Font.DemiBold : Font.Normal
                            font.features: { "tnum": 1 }
                            elide: Text.ElideRight
                        }
                        Item {  // sectors: purple best of class (tallest bar), green personal best (middle), yellow slower (low)
                            anchors.right: parent.right
                            width: bars.implicitWidth
                            height: Math.round(theme.em * 0.5)
                            visible: row.s1Tone !== "" || row.s2Tone !== "" || row.s3Tone !== ""
                            ToolTip.visible: sectorArea.containsMouse && row.sectorTip !== ""
                            ToolTip.text: row.sectorTip
                            ToolTip.delay: theme.tipDelay
                            Row {
                                id: bars
                                anchors.bottom: parent.bottom
                                spacing: 2
                                Repeater {
                                    model: 3  // bars kept, colors & heights change as sectors complete
                                    delegate: Rectangle {
                                        required property int index
                                        readonly property string toneName: index === 0 ? row.s1Tone : index === 1 ? row.s2Tone : row.s3Tone
                                        // Height tells the sector kind without color (colorblind): best > personal > other
                                        readonly property real level: toneName === "fastest" ? 0.5 : toneName === "gain" ? 0.38 : 0.26
                                        anchors.bottom: parent.bottom
                                        width: Math.round(theme.em * 0.75)
                                        height: Math.max(3, Math.round(theme.em * level))
                                        radius: Math.min(height, width) / 2
                                        color: toneName !== "" ? theme.tone(toneName) : theme.border
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
                        fallback: "◎"
                        tip: i18n.tr("Cut to this car (double click)")
                        opacity: row.onAir || rowArea.containsMouse || hovered || visualFocus || row.current ? 1 : 0.4
                        onClicked: backend.cutToCar(row.slot)
                    }
                }
            }
        }
    }
}
