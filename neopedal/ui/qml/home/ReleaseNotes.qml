import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// What's New page: version header & version menu (any version of the local changelog), search, contents chips
// (versions or groups), notes as one list (version headers, group headings, cards, folds), download progress
// & install actions (secondary ones in a "⋯" menu when room runs out: the main button keeps its text).
// Screenshots open in the viewer (arrows browse, Esc closes). Ctrl+F searches. Try turns an overlay on, Undo in
// the toast.
TpPage {
    id: page

    function jumpTo(key) {
        const row = backend.rowOf(key)
        if (row >= 0)
            notes.positionViewAtIndex(row, ListView.Beginning)
    }
    function isFind(event) {
        return event.key === Qt.Key_F && event.modifiers === Qt.ControlModifier
    }

    // Ctrl+F searches the notes: taken before the app's own Ctrl+F shortcut (a QML Shortcut never fires in this
    // page: the app window has the keyboard)
    Keys.onShortcutOverride: function(event) {
        if (isFind(event))
            event.accepted = true
    }
    Keys.onPressed: function(event) {
        if (isFind(event)) {
            search.forceActiveFocus()
            search.selectAll()
            event.accepted = true
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space3

        // Version & its state, release date under it, version menu (title cut first on narrow windows)
        TpPageHeader {
            title: backend.title
            subtitle: backend.detail
            status: [
                Pill {
                    visible: backend.chip !== ""
                    text: backend.chip
                    tint: backend.chipNew ? theme.gain : theme.accent
                }
            ]
            TpCombo {
                id: versionMenu
                Layout.preferredWidth: theme.em * 11
                visible: count > 1
                model: backend.versions
                textRole: "label"
                tip: i18n.tr("Show the notes of another version")
                currentIndex: {
                    const choices = backend.versions
                    for (let index = 0; index < choices.length; index++)
                        if (choices[index].key === backend.view)
                            return index
                    return 0
                }
                onActivated: function(index) { backend.showVersion(backend.versions[index].key) }
            }
        }
        // Preference (kept out of the action row: room for the main button)
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            Item { Layout.fillWidth: true }
            TpSwitch {
                objectName: "showAfterUpdateSwitch"
                checkable: false
                checked: backend.showAfterUpdate
                text: i18n.tr("Show after each update")
                tip: i18n.tr("What's new is shown once at the first start of a new version")
                onClicked: backend.setShowAfterUpdate(!backend.showAfterUpdate)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Show after each update")
                Accessible.checked: backend.showAfterUpdate
            }
        }

        TpSearchField {
            id: search
            objectName: "notesSearch"
            Layout.fillWidth: true
            placeholderText: i18n.tr("Search the notes") + "   Ctrl+F"
            onSearchChanged: function(text) { backend.setSearch(text) }
            onExitField: notes.forceActiveFocus()
        }

        Flow {
            Layout.fillWidth: true
            visible: backend.contents.length > 0 && !backend.searching
            spacing: theme.space2
            Repeater {
                model: backend.contents
                TpChip {
                    required property var modelData
                    text: modelData.label
                    size: "sm"
                    tip: i18n.tr("Go to this part")
                    onClicked: page.jumpTo(modelData.key)
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: notes
                anchors.fill: parent
                clip: true
                model: backend.notes
                spacing: theme.space3
                boundsBehavior: Flickable.StopAtBounds
                activeFocusOnTab: true
                cacheBuffer: Math.max(height, 0)  // screenshots of the next screen loaded once the visible ones are
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Loader {
                    id: row
                    required property string key
                    required property string kind
                    required property string title
                    required property string subtitle
                    required property var items
                    required property var overlays
                    required property bool expanded
                    required property int count
                    required property int index
                    width: ListView.view.width - theme.space2
                    sourceComponent: kind === "card" ? cardRow : kind === "fold" ? foldRow
                                   : kind === "version" ? versionRow : groupRow

                    Component {
                        id: cardRow
                        ReleaseCard {
                            title: row.title
                            items: row.items
                            overlays: row.overlays
                            onImageOpened: function(url) { viewer.show(url) }
                        }
                    }
                    Component {
                        id: groupRow
                        Text {
                            topPadding: theme.space2
                            text: row.title
                            textFormat: Text.StyledText
                            color: theme.text
                            font.pointSize: theme.fontHeading
                            font.weight: Font.DemiBold
                            wrapMode: Text.Wrap
                            Accessible.role: Accessible.Heading
                            Accessible.name: text
                        }
                    }
                    Component {
                        id: versionRow
                        ColumnLayout {
                            spacing: 0
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.bottomMargin: theme.space3
                                visible: row.index > 0
                                implicitHeight: 1
                                color: theme.border
                            }
                            RowLayout {
                                spacing: theme.space3
                                Text {
                                    text: row.title
                                    textFormat: Text.PlainText
                                    color: theme.accent
                                    font.pointSize: theme.fontLarge
                                    font.weight: Font.DemiBold
                                    Accessible.role: Accessible.Heading
                                    Accessible.name: text
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: row.subtitle
                                    textFormat: Text.PlainText
                                    color: theme.dimText
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                    Component {
                        id: foldRow
                        RowLayout {
                            spacing: theme.space2
                            TpButton {
                                flat: true
                                size: "sm"
                                glyph: row.expanded ? "" : ""  // chevron down, chevron right
                                fallback: row.expanded ? "▾" : "▸"
                                text: row.title
                                tip: row.expanded ? i18n.tr("Hide") : i18n.tr("Show")
                                Accessible.role: Accessible.CheckBox
                                Accessible.checked: row.expanded
                                onClicked: backend.toggleFold(row.key)
                            }
                            Pill {
                                text: "" + row.count
                                tint: theme.dimText
                                size: "sm"
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: row.subtitle !== ""
                                text: row.subtitle
                                textFormat: Text.PlainText
                                color: theme.dimText
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                Keys.onPressed: function(event) {
                    if (search.routeTyped(event))
                        event.accepted = true
                }
            }

            TpStateView {
                anchors.centerIn: parent
                empty: notes.count === 0
                glyph: backend.searching ? "" : ""  // search, list
                title: backend.searching ? i18n.tr("Nothing found in these notes") : i18n.tr("No release notes for this version.")
                text: backend.searching ? i18n.tr("Check spelling, or try fewer or other words.") : ""
                actionText: backend.searching ? i18n.tr("Clear Search") : ""
                onAction: { search.text = ""; backend.setSearch("") }
            }
        }

        TpNotice {
            Layout.fillWidth: true
            visible: backend.portableNote !== ""
            tone: theme.accent
            glyph: ""  // info
            fallback: "i"
            text: backend.portableNote
        }

        // Download of installer: progress & cancel
        RowLayout {
            Layout.fillWidth: true
            visible: backend.downloading
            spacing: theme.space3
            Text {
                text: backend.progressText
                textFormat: Text.PlainText
                color: theme.text
                font.features: { "tnum": 1 }
            }
            TpSpinner { visible: backend.progress < 0 }  // size not known yet
            TpMeter {
                id: progress
                Layout.fillWidth: true
                visible: backend.progress >= 0
                value: Math.max(backend.progress, 0)
                name: i18n.tr("Download progress")
                Accessible.description: backend.progressText
            }
            TpButton {
                text: i18n.tr("Cancel Download")
                enabled: !backend.cancelling
                onClicked: backend.cancelDownload()
            }
        }

        // Secondary actions (into a "⋯" menu when room runs out), then the main ones, never squeezed
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpToolbar {
                objectName: "releaseActions"
                Layout.fillWidth: true
                alignRight: false
                TpAction {
                    name: "githubButton"
                    text: i18n.tr("View On GitHub")
                    glyph: ""  // globe
                    fallback: "↗"
                    priority: 1
                    onTriggered: backend.openGitHub()
                }
                TpAction {
                    name: "skipButton"
                    shown: backend.skipVisible
                    enabled: !backend.downloading
                    text: i18n.tr("Skip This Version")
                    tip: i18n.tr("Not shown again for this version, shown again for a newer one")
                    onTriggered: backend.skip()
                }
                onMenuClosed: notes.forceActiveFocus()
            }
            TpButton {
                objectName: "closeButton"
                Layout.minimumWidth: implicitWidth
                visible: backend.closeVisible
                text: backend.closeText
                onClicked: backend.close()
            }
            TpButton {
                objectName: "installButton"
                Layout.minimumWidth: implicitWidth
                visible: backend.installVisible
                enabled: !backend.downloading
                accent: true
                text: backend.installText
                tip: backend.installTip
                onClicked: backend.install()
            }
        }
    }

    ReleaseViewer {
        id: viewer
        anchors.fill: parent
    }

    // Dialogs & toasts asked by the backend (confirmations, alerts, messages with Undo)
    TpDialogHost {}
}
