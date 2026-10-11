import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Broadcast graphics of the director: browser source address (stream overlay server). Tabs: graphics shown
// (standings tower, driver card, battle card & train, banners, replay, clock & weather, pit radar, onboard,
// qualifying lap, track map), on demand graphics (starting grid, event card, classification, championship,
// message, countdown, shown by the director itself if wanted) and style & layout (opacity, temperature unit,
// league branding, layout presets & editor in the browser, sources with some graphics only).
Popup {
    id: popup
    objectName: "graphicsPopup"
    width: theme.em * 34
    padding: theme.em * 1.0
    onOpened: backend.checkGraphics()
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
    background: Rectangle {
        radius: theme.em * 0.7
        color: theme.raised
        border.width: 1
        border.color: theme.border
    }

    readonly property var graphics: backend.graphicsSettings
    property int tab: 0
    property var partial: []  // graphics of a source with some graphics only
    readonly property real maxTabHeight: Math.max(theme.em * 16, (Overlay.overlay ? Overlay.overlay.height : theme.em * 50) - theme.em * 19)

    function togglePartial(key) {
        const list = popup.partial.slice()
        const index = list.indexOf(key)
        if (index >= 0) list.splice(index, 1)
        else list.push(key)
        popup.partial = list
    }

    component Toggle: TpSwitch {
        property string key: ""
        objectName: "graphic_" + key
        Layout.fillWidth: true
        checked: popup.graphics[key] === true
        onToggled: backend.setGraphic(key, checked)
    }
    component Seconds: NumberField {
        property string key: ""
        Layout.preferredWidth: theme.em * 5
        value: popup.graphics[key] || 0
        suffix: " s"
        onEdited: function(value) { backend.setGraphic(key, value) }
    }
    component Hint: Text {
        Layout.fillWidth: true
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.85
        wrapMode: Text.WordWrap
    }
    component Line: Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border }
    component Heading: Text { color: theme.text; font.weight: Font.DemiBold }
    // Tab content scrolled when taller than the window
    component TabScroll: ScrollView {
        id: scroller
        default property alias content: column.data
        Layout.fillWidth: true
        implicitHeight: Math.min(column.implicitHeight, popup.maxTabHeight)
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            id: column
            width: scroller.availableWidth - (scroller.ScrollBar.vertical.visible ? theme.em * 0.8 : 0)
            spacing: theme.em * 0.45
        }
    }

    contentItem: ColumnLayout {
        spacing: theme.em * 0.55

        RowLayout {
            Layout.fillWidth: true
            Icon { glyph: ""; color: theme.accent }  // streaming
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Broadcast Graphics")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontPoint * 1.1
            }
        }
        Hint { text: i18n.tr("TV graphics made for the director, as one browser source (1920 x 1080) in OBS, Streamlabs, XSplit or vMix.") }
        // Source address, or how to get one
        RowLayout {
            Layout.fillWidth: true
            visible: backend.graphicsUrl !== ""
            Text {
                Layout.fillWidth: true
                text: backend.graphicsUrl
                color: theme.text
                font.pointSize: theme.fontPoint * 0.85
                elide: Text.ElideMiddle
            }
            TpButton {
                objectName: "copyGraphicsButton"
                accent: true
                glyph: ""  // copy
                text: i18n.tr("Copy Address")
                onClicked: backend.copyGraphicsUrl()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: backend.graphicsUrl === ""
            Text {
                Layout.fillWidth: true
                text: i18n.tr("Stream overlays are off: turn them on to use this source.")
                color: theme.warning
                font.pointSize: theme.fontPoint * 0.88
                wrapMode: Text.WordWrap
            }
            TpButton {
                text: i18n.tr("Stream Overlays")
                glyph: ""
                onClicked: { popup.close(); backend.openStreamOverlays() }
            }
        }
        TpSegmented {
            objectName: "graphicsTabs"
            Layout.fillWidth: true
            options: [i18n.tr("Graphics"), i18n.tr("On Demand"), i18n.tr("Style & Layout")]
            currentIndex: popup.tab
            onActivated: function(index) { popup.tab = index }
        }

        StackLayout {
            id: tabs
            Layout.fillWidth: true
            Layout.preferredHeight: tabs.children[popup.tab] ? tabs.children[popup.tab].implicitHeight : 0  // tab shown
            currentIndex: popup.tab

            // Graphics shown by themselves
            TabScroll {
                RowLayout {
                    Layout.fillWidth: true
                    Toggle { key: "tower"; text: i18n.tr("Standings tower") }
                    TpCombo {
                        Layout.preferredWidth: theme.em * 10
                        enabled: popup.graphics.tower === true
                        model: [i18n.tr("Overall"), i18n.tr("Each class in turn"), i18n.tr("Class of the car on air")]
                        currentIndex: ["all", "class", "air"].indexOf(popup.graphics.towerMode)
                        onActivated: function(index) { backend.setGraphic("towerMode", ["all", "class", "air"][index]) }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: theme.em * 3
                    columns: 2
                    columnSpacing: theme.em * 0.6
                    rowSpacing: theme.em * 0.3
                    enabled: popup.graphics.tower === true
                    Text { Layout.fillWidth: true; text: i18n.tr("Cars shown"); color: theme.dimText }
                    NumberField {
                        Layout.preferredWidth: theme.em * 5
                        value: popup.graphics.towerRows || 12
                        minimum: 3; maximum: 30
                        onEdited: function(value) { backend.setGraphic("towerRows", value) }
                    }
                    Text { Layout.fillWidth: true; text: i18n.tr("Gaps"); color: theme.dimText }
                    TpSegmented {
                        options: [i18n.tr("To the car ahead"), i18n.tr("To the leader")]
                        currentIndex: popup.graphics.towerGap === "leader" ? 1 : 0
                        onActivated: function(index) { backend.setGraphic("towerGap", index === 1 ? "leader" : "interval") }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    Layout.leftMargin: theme.em * 3
                    spacing: theme.em * 0.8
                    enabled: popup.graphics.tower === true
                    TpSwitch { text: i18n.tr("Lap times"); checked: popup.graphics.towerLaps === true; onToggled: backend.setGraphic("towerLaps", checked) }
                    TpSwitch { text: i18n.tr("Tyres"); checked: popup.graphics.towerTyres === true; onToggled: backend.setGraphic("towerTyres", checked) }
                    TpSwitch { text: i18n.tr("Penalties"); checked: popup.graphics.towerPenalties === true; onToggled: backend.setGraphic("towerPenalties", checked) }
                    TpSwitch { text: i18n.tr("Fastest lap"); checked: popup.graphics.towerFastest === true; onToggled: backend.setGraphic("towerFastest", checked) }
                    TpSwitch { text: i18n.tr("Pit Stops"); checked: popup.graphics.towerStops === true; onToggled: backend.setGraphic("towerStops", checked) }
                    TpSwitch {
                        text: i18n.tr("Classes apart in overall")
                        checked: popup.graphics.towerGroup === true
                        onToggled: backend.setGraphic("towerGroup", checked)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Toggle { key: "card"; text: i18n.tr("Driver card on each cut") }
                    Seconds {
                        key: "cardSeconds"
                        enabled: popup.graphics.card === true
                        minimum: 0; maximum: 60
                        tip: i18n.tr("Seconds shown, 0: always")
                    }
                }
                Toggle { key: "cardPicture"; text: i18n.tr("Car picture on the driver card"); enabled: popup.graphics.card === true; Layout.leftMargin: theme.em * 3 }
                Toggle { key: "battle"; text: i18n.tr("Battle card while a battle is on air") }
                Toggle { key: "train"; text: i18n.tr("Battle train: up to 6 cars close together"); enabled: popup.graphics.battle === true; Layout.leftMargin: theme.em * 3 }
                RowLayout {
                    Layout.fillWidth: true
                    Toggle { key: "banners"; text: i18n.tr("Banners: fastest lap, penalty, flags, lead change, heavy contact") }
                    Seconds {
                        key: "bannerSeconds"
                        enabled: popup.graphics.banners === true
                        minimum: 2; maximum: 30
                    }
                }
                Toggle { key: "replay"; text: i18n.tr("Replay mark during replays") }
                Toggle {
                    key: "replayGraphics"
                    text: i18n.tr("Instant replay graphics: driver or contact card, banners held until live")
                    Layout.leftMargin: theme.em * 3
                }
                Toggle { key: "clock"; text: i18n.tr("Session clock & weather") }
                RowLayout {
                    Layout.fillWidth: true
                    Toggle { key: "pitRadar"; text: i18n.tr("Pit radar: cars near the car on air in the pit lane") }
                    NumberField {
                        Layout.preferredWidth: theme.em * 5
                        enabled: popup.graphics.pitRadar === true
                        value: popup.graphics.pitRadarRange
                        minimum: 30; maximum: 400; suffix: " m"
                        onEdited: function(value) { backend.setGraphic("pitRadarRange", value) }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Toggle { key: "onboard"; text: i18n.tr("Onboard: speed, gear, rpm, pedals of the car on air") }
                    TpCombo {
                        Layout.preferredWidth: theme.em * 7
                        enabled: popup.graphics.onboard === true
                        model: [i18n.tr("Dash"), i18n.tr("Cockpit"), i18n.tr("Helmet")]
                        currentIndex: ["dash", "cockpit", "helmet"].indexOf(popup.graphics.onboardStyle)
                        onActivated: function(index) { backend.setGraphic("onboardStyle", ["dash", "cockpit", "helmet"][index]) }
                    }
                }
                Toggle { key: "quali"; text: i18n.tr("Qualifying lap outside races: lap time, sectors, gap to pole") }
                Toggle { key: "map"; text: i18n.tr("Track Map") }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: theme.em * 3
                    enabled: popup.graphics.map === true
                    Text { text: i18n.tr("Rotation"); color: theme.dimText }
                    TpSegmented {
                        options: ["0°", "90°", "180°", "270°"]
                        currentIndex: Math.max([0, 90, 180, 270].indexOf(popup.graphics.mapRotation), 0)
                        onActivated: function(index) { backend.setGraphic("mapRotation", [0, 90, 180, 270][index]) }
                    }
                    Item { Layout.fillWidth: true }
                    Text { text: i18n.tr("Dots"); color: theme.dimText }
                    NumberField {
                        Layout.preferredWidth: theme.em * 5.5
                        value: popup.graphics.mapDots || 100
                        minimum: 50; maximum: 200; suffix: " %"
                        onEdited: function(value) { backend.setGraphic("mapDots", value) }
                    }
                }
            }

            // On demand: shown by the operator, one at a time (or by the director itself)
            TabScroll {
                Hint { text: i18n.tr("Shown until clicked again, one at a time.") }
                RowLayout {
                    Layout.fillWidth: true
                    Icon { glyph: ""; color: theme.dimText }  // car
                    Text { Layout.fillWidth: true; text: i18n.tr("Starting Grid"); color: theme.text }
                    Seconds { key: "gridSeconds"; minimum: 3; maximum: 60; tip: i18n.tr("Page time") }
                    TpButton {
                        objectName: "showGrid"
                        text: i18n.tr("Show")
                        checked: backend.onDemand === "grid"
                        onClicked: backend.showOnDemand("grid")
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Icon { glyph: ""; color: theme.dimText }  // calendar
                    Text { Layout.fillWidth: true; text: i18n.tr("Event card: track, conditions, forecast"); color: theme.text; wrapMode: Text.WordWrap }
                    TpButton {
                        objectName: "showEvent"
                        text: i18n.tr("Show")
                        checked: backend.onDemand === "event"
                        onClicked: backend.showOnDemand("event")
                    }
                }
                Line {}
                RowLayout {
                    Layout.fillWidth: true
                    Icon { glyph: ""; color: theme.dimText }  // list
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Text { text: i18n.tr("Classification"); color: theme.text }
                        Text {
                            Layout.fillWidth: true
                            text: backend.captureText !== "" ? i18n.tr("Captured: %1").arg(backend.captureText) : i18n.tr("Not captured yet")
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.8
                            elide: Text.ElideRight
                        }
                    }
                    TpButton {
                        objectName: "captureResults"
                        glyph: ""  // camera
                        text: i18n.tr("Capture")
                        tip: i18n.tr("Classification now, shown until captured again")
                        onClicked: backend.captureResults()
                    }
                    TpButton {
                        text: i18n.tr("Show")
                        checked: backend.onDemand === "results"
                        onClicked: backend.showOnDemand("results")
                    }
                    TpButton {
                        glyph: ""  // cancel
                        flat: true
                        tip: i18n.tr("Clear")
                        enabled: backend.captureText !== ""
                        onClicked: backend.clearResults()
                    }
                }
                Line {}
                RowLayout {
                    Layout.fillWidth: true
                    Icon { glyph: ""; color: theme.dimText }  // star
                    Text { text: i18n.tr("Championship"); color: theme.text }
                    TpCombo {
                        Layout.fillWidth: true
                        visible: backend.championshipNames.length > 0
                        model: backend.championshipNames
                        currentIndex: backend.championshipIndex
                        onActivated: function(index) { backend.setChampionship(index) }
                    }
                    Item { Layout.fillWidth: true; visible: backend.championshipNames.length === 0 }
                    TpButton {
                        objectName: "importChampionship"
                        glyph: ""  // open file
                        text: backend.championshipNames.length > 0 ? "" : i18n.tr("Import...")
                        tip: i18n.tr("Import a CSV file: driver, points, and team, class if you want")
                        onClicked: backend.importChampionship()
                    }
                    TpButton {
                        glyph: ""  // delete
                        flat: true
                        visible: backend.championshipNames.length > 0
                        tip: i18n.tr("Remove this championship")
                        onClicked: backend.removeChampionship()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: theme.em * 1.8
                    visible: backend.championshipNames.length > 0
                    TpCombo {
                        Layout.fillWidth: true
                        visible: backend.championshipClasses.length > 0
                        model: [i18n.tr("All Classes")].concat(backend.championshipClasses)
                        currentIndex: Math.max(backend.championshipClasses.indexOf(backend.championshipClass) + 1, 0)
                        onActivated: function(index) { backend.setChampionshipClass(index > 0 ? backend.championshipClasses[index - 1] : "") }
                    }
                    Item { Layout.fillWidth: true; visible: backend.championshipClasses.length === 0 }
                    TpButton {
                        objectName: "showChampionship"
                        text: i18n.tr("Show")
                        checked: backend.onDemand === "champ"
                        onClicked: backend.showOnDemand("champ")
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; text: i18n.tr("Rows per page"); color: theme.dimText }
                    NumberField {
                        Layout.preferredWidth: theme.em * 5
                        value: popup.graphics.resultsRows || 10
                        minimum: 5; maximum: 20
                        onEdited: function(value) { backend.setGraphic("resultsRows", value) }
                    }
                    Text { text: i18n.tr("Page time"); color: theme.dimText }
                    Seconds { key: "pageSeconds"; minimum: 3; maximum: 60 }
                }
                Line {}
                // Message of the operator (lower third)
                Heading { text: i18n.tr("Message") }
                RowLayout {
                    Layout.fillWidth: true
                    TpTextField {
                        id: messageTitle
                        objectName: "messageTitle"
                        Layout.preferredWidth: theme.em * 11
                        placeholderText: i18n.tr("Title")
                        text: i18n.tr("Race control")
                    }
                    TpTextField {
                        id: messageText
                        objectName: "messageText"
                        Layout.fillWidth: true
                        placeholderText: i18n.tr("Text shown on the graphics")
                        onAccepted: backend.showMessage(messageTitle.text, messageText.text)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    TpButton {
                        objectName: "showMessage"
                        text: i18n.tr("Show")
                        checked: backend.messageText !== ""
                        onClicked: backend.showMessage(messageTitle.text, messageText.text)
                    }
                    TpButton {
                        text: i18n.tr("Hide")
                        enabled: backend.messageText !== ""
                        onClicked: backend.hideMessage()
                    }
                }
                // Countdown
                Heading { text: i18n.tr("Countdown") }
                RowLayout {
                    Layout.fillWidth: true
                    NumberField {
                        id: countdownMinutes
                        Layout.preferredWidth: theme.em * 6
                        value: 5
                        minimum: 0.5; maximum: 1440; decimals: 1; suffix: " min"
                        onEdited: function(minutes) { value = minutes }
                    }
                    TpTextField {
                        id: countdownLabel
                        Layout.fillWidth: true
                        placeholderText: i18n.tr("Race starts in")
                    }
                    TpButton {
                        objectName: "startCountdown"
                        text: i18n.tr("Start")
                        checked: backend.countdownRunning
                        onClicked: backend.startCountdown(countdownMinutes.value, countdownLabel.text)
                    }
                    TpButton {
                        glyph: ""  // cancel
                        flat: true
                        tip: i18n.tr("Stop")
                        enabled: backend.countdownRunning
                        onClicked: backend.stopCountdown()
                    }
                }
                Line {}
                // Shown by the director itself
                Heading { text: i18n.tr("Automatic") }
                Toggle { key: "autoGrid"; text: i18n.tr("Starting grid during the formation lap") }
                Toggle { key: "autoEvent"; text: i18n.tr("Event card for 20 s when a session starts") }
                Toggle { key: "autoResults"; text: i18n.tr("Classification at the chequered flag") }
            }

            // Style & layout
            TabScroll {
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; text: i18n.tr("Panel opacity"); color: theme.text }
                    NumberField {
                        objectName: "graphicsOpacity"
                        Layout.preferredWidth: theme.em * 5.5
                        value: popup.graphics.opacity || 92
                        minimum: 30; maximum: 100; suffix: " %"
                        onEdited: function(value) { backend.setGraphic("opacity", value) }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; text: i18n.tr("Temperatures"); color: theme.text }
                    TpSegmented {
                        options: [i18n.tr("App setting"), "°C", "°F"]
                        currentIndex: Math.max(["app", "celsius", "fahrenheit"].indexOf(popup.graphics.temperatureUnit), 0)
                        onActivated: function(index) { backend.setGraphic("temperatureUnit", ["app", "celsius", "fahrenheit"][index]) }
                    }
                }
                Line {}
                // League branding
                Heading { text: i18n.tr("League") }
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: i18n.tr("Accent color"); color: theme.dimText }
                    Rectangle {
                        implicitWidth: theme.em * 1.6
                        implicitHeight: theme.em * 1.6
                        radius: theme.em * 0.3
                        color: popup.graphics.accent || "#e5383b"
                        border.width: 1
                        border.color: theme.border
                    }
                    TpTextField {
                        objectName: "accentColor"
                        Layout.preferredWidth: theme.em * 6
                        text: popup.graphics.accent || "#e5383b"
                        onEditingFinished: backend.setGraphic("accent", text)
                    }
                    Item { Layout.fillWidth: true }
                }
                TpTextField {
                    objectName: "brandName"
                    Layout.fillWidth: true
                    placeholderText: i18n.tr("Event or league name")
                    text: popup.graphics.brandName || ""
                    onEditingFinished: backend.setGraphic("brandName", text)
                }
                RowLayout {
                    Layout.fillWidth: true
                    Toggle { key: "logo"; text: i18n.tr("League logo & name") }
                    TpButton {
                        glyph: ""  // picture
                        text: i18n.tr("Logo...")
                        onClicked: backend.chooseLogo()
                    }
                    TpButton {
                        glyph: ""  // cancel
                        flat: true
                        tip: i18n.tr("Remove the logo")
                        onClicked: backend.clearLogo()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Toggle { key: "sponsors"; text: i18n.tr("Sponsors in turn") }
                    Seconds { key: "sponsorSeconds"; minimum: 3; maximum: 60 }
                    TpButton {
                        glyph: ""  // folder open
                        tip: i18n.tr("Folder of sponsors pictures (PNG, JPG, WEBP, SVG)")
                        onClicked: backend.openSponsorsFolder()
                    }
                }
                Line {}
                Heading { text: i18n.tr("Layout") }
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: i18n.tr("Preset in use"); color: theme.dimText }
                    TpCombo {
                        objectName: "layoutPreset"
                        Layout.fillWidth: true
                        model: backend.layoutPresets.map(function(item) { return item.name })
                        currentIndex: Math.max(backend.layoutPresets.map(function(item) { return item.key }).indexOf(backend.layoutPreset), 0)
                        onActivated: function(index) { backend.setLayoutPreset(backend.layoutPresets[index].key) }
                    }
                }
                Hint { text: i18n.tr("Move and resize every graphic in your browser, with sample data: drag to move, mouse wheel to resize, then Save. Every source of this computer follows.") }
                RowLayout {
                    Layout.fillWidth: true
                    TpButton {
                        objectName: "editGraphicsLayout"
                        Layout.fillWidth: true
                        accent: true
                        glyph: ""  // layers
                        text: i18n.tr("Edit Layout")
                        enabled: backend.graphicsUrl !== ""
                        onClicked: backend.editGraphicsLayout()
                    }
                    TpButton {
                        Layout.fillWidth: true
                        glyph: ""  // undo
                        text: i18n.tr("Reset Layout")
                        onClicked: backend.resetGraphicsLayout()
                    }
                }
                Line {}
                // Source with some graphics only (another scene or source of the streaming software)
                Heading { text: i18n.tr("Source with some graphics only") }
                Flow {
                    Layout.fillWidth: true
                    spacing: theme.em * 0.3
                    Repeater {
                        model: backend.graphicNames
                        delegate: AbstractButton {
                            id: chip
                            required property var modelData
                            readonly property bool chosen: popup.partial.indexOf(modelData.key) >= 0
                            height: Math.round(theme.em * 1.7)
                            width: chipText.implicitWidth + theme.em * 1.0
                            hoverEnabled: true
                            focusPolicy: Qt.NoFocus
                            onClicked: popup.togglePartial(modelData.key)
                            background: Rectangle {
                                radius: height / 2
                                color: chip.chosen ? Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.2) : chip.hovered ? theme.hover : theme.raised
                                border.width: 1
                                border.color: chip.chosen ? theme.accent : theme.border
                            }
                            contentItem: Text {
                                id: chipText
                                text: chip.modelData.name
                                color: theme.text
                                font.pointSize: theme.fontPoint * 0.8
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    TpCombo {
                        id: partialPreset
                        Layout.fillWidth: true
                        model: [i18n.tr("Preset in use")].concat(backend.layoutPresets.map(function(item) { return item.name }))
                    }
                    TpButton {
                        objectName: "copyPartialUrl"
                        glyph: ""  // copy
                        text: i18n.tr("Copy Address")
                        enabled: popup.partial.length > 0 && backend.graphicsUrl !== ""
                        onClicked: backend.copyPartialUrl(popup.partial, partialPreset.currentIndex > 0 ? backend.layoutPresets[partialPreset.currentIndex - 1].key : "")
                    }
                }
            }
        }

        Line {}
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.4
            TpButton {
                Layout.fillWidth: true
                glyph: ""  // contact
                text: i18n.tr("Show Driver Card")
                enabled: popup.graphics.card === true
                onClicked: backend.showDriverCard()
            }
            TpButton {
                objectName: "hideGraphicsButton"
                Layout.fillWidth: true
                glyph: popup.graphics.hidden ? "" : ""  // view, hide
                checked: popup.graphics.hidden === true
                text: popup.graphics.hidden ? i18n.tr("Show Graphics") : i18n.tr("Hide Graphics")
                onClicked: backend.setGraphic("hidden", !popup.graphics.hidden)
            }
        }
    }
}
