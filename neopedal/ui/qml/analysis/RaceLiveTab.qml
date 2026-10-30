import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Race calculator live tab: every input value the game gives (car, session, LMU garage screens)
// against the calculator, filled in one by one or all at once (values followed), whether inputs follow each new
// lap (Follow Live), race under way (plan of the rest of the race from now) and tyres the pit menu offers.
// Values followed are also filled in when the Game Session source is chosen & by Follow Live.
Item {
    id: tab
    // Parts notified apart: race time changes at each refresh, rows kept in place (title row before each group)
    readonly property var race: backend.liveRace
    readonly property var tyres: backend.liveTyres
    readonly property bool narrow: width < theme.bpNarrow  // side cards below, source column hidden

    GridLayout {
        anchors.fill: parent
        anchors.topMargin: theme.space3
        columns: tab.narrow ? 1 : 2
        columnSpacing: theme.space4
        rowSpacing: theme.space4

        TpSectionCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 14
            title: i18n.tr("Game data")
            glyph: ""  // pulse
            busy: backend.liveBusy
            tip: i18n.tr("Values of the car, the session and the LMU garage screens (pit stop times, tyres, team): followed values are filled in by the Game Session source, Follow Live and Fill In All")
            actions: [
                RaceSwitch {
                    objectName: "followLiveSwitch"
                    Layout.fillWidth: false
                    wrap: false
                    text: tab.narrow ? "" : i18n.tr("Follow Live")
                    tip: i18n.tr("Inputs follow each new lap of the live session (values followed below)")
                    Accessible.name: i18n.tr("Follow Live")
                    on: backend.header.followLive === true
                    onSwitched: function(on) { backend.setFollowLive(on) }
                },
                TpButton {
                    enabled: !backend.liveBusy
                    flat: true
                    size: "sm"
                    glyph: theme.glyphs.refresh
                    fallback: "⟳"
                    text: tab.narrow ? "" : i18n.tr("Refresh")
                    tip: i18n.tr("Ask game again")
                    onClicked: backend.refreshGarage()
                    Accessible.name: i18n.tr("Refresh")
                },
                TpButton {
                    accent: true
                    size: "sm"
                    enabled: backend.liveDiffering > 0
                    glyph: ""  // check
                    text: i18n.tr("Fill In All") + (backend.liveDiffering > 0 ? " (" + backend.liveDiffering + ")" : "")
                    tip: i18n.tr("Every followed value the game gives goes to the calculator")
                    onClicked: backend.applyAllLive()
                }
            ]
            Text {
                Layout.fillWidth: true
                text: backend.liveDataStatus
                textFormat: Text.PlainText
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.Wrap
            }
            RowLayout {  // header
                Layout.fillWidth: true
                spacing: theme.space3
                Repeater {
                    model: [i18n.tr("Data"), i18n.tr("Game"), i18n.tr("Calculator")]  // widths read by index: kept on resize
                    TpHeaderCell {
                        required property var modelData
                        required property int index
                        Layout.preferredWidth: index === 0 ? list.titleWidth : list.valueWidth
                        text: modelData
                        align: index === 0 ? Qt.AlignLeft : Qt.AlignRight
                    }
                }
                TpHeaderCell {
                    Layout.fillWidth: true
                    visible: !tab.narrow
                    text: i18n.tr("Source")
                }
                Item { Layout.fillWidth: tab.narrow; visible: tab.narrow }
                TpHeaderCell {
                    Layout.preferredWidth: list.actionsWidth
                    text: i18n.tr("Follow")
                    tip: i18n.tr("Filled in by the Game Session source, Follow Live and Fill In All")
                }
            }
            ListView {
                id: list
                objectName: "liveRows"
                readonly property real titleWidth: Math.max(theme.em * 9, width * (tab.narrow ? 0.34 : 0.24))
                readonly property real valueWidth: Math.max(theme.em * 6, width * (tab.narrow ? 0.2 : 0.16))
                readonly property real actionsWidth: theme.em * 5.2
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: theme.em * 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: backend.liveRows
                reuseItems: true
                ScrollBar.vertical: ScrollBar {}
                delegate: Item {
                    id: liveRow
                    required property string key
                    required property bool header
                    required property string title
                    required property string game
                    required property string calc
                    required property string source
                    required property string tip
                    required property bool known
                    required property bool auto
                    required property bool followed
                    required property bool differs
                    property bool live: true  // false while recycled (reuseItems): row look shown at once
                    ListView.onPooled: live = false
                    ListView.onReused: live = true
                    width: list.width
                    height: Math.round(header ? theme.em * 1.9 : theme.rowCompact)

                    TpSectionLabel {  // group title
                        visible: liveRow.header
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: theme.space1
                        width: parent.width
                        text: liveRow.title
                        color: theme.accent
                    }
                    TpListRow {
                        id: rowSurface
                        visible: !liveRow.header
                        anchors.fill: parent
                        anchors.margins: 1
                        radius: theme.radiusSm
                        animate: liveRow.live
                        hovered: rowHover.hovered
                        emphasized: liveRow.differs && liveRow.followed  // game value differs: to fill in
                        HoverHandler { id: rowHover }
                        ToolTip.visible: rowHover.hovered && liveRow.tip !== ""
                        ToolTip.text: liveRow.tip
                        ToolTip.delay: theme.tipDelay
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: theme.space2
                            spacing: theme.space3
                            // Value the game does not give (rough estimate): dim text, never faded by opacity
                            Text {
                                Layout.preferredWidth: list.titleWidth - theme.space2
                                text: liveRow.title
                                textFormat: Text.PlainText
                                color: liveRow.known ? theme.text : theme.dimOn(rowSurface.color)
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: list.valueWidth
                                text: liveRow.game + (liveRow.differs ? " ●" : "")  // differs: mark too, not only color
                                textFormat: Text.PlainText
                                color: liveRow.differs ? theme.accent : liveRow.known ? theme.text : theme.dimOn(rowSurface.color)
                                font.weight: liveRow.differs ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                                horizontalAlignment: Text.AlignRight
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: list.valueWidth
                                text: liveRow.calc
                                textFormat: Text.PlainText
                                color: theme.dimOn(rowSurface.color)
                                font.features: { "tnum": 1 }
                                horizontalAlignment: Text.AlignRight
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: !tab.narrow
                                leftPadding: theme.space3
                                text: liveRow.source
                                textFormat: Text.PlainText
                                color: theme.dimOn(rowSurface.color)
                                font.pointSize: theme.fontSmall
                                elide: Text.ElideRight
                            }
                            Item { Layout.fillWidth: tab.narrow; visible: tab.narrow }
                            Row {
                                Layout.preferredWidth: list.actionsWidth
                                spacing: theme.space2
                                RaceSwitch {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: theme.em * 2.6
                                    wrap: false
                                    enabled: liveRow.auto
                                    on: liveRow.followed
                                    tip: liveRow.auto ? i18n.tr("Filled in by the Game Session source, Follow Live and Fill In All")
                                                                : i18n.tr("Rough estimate: fill it in by hand")
                                    onSwitched: function(on) { backend.setLiveFollowed(liveRow.key, on) }
                                    Accessible.name: liveRow.title
                                }
                                TpButton {
                                    anchors.verticalCenter: parent.verticalCenter
                                    size: "xs"
                                    flat: true
                                    enabled: liveRow.differs
                                    glyph: ""  // arrow: to the calculator
                                    fallback: "→"
                                    tip: i18n.tr("Fill In") + ": " + liveRow.game
                                    onClicked: backend.applyLiveValue(liveRow.key)
                                    Accessible.name: i18n.tr("Fill In") + " " + liveRow.title
                                }
                            }
                        }
                    }
                }
            }
        }

        ScrollView {  // race under way & tyres offered
            id: side
            Layout.fillWidth: tab.narrow
            Layout.fillHeight: true
            Layout.preferredWidth: tab.narrow ? -1 : theme.em * 21
            Layout.maximumHeight: tab.narrow ? theme.em * 16 : Number.POSITIVE_INFINITY
            Layout.minimumHeight: theme.em * 8
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: side.availableWidth
                spacing: theme.space4

                TpSectionCard {
                    title: i18n.tr("Race in Progress")
                    glyph: ""  // flag
                    RaceSwitch {  // live race: plan of the rest of the race (also proposed above the page in a race)
                        objectName: "liveRaceSwitch"
                        text: i18n.tr("Plan From Now")
                        tip: i18n.tr("During a race: plan of the rest of the race from now (laps & time done, fuel, energy & tyres of the car, stops done)")
                        on: backend.header.liveRace === true
                        onSwitched: function(on) { backend.setLiveRace(on) }
                    }
                    Text {  // plan from lap N, in the pits, safety car... (values read in its tooltip)
                        Layout.fillWidth: true
                        visible: backend.liveStatus !== ""
                        text: backend.liveStatus
                        textFormat: Text.PlainText
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        wrapMode: Text.Wrap
                        HoverHandler { id: statusHover; enabled: backend.liveTip !== "" }
                        ToolTip.visible: statusHover.hovered
                        ToolTip.text: backend.liveTip
                        ToolTip.delay: theme.tipDelay
                    }
                    Repeater {
                        model: tab.race.length  // count: rows kept while the values change at each refresh
                        TpKeyValue {
                            required property int index
                            readonly property var item: tab.race[index] || ({})
                            label: item.title || ""
                            value: item.value || ""
                            warning: item.warning === true
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: tab.race.length === 0
                        text: i18n.tr("Shown during a race of the game.")
                        color: theme.dimText
                        wrapMode: Text.Wrap
                    }
                }

                TpSectionCard {
                    title: i18n.tr("Tyres Available")
                    glyph: ""  // car
                    tip: i18n.tr("Tyres the pit menu offers (LMU): new compounds and used tyres of each wheel with their tread")
                    Text {
                        Layout.fillWidth: true
                        visible: tab.tyres.known !== true
                        text: i18n.tr("No tyre data: LMU in a session needed (pit menu).")
                        color: theme.dimText
                        wrapMode: Text.Wrap
                    }
                    TpKeyValue {
                        visible: (tab.tyres.allowed || 0) > 0
                        label: i18n.tr("Maximum Tyres")
                        value: String(tab.tyres.allowed || 0)
                    }
                    TpKeyValue {
                        visible: (tab.tyres.allowed || 0) > 0 && (tab.tyres.newLeft !== undefined ? tab.tyres.newLeft : -1) >= 0
                        label: i18n.tr("New Left")
                        value: String(tab.tyres.newLeft !== undefined ? tab.tyres.newLeft : "")
                    }
                    Flow {  // new compounds: badge (as overlays) & name each
                        Layout.fillWidth: true
                        visible: (tab.tyres.newCompounds || []).length > 0
                        spacing: theme.em * 0.5
                        Text { text: i18n.tr("New Tyres") + ":"; color: theme.text }
                        Repeater {
                            model: tab.tyres.newCompounds || []
                            Row {
                                required property string modelData
                                spacing: theme.space2
                                TpCompound { name: parent.modelData; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: parent.modelData; color: theme.text; anchors.verticalCenter: parent.verticalCenter; textFormat: Text.PlainText }
                            }
                        }
                    }
                    TpButton {
                        visible: (tab.tyres.used || 0) > 0
                        size: "sm"
                        glyph: theme.glyphs.add
                        text: i18n.tr("Add Used Tyres to Stock")
                        tip: i18n.tr("Used tyres the pit menu offers go to the tyre stock (Tyres tab) with their tread, to fit them by hand")
                        onClicked: backend.addGameTyres()
                    }
                    Repeater {
                        model: (tab.tyres.wheels || []).length  // count: rows kept when tyres change
                        RowLayout {
                            id: wheelRow
                            required property int index
                            readonly property var wheel: (tab.tyres.wheels || [])[index] || ({ wheel: "", tyres: [] })
                            Layout.fillWidth: true
                            spacing: theme.space3
                            Text {
                                Layout.preferredWidth: theme.em * 7.5
                                Layout.alignment: Qt.AlignTop
                                text: wheelRow.wheel.wheel
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: theme.dimText
                                font.weight: Font.DemiBold
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: theme.space2
                                Text {
                                    visible: wheelRow.wheel.tyres.length === 0
                                    text: i18n.tr("No used tyre")
                                    color: theme.dimText
                                    font.pointSize: theme.fontSmall
                                }
                                Repeater {
                                    model: wheelRow.wheel.tyres.length
                                    Rectangle {
                                        required property int index
                                        id: usedChip
                                        readonly property var chip: wheelRow.wheel.tyres[index] || ({ text: "", color: "transparent", tip: "", compound: "" })
                                        implicitWidth: chipRow.implicitWidth + theme.em * 0.9
                                        implicitHeight: Math.round(theme.em * 1.5)
                                        radius: height / 2
                                        color: "transparent"
                                        border.width: 1
                                        border.color: chip.color
                                        Accessible.role: Accessible.StaticText
                                        Accessible.name: (chip.compound || "") + " " + (chip.text || "")
                                        Row {  // compound badge (as overlays), name & tread in tread color
                                            id: chipRow
                                            anchors.centerIn: parent
                                            spacing: theme.space2
                                            TpCompound {
                                                name: usedChip.chip.compound || ""
                                                width: Math.round(theme.em * 0.9)
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                            Text {
                                                text: usedChip.chip.text
                                                textFormat: Text.PlainText
                                                color: usedChip.chip.color
                                                font.pointSize: theme.fontSmall
                                                font.features: { "tnum": 1 }
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                        }
                                        HoverHandler { id: chipHover }
                                        ToolTip.visible: chipHover.hovered
                                        ToolTip.text: chip.tip
                                        ToolTip.delay: theme.tipDelay
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
