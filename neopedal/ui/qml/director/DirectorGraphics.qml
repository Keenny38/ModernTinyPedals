import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Broadcast graphics of the director: browser source address (stream overlay server). Tabs: graphics shown
// (standings tower, driver card, battle card & train, banners, replay, clock & weather, pit radar, onboard,
// qualifying lap, track map), on demand graphics (starting grid, event card, classification, championship,
// message, countdown, shown by the director itself if wanted) and style & layout (opacity, temperature unit,
// league branding, layout presets & editor in the browser, sources with some graphics only).
// The address holds the access token: shown masked (Copy Address puts the whole address in the clipboard).
TpPopup {
    id: popup
    objectName: "graphicsPopup"
    width: Math.min(theme.em * 34, (Overlay.overlay ? Overlay.overlay.width : theme.em * 36) - theme.em * 2)
    onOpened: backend.graphics.checkGraphics()

    readonly property var graphics: backend.graphics.graphicsSettings
    property int tab: 0
    property var partial: []  // graphics of a source with some graphics only
    readonly property real maxTabHeight: Math.max(theme.em * 16, (Overlay.overlay ? Overlay.overlay.height : theme.em * 50) - theme.em * 24)  // header, notice & buttons kept in the window

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
        wrap: true  // long labels on several lines, never cut
        checkable: false  // follows backend (a click never breaks the binding)
        checked: popup.graphics[key] === true
        onClicked: backend.graphics.setGraphic(key, popup.graphics[key] !== true)
    }
    component Seconds: NumberField {
        property string key: ""
        Layout.preferredWidth: theme.em * 5
        value: popup.graphics[key] || 0
        suffix: " s"
        showRange: true
        onEdited: function(value) { backend.graphics.setGraphic(key, value) }
    }
    component Line: Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border }
    component Heading: TpSectionLabel { Layout.fillWidth: true }
    // On demand graphic: "Show" while hidden, "Hide" (checked) while shown: a second click hides it
    component ShowButton: TpButton {
        property bool shown: false
        property string hotkey: ""  // director hotkey showing or hiding it: key in the tooltip
        checked: shown
        text: shown ? i18n.tr("Hide") : i18n.tr("Show")
        tip: (backend.keyLabels[hotkey] || "") !== "" ? i18n.tr("Hotkey %1").arg(backend.keyLabels[hotkey]) : ""
    }
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
            width: scroller.availableWidth - (scroller.ScrollBar.vertical.visible ? theme.space5 : 0)
            spacing: theme.space3
        }
    }

    contentItem: LazyPane {
        shown: popup.visible
        sourceComponent: ColumnLayout {
            id: panel
            // Combo boxes have a popup property of their own (hides the popup id of this file in their bindings)
            readonly property var graphics: popup.graphics
            spacing: theme.space4

            TpCardHeader {
                level: "popup"
                glyph: ""  // streaming
                title: i18n.tr("Broadcast Graphics")
                closable: true
                onClosed: popup.close()
            }
            TpText { Layout.fillWidth: true; role: "caption"; wrap: true; text: i18n.tr("TV graphics made for the director, as one browser source (1920 x 1080) in OBS, Streamlabs, XSplit or vMix.") }
            // Source address (token masked), or how to get one
            RowLayout {
                Layout.fillWidth: true
                visible: backend.graphics.graphicsUrl !== ""
                Text {
                    Layout.fillWidth: true
                    text: backend.graphics.graphicsUrl.replace(/token=[^&]*/, "token=••••")
                    textFormat: Text.PlainText
                    color: theme.text
                    font.pointSize: theme.fontSmall
                    elide: Text.ElideMiddle
                    Accessible.name: i18n.tr("Copy Address")
                }
                TpButton {
                    objectName: "copyGraphicsButton"
                    accent: true
                    glyph: theme.glyphs.copy
                    text: i18n.tr("Copy Address")
                    onClicked: backend.graphics.copyGraphicsUrl()
                }
            }
            TpNotice {
                visible: backend.graphics.graphicsUrl === ""
                text: i18n.tr("Stream overlays are off: turn them on to use this source.")
                actionText: i18n.tr("Stream Overlays")
                onAction: { popup.close(); backend.graphics.openStreamOverlays() }
            }
            TpSegmented {
                objectName: "graphicsTabs"
                Layout.fillWidth: true
                name: i18n.tr("Broadcast Graphics")
                options: [i18n.tr("Graphics"), i18n.tr("On Demand"), i18n.tr("Style & Layout")]
                currentIndex: popup.tab
                onActivated: function(index) { popup.tab = index }
            }

            StackLayout {
                id: tabs
                Layout.fillWidth: true
                Layout.preferredHeight: tabs.children[popup.tab] ? tabs.children[popup.tab].implicitHeight : 0  // tab shown
                Behavior on Layout.preferredHeight { NumberAnimation { duration: theme.motionBase; easing.type: Easing.OutCubic } }
                currentIndex: popup.tab

                // Graphics shown by themselves
                TabScroll {
                    RowLayout {
                        Layout.fillWidth: true
                        Toggle { key: "tower"; text: i18n.tr("Standings tower") }
                        TpCombo {
                            Layout.preferredWidth: theme.em * 10
                            enabled: panel.graphics.tower === true
                            model: [i18n.tr("Overall"), i18n.tr("Each class in turn"), i18n.tr("Class of the car on air")]
                            currentIndex: ["all", "class", "air"].indexOf(panel.graphics.towerMode)
                            tip: i18n.tr("Standings tower")
                            onActivated: function(index) { backend.graphics.setGraphic("towerMode", ["all", "class", "air"][index]) }
                        }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: theme.em * 3  // content-tuned: under the switch label
                        columns: 2
                        columnSpacing: theme.space4
                        rowSpacing: theme.space2
                        enabled: popup.graphics.tower === true
                        Text { Layout.fillWidth: true; text: i18n.tr("Cars shown"); color: theme.dimText; wrapMode: Text.WordWrap }
                        NumberField {
                            Layout.preferredWidth: theme.em * 5
                            value: popup.graphics.towerRows || 12
                            minimum: 3; maximum: 70
                            showRange: true
                            tip: i18n.tr("Cars shown")
                            onEdited: function(value) { backend.graphics.setGraphic("towerRows", value) }
                        }
                        Text { Layout.fillWidth: true; text: i18n.tr("Gaps"); color: theme.dimText; wrapMode: Text.WordWrap }
                        TpSegmented {
                            name: i18n.tr("Gaps")
                            options: [i18n.tr("To the car ahead"), i18n.tr("To the leader")]
                            currentIndex: popup.graphics.towerGap === "leader" ? 1 : 0
                            onActivated: function(index) { backend.graphics.setGraphic("towerGap", index === 1 ? "leader" : "interval") }
                        }
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.leftMargin: theme.em * 3  // content-tuned: under the switch label
                        spacing: theme.space5
                        enabled: popup.graphics.tower === true
                        TpSwitch { text: i18n.tr("Lap times"); checkable: false; checked: popup.graphics.towerLaps === true; onClicked: backend.graphics.setGraphic("towerLaps", popup.graphics.towerLaps !== true) }
                        TpSwitch { text: i18n.tr("Tyres"); checkable: false; checked: popup.graphics.towerTyres === true; onClicked: backend.graphics.setGraphic("towerTyres", popup.graphics.towerTyres !== true) }
                        TpSwitch { text: i18n.tr("Penalties"); checkable: false; checked: popup.graphics.towerPenalties === true; onClicked: backend.graphics.setGraphic("towerPenalties", popup.graphics.towerPenalties !== true) }
                        TpSwitch { text: i18n.tr("Fastest lap"); checkable: false; checked: popup.graphics.towerFastest === true; onClicked: backend.graphics.setGraphic("towerFastest", popup.graphics.towerFastest !== true) }
                        TpSwitch { text: i18n.tr("Pit stops"); checkable: false; checked: popup.graphics.towerStops === true; onClicked: backend.graphics.setGraphic("towerStops", popup.graphics.towerStops !== true) }
                        TpSwitch {
                            text: i18n.tr("Classes apart in overall")
                            checkable: false
                            checked: popup.graphics.towerGroup === true
                            onClicked: backend.graphics.setGraphic("towerGroup", popup.graphics.towerGroup !== true)
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
                            showRange: true
                            onEdited: function(value) { backend.graphics.setGraphic("pitRadarRange", value) }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Toggle { key: "onboard"; text: i18n.tr("Onboard: speed, gear, rpm, pedals of the car on air") }
                        TpCombo {
                            Layout.preferredWidth: theme.em * 7
                            enabled: panel.graphics.onboard === true
                            model: [i18n.tr("Dash"), i18n.tr("Cockpit"), i18n.tr("Helmet")]
                            currentIndex: ["dash", "cockpit", "helmet"].indexOf(panel.graphics.onboardStyle)
                            onActivated: function(index) { backend.graphics.setGraphic("onboardStyle", ["dash", "cockpit", "helmet"][index]) }
                        }
                    }
                    Toggle { key: "quali"; text: i18n.tr("Qualifying lap outside races: lap time, sectors, gap to pole") }
                    Toggle { key: "map"; text: i18n.tr("Track Map") }
                    Flow {
                        Layout.fillWidth: true
                        Layout.leftMargin: theme.em * 3  // content-tuned: under the switch label
                        spacing: theme.space4
                        enabled: popup.graphics.map === true
                        RowLayout {
                            Text { text: i18n.tr("Rotation"); color: theme.dimText }
                            TpSegmented {
                                name: i18n.tr("Rotation")
                                options: ["0°", "90°", "180°", "270°"]
                                currentIndex: Math.max([0, 90, 180, 270].indexOf(popup.graphics.mapRotation), 0)
                                onActivated: function(index) { backend.graphics.setGraphic("mapRotation", [0, 90, 180, 270][index]) }
                            }
                        }
                        RowLayout {
                            Text { text: i18n.tr("Dots"); color: theme.dimText }
                            NumberField {
                                Layout.preferredWidth: theme.em * 5.5
                                value: popup.graphics.mapDots || 100
                                minimum: 50; maximum: 200; suffix: " %"
                                showRange: true
                                tip: i18n.tr("Dots")
                                onEdited: function(value) { backend.graphics.setGraphic("mapDots", value) }
                            }
                        }
                    }
                }

                // On demand: shown by the operator, one at a time (or by the director itself)
                TabScroll {
                    TpText { Layout.fillWidth: true; role: "caption"; wrap: true; text: i18n.tr("Shown until clicked again, one at a time.") }
                    RowLayout {
                        Layout.fillWidth: true
                        Icon { glyph: ""; color: theme.dimText }  // car
                        Text { Layout.fillWidth: true; text: i18n.tr("Starting Grid"); color: theme.text; wrapMode: Text.WordWrap }
                        Seconds { key: "gridSeconds"; minimum: 3; maximum: 60; tip: i18n.tr("Page time") }
                        ShowButton {
                            objectName: "showGrid"
                            hotkey: "director_starting_grid"
                            shown: backend.graphics.onDemand === "grid"
                            onClicked: backend.graphics.showOnDemand("grid")
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Icon { glyph: ""; color: theme.dimText }  // calendar
                        Text { Layout.fillWidth: true; text: i18n.tr("Event card: track, conditions, forecast"); color: theme.text; wrapMode: Text.WordWrap }
                        ShowButton {
                            objectName: "showEvent"
                            hotkey: "director_event_card"
                            shown: backend.graphics.onDemand === "event"
                            onClicked: backend.graphics.showOnDemand("event")
                        }
                    }
                    Line {}
                    RowLayout {
                        Layout.fillWidth: true
                        Icon { glyph: ""; color: theme.dimText }  // list
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text { Layout.fillWidth: true; text: i18n.tr("Classification"); color: theme.text; elide: Text.ElideRight }
                            Text {
                                Layout.fillWidth: true
                                text: backend.graphics.captureText !== "" ? i18n.tr("Captured: %1").arg(backend.graphics.captureText) : i18n.tr("Not captured yet")
                                textFormat: Text.PlainText
                                color: theme.dimText
                                font.pointSize: theme.fontCaption
                                elide: Text.ElideRight
                            }
                        }
                        TpButton {
                            objectName: "captureResults"
                            glyph: ""  // camera
                            text: i18n.tr("Capture")
                            tip: i18n.tr("Classification now, shown until captured again")
                            onClicked: backend.graphics.captureResults()
                        }
                        ShowButton {
                            hotkey: "director_classification"
                            shown: backend.graphics.onDemand === "results"
                            onClicked: backend.graphics.showOnDemand("results")
                        }
                        TpButton {
                            objectName: "clearResults"
                            glyph: theme.glyphs.remove
                            fallback: "✕"
                            flat: true
                            tip: i18n.tr("Clear")
                            enabled: backend.graphics.captureText !== ""
                            onClicked: clearResultsDialog.open()
                            TpConfirmDialog {
                                id: clearResultsDialog
                                objectName: "clearResultsDialog"
                                danger: true
                                title: i18n.tr("Clear the captured classification?")
                                text: i18n.tr("The classification captured at that moment is lost: a new capture takes the order of now.")
                                acceptText: i18n.tr("Clear")
                                onAccepted: backend.graphics.clearResults()
                            }
                        }
                    }
                    Line {}
                    RowLayout {
                        Layout.fillWidth: true
                        Icon { glyph: ""; color: theme.dimText }  // star
                        Text { text: i18n.tr("Championship"); color: theme.text }
                        TpCombo {
                            Layout.fillWidth: true
                            visible: backend.graphics.championshipNames.length > 0
                            model: backend.graphics.championshipNames
                            currentIndex: backend.graphics.championshipIndex
                            tip: i18n.tr("Championship")
                            onActivated: function(index) { backend.graphics.setChampionship(index) }
                        }
                        Item { Layout.fillWidth: true; visible: backend.graphics.championshipNames.length === 0 }
                        TpButton {
                            objectName: "importChampionship"
                            glyph: theme.glyphs["import"]
                            fallback: "…"
                            text: backend.graphics.championshipNames.length > 0 ? "" : i18n.tr("Import…")
                            tip: i18n.tr("Import a CSV file: driver, points, and team, class if you want")
                            onClicked: backend.graphics.importChampionship()
                        }
                        TpButton {
                            glyph: theme.glyphs.delete
                            fallback: "✕"
                            flat: true
                            visible: backend.graphics.championshipNames.length > 0
                            tip: i18n.tr("Remove this championship")
                            onClicked: removeChampionshipDialog.open()
                            TpConfirmDialog {
                                id: removeChampionshipDialog
                                danger: true
                                title: i18n.tr("Remove this championship?")
                                text: i18n.tr("Its standings leave the broadcast graphics. Import the CSV file again to get them back.")
                                acceptText: i18n.tr("Remove")
                                onAccepted: backend.graphics.removeChampionship()
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: theme.em * 1.8  // content-tuned: under the championship name
                        visible: backend.graphics.championshipNames.length > 0
                        TpCombo {
                            Layout.fillWidth: true
                            visible: backend.graphics.championshipClasses.length > 0
                            model: [i18n.tr("All Classes")].concat(backend.graphics.championshipClasses)
                            currentIndex: Math.max(backend.graphics.championshipClasses.indexOf(backend.graphics.championshipClass) + 1, 0)
                            tip: i18n.tr("Classes")
                            onActivated: function(index) { backend.graphics.setChampionshipClass(index > 0 ? backend.graphics.championshipClasses[index - 1] : "") }
                        }
                        Item { Layout.fillWidth: true; visible: backend.graphics.championshipClasses.length === 0 }
                        ShowButton {
                            objectName: "showChampionship"
                            hotkey: "director_championship"
                            shown: backend.graphics.onDemand === "champ"
                            onClicked: backend.graphics.showOnDemand("champ")
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { Layout.fillWidth: true; text: i18n.tr("Rows per page"); color: theme.dimText; wrapMode: Text.WordWrap }
                        NumberField {
                            Layout.preferredWidth: theme.em * 5
                            value: popup.graphics.resultsRows || 10
                            minimum: 5; maximum: 20
                            showRange: true
                            tip: i18n.tr("Rows per page")
                            onEdited: function(value) { backend.graphics.setGraphic("resultsRows", value) }
                        }
                        Text { text: i18n.tr("Page time"); color: theme.dimText }
                        Seconds { key: "pageSeconds"; minimum: 3; maximum: 60; tip: i18n.tr("Page time") }
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
                            onAccepted: backend.graphics.showMessage(messageTitle.text, messageText.text)
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        TpButton {
                            objectName: "showMessage"
                            text: i18n.tr("Show")
                            checked: backend.graphics.messageText !== ""
                            tip: checked ? i18n.tr("Message shown: Show puts the new text on air") : ""
                            onClicked: backend.graphics.showMessage(messageTitle.text, messageText.text)
                        }
                        TpButton {
                            text: i18n.tr("Hide")
                            enabled: backend.graphics.messageText !== ""
                            onClicked: backend.graphics.hideMessage()
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
                            showRange: true
                            tip: i18n.tr("Countdown")
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
                            checked: backend.graphics.countdownRunning
                            onClicked: backend.graphics.startCountdown(countdownMinutes.value, countdownLabel.text)
                        }
                        TpButton {
                            glyph: ""  // cancel
                            fallback: "✕"
                            flat: true
                            tip: i18n.tr("Stop")
                            enabled: backend.graphics.countdownRunning
                            onClicked: backend.graphics.stopCountdown()
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
                        Text { Layout.fillWidth: true; text: i18n.tr("Panel opacity"); color: theme.text; wrapMode: Text.WordWrap }
                        NumberField {
                            objectName: "graphicsOpacity"
                            Layout.preferredWidth: theme.em * 5.5
                            value: popup.graphics.opacity || 92
                            minimum: 30; maximum: 100; suffix: " %"
                            showRange: true
                            tip: i18n.tr("Panel opacity")
                            onEdited: function(value) { backend.graphics.setGraphic("opacity", value) }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { Layout.fillWidth: true; text: i18n.tr("Temperatures"); color: theme.text; wrapMode: Text.WordWrap }
                        TpSegmented {
                            name: i18n.tr("Temperatures")
                            options: [i18n.tr("App setting"), "°C", "°F"]
                            currentIndex: Math.max(["app", "celsius", "fahrenheit"].indexOf(popup.graphics.temperatureUnit), 0)
                            onActivated: function(index) { backend.graphics.setGraphic("temperatureUnit", ["app", "celsius", "fahrenheit"][index]) }
                        }
                    }
                    Line {}
                    // League branding
                    Heading { text: i18n.tr("League") }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: i18n.tr("Accent color"); color: theme.dimText }
                        Rectangle {  // color in use (the typed one once valid)
                            implicitWidth: theme.em * 1.6
                            implicitHeight: theme.em * 1.6
                            radius: theme.radiusSm
                            color: accentField.invalid ? (popup.graphics.accent || "transparent") : accentField.text
                            border.width: 1
                            border.color: theme.border
                        }
                        TpTextField {
                            id: accentField
                            objectName: "accentColor"
                            // #RRGGBB only: anything else stays in the field marked invalid, never sent
                            readonly property bool valid: /^#[0-9A-Fa-f]{6}$/.test(text.trim())
                            Layout.preferredWidth: theme.em * 6
                            text: popup.graphics.accent || ""
                            invalid: !valid
                            maximumLength: 7
                            tip: valid ? i18n.tr("Accent color") : i18n.tr("Color as #RRGGBB, for example #E5383B")
                            onEditingFinished: if (valid) backend.graphics.setGraphic("accent", text.trim())
                            onEscaped: text = Qt.binding(function() { return popup.graphics.accent || "" })
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: accentField.invalid
                            text: i18n.tr("Color as #RRGGBB, for example #E5383B")
                            color: theme.loss
                            font.pointSize: theme.fontSmall
                            wrapMode: Text.WordWrap
                        }
                        Item { Layout.fillWidth: true; visible: !accentField.invalid }
                    }
                    TpTextField {
                        objectName: "brandName"
                        Layout.fillWidth: true
                        placeholderText: i18n.tr("Event or league name")
                        text: popup.graphics.brandName || ""
                        onEditingFinished: backend.graphics.setGraphic("brandName", text)
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Toggle { key: "logo"; text: i18n.tr("League logo & name") }
                        TpButton {
                            glyph: ""  // picture
                            text: i18n.tr("Logo…")
                            onClicked: backend.graphics.chooseLogo()
                        }
                        TpButton {
                            objectName: "removeLogo"
                            glyph: theme.glyphs.remove
                            fallback: "✕"
                            flat: true
                            tip: i18n.tr("Remove the logo")
                            enabled: backend.graphics.hasLogo
                            onClicked: removeLogoDialog.open()
                            TpConfirmDialog {
                                id: removeLogoDialog
                                objectName: "removeLogoDialog"
                                danger: true
                                title: i18n.tr("Remove the league logo?")
                                text: i18n.tr("The logo file is deleted from the branding folder. Choose the picture again to get it back.")
                                acceptText: i18n.tr("Remove")
                                onAccepted: backend.graphics.clearLogo()
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Toggle { key: "sponsors"; text: i18n.tr("Sponsors in turn") }
                        Seconds { key: "sponsorSeconds"; minimum: 3; maximum: 60 }
                        TpButton {
                            glyph: theme.glyphs.browse
                            fallback: "…"
                            tip: i18n.tr("Folder of sponsors pictures (PNG, JPG, WEBP, SVG)")
                            onClicked: backend.graphics.openSponsorsFolder()
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
                            model: backend.graphics.layoutPresets
                            textRole: "name"
                            currentIndex: Math.max(backend.graphics.layoutPresets.findIndex(function(item) { return item.key === backend.graphics.layoutPreset }), 0)
                            tip: i18n.tr("Preset in use")
                            onActivated: function(index) { backend.graphics.setLayoutPreset(backend.graphics.layoutPresets[index].key) }
                        }
                    }
                    TpText { Layout.fillWidth: true; role: "caption"; wrap: true; text: i18n.tr("Move and resize every graphic in your browser, with sample data: drag to move, mouse wheel to resize, then Save. Every source of this computer follows.") }
                    RowLayout {
                        Layout.fillWidth: true
                        TpButton {
                            objectName: "editGraphicsLayout"
                            Layout.fillWidth: true
                            accent: true
                            glyph: ""  // layers
                            text: i18n.tr("Edit Layout")
                            enabled: backend.graphics.graphicsUrl !== ""
                            onClicked: backend.graphics.editGraphicsLayout()
                        }
                        TpButton {  // reversible: done at once, Undo in the toast & Ctrl+Z (never confirmed)
                            objectName: "resetGraphicsLayout"
                            Layout.fillWidth: true
                            glyph: theme.glyphs.reset
                            text: i18n.tr("Reset Layout")
                            onClicked: backend.graphics.resetGraphicsLayout()
                        }
                    }
                    Line {}
                    // Source with some graphics only (another scene or source of the streaming software)
                    Heading { text: i18n.tr("Source with some graphics only") }
                    Flow {
                        Layout.fillWidth: true
                        spacing: theme.space2
                        Repeater {
                            model: backend.graphics.graphicNames
                            delegate: TpChip {
                                required property var modelData
                                size: "sm"
                                multi: true
                                text: modelData.name
                                selected: popup.partial.indexOf(modelData.key) >= 0
                                onClicked: popup.togglePartial(modelData.key)
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TpCombo {
                            id: partialPreset
                            Layout.fillWidth: true
                            model: [{ name: i18n.tr("Preset in use") }].concat(backend.graphics.layoutPresets)
                            textRole: "name"
                            tip: i18n.tr("Layout")
                        }
                        TpButton {
                            objectName: "copyPartialUrl"
                            glyph: theme.glyphs.copy
                            text: i18n.tr("Copy Address")
                            enabled: popup.partial.length > 0 && backend.graphics.graphicsUrl !== ""
                            onClicked: backend.graphics.copyPartialUrl(popup.partial, partialPreset.currentIndex > 0 ? backend.graphics.layoutPresets[partialPreset.currentIndex - 1].key : "")
                        }
                    }
                }
            }

            Line {}
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                TpButton {
                    Layout.fillWidth: true
                    glyph: ""  // contact
                    text: i18n.tr("Show Driver Card")
                    enabled: popup.graphics.card === true
                    onClicked: backend.graphics.showDriverCard()
                }
                TpButton {
                    objectName: "hideGraphicsButton"
                    Layout.fillWidth: true
                    glyph: popup.graphics.hidden ? "" : ""  // view, hide
                    checked: popup.graphics.hidden === true
                    text: popup.graphics.hidden ? i18n.tr("Show Graphics") : i18n.tr("Hide Graphics")
                    tip: (backend.keyLabels.director_hide_graphics || "") !== ""
                         ? i18n.tr("Hotkey %1").arg(backend.keyLabels.director_hide_graphics) : ""
                    onClicked: backend.graphics.setGraphic("hidden", !popup.graphics.hidden)
                }
            }
        }
    }
}
