import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Recorded laps grouped by session: click to compare (Shift+click: every lap between), flag (or double-click)
// to set reference lap, click a sector time: zoom charts on sector, search by vehicle, session, conditions, note.
// Right-click a lap or a session header: keep, note, move to trash, delta best...
Card {
    id: root

    property var chart  // TraceChart
    property string menuPath: ""
    property bool menuKept: false
    property string anchorPath: ""  // last clicked lap (Shift+click range start)
    property string menuSession: ""  // session header right-clicked

    // Keys back to charts (lap clicked, search left): space, arrows, A/B work again without clicking charts
    function keysToChart() { if (root.chart) root.chart.forceActiveFocus() }

    // Right-click on lap: recorded laps of track can also be kept, noted & deleted
    function openLapMenu(path, item, x, y) {
        var actions = backend.lapActions(path)
        menuPath = path
        menuKept = actions.kept
        if (actions.recorded) recordedMenu.popup(item, x, y)
        else addedMenu.popup(item, x, y)
    }

    TpMenu {
        id: recordedMenu
        Action { text: i18n.tr("Set as Reference"); onTriggered: backend.setReference(root.menuPath) }
        Action { text: i18n.tr("Export MoTeC..."); onTriggered: backend.exportMotec(root.menuPath) }
        MenuSeparator {}
        Action {
            text: i18n.tr("Keep Lap")
            checkable: true
            checked: root.menuKept
            onTriggered: backend.keepLap(root.menuPath, checked)
        }
        Action { text: i18n.tr("Note..."); onTriggered: backend.editNote(root.menuPath) }
        Action { text: i18n.tr("Use as Delta Best..."); onTriggered: backend.exportDeltaBest(root.menuPath) }
        MenuSeparator {}
        Action { text: i18n.tr("Move to Trash"); onTriggered: backend.deleteLap(root.menuPath) }
    }
    TpMenu {
        id: sessionMenu
        Action { text: i18n.tr("Show Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "show") }
        Action { text: i18n.tr("Hide Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "hide") }
        MenuSeparator {}
        Action { text: i18n.tr("Keep Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "keep") }
        Action { text: i18n.tr("Stop Keeping Session Laps"); onTriggered: backend.sessionAction(root.menuSession, "unkeep") }
        MenuSeparator {}
        Action { text: i18n.tr("Move Session Laps to Trash..."); onTriggered: backend.sessionAction(root.menuSession, "delete") }
    }
    TpMenu {
        id: addedMenu
        Action { text: i18n.tr("Set as Reference"); onTriggered: backend.setReference(root.menuPath) }
        Action { text: i18n.tr("Export MoTeC..."); onTriggered: backend.exportMotec(root.menuPath) }
    }
    TpMenu {
        id: selectMenu
        Action { text: i18n.tr("Best vs Last Lap"); onTriggered: backend.compareBestLast() }
        Action { text: i18n.tr("3 Best Laps"); onTriggered: backend.compareBest(3) }
        Action { text: i18n.tr("5 Best Laps"); onTriggered: backend.compareBest(5) }
        MenuSeparator {}
        Action { text: i18n.tr("Uncheck All"); onTriggered: backend.clearSelection() }
        MenuSeparator {}
        Action { text: i18n.tr("Keep Checked Laps"); onTriggered: backend.keepChecked(true) }
        Action { text: i18n.tr("Stop Keeping Checked Laps"); onTriggered: backend.keepChecked(false) }
        Action { text: i18n.tr("Export Checked Laps (MoTeC)..."); onTriggered: backend.exportMotecMany(false) }
        Action { text: i18n.tr("Move Checked Laps to Trash..."); onTriggered: backend.deleteChecked() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.6
        spacing: theme.em * 0.4

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: theme.em * 0.3
            Text {
                text: i18n.tr("Laps")
                color: theme.text
                font.pointSize: theme.fontPoint * 1.25
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            TpButton {
                id: selectButton
                glyph: ""  // multi select
                flat: true
                implicitHeight: theme.em * 1.9
                tip: i18n.tr("Quick selection: best vs last lap, best laps, uncheck all")
                checked: selectMenu.visible
                onClicked: selectMenu.visible ? selectMenu.close() : selectMenu.popup(selectButton, 0, selectButton.height + 4)
            }
            TpSwitch {
                text: i18n.tr("Clean only")
                tip: i18n.tr("Hide invalid, out & in laps")
                checked: backend.hideUnclean
                onToggled: backend.setHideUnclean(checked)
            }
        }

        // Search: every word found in lap name, time, session, vehicle, conditions, note or setup
        TextField {
            id: searchField
            Layout.fillWidth: true
            implicitHeight: Math.round(theme.em * 2.1)
            placeholderText: i18n.tr("Search laps: vehicle, session, note...")
            color: theme.text
            placeholderTextColor: theme.dimText
            rightPadding: theme.em * 2
            text: backend.filterText
            onTextEdited: searchTimer.restart()
            Keys.onEscapePressed: { text = ""; backend.setFilter(""); root.keysToChart() }
            Keys.onReturnPressed: { backend.setFilter(text); root.keysToChart() }
            Keys.onEnterPressed: { backend.setFilter(text); root.keysToChart() }
            Timer { id: searchTimer; interval: 250; onTriggered: backend.setFilter(searchField.text) }
            background: Rectangle {
                radius: theme.em * 0.45
                color: theme.base
                border.width: 1
                border.color: searchField.activeFocus ? theme.accent : theme.border
            }
            Text {
                visible: searchField.text !== ""
                anchors.right: parent.right
                anchors.rightMargin: theme.em * 0.6
                anchors.verticalCenter: parent.verticalCenter
                text: "×"
                color: clearArea.containsMouse ? theme.text : theme.dimText
                font.weight: Font.Bold
                MouseArea {
                    id: clearArea
                    anchors.fill: parent
                    anchors.margins: -4
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { searchField.text = ""; backend.setFilter("") }
                }
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.laps
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Item {
                id: row
                required property int index
                required property string kind
                required property string session
                required property string path
                required property string title
                required property string time
                required property string s1
                required property string s2
                required property string s3
                required property bool best1
                required property bool best2
                required property bool best3
                required property string info
                required property string note
                required property bool checked
                required property bool reference
                required property string color
                required property bool dim
                required property bool fastest
                required property int count
                required property bool error
                required property string gap
                required property string tip

                readonly property bool isSession: kind === "session"
                readonly property bool open: backend.expanded.indexOf(session) >= 0
                width: ListView.view.width - (list.ScrollBar.vertical.visible ? list.ScrollBar.vertical.width : 0)
                height: isSession ? Math.round(theme.em * 2.6) : (open ? Math.round(theme.em * 3.1) : 0)
                clip: true
                opacity: isSession || open ? 1 : 0
                Behavior on height { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: 160 } }

                // Session header
                Item {
                    visible: row.isSession
                    anchors.fill: parent
                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: row.index > 0 ? theme.em * 0.35 : 0
                        radius: theme.em * 0.45
                        color: headerArea.containsMouse ? theme.hover : "transparent"
                        Behavior on color { ColorAnimation { duration: 100 } }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: theme.em * 0.3
                            anchors.rightMargin: theme.em * 0.5
                            spacing: theme.em * 0.4
                            Icon {
                                glyph: ""  // chevron right
                                size: theme.em * 0.75
                                color: theme.dimText
                                rotation: row.open ? 90 : 0
                                Behavior on rotation { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                            }
                            Text {
                                text: row.title
                                color: theme.text
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: row.info
                                visible: text !== ""
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.85
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Rectangle {
                                radius: height / 2
                                color: theme.hover
                                implicitWidth: countText.implicitWidth + theme.em * 0.9
                                implicitHeight: countText.implicitHeight + theme.em * 0.15
                                Text {
                                    id: countText
                                    anchors.centerIn: parent
                                    text: row.count
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.85
                                }
                            }
                            Text {
                                text: row.time
                                color: theme.dimText
                                font.features: { "tnum": 1 }
                            }
                        }
                        MouseArea {
                            id: headerArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function(mouse) {
                                if (mouse.button === Qt.RightButton) {
                                    root.menuSession = row.session
                                    sessionMenu.popup(headerArea, mouse.x, mouse.y)
                                } else {
                                    backend.toggleSession(row.session)
                                    root.keysToChart()
                                }
                            }
                        }
                    }
                }

                // Lap
                Rectangle {
                    visible: !row.isSession
                    anchors.fill: parent
                    anchors.topMargin: 1
                    anchors.bottomMargin: 1
                    radius: theme.em * 0.45
                    color: row.checked ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, lapArea.containsMouse ? 0.16 : 0.10)
                         : lapArea.containsMouse ? theme.hover : "transparent"
                    Behavior on color { ColorAnimation { duration: 120 } }
                    ToolTip.visible: lapArea.containsMouse && (row.tip !== "" || row.error)
                    ToolTip.text: row.error ? i18n.tr("Unable to read this lap file") : row.tip
                    ToolTip.delay: 700

                    // Lap color bar when shown in charts
                    Rectangle {
                        width: 3
                        radius: 1.5
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.margins: theme.em * 0.4
                        color: row.color || "transparent"
                        scale: row.color ? 1 : 0
                        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
                    }

                    MouseArea {
                        id: lapArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: function(mouse) {
                            if (mouse.button === Qt.RightButton) {
                                root.openLapMenu(row.path, lapArea, mouse.x, mouse.y)
                            } else if ((mouse.modifiers & Qt.ShiftModifier) && root.anchorPath !== "") {
                                backend.selectRange(root.anchorPath, row.path, !row.checked)
                                root.keysToChart()
                            } else {
                                backend.toggleLap(row.path)
                                root.anchorPath = row.path
                                root.keysToChart()
                            }
                        }
                        onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.setReference(row.path) }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.em * 1.0
                        anchors.rightMargin: theme.em * 0.4
                        spacing: theme.em * 0.5

                        // Check box (warning if lap file unreadable)
                        Rectangle {
                            implicitWidth: theme.em * 1.15
                            implicitHeight: implicitWidth
                            radius: theme.em * 0.3
                            color: row.error ? theme.warning : row.checked ? (row.color || theme.accent) : "transparent"
                            border.width: row.checked || row.error ? 0 : 1.5
                            border.color: theme.dimText
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Icon {
                                anchors.centerIn: parent
                                glyph: row.error ? "" : ""  // warning, check mark
                                size: theme.em * 0.75
                                color: "white"
                                opacity: row.checked || row.error ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: 120 } }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            RowLayout {
                                spacing: theme.em * 0.35
                                Text {
                                    text: (row.fastest ? "★ " : "") + row.title
                                    color: row.fastest ? theme.gold : theme.text
                                    font.weight: row.reference ? Font.Bold : Font.Normal
                                }
                                Rectangle {
                                    visible: row.reference
                                    radius: theme.em * 0.25
                                    color: theme.accent
                                    implicitWidth: refText.implicitWidth + theme.em * 0.6
                                    implicitHeight: refText.implicitHeight + 2
                                    Text {
                                        id: refText
                                        anchors.centerIn: parent
                                        text: i18n.tr("REF")
                                        color: "white"
                                        font.pointSize: theme.fontPoint * 0.75
                                        font.weight: Font.Bold
                                    }
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    visible: row.gap !== ""
                                    text: row.gap
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.8
                                    font.features: { "tnum": 1 }
                                }
                                Text {
                                    text: row.time
                                    color: row.dim ? theme.dimText : theme.text
                                    font.features: { "tnum": 1 }
                                    font.weight: Font.DemiBold
                                }
                            }
                            RowLayout {
                                spacing: theme.em * 0.6
                                Repeater {
                                    model: [[row.s1, row.best1], [row.s2, row.best2], [row.s3, row.best3]]
                                    Text {
                                        text: modelData[0]
                                        color: sectorArea.containsMouse ? theme.accent : modelData[1] ? theme.purple : theme.dimText
                                        font.pointSize: theme.fontPoint * 0.85
                                        font.features: { "tnum": 1 }
                                        font.weight: modelData[1] ? Font.DemiBold : Font.Normal
                                        MouseArea {
                                            id: sectorArea
                                            anchors.fill: parent
                                            enabled: modelData[0] !== "-" && root.chart !== undefined
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: root.chart.zoomSector(index + 1)
                                            ToolTip.visible: containsMouse
                                            ToolTip.text: i18n.tr("Zoom charts on this sector")
                                            ToolTip.delay: 600
                                        }
                                    }
                                }
                                Text {
                                    text: [row.info, row.note ? "“" + row.note + "”" : ""].filter(Boolean).join(" · ")
                                    color: theme.dimText
                                    font.pointSize: theme.fontPoint * 0.85
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        // Set as reference
                        TpButton {
                            glyph: ""  // flag
                            flat: true
                            implicitHeight: theme.em * 1.9
                            tip: i18n.tr("Set as Reference")
                            opacity: row.reference ? 1 : (lapArea.containsMouse || hovered ? 0.8 : 0)
                            checked: row.reference
                            Behavior on opacity { NumberAnimation { duration: 120 } }
                            onClicked: backend.setReference(row.path)
                        }
                    }
                }
            }
        }

        Text {
            visible: text !== ""
            text: backend.bestText
            color: theme.purple
            font.weight: Font.DemiBold
            Layout.leftMargin: theme.em * 0.3
        }
    }
}
