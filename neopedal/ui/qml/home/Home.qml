import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Home page: app header (version, release notes, update), checks (what keeps overlays from showing right), state
// cards (game, overlay, preset, overlays, modules, last session), session debrief (each corner opens the
// telemetry viewer on it), driver card (ranks over time), quick access. Cards open their page: click, or Tab then
// Enter / Space. Cards follow page width in 1 to 3 columns, the page scrolls when taller than the window.
TpPage {
    id: page

    readonly property int columns: width >= theme.bpWide ? 3 : width >= theme.bpCompact ? 2 : 1
    readonly property bool compact: width < theme.bpCompact
    readonly property var header: backend.header
    readonly property var game: backend.game
    readonly property var overlay: backend.overlay
    readonly property var preset: backend.preset
    readonly property var counts: backend.counts
    readonly property var last: backend.lastSession
    readonly property var debrief: backend.debrief
    readonly property var driver: backend.driver
    readonly property var checks: backend.checks

    function levelColor(level) {
        return level === "error" ? theme.loss : level === "warning" ? theme.warning
             : level === "success" ? theme.gain : theme.accent
    }
    function levelGlyph(level) {
        return level === "success" ? "" : level === "info" ? "" : ""  // check, info, warning
    }
    function joined(parts) {
        return parts.filter(function(part) { return part !== undefined && part !== "" }).join(" · ")
    }
    function rankColor(row) {
        return (theme.dark ? row.color : row.lightColor) || theme.text
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight + theme.padPage * 2
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: column
            x: theme.padPage
            y: theme.padPage
            width: flick.width - theme.padPage * 2
            spacing: theme.space4

            // Header: app, version & game, update state, release notes
            Card {
                Layout.fillWidth: true
                implicitHeight: heroGrid.implicitHeight + theme.padCard * 2
                color: Qt.tint(theme.base, theme.tint(theme.accent, "subtle"))

                GridLayout {
                    id: heroGrid
                    anchors.fill: parent
                    anchors.margins: theme.padCard
                    columns: page.compact ? 1 : 2
                    columnSpacing: theme.space5
                    rowSpacing: theme.space3

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.space5
                        Image {
                            source: (theme.dark ? page.header.icon : page.header.iconLight) || ""
                            visible: status === Image.Ready
                            Layout.preferredWidth: Math.round(theme.em * 2.8)
                            Layout.preferredHeight: Layout.preferredWidth
                            sourceSize.height: Math.ceil(theme.em * 2.8 * Screen.devicePixelRatio)
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            smooth: true
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: theme.space1
                            Text {
                                Layout.fillWidth: true
                                text: page.header.app || ""
                                color: theme.text
                                font.pointSize: theme.fontTitle
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                Accessible.role: Accessible.Heading
                                Accessible.name: text
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: theme.space3
                                Text {
                                    text: page.joined([i18n.tr("Version") + " " + (page.header.version || ""), page.header.game || ""])
                                    color: theme.dimText
                                    textFormat: Text.PlainText
                                    height: Math.round(theme.em * 1.45)
                                    verticalAlignment: Text.AlignVCenter
                                }
                                Pill {
                                    visible: page.header.update === "available"
                                    text: i18n.tr("Update Available") + " · v" + (page.header.latest || "")
                                    solid: true
                                    dot: true
                                    pulsing: visible
                                }
                            }
                        }
                    }
                    RowLayout {
                        Layout.alignment: page.compact ? Qt.AlignLeft : Qt.AlignRight | Qt.AlignVCenter
                        spacing: theme.space3
                        TpButton {
                            text: i18n.tr("Release Notes")
                            tip: i18n.tr("What's new in this version")
                            onClicked: backend.showReleaseNotes()
                        }
                        TpButton {
                            readonly property string state: page.header.update || ""
                            glyph: ""  // sync
                            text: state === "checking" ? i18n.tr("Checking...")
                                : state === "available" ? i18n.tr("See Update") : i18n.tr("Check for Updates")
                            tip: page.header.tip || ""
                            enabled: state !== "checking"
                            accent: state === "available"
                            onClicked: backend.updateAction()
                        }
                    }
                }
            }

            // Checks: what keeps overlays from showing right, else ready
            HomeCard {
                id: checksCard
                Layout.fillWidth: true
                visible: page.checks.length > 0
                readonly property string level: page.checks.length > 0 ? page.checks[0].level : "info"
                glyph: page.levelGlyph(level)
                fallback: level === "success" ? "✓" : "!"
                tint: page.levelColor(level)
                title: i18n.tr("Checks")

                Repeater {
                    model: page.checks
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Rectangle {  // level strip: told by icon & text too, never by color alone
                            Layout.fillHeight: true
                            Layout.preferredWidth: Math.max(2, Math.round(theme.em * 0.2))
                            radius: width / 2
                            color: page.levelColor(modelData.level)
                        }
                        Icon {
                            glyph: page.levelGlyph(modelData.level)
                            fallback: modelData.level === "success" ? "✓" : modelData.level === "info" ? "i" : "!"
                            color: page.levelColor(modelData.level)
                            Layout.alignment: Qt.AlignTop
                            Layout.topMargin: theme.space1
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: modelData.title
                                color: theme.text
                                font.weight: Font.DemiBold
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: modelData.text
                                color: theme.dimText
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                            }
                        }
                        TpButton {
                            visible: modelData.actionText !== ""
                            text: modelData.actionText
                            size: "sm"
                            Layout.alignment: Qt.AlignVCenter
                            onClicked: backend.runCheck(modelData.action)
                        }
                    }
                }
            }

            // State cards
            GridLayout {
                Layout.fillWidth: true
                columns: page.columns
                columnSpacing: theme.space4
                rowSpacing: theme.space4
                uniformCellWidths: true

                HomeCard {  // game & session
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    glyph: ""  // game controller
                    fallback: "G"
                    title: i18n.tr("Game")
                    clickable: true
                    tip: i18n.tr("API settings of the game")
                    onOpened: backend.openGameSettings()
                    trailing: [
                        GameLogo { source: page.game.trackLogo || ""; boxWidth: theme.em * 3; boxHeight: theme.em * 1.2 },
                        GameLogo { source: page.game.brandLogo || ""; boxWidth: theme.em * 3; boxHeight: theme.em * 1.2 }
                    ]
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.space3
                        TpPulseDot {
                            width: Math.round(theme.em * 0.6)
                            color: page.game.running ? theme.gain : theme.dimText
                            pulsing: page.game.running === true
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Text {
                            Layout.fillWidth: true
                            text: page.game.name || ""
                            color: theme.text
                            font.pointSize: theme.fontSubtitle
                            font.weight: Font.DemiBold
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: (page.game.track || "") !== ""
                              ? page.joined([page.game.track, page.game.session, page.game.place, page.game.lap])
                              : (page.game.status || "")
                        color: theme.dimText
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                    }
                }

                HomeCard {  // overlay lock & display options
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    glyph: page.overlay.locked ? "" : ""  // lock, unlock
                    fallback: page.overlay.locked ? "L" : "U"
                    title: i18n.tr("Overlay")
                    clickable: true
                    tip: i18n.tr("Open overlays")
                    onOpened: backend.openPage("widget")
                    Text {
                        Layout.fillWidth: true
                        text: page.overlay.locked ? i18n.tr("Locked") : i18n.tr("Unlocked")
                        color: theme.text
                        font.pointSize: theme.fontSubtitle
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: page.overlay.locked === false
                        text: i18n.tr("Drag overlays to move them")
                        color: theme.dimText
                        wrapMode: Text.WordWrap
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: theme.space2
                        visible: page.overlay.autoHide === true || page.overlay.vr === true
                        Pill { visible: page.overlay.autoHide === true; text: i18n.tr("Auto Hide"); size: "sm" }
                        Pill { visible: page.overlay.vr === true; text: i18n.tr("VR Compatibility"); size: "sm" }
                    }
                    actions: TpButton {
                        text: page.overlay.locked ? i18n.tr("Unlock Overlay") : i18n.tr("Lock Overlay")
                        accent: true
                        size: "sm"
                        onClicked: backend.toggleLock()
                    }
                }

                HomeCard {  // preset loaded, switch to another one
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    glyph: ""  // library
                    fallback: "P"
                    title: i18n.tr("Preset")
                    clickable: true
                    tip: i18n.tr("Open presets")
                    onOpened: backend.openPage("preset")
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Text {
                            Layout.fillWidth: true
                            text: page.preset.name || ""
                            color: theme.text
                            font.pointSize: theme.fontSubtitle
                            font.weight: Font.DemiBold
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                        }
                        Pill {
                            visible: page.preset.locked === true
                            text: i18n.tr("Locked")
                            glyph: ""  // lock
                            tint: theme.dimText
                            size: "sm"
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: page.preset.autoLoad ? i18n.tr("Primary preset loads automatically")
                                                   : i18n.tr("Primary preset auto load off")
                        color: theme.dimText
                        wrapMode: Text.WordWrap
                    }
                    actions: TpButton {
                        id: switchButton
                        text: i18n.tr("Switch Preset")
                        glyph: ""  // chevron down
                        size: "sm"
                        tip: i18n.tr("Load another preset")
                        onClicked: {
                            presetMenu.rows = backend.presetList()
                            presetMenu.popup(switchButton, 0, switchButton.height)
                        }
                    }
                }

                HomeCard {  // overlays enabled
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    glyph: ""  // view all
                    fallback: "O"
                    title: i18n.tr("Overlays")
                    clickable: true
                    tip: i18n.tr("Open overlays")
                    onOpened: backend.openPage("widget")
                    CountLine { value: page.counts.overlays || 0; total: page.counts.overlayTotal || 0 }
                }

                HomeCard {  // modules enabled
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    glyph: ""  // processing
                    fallback: "M"
                    title: i18n.tr("Module")
                    clickable: true
                    tip: i18n.tr("Open modules")
                    onOpened: backend.openPage("module")
                    CountLine { value: page.counts.modules || 0; total: page.counts.moduleTotal || 0 }
                }

                HomeCard {  // last driven session
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: (page.last.track || "") !== ""
                    glyph: ""  // history
                    fallback: "H"
                    title: i18n.tr("Last Session")
                    clickable: true
                    tip: i18n.tr("Driver stats of this track & car")
                    onOpened: backend.openLastSession()
                    trailing: [
                        GameLogo { source: page.last.trackLogo || ""; boxWidth: theme.em * 3; boxHeight: theme.em * 1.2 },
                        GameLogo { source: page.last.brandLogo || ""; boxWidth: theme.em * 3; boxHeight: theme.em * 1.2 }
                    ]
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Text {
                            Layout.fillWidth: true
                            text: page.last.track || ""
                            color: theme.text
                            font.pointSize: theme.fontSubtitle
                            font.weight: Font.DemiBold
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                        }
                        Pill {
                            visible: (page.last.result || "") !== ""
                            text: page.last.result || ""
                            size: "sm"
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: page.joined([page.last.vehicle, page.last.session,
                                           page.last.best ? i18n.tr("Best") + " " + page.last.best : "", page.last.date])
                        color: theme.dimText
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                    }
                }

                HomeCard {  // debrief of last session
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.columnSpan: Math.min(2, page.columns)
                    visible: page.debrief.figures !== undefined
                    glyph: ""  // area chart
                    fallback: "R"
                    title: i18n.tr("Session Debrief")
                    clickable: page.debrief.canOpen === true
                    tip: i18n.tr("Open telemetry")
                    onOpened: backend.openDebrief()
                    Flow {
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Text {
                            text: (page.debrief.best || "") !== "" ? i18n.tr("Best") + " " + page.debrief.best : (page.debrief.track || "")
                            color: theme.text
                            font.pointSize: theme.fontSubtitle
                            font.weight: Font.DemiBold
                            textFormat: Text.PlainText
                            font.features: { "tnum": 1 }
                        }
                        Pill {
                            visible: page.debrief.personal === "new"
                            text: page.debrief.personalText || ""
                            glyph: ""  // star
                            tint: theme.gain
                        }
                        Text {
                            visible: page.debrief.personal === "slower"
                            text: page.debrief.personalText || ""
                            color: theme.dimText
                            textFormat: Text.PlainText
                            height: Math.round(theme.em * 1.45)
                            verticalAlignment: Text.AlignVCenter
                            font.features: { "tnum": 1 }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: (page.debrief.figures || []).join(" · ")
                        color: theme.dimText
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        font.features: { "tnum": 1 }
                    }
                    TpSectionLabel {
                        Layout.fillWidth: true
                        Layout.topMargin: theme.space2
                        visible: (page.debrief.tips || []).length > 0
                        text: i18n.tr("Work on") + " · " + (page.debrief.against || "")
                    }
                    Repeater {
                        model: page.debrief.tips || []
                        CornerTipRow {}
                    }
                    ColumnLayout {  // lap time goal of driver stats page
                        id: goalBlock
                        Layout.fillWidth: true
                        Layout.topMargin: theme.space2
                        visible: (page.debrief.goal || {}).goal !== undefined
                        spacing: theme.space2
                        readonly property var goal: page.debrief.goal || {}
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.space3
                            Icon {
                                glyph: ""  // target
                                fallback: "◎"
                                color: goalBlock.goal.state === "reached" ? theme.gain : theme.accent
                            }
                            Text {
                                text: i18n.tr("Goal") + " " + (goalBlock.goal.goal || "")
                                color: theme.text
                                font.weight: Font.DemiBold
                                font.features: { "tnum": 1 }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: goalBlock.goal.state === "reached" ? "✓ " + i18n.tr("reached") : (goalBlock.goal.gap || "")
                                color: goalBlock.goal.state === "reached" ? theme.gain : theme.dimText
                                font.weight: goalBlock.goal.state === "reached" ? Font.DemiBold : Font.Normal
                                font.features: { "tnum": 1 }
                                elide: Text.ElideRight
                            }
                            Text {
                                text: goalBlock.goal.percent || ""
                                visible: text !== ""
                                color: theme.dimText
                                font.features: { "tnum": 1 }
                            }
                        }
                        TpMeter {
                            Layout.fillWidth: true
                            visible: (goalBlock.goal.ratio === undefined ? -1 : goalBlock.goal.ratio) >= 0
                            value: Math.max(goalBlock.goal.ratio || 0, 0)
                            tint: goalBlock.goal.state === "reached" ? theme.gain : theme.accent
                            name: i18n.tr("Goal")
                        }
                    }
                    actions: TpButton {
                        visible: page.debrief.canOpen === true
                        text: i18n.tr("Open Telemetry")
                        glyph: ""  // area chart
                        size: "sm"
                        onClicked: backend.openDebrief()
                    }
                }

                HomeCard {  // driver: ranks, badge, race record
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.columnSpan: page.columns === 2 ? 2 : 1
                    visible: page.driver.name !== undefined
                    glyph: ""  // contact
                    fallback: "D"
                    title: i18n.tr("Driver")
                    clickable: true
                    tip: i18n.tr("Open driver stats")
                    onOpened: backend.openDriverStats()
                    Text {
                        Layout.fillWidth: true
                        text: page.driver.name || ""
                        color: theme.text
                        font.pointSize: theme.fontSubtitle
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: page.driver.identity || ""
                        color: theme.dimText
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                    }
                    Repeater {
                        model: page.driver.ranks || []
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: theme.space1
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: theme.space3
                                Text {
                                    text: modelData.label
                                    color: theme.dimText
                                    font.pointSize: theme.fontSmall
                                    elide: Text.ElideRight
                                    Layout.preferredWidth: theme.em * 6.5
                                }
                                Text {
                                    text: modelData.value
                                    color: page.rankColor(modelData)
                                    font.weight: Font.DemiBold
                                }
                                TpMeter {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: theme.em * 2
                                    Layout.alignment: Qt.AlignVCenter
                                    value: modelData.progress
                                    tint: page.rankColor(modelData)
                                    name: modelData.label
                                }
                                Text {
                                    text: modelData.progressText
                                    color: theme.text
                                    font.pointSize: theme.fontSmall
                                    font.features: { "tnum": 1 }
                                }
                                Text {  // change since previous rank: arrow & sign, not color alone
                                    visible: modelData.change !== ""
                                    text: (modelData.changeTone > 0 ? "▲ " : "▼ ") + modelData.change
                                    color: modelData.changeTone > 0 ? theme.gain : theme.loss
                                    font.pointSize: theme.fontCaption
                                    font.features: { "tnum": 1 }
                                }
                            }
                            HomeRankLine {
                                Layout.fillWidth: true
                                visible: (modelData.chart || []).length > 1
                                points: modelData.chart || []
                                tint: page.rankColor(modelData)
                                label: modelData.label
                            }
                        }
                    }
                    RowLayout {  // game badge in its color
                        readonly property var badge: page.driver.badge || {}
                        visible: (badge.name || "") !== ""
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Image {
                            source: parent.badge.icon || ""
                            visible: status === Image.Ready
                            Layout.preferredWidth: Math.round(theme.em * 1.3)
                            Layout.preferredHeight: Layout.preferredWidth
                            sourceSize.height: Math.ceil(theme.em * 1.3 * Screen.devicePixelRatio)
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                        }
                        Text {
                            Layout.fillWidth: true
                            text: parent.badge.name || ""
                            color: (theme.dark ? parent.badge.color : parent.badge.lightColor) || theme.text
                            font.weight: Font.DemiBold
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                        }
                    }
                    Flow {  // race record of results files
                        Layout.fillWidth: true
                        visible: (page.driver.figures || []).length > 0
                        spacing: theme.space5
                        Repeater {
                            model: page.driver.figures || []
                            Column {
                                required property var modelData
                                Text {
                                    text: modelData.value
                                    color: theme.text
                                    font.weight: Font.DemiBold
                                    font.features: { "tnum": 1 }
                                }
                                Text {
                                    text: modelData.label
                                    color: theme.dimText
                                    font.pointSize: theme.fontCaption
                                }
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: page.driver.note || ""
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                    }
                    Repeater {  // other game accounts of this computer
                        model: page.driver.others || []
                        Text {
                            required property var modelData
                            Layout.fillWidth: true
                            text: modelData.name + ": " + page.joined(modelData.ranks.map(function(rank) {
                                return rank.label + " " + rank.value
                            }).concat([modelData.badge.name || ""])) + " (" + modelData.when + ")"
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            // Quick access: tools, pages & actions chosen by the user (Customize, or right-click)
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: theme.space2
                spacing: theme.space3
                TpSectionLabel { text: i18n.tr("Quick Access") }
                TpButton {
                    flat: true
                    size: "xs"
                    text: i18n.tr("Customize...")
                    tip: i18n.tr("Add, remove or reorder quick access buttons")
                    onClicked: backend.customizeQuick()
                }
                Item { Layout.fillWidth: true }
            }
            GridLayout {
                id: quickGrid
                Layout.fillWidth: true
                columns: page.columns === 1 ? 1 : page.columns === 2 ? 3 : 5
                columnSpacing: theme.space3
                rowSpacing: theme.space3
                uniformCellWidths: true
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: function(point) { quickMenu.popup() }
                }
                Repeater {
                    model: backend.quick
                    TpButton {
                        required property var modelData
                        Layout.fillWidth: true
                        glyph: modelData.glyph
                        fallback: modelData.letter
                        text: modelData.label
                        tip: modelData.shortcut !== "" ? modelData.label + "  " + modelData.shortcut : ""
                        onClicked: backend.runQuick(modelData.key)
                    }
                }
                Text {
                    visible: backend.quick.length === 0
                    Layout.fillWidth: true
                    text: i18n.tr("No quick access button: use Customize... to add tools, pages or actions.")
                    color: theme.dimText
                    wrapMode: Text.WordWrap
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: theme.space2
                text: i18n.tr("Tip: press Ctrl+K to find any widget, option, tool or preset. Drop a preset or plugin file on this window to import it.")
                color: theme.dimText
                font.pointSize: theme.fontSmall
                wrapMode: Text.WordWrap
            }
        }
    }

    // Overlays or modules enabled: count, total & share bar
    component CountLine: ColumnLayout {
        id: countLine
        property int value: 0
        property int total: 0
        Layout.fillWidth: true
        spacing: theme.space2
        Text {
            Layout.fillWidth: true
            text: i18n.trm(countLine.value + " / " + countLine.total + " enabled")
            color: theme.text
            font.pointSize: theme.fontSubtitle
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            elide: Text.ElideRight
        }
        TpMeter {
            Layout.fillWidth: true
            value: countLine.total > 0 ? countLine.value / countLine.total : 0
            name: i18n.tr("Enabled")
        }
    }

    // Corner to work on: label, time lost, likely cause; click or Enter opens the telemetry viewer on it
    component CornerTipRow: Rectangle {
        id: tipRow
        required property var modelData
        Layout.fillWidth: true
        implicitHeight: tipLine.implicitHeight + theme.space2 * 2
        radius: theme.radiusMd
        color: tipArea.containsMouse ? theme.hover : "transparent"
        activeFocusOnTab: true
        Keys.onReturnPressed: backend.openCorner(modelData.index)
        Keys.onEnterPressed: backend.openCorner(modelData.index)
        Keys.onSpacePressed: backend.openCorner(modelData.index)
        Accessible.role: Accessible.Button
        Accessible.name: modelData.label + " " + modelData.loss + " " + modelData.cause
        Accessible.onPressAction: backend.openCorner(modelData.index)
        RowLayout {
            id: tipLine
            anchors.fill: parent
            anchors.leftMargin: theme.space2
            anchors.rightMargin: theme.space2
            spacing: theme.space3
            Text {
                text: tipRow.modelData.label
                color: theme.text
                font.weight: Font.DemiBold
                textFormat: Text.PlainText
            }
            Text {
                text: tipRow.modelData.loss
                color: theme.tone("loss")
                font.features: { "tnum": 1 }
            }
            Text {
                Layout.fillWidth: true
                text: tipRow.modelData.cause
                color: theme.dimText
                textFormat: Text.PlainText
                elide: Text.ElideRight
            }
            Icon {
                glyph: ""  // chevron right
                fallback: "›"
                color: theme.dimText
                size: theme.em * 0.8
            }
        }
        MouseArea {
            id: tipArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: backend.openCorner(tipRow.modelData.index)
            ToolTip.visible: containsMouse
            ToolTip.text: i18n.tr("Open this corner in telemetry")
            ToolTip.delay: theme.tipDelay
        }
        FocusRing { visible: tipRow.activeFocus }
    }

    // Presets of the preset card, newest first: click loads one
    TpMenu {
        id: presetMenu
        property var rows: []
        Instantiator {
            model: presetMenu.rows
            delegate: TpMenuItem {
                required property var modelData
                text: modelData.name
                checkable: true
                checked: modelData.loaded
                enabled: !modelData.loaded
                onTriggered: backend.loadPreset(modelData.file)
            }
            onObjectAdded: function(index, object) { presetMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { presetMenu.removeItem(object) }
        }
        MenuSeparator {}
        TpMenuItem {
            text: i18n.tr("All Presets...")
            onTriggered: backend.openPage("preset")
        }
    }

    TpMenu {
        id: quickMenu
        TpMenuItem {
            text: i18n.tr("Customize Quick Access...")
            onTriggered: backend.customizeQuick()
        }
    }
}
