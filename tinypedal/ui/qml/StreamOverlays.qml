import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Stream overlays page: browser sources for OBS Studio, Streamlabs, XSplit, vMix... Server switch & status,
// addresses to copy (whole layout, race results with its options, each overlay), where each overlay is shown
// (screen & stream, stream only, screen only), server settings. Sources shown now are marked live.
TpPage {
    id: page

    readonly property bool wide: width > theme.em * 66
    readonly property bool on: backend.enabled && backend.running

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
        spacing: theme.em * 0.7
        Rectangle {
            implicitWidth: Math.round(theme.em * 2.4)
            implicitHeight: implicitWidth
            radius: theme.em * 0.5
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.14)
            Icon { anchors.centerIn: parent; glyph: source.glyph; color: theme.accent }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.1
            RowLayout {
                spacing: theme.em * 0.5
                Text { text: source.title; color: theme.text; font.weight: Font.DemiBold }
                LiveMark { visible: source.live }
            }
            Text {
                Layout.fillWidth: true
                text: source.detail
                color: theme.dimText
                font.pointSize: theme.fontPoint * 0.9
                wrapMode: Text.WordWrap
            }
        }
        TpButton {
            glyph: ""  // copy
            text: source.showText ? i18n.tr("Copy Address") : ""
            tip: source.url
            enabled: source.active
            onClicked: backend.copy(source.url)
        }
        TpButton {
            glyph: ""  // open in new window
            flat: true
            tip: i18n.tr("Open in browser")
            enabled: source.active
            onClicked: backend.openInBrowser(source.url)
        }
    }
    // Source shown now in streaming software: pulsing dot
    component LiveMark: Rectangle {
        implicitHeight: liveText.implicitHeight + theme.em * 0.2
        implicitWidth: liveText.implicitWidth + theme.em * 1.6
        radius: height / 2
        color: Qt.rgba(theme.loss.r, theme.loss.g, theme.loss.b, 0.16)
        Rectangle {
            id: liveDot
            x: theme.em * 0.45
            anchors.verticalCenter: parent.verticalCenter
            width: theme.em * 0.45
            height: width
            radius: width / 2
            color: theme.loss
            SequentialAnimation on opacity {
                // A few pulses when state starts or page shows again, then still: no endless redraw
                running: liveDot.visible && pageState.active
                loops: 3
                onRunningChanged: if (!running) liveDot.opacity = 1
                NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
            }
        }
        Text {
            id: liveText
            anchors.left: liveDot.right
            anchors.leftMargin: theme.em * 0.3
            anchors.verticalCenter: parent.verticalCenter
            text: i18n.tr("LIVE")
            color: theme.loss
            font.pointSize: theme.fontPoint * 0.72
            font.weight: Font.Bold
        }
    }
    component SectionTitle: Text {
        color: theme.text
        font.weight: Font.DemiBold
        font.pointSize: theme.fontPoint * 1.05
    }
    component OptionLabel: Text {
        color: theme.dimText
        font.pointSize: theme.fontPoint * 0.9
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.em * 0.7
        spacing: theme.em * 0.6

        // Header: status, sources page, server switch
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.em * 0.6
            Icon { glyph: ""; color: theme.accent; size: theme.em * 1.3 }  // streaming
            Text {
                text: i18n.tr("Stream Overlays")
                color: theme.text
                font.weight: Font.DemiBold
                font.pointSize: theme.fontPoint * 1.25
            }
            Rectangle {
                id: statusPill
                readonly property color tone: !backend.enabled ? theme.dimText : !backend.running ? theme.loss
                                            : backend.watchingCount > 0 ? theme.gain : theme.accent
                implicitHeight: Math.round(theme.em * 2.0)
                implicitWidth: statusText.implicitWidth + theme.em * 2.4
                radius: height / 2
                color: Qt.rgba(tone.r, tone.g, tone.b, 0.12)
                border.width: 1
                border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.4)
                Behavior on color { ColorAnimation { duration: 250 } }
                Rectangle {
                    id: statusDot
                    x: theme.em * 0.75
                    anchors.verticalCenter: parent.verticalCenter
                    width: theme.em * 0.55
                    height: width
                    radius: width / 2
                    color: statusPill.tone
                    SequentialAnimation on opacity {
                        // A few pulses when state starts or page shows again, then still: no endless redraw
                        running: backend.watchingCount > 0 && pageState.active
                        loops: 3
                        onRunningChanged: if (!running) statusDot.opacity = 1
                        NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    id: statusText
                    anchors.left: statusDot.right
                    anchors.leftMargin: theme.em * 0.45
                    anchors.verticalCenter: parent.verticalCenter
                    text: backend.statusText
                    color: theme.text
                    font.weight: Font.DemiBold
                }
            }
            Item { Layout.fillWidth: true }
            TpButton {
                glyph: ""  // open in new window
                text: page.wide ? i18n.tr("Sources Page") : ""
                tip: i18n.tr("Every source in a browser page, to test them")
                flat: true
                enabled: page.on
                onClicked: backend.openInBrowser(backend.indexUrl)
            }
            TpSwitch {
                text: i18n.tr("Enabled")
                checked: backend.enabled
                onToggled: backend.setEnabled(checked)
            }
        }

        Text {
            Layout.fillWidth: true
            text: i18n.tr("Add these addresses as Browser sources in OBS Studio, Streamlabs, XSplit or vMix: transparent background, overlays exactly as on screen, also with the game in exclusive fullscreen.")
            color: theme.dimText
            wrapMode: Text.WordWrap
        }

        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: scroll.availableWidth
                spacing: theme.em * 0.6
                opacity: backend.enabled ? 1 : 0.55
                Behavior on opacity { NumberAnimation { duration: 200 } }

                // Layout & race results
                Card {
                    Layout.fillWidth: true
                    implicitHeight: sourcesColumn.implicitHeight + theme.em * 1.6
                    ColumnLayout {
                        id: sourcesColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: theme.em * 0.8
                        spacing: theme.em * 0.8
                        SectionTitle { text: i18n.tr("Sources") }
                        SourceRow {
                            Layout.fillWidth: true
                            glyph: ""  // layers
                            title: i18n.tr("Layout")
                            detail: i18n.tr("Every overlay shown on stream, at its place on screen.") + "  "
                                    + i18n.tr("Browser source size") + ": " + backend.screenText
                            url: backend.layoutUrl
                            live: backend.layoutLive
                            showText: page.wide
                            active: page.on
                        }
                        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: theme.border; opacity: 0.5 }
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
                            Layout.leftMargin: theme.em * 3.1
                            spacing: theme.em * 0.8
                            RowLayout {
                                spacing: theme.em * 0.4
                                OptionLabel { text: i18n.tr("Session") }
                                TpSegmented {
                                    options: [i18n.tr("Race"), i18n.tr("Qualifying"), i18n.tr("Any")]
                                    currentIndex: backend.resultsSessionIndex
                                    onActivated: function(index) { backend.setResultsSession(index) }
                                }
                            }
                            RowLayout {
                                spacing: theme.em * 0.4
                                OptionLabel { text: i18n.tr("Classes") }
                                TpSegmented {
                                    options: [i18n.tr("All Classes"), i18n.tr("Class by class")]
                                    currentIndex: backend.resultsClassIndex
                                    onActivated: function(index) { backend.setResultsClass(index) }
                                }
                            }
                            RowLayout {
                                spacing: theme.em * 0.4
                                OptionLabel { text: i18n.tr("Cars per page") }
                                TpCombo {
                                    implicitWidth: theme.em * 5
                                    model: backend.resultsRowsChoices
                                    currentIndex: backend.resultsRowsIndex
                                    onActivated: function(index) { backend.setResultsRows(index) }
                                }
                            }
                            RowLayout {
                                spacing: theme.em * 0.4
                                OptionLabel { text: i18n.tr("Page time") }
                                TpCombo {
                                    implicitWidth: theme.em * 5
                                    model: backend.resultsCycleChoices
                                    currentIndex: backend.resultsCycleIndex
                                    onActivated: function(index) { backend.setResultsCycle(index) }
                                }
                            }
                        }
                    }
                }

                // Each overlay: where shown, address
                Card {
                    Layout.fillWidth: true
                    implicitHeight: overlaysColumn.implicitHeight + theme.em * 1.6
                    ColumnLayout {
                        id: overlaysColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: theme.em * 0.8
                        spacing: theme.em * 0.3
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: theme.em * 0.5
                            SectionTitle { text: i18n.tr("Overlays") }
                            Text {
                                text: backend.overlayCount
                                color: theme.dimText
                                font.features: { "tnum": 1 }
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                Layout.maximumWidth: page.width * 0.5
                                text: i18n.tr("Stream only: hidden on your screen while overlays are locked.")
                                color: theme.dimText
                                font.pointSize: theme.fontPoint * 0.88
                                elide: Text.ElideRight
                            }
                        }
                        Text {
                            visible: backend.overlayCount === 0
                            text: i18n.tr("No overlay enabled: enable overlays on the Overlays page.")
                            color: theme.dimText
                        }
                        Repeater {
                            model: backend.overlayModel
                            delegate: Rectangle {
                                id: row
                                required property int index
                                required property string key
                                required property string label
                                required property int visibility
                                required property string sizeText
                                required property bool live
                                required property bool shown
                                Layout.fillWidth: true
                                implicitHeight: Math.round(theme.em * 2.8)
                                radius: theme.em * 0.45
                                color: rowArea.containsMouse ? theme.hover
                                     : index % 2 ? Qt.rgba(theme.text.r, theme.text.g, theme.text.b, theme.dark ? 0.025 : 0.03)
                                     : "transparent"
                                MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: theme.em * 0.5
                                    anchors.rightMargin: theme.em * 0.3
                                    spacing: theme.em * 0.6
                                    Text {
                                        Layout.fillWidth: true
                                        text: row.label
                                        color: row.visibility === 2 ? theme.dimText : theme.text
                                        elide: Text.ElideRight
                                    }
                                    LiveMark { visible: row.live }
                                    Text {
                                        Layout.preferredWidth: theme.em * 6
                                        horizontalAlignment: Text.AlignRight
                                        text: row.sizeText
                                        color: theme.dimText
                                        font.pointSize: theme.fontPoint * 0.88
                                        font.features: { "tnum": 1 }
                                    }
                                    TpSegmented {
                                        options: [i18n.tr("Screen & Stream"), i18n.tr("Stream Only"), i18n.tr("Screen Only")]
                                        currentIndex: row.visibility
                                        maxWidth: page.wide ? 0 : page.width * 0.45
                                        onActivated: function(index) { backend.setVisibility(row.key, index) }
                                    }
                                    TpButton {
                                        glyph: ""  // copy
                                        flat: true
                                        tip: i18n.tr("Copy Address") + (row.sizeText !== "" ? "  (" + i18n.tr("Browser source size") + ": " + row.sizeText + ")" : "")
                                        enabled: page.on && row.visibility !== 2
                                        onClicked: backend.copy(backend.overlayUrl(row.key))
                                    }
                                    TpButton {
                                        glyph: ""  // open in new window
                                        flat: true
                                        tip: i18n.tr("Open in browser")
                                        enabled: page.on && row.visibility !== 2
                                        onClicked: backend.openInBrowser(backend.overlayUrl(row.key))
                                    }
                                }
                            }
                        }
                    }
                }

                // Server settings
                Card {
                    Layout.fillWidth: true
                    implicitHeight: settingsColumn.implicitHeight + theme.em * 1.6
                    ColumnLayout {
                        id: settingsColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: theme.em * 0.8
                        spacing: theme.em * 0.6
                        SectionTitle { text: i18n.tr("Server") }
                        Flow {
                            Layout.fillWidth: true
                            spacing: theme.em * 1.2
                            RowLayout {
                                spacing: theme.em * 0.4
                                OptionLabel { text: i18n.tr("Port") }
                                NumberField {
                                    implicitWidth: theme.em * 5.5
                                    value: backend.port
                                    minimum: 1024
                                    maximum: 65535
                                    tip: i18n.tr("Server port (default 8339)")
                                    onEdited: function(value) { backend.setPort(Math.round(value)) }
                                }
                            }
                            RowLayout {
                                spacing: theme.em * 0.4
                                OptionLabel { text: i18n.tr("Images per second") }
                                TpSegmented {
                                    options: ["15", "30", "60"]
                                    currentIndex: backend.frameRateIndex
                                    onActivated: function(index) { backend.setFrameRate(index) }
                                }
                            }
                            TpSwitch {
                                text: i18n.tr("Another computer (LAN)")
                                tip: i18n.tr("Sources for a streaming PC on your local network")
                                checked: backend.lanAccess
                                onToggled: backend.setLanAccess(checked)
                            }
                            TpButton {
                                glyph: ""  // refresh
                                text: i18n.tr("New Access Token")
                                tip: i18n.tr("Every address gets a new token: addresses copied before stop working (address shown on stream by mistake)")
                                onClicked: backend.newToken()
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: backend.lanText !== ""
                            text: i18n.tr("Addresses for another computer") + ":  " + backend.lanText
                            color: theme.dimText
                            wrapMode: Text.WordWrap
                            font.features: { "tnum": 1 }
                        }
                    }
                }
            }
        }
    }

    // Copied address, new token, port unavailable: a few seconds
    Rectangle {
        id: toast
        property bool shown: false
        anchors.horizontalCenter: parent.horizontalCenter
        y: shown ? parent.height - height - theme.em * 1.2 : parent.height + theme.em
        width: Math.min(toastRow.implicitWidth + theme.em * 2.4, page.width - theme.em * 4)
        height: toastRow.implicitHeight + theme.em * 1.1
        radius: theme.em * 0.8
        color: theme.raised
        border.width: 1
        border.color: theme.border
        opacity: shown ? 1 : 0
        visible: opacity > 0
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Timer { id: toastTimer; interval: 4000; onTriggered: toast.shown = false }
        Connections {
            target: backend
            function onNoticeChanged() { toast.shown = true; toastTimer.restart() }
        }
        MouseArea { anchors.fill: parent; onClicked: toast.shown = false }
        Row {
            id: toastRow
            anchors.centerIn: parent
            spacing: theme.em * 0.6
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                glyph: ""  // check
                color: theme.gain
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, page.width - theme.em * 7)
                text: backend.noticeText
                color: theme.text
                wrapMode: Text.WordWrap
            }
        }
    }
}
