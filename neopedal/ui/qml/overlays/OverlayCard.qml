import QtQuick
import QtQuick.Controls.Basic
import "../components"

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
    readonly property bool hovered: area.containsMouse
    property bool recycling: false  // in reuse pool: no animation from the previous row's state
    signal menuRequested(Item item, real x, real y)

    GridView.onPooled: {
        recycling = true
        opacity = 1  // add transition cut short by pooling: not reused faded or shrunk
        scale = 1
    }
    GridView.onReused: recycling = false

    width: GridView.view.cellWidth
    height: GridView.view.cellHeight

    Accessible.role: Accessible.ListItem
    Accessible.name: label + ", " + categoryLabel + ", " + (active ? i18n.tr("Enabled") : i18n.tr("Disabled"))
                     + (failed ? ", " + i18n.tr("Error") : "")

    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.margins: theme.space2
        radius: theme.radiusXl
        // Active & hovered: tint a step stronger (both states shown, as in the list rows)
        color: card.active ? Qt.tint(theme.base, theme.tint(theme.accent, card.hovered ? theme.tintSubtle * 1.4 : theme.tintSubtle * 0.7))
             : card.hovered ? (theme.dark ? Qt.lighter(theme.base, 1.12) : Qt.darker(theme.base, 1.02))
             : theme.base
        border.width: card.active ? 1.5 : 1
        border.color: card.active ? theme.accent
                    : card.hovered ? Qt.lighter(theme.border, 1.3)
                    : theme.cardBorder
        Behavior on color { enabled: !card.recycling; ColorAnimation { duration: theme.motionBase } }
        Behavior on border.color { enabled: !card.recycling; ColorAnimation { duration: theme.motionBase } }

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
            radius: theme.radiusMd
            clip: true
            gradient: Gradient {
                GradientStop { position: 0; color: theme.stageTop }
                GradientStop { position: 1; color: theme.stageBottom }
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
                // image://overlaypreview URL changes only with the picture: cached, decoded off the UI thread,
                // old picture kept until the new one is ready, scaled once by the provider (32 px steps on resize)
                asynchronous: true
                retainWhileLoading: !card.recycling  // never the picture of the previous row
                cache: true
                sourceSize.width: Math.ceil(width * Screen.devicePixelRatio / 32) * 32
                smooth: true
                opacity: card.active ? 1 : 0.5  // picture only: overlay off
                scale: card.hovered ? 1.03 : 1
                Behavior on opacity { enabled: !card.recycling; NumberAnimation { duration: theme.motionBase } }
                Behavior on scale { enabled: !card.recycling; NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
            }

            // Loading: soft pulse where the picture comes
            Rectangle {
                visible: card.previewState === 0
                anchors.centerIn: parent
                width: parent.width * 0.55
                height: parent.height * 0.34
                radius: theme.radiusSm
                color: theme.stageText
                opacity: 0.05
                SequentialAnimation on opacity {
                    running: card.previewState === 0 && card.visible && pageState.active && theme.animate  // QML visible stays true while page hidden
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
                color: theme.stageText
                font.pointSize: theme.fontSmall
            }

            // Enabled but not running: start error (see log)
            Rectangle {
                visible: card.failed
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: theme.space3
                height: Math.round(theme.em * 1.5)
                width: failedRow.implicitWidth + theme.space5
                radius: height / 2
                color: theme.lossFill
                Row {
                    id: failedRow
                    anchors.centerIn: parent
                    spacing: theme.space2
                    Icon { glyph: ""; fallback: "!"; size: theme.em * 0.8; color: theme.inkOn(theme.lossFill); anchors.verticalCenter: parent.verticalCenter }  // warning
                    Text {
                        text: i18n.tr("Error")
                        color: theme.inkOn(theme.lossFill)
                        font.pointSize: theme.fontCaption
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea { id: failedArea; anchors.fill: parent; hoverEnabled: true }
                ToolTip.visible: failedArea.containsMouse
                ToolTip.text: i18n.tr("Overlay could not start, see log (Help menu)")
                ToolTip.delay: theme.tipDelay
            }

            // Settings, shown while hovering the card (card click and Enter open settings too: no Tab stop)
            AbstractButton {
                id: settingsButton
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: theme.space3
                width: Math.round(theme.em * 2)
                height: width
                hoverEnabled: true
                focusPolicy: Qt.NoFocus
                opacity: card.hovered || hovered || card.current ? 1 : 0
                visible: opacity > 0
                Behavior on opacity { enabled: !card.recycling; NumberAnimation { duration: theme.motionFast } }
                ToolTip.visible: hovered
                ToolTip.text: i18n.tr("Config")
                ToolTip.delay: theme.tipDelay
                Accessible.name: i18n.tr("Config")
                background: Rectangle {  // on the dark stage: white tints
                    radius: width / 2
                    color: settingsButton.down ? Qt.rgba(1, 1, 1, 0.3) : settingsButton.hovered ? Qt.rgba(1, 1, 1, 0.2) : Qt.rgba(0, 0, 0, 0.45)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.18)
                }
                contentItem: Icon {
                    glyph: ""  // settings
                    fallback: "⚙"
                    size: theme.em * 0.95
                    color: "white"
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

            ColorDot {
                id: dot
                x: card.pad + theme.space1
                y: nameText.y + texts.y + nameText.height / 2 - height / 2
                color: card.categoryColor
            }
            Column {
                id: texts
                anchors.left: dot.right
                anchors.leftMargin: theme.em * 0.5
                anchors.right: controls.left
                anchors.rightMargin: theme.space2
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
                    ToolTip.delay: theme.tipDelay
                }
                Text {
                    width: parent.width
                    text: card.categoryLabel
                    color: theme.dimOn(surface.color)
                    font.pointSize: theme.fontSmall
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
    FocusRing { target: surface; visible: card.current }
}
