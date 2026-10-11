import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Race calculator live tab: every input value the game gives (car, session, LMU garage screens)
// against the calculator, filled in one by one or all at once (values followed), race under way
// and tyres the pit menu offers. Values followed are also filled in by Load Live & Follow Live.
Item {
    id: tab
    readonly property var live: backend.liveData
    readonly property var rows: live.rows || []
    readonly property var groups: live.groups || []
    readonly property var race: live.race || []
    readonly property var tyres: live.tyres || ({})
    readonly property bool narrow: width < theme.em * 58  // side cards below, source column hidden
    // Rows with a title row before each group
    readonly property var items: {
        const list = []
        for (const group of tab.groups) {
            const members = tab.rows.filter(row => row.group === group.key)
            if (members.length === 0)
                continue
            list.push({ header: true, title: group.title })
            for (const row of members)
                list.push(row)
        }
        return list
    }

    GridLayout {
        anchors.fill: parent
        anchors.topMargin: theme.em * 0.4
        columns: tab.narrow ? 1 : 2
        columnSpacing: theme.em * 0.6
        rowSpacing: theme.em * 0.6

        RaceCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: theme.em * 14
            title: i18n.tr("Game data")
            glyph: ""  // pulse
            tip: i18n.tr("Values of the car, the session and the LMU garage screens (pit stop times, tyres, team): followed values are filled in by Load Live, Follow Live and Fill In All")
            actions: [
                TpButton {
                    enabled: !tab.live.busy
                    flat: true
                    glyph: ""  // refresh
                    text: tab.narrow ? "" : i18n.tr("Refresh")
                    tip: i18n.tr("Ask game again")
                    onClicked: backend.refreshGarage()
                    Accessible.name: i18n.tr("Refresh")
                },
                TpButton {
                    accent: true
                    enabled: (tab.live.differing || 0) > 0
                    glyph: ""  // check
                    text: i18n.tr("Fill In All") + ((tab.live.differing || 0) > 0 ? " (" + tab.live.differing + ")" : "")
                    tip: i18n.tr("Every followed value the game gives goes to the calculator")
                    onClicked: backend.applyAllLive()
                }
            ]
            Text {
                Layout.fillWidth: true
                text: tab.live.status || ""
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.88
                wrapMode: Text.Wrap
            }
            RowLayout {  // header
                Layout.fillWidth: true
                spacing: theme.em * 0.4
                Repeater {
                    model: [
                        { text: i18n.tr("Data"), width: list.titleWidth },
                        { text: i18n.tr("Game"), width: list.valueWidth },
                        { text: i18n.tr("Calculator"), width: list.valueWidth },
                    ]
                    Text {
                        required property var modelData
                        Layout.preferredWidth: modelData.width
                        text: modelData.text
                        color: theme.dimText
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontPoint * 0.88
                        elide: Text.ElideRight
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: !tab.narrow
                    text: i18n.tr("Source")
                    color: theme.dimText
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontPoint * 0.88
                    elide: Text.ElideRight
                }
                Item { Layout.fillWidth: tab.narrow; implicitWidth: 1 }
                Text {
                    Layout.preferredWidth: list.actionsWidth
                    text: i18n.tr("Follow")
                    color: theme.dimText
                    font.weight: Font.DemiBold
                    font.pointSize: theme.fontPoint * 0.88
                    elide: Text.ElideRight
                    HoverHandler { id: followHover }
                    ToolTip.visible: followHover.hovered
                    ToolTip.text: i18n.tr("Filled in by Load Live, Follow Live and Fill In All")
                    ToolTip.delay: 500
                }
            }
            ListView {
                id: list
                readonly property real titleWidth: Math.max(theme.em * 9, width * (tab.narrow ? 0.34 : 0.24))
                readonly property real valueWidth: Math.max(theme.em * 6, width * (tab.narrow ? 0.2 : 0.16))
                readonly property real actionsWidth: theme.em * 5.2
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: theme.em * 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: tab.items
                ScrollBar.vertical: ScrollBar {}
                delegate: Item {
                    id: liveRow
                    required property var modelData
                    required property int index
                    readonly property bool header: modelData.header === true
                    readonly property bool differs: !header && modelData.differs === true
                    width: list.width
                    height: Math.round(theme.em * (header ? 1.9 : 1.85))

                    Text {  // group title
                        visible: liveRow.header
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: theme.em * 0.2
                        text: liveRow.modelData.title || ""
                        color: theme.accent
                        font.weight: Font.DemiBold
                        font.pointSize: theme.fontPoint * 0.9
                    }
                    Rectangle {
                        visible: !liveRow.header
                        anchors.fill: parent
                        radius: theme.em * 0.3
                        opacity: liveRow.modelData.known ? 1 : 0.55
                        color: liveRow.differs && liveRow.modelData.followed
                               ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.dark ? 0.16 : 0.1)
                               : rowHover.hovered ? theme.hover : "transparent"
                        HoverHandler { id: rowHover }
                        ToolTip.visible: rowHover.hovered && (liveRow.modelData.tip || "") !== ""
                        ToolTip.text: liveRow.modelData.tip || ""
                        ToolTip.delay: 500
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: theme.em * 0.3
                            spacing: theme.em * 0.4
                            Text {
                                Layout.preferredWidth: list.titleWidth - theme.em * 0.3
                                text: liveRow.modelData.title || ""
                                color: theme.text
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: list.valueWidth
                                text: liveRow.modelData.game || ""
                                color: liveRow.differs ? theme.accent : theme.text
                                font.weight: liveRow.differs ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: list.valueWidth
                                text: liveRow.modelData.calc || ""
                                color: theme.dimText
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: !tab.narrow
                                text: liveRow.modelData.source || ""
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.85
                                elide: Text.ElideRight
                            }
                            Item { Layout.fillWidth: tab.narrow; implicitWidth: 1 }
                            Row {
                                Layout.preferredWidth: list.actionsWidth
                                spacing: theme.em * 0.3
                                RaceSwitch {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: theme.em * 2.6
                                    enabled: liveRow.modelData.auto === true
                                    on: liveRow.modelData.followed === true
                                    tip: liveRow.modelData.auto ? i18n.tr("Filled in by Load Live, Follow Live and Fill In All")
                                                                : i18n.tr("Rough estimate: fill it in by hand")
                                    onSwitched: function(on) { backend.setLiveFollowed(liveRow.modelData.key, on) }
                                    Accessible.name: liveRow.modelData.title || ""
                                }
                                TpButton {
                                    anchors.verticalCenter: parent.verticalCenter
                                    implicitHeight: Math.round(theme.em * 1.6)
                                    flat: true
                                    enabled: liveRow.differs
                                    glyph: ""  // arrow: to the calculator
                                    tip: i18n.tr("Fill In") + ": " + (liveRow.modelData.game || "")
                                    onClicked: backend.applyLiveValue(liveRow.modelData.key)
                                    Accessible.name: i18n.tr("Fill In") + " " + (liveRow.modelData.title || "")
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
                spacing: theme.em * 0.6

                RaceCard {
                    title: i18n.tr("Race in Progress")
                    glyph: ""  // flag
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: theme.em * 0.6
                        rowSpacing: theme.em * 0.25
                        visible: tab.race.length > 0
                        Repeater {
                            model: tab.race.length * 2
                            Text {
                                required property int index
                                readonly property var item: tab.race[Math.floor(index / 2)] || ({})
                                readonly property bool isValue: index % 2 === 1
                                Layout.fillWidth: isValue
                                text: isValue ? (item.value || "") : (item.title || "")
                                color: isValue && item.warning ? theme.loss : isValue ? theme.text : theme.dimText
                                font.weight: isValue ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                                horizontalAlignment: isValue ? Text.AlignRight : Text.AlignLeft
                                elide: Text.ElideRight
                            }
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

                RaceCard {
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
                    Text {
                        Layout.fillWidth: true
                        visible: (tab.tyres.allowed || 0) > 0
                        text: i18n.tr("Maximum Tyres") + ": <b>" + (tab.tyres.allowed || 0) + "</b>"
                              + ((tab.tyres.newLeft !== undefined ? tab.tyres.newLeft : -1) >= 0 ? " · " + i18n.tr("New Left") + ": <b>" + tab.tyres.newLeft + "</b>" : "")
                        textFormat: Text.StyledText
                        color: theme.text
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: (tab.tyres.newCompounds || []).length > 0
                        text: i18n.tr("New Tyres") + ": " + (tab.tyres.newCompounds || []).join(", ")
                        color: theme.text
                        wrapMode: Text.Wrap
                    }
                    TpButton {
                        visible: (tab.tyres.used || 0) > 0
                        glyph: "\uE710"  // add
                        text: i18n.tr("Add Used Tyres to Stock")
                        tip: i18n.tr("Used tyres the pit menu offers go to the tyre stock (Tyres tab) with their tread, to fit them by hand")
                        onClicked: backend.addGameTyres()
                    }
                    Repeater {
                        model: tab.tyres.wheels || []
                        RowLayout {
                            id: wheelRow
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: theme.em * 0.4
                            Text {
                                Layout.preferredWidth: theme.em * 7.5
                                text: wheelRow.modelData.wheel
                                elide: Text.ElideRight
                                color: theme.dimText
                                font.weight: Font.DemiBold
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: theme.em * 0.3
                                Text {
                                    visible: wheelRow.modelData.tyres.length === 0
                                    text: i18n.tr("No used tyre")
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.88
                                }
                                Repeater {
                                    model: wheelRow.modelData.tyres
                                    Rectangle {
                                        required property var modelData
                                        implicitWidth: chipText.implicitWidth + theme.em * 0.9
                                        implicitHeight: Math.round(theme.em * 1.5)
                                        radius: height / 2
                                        color: Qt.rgba(0, 0, 0, 0)
                                        border.width: 1
                                        border.color: modelData.color
                                        Text {
                                            id: chipText
                                            anchors.centerIn: parent
                                            text: parent.modelData.text
                                            color: parent.modelData.color
                                            font.pointSize: theme.fontPoint * 0.85
                                            font.features: { "tnum": 1 }
                                        }
                                        HoverHandler { id: chipHover }
                                        ToolTip.visible: chipHover.hovered
                                        ToolTip.text: modelData.tip
                                        ToolTip.delay: 400
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
