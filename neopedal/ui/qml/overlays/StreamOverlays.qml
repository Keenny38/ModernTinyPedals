import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Stream overlays page: browser sources for OBS Studio, Streamlabs, XSplit, vMix... Server switch & status,
// addresses to copy (whole layout, race results with its options, each overlay), where each overlay is shown
// (screen & stream, stream only, screen only), server settings. Sources shown now are marked live.
// Addresses hold the access token: never shown in tooltips or read by screen readers (copy them instead).
TpPage {
    id: page

    readonly property bool wide: width > theme.em * 66  // content-tuned: button texts of source rows fit
    readonly property bool on: backend.enabled && backend.running
    readonly property var searchWords: overlaySearch.text.toLowerCase().split(" ").filter(function(word) { return word !== "" })

    // Overlay row matching every word of the overlays search
    function matches(label) {
        var text = label.toLowerCase()
        for (var i = 0; i < searchWords.length; ++i)
            if (text.indexOf(searchWords[i]) < 0)
                return false
        return true
    }
    function isFind(event) {
        return event.key === Qt.Key_F && event.modifiers === Qt.ControlModifier
    }
    // Layout reset undone with Ctrl+Z, as the Undo of its toast (a focused text field keeps its own Ctrl+Z)
    Shortcut {
        sequences: [StandardKey.Undo]
        enabled: pageState.active && backend.canUndoReset
        onActivated: backend.undoResetLayout()
    }
    // Ctrl+F searches the overlays of this page: taken before the app's own Ctrl+F shortcut
    Keys.onShortcutOverride: function(event) {
        if (isFind(event))
            event.accepted = true
    }
    Keys.onPressed: function(event) {
        if (isFind(event)) {
            overlaySearch.forceActiveFocus()
            overlaySearch.selectAll()
            event.accepted = true
        }
    }

    // Address of a source: title, detail, live mark, copy & open buttons
    component SourceRow: RowLayout {
        id: source
        property string glyph: ""
        property string title: ""
        property string detail: ""
        property string url: ""
        property bool live: false
        property bool showText: true  // button texts (wide page)
        property bool active: true  // server running
        spacing: theme.padCard
        TpIconTile {
            Layout.preferredWidth: size
            Layout.preferredHeight: size
            Layout.alignment: Qt.AlignTop
            size: Math.round(theme.em * 2.4)
            glyph: source.glyph
            fallbackText: source.title
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.1
            RowLayout {
                Layout.fillWidth: true
                spacing: theme.space3
                Text {
                    Layout.fillWidth: true
                    Layout.maximumWidth: implicitWidth
                    text: source.title
                    textFormat: Text.PlainText
                    color: theme.text
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                LiveMark { visible: source.live }
                Item { Layout.fillWidth: true }
            }
            TpText {
                Layout.fillWidth: true
                role: "label"
                text: source.detail
                color: theme.dimText
                elide: Text.ElideNone
                wrapMode: Text.WordWrap
            }
        }
        TpButton {
            glyph: theme.glyphs.copy
            fallback: i18n.tr("Copy")
            text: source.showText ? i18n.tr("Copy Address") : ""
            tip: i18n.tr("Copy Address")
            enabled: source.active
            onClicked: backend.copy(source.url)
        }
        TpButton {
            glyph: theme.glyphs.openExternal
            fallback: "↗"
            flat: true
            tip: i18n.tr("Open in browser")
            enabled: source.active
            onClicked: backend.openInBrowser(source.url)
        }
    }
    // Source shown now in streaming software: red pill with a pulsing dot & text (never color alone)
    component LiveMark: Pill {
        text: i18n.tr("LIVE")
        tint: theme.loss
        dot: true
        pulsing: visible
        size: "sm"
    }
    component OptionLabel: TpText {
        role: "label"
        color: theme.dimText
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space4

        // Header: title, status, sources page, server switch
        TpPageHeader {  // no title: the host's title bar shows it
            title: ""
            Pill {
                id: statusPill
                readonly property color tone: !backend.enabled ? theme.dimText : !backend.running ? theme.loss
                                            : backend.watchingCount > 0 ? theme.gain : theme.accent
                Layout.alignment: Qt.AlignVCenter
                text: backend.statusText
                tint: tone
                dot: true
                pulsing: backend.watchingCount > 0
                maximumTextWidth: page.width * 0.3
            }
            TpButton {
                glyph: theme.glyphs.openExternal
                fallback: "↗"
                text: page.wide ? i18n.tr("Sources Page") : ""
                tip: i18n.tr("Every source in a browser page, to test them")
                flat: true
                enabled: page.on
                onClicked: backend.openInBrowser(backend.indexUrl)
            }
            TpSwitch {
                objectName: "streamEnabledSwitch"
                text: backend.enabled ? i18n.tr("Enabled") : i18n.tr("Disabled")
                tip: i18n.tr("Stream Overlays")
                checkable: false  // follows backend (banner button, port taken): the binding stays
                checked: backend.enabled
                onClicked: backend.setEnabled(!backend.enabled)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Stream Overlays")
                Accessible.checked: backend.enabled
            }
        }

        Text {
            Layout.fillWidth: true
            text: i18n.tr("Add these addresses as Browser sources in OBS Studio, Streamlabs, XSplit or vMix: transparent background, overlays exactly as on screen, also with the game in exclusive fullscreen.")
            color: theme.dimText
            wrapMode: Text.WordWrap
        }

        // Server off: sources stay empty (settings below can still be changed)
        TpNotice {
            visible: !backend.enabled
            tone: theme.accent
            glyph: ""  // info
            fallback: "i"
            text: i18n.tr("Stream overlays are off: the addresses below show nothing until you turn them on.")
            actionText: i18n.tr("Turn On Server")
            onAction: backend.setEnabled(true)
        }
        // Sources empty now: no overlay shown (auto hide outside sessions...), and why
        TpNotice {
            visible: backend.enabled && backend.hiddenText !== ""
            text: backend.hiddenText
        }

        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: scroll.availableWidth
                spacing: theme.space4

                // Layout & race results
                TpSectionCard {
                    Layout.fillWidth: true
                    title: i18n.tr("Sources")
                    spacing: theme.space5

                    SourceRow {
                        Layout.fillWidth: true
                        glyph: ""  // layers
                        title: i18n.tr("Layout")
                        detail: i18n.tr("Every overlay shown on stream, at its place on screen.") + "  "
                                + backend.layoutSizeText
                        url: backend.layoutUrl
                        live: backend.layoutLive
                        showText: page.wide
                        active: page.on
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.leftMargin: theme.em * 3.1  // content-tuned: under the source texts (icon tile + gap)
                        spacing: theme.space3
                        RowLayout {
                            spacing: theme.space3
                            OptionLabel { text: i18n.tr("Format") }
                            TpSegmented {
                                name: i18n.tr("Format")
                                options: [i18n.tr("16:9 (screen centre)"), i18n.tr("Whole screen")]
                                currentIndex: backend.layoutFormatIndex
                                onActivated: function(index) { backend.setLayoutFormat(index) }
                            }
                        }
                        TpButton {
                            objectName: "editStreamLayout"
                            glyph: ""  // layers
                            text: i18n.tr("Edit Layout")
                            tip: i18n.tr("Place overlays on this layout in your browser, apart from their place on screen (for example overlays of the sides of an ultrawide screen)")
                            enabled: page.on
                            onClicked: backend.editLayout()
                        }
                        TpButton {  // reversible: done at once, Undo in the toast & Ctrl+Z (never confirmed)
                            objectName: "resetStreamLayout"
                            glyph: theme.glyphs.reset
                            fallback: "↺"
                            flat: true
                            tip: i18n.tr("Overlays of this layout back to their place on screen")
                            enabled: page.on && backend.layoutPlaced
                            onClicked: backend.resetLayout()
                        }
                    }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border }
                    SourceRow {
                        Layout.fillWidth: true
                        glyph: ""  // flag
                        title: i18n.tr("Race Results")
                        detail: i18n.tr("Classification of the last session, from the results files of the game, updated when a new one is written.") + "  "
                                + i18n.tr("Browser source size") + ": 1920 × 1080"
                        url: backend.resultsUrl
                        showText: page.wide
                        active: page.on
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.leftMargin: theme.em * 3.1  // content-tuned: under the source texts (icon tile + gap)
                        spacing: theme.space5
                        RowLayout {
                            spacing: theme.space3
                            OptionLabel { text: i18n.tr("Session") }
                            TpSegmented {
                                name: i18n.tr("Session")
                                options: [i18n.tr("Race"), i18n.tr("Qualifying"), i18n.tr("Any")]
                                currentIndex: backend.resultsSessionIndex
                                onActivated: function(index) { backend.setResultsSession(index) }
                            }
                        }
                        RowLayout {
                            spacing: theme.space3
                            OptionLabel { text: i18n.tr("Classes") }
                            TpSegmented {
                                name: i18n.tr("Classes")
                                options: [i18n.tr("All Classes"), i18n.tr("Class by class")]
                                currentIndex: backend.resultsClassIndex
                                onActivated: function(index) { backend.setResultsClass(index) }
                            }
                        }
                        RowLayout {
                            spacing: theme.space3
                            OptionLabel { text: i18n.tr("Cars per page") }
                            TpCombo {
                                implicitWidth: theme.em * 5
                                model: backend.resultsRowsChoices
                                currentIndex: backend.resultsRowsIndex
                                tip: i18n.tr("Cars per page")
                                onActivated: function(index) { backend.setResultsRows(index) }
                            }
                        }
                        RowLayout {
                            spacing: theme.space3
                            OptionLabel { text: i18n.tr("Page time") }
                            TpCombo {
                                implicitWidth: theme.em * 5
                                model: backend.resultsCycleChoices
                                currentIndex: backend.resultsCycleIndex
                                tip: i18n.tr("Page time")
                                onActivated: function(index) { backend.setResultsCycle(index) }
                            }
                        }
                    }
                }

                // Each overlay: where shown, address
                TpSectionCard {
                    Layout.fillWidth: true
                    title: i18n.tr("Overlays")
                    count: String(backend.overlayCount)
                    spacing: theme.space2

                    TpSearchField {
                        id: overlaySearch
                        objectName: "streamOverlaySearch"
                        Layout.fillWidth: true
                        Layout.maximumWidth: theme.em * 22
                        searchDelay: 0  // rows filtered at once
                        placeholderText: i18n.tr("Search overlays") + "   Ctrl+F"
                        Accessible.name: i18n.tr("Search overlays")
                    }
                    Text {
                        Layout.fillWidth: true
                        text: i18n.tr("Stream only: hidden on your screen while overlays are locked.")
                        color: theme.dimText
                        font.pointSize: theme.fontSmall
                        wrapMode: Text.WordWrap
                    }
                    TpStateView {
                        compact: true
                        empty: backend.overlayCount === 0
                        glyph: ""  // monitor
                        title: i18n.tr("No overlay enabled: enable overlays on the Overlays page.")
                    }
                    TpStateView {
                        objectName: "streamNoMatch"
                        compact: true
                        empty: backend.overlayCount > 0 && page.searchWords.length > 0
                               && !backend.overlayLabels.some(function(label) { return page.matches(label) })
                        glyph: ""  // search
                        title: i18n.tr("No overlay matches the search")
                        secondaryActionText: i18n.tr("Clear Search")
                        onSecondaryAction: overlaySearch.clearSearch()
                    }
                    Repeater {
                        model: backend.overlayModel
                        delegate: Item {
                            id: row
                            required property int index
                            required property string key
                            required property string label
                            required property int visibility
                            required property string sizeText
                            required property bool live
                            required property bool shown
                            Layout.fillWidth: true
                            visible: page.matches(row.label)
                            implicitHeight: Math.round(theme.row)
                            TpListRow {
                                id: rowBack
                                anchors.fill: parent
                                hovered: rowArea.containsMouse
                                striped: row.index % 2 === 1 && page.searchWords.length === 0  // rows hidden by the search: no stripes
                            }
                            MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: theme.space3
                                anchors.rightMargin: theme.space2
                                spacing: theme.space4
                                Text {
                                    Layout.fillWidth: true
                                    text: row.label
                                    textFormat: Text.PlainText
                                    color: row.visibility === 2 ? theme.dimOn(rowBack.color) : theme.text
                                    elide: Text.ElideRight
                                }
                                LiveMark { visible: row.live }
                                Text {
                                    Layout.preferredWidth: theme.em * 6
                                    horizontalAlignment: Text.AlignRight
                                    text: row.sizeText
                                    textFormat: Text.PlainText
                                    color: theme.dimOn(rowBack.color)
                                    font.pointSize: theme.fontSmall
                                    font.features: { "tnum": 1 }
                                }
                                TpSegmented {
                                    name: row.label
                                    options: [i18n.tr("Screen & Stream"), i18n.tr("Stream Only"), i18n.tr("Screen Only")]
                                    currentIndex: row.visibility
                                    maxWidth: page.wide ? 0 : page.width * 0.45
                                    onActivated: function(index) { backend.setVisibility(row.key, index) }
                                }
                                TpButton {
                                    glyph: theme.glyphs.copy
                                    fallback: i18n.tr("Copy")
                                    flat: true
                                    size: "sm"
                                    tip: i18n.tr("Copy Address") + (row.sizeText !== "" ? "  (" + i18n.tr("Browser source size") + ": " + row.sizeText + ")" : "")
                                    enabled: page.on && row.visibility !== 2
                                    onClicked: backend.copy(backend.overlayUrl(row.key))
                                }
                                TpButton {
                                    glyph: theme.glyphs.openExternal
                                    fallback: "↗"
                                    flat: true
                                    size: "sm"
                                    tip: i18n.tr("Open in browser")
                                    enabled: page.on && row.visibility !== 2
                                    onClicked: backend.openInBrowser(backend.overlayUrl(row.key))
                                }
                            }
                        }
                    }
                }

                // Server settings
                TpSectionCard {
                    Layout.fillWidth: true
                    title: i18n.tr("Server")
                    spacing: theme.space4

                    Flow {
                        Layout.fillWidth: true
                        spacing: theme.space6
                        RowLayout {
                            spacing: theme.space3
                            OptionLabel { text: i18n.tr("Port") }
                            NumberField {
                                implicitWidth: theme.em * 5.5
                                value: backend.port
                                minimum: 1024
                                maximum: 65535
                                showRange: true
                                tip: i18n.tr("Server port (default 8339)")
                                onEdited: function(value) { backend.setPort(Math.round(value)) }
                            }
                        }
                        RowLayout {
                            spacing: theme.space3
                            OptionLabel { text: i18n.tr("Images per second") }
                            TpSegmented {
                                name: i18n.tr("Images per second")
                                options: ["15", "30", "60"]
                                currentIndex: backend.frameRateIndex
                                onActivated: function(index) { backend.setFrameRate(index) }
                            }
                        }
                        TpSwitch {
                            text: i18n.tr("Show overlays while spectating")
                            tip: i18n.tr("Overlays shown & updated while you spectate a session or watch a replay, as long as a layout or overlay source is on air (hidden otherwise by Auto Hide)")
                            objectName: "streamSpectatingSwitch"
                            checkable: false  // follows backend
                            checked: backend.spectating
                            onClicked: backend.setSpectating(!backend.spectating)
                        }
                        TpSwitch {
                            text: i18n.tr("Another computer (LAN)")
                            tip: i18n.tr("Sources for a streaming PC on your local network")
                            objectName: "streamLanSwitch"
                            checkable: false  // follows backend
                            checked: backend.lanAccess
                            onClicked: backend.setLanAccess(!backend.lanAccess)
                        }
                        TpButton {
                            objectName: "newTokenButton"
                            glyph: theme.glyphs.refresh
                            text: i18n.tr("New Access Token")
                            tip: i18n.tr("Every address gets a new token: addresses copied before stop working (address shown on stream by mistake)")
                            onClicked: newTokenDialog.open()
                            TpConfirmDialog {
                                id: newTokenDialog
                                objectName: "newTokenDialog"
                                title: i18n.tr("Make a new access token?")
                                text: i18n.tr("Every browser source already set up in your streaming software stops working until you copy its new address into it.")
                                acceptText: i18n.tr("New Access Token")
                                onAccepted: backend.newToken()
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: backend.lanText !== ""
                        text: i18n.tr("Addresses for another computer") + ":  " + backend.lanText
                        textFormat: Text.PlainText
                        color: theme.dimText
                        wrapMode: Text.WordWrap
                        font.features: { "tnum": 1 }
                    }
                }
            }
        }
    }

    // Dialogs & toasts asked by the backend (confirmations, alerts, messages with Undo)
    TpDialogHost {}
}
