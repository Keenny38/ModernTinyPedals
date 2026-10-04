import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Recorded laps grouped by session: click to compare, flag (or double-click) to set reference lap
Card {
    id: root

    property string menuPath: ""
    property bool menuKept: false

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
        MenuSeparator {}
        Action { text: i18n.tr("Delete Lap"); onTriggered: backend.deleteLap(root.menuPath) }
    }
    TpMenu {
        id: addedMenu
        Action { text: i18n.tr("Set as Reference"); onTriggered: backend.setReference(root.menuPath) }
        Action { text: i18n.tr("Export MoTeC..."); onTriggered: backend.exportMotec(root.menuPath) }
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
            TpSwitch {
                text: i18n.tr("Clean only")
                tip: i18n.tr("Hide invalid, out & in laps")
                checked: backend.hideUnclean
                onToggled: backend.setHideUnclean(checked)
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
                            onClicked: backend.toggleSession(row.session)
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
                            if (mouse.button === Qt.RightButton) root.openLapMenu(row.path, lapArea, mouse.x, mouse.y)
                            else backend.toggleLap(row.path)
                        }
                        onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) backend.setReference(row.path) }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: theme.em * 1.0
                        anchors.rightMargin: theme.em * 0.4
                        spacing: theme.em * 0.5

                        // Check box
                        Rectangle {
                            implicitWidth: theme.em * 1.15
                            implicitHeight: implicitWidth
                            radius: theme.em * 0.3
                            color: row.checked ? (row.color || theme.accent) : "transparent"
                            border.width: row.checked ? 0 : 1.5
                            border.color: theme.dimText
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Icon {
                                anchors.centerIn: parent
                                glyph: ""  // check mark
                                size: theme.em * 0.75
                                color: "white"
                                opacity: row.checked ? 1 : 0
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
                                    color: row.fastest ? "#FACC15" : theme.text
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
                                        color: modelData[1] ? "#A855F7" : theme.dimText
                                        font.pointSize: theme.fontPoint * 0.85
                                        font.features: { "tnum": 1 }
                                        font.weight: modelData[1] ? Font.DemiBold : Font.Normal
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
            color: "#A855F7"
            font.weight: Font.DemiBold
            Layout.leftMargin: theme.em * 0.3
        }
    }
}
