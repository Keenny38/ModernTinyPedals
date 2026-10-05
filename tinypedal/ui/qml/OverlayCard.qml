import QtQuick
import QtQuick.Controls.Basic

// Overlay card of Overlays page (grid): preview on a dark stage (overlays are drawn over the game),
// name & category, settings button & on/off switch. Click opens settings, right-click the menu.
Item {
    id: card
    required property int index
    required property string name
    required property string label
    required property string category
    required property string categoryLabel
    required property color categoryColor
    required property bool active
    required property bool failed
    required property string preview
    required property int previewState  // 0 loading, 1 ready, 2 not available
    required property int previewWidth
    required property int previewHeight
    readonly property bool current: GridView.isCurrentItem && GridView.view.activeFocus
    readonly property real pad: Math.round(theme.em * 0.45)
    signal menuRequested(Item item, real x, real y)

    width: GridView.view.cellWidth
    height: GridView.view.cellHeight

    Accessible.role: Accessible.ListItem
    Accessible.name: label + ", " + categoryLabel + ", " + (active ? i18n.tr("Enabled") : i18n.tr("Disabled"))

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.margins: Math.round(theme.em * 0.3)
        radius: theme.em * 0.7
        color: card.active ? Qt.tint(theme.base, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.07))
             : area.containsMouse ? (theme.dark ? Qt.lighter(theme.base, 1.12) : Qt.darker(theme.base, 1.02))
             : theme.base
        border.width: card.active ? 1.5 : 1
        border.color: card.active ? theme.accent
                    : area.containsMouse ? Qt.lighter(theme.border, 1.3)
                    : theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border
        Behavior on color { ColorAnimation { duration: 150 } }
        Behavior on border.color { ColorAnimation { duration: 150 } }

        // Card background click (buttons above get their own clicks)
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onClicked: function(mouse) {
                card.GridView.view.currentIndex = card.index
                if (mouse.button === Qt.RightButton)
                    card.menuRequested(area, mouse.x, mouse.y)
                else
                    backend.openConfig(card.name)
            }
        }

        // Preview stage
        Rectangle {
            id: stage
            x: card.pad
            y: card.pad
            width: parent.width - card.pad * 2
            height: parent.height - footer.height - card.pad
            radius: theme.em * 0.45
            clip: true
            gradient: Gradient {
                GradientStop { position: 0; color: "#2B313A" }
                GradientStop { position: 1; color: "#14171C" }
            }

            Image {
                id: shot
                readonly property real fit: Math.min(1, (stage.width - theme.em) / Math.max(card.previewWidth, 1),
                                                     (stage.height - theme.em) / Math.max(card.previewHeight, 1))
                anchors.centerIn: parent
                width: Math.round(card.previewWidth * fit)
                height: Math.round(card.previewHeight * fit)
                source: card.preview
                visible: card.previewState === 1
                cache: false
                smooth: true
                mipmap: true
                opacity: card.active ? 1 : 0.5
                scale: area.containsMouse ? 1.03 : 1
                Behavior on opacity { NumberAnimation { duration: 180 } }
                Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            }

            // Loading: soft pulse where the picture comes
            Rectangle {
                visible: card.previewState === 0
                anchors.centerIn: parent
                width: parent.width * 0.55
                height: parent.height * 0.34
                radius: theme.em * 0.35
                color: "#FFFFFF"
                opacity: 0.05
                SequentialAnimation on opacity {
                    running: card.previewState === 0 && card.visible
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.12; duration: 650; easing.type: Easing.InOutQuad }
                    NumberAnimation { to: 0.05; duration: 650; easing.type: Easing.InOutQuad }
                }
            }

            Text {
                visible: card.previewState === 2
                anchors.centerIn: parent
                width: parent.width - theme.em
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: i18n.tr("Preview not available")
                color: "#8B949E"
                font.pointSize: theme.fontPoint * 0.85
            }

            // Enabled but not running: start error (see log)
            Rectangle {
                visible: card.failed
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: theme.em * 0.35
                height: Math.round(theme.em * 1.5)
                width: failedRow.implicitWidth + theme.em * 0.8
                radius: height / 2
                color: Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.92)
                Row {
                    id: failedRow
                    anchors.centerIn: parent
                    spacing: theme.em * 0.3
                    Icon { glyph: ""; size: theme.em * 0.8; color: "white"; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: i18n.tr("Error")
                        color: "white"
                        font.pointSize: theme.fontPoint * 0.8
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea { id: failedArea; anchors.fill: parent; hoverEnabled: true }
                ToolTip.visible: failedArea.containsMouse
                ToolTip.text: i18n.tr("Overlay could not start, see log (Help menu)")
                ToolTip.delay: 300
            }

            // Settings, shown while hovering the card (card click opens settings too)
            AbstractButton {
                id: settingsButton
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: theme.em * 0.35
                width: Math.round(theme.em * 2)
                height: width
                hoverEnabled: true
                focusPolicy: Qt.NoFocus
                opacity: area.containsMouse || hovered || card.current ? 1 : 0
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: 140 } }
                ToolTip.visible: hovered
                ToolTip.text: i18n.tr("Config")
                ToolTip.delay: 500
                Accessible.name: i18n.tr("Config")
                background: Rectangle {
                    radius: width / 2
                    color: settingsButton.down ? Qt.rgba(1, 1, 1, 0.3) : settingsButton.hovered ? Qt.rgba(1, 1, 1, 0.2) : Qt.rgba(0, 0, 0, 0.45)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.18)
                }
                contentItem: Text {
                    text: theme.iconFont !== "" ? "" : "⚙"  // settings
                    font.family: theme.iconFont !== "" ? theme.iconFont : font.family
                    font.pixelSize: theme.em * 0.95
                    color: "white"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: backend.openConfig(card.name)
            }
        }

        // Name, category & controls
        Item {
            id: footer
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: Math.round(theme.em * 3.1)

            Rectangle {
                id: dot
                x: card.pad + theme.em * 0.2
                y: nameText.y + nameText.height / 2 - height / 2
                width: Math.round(theme.em * 0.55)
                height: width
                radius: width / 2
                color: card.categoryColor
            }
            Column {
                id: texts
                anchors.left: dot.right
                anchors.leftMargin: theme.em * 0.45
                anchors.right: controls.left
                anchors.rightMargin: theme.em * 0.3
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                Text {
                    id: nameText
                    width: parent.width
                    text: card.label
                    color: theme.text
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    MouseArea {
                        id: nameArea
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton  // clicks go to card
                    }
                    ToolTip.visible: truncated && nameArea.containsMouse
                    ToolTip.text: card.label
                    ToolTip.delay: 400
                }
                Text {
                    width: parent.width
                    text: card.categoryLabel
                    color: theme.dimText
                    font.pointSize: theme.fontPoint * 0.85
                    elide: Text.ElideRight
                }
            }
            Row {
                id: controls
                anchors.right: parent.right
                anchors.rightMargin: card.pad
                anchors.verticalCenter: parent.verticalCenter
                TpSwitch {
                    checkable: false  // follows model: switched by backend
                    checked: card.active
                    tip: i18n.tr("Enable / Disable")
                    implicitWidth: theme.em * 2.6
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: {
                        card.GridView.view.currentIndex = card.index
                        backend.toggle(card.name)
                    }
                    Accessible.role: Accessible.CheckBox
                    Accessible.name: card.label
                    Accessible.checked: card.active
                }
            }
        }
    }

    // Keyboard focus ring
    Rectangle {
        anchors.fill: surface
        anchors.margins: -3
        radius: surface.radius + 3
        color: "transparent"
        border.width: 2
        border.color: theme.accent
        visible: card.current
    }
}
